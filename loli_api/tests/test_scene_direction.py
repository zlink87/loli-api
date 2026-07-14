"""
WS2 — Venice scene-direction writer (validated, fallback-safe).

The deterministic planner decides WHAT each photo is; Venice writes HOW IT LOOKS — 1-3
sentences of concrete photographic staging per item, hard-validated. Covers:

  * validate_scene_direction unit matrix: length, identity/appearance, wrong-location
    tokens, people-in-private vs anonymous-crowd-in-public, garments outside the outfit,
    story/second-person markers, and the happy path.
  * apply_scene_directions with a MOCKED Venice transport: happy path (valid JSON ->
    directions applied, source="venice"); per-item validation failures fall back
    individually; a whole-call failure -> every item falls back; provider="deterministic"
    (and no-key) -> Venice never called and the fields stay None.
  * determinism: every DETERMINISTIC scene field is unchanged whether the writer runs or
    not — only scene_direction/direction_source move.
  * SceneSpec round-trip through jsonb (the two new fields are jsonb-safe; legacy dict
    without the keys parses back to None).
  * scene_mapper: a present direction REPLACES the bare staging phrase in the composed
    scene text and rides stagingText when it fits the 160-char cap (a longer one stays in
    the scene text and the pose prompt keeps the short staging phrase); None -> staging.

Runs under pytest or directly: python loli_api/tests/test_scene_direction.py
"""
import asyncio
import json

import models.requests as _mr

# These tests exercise the writer/mapper, not the SSRF allowlist.
_mr.validate_source_image = lambda u: u  # type: ignore

from types import SimpleNamespace

from models.enums import NudityLevel, OutfitType, LocationType, TimeOfDayType, PoseType
from models.requests import PersonaOptions
from models.batch import BatchControls
from models.scene import SceneSpec
from services import scene_direction as sd
from services import venice_client as vc
from services.scene_mapper import scene_to_pipeline_request
from services.story_planner import Character, DeterministicScenePlanner, validate_and_repair


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _settings(provider="venice", key="test-key"):
    return SimpleNamespace(
        SCENE_DIRECTION_PROVIDER=provider,
        VENICE_API_KEY=key,
        VENICE_BASE_URL="https://api.venice.ai/api/v1",
        VENICE_MODEL="venice-uncensored",
        SCENE_DIRECTION_MODEL="",
        SCENE_DIRECTION_TEMPERATURE=0.7,
        SCENE_DIRECTION_MAX_TOKENS=4000,
        SCENE_DIRECTION_TIMEOUT_SECONDS=20.0,
    )


def _scene(i, location, outfit=None, outfit_detail=None, pose=None, staging=None,
           nudity=NudityLevel.MEDIUM):
    return SceneSpec(
        arc_id="a", arc_title="A", beat_index=i, global_index=i, beat_description="b",
        location=location, outfit=outfit, outfit_detail=outfit_detail, pose=pose,
        staging=staging, nudityLevel=nudity, time_of_day=TimeOfDayType.EVENING,
    )


class _StubChat:
    """Async stand-in for VeniceClient.chat that returns a canned (content, usage)."""

    def __init__(self, content):
        self.content = content
        self.calls = 0

    async def __call__(self, _self, messages, *, temperature=0.7, max_tokens=1500, model=None):
        self.calls += 1
        return self.content, {}


def _run_apply(scenes, controls, settings, content):
    """apply_scene_directions with VeniceClient.chat swapped for a stub. Returns the stub
    (so callers can assert .calls). Manual save/restore so it runs under the __main__ runner."""
    stub = _StubChat(content)
    saved = vc.VeniceClient.chat
    vc.VeniceClient.chat = lambda self, messages, **kw: stub(self, messages, **kw)
    try:
        asyncio.run(sd.apply_scene_directions(scenes, controls, settings=settings))
    finally:
        vc.VeniceClient.chat = saved
    return stub


_VALID_1 = ("Colored lights wash across a low velvet booth and a mirrored back wall; the "
            "camera sits at eye level with a shallow depth of field and glittering bokeh.")
