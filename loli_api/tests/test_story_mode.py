"""
Tests for story-driven batches (Feature 2): story JSON parsing, narrative identity
scrub, deterministic story fallback, render-field repair with narrative present,
narrative excluded from the render prompt, NSFW gating, and story assembly.

Runs under pytest or directly: python loli_api/tests/test_story_mode.py
"""
import asyncio
import re
from types import SimpleNamespace

# The mapper SSRF-validates source_image; these tests exercise narrative/mapping,
# not the allowlist, so make the validator a passthrough (mirrors test_scene_mapper).
import models.requests as _mr
_mr.validate_source_image = lambda u: u  # type: ignore

from models.requests import PersonaOptions
from models.batch import BatchControls, assemble_story, BatchItemRead
from models.scene import SceneSpec
from models.enums import OutfitType, LocationType, PoseType, NudityLevel
from services.story_planner import (
    Character, DeterministicScenePlanner, validate_and_repair, plan_scenes, _parse_arcs_json,
    VeniceScenePlanner, STORY_DIRECTOR_SYSTEM_PROMPT,
)
from services.scene_mapper import scene_to_pipeline_request


def _persona(occupation="stripper"):
    return PersonaOptions(
        ethnicity="latina", age=24, hairStyle="straight", hairColor="black",
        eyeColor="brown", bodyType="curvy", breastSize="medium", name="Nora",
        occupation=occupation, personality="nympho", relationship="sugar_baby",
        kinks=["oral_play"],
    )


def _character(occupation="stripper", bio=None):
    return Character(
        persona=_persona(occupation), hero_photo_url="https://x.supabase.co/img.png", bio=bio,
    )


def _fake_settings(venice="", anthropic="", provider=""):
    return SimpleNamespace(
        VENICE_API_KEY=venice, VENICE_BASE_URL="https://api.venice.ai/api/v1",
        VENICE_MODEL="venice-uncensored",
        ANTHROPIC_API_KEY=anthropic, ANTHROPIC_MODEL="claude-sonnet-4-5",
        STORY_PLANNER_PROVIDER=provider,
    )


def _items(scenes):
    return [
        BatchItemRead(
            id=str(i), scene_index=i, status="succeeded",
            scene_spec=s.model_dump(mode="json"), image_url=f"http://x/{i}.png",
        )
        for i, s in enumerate(scenes)
    ]


# --- Venice JSON parsing ---
def test_story_json_parses_title_and_narrative():
    raw = (
        '{"story_title":"Neon Nights","arcs":[{"arc_id":"studio","arc_title":"In the studio",'
        '"beats":[{"beat_description":"posing under the lights",'
        '"narrative":"Nora owns the room, every eye on her."}]}]}'
    )
    scenes = _parse_arcs_json(raw)
    assert len(scenes) == 1
    assert scenes[0].story_title == "Neon Nights"
    assert "Nora owns the room" in scenes[0].narrative


def test_scrub_identity_strips_appearance_from_narrative():
    raw = (
        '{"story_title":"S","arcs":[{"arc_id":"a","arc_title":"A","beats":[{"beat_description":"x",'
        '"narrative":"A stunning young redhead with green eyes leans back, her tan skin glowing."}]}]}'
    )
    scenes = validate_and_repair(_parse_arcs_json(raw), _character(), 1, BatchControls())
    n = (scenes[0].narrative or "").lower()
    for banned in ("redhead", "young", "eyes", "skin"):
        assert banned not in n, f"identity token survived: {banned} in {n!r}"


# --- deterministic fallback story ---
def test_deterministic_story_has_title_and_one_narrative_per_scene():
    for count in (1, 20, 50):
        ctrl = BatchControls(base_seed=5, story_mode=True)
        scenes = DeterministicScenePlanner().plan_scenes_sync(_character(), count, ctrl)
        assert len(scenes) == count
        assert all(s.narrative for s in scenes), f"missing narrative at count={count}"
        assert len({s.story_title for s in scenes}) == 1
        assert scenes[0].story_title


def test_story_mode_off_leaves_narrative_none():
    ctrl = BatchControls(base_seed=5, story_mode=False)
    scenes = DeterministicScenePlanner().plan_scenes_sync(_character(), 4, ctrl)
    assert all(s.narrative is None and s.story_title is None for s in scenes)


