"""
WS-S — Style fidelity regression suite.

Covers the style-fidelity work end to end:
  * palette scope: a character's color palette + styled room reach ONLY home-ish
    scenes (scene_mapper gate), never a cafe/street/gym;
  * codeformer dial: natural/candid_phone default the pose-step ReActor gentler
    (0.2 / 0.7) unless the admin set an explicit value;
  * face-ref rewire: scene_mapper threads the sharp hero as faceRefImage, both pose
    graphs swap the face from the dedicated node 210 (falling back to the source),
    and the pipeline worker threads a staged face-ref name onto node 210;
  * junk fix: no "{state} expression" garbage for the A2 candid/camera-aware pool;
  * pose de-bloat: a representative batch pose positive stays under budget with all
    load-bearing content, and the generic clause is dropped only when anchors carry it;
  * style clause LEADS the edit positive.

Runs under pytest or directly: python loli_api/tests/test_style_fidelity.py
"""
import asyncio
import json
from pathlib import Path

import models.requests as _mr

# These tests exercise mapping/prompt logic, not the SSRF allowlist.
_mr.validate_source_image = lambda u: u  # type: ignore

from models.enums import (
    PoseType, NudityLevel, LocationType, TimeOfDayType, LightingType,
    PhotoStyleType, PaletteType, InteriorStyleType,
)
from models.requests import PersonaOptions, PipelineEditRequest
from models.batch import BatchControls
from models.scene import SceneSpec
from services import scene_vocab as sv
from services import prompt_constants as pc
from services.scene_mapper import scene_to_pipeline_request
from services.story_planner import (
    Character, _BATCH_EXPRESSIONS_CANDID, _BATCH_EXPRESSIONS_CAMERA_AWARE,
)
from api.v1.endpoints.pose import build_pose_prompt, prepare_pose_workflow

_WF_DIR = Path(__file__).resolve().parent.parent / "workflows"


def _character(**persona_kw):
    base = dict(
        ethnicity="japanese", age=28, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Stella",
        occupation="model", relationship="girlfriend",
    )
    base.update(persona_kw)
    return Character(
        persona=PersonaOptions(**base), hero_photo_url="https://x.supabase.co/hero.png"
    )


def _scene(location, **kw):
    base = dict(
        arc_id="a", arc_title="A", beat_index=0, global_index=0, beat_description="b",
        location=location, time_of_day=TimeOfDayType.DAYTIME,
        lighting=LightingType.BRIGHT_DAYLIGHT, pose=PoseType.SITTING,
    )
    base.update(kw)
    return SceneSpec(**base)


# ---------------------------------------------------------------------------
# Palette / styled-room scope (WS-S deliverable 2)
# ---------------------------------------------------------------------------
def test_palette_and_styled_room_reach_home_scenes_only():
    ctl = BatchControls(
        interior_style=InteriorStyleType.LUXURY_GLAM, color_palette=PaletteType.BOLD_DARK,
    )
    char = _character()
    pal = sv.PALETTE_PHRASES[PaletteType.BOLD_DARK]

    home = scene_to_pipeline_request(char, _scene(LocationType.HOME_BEDROOM), ctl)
    assert pal in home.prompt
    assert sv.styled_room_phrase(
        InteriorStyleType.LUXURY_GLAM, LocationType.HOME_BEDROOM
    ) in home.prompt

    for loc in (LocationType.CAFE, LocationType.CITY_STREET, LocationType.GYM):
        req = scene_to_pipeline_request(char, _scene(loc), ctl)
        assert pal not in req.prompt, f"palette leaked to {loc.value}"
        assert sv.LOCATION_PHRASES[loc.value] in req.prompt  # generic phrase stands


def test_is_home_like_location_derives_from_interior_rooms():
    # Single source of truth: every INTERIOR_ROOM_PHRASES key is home-like; nothing else.
    room_keys = set().union(*(set(r) for r in sv.INTERIOR_ROOM_PHRASES.values()))
    assert sv.HOME_LIKE_LOCATIONS == frozenset(room_keys)
    for loc in (LocationType.HOME_BEDROOM, LocationType.HOTEL_ROOM, LocationType.HOME_KITCHEN):
        assert sv.is_home_like_location(loc)
    for loc in (LocationType.CAFE, LocationType.CITY_STREET, LocationType.BEACH, LocationType.OFFICE):
        assert not sv.is_home_like_location(loc)
    assert sv.is_home_like_location("home_bedroom") and not sv.is_home_like_location("cafe")


# ---------------------------------------------------------------------------
# Codeformer dial (WS-S deliverable 3)
# ---------------------------------------------------------------------------
def test_codeformer_dial_for_soft_styles_when_unset():
    char = _character()
    for style in (PhotoStyleType.NATURAL, PhotoStyleType.CANDID_PHONE):
        req = scene_to_pipeline_request(
            char, _scene(LocationType.CAFE), BatchControls(photo_style=style)
        )
        assert req.reactorCodeformerWeight == 0.2, style
        assert req.reactorRestoreVisibility == 0.7, style


def test_codeformer_dial_off_for_polished_and_explicit_wins():
    char = _character()
    polished = scene_to_pipeline_request(
        char, _scene(LocationType.CAFE), BatchControls(photo_style=PhotoStyleType.POLISHED)
    )
    assert polished.reactorCodeformerWeight is None
    assert polished.reactorRestoreVisibility is None
    # An explicit admin value wins even on a soft style.
    explicit = scene_to_pipeline_request(
        char, _scene(LocationType.CAFE),
        BatchControls(
            photo_style=PhotoStyleType.NATURAL,
            reactor_codeformer_weight=0.5, reactor_restore_visibility=0.9,
        ),
    )
    assert explicit.reactorCodeformerWeight == 0.5
    assert explicit.reactorRestoreVisibility == 0.9