_VALID_3 = ("Warm lamplight pools over a rumpled bed and a bedside table; shot from a low "
            "three-quarter angle, close and intimate, the far corner soft in shadow.")
_INVALID_IDENTITY = "Soft light falls across her blonde hair beside the tall window."


# ---------------------------------------------------------------------------
# validator unit matrix
# ---------------------------------------------------------------------------
def test_validator_happy_path():
    out = sd.validate_scene_direction(
        _VALID_1, location=LocationType.NIGHTCLUB, outfit=OutfitType.BODYCON_DRESS,
        outfit_detail="black bodycon dress", venue_public=True,
    )
    assert out == _VALID_1


def test_validator_rejects_identity_and_appearance():
    for bad in (
        "Light catches her blonde hair by the window.",
        "The lens holds on her face and soft cheeks.",
        "A shot that flatters her curvy figure.",
        "Framing her toned thighs against the sheets.",
        "A young woman's silhouette by the glass.",
    ):
        assert sd.validate_scene_direction(bad, location=LocationType.HOME_BEDROOM) is None, bad


def test_validator_rejects_wrong_location_tokens():
    # names a DIFFERENT place than the item's location.
    assert sd.validate_scene_direction(
        "Waves break on the sunny beach behind the loungers.",
        location=LocationType.OFFICE, venue_public=True,
    ) is None
    # naming its OWN place is fine.
    assert sd.validate_scene_direction(
        "Glass office partitions frame a tidy desk; wide, cool, symmetrical.",
        location=LocationType.OFFICE, venue_public=True,
    ) is not None


def test_validator_people_rules():
    L = LocationType
    # relational/individuated people banned everywhere.
    for bad in ("A man waits by the bar.", "Her boyfriend stands nearby.",
                "A couple laughs at the next table."):
        assert sd.validate_scene_direction(bad, location=L.BAR, venue_public=True) is None, bad
    # anonymous background crowd: allowed at a PUBLIC venue, banned in PRIVATE.
    crowd = "A blurred crowd fills the far background of the room."
    assert sd.validate_scene_direction(crowd, location=L.NIGHTCLUB, venue_public=True) is not None
    assert sd.validate_scene_direction(crowd, location=L.HOME_BEDROOM, venue_public=False) is None


def test_validator_garment_rules():
    L, O = LocationType, OutfitType
    # names a garment NOT in the item's outfit -> reject.
    assert sd.validate_scene_direction(
        "A red dress is draped over the chair by the desk.",
        location=L.OFFICE, outfit=O.BUSINESS_SUIT, outfit_detail="grey suit", venue_public=True,
    ) is None
    # a furniture material that merely LOOKS like a fabric is fine (not a garment word).
    assert sd.validate_scene_direction(
        "A brown leather sofa faces a low glass table; medium shot, soft window light.",
        location=L.HOME_LIVING_ROOM, venue_public=False,
    ) is not None


def test_validator_story_and_length():
    L = LocationType
    assert sd.validate_scene_direction(
        "She remembers the summers spent on this balcony.", location=L.HOME_BALCONY,
    ) is None
    assert sd.validate_scene_direction(
        "You can almost feel the warm evening air here.", location=L.HOME_BALCONY,
    ) is None
    assert sd.validate_scene_direction("x" * 321, location=L.HOME_BEDROOM) is None
    assert sd.validate_scene_direction("", location=L.HOME_BEDROOM) is None
    assert sd.validate_scene_direction(None, location=L.HOME_BEDROOM) is None