# --- render fields stay authoritative with a narrative present ---
def test_render_fields_still_repaired_with_narrative():
    outfit = next(o for o in OutfitType if o != OutfitType.NAKED)
    scene = SceneSpec(
        arc_id="a", arc_title="A", beat_index=0, global_index=0, beat_description="x",
        outfit=outfit, location=list(LocationType)[0],
        narrative="Nora smiles to herself.", story_title="S",
    )
    controls = BatchControls(blocked_outfits=[outfit])
    repaired = validate_and_repair([scene], _character(), 1, controls, enforce_beat_pool=False)
    assert repaired[0].outfit is None  # blocked outfit cleared despite narrative
    assert repaired[0].narrative == "Nora smiles to herself."  # narrative preserved


def test_narrative_excluded_from_pipeline_prompt():
    marker = "ZZQUUXGLITTERUNICORN"
    scene = SceneSpec(
        arc_id="a", arc_title="A", beat_index=0, global_index=0,
        beat_description="leaning by the window", location=list(LocationType)[0],
        pose=list(PoseType)[0], narrative=f"Nora {marker} shimmers.", story_title="S",
    )
    req = scene_to_pipeline_request(_character(), scene, BatchControls())
    blob = " ".join(str(v) for v in req.model_dump().values())
    assert marker not in blob


# --- gating ---
def test_nsfw_story_mode_never_selects_claude():
    ctrl = BatchControls(content_rating="nsfw", story_mode=True)
    scenes, provider = asyncio.run(
        plan_scenes(_character(), 6, ctrl, settings=_fake_settings(venice="", anthropic="key"))
    )
    assert provider != "claude"
    assert provider == "deterministic"
    assert len(scenes) == 6


# --- story assembly (read-time, no new storage) ---
def test_assemble_story_groups_into_ordered_chapters():
    ctrl = BatchControls(base_seed=3, story_mode=True)
    scenes = DeterministicScenePlanner().plan_scenes_sync(_character(), 8, ctrl)
    story = assemble_story(_items(scenes))
    assert story is not None and story.title
    assert len(story.chapters) >= 2
    assert sum(len(c.beats) for c in story.chapters) == 8
    idxs = [b.scene_index for c in story.chapters for b in c.beats]
    assert idxs == sorted(idxs)


def test_assemble_story_none_for_non_story_items():
    items = [BatchItemRead(id="0", scene_index=0, status="x", scene_spec={"arc_id": "a", "arc_title": "A"})]
    assert assemble_story(items) is None


# --- render-safe story channel: setting/activity DO reach the render, narrative does NOT ---
def test_setting_activity_reach_render_but_narrative_does_not():
    act_marker, set_marker, narr_marker = "MARKERPOUR", "MARKERNOOK", "ZZUNICORNGLITTER"
    scene = SceneSpec(
        arc_id="a", arc_title="A", beat_index=0, global_index=0,
        beat_description="a calm moment", location=list(LocationType)[0],
        activity=f"{act_marker} holding a mug", setting=f"a {set_marker} corner",
        narrative=f"Nora {narr_marker} smiles.", story_title="S",
    )
    req = scene_to_pipeline_request(_character(), scene, BatchControls())
    prompt = req.prompt or ""
    assert act_marker in prompt, "activity must reach the render prompt"
    assert set_marker in prompt, "setting must reach the render prompt"
    # The free-prose narrative must never leak into ANY render field.
    blob = " ".join(str(v) for v in req.model_dump().values())
    assert narr_marker not in blob, "narrative must stay out of the render"


def test_venice_output_not_snapped_to_pool_when_enforcement_off():
    # A coherent combo the LLM chose freely must survive when enforce_beat_pool=False
    # (the mode Venice-director output uses) — it is NOT snapped back to a BeatTemplate.
    outfit = next(o for o in OutfitType if o != OutfitType.NAKED)
    location = list(LocationType)[-1]
    scene = SceneSpec(
        arc_id="a", arc_title="A", beat_index=0, global_index=0, beat_description="x",
        outfit=outfit, location=location, pose=list(PoseType)[0],
    )
    repaired = validate_and_repair([scene], _character(), 1, BatchControls(), enforce_beat_pool=False)
    assert repaired[0].outfit == outfit
    assert repaired[0].location == location


def test_scrub_identity_strips_appearance_from_setting_activity():
    raw = (
        '{"story_title":"S","arcs":[{"arc_id":"a","arc_title":"A","beats":[{'
        '"beat_description":"x","location":"home_living_room",'
        '"setting":"a cozy room where a young redhead with green eyes stands",'
        '"activity":"the brunette with pale skin pours coffee"}]}]}'
    )
    scenes = validate_and_repair(
        _parse_arcs_json(raw), _character(), 1, BatchControls(), enforce_beat_pool=False
    )
    s = scenes[0]
    blob = ((s.setting or "") + " " + (s.activity or "")).lower()
    for banned in ("redhead", "young", "eyes", "brunette", "skin"):
        assert banned not in blob, f"identity survived in setting/activity: {banned!r} in {blob!r}"
    # And nothing identity-bearing reaches the render prompt either.
    req = scene_to_pipeline_request(_character(), s, BatchControls())
    rp = (req.prompt or "").lower()
    for banned in ("redhead", "brunette", "green eyes"):
        assert banned not in rp


