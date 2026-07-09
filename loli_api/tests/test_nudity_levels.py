"""
Tests for the 5-level NudityLevel ladder (LOW < SUGGESTIVE < MEDIUM < REVEALING <
HIGH) and the BatchControls.period_days batch control.

Runs under pytest or directly: python loli_api/tests/test_nudity_levels.py
"""
import pytest
from pydantic import ValidationError

from models.enums import NudityLevel
from models.batch import BatchControls
from services.scene_mapper import _clamp_nudity
from services.prompt_constants import NUDITY_SUPPRESSION


# ---------------------------------------------------------------------------
# NudityLevel enum shape
# ---------------------------------------------------------------------------
def test_nudity_level_has_five_members_in_ladder_order():
    assert [m.value for m in NudityLevel] == [
        "low", "suggestive", "medium", "revealing", "high",
    ]


def test_nudity_level_legacy_values_still_parse():
    # Back-compat: existing stored jsonb/controls using the original 3-level
    # string values must still parse to the same members.
    assert NudityLevel("low") is NudityLevel.LOW
    assert NudityLevel("medium") is NudityLevel.MEDIUM
    assert NudityLevel("high") is NudityLevel.HIGH


def test_nudity_level_new_values_parse():
    assert NudityLevel("suggestive") is NudityLevel.SUGGESTIVE
    assert NudityLevel("revealing") is NudityLevel.REVEALING


# ---------------------------------------------------------------------------
# NUDITY_SUPPRESSION completeness (edit_negative/generation_negative index by
# NudityLevel.value; a missing key would silently fall back to "low" rather
# than KeyError, but the new levels need their own distinct suppression text).
# ---------------------------------------------------------------------------
def test_nudity_suppression_has_all_five_keys():
    for level in NudityLevel:
        assert level.value in NUDITY_SUPPRESSION, f"missing NUDITY_SUPPRESSION[{level.value!r}]"


def test_nudity_suppression_values_are_strings():
    for level in NudityLevel:
        assert isinstance(NUDITY_SUPPRESSION[level.value], str)


# ---------------------------------------------------------------------------
# scene_mapper._clamp_nudity across the 5-level ladder
# ---------------------------------------------------------------------------
def test_clamp_nudity_low_stays_low():
    controls = BatchControls(max_nudity=NudityLevel.HIGH)
    assert _clamp_nudity(NudityLevel.LOW, controls) == NudityLevel.LOW


def test_clamp_nudity_clamps_revealing_down_to_medium_ceiling():
    controls = BatchControls(max_nudity=NudityLevel.MEDIUM)
    assert _clamp_nudity(NudityLevel.REVEALING, controls) == NudityLevel.MEDIUM


def test_clamp_nudity_passes_through_when_under_ceiling():
    controls = BatchControls(max_nudity=NudityLevel.HIGH)
    assert _clamp_nudity(NudityLevel.SUGGESTIVE, controls) == NudityLevel.SUGGESTIVE


def test_clamp_nudity_accepts_raw_string_values():
    controls = BatchControls(max_nudity=NudityLevel.HIGH)
    assert _clamp_nudity("revealing", controls) == NudityLevel.REVEALING


def test_clamp_nudity_sfw_only_forces_low():
    controls = BatchControls(sfw_only=True, max_nudity=NudityLevel.HIGH)
    assert _clamp_nudity(NudityLevel.HIGH, controls) == NudityLevel.LOW


# ---------------------------------------------------------------------------
# BatchControls.period_days
# ---------------------------------------------------------------------------
def test_period_days_defaults_to_one():
    assert BatchControls().period_days == 1


def test_period_days_accepts_valid_value():
    assert BatchControls(period_days=3).period_days == 3


def test_period_days_rejects_below_minimum():
    with pytest.raises(ValidationError):
        BatchControls(period_days=0)


def test_period_days_rejects_above_maximum():
    with pytest.raises(ValidationError):
        BatchControls(period_days=8)


def test_legacy_batch_controls_still_parses_with_period_days_default():
    # Old stored controls jsonb (pre-period_days) must still parse, with the
    # new field defaulting rather than erroring.
    controls = BatchControls(**{"max_nudity": "medium"})
    assert controls.max_nudity == NudityLevel.MEDIUM
    assert controls.period_days == 1


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
        except Exception as e:
            failures += 1
            print(f"ERROR {fn.__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