# ---------------------------------------------------------------------------
# Face-reference rewire (WS-S coordinator addition A)
# ---------------------------------------------------------------------------
def test_scene_mapper_threads_hero_as_face_ref_even_off_a_nude_base():
    char = _character()
    char.nude_base_url = "https://x.supabase.co/nude.png"  # source is the nude base…
    req = scene_to_pipeline_request(char, _scene(LocationType.HOME_BEDROOM), BatchControls())
    assert req.source_image == "https://x.supabase.co/nude.png"
    # …but the ReActor face donor is ALWAYS the sharp original hero.
    assert req.faceRefImage == "https://x.supabase.co/hero.png"


def test_prepare_pose_workflow_sets_face_donor_node_210_both_graphs():
    for name in ("pose_2511_API.json", "edit_pose_action.json"):
        with open(_WF_DIR / name, "r", encoding="utf-8") as f:
            g = json.load(f)
        # The graph JSON wires the ReActor donor to the dedicated node 210.
        assert g["200"]["inputs"]["source_image"] == ["210", 0], name
        with_ref = prepare_pose_workflow(g, "src.png", "ref.png", face_ref_image="hero.png")
        assert with_ref["210"]["inputs"]["image"] == "hero.png", name
        # Fallback: no face ref -> node 210 == the step source (donor==source, as before).
        without = prepare_pose_workflow(g, "src.png", "ref.png")
        assert without["210"]["inputs"]["image"] == "src.png", name


def test_pipeline_pose_step_threads_face_ref_into_node_210():
    from workers.pipeline_worker import PipelineBackgroundWorker

    w = PipelineBackgroundWorker(
        job_manager=None, comfyui_client=None, storage_service=None,
        pose_workflow_path=str(_WF_DIR / "pose_2511_API.json"),
        outfit_workflow_path=str(_WF_DIR / "test_final_API.json"),
        background_workflow_path=str(_WF_DIR / "test_final_API.json"),
    )
    asyncio.run(w._load_workflows())
    req = PipelineEditRequest(
        source_image="https://x.supabase.co/s.png", pose=PoseType.SITTING,
        faceRefImage="https://x.supabase.co/hero.png",
    )
    wf = w._build_step_workflow(
        "pose", req, "src.png", 1, "job", pose_ref_name="ref.png", face_ref_name="faceref.png",
    )
    assert wf["210"]["inputs"]["image"] == "faceref.png"
    # No staged face ref -> node 210 falls back to the step source.
    wf2 = w._build_step_workflow("pose", req, "src.png", 1, "job", pose_ref_name="ref.png")
    assert wf2["210"]["inputs"]["image"] == "src.png"


# ---------------------------------------------------------------------------
# Expression junk regression (WS-S deliverable 4)
# ---------------------------------------------------------------------------
def test_no_expression_junk_across_a2_pool():
    pool = list(_BATCH_EXPRESSIONS_CANDID) + list(_BATCH_EXPRESSIONS_CAMERA_AWARE)
    assert pool  # guard against an empty import
    for state in pool:
        p = build_pose_prompt(
            PoseType.SITTING, expression=state, activity="pouring coffee",
            lighting="moody_dim", time_of_day="night", location="home_kitchen",
        )
        assert "doing expression" not in p, state
        assert "expression expression" not in p, state
        assert ", ," not in p, state
        assert f"her expression: {state}" in p, state


# ---------------------------------------------------------------------------
# Pose de-bloat + style lead (WS-S deliverables 1 & 5)
# ---------------------------------------------------------------------------
def test_representative_batch_pose_is_debloated_and_complete():
    anchors = (
        "warm dark-brown skin, straight blonde hair, green eyes, "
        "curvy build with medium breasts"
    )
    p = build_pose_prompt(
        PoseType.STANDING_LEANING,
        activity="pouring her first coffee",
        expression="focused on what she's doing",
        lighting="moody_dim", time_of_day="night",
        outfit_text="a velvet wrap dress",
        location="home_kitchen",
        pose_detail="leaning against the kitchen counter, weight on one hip",
        identity_anchors=anchors,
    )
    assert len(p) < 1000  # target <= 900 after de-bloat
    # Generic clause dropped: the concrete anchors carry the same content.
    assert pc.POSE_IDENTITY_CLAUSE not in p
    # All load-bearing content still present.
    assert "leaning against the kitchen counter" in p            # pose
    assert anchors in p                                          # anchors
    assert "keep her state of dress" in p                        # outfit continuity
    assert "completely alone in the frame" in p                  # solo
    assert "her expression: focused on what she's doing" in p    # clean expression
    # No junk.
    assert "doing expression" not in p and ", ," not in p and ".," not in p
    # Style clause LEADS the wrapped positive, body preserved.
    wrapped = pc.apply_edit_photo_style(p, PhotoStyleType.NATURAL)
    assert wrapped.startswith(pc.EDIT_PHOTO_STYLE_SUFFIXES["natural"])
    assert p in wrapped


def test_generic_identity_clause_kept_when_no_anchors():
    p = build_pose_prompt(PoseType.SITTING)
    assert pc.POSE_IDENTITY_CLAUSE in p


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
