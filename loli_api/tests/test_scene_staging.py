"""
SCENE STAGING (WS-STAGE) — staging phrases + public-venue solo policy.

Live failures driving this (07-13 prod batch):
  1. "Bodycon Dress · Sitting Legs Wide Open" at a nightclub rendered as the girl
     sitting cross-legged barefoot ON THE BAR COUNTER — the scene text named only
     the venue, so the full-frame pose re-diffusion improvised an absurd seat.
  2. The pose prompt demanded "completely alone … no other people" even for a
     NIGHTCLUB — a baked-in contradiction the model split by rendering a crowd anyway.

Covers:
  s1  pose-class map covers every PoseType; classes come from the known set
  s2  STAGING_PHRASES covers every LocationType; class keys valid; pools non-empty
  s3  phrase hygiene: lowercase comma-fragments, <=160 chars, no person nouns
      (word-boundary: man/woman/people/crowd/…), no identity/clothing/nudity vocab,
      no absurd seats (never sitting ON a countertop/table)
  s4  staging_options: pose bucketed FIRST (a sitting pose only ever draws a sitting
      anchor); missing (location x class) -> () clean skip; unknown inputs -> ()
  s5  planner: seeded 24-item plan -> staging deterministic (same seed -> same),
      always from the FINAL (location, pose-class) pool, SITTING/LYING anchored
      wherever a pool exists, class-mismatch -> None, and the assignment perturbs NO
      other seeded field (new draws ride a dedicated offset RNG)
  s6  SceneSpec.staging round-trips through jsonb; legacy dict without key -> None
  s7  build_scene_background_text: staging joins right after the location phrase;
      None -> byte-identical output (back-compat)
  s8  scene_mapper: stagingText threaded onto the request; background prompt carries
      the phrase once; single-pass composed prompt carries it once; no staging -> None
  s9  build_pose_prompt: multi-step target-pose sentence gains the staging once;
      single-pass (scene_text set) suppresses the duplicate append; staging=None ->
      byte-identical base prompt
  s10 solo policy: public venue -> background-strangers clause (and NOT "completely
      alone"); private venue / no location -> strict clause; HIGH nudity or a
      naked-class outfit_text -> strict EVERYWHERE (nudity guard)
  s11 PUBLIC_VENUE_LOCATIONS membership sanity (nightclub/cafe/beach/… in;
      home_*/hotel_room/photo_studio/car_interior out); is_public_venue coercion
  s12 pipeline worker integration: stagingText + nudityLevel ride the request into
      node 114 (multi-step staging append; public-venue clause; HIGH stays strict)

Runs under pytest or directly: python loli_api/tests/test_scene_staging.py
"""
import asyncio
import re
from pathlib import Path

import models.requests as _mr

# These tests exercise planner/prompt logic, not the SSRF allowlist.
_mr.validate_source_image = lambda u: u  # type: ignore

from models.enums import (
    PoseType, OutfitType, NudityLevel, LocationType, TimeOfDayType, LightingType,
)
from models.requests import PersonaOptions, PipelineEditRequest
from models.batch import BatchControls
from models.scene import SceneSpec
from services import scene_vocab as sv
from services import story_planner as sp
from services.scene_mapper import scene_to_pipeline_request
from services.story_planner import Character, DeterministicScenePlanner, validate_and_repair
from api.v1.endpoints.pose import build_pose_prompt, _pose_keeps_strict_solo
from workers.pipeline_worker import PipelineBackgroundWorker

_WF_DIR = Path(__file__).resolve().parent.parent / "workflows"

_STRICT_SOLO = "She is completely alone in the frame — exactly one person, no other people"
_PUBLIC_SOLO = (
    "She is the clear subject, sharp and in focus; any other people are anonymous "
    "strangers in the soft-focus background, never interacting with her, never "
    "touching her, no other person near the camera"
)