def test_validator_rejects_reused_identity_vocab():
    # FIX: the identity scan reuses the planner's FULL vocab (story_planner._IDENTITY_TOKENS),
    # so ethnicity/hair/eye words the old hand list missed are now caught.
    L = LocationType
    # 'redhead' (hair-person word).
    assert sd.validate_scene_direction(
        "A lamp beside the redhead on the couch.", location=L.HOME_LIVING_ROOM,
    ) is None
    # an ethnicity word the OLD hand list did NOT have (it only listed asian/caucasian/latina).
    assert sd.validate_scene_direction(
        "A japanese folding screen by the low table.", location=L.HOME_BEDROOM,
    ) is None
    assert sd.validate_scene_direction(
        "Korean signage over a low counter.", location=L.CITY_STREET, venue_public=True,
    ) is None
    # a multi-word ethnicity PHRASE (substring match).
    assert sd.validate_scene_direction(
        "A south asian motif on the far wall.", location=L.HOME_LIVING_ROOM,
    ) is None
    # an eye-color PHRASE (caught in context by the reused appearance patterns).
    assert sd.validate_scene_direction(
        "Soft light catching her blue eyes.", location=L.HOME_BEDROOM,
    ) is None


def test_validator_keeps_camera_idiom_and_clean_scene_colors():
    L = LocationType
    # the 'eye level' camera idiom still passes (a framing term, not an eyes appearance word).
    assert sd.validate_scene_direction(
        "A tidy desk shot at eye level, wide and symmetrical.", location=L.OFFICE, venue_public=True,
    ) is not None
    # bare scene colors / shapes are NOT identity out of context -> a clean set passes (the same
    # words are only rejected in an appearance context like "brown hair", via the patterns).
    assert sd.validate_scene_direction(
        "A short black bench and a brown side table under a green plant.",
        location=L.HOME_LIVING_ROOM,
    ) is not None


def test_validator_garment_plural_tolerance_reuses_planner_set():
    # FIX: the garment check reuses story_planner._GARMENT_CLASS_WORDS with single-'s'/'es'
    # plural tolerance, so a stray plural garment is caught but the item's own word passes.
    L, O = LocationType, OutfitType
    assert sd.validate_scene_direction(
        "Several dresses hang on a rail beside the desk.",
        location=L.OFFICE, outfit=O.BUSINESS_SUIT, outfit_detail="grey suit", venue_public=True,
    ) is None
    # the item's OWN garment word still passes ('suit' is in its outfit words).
    assert sd.validate_scene_direction(
        "A charcoal suit hangs on the rail; wide, cool, symmetrical.",
        location=L.OFFICE, outfit=O.BUSINESS_SUIT, outfit_detail="grey suit", venue_public=True,
    ) is not None


# ---------------------------------------------------------------------------
# apply_scene_directions — mocked Venice
# ---------------------------------------------------------------------------
def test_apply_happy_path_sets_venice_source():
    scenes = [
        _scene(0, LocationType.NIGHTCLUB, OutfitType.BODYCON_DRESS, "black bodycon dress",
               PoseType.SITTING, staging="perched on a bar stool at the counter"),
        _scene(1, LocationType.HOME_BEDROOM, OutfitType.SATIN_ROBE, "satin robe",
               PoseType.LYING_BACK, staging="lying back on the pillows", nudity=NudityLevel.HIGH),
    ]
    content = json.dumps([
        {"index": 0, "direction": _VALID_1},
        {"index": 1, "direction": _VALID_3},
    ])
    stub = _run_apply(scenes, BatchControls(base_seed=1), _settings(), content)
    assert stub.calls == 1                                        # ONE batched call
    assert scenes[0].scene_direction == _VALID_1 and scenes[0].direction_source == "venice"
    assert scenes[1].scene_direction == _VALID_3 and scenes[1].direction_source == "venice"


def test_apply_per_item_validation_failure_falls_back_individually():
    scenes = [
        _scene(0, LocationType.NIGHTCLUB, OutfitType.BODYCON_DRESS, "bodycon dress",
               staging="perched on a bar stool at the counter"),
        _scene(1, LocationType.HOME_BEDROOM, OutfitType.SATIN_ROBE, "satin robe",
               staging="lying back on the pillows"),
    ]
    content = json.dumps([
        {"index": 0, "direction": _VALID_1},              # valid
        {"index": 1, "direction": _INVALID_IDENTITY},     # fails validation -> fallback
    ])
    _run_apply(scenes, BatchControls(base_seed=1), _settings(), content)
    assert scenes[0].scene_direction == _VALID_1 and scenes[0].direction_source == "venice"
    assert scenes[1].scene_direction is None and scenes[1].direction_source == "fallback"


