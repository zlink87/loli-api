"""
Tests for WS3.2 "outfit application strength" plumbing:

  s1  prepare_outfit_cropstitch_workflow: denoise=None keeps the 0.80 default on
      node 106 (back-compat); an explicit override (e.g. 0.85) plumbs through.
  s2  prepare_outfit_workflow (auto-dispatch) threads denoise the same way on both
      the Rapid V2 crop-stitch template and the Tier-A 2511full template.
  s3  prepare_outfit_workflow does NOT apply a denoise override on the legacy V1
      whole-frame template — node 106 stays at the template's own baked value,
      matching the existing "aggressive denoise is only safe once crop-confined"
      design note in outfit.py.
  s4  BATCH_REQUIRE_CROPSTITCH_OUTFIT guard (batch_pipeline_worker._check_
      cropstitch_outfit_required): raises when required + resolved tier is "v1"
      (naming the offending path), never raises when not required, and never
      raises for either crop-stitch tier — exercised against the REAL workflow
      JSONs via services.workflow_meta.describe_template, the same shape
      PipelineBackgroundWorker._load_workflows() actually stores.

Runs under pytest or directly: python tests/test_outfit_strength.py
"""
import json
from pathlib import Path

from models.enums import OutfitType
from api.v1.endpoints.outfit import prepare_outfit_workflow, prepare_outfit_cropstitch_workflow
from services.workflow_meta import describe_template, TIER_V1, TIER_RAPID_CROPSTITCH, TIER_2511FULL
from workers.batch_pipeline_worker import _check_cropstitch_outfit_required

_WF_DIR = Path(__file__).resolve().parent.parent / "workflows"