# --- story-director prompt (WS1.4) + structured channels (WS2.2) ---
def test_director_system_prompt_declares_outfit_detail_and_expression():
    # WS2.2: the BEAT schema the director must emit now includes both structured fields.
    assert '"outfit_detail"' in STORY_DIRECTOR_SYSTEM_PROMPT
    assert '"expression"' in STORY_DIRECTOR_SYSTEM_PROMPT


def test_director_prompt_has_kinks_work_location_nudity_plan_and_no_appearance():
    planner = VeniceScenePlanner(api_key="x")
    controls = BatchControls(start_nudity="low", max_nudity="high", story_mode=True)
    prompt = planner._build_director_user_prompt(_character(occupation="nurse"), 8, controls)
    # her kinks (raw value + phrase from ap.KINK_PHRASES)
    assert "oral_play" in prompt
    assert "sultry intimate mood" in prompt
    # occupation-anchored work location + the day/nudity structure blocks
    assert "hospital_ward" in prompt
    assert "DAY SHAPE" in prompt
    assert "NUDITY PLAN" in prompt
    # the identity firewall: the director prompt must carry NO appearance tokens
    # ("hair" is intentionally not checked — it collides with the 'hair_pulling' kink value).
    low = prompt.lower()
    for banned in ("redhead", "blonde", "brunette", "auburn", "eyes", "skin", "freckle"):
        assert banned not in low, f"appearance token leaked into director prompt: {banned!r}"


def test_parser_maps_and_scrubs_outfit_detail_and_expression():
    raw = (
        '{"story_title":"S","arcs":[{"arc_id":"a","arc_title":"A","beats":[{'
        '"beat_description":"x","location":"home_kitchen",'
        '"outfit_detail":"champagne silk pajama set, camisole and shorts",'
        '"expression":"soft sleepy smile, parted lips, sharp cheekbones"}]}]}'
    )
    scenes = _parse_arcs_json(raw)
    assert len(scenes) == 1
    # outfit_detail is mapped + scrubbed but keeps the clothing description
    assert scenes[0].outfit_detail and "silk pajama" in scenes[0].outfit_detail
    # expression keeps the mood but drops facial-FEATURE words
    expr = (scenes[0].expression or "").lower()
    assert "smile" in expr
    for feature in ("lips", "cheekbone"):
        assert feature not in expr, f"facial feature survived in expression: {feature!r}"


# --- freeform pose text (C1a): parse, scrub, persistence round-trip ---
def test_parser_maps_and_scrubs_pose_detail():
    # pose_detail carries an identity phrase AND a companion tail: the parse-time
    # identity scrub plus the plan-time strip_companions must leave only the solo,
    # identity-free body-position text.
    raw = (
        '{"story_title":"S","arcs":[{"arc_id":"a","arc_title":"A","beats":[{'
        '"beat_description":"x","location":"home_living_room","pose":"sofa",'
        '"pose_detail":"the young woman curled up on the sofa with a partner"}]}]}'
    )
    scenes = validate_and_repair(
        _parse_arcs_json(raw), _character(), 1, BatchControls(), enforce_beat_pool=False
    )
    s = scenes[0]
    assert s.pose_detail == "curled up on the sofa"
    for banned in ("young", "woman", "partner"):
        assert banned not in s.pose_detail


def test_pose_detail_round_trips_and_defaults_none_on_legacy():
    # The batch reconciler reconstructs SceneSpec(**item.scene_spec) from jsonb.
    s = SceneSpec(
        arc_id="a", arc_title="A", beat_index=0, global_index=0, beat_description="b",
        location=list(LocationType)[0], pose=list(PoseType)[0],
        pose_detail="kneeling on the rug, back arched",
    )
    dumped = s.model_dump(mode="json")
    assert dumped["pose_detail"] == "kneeling on the rug, back arched"
    assert SceneSpec.model_validate(dumped).pose_detail == "kneeling on the rug, back arched"
    # Legacy jsonb written before this field existed has no key -> defaults None.
    legacy = {k: v for k, v in dumped.items() if k != "pose_detail"}
    assert SceneSpec(**legacy).pose_detail is None