def test_apply_whole_call_failure_all_fall_back():
    scenes = [_scene(0, LocationType.NIGHTCLUB, staging="perched on a bar stool at the counter"),
              _scene(1, LocationType.HOME_BEDROOM, staging="lying back on the pillows")]
    # chat returns None (timeout/error) -> every item falls back.
    _run_apply(scenes, BatchControls(base_seed=1), _settings(), None)
    for s in scenes:
        assert s.scene_direction is None and s.direction_source == "fallback"


def test_apply_bad_json_all_fall_back():
    scenes = [_scene(0, LocationType.NIGHTCLUB, staging="perched on a bar stool at the counter")]
    _run_apply(scenes, BatchControls(base_seed=1), _settings(), "not json at all { [")
    assert scenes[0].scene_direction is None and scenes[0].direction_source == "fallback"


def test_provider_deterministic_never_calls_venice():
    scenes = [_scene(0, LocationType.NIGHTCLUB, staging="perched on a bar stool at the counter")]
    stub = _run_apply(scenes, BatchControls(base_seed=1),
                      _settings(provider="deterministic"), json.dumps([{"index": 0, "direction": _VALID_1}]))
    assert stub.calls == 0                                        # Venice skipped entirely
    assert scenes[0].scene_direction is None and scenes[0].direction_source is None


def test_no_api_key_never_calls_venice():
    scenes = [_scene(0, LocationType.NIGHTCLUB, staging="perched on a bar stool at the counter")]
    stub = _run_apply(scenes, BatchControls(base_seed=1),
                      _settings(key=""), json.dumps([{"index": 0, "direction": _VALID_1}]))
    assert stub.calls == 0
    assert scenes[0].scene_direction is None and scenes[0].direction_source is None


def _capture_write_batch_max_tokens(n_items: int, setting_max_tokens: int = 4000) -> int:
    """Run write_batch over n_items with a chat stub that records the max_tokens it was
    passed. Returns that value."""
    captured = {}

    async def _fake_chat(_self, messages, *, temperature=0.7, max_tokens=0, model=None):
        captured["max_tokens"] = max_tokens
        return "[]", {}

    writer = sd.SceneDirectionWriter(api_key="k", max_tokens=setting_max_tokens)
    saved = vc.VeniceClient.chat
    vc.VeniceClient.chat = lambda self, messages, **kw: _fake_chat(self, messages, **kw)
    try:
        items = [{"index": i, "location": "home_bedroom"} for i in range(n_items)]
        asyncio.run(writer.write_batch(items))
    finally:
        vc.VeniceClient.chat = saved
    return captured["max_tokens"]


def test_write_batch_scales_max_tokens_with_item_count():
    # A big batch is ONE call; a fixed 4000 cap would truncate it into an all-fallback response.
    # The setting is a FLOOR — write_batch raises effective max_tokens to 400 + 130*n.
    assert _capture_write_batch_max_tokens(50) >= 6900   # 400 + 130*50 = 6900 (> the 4000 floor)


def test_write_batch_uses_setting_floor_for_small_batch():
    # A small batch stays at the configured floor (400 + 130*1 = 530 < 4000).
    assert _capture_write_batch_max_tokens(1) == 4000


# ---------------------------------------------------------------------------
# determinism: only the two new fields move
# ---------------------------------------------------------------------------
def _character(occupation="model"):
    persona = PersonaOptions(
        ethnicity="caucasian", age=28, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Estella",
        occupation=occupation, personality="temptress", relationship="girlfriend",
    )
    return Character(persona=persona, likes=[], dislikes=[], hero_photo_url="https://x/h.png")


def _dump_without_direction(scenes):
    out = []
    for s in scenes:
        d = s.model_dump()
        d.pop("scene_direction", None)
        d.pop("direction_source", None)
        out.append(d)
    return out


