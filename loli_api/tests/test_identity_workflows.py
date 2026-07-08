"""
Static guards for the identity-locked edit workflows.

These assert the wiring that guarantees a character's face/body/hair cannot drift
across batch edits:

  - Outfit/background re-diffuse ONLY inside a mask; everything else is composited
    back from the original encode via InpaintModelConditioning (node 121).
  - The mask comes from GroundingDINO+SAM (node 202); background inverts it (204).
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
    assert wf["205"]["inputs"]["destination"] == ["202", 1]
    assert wf["205"]["inputs"]["source"] == ["212", 0]
    # The grow/blur node consumes the PROTECTED mask.
    assert wf["119"]["inputs"]["mask"] == ["205", 0]
    # The old on-worker DINO face segment must be gone.
    assert "203" not in wf and "206" not in wf


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
    assert wf["204"]["inputs"]["mask"] == ["202", 1]


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
    """No staged mask -> raw person mask + node 211 points at an existing file."""
    wf = prepare_outfit_workflow(_load("test_final_API.json"), "src.png", "a red dress")
    assert wf["119"]["inputs"]["mask"] == ["202", 1]
    assert wf["211"]["inputs"]["image"] == "src.png"


def test_prepare_background_keeps_node_211_valid():
    """Background never uses the head mask but LoadImage must validate."""
    wf = prepare_background_workflow(_load("test_final_API.json"), "src.png", "a beach")
    assert wf["211"]["inputs"]["image"] == "src.png"


def test_head_mask_service():
    """Black mask when no face; white feathered region when a face is found."""
    import numpy as np
    import cv2
    from services import head_mask

    # Synthetic no-face image -> all-black mask, found=False.
    blank = cv2.imencode(".png", np.full((240, 180, 3), 128, np.uint8))[1].tobytes()
    png, found = head_mask.build_head_mask(blank)
    m = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert not found and m.shape == (240, 180) and int(m.max()) == 0

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
