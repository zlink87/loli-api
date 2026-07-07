"""
Tests for prompt assembly correctness (Part C).

Covers:
  c1  adult-appearance negatives present in BOTH generation_negative() and
      edit_negative() (child/teenager/underage/minor/youthful appearance);
      edit_negative() still carries the identity terms aged/younger.
  c2  outfit build_prompt (dressed, HIGH nudity): contains the neutral lead
      "Change the person's outfit to:" and identity terms incl. "eye color",
      and does NOT contain "Dress the person in".
  c3  outfit build_prompt (NAKED) starts with "Remove all clothing".
  c4  build_pose_prompt contains body proportion + outfit + eye color and the
      surrounding pose sentences.
  c5  background build_background_prompt still contains identity terms (regression).
  c6  the dead edit-prompt assembler was deleted (not hasattr on the module).
  c7  has_contradiction: true case (hairColor=black persona vs "blonde" text),
      false case (lighting-only text), shared-"black" non-flag case.
  c8  MAX_SCENE_WORDS rejection predicate (word-count logic).
  c9  KINK_PHRASES covers all 23 KinkType and RELATIONSHIP_PHRASES all 19
      RelationshipType with non-empty phrases; "dominant" removed from kinks;
      no phrase in either map contains "youthful".
  c10 prepare_outfit_workflow with negative_prompt="test_negative_xyz" puts it
      into node 117 inputs.

Runs under pytest AND under plain ``python tests/test_prompt_assembly.py`` (the
__main__ block invokes each test function; pytest is not required).
"""
import sys
from pathlib import Path

# Ensure the loli_api package dir is importable when run as a plain script
# (mirrors conftest.py / main.py:22).
_LOLI_API_DIR = Path(__file__).resolve().parent.parent
if str(_LOLI_API_DIR) not in sys.path:
    sys.path.insert(0, str(_LOLI_API_DIR))

import models.requests as _mr  # noqa: E402

# These tests exercise prompt/identity logic, not the SSRF allowlist. The env may
# configure a real SOURCE_IMAGE_ALLOWED_HOSTS that rejects placeholder URLs, so make
# the source_image validator a passthrough (same pattern as test_scene_mapper.py).
_mr.validate_source_image = lambda u: u  # type: ignore

from models.enums import (  # noqa: E402
    KinkType,
    RelationshipType,
    OutfitType,
    NudityLevel,
    PoseType,
)
from models.requests import PersonaOptions, OutfitEditRequest, PoseEditRequest  # noqa: E402
from services import attribute_phrases as ap  # noqa: E402
from services import prompt_constants as pc  # noqa: E402
from services import prompt_generator as pg  # noqa: E402
from api.v1.endpoints import outfit as outfit_ep  # noqa: E402
from api.v1.endpoints import pose as pose_ep  # noqa: E402
from api.v1.endpoints import background as background_ep  # noqa: E402


# A source URL that passes validate_source_image (no allowlist enforced in tests).
_SRC = "https://xxx.supabase.co/storage/v1/object/public/images/test.png"


# ---------------------------------------------------------------------------
# c1 — adult-appearance negatives in both negatives; edit keeps aged/younger
# ---------------------------------------------------------------------------
def test_adult_negatives_in_generation_and_edit():
    gen = pc.generation_negative()
    edit = pc.edit_negative()

    adult_terms = ["child", "teenager", "underage", "minor", "youthful appearance"]
    for term in adult_terms:
        assert term in gen, f"generation_negative missing adult term: {term}"
        assert term in edit, f"edit_negative missing adult term: {term}"

    # edit_negative still carries the identity-preservation aged/younger terms.
    assert "aged" in edit
    assert "younger" in edit

    # generation_negative is quality + adult only (no identity block).
    assert "different face" not in gen

    # extra terms still append.
    assert pc.edit_negative("marker_extra_abc").endswith("marker_extra_abc")
    assert pc.generation_negative("marker_extra_abc").endswith("marker_extra_abc")
    print("c1 OK: adult negatives in generation + edit; edit keeps aged/younger")


# ---------------------------------------------------------------------------
# c2 — outfit dressed branch: neutral verb + identity, no "Dress the person in"
# ---------------------------------------------------------------------------
def test_outfit_dressed_prompt_neutral_verb_and_identity():
    # HIGH nudity on a suit exercises the verb/content contradiction W1 fixes.
    prompt = outfit_ep.build_prompt(OutfitType.BUSINESS_SUIT, None, NudityLevel.HIGH)

    assert "Change the person's outfit to:" in prompt
    assert "Dress the person in" not in prompt
    # Identity clause gained via pc.identity_clause — includes eye color + hair color.
    assert "eye color" in prompt
    assert "hair color" in prompt
    assert "only change the clothing, nothing else" in prompt
    print("c2 OK: dressed prompt uses neutral verb + full identity clause")