_ALL_CLASSES = {
    sv.POSE_CLASS_SITTING, sv.POSE_CLASS_STANDING, sv.POSE_CLASS_LYING,
    sv.POSE_CLASS_KNEELING, sv.POSE_CLASS_ATHLETIC, sv.POSE_CLASS_OTHER,
    sv.POSE_CLASS_MOTION,  # POSE PACK (07-14): walking/dancing/stretching/turning
}


def _character():
    persona = PersonaOptions(
        name="Stage", style="realistic", ethnicity="caucasian", age=25,
        eyeColor="green", hairStyle="straight", hairColor="blonde",
        bodyType="curvy", breastSize="medium", personality="lover",
        occupation="model", relationship="girlfriend",
    )
    return Character(persona=persona, hero_photo_url="https://x.supabase.co/hero.png")


def _planned(seed=1234, count=24, **ctrl):
    controls = BatchControls(base_seed=seed, max_nudity=NudityLevel.HIGH, **ctrl)
    scenes = DeterministicScenePlanner().plan_scenes_sync(_character(), count, controls)
    return validate_and_repair(scenes, _character(), count, controls)


def _scene(**kw):
    base = dict(
        arc_id="a", arc_title="A", beat_index=0, global_index=0, beat_description="b",
        location=LocationType.NIGHTCLUB, time_of_day=TimeOfDayType.NIGHT,
        lighting=LightingType.NEON,
    )
    base.update(kw)
    return SceneSpec(**base)


# ---------------------------------------------------------------------------
# s1 — pose-class map covers every PoseType
# ---------------------------------------------------------------------------
def test_pose_class_covers_every_pose():
    for p in PoseType:
        assert p.value in sv._POSE_CLASS, f"PoseType.{p.name} missing from _POSE_CLASS"
        assert sv._POSE_CLASS[p.value] in _ALL_CLASSES
    # Spot-check the buckets the staging pools key off.
    assert sv.pose_class(PoseType.SITTING_LEGS_WIDE_OPEN) == sv.POSE_CLASS_SITTING
    assert sv.pose_class(PoseType.SOFA) == sv.POSE_CLASS_SITTING
    assert sv.pose_class(PoseType.STANDING_LEANING) == sv.POSE_CLASS_STANDING
    assert sv.pose_class(PoseType.HANDS_BEHIND_HEAD) == sv.POSE_CLASS_STANDING
    assert sv.pose_class(PoseType.LYING_BACK) == sv.POSE_CLASS_LYING
    assert sv.pose_class(PoseType.SPREAD_LEGS) == sv.POSE_CLASS_LYING
    assert sv.pose_class(PoseType.KNEELING) == sv.POSE_CLASS_KNEELING
    assert sv.pose_class(PoseType.ALL_FOURS) == sv.POSE_CLASS_KNEELING
    assert sv.pose_class(PoseType.JOGGING) == sv.POSE_CLASS_ATHLETIC
    assert sv.pose_class(PoseType.COOKING) == sv.POSE_CLASS_OTHER
    # Unknown / None -> OTHER (never a crash, never a staged anchor).
    assert sv.pose_class("not_a_pose") == sv.POSE_CLASS_OTHER
    assert sv.pose_class(None) == sv.POSE_CLASS_OTHER
    print("s1 OK: every PoseType classed; buckets as designed; unknown -> OTHER")


