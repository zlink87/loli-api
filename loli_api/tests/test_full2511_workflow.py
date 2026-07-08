"""
Tests for the Tier-A full Qwen-Image-Edit-2511 workflow
(outfit_cropstitch_2511full_API.json): it is a crop-and-stitch clone with only the
loader block swapped (all-in-one Rapid checkpoint -> native UNet+CLIP+VAE + realism/
NSFW LoRAs) and the sampler retuned for the non-distilled model. The shared
prepare_outfit_cropstitch_workflow must drive it with NO code change, and the
full-model sampler settings must survive preparation.
"""
import json
from pathlib import Path

from models.enums import OutfitType, NudityLevel
from api.v1.endpoints.outfit import prepare_outfit_workflow, _is_cropstitch_template

_WF = Path(__file__).resolve().parent.parent / "workflows" / "outfit_cropstitch_2511full_API.json"


def _template():
    with open(_WF, "r", encoding="utf-8") as f:
        return json.load(f)


def test_loader_block_swapped_to_full_2511():
    g = _template()
    assert "101" not in g  # all-in-one Rapid checkpoint removed
    assert g["301"]["class_type"] == "UNETLoader"
    assert g["302"]["class_type"] == "CLIPLoader" and g["302"]["inputs"]["type"] == "qwen_image"
    assert g["303"]["class_type"] == "VAELoader"
    # model chain: UNet -> realism LoRA -> NSFW LoRA -> DifferentialDiffusion -> KSampler
    assert g["304"]["inputs"]["model"] == ["301", 0]
    assert g["305"]["inputs"]["model"] == ["304", 0]
    assert g["237"]["inputs"]["model"] == ["305", 0]
    assert g["106"]["inputs"]["model"] == ["237", 0]


def test_no_dangling_references_to_removed_loader():
    g = _template()
    dangling = [
        f"{nid}.{k}"
        for nid, n in g.items()
        for k, v in n.get("inputs", {}).items()
        if isinstance(v, list) and len(v) == 2 and str(v[0]) == "101"
    ]
    assert dangling == [], f"references to removed node 101: {dangling}"


def test_is_detected_as_cropstitch_graph():
    assert _is_cropstitch_template(_template()) is True


def test_full_model_sampler_settings_survive_preparation():
    # Full (non-distilled) 2511 needs >20 steps / higher CFG, unlike the distilled
    # Rapid path (8 steps / cfg 1). The preparer only sets seed + denoise, so the
    # baked full-model steps/cfg must remain.
    wf = prepare_outfit_workflow(
        _template(), "src.png", "a red dress",
        seed=5, nudity_level=NudityLevel.LOW, outfit=OutfitType.COCKTAIL_DRESS,
        head_mask_name="hm.png", source_dressed=True,
    )
    s = wf["106"]["inputs"]
    assert s["steps"] >= 20
    assert s["cfg"] >= 2.0
    assert s["seed"] == 5
    assert s["denoise"] == 0.80  # preparer override (BODY/GARMENT)


def test_preparer_mask_mode_still_works_on_2511_graph():
    # GARMENT for a dressed opt-in outfit, BODY otherwise — same contract as V2.
    garment = prepare_outfit_workflow(
        _template(), "src.png", "x", seed=1, outfit=OutfitType.COCKTAIL_DRESS,
        head_mask_name="hm.png", source_dressed=True,
    )
    body = prepare_outfit_workflow(
        _template(), "src.png", "x", seed=1, outfit=OutfitType.COCKTAIL_DRESS,
        head_mask_name="hm.png", source_dressed=False,
    )
    assert garment["233"]["inputs"]["destination"] == ["230", 1]
    assert body["233"]["inputs"]["destination"] == ["213", 0]


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
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {fn.__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
