"""
WS-M — Cropstitch mask hardening.

Guards the hardened mask-chain parameters on the crop-and-stitch outfit graphs
(the forearm-seam / jaggy-mask fix) and the dress-mode-on-nude-source routing
(the "what mask reaches the inpaint on a bare body" audit).

Mask chain (identical node ids across all four graphs; only the model-loader
block, the SaveImage source, and the preview crop size differ):

    108 LoadImage (source)
    202 GroundingDinoSAMSegment  "person"      -> raw person mask
    213 GrowMaskWithBlur (fill holes)          -> BODY base   (inpaint path in BODY mode)
    230 ClothesSegment                         -> GARMENT base (inpaint path in GARMENT mode)
    211/212 head-protect mask (YuNet PNG -> MASK)
    233 MaskComposite subtract                 -> editable = (base selected by preparer) - head
    235 InpaintCropImproved                    -> crop the edit region to full res
    236 GrowMaskWithBlur (soften)              -> final soft inpaint mask (ALWAYS on the path)
    121 InpaintModelConditioning (noise_mask)  -> consumes node 236

Both grow nodes (213, 236) feed the inpaint mask — there is no auxiliary grow
node to leave un-hardened. 213 is path-active only in BODY mode (GARMENT mode
routes node 233's destination to 230 instead); 236 is path-active always.
"""
import json
from pathlib import Path

from models.enums import OutfitType
from api.v1.endpoints.outfit import (
    prepare_outfit_workflow,
    GARMENT_MODE_OUTFITS,
)

_WF_DIR = Path(__file__).resolve().parent.parent / "workflows"

# The three RENDER graphs kept in sync + the maskpreview graph.
RENDER_GRAPHS = [
    "outfit_cropstitch_2511full_API.json",
    "outfit_cropstitch_2511full_softlora_API.json",
    "outfit_cropstitch_API.json",
]
MASKPREVIEW_GRAPH = "outfit_cropstitch_maskpreview_API.json"
ALL_GRAPHS = RENDER_GRAPHS + [MASKPREVIEW_GRAPH]

# Hardened target values (WS-M deliverable 1).
CLOTHES_SEGMENT = {"process_res": 1024, "mask_blur": 4, "mask_offset": 2}   # node 230
GROW_BODY = {"expand": 8, "blur_radius": 6}                                 # node 213
GROW_SOFTEN = {"expand": 8, "blur_radius": 6}                              # node 236
CROP_BLEND = {"context_from_mask_extend_factor": 1.3, "mask_blend_pixels": 12}  # node 235