# ---------------------------------------------------------------------------
# s2 — STAGING_PHRASES coverage + shape
# ---------------------------------------------------------------------------
def test_staging_phrases_cover_every_location():
    for loc in LocationType:
        assert loc.value in sv.STAGING_PHRASES, f"LocationType.{loc.name} missing"
        pools = sv.STAGING_PHRASES[loc.value]
        assert pools, f"{loc.value} has an empty class map"
        for cls, phrases in pools.items():
            assert cls in _ALL_CLASSES, f"{loc.value} keys unknown class {cls!r}"
            assert isinstance(phrases, tuple) and phrases, f"{loc.value}/{cls} pool empty"
    # SITTING + STANDING are the anchoring classes — present at (almost) every location;
    # car_interior is the sole deliberate STANDING skip (no one stands inside a car).
    for loc in LocationType:
        assert sv.POSE_CLASS_SITTING in sv.STAGING_PHRASES[loc.value], loc.value
        if loc is not LocationType.CAR_INTERIOR:
            assert sv.POSE_CLASS_STANDING in sv.STAGING_PHRASES[loc.value], loc.value
    # LYING only where a real reclining surface exists — private interiors, beach, etc.
    for loc_val in ("home_bedroom", "hotel_room", "beach", "poolside", "home_living_room"):
        assert sv.POSE_CLASS_LYING in sv.STAGING_PHRASES[loc_val], loc_val
    for loc_val in ("nightclub", "cafe", "city_street", "classroom", "office"):
        assert sv.POSE_CLASS_LYING not in sv.STAGING_PHRASES[loc_val], loc_val
    print("s2 OK: all locations covered; sitting/standing anchored; lying only where sane")


# ---------------------------------------------------------------------------
# s3 — phrase hygiene
# ---------------------------------------------------------------------------
# Person nouns (a staging phrase must never ADD people) — word-boundary matched so
# "ottoman" never trips on the "man" substring.
_PERSON_WORDS = (
    "man", "men", "woman", "women", "people", "person", "crowd", "crowds",
    "stranger", "strangers", "guy", "guys", "girl", "girls", "lady", "couple",
    "friend", "friends", "partner", "bystander", "bystanders", "onlooker",
    "onlookers", "passersby",
)
# Identity / clothing / nudity vocab — staging is scenery ONLY.
_IDENTITY_CLOTHING_WORDS = (
    "hair", "eyes", "skin", "face", "facial", "dress", "dressed", "outfit",
    "garment", "clothing", "clothes", "naked", "nude", "topless", "lingerie",
    "bikini", "breast", "breasts", "cleavage", "blonde", "brunette", "barefoot",
)


def _word_in(word: str, text: str) -> bool:
    return re.search(r"\b" + re.escape(word) + r"\b", text) is not None


def test_staging_phrase_hygiene():
    for loc_val, pools in sv.STAGING_PHRASES.items():
        for cls, phrases in pools.items():
            for ph in phrases:
                ctx = f"{loc_val}/{cls}: {ph!r}"
                assert ph == ph.strip(), f"edge whitespace — {ctx}"
                assert 0 < len(ph) <= 160, f"length — {ctx}"
                assert ph == ph.lower(), f"not lowercase — {ctx}"
                assert not ph.endswith("."), f"trailing period (must be a fragment) — {ctx}"
                assert not ph.startswith(","), f"leading comma — {ctx}"
                for w in _PERSON_WORDS:
                    assert not _word_in(w, ph), f"person noun {w!r} — {ctx}"
                for w in _IDENTITY_CLOTHING_WORDS:
                    assert not _word_in(w, ph), f"identity/clothing token {w!r} — {ctx}"
    # The reported absurdity is impossible by construction: no SITTING phrase ever seats
    # her ON a counter/countertop/table/desk/bar SURFACE — the seat verb must never
    # directly precede one of those surfaces. "perched on a bar stool" is the GOOD case
    # (a stool AT the counter -> the "<surface> stool" lookahead), and an OBJECT resting
    # "on the table" ("… with a drink on the table") is fine because no seat verb
    # precedes it.
    absurd_seat = re.compile(
        r"\b(?:sitting|seated|perched|sat) on (?:the|a) "
        r"(?:bar counter|countertop|counter|tabletop|table|desk|bar)\b(?!\s+stool)"
    )
    for loc_val, pools in sv.STAGING_PHRASES.items():
        for ph in pools.get(sv.POSE_CLASS_SITTING, ()):
            assert not absurd_seat.search(ph), f"absurd seat — {loc_val}: {ph!r}"
    print("s3 OK: fragments lowercase/<=160; no person/identity/clothing tokens; no absurd seats")