def test_deterministic_fields_unchanged_whether_venice_runs():
    char = _character("model")
    controls = BatchControls(max_nudity=NudityLevel.HIGH, escalation="building", base_seed=3)
    base = validate_and_repair(
        DeterministicScenePlanner().plan_scenes_sync(char, 12, controls), char, 12, controls
    )
    before = _dump_without_direction(base)
    # run the (mocked-valid) writer over a copy and confirm ONLY the direction fields changed.
    copy = [s.model_copy(deep=True) for s in base]
    content = json.dumps([{"index": i, "direction": _VALID_3} for i in range(len(copy))])
    _run_apply(copy, controls, _settings(), content)
    assert _dump_without_direction(copy) == before
    assert any(s.direction_source for s in copy)  # the writer really ran


def test_scene_spec_direction_fields_round_trip_jsonb():
    s = _scene(0, LocationType.HOME_BEDROOM, OutfitType.SATIN_ROBE, "satin robe")
    s.scene_direction = _VALID_3
    s.direction_source = "venice"
    dumped = s.model_dump(mode="json")
    assert dumped["scene_direction"] == _VALID_3 and dumped["direction_source"] == "venice"
    back = SceneSpec(**dumped)
    assert back.scene_direction == _VALID_3 and back.direction_source == "venice"
    # legacy jsonb WITHOUT the keys -> defaults None.
    legacy = {k: v for k, v in dumped.items() if k not in ("scene_direction", "direction_source")}
    legacy_spec = SceneSpec(**legacy)
    assert legacy_spec.scene_direction is None and legacy_spec.direction_source is None


# ---------------------------------------------------------------------------
# scene_mapper integration
# ---------------------------------------------------------------------------
def test_mapper_direction_replaces_staging_and_rides_stagingtext():
    char = _character()
    controls = BatchControls(base_seed=1)
    s = _scene(0, LocationType.HOME_BEDROOM, OutfitType.SATIN_ROBE, "satin robe",
               PoseType.LYING_BACK, staging="lying back on the pillows")
    s.scene_direction = _VALID_3
    s.direction_source = "venice"
    req = scene_to_pipeline_request(char, s, controls, single_pass=False)
    # the direction is in the composed scene text; the bare staging phrase is NOT doubled in.
    assert _VALID_3 in req.prompt
    assert "lying back on the pillows" not in req.prompt
    # it fits the 160-char cap -> it rides stagingText too.
    assert len(_VALID_3) <= 160 and req.stagingText == _VALID_3


def test_mapper_long_direction_keeps_short_staging_in_pose_slot():
    char = _character()
    controls = BatchControls(base_seed=1)
    long_dir = ("Warm sconces line the panelled wall above a deep sofa and a low marble table, "
                "a tall lamp glowing in the far corner; the camera holds a slow, wide, "
                "eye-level frame with the near edge soft and the room falling gently out of "
                "focus toward the shadowed doorway beyond.")
    assert 160 < len(long_dir) <= 320
    s = _scene(0, LocationType.HOME_LIVING_ROOM, OutfitType.SATIN_ROBE, "satin robe",
               PoseType.SOFA, staging="sitting on the plush sofa")
    s.scene_direction = long_dir
    s.direction_source = "venice"
    req = scene_to_pipeline_request(char, s, controls, single_pass=False)
    assert long_dir in req.prompt                       # full direction rides the scene text
    assert req.stagingText == "sitting on the plush sofa"  # pose slot keeps the SHORT phrase


def test_mapper_no_direction_falls_back_to_staging():
    char = _character()
    controls = BatchControls(base_seed=1)
    s = _scene(0, LocationType.HOME_BEDROOM, OutfitType.SATIN_ROBE, "satin robe",
               PoseType.LYING_BACK, staging="lying back on the pillows")
    # scene_direction is None (deterministic provider / legacy) -> the staging phrase stands.
    req = scene_to_pipeline_request(char, s, controls, single_pass=False)
    assert req.stagingText == "lying back on the pillows"
    assert "lying back on the pillows" in req.prompt


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"ok  {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
