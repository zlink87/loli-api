"""
Tests for story-driven batches (Feature 2): story JSON parsing, narrative identity
scrub, deterministic story fallback, render-field repair with narrative present,
narrative excluded from the render prompt, NSFW gating, and story assembly.

Runs under pytest or directly: python loli_api/tests/test_story_mode.py
"""
import asyncio
from types import SimpleNamespace

# The mapper SSRF-validates source_image; these tests exercise narrative/mapping,
# not the allowlist, so make the validator a passthrough (mirrors test_scene_mapper).
import models.requests as _mr
_mr.validate_source_image = lambda u: u  # type: ignore

from models.requests import PersonaOptions
from models.batch import BatchControls, assemble_story, BatchItemRead
from models.scene import SceneSpec
from models.enums import OutfitType, LocationType, PoseType
from services.story_planner import (
    Character, DeterministicScenePlanner, validate_and_repair, plan_scenes, _parse_arcs_json,
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