# ---------------------------------------------------------------------------
# s4 — staging_options coherence guard
# ---------------------------------------------------------------------------
def test_staging_options_bucket_by_pose_class_and_skip_cleanly():
    # A sitting pose at a nightclub draws ONLY from the nightclub sitting pool.
    opts = sv.staging_options(LocationType.NIGHTCLUB, PoseType.SITTING_LEGS_WIDE_OPEN)
    assert opts == sv.STAGING_PHRASES["nightclub"][sv.POSE_CLASS_SITTING]
    # A lying pose at a nightclub has NO pool -> clean skip (never relocated here).
    assert sv.staging_options(LocationType.NIGHTCLUB, PoseType.LYING_BACK) == ()
    assert sv.staging_options("nightclub", "lying_stomach") == ()
    # OTHER-class poses (their description already names the surface) are unstaged.
    assert sv.staging_options(LocationType.HOME_KITCHEN, PoseType.COOKING) == ()
    # Raw values accepted; unknown location/pose/None -> ().
    assert sv.staging_options("beach", "lying_back") == sv.STAGING_PHRASES["beach"][sv.POSE_CLASS_LYING]
    assert sv.staging_options("not_a_place", PoseType.SITTING) == ()
    assert sv.staging_options(LocationType.BEACH, None) == ()
    print("s4 OK: pose bucketed first; missing combos and unknowns skip cleanly")


# ---------------------------------------------------------------------------
# s5 — planner assignment: deterministic, final-state-coherent, non-perturbing
# ---------------------------------------------------------------------------
def test_planner_staging_deterministic_and_matches_final_state():
    a, b = _planned(seed=1234), _planned(seed=1234)
    assert [s.staging for s in a] == [s.staging for s in b], "same seed must reproduce stagings"

    staged = 0
    for s in a:
        opts = sv.staging_options(s.location, s.pose)
        if opts:
            # Always drawn from the FINAL (location, pose-class) pool — the coherence guard.
            assert s.staging in opts, (s.location, s.pose, s.staging)
            staged += 1
        else:
            assert s.staging is None, (s.location, s.pose, s.staging)
        if s.staging:
            cls = sv.pose_class(s.pose)
            assert s.staging in sv.STAGING_PHRASES[s.location.value][cls]
            assert len(s.staging) <= 160
    assert staged > 0, "a 24-item plan should stage at least one scene"

    # Every SITTING/LYING scene in a location that HAS that class pool is anchored.
    for s in a:
        cls = sv.pose_class(s.pose)
        if cls in (sv.POSE_CLASS_SITTING, sv.POSE_CLASS_LYING) and \
                sv.STAGING_PHRASES.get(s.location.value, {}).get(cls):
            assert s.staging, f"unanchored {cls} at {s.location.value}"

    # A different seed produces a different staging sequence (not a constant).
    assert [s.staging for s in _planned(seed=999)] != [s.staging for s in a]
    print("s5a OK: deterministic; final-state coherent; sitting/lying anchored where pools exist")


def test_planner_staging_perturbs_no_other_seeded_field():
    # Monkeypatch the assignment out, re-run the same seed, and diff everything else:
    # byte-identical -> the staging draw added NO new RNG consumption to existing picks.
    orig = sp._assign_staging
    try:
        sp._assign_staging = lambda scenes, controls: None
        without = _planned(seed=1234)
    finally:
        sp._assign_staging = orig
    with_staging = _planned(seed=1234)
    for x, y in zip(without, with_staging):
        dx, dy = x.model_dump(), y.model_dump()
        dx.pop("staging"), dy.pop("staging")
        assert dx == dy, "staging assignment shifted an existing seeded pick"
    print("s5b OK: staging assignment leaves every existing seeded field byte-identical")


