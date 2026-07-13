"""
Tests for camera_vocab demeanor-aware expression pools (WS-B) + rng-parity.

The key contract: varied_shot_fields(rng, demeanor=...) swaps ONLY the expression
pool; the framing/angle draws and the rng draw ORDER/COUNT are unchanged, so a None
demeanor is byte-identical to the legacy behavior (existing seeded tests unaffected).

Runs under pytest or directly: python loli_api/tests/test_camera_vocab_demeanor.py
"""
import random

from models.enums import DemeanorType, ExpressionType
from services import camera_vocab as cv


# --- coverage ---
def test_every_demeanor_has_a_pool():
    for d in DemeanorType:
        assert d in cv.DEMEANOR_EXPRESSION_POOLS, f"missing pool for {d}"
        assert cv.DEMEANOR_EXPRESSION_POOLS[d], f"empty pool for {d}"


def test_all_pool_values_are_valid_expressions():
    valid = {e.value for e in ExpressionType}
    for d, pool in cv.DEMEANOR_EXPRESSION_POOLS.items():
        for v in pool:
            assert v in valid, f"{d}: '{v}' is not an ExpressionType / EXPRESSION_PHRASES key"
            assert cv.EXPRESSION_PHRASES.get(v), f"no phrase for '{v}'"


# --- rng parity: None == legacy ---
def test_none_demeanor_is_byte_identical_to_legacy():
    r1 = random.Random(1234)
    r2 = random.Random(1234)
    seq_legacy = [cv.varied_shot_fields(r1) for _ in range(8)]
    seq_none = [cv.varied_shot_fields(r2, demeanor=None) for _ in range(8)]
    assert seq_legacy == seq_none


def test_demeanor_does_not_change_rng_draw_count():
    # After the same number of calls, both rngs must be at the SAME position — proving
    # demeanor consumes exactly as many draws (framing, angle, expression) as legacy.
    r1 = random.Random(99)
    r2 = random.Random(99)
    for _ in range(8):
        cv.varied_shot_fields(r1)                     # legacy
        cv.varied_shot_fields(r2, demeanor="sultry")  # demeanor path
    assert r1.random() == r2.random()


def test_demeanor_swaps_only_expression_framing_angle_unchanged():
    r1 = random.Random(7)
    r2 = random.Random(7)
    legacy = [cv.varied_shot_fields(r1) for _ in range(12)]
    shy = [cv.varied_shot_fields(r2, demeanor=DemeanorType.SHY) for _ in range(12)]
    # framing + angle identical to legacy for the same seed
    for a, b in zip(legacy, shy):
        assert a["framing"] == b["framing"]
        assert a["angle"] == b["angle"]
    # expressions come from the shy pool
    shy_pool = set(cv.DEMEANOR_EXPRESSION_POOLS[DemeanorType.SHY])
    assert all(s["expression"] in shy_pool for s in shy)


def test_demeanor_accepts_enum_or_string():
    r1 = random.Random(3)
    r2 = random.Random(3)
    a = [cv.varied_shot_fields(r1, demeanor="playful") for _ in range(6)]
    b = [cv.varied_shot_fields(r2, demeanor=DemeanorType.PLAYFUL) for _ in range(6)]
    assert a == b


def test_unknown_demeanor_falls_back_to_default_pool():
    # An unknown demeanor must not raise and must keep framing/angle at legacy parity.
    r1 = random.Random(55)
    r2 = random.Random(55)
    legacy = [cv.varied_shot_fields(r1) for _ in range(6)]
    unknown = [cv.varied_shot_fields(r2, demeanor="not-a-demeanor") for _ in range(6)]
    assert legacy == unknown  # default expression pool == legacy pool


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
