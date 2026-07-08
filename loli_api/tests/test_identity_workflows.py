"""
Static guards for the identity-locked edit workflows.

These assert the wiring that guarantees a character's face/body/hair cannot drift
across batch edits:

  - Outfit/background re-diffuse ONLY inside a mask; everything else is composited
    back from the original encode via InpaintModelConditioning (node 121).
  - The mask comes from GroundingDINO+SAM (node 202), hole-filled (213) before
    branching; background inverts the hole-filled mask (204).
  - Pose repose is followed by a ReActor face-swap (node 200) that locks the
    hero's face onto the reposed body before the image is saved.

If someone re-plumbs these graphs and breaks the identity path, these fail fast
(offline, no GPU / RunPod needed).
"""
import json
from pathlib import Path

from api.v1.endpoints.outfit import prepare_outfit_workflow
from api.v1.endpoints.background import prepare_background_workflow

WF_DIR = Path(__file__).resolve().parent.parent / "workflows"


def _load(name):
    with open(WF_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Outfit / background template (test_final_API.json)
# ---------------------------------------------------------------------------
def test_outfit_template_has_identity_lock_chain():
    wf = _load("test_final_API.json")
    # The composite-back inpaint node is present and masked.
    assert wf["121"]["class_type"] == "InpaintModelConditioning"
    assert wf["121"]["inputs"]["mask"] == ["119", 0]
    assert wf["121"]["inputs"]["pixels"] == ["108", 0]  # inpaint over the ORIGINAL pixels
    # Sampler consumes the inpaint latent (Latent Switch select=3 -> node 121).
    assert wf["105"]["inputs"]["select"] == 3
    assert wf["105"]["inputs"]["latent_3"] == ["121", 2]
    assert wf["106"]["inputs"]["latent_image"] == ["105", 0]


def test_outfit_mask_source_is_grounding_dino_sam():
    wf = _load("test_final_API.json")
    assert wf["202"]["class_type"] == "GroundingDinoSAMSegment (segment anything)"
    assert wf["202"]["inputs"]["image"] == ["108", 0]          # segment the raw source
    assert wf["204"]["class_type"] == "InvertMask (segment anything)"  # background path
    # SAM3 must be gone.
    classes = {n["class_type"] for n in wf.values()}
    assert not any("SAM3" in c for c in classes)


def test_outfit_mask_is_person_region():
    """
    Node 202 must segment "person" — evidence-verified as the only mask that
    handles BOTH undressing and dressing a nude source (garment-term masks find
    nothing on a nude body and produce patchy garbage).
    """
    wf = _load("test_final_API.json")
    assert wf["202"]["inputs"]["prompt"] == "person"


def test_outfit_template_protects_head_via_server_mask():
    """
    Person mask minus the SERVER-COMPUTED head-protect mask (node 211, shipped
    per-request; YuNet detects the stylized hero faces that GroundingDINO and
    insightface miss). No on-worker face detection in the chain.
    """
    wf = _load("test_final_API.json")
    assert wf["211"]["class_type"] == "LoadImage"
    assert wf["212"]["class_type"] == "ImageToMask"
    assert wf["212"]["inputs"]["image"] == ["211", 0]
    assert wf["205"]["class_type"] == "MaskComposite"
    assert wf["205"]["inputs"]["operation"] == "subtract"
    assert wf["205"]["inputs"]["destination"] == ["213", 0]  # hole-filled person mask, not raw 202
    assert wf["205"]["inputs"]["source"] == ["212", 0]
    # The grow/blur node consumes the PROTECTED mask.
    assert wf["119"]["inputs"]["mask"] == ["205", 0]
    # The old on-worker DINO face segment must be gone.
    assert "203" not in wf


def test_outfit_template_fills_raw_mask_holes_before_branching():
    """
    Node 213 fills accidental internal gaps in SAM's raw person mask (202)
    BEFORE it branches to the head-subtract (205, outfit) and invert (204,
    background) paths — a fill_holes-ONLY pass (expand=0, blur_radius=0), so
    it does not touch the mask's outer boundary. Without this, a small
    unfilled hole in the segmentation (SAM missing a fold of fabric, a shadow,
    etc.) survives all the way to the composite-back (node 220) and shows up
    as a blurred patch of the STALE original image bleeding through mid-
    garment, since noise_mask=true + composite-back now take the mask's exact
    shape literally (an earlier noise_mask=false config didn't have this
    failure mode, because the whole frame was re-diffused regardless of mask
    shape).
    """
    wf = _load("test_final_API.json")
    assert wf["213"]["class_type"] == "GrowMaskWithBlur"
    assert wf["213"]["inputs"]["fill_holes"] is True
    assert wf["213"]["inputs"]["expand"] == 0
    assert wf["213"]["inputs"]["blur_radius"] == 0
    assert wf["213"]["inputs"]["mask"] == ["202", 1]  # consumes the RAW SAM mask
    # Both downstream branches consume the hole-filled mask, not raw 202.
    assert wf["205"]["inputs"]["destination"] == ["213", 0]  # outfit (head-subtract)
    assert wf["204"]["inputs"]["mask"] == ["213", 0]         # background (invert)


def test_outfit_template_mask_is_a_real_wall():
    """
    noise_mask MUST be true: the sampler only denoises the masked latent
    region. An earlier config (noise_mask=false) reduced the mask to a mere
    green-overlay hint and let the sampler re-diffuse the ENTIRE frame at
    denoise 0.8, which is what let outfit/background edits silently drift
    the face and change the whole image.
    """
    wf = _load("test_final_API.json")
    assert wf["121"]["inputs"]["noise_mask"] is True


def test_outfit_template_composites_back_onto_original_source():
    """
    Node 220 (ImageCompositeMasked) pastes the sampled decode (118) back onto
    the ORIGINAL source (108) using the same mask (119) that gated the
    sampler — so every pixel outside the feathered mask, including the face,
    is byte-identical to the source. This is the real identity guarantee now;
    ReActorFaceSwap (210) is kept in the graph but disabled, since a
    redundant face-swap on top of an exact composite only reintroduced a
    waxy, over-restored look.
    """
    wf = _load("test_final_API.json")
    assert wf["210"]["class_type"] == "ReActorFaceSwap"
    assert wf["210"]["inputs"]["enabled"] is False
    assert wf["220"]["class_type"] == "ImageCompositeMasked"
    assert wf["220"]["inputs"]["destination"] == ["108", 0]  # ORIGINAL pixels
    assert wf["220"]["inputs"]["source"] == ["118", 0]       # sampled/decoded pixels
    assert wf["220"]["inputs"]["mask"] == ["119", 0]         # same mask that gated the sampler
    assert wf["116"]["inputs"]["images"] == ["220", 0]       # SaveImage reads the composite


def test_prepare_background_inverts_person_mask():
    wf = prepare_background_workflow(_load("test_final_API.json"), "src.png", "a beach at sunset")
    # Background segments the person (single robust GroundingDINO term)...
    assert wf["202"]["inputs"]["prompt"] == "person"
    # ...and inpaints the INVERTED FULL-person mask (background region), keeping
    # the subject incl. face/hair composited back untouched.
    assert wf["119"]["inputs"]["mask"] == ["204", 0]
    assert wf["204"]["inputs"]["mask"] == ["213", 0]


def test_prepare_outfit_keeps_protected_person_mask():
    from models.enums import NudityLevel
    for level in (None, NudityLevel.LOW, NudityLevel.MEDIUM, NudityLevel.HIGH):
        wf = prepare_outfit_workflow(
            _load("test_final_API.json"), "src.png", "a red dress",
            nudity_level=level, head_mask_name="headmask_x.png",
        )
        # Every direction uses the head-protected person mask.
        assert wf["202"]["inputs"]["prompt"] == "person", f"{level}"
        assert wf["119"]["inputs"]["mask"] == ["205", 0], f"{level}"
        assert wf["211"]["inputs"]["image"] == "headmask_x.png", f"{level}"


def test_prepare_outfit_without_head_mask_falls_back_safely():
    """No staged mask -> hole-filled person mask (213, not raw 202) + node 211
    points at an existing file."""
    wf = prepare_outfit_workflow(_load("test_final_API.json"), "src.png", "a red dress")
    assert wf["119"]["inputs"]["mask"] == ["213", 0]
    assert wf["211"]["inputs"]["image"] == "src.png"


def test_prepare_background_keeps_node_211_valid():
    """Background never uses the head mask but LoadImage must validate."""
    wf = prepare_background_workflow(_load("test_final_API.json"), "src.png", "a beach")
    assert wf["211"]["inputs"]["image"] == "src.png"


def test_head_mask_service():
    """Fail-closed fallback box when no face; white feathered region when found."""
    import numpy as np
    import cv2
    from services import head_mask

    # Synthetic no-face image -> FAIL CLOSED: a conservative top-center fallback
    # box protects the head region (NOT an all-black mask, which would leave the
    # face editable and let the inpaint destroy it). found is still False so logs
    # stay accurate.
    blank = cv2.imencode(".png", np.full((240, 180, 3), 128, np.uint8))[1].tobytes()
    png, found = head_mask.build_head_mask(blank)
    m = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert not found and m.shape == (240, 180)
    assert int(m.max()) == 255                     # fallback box is present, not black
    assert 0.05 < (m > 127).mean() < 0.35          # a top-center head region, not the whole frame
    assert int(m[160:, :].max()) == 0              # ...and nothing protected in the bottom third

    # A real face (original pose ref backup, if present) -> white region.
    ref = Path(__file__).resolve().parent.parent / "assets" / "poses" / "pose_ref_standing_leaning.orig.png"
    if ref.exists():
        png, found = head_mask.build_head_mask(ref.read_bytes())
        m = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
        assert found and int(m.max()) == 255
        assert 0 < (m > 127).mean() < 0.25   # a head-sized region, not the frame


# ---------------------------------------------------------------------------
# Pose template (edit_pose_action.json)
# ---------------------------------------------------------------------------
def test_pose_template_face_swaps_before_save():
    wf = _load("edit_pose_action.json")
    assert wf["200"]["class_type"] == "ReActorFaceSwap"
    # Hero face (node 109) swapped onto the reposed body (node 8 VAEDecode).
    assert wf["200"]["inputs"]["source_image"] == ["109", 0]
    assert wf["200"]["inputs"]["input_image"] == ["8", 0]
    # The SAVED image is the face-locked one, not the raw repose.
    assert wf["164"]["class_type"] == "SaveImage"
    assert wf["164"]["inputs"]["images"] == ["200", 0]


# ---------------------------------------------------------------------------
# Outfit V2 crop-and-stitch template (outfit_cropstitch_API.json)
# ---------------------------------------------------------------------------
from api.v1.endpoints import outfit as _outfit_mod
from api.v1.endpoints.outfit import _is_cropstitch_template, GARMENT_MODE_OUTFITS
from models.enums import OutfitType


def test_v2_template_is_crop_and_stitch():
    wf = _load("outfit_cropstitch_API.json")
    assert _is_cropstitch_template(wf)
    assert wf["235"]["class_type"] == "InpaintCropImproved"
    assert wf["238"]["class_type"] == "InpaintStitchImproved"


def test_v2_identity_is_stitched_back_pixel_exact():
    wf = _load("outfit_cropstitch_API.json")
    # The ONLY SaveImage reads the stitched image (crop pasted back onto original).
    saves = [k for k, n in wf.items() if n["class_type"] == "SaveImage"]
    assert saves == ["116"]
    assert wf["116"]["inputs"]["images"] == ["238", 0]
    # Stitch consumes the crop's stitcher (byte-exact outside the mask) + the decode.
    assert wf["238"]["inputs"]["stitcher"] == ["235", 0]
    assert wf["238"]["inputs"]["inpainted_image"] == ["118", 0]
    # No whole-frame re-diffusion escape hatches survive from V1.
    classes = {n["class_type"] for n in wf.values()}
    assert "ImageCompositeMasked" not in classes  # replaced by the stitch node
    assert "EmptyLatentImage" not in classes        # sampler works on the crop latent
    assert "DrawMaskOnImage" not in classes         # clean crop reference, no green hint


def test_v2_edit_is_confined_to_crop_minus_head():
    wf = _load("outfit_cropstitch_API.json")
    # Crop region = base mask MINUS the server head mask.
    assert wf["233"]["class_type"] == "MaskComposite"
    assert wf["233"]["inputs"]["operation"] == "subtract"
    assert wf["233"]["inputs"]["source"] == ["212", 0]      # head mask
    assert wf["212"]["inputs"]["image"] == ["211", 0]        # server-computed PNG
    assert wf["235"]["inputs"]["mask"] == ["233", 0]         # crop uses head-subtracted mask
    # Masked inpaint over the CROPPED pixels, soft edge via differential diffusion.
    assert wf["121"]["class_type"] == "InpaintModelConditioning"
    assert wf["121"]["inputs"]["noise_mask"] is True
    assert wf["121"]["inputs"]["pixels"] == ["235", 1]       # cropped_image, not full frame
    assert wf["237"]["class_type"] == "DifferentialDiffusion"
    assert wf["106"]["inputs"]["model"] == ["237", 0]


def test_v2_prepare_defaults_to_body_mode():
    wf = prepare_outfit_workflow(
        _load("outfit_cropstitch_API.json"), "src.png", "a red dress",
        seed=7, outfit=OutfitType.CROP_TOP_CARGO, head_mask_name="hm.png",
    )
    # BODY mode by default (GARMENT_MODE_OUTFITS is opt-in and starts empty).
    assert GARMENT_MODE_OUTFITS == set()
    assert wf["233"]["inputs"]["destination"] == ["213", 0]  # person base, not garment
    assert wf["211"]["inputs"]["image"] == "hm.png"
    assert wf["108"]["inputs"]["image"] == "src.png"
    assert wf["106"]["inputs"]["seed"] == 7


def test_v2_garment_mode_selects_clothes_mask():
    saved = set(_outfit_mod.GARMENT_MODE_OUTFITS)
    _outfit_mod.GARMENT_MODE_OUTFITS = {OutfitType.CROP_TOP_CARGO}
    try:
        wf = prepare_outfit_workflow(
            _load("outfit_cropstitch_API.json"), "src.png", "cargo set",
            seed=1, outfit=OutfitType.CROP_TOP_CARGO, head_mask_name="hm.png",
        )
        assert wf["233"]["inputs"]["destination"] == ["230", 1]  # ClothesSegment mask
        assert wf["230"]["class_type"] == "ClothesSegment"
    finally:
        _outfit_mod.GARMENT_MODE_OUTFITS = saved


def test_v2_no_head_mask_bypasses_subtraction():
    wf = prepare_outfit_workflow(
        _load("outfit_cropstitch_API.json"), "src.png", "x",
        seed=1, outfit=OutfitType.NAKED, head_mask_name=None,
    )
    # With no staged head mask, the crop reads the base mask directly (no bad subtract).
    assert wf["235"]["inputs"]["mask"] == ["213", 0]
    assert wf["211"]["inputs"]["image"] == "src.png"  # LoadImage stays valid