# ---------------------------------------------------------------------------
# s6 — SceneSpec.staging persistence round-trip + legacy default
# ---------------------------------------------------------------------------
def test_scene_spec_staging_round_trips_and_defaults_none_on_legacy():
    s = _scene(pose=PoseType.SITTING, staging="perched on a bar stool at the counter")
    dumped = s.model_dump(mode="json")
    assert dumped["staging"] == "perched on a bar stool at the counter"
    assert SceneSpec.model_validate(dumped).staging == "perched on a bar stool at the counter"
    # Legacy jsonb written before this field existed has no key -> defaults None.
    legacy = {k: v for k, v in dumped.items() if k != "staging"}
    assert SceneSpec(**legacy).staging is None
    print("s6 OK: staging round-trips through jsonb; legacy dicts default None")


# ---------------------------------------------------------------------------
# s7 — build_scene_background_text placement + back-compat
# ---------------------------------------------------------------------------
def test_background_text_staging_joins_after_location_phrase():
    txt = sv.build_scene_background_text(
        location=LocationType.NIGHTCLUB,
        time_of_day=TimeOfDayType.NIGHT,
        lighting=LightingType.NEON,
        staging="perched on a bar stool at the counter",
    )
    loc = sv.location_phrase(LocationType.NIGHTCLUB)
    # Staging sits IMMEDIATELY after the location phrase, before time/lighting.
    assert f"{loc}, perched on a bar stool at the counter, late at night" in txt
    # None / empty -> byte-identical to the pre-staging composition.
    base = sv.build_scene_background_text(
        location=LocationType.NIGHTCLUB, time_of_day=TimeOfDayType.NIGHT,
        lighting=LightingType.NEON,
    )
    assert sv.build_scene_background_text(
        location=LocationType.NIGHTCLUB, time_of_day=TimeOfDayType.NIGHT,
        lighting=LightingType.NEON, staging=None,
    ) == base
    assert sv.build_scene_background_text(
        location=LocationType.NIGHTCLUB, time_of_day=TimeOfDayType.NIGHT,
        lighting=LightingType.NEON, staging="   ",
    ) == base
    print("s7 OK: staging placed right after the location phrase; None/blank byte-identical")


# ---------------------------------------------------------------------------
# s8 — scene_mapper threading (multi-step + single-pass)
# ---------------------------------------------------------------------------
def test_mapper_threads_staging_into_prompt_and_request():
    char = _character()
    scene = _scene(
        pose=PoseType.SITTING_LEGS_WIDE_OPEN, outfit=OutfitType.BODYCON_DRESS,
        nudityLevel=NudityLevel.MEDIUM, staging="perched on a bar stool at the counter",
    )
    req = scene_to_pipeline_request(char, scene, BatchControls(max_nudity=NudityLevel.MEDIUM))
    assert req.stagingText == "perched on a bar stool at the counter"
    # Background text carries the phrase exactly once, right after the location phrase.
    assert (req.prompt or "").count("perched on a bar stool at the counter") == 1
    assert "a vibrant nightclub with colored lights and a crowd, perched on a bar stool" in req.prompt

    # No staging -> None threaded, composition byte-identical to a staging-less scene.
    bare = scene.model_copy(update={"staging": None})
    req_bare = scene_to_pipeline_request(char, bare, BatchControls(max_nudity=NudityLevel.MEDIUM))
    assert req_bare.stagingText is None
    assert "bar stool" not in (req_bare.prompt or "")
    print("s8a OK: stagingText + background prompt threaded; None threads nothing")