def _load(name: str) -> dict:
    with open(_WF_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Deliverable 1 — hardened mask-chain params on ALL four graphs.
# ---------------------------------------------------------------------------
def test_clothes_segment_hardened_on_all_graphs():
    """Node 230 ClothesSegment: 512->1024 res, +4 blur, +2 offset (less jaggy garment mask)."""
    for name in ALL_GRAPHS:
        n230 = _load(name)["230"]
        assert n230["class_type"] == "ClothesSegment", name
        for k, v in CLOTHES_SEGMENT.items():
            assert n230["inputs"][k] == v, f"{name} node230.{k}={n230['inputs'][k]} != {v}"


def test_body_base_grow_hardened_on_all_graphs():
    """Node 213 (BODY base, fill_holes): expand 0->8, blur 0->6. Feeds node 233 in BODY mode."""
    for name in ALL_GRAPHS:
        n213 = _load(name)["213"]
        assert n213["class_type"] == "GrowMaskWithBlur", name
        # Identity of node 213: fills the RAW SAM person mask.
        assert n213["inputs"]["fill_holes"] is True, name
        assert n213["inputs"]["mask"] == ["202", 1], name
        for k, v in GROW_BODY.items():
            assert n213["inputs"][k] == v, f"{name} node213.{k}={n213['inputs'][k]} != {v}"


def test_soften_grow_hardened_on_all_graphs():
    """Node 236 (final soften): expand 0->8, blur ->6. ALWAYS on the inpaint path (-> node 121)."""
    for name in ALL_GRAPHS:
        g = _load(name)
        n236 = g["236"]
        assert n236["class_type"] == "GrowMaskWithBlur", name
        # Identity of node 236: softens the CROPPED mask (from node 235, output 2).
        assert n236["inputs"]["fill_holes"] is False, name
        assert n236["inputs"]["mask"] == ["235", 2], name
        for k, v in GROW_SOFTEN.items():
            assert n236["inputs"][k] == v, f"{name} node236.{k}={n236['inputs'][k]} != {v}"
        # It is the FINAL inpaint mask: InpaintModelConditioning consumes node 236.
        assert g["121"]["inputs"]["mask"] == ["236", 0], name


def test_crop_context_and_blend_sane_for_bigger_soft_mask():
    """Node 235 InpaintCropImproved: context 1.2->1.3 (room for the wider soft mask) and
    blend 8/16->12 (softer stitch-back so the forearm seam blends)."""
    for name in ALL_GRAPHS:
        n235 = _load(name)["235"]
        assert n235["class_type"] == "InpaintCropImproved", name
        for k, v in CROP_BLEND.items():
            assert n235["inputs"][k] == v, f"{name} node235.{k}={n235['inputs'][k]} != {v}"
        # The soft mask (236) must not exceed the crop context room: context extension
        # (30%) must comfortably exceed the mask growth (expand 8 + blur 6 ~ 20px vs the
        # per-side extension). Guarded as a monotonic invariant, not a pixel calc.
        assert n235["inputs"]["context_from_mask_extend_factor"] >= 1.3, name


# ---------------------------------------------------------------------------
# Maskpreview stays in sync with the render mask chain (so a preview matches
# what the render graphs will actually segment/grow).
# ---------------------------------------------------------------------------
def test_maskpreview_mask_chain_matches_render_graphs():
    """The maskpreview graph's mask-chain nodes (230/213/236/235 params) are byte-identical
    to the render graphs — only the loader block, the SaveImage source, and the preview crop
    SIZE may differ."""
    ref = _load(RENDER_GRAPHS[0])
    prev = _load(MASKPREVIEW_GRAPH)
    for nid in ("230", "213", "236"):
        assert prev[nid]["inputs"] == ref[nid]["inputs"], f"maskpreview node {nid} drifted"
    # Node 235: the mask-shaping params match; only the preview output size is allowed to differ.
    for k in ("context_from_mask_extend_factor", "mask_blend_pixels", "mask_expand_pixels"):
        assert prev["235"]["inputs"][k] == ref["235"]["inputs"][k], f"maskpreview 235.{k} drifted"


def test_maskpreview_saves_the_editable_mask_not_the_edit():
    """The maskpreview graph outputs the editable mask (MaskToImage of node 233) so an operator
    can see the region the outfit step will repaint — the whole point of OUTFIT_DEBUG_SAVE_MASK."""
    g = _load(MASKPREVIEW_GRAPH)
    assert g["116"]["class_type"] == "SaveImage"
    assert g["116"]["inputs"]["images"] == ["240", 0]
    assert g["240"]["class_type"] == "MaskToImage"
    assert g["240"]["inputs"]["mask"] == ["233", 0]  # the editable region (base - head)


def test_render_graphs_still_stitch_the_edit():
    """Render graphs must NOT accidentally inherit the maskpreview's mask-only output: their
    SaveImage still reads the stitched edit (node 238)."""
    for name in RENDER_GRAPHS:
        g = _load(name)
        assert g["116"]["inputs"]["images"] == ["238", 0], name
        assert g["238"]["class_type"] == "InpaintStitchImproved", name


# ---------------------------------------------------------------------------
# Deliverable 2 — dress-mode-on-nude-source audit (CRITICAL).
#
# Verdict: on a nude source the batch flow leaves sourceDressed=False (scene_mapper
# never sets it; PipelineEditRequest defaults it False), so GARMENT mode's
# source_dressed conjunction is False and the preparer routes node 233's destination
# to the BODY (person) base [213,0] MINUS the head — NOT the ClothesSegment mask
# [230,1] (which finds nothing on bare skin). The mask that reaches the inpaint is
# therefore the torso/person region with the face composited-protected, never an
# empty/degenerate clothes mask.
# ---------------------------------------------------------------------------
def test_dress_class_outfit_on_nude_source_uses_body_mask_not_empty_clothes():
    """FLORAL_MAXI_DRESS IS garment-mode-eligible, yet on a NUDE source (source_dressed=False)
    the preparer must select the BODY person mask, never the ClothesSegment mask that would be
    empty on bare skin."""
    assert OutfitType.FLORAL_MAXI_DRESS in GARMENT_MODE_OUTFITS  # the tempting-but-wrong path
    for name in RENDER_GRAPHS + [MASKPREVIEW_GRAPH]:
        wf = prepare_outfit_workflow(
            _load(name), "nude_base.png", "dress her in a floral maxi dress",
            seed=1, outfit=OutfitType.FLORAL_MAXI_DRESS,
            head_mask_name="hm.png", source_dressed=False,  # nude base source
        )
        assert wf["233"]["inputs"]["destination"] == ["213", 0], name  # BODY/person mask
        assert wf["233"]["inputs"]["source"] == ["212", 0], name       # minus head (face-protected)
        assert wf["233"]["inputs"]["operation"] == "subtract", name


def test_garment_mode_still_engages_on_dressed_source():
    """The nude-source fix must not disable GARMENT mode for a genuinely DRESSED source: the same
    dress-class outfit with source_dressed=True routes to the tight ClothesSegment mask."""
    for name in RENDER_GRAPHS:
        wf = prepare_outfit_workflow(
            _load(name), "dressed.png", "swap her dress",
            seed=1, outfit=OutfitType.FLORAL_MAXI_DRESS,
            head_mask_name="hm.png", source_dressed=True,
        )
        assert wf["233"]["inputs"]["destination"] == ["230", 1], name  # ClothesSegment (garment)


if __name__ == "__main__":
    import sys

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
