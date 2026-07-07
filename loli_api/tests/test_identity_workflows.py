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
    assert wf["202"]["class_type"] == "GroundingDinoSAMSegment"
    assert wf["202"]["inputs"]["image"] == ["108", 0]          # segment the raw source
    assert wf["119"]["inputs"]["mask"] == ["202", 1]           # grow/blur the clothing MASK
    assert wf["204"]["class_type"] == "InvertMask"             # present for the background path
    # SAM3 must be gone.
    classes = {n["class_type"] for n in wf.values()}
    assert not any("SAM3" in c for c in classes)


def test_prepare_background_inverts_person_mask():
    wf = prepare_background_workflow(_load("test_final_API.json"), "src.png", "a beach at sunset")
    # Background segments the person...
    assert "person" in wf["202"]["inputs"]["prompt"]
    # ...and inpaints the INVERTED mask (the background region), keeping the subject.
    assert wf["119"]["inputs"]["mask"] == ["204", 0]
    assert wf["204"]["inputs"]["mask"] == ["202", 1]


def test_prepare_outfit_keeps_clothing_mask():
    wf = prepare_outfit_workflow(_load("test_final_API.json"), "src.png", "a red dress")
    # Outfit default keeps the clothing mask feeding the grow/blur node directly.
    assert wf["119"]["inputs"]["mask"] == ["202", 1]


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
