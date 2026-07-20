"""
Tests for the tiered video action catalog (services/video_action_catalog.py):
the data-driven registry that backs the admin action picker + the per-item
render snapshot.

Guards the contract the orchestrator + admin FE depend on:
  * every id is unique + slug-like, every label non-empty, every prompt non-empty
    and camera-facing (matches the MOTION_DESCRIPTIONS register);
  * LoRAs are wired ONLY on the explicit tier, and each explicit entry carries
    exactly the one clean-licensed enhancer LoRA (high-chain only);
  * all 24 back-compat MotionType ids appear as catalog ids;
  * catalog_grouped_by_tier covers all 5 tiers in ascending order.

Runs under pytest or directly: python loli_api/tests/test_video_action_catalog.py
"""
import re

from models.enums import MotionType
from models.video_batch import VideoActionTier
from services.video_action_catalog import (
    VIDEO_ACTION_CATALOG,
    CATALOG_BY_ID,
    LoraRef,
    VideoActionPreset,
    catalog_grouped_by_tier,
    get_preset,
)

_SLUG_RE = re.compile(r"^[a-z0-9_]+$")

# The single clean-licensed (openrail-m) enhancer LoRA wired on the explicit tier.
_EXPLICIT_LORA_NAME = "nsfw/nsfw_wan14b_e15.safetensors"


def test_every_id_is_unique_and_slug_like():
    ids = [p.id for p in VIDEO_ACTION_CATALOG]
    assert len(ids) == len(set(ids)), "catalog ids must be unique"
    # CATALOG_BY_ID is built from the same list — it must not have collapsed dupes.
    assert len(CATALOG_BY_ID) == len(VIDEO_ACTION_CATALOG)
    for pid in ids:
        assert _SLUG_RE.match(pid), f"id {pid!r} is not slug-like (a-z0-9_)"


def test_every_label_non_empty():
    for p in VIDEO_ACTION_CATALOG:
        assert p.label and p.label.strip(), f"preset {p.id} has an empty label"


def test_every_prompt_non_empty_and_camera_facing():
    for p in VIDEO_ACTION_CATALOG:
        assert p.prompt and p.prompt.strip(), f"preset {p.id} has an empty prompt"
        assert "camera" in p.prompt.lower(), (
            f"preset {p.id} prompt is not camera-facing (missing 'camera')"
        )


def test_loras_present_only_on_the_explicit_tier():
    for p in VIDEO_ACTION_CATALOG:
        if p.tier == VideoActionTier.EXPLICIT:
            assert p.loras, f"explicit preset {p.id} must carry a LoRA"
        else:
            assert p.loras == (), (
                f"non-explicit preset {p.id} (tier {p.tier.value}) must carry no LoRAs"
            )


def test_every_explicit_entry_has_the_single_enhancer_lora():
    explicit = [p for p in VIDEO_ACTION_CATALOG if p.tier == VideoActionTier.EXPLICIT]
    assert explicit, "expected at least one explicit-tier preset"
    for p in explicit:
        assert len(p.loras) == 1, f"explicit preset {p.id} must have exactly one LoRA"
        ref = p.loras[0]
        assert isinstance(ref, LoraRef)
        assert ref.name == _EXPLICIT_LORA_NAME, (
            f"explicit preset {p.id} wires an unexpected LoRA {ref.name!r}"
        )
        # 2.1-T2V-based enhancer: HIGH-noise expert only, moderate strength.
        assert 0.5 <= ref.strength_high <= 0.8, (
            f"explicit preset {p.id} strength_high {ref.strength_high} out of [0.5, 0.8]"
        )
        assert ref.strength_low == 0.0, (
            f"explicit preset {p.id} must not load on the low-noise expert "
            f"(strength_low={ref.strength_low})"
        )


def test_every_tier_is_a_valid_enum_member():
    valid = set(VideoActionTier)
    for p in VIDEO_ACTION_CATALOG:
        assert p.tier in valid, f"preset {p.id} has an invalid tier {p.tier!r}"


def test_total_count_in_expected_band():
    assert 35 <= len(VIDEO_ACTION_CATALOG) <= 45, (
        f"catalog has {len(VIDEO_ACTION_CATALOG)} presets (expected 35-45)"
    )


def test_all_24_motion_type_ids_present_as_catalog_ids():
    motion_ids = {m.value for m in MotionType}
    assert len(motion_ids) == 24, "MotionType enum is expected to hold 24 members"
    catalog_ids = {p.id for p in VIDEO_ACTION_CATALOG}
    missing = motion_ids - catalog_ids
    assert not missing, f"MotionType ids missing from the catalog: {sorted(missing)}"
    # And each reused entry resolves via the public lookup.
    for mid in motion_ids:
        assert get_preset(mid) is not None, f"get_preset({mid!r}) returned None"


def test_catalog_grouped_by_tier_covers_all_tiers_ascending():
    groups = catalog_grouped_by_tier()
    expected_order = [
        VideoActionTier.CHARM_IDLE.value,
        VideoActionTier.PLAYFUL.value,
        VideoActionTier.GLAMOUR.value,
        VideoActionTier.TEASE.value,
        VideoActionTier.EXPLICIT.value,
    ]
    assert [g["tier"] for g in groups] == expected_order, "tier groups out of ascending order"

    # Every group has a display label + at least one preset, and the flattened
    # grouping is a partition of the whole catalog (no drops, no dupes).
    flattened = []
    for g in groups:
        assert g["label"] and g["label"].strip(), f"tier {g['tier']} has no label"
        assert g["presets"], f"tier {g['tier']} has no presets"
        for entry in g["presets"]:
            assert entry["tier"] == g["tier"]
            flattened.append(entry["id"])
    assert sorted(flattened) == sorted(p.id for p in VIDEO_ACTION_CATALOG), (
        "grouped presets must partition the full catalog"
    )


def test_dataclasses_are_frozen():
    # Frozen dataclasses keep the module-level registry immutable at runtime.
    p = VIDEO_ACTION_CATALOG[0]
    for attr, val in (("id", "x"), ("label", "y")):
        try:
            setattr(p, attr, val)
        except Exception:  # noqa: BLE001 — FrozenInstanceError expected
            continue
        raise AssertionError(f"VideoActionPreset.{attr} was mutable (dataclass not frozen)")


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