def test_director_system_prompt_declares_pose_detail_and_setting_rules():
    # C1a/C3: the BEAT schema and HARD RULES carry the new freeform-pose and
    # concrete-setting instructions.
    p = STORY_DIRECTOR_SYSTEM_PROMPT
    assert '"pose_detail"' in p
    assert '"pose_detail" (REQUIRED on every beat)' in p
    assert "the enum still selects" in p and "the pose reference image" in p
    assert "no other people, no facial-feature language" in p
    assert '"setting" (REQUIRED on every beat)' in p
    assert "LEADS the rendered background text" in p


# --- WS2: render fields are literal camera instructions, not story prose ---
def test_director_prompt_render_fields_are_literal_camera_instructions():
    # WS2: the render-bound fields (setting/activity/pose_detail/outfit_detail/expression)
    # must be governed by a literalness rule that frames them as camera instructions and
    # bans metaphor / mood-prose — the owner's complaint was flowery, unrenderable output.
    p = STORY_DIRECTOR_SYSTEM_PROMPT
    # Whitespace-normalized copy so line-wrapped phrases still match.
    flat = re.sub(r"\s+", " ", p)
    low = flat.lower()
    assert "CAMERA INSTRUCTIONS" in flat
    assert "what a camera sees, not what a narrator feels" in flat
    # the two registers are named and separated
    assert "RENDER register" in flat and "STORY register" in flat
    # metaphor + mood abstractions are explicitly banned in the render fields
    assert "metaphor" in low
    assert "mood abstractions" in low
    # the exact flavor of the reported bad output is called out as forbidden
    assert "tension easing" in low
    # at least one concrete GOOD example per render field is present
    assert "wooden desk with stacked papers" in flat        # setting GOOD
    assert "pouring coffee from a steel kettle" in flat      # activity GOOD


def test_director_prompt_keeps_display_prose_separate_from_render():
    # narrative + beat_description are gallery-only (may keep the storytelling voice);
    # the render fields must not — the prompt must state this split.
    p = STORY_DIRECTOR_SYSTEM_PROMPT
    assert "DISPLAY text shown only in the" in p
    assert "NEVER fed to the image model" in p


def test_director_prompt_examples_carry_no_banned_style_words():
    # The GOOD examples inside the prompt must not contain any BANNED_STYLE_WORDS, or we'd
    # teach the model to emit text scene_mapper._clean_scene_part drops wholesale.
    from services.prompt_constants import has_banned_style_words
    assert not has_banned_style_words(STORY_DIRECTOR_SYSTEM_PROMPT)


# --- variety-only: the orchestrator FORCES story_mode off before planning ---
def test_launch_batch_forces_story_mode_off_even_for_stale_payload():
    # An old admin payload may still carry story_mode=True. BatchLaunchService must strip it
    # to False before planning so the retired story-director path can never re-activate.
    import services.batch_orchestrator as bo
    from services.batch_orchestrator import BatchOrchestrator
    from models.batch import BatchCreate

    captured = {}

    async def _fake_plan_scenes(character, count, controls, *, settings, **kw):
        captured["story_mode"] = getattr(controls, "story_mode", None)
        scenes = DeterministicScenePlanner().plan_scenes_sync(character, count, controls)
        return scenes, "deterministic"

    orig = bo.story_planner.plan_scenes
    bo.story_planner.plan_scenes = _fake_plan_scenes
    try:
        char = _character()
        char_ns = SimpleNamespace(
            persona=char.persona, hero_image_url="https://x/img.png", bio=None,
        )

        class _FakeCharStore:
            async def get(self, cid):
                return char_ns

        class _FakeBatchStore:
            def __init__(self):
                self.batch = SimpleNamespace(id="batch-1")
                self.provider = None

            async def create_batch(self, *a, **k):
                return self.batch

            async def set_planner_provider(self, batch_id, provider):
                self.provider = provider

            async def insert_items(self, batch_id, rows):
                return rows

            async def set_batch_status(self, *a, **k):
                return None

            async def get_batch(self, batch_id):
                return self.batch

        settings = SimpleNamespace(
            RUNPOD_AVG_STEP_SECONDS=5, BATCH_WORKER_POOL_SIZE=3, RUNPOD_GPU_USD_PER_SECOND=0.0,
        )
        store = _FakeBatchStore()
        orch = BatchOrchestrator(
            job_manager=None, character_store=_FakeCharStore(), batch_store=store, settings=settings,
        )
        body = BatchCreate(
            count=4, controls=BatchControls(story_mode=True, base_seed=1), dry_run=True,
        )
        asyncio.run(orch.launch_batch("char-1", body))
        assert captured["story_mode"] is False, "orchestrator must force story_mode off before planning"
        assert store.provider == "deterministic", "resolved planner provider must be persisted"
    finally:
        bo.story_planner.plan_scenes = orig


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