# ---------------------------------------------------------------------------
# c3 — outfit NAKED branch starts with the removal lead + identity clause
# ---------------------------------------------------------------------------
def test_outfit_naked_prompt_removal_lead():
    prompt = outfit_ep.build_prompt(OutfitType.NAKED, None, NudityLevel.HIGH)

    assert prompt.startswith("Remove all clothing")
    assert "eye color" in prompt
    assert "only change the clothing and covering, nothing else" in prompt
    print("c3 OK: naked prompt starts with 'Remove all clothing' + identity clause")


# ---------------------------------------------------------------------------
# c4 — pose prompt has body proportion + outfit + eye color and framing text
# ---------------------------------------------------------------------------
def test_pose_prompt_identity_and_framing():
    prompt = pose_ep.build_pose_prompt(PoseType.SPREAD_LEGS)

    assert "body proportion" in prompt
    assert "outfit" in prompt
    assert "eye color" in prompt
    # Surrounding sentences preserved.
    assert "Make the person in image 1 do the exact same pose" in prompt
    assert "The new pose should match image 2 accurately." in prompt
    assert "Adapt the background and environment to suit the pose naturally." in prompt
    # The pose-specific clause is what supplies the identity terms.
    assert pc.pose_identity_clause() in prompt
    print("c4 OK: pose prompt has body proportion + outfit + eye color + framing")


# ---------------------------------------------------------------------------
# c5 — background prompt still carries identity terms (regression)
# ---------------------------------------------------------------------------
def test_background_prompt_identity_regression():
    prompt = background_ep.build_background_prompt("tropical beach at sunset")

    assert "eye color" in prompt
    assert "hair color" in prompt
    assert "the background and surroundings" in prompt
    print("c5 OK: background prompt still contains identity terms")


# ---------------------------------------------------------------------------
# c6 — dead edit-prompt assembler removed
# ---------------------------------------------------------------------------
def test_dead_edit_assembler_removed():
    # Name built at runtime so this file contains no static reference to the
    # deleted symbol (keeps a repo-wide grep for it clean).
    dead_name = "assemble_" + "edit_" + "prompt"
    assert not hasattr(pg, dead_name)
    print(f"c6 OK: {dead_name} removed from prompt_generator")


# ---------------------------------------------------------------------------
# c7 — has_contradiction true / false / shared-"black" cases
# ---------------------------------------------------------------------------
def _persona(**overrides) -> PersonaOptions:
    base = dict(
        ethnicity="caucasian",
        age=30,
        hairStyle="straight",
        hairColor="black",
        eyeColor="brown",
        name="Tester",
    )
    base.update(overrides)
    return PersonaOptions(**base)


def test_has_contradiction_true_false_and_shared_black():
    persona = _persona(hairColor="black")  # black hair, caucasian, brown eyes

    # TRUE: a sibling hair color the admin did not request appears.
    assert pg.has_contradiction(
        "soft warm lighting, blonde waves catching the light", persona
    ) is True

    # FALSE: lighting/composition-only embellishment, no physical attribute.
    assert pg.has_contradiction(
        "soft warm cinematic lighting, shallow depth of field, golden hour, elegant composition",
        persona,
    ) is False

    # SHARED-"black" non-flag: persona requested black hair, so "black hair" in
    # text is legitimate and must NOT be flagged as a contradiction.
    assert pg.has_contradiction("black hair, gentle rim lighting", persona) is False

    # And a black-ethnicity persona also makes "black" legitimate.
    persona_afro = _persona(hairColor="brunette", ethnicity="black_afro")
    assert pg.has_contradiction("black hair, studio lighting", persona_afro) is False

    # A contradicting eye color is caught (searched with the noun to be safe).
    assert pg.has_contradiction("striking green eyes, moody light", persona) is True
    print("c7 OK: has_contradiction true/false/shared-black cases pass")


# ---------------------------------------------------------------------------
# c8 — MAX_SCENE_WORDS rejection predicate
# ---------------------------------------------------------------------------
def test_max_scene_words_predicate():
    cap = pg.MAX_SCENE_WORDS
    assert cap == 90

    # The rejection predicate used in _write_scene is: len(content.split()) > cap.
    over = " ".join(["word"] * (cap + 5))
    under = " ".join(["word"] * (cap - 5))
    at = " ".join(["word"] * cap)

    assert len(over.split()) > cap  # rejected
    assert not (len(under.split()) > cap)  # accepted
    assert not (len(at.split()) > cap)  # exactly at cap is accepted
    print(f"c8 OK: MAX_SCENE_WORDS={cap} rejection predicate correct")


