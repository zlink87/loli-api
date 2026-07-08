"""
Tests for GARMENT vs BODY mask-mode selection in the V2 crop-and-stitch outfit
graph. GARMENT mode (tight ClothesSegment mask, node 230) must engage ONLY when
the caller marks the source as dressed AND the target outfit is opt-in; every
other case falls back to the whole-BODY person mask (node 213) so a nude source
is never handed an empty garment crop (the safety guarantee behind the
`sourceDressed` API flag).
"""
import json
from pathlib import Path

from models.enums import OutfitType
from api.v1.endpoints.outfit import prepare_outfit_workflow, GARMENT_MODE_OUTFITS

_V2 = str(Path(__file__).resolve().parent.parent / "workflows" / "outfit_cropstitch_API.json")

GARMENT = ["230", 1]  # ClothesSegment mask (output 1)
BODY = ["213", 0]     # hole-filled whole-person mask


def _template():
    with open(_V2, "r", encoding="utf-8") as f:
        return json.load(f)


def _mask_base(**kw):
    # node 233 MaskComposite destination = the selected base mask before head-subtract
    wf = prepare_outfit_workflow(
        _template(), "src.png", "change outfit", head_mask_name="head.png", **kw
    )
    return wf["233"]["inputs"]["destination"]


def test_dressed_source_plus_optin_outfit_uses_garment():
    assert OutfitType.COCKTAIL_DRESS in GARMENT_MODE_OUTFITS
    assert _mask_base(outfit=OutfitType.COCKTAIL_DRESS, source_dressed=True) == GARMENT


def test_nude_source_never_uses_garment_even_for_optin_outfit():
    # The whole point of the flag: a nude/undressed source must fall back to BODY,
    # because ClothesSegment would find no clothing and yield an empty crop.
    assert _mask_base(outfit=OutfitType.COCKTAIL_DRESS, source_dressed=False) == BODY


def test_dressed_source_but_non_optin_outfit_uses_body():
    # Coverage-increasing / non-graduated targets stay BODY even on a dressed source.
    assert OutfitType.BIKINI not in GARMENT_MODE_OUTFITS
    assert _mask_base(outfit=OutfitType.BIKINI, source_dressed=True) == BODY


def test_default_source_dressed_is_false_uses_body():
    # Backward compat: callers that omit the flag keep the old BODY behavior.
    assert _mask_base(outfit=OutfitType.COCKTAIL_DRESS) == BODY


def test_no_outfit_uses_body():
    assert _mask_base(outfit=None, source_dressed=True) == BODY


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