def test_mapper_single_pass_scene_text_carries_staging_once():
    char = _character()
    char.nude_base_url = "https://x.supabase.co/nude.png"
    scene = _scene(
        pose=PoseType.SITTING_LEGS_WIDE_OPEN, outfit=OutfitType.BODYCON_DRESS,
        nudityLevel=NudityLevel.MEDIUM, staging="perched on a bar stool at the counter",
    )
    req = scene_to_pipeline_request(
        char, scene, BatchControls(max_nudity=NudityLevel.MEDIUM), single_pass=True,
    )
    assert req.singlePassEdit is True
    assert (req.prompt or "").count("perched on a bar stool at the counter") == 1

    # The single-pass pose positive (scene_text = request.prompt) then carries it exactly
    # once too: it rides "Place her in: …" and the target-pose append is suppressed.
    p = build_pose_prompt(
        req.pose, scene_text=req.prompt, staging=req.stagingText,
        location=req.location, nudity_level=req.nudityLevel, dress_mode=True,
        outfit_text="a fitted dress",
    )
    assert p.count("perched on a bar stool at the counter") == 1
    assert "Place her in:" in p
    print("s8b OK: single-pass carries the staging phrase exactly once (no duplication)")


# ---------------------------------------------------------------------------
# s9 — build_pose_prompt staging append (multi-step) + back-compat
# ---------------------------------------------------------------------------
def test_pose_prompt_staging_appends_to_target_pose_sentence():
    p = build_pose_prompt(
        PoseType.SITTING_LEGS_WIDE_OPEN, location="nightclub",
        staging="perched on a bar stool at the counter",
    )
    # The target-pose sentence itself names the seat.
    assert (
        "The target pose is: sitting with legs spread wide open, provocative seated "
        "pose, perched on a bar stool at the counter." in p
    )
    assert p.count("perched on a bar stool at the counter") == 1

    # pose_detail + staging compose (detail replaces the enum text; staging still appends).
    p2 = build_pose_prompt(
        PoseType.SITTING, pose_detail="sitting with one knee drawn up",
        staging="seated in a corner booth with drinks on the table",
    )
    assert (
        "The target pose is: sitting with one knee drawn up, seated in a corner booth "
        "with drinks on the table." in p2
    )

    # None/blank staging -> byte-identical to the pre-staging prompt.
    base = build_pose_prompt(PoseType.SITTING, location="home_bedroom")
    assert build_pose_prompt(PoseType.SITTING, location="home_bedroom", staging=None) == base
    assert build_pose_prompt(PoseType.SITTING, location="home_bedroom", staging="  ") == base
    print("s9 OK: staging joins the target-pose sentence once; None/blank byte-identical")


# ---------------------------------------------------------------------------
# s10 — solo policy by venue + nudity guard
# ---------------------------------------------------------------------------
def test_solo_policy_public_private_and_nudity_guard():
    # Public venue, non-explicit -> background-strangers clause, strict clause GONE.
    club = build_pose_prompt(
        PoseType.SITTING, location="nightclub", nudity_level=NudityLevel.MEDIUM,
    )
    assert _PUBLIC_SOLO in club
    assert "completely alone" not in club

    # Private venue -> the exact strict clause, strangers clause absent.
    bedroom = build_pose_prompt(
        PoseType.SITTING, location="home_bedroom", nudity_level=NudityLevel.MEDIUM,
    )
    assert _STRICT_SOLO in bedroom
    assert "anonymous strangers" not in bedroom

    # NUDITY GUARD: HIGH keeps strict even at a public venue — never a crowd around
    # explicit content.
    club_high = build_pose_prompt(
        PoseType.SITTING, location="nightclub", nudity_level=NudityLevel.HIGH,
    )
    assert _STRICT_SOLO in club_high and _PUBLIC_SOLO not in club_high

    # Naked-class outfit_text (NAKED-tier continuity prose) keeps strict too, at any level.
    club_naked = build_pose_prompt(
        PoseType.SITTING, location="nightclub", nudity_level=NudityLevel.MEDIUM,
        outfit_text="completely naked, fully nude, bare breasts exposed",
    )
    assert _STRICT_SOLO in club_naked and _PUBLIC_SOLO not in club_naked
    # …while a DRESSED garment ("wearing …") does not trip the guard.
    assert _pose_keeps_strict_solo(NudityLevel.MEDIUM, "wearing a bodycon dress") is False
    assert _pose_keeps_strict_solo(NudityLevel.HIGH, None) is True
    assert _pose_keeps_strict_solo("high", None) is True          # raw value accepted
    assert _pose_keeps_strict_solo(None, "topless, bare chest") is True
    assert _pose_keeps_strict_solo(None, None) is False

    # No location (interactive /v1/edit/pose) -> strict, byte-identical back-compat.
    bare = build_pose_prompt(PoseType.SITTING)
    assert _STRICT_SOLO in bare and bare.endswith("no other people.")
    assert build_pose_prompt(PoseType.SITTING, nudity_level=NudityLevel.LOW) == bare
    print("s10 OK: public->strangers clause; private/none->strict; HIGH/naked-class->strict everywhere")