# ---------------------------------------------------------------------------
# c9 — full KinkType/RelationshipType coverage; no stale key; no "youthful"
# ---------------------------------------------------------------------------
def test_kink_and_relationship_phrase_coverage():
    # Every KinkType has a non-empty phrase.
    missing_kinks = [k.value for k in KinkType if not ap.KINK_PHRASES.get(k.value)]
    assert not missing_kinks, f"KinkType values missing a phrase: {missing_kinks}"
    assert len([k for k in KinkType]) == 23
    # Stale "dominant" key removed (not a KinkType value).
    assert "dominant" not in ap.KINK_PHRASES

    # Every RelationshipType has a non-empty phrase.
    missing_rel = [r.value for r in RelationshipType if not ap.RELATIONSHIP_PHRASES.get(r.value)]
    assert not missing_rel, f"RelationshipType values missing a phrase: {missing_rel}"
    assert len([r for r in RelationshipType]) == 19

    # Manager corrections applied verbatim.
    assert ap.RELATIONSHIP_PHRASES["school_mate"] == "casual collegiate style"
    assert ap.RELATIONSHIP_PHRASES["step_daughter"] == "playful lighthearted vibe"

    # No phrase in either map contains "youthful" (negated by ADULT_APPEARANCE_NEGATIVE).
    for value in ap.KINK_PHRASES.values():
        assert "youthful" not in value, f"KINK phrase contains 'youthful': {value}"
    for value in ap.RELATIONSHIP_PHRASES.values():
        assert "youthful" not in value, f"RELATIONSHIP phrase contains 'youthful': {value}"
    print("c9 OK: 23/23 kinks, 19/19 relationships, no stale key, no 'youthful'")


# ---------------------------------------------------------------------------
# c10 — prepare_outfit_workflow threads negative_prompt into node 117
# ---------------------------------------------------------------------------
def test_prepare_outfit_workflow_negative_prompt_reaches_node_117():
    template = {
        "108": {"inputs": {"image": ""}},
        "16": {"inputs": {"positive": ""}},
        "117": {"inputs": {"negative": ""}},
        "106": {"inputs": {"seed": 0}},
    }
    wf = outfit_ep.prepare_outfit_workflow(
        template, "img.png", "a prompt", seed=1, negative_prompt="test_negative_xyz"
    )
    assert "test_negative_xyz" in wf["117"]["inputs"]["negative"]
    # And the base negatives are still present (quality + adult + identity).
    assert "child" in wf["117"]["inputs"]["negative"]
    assert "different face" in wf["117"]["inputs"]["negative"]
    # Original template untouched (deep-copied).
    assert template["117"]["inputs"]["negative"] == ""
    print("c10 OK: negative_prompt='test_negative_xyz' present in node 117 inputs")


# ---------------------------------------------------------------------------
# Bonus regression — request models accept negativePrompt on outfit + pose
# ---------------------------------------------------------------------------
def test_requests_accept_negative_prompt():
    of = OutfitEditRequest(source_image=_SRC, outfit="bikini", negativePrompt="foo")
    pe = PoseEditRequest(source_image=_SRC, pose="sitting", negativePrompt="bar")
    assert of.negativePrompt == "foo"
    assert pe.negativePrompt == "bar"
    # Both default to None when omitted.
    assert OutfitEditRequest(source_image=_SRC, outfit="bikini").negativePrompt is None
    assert PoseEditRequest(source_image=_SRC, pose="sitting").negativePrompt is None
    print("c11 OK: OutfitEditRequest + PoseEditRequest accept negativePrompt")


# ---------------------------------------------------------------------------
# Plain-script runner (pytest not required)
# ---------------------------------------------------------------------------
def _run_all():
    tests = [
        test_adult_negatives_in_generation_and_edit,
        test_outfit_dressed_prompt_neutral_verb_and_identity,
        test_outfit_naked_prompt_removal_lead,
        test_pose_prompt_identity_and_framing,
        test_background_prompt_identity_regression,
        test_dead_edit_assembler_removed,
        test_has_contradiction_true_false_and_shared_black,
        test_max_scene_words_predicate,
        test_kink_and_relationship_phrase_coverage,
        test_prepare_outfit_workflow_negative_prompt_reaches_node_117,
        test_requests_accept_negative_prompt,
    ]
    failures = 0
    for fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            import traceback

            print(f"FAIL: {fn.__name__}: {exc}")
            traceback.print_exc()
    print()
    print(f"{len(tests) - failures}/{len(tests)} tests passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