def _load(name: str) -> dict:
    with open(_WF_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# s1 — prepare_outfit_cropstitch_workflow: default vs override
# ---------------------------------------------------------------------------
def test_cropstitch_denoise_defaults_to_080_when_none():
    wf = prepare_outfit_cropstitch_workflow(
        _load("outfit_cropstitch_API.json"), "src.png", "change outfit", seed=1,
    )
    assert wf["106"]["inputs"]["denoise"] == 0.80


def test_cropstitch_denoise_override_plumbs_to_node_106():
    wf = prepare_outfit_cropstitch_workflow(
        _load("outfit_cropstitch_API.json"), "src.png", "change outfit", seed=1, denoise=0.85,
    )
    assert wf["106"]["inputs"]["denoise"] == 0.85


def test_cropstitch_denoise_respects_lower_bound_override():
    # The float itself isn't re-validated here (PipelineEditRequest.outfitDenoise's
    # ge=0.5/le=0.95 Field constraint is the enforcement point) — the preparer just
    # plumbs whatever it's given straight to node 106.
    wf = prepare_outfit_cropstitch_workflow(
        _load("outfit_cropstitch_API.json"), "src.png", "change outfit", seed=1, denoise=0.5,
    )
    assert wf["106"]["inputs"]["denoise"] == 0.5


# ---------------------------------------------------------------------------
# s2 — prepare_outfit_workflow auto-dispatch threads denoise on BOTH
# crop-stitch tiers (Rapid V2 and Tier-A 2511full)
# ---------------------------------------------------------------------------
def test_prepare_outfit_workflow_threads_denoise_on_rapid_v2():
    default_wf = prepare_outfit_workflow(
        _load("outfit_cropstitch_API.json"), "src.png", "x", seed=1,
        outfit=OutfitType.BUSINESS_SUIT, head_mask_name="hm.png",
    )
    assert default_wf["106"]["inputs"]["denoise"] == 0.80

    override_wf = prepare_outfit_workflow(
        _load("outfit_cropstitch_API.json"), "src.png", "x", seed=1,
        outfit=OutfitType.BUSINESS_SUIT, head_mask_name="hm.png", denoise=0.9,
    )
    assert override_wf["106"]["inputs"]["denoise"] == 0.9


def test_prepare_outfit_workflow_threads_denoise_on_2511full():
    default_wf = prepare_outfit_workflow(
        _load("outfit_cropstitch_2511full_API.json"), "src.png", "x", seed=1,
        outfit=OutfitType.COCKTAIL_DRESS, head_mask_name="hm.png", source_dressed=True,
    )
    assert default_wf["106"]["inputs"]["denoise"] == 0.80  # matches test_full2511_workflow.py

    override_wf = prepare_outfit_workflow(
        _load("outfit_cropstitch_2511full_API.json"), "src.png", "x", seed=1,
        outfit=OutfitType.COCKTAIL_DRESS, head_mask_name="hm.png", source_dressed=True,
        denoise=0.85,
    )
    assert override_wf["106"]["inputs"]["denoise"] == 0.85
    # Full-model sampler settings (steps/cfg) are untouched by the denoise override.
    assert override_wf["106"]["inputs"]["steps"] >= 20
    assert override_wf["106"]["inputs"]["cfg"] >= 2.0


# ---------------------------------------------------------------------------
# s3 — legacy V1 whole-frame graph: denoise override is accepted but ignored
# ---------------------------------------------------------------------------
def test_prepare_outfit_workflow_v1_ignores_denoise_override():
    template = _load("test_final_API.json")
    baked_denoise = template["106"]["inputs"]["denoise"]

    wf_no_override = prepare_outfit_workflow(template, "src.png", "a red dress", seed=1)
    wf_with_override = prepare_outfit_workflow(
        template, "src.png", "a red dress", seed=1, denoise=0.5,
    )
    assert wf_no_override["106"]["inputs"]["denoise"] == baked_denoise
    # V1 intentionally never applies the caller's denoise override — see the
    # "aggressive denoise is only safe once crop-confined" note in outfit.py.
    assert wf_with_override["106"]["inputs"]["denoise"] == baked_denoise


# ---------------------------------------------------------------------------
# s4 — BATCH_REQUIRE_CROPSTITCH_OUTFIT guard, exercised against real templates
# ---------------------------------------------------------------------------
def test_guard_noop_when_not_required():
    v1_meta = {"path": "/x/test_final_API.json", **describe_template(_load("test_final_API.json"))}
    assert v1_meta["tier"] == TIER_V1
    _check_cropstitch_outfit_required(v1_meta, require=False)  # must not raise


def test_guard_raises_on_v1_tier_when_required():
    v1_meta = {"path": "/x/test_final_API.json", **describe_template(_load("test_final_API.json"))}
    try:
        _check_cropstitch_outfit_required(v1_meta, require=True)
        raised = None
    except RuntimeError as e:
        raised = e
    assert raised is not None, "expected RuntimeError, none was raised"
    assert "/x/test_final_API.json" in str(raised)
    assert "v1" in str(raised)


def test_guard_allows_rapid_cropstitch_tier_when_required():
    meta = {"path": "/x/outfit_cropstitch_API.json", **describe_template(_load("outfit_cropstitch_API.json"))}
    assert meta["tier"] == TIER_RAPID_CROPSTITCH
    _check_cropstitch_outfit_required(meta, require=True)  # must not raise


def test_guard_allows_2511full_tier_when_required():
    meta = {
        "path": "/x/outfit_cropstitch_2511full_API.json",
        **describe_template(_load("outfit_cropstitch_2511full_API.json")),
    }
    assert meta["tier"] == TIER_2511FULL
    _check_cropstitch_outfit_required(meta, require=True)  # must not raise


def test_guard_missing_metadata_does_not_raise():
    # Defensive edge case: no workflow_meta yet (shouldn't happen in practice since
    # start() awaits _load_workflows() first) — the guard has no evidence of "v1", so
    # it stays silent rather than raising on an unproven claim.
    _check_cropstitch_outfit_required(None, require=True)
    _check_cropstitch_outfit_required({}, require=True)


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