def test_solo_policy_uses_outfit_enum_over_prose_prefix():
    # FIX: outfit_continuity_text can PREPEND a caption detail, so the NAKED-tier prose no
    # longer starts with a state-of-undress word — a prose-prefix sniff would wrongly place a
    # soft-focus crowd around explicit content. Threading the outfit ENUM fixes it.
    caption_prefixed = "a sheer open wrap, topless with bare breasts exposed"
    # the prose-prefix fallback is DEFEATED (the text starts with "a sheer open wrap"):
    assert _pose_keeps_strict_solo(NudityLevel.REVEALING, caption_prefixed) is False
    # …but with the NAKED enum threaded the guard holds — strict even at REVEALING (not HIGH).
    assert _pose_keeps_strict_solo(
        NudityLevel.REVEALING, caption_prefixed, OutfitType.NAKED.value
    ) is True
    club_naked = build_pose_prompt(
        PoseType.SITTING, location="nightclub", nudity_level=NudityLevel.REVEALING,
        outfit_text=caption_prefixed, outfit_enum=OutfitType.NAKED.value,
    )
    assert _STRICT_SOLO in club_naked and _PUBLIC_SOLO not in club_naked

    # A DRESSED outfit enum at a public venue -> the crowd clause (not strict).
    club_dressed = build_pose_prompt(
        PoseType.SITTING, location="nightclub", nudity_level=NudityLevel.MEDIUM,
        outfit_text="wearing a fitted bodycon dress", outfit_enum=OutfitType.BODYCON_DRESS.value,
    )
    assert _PUBLIC_SOLO in club_dressed and "completely alone" not in club_dressed

    # enum-less fallback still works (interactive callers thread no enum).
    assert _pose_keeps_strict_solo(NudityLevel.MEDIUM, "topless, bare chest", None) is True
    assert _pose_keeps_strict_solo(NudityLevel.MEDIUM, "wearing a coat", None) is False
    print("s10b OK: outfit_enum drives NAKED strict-solo over a caption-prefixed prose; fallback intact")


# ---------------------------------------------------------------------------
# s11 — PUBLIC_VENUE_LOCATIONS membership sanity
# ---------------------------------------------------------------------------
def test_public_venue_membership():
    public = {
        LocationType.NIGHTCLUB, LocationType.CAFE, LocationType.RESTAURANT,
        LocationType.BAR, LocationType.CITY_STREET, LocationType.BEACH,
        LocationType.PARK, LocationType.GYM, LocationType.OFFICE,
        LocationType.CLASSROOM, LocationType.POOLSIDE, LocationType.LUXURY_LOUNGE,
        LocationType.ROOFTOP, LocationType.LIBRARY, LocationType.SALON,
        LocationType.STAGE, LocationType.HOSPITAL_WARD, LocationType.YOGA_STUDIO,
        LocationType.RESTAURANT_KITCHEN,
    }
    private = {
        LocationType.HOME_BEDROOM, LocationType.HOME_LIVING_ROOM,
        LocationType.HOME_KITCHEN, LocationType.HOME_BATHROOM,
        LocationType.HOME_BALCONY, LocationType.HOME_OFFICE,
        LocationType.HOTEL_ROOM, LocationType.PHOTO_STUDIO,
        LocationType.CAR_INTERIOR, LocationType.LAB, LocationType.FOREST_TRAIL,
        LocationType.GARDEN,
    }
    assert public | private == set(LocationType), "every location must be classified"
    assert public & private == set()
    for loc in public:
        assert sv.is_public_venue(loc) and sv.is_public_venue(loc.value), loc
    for loc in private:
        assert not sv.is_public_venue(loc) and not sv.is_public_venue(loc.value), loc
    # Unknown / None -> private (strict solo) — the safe default.
    assert not sv.is_public_venue("not_a_place") and not sv.is_public_venue(None)
    print("s11 OK: venue classification total, disjoint, and as designed; unknown -> private")


# ---------------------------------------------------------------------------
# s12 — pipeline worker integration (node 114)
# ---------------------------------------------------------------------------
def _worker():
    return PipelineBackgroundWorker(
        job_manager=None, comfyui_client=None, storage_service=None,
        pose_workflow_path=str(_WF_DIR / "edit_pose_action.json"),
        outfit_workflow_path=str(_WF_DIR / "test_final_API.json"),
        background_workflow_path=str(_WF_DIR / "test_final_API.json"),
    )


def test_worker_threads_staging_and_solo_policy_into_node_114():
    w = _worker()
    asyncio.run(w._load_workflows())

    # Multi-step nightclub item: staging in the target-pose sentence + strangers clause.
    req = PipelineEditRequest(
        source_image="https://x.supabase.co/s.png",
        pose=PoseType.SITTING_LEGS_WIDE_OPEN, outfit=OutfitType.BODYCON_DRESS,
        nudityLevel=NudityLevel.MEDIUM, location="nightclub",
        stagingText="perched on a bar stool at the counter",
    )
    wf = w._build_step_workflow("pose", req, "src.png", 7, "job", pose_ref_name="ref.png")
    node114 = wf["114"]["inputs"]["prompt"]
    assert node114.count("perched on a bar stool at the counter") == 1
    assert "The target pose is: sitting with legs spread wide open, provocative seated pose, " \
           "perched on a bar stool at the counter." in node114
    assert _PUBLIC_SOLO in node114 and "completely alone" not in node114

    # Same item at HIGH nudity -> the strict clause survives the venue.
    req_high = req.model_copy(update={"nudityLevel": NudityLevel.HIGH})
    wf_high = w._build_step_workflow("pose", req_high, "src.png", 7, "job", pose_ref_name="ref.png")
    assert _STRICT_SOLO in wf_high["114"]["inputs"]["prompt"]

    # Legacy request without the new fields -> byte-identical prompt (back-compat):
    # staging/location default None (nothing appended, strict solo) and nudityLevel LOW,
    # so node 114 matches a pre-staging build exactly — build_pose_prompt(pose) wrapped
    # with the request's default photoStyle (PipelineEditRequest defaults POLISHED).
    from services.prompt_constants import apply_edit_photo_style
    req_legacy = PipelineEditRequest(
        source_image="https://x.supabase.co/s.png", pose=PoseType.SITTING,
    )
    wf_legacy = w._build_step_workflow("pose", req_legacy, "src.png", 7, "job", pose_ref_name="ref.png")
    assert wf_legacy["114"]["inputs"]["prompt"] == apply_edit_photo_style(
        build_pose_prompt(PoseType.SITTING), req_legacy.photoStyle
    )
    assert _STRICT_SOLO in wf_legacy["114"]["inputs"]["prompt"]
    print("s12 OK: node 114 carries staging once + venue-correct solo clause; legacy unchanged")


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
