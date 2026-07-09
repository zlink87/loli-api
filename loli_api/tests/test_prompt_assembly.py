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
  c9  KINK_PHRASES covers all 23 KinkType and RELATIONSHIP_PHRASES all 19
      RelationshipType with non-empty phrases; "dominant" removed from kinks;
      no phrase in either map contains "youthful".
  c10 prepare_outfit_workflow with negative_prompt="test_negative_xyz" puts it
      into node 117 inputs.
  c12 edit_negative() nudity suppression is leveled and defaults to low.
  c13 has_banned_style_words flags glamour/stock-photo filler.
  c14 every non-NAKED outfit's LOW tier is a real, non-exposing garment.
  c16 every selected generation option lands in the assembled prompt, and the
      scene clause (used verbatim; Venice generation-scene-writing was removed
      2026-07-08) sits before persona flavor, not buried at the tail.
  c17 Venice generation-scene-writing fully removed (regression guard).
  c18 outfit build_prompt: outfit_detail appended after the tier prose, before
      the identity clause; omitted -> byte-identical to the pre-WS2 prompt.
  c19 outfit build_prompt: outfit_detail also appended on the NAKED branch.
  c20 outfit build_prompt: replace_mode swaps the dressed-branch lead-in to the
      remove-then-replace instruction; NAKED branch is unaffected (it already
      reads as a removal).
  c21 build_pose_prompt: activity/expression appended (", while {activity}" /
      ", {expression} expression"); base prompt is byte-identical when both are
      omitted/None (back-compat for /v1/edit/pose, which never sets them).
  c22 build_pose_prompt: lighting phrase-ified via services.scene_vocab and
      appended (", in {lighting phrase}"); raw enum-value string never leaks;
      None/unrecognized -> byte-identical to the base prompt.
  c23 build_pose_prompt: time_of_day phrase-ified and appended (", {time_of_day
      phrase}"); same graceful None/unrecognized back-compat; combines with
      activity/expression/lighting in the documented append order.
  c24 outfit build_prompt: lighting phrase-ified and appended after
      outfit_detail (both branches: dressed and NAKED); same graceful
      None/unrecognized back-compat.

(c7, c8, c15 covered `has_contradiction`/`MAX_SCENE_WORDS`/`scene_preserves_hint`
— all removed with the Venice generation-scene-writer on 2026-07-08. c11 is the
"Bonus regression" test below, unrelated to Venice — kept.)

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
# c12 — edit_negative() carries nudity suppression, leveled + defaulted to low
# ---------------------------------------------------------------------------
def test_edit_negative_nudity_suppression_levels():
    low = pc.edit_negative(nudity_level=NudityLevel.LOW)
    medium = pc.edit_negative(nudity_level=NudityLevel.MEDIUM)
    high = pc.edit_negative(nudity_level=NudityLevel.HIGH)
    default = pc.edit_negative()  # None -> treated as low

    assert "exposed breasts" in low and "topless" in low
    assert "full frontal nudity" in medium
    assert medium == pc.edit_negative(nudity_level="medium")  # string value accepted
    # HIGH suppresses nothing extra, but quality/adult/identity still present.
    assert "child" in high and "different face" in high
    assert default == low  # dressed-by-default: no level == low, never silently more exposed
    print("c12 OK: edit_negative() nudity suppression is leveled and defaults to low")


# ---------------------------------------------------------------------------
# c13 — banned style/glamour-filler word scrubber
# ---------------------------------------------------------------------------
def test_has_banned_style_words():
    assert pc.has_banned_style_words("posing in a professional photography studio with soft bokeh")
    assert pc.has_banned_style_words("an 8k cinematic masterpiece")
    assert not pc.has_banned_style_words(
        "cutting vegetables at the kitchen counter while music plays softly"
    )
    print("c13 OK: has_banned_style_words flags glamour/stock-photo filler, not plain scenes")


# ---------------------------------------------------------------------------
# c14 — outfit vocab LOW tier is a real garment, never exposing (NAKED excluded
# by design: selecting the "naked" outfit is itself a deliberate undress request)
# ---------------------------------------------------------------------------
def test_outfit_low_tier_has_no_exposure_language():
    from services.outfit_vocab import OUTFIT_DESCRIPTIONS

    banned = [
        "cleavage", "nipple", "breast", "sideboob", "underboob", "bare ass",
        "ass cheek", "pussy", "labia", "areola", "topless", "bare skin",
        "exposed", "exposing",
    ]
    for outfit, levels in OUTFIT_DESCRIPTIONS.items():
        if outfit == OutfitType.NAKED:
            continue
        low_text = levels[NudityLevel.LOW].lower()
        for term in banned:
            assert term not in low_text, f"{outfit.value} LOW contains '{term}': {low_text}"
        # MEDIUM/HIGH must still exist and differ from LOW (tiers still graded).
        assert levels[NudityLevel.MEDIUM] != low_text
        assert levels[NudityLevel.HIGH] != levels[NudityLevel.MEDIUM]
    print("c14 OK: every non-NAKED outfit's LOW tier is a real, non-exposing garment")


# ---------------------------------------------------------------------------
# c16 — every selected generation option verifiably lands in the final prompt,
# and the scene clause sits before persona flavor (not buried at the tail)
# ---------------------------------------------------------------------------
def test_generation_prompt_option_fidelity():
    from models.requests import ShotOptions
    from models.enums import AccessoryType, ExpressionType

    persona = PersonaOptions(
        name="Addison", ethnicity="caucasian", age=24, hairStyle="straight", hairColor="blonde",
        eyeColor="blue", bodyType="skinny", breastSize="medium",
        personality="nympho", relationship="girlfriend", occupation="student",
        kinks=["bondage", "creampie", "cuddling"],
    )
    shot = ShotOptions(expression=ExpressionType.CONFIDENT)
    positive, negative, locked = pg.assemble_generation_prompt(
        persona,
        free_text="School dance",
        shot=shot,
        outfit=OutfitType.LITTLE_BLACK_DRESS,
        nudity_level=NudityLevel.MEDIUM,
        accessories=[AccessoryType.EARRINGS],
    )

    # Locked identity present verbatim.
    for tok in locked.split(", "):
        assert tok in positive, f"locked identity token missing from prompt: {tok}"
    # Outfit selection present (MEDIUM tier text).
    from services.outfit_vocab import OUTFIT_DESCRIPTIONS
    assert OUTFIT_DESCRIPTIONS[OutfitType.LITTLE_BLACK_DRESS][NudityLevel.MEDIUM] in positive
    # Accessory present.
    assert "earrings" in positive
    # User scene hint present, and positioned BEFORE the persona flavor
    # (occupation/kinks) rather than buried after it — a turbo model weights
    # earlier tokens more heavily, so the requested scene must not be diluted.
    assert "School dance" in positive
    flavor_marker = ap.phrase(ap.OCCUPATION_PHRASES, persona.occupation)
    assert positive.index("School dance") < positive.index(flavor_marker)
    # Nudity suppression on the negative side matches the requested level.
    assert negative == pc.generation_negative(nudity_level=NudityLevel.MEDIUM)
    print("c16 OK: every selected option lands in the prompt; scene clause precedes flavor")


# ---------------------------------------------------------------------------
# c17 — Venice generation-scene-writing was fully removed (regression guard):
# no isEnhance field, no is_enhance param, context always used verbatim.
# ---------------------------------------------------------------------------
def test_venice_generation_enhancement_removed():
    from models.requests import GenerateImageRequest
    import inspect
    from services.prompt_generator import PromptGenerator

    assert "isEnhance" not in GenerateImageRequest.model_fields

    sig = inspect.signature(PromptGenerator.generate_generation_prompt)
    assert "is_enhance" not in sig.parameters

    persona = PersonaOptions(
        name="Riley", ethnicity="caucasian", age=25, hairStyle="straight", hairColor="black",
        eyeColor="brown", bodyType="average", breastSize="medium",
        personality="shy", relationship="stranger", occupation="student",
    )
    positive, _negative, _locked = pg.assemble_generation_prompt(
        persona, free_text="a weird hint xyzzy123 that no LLM would invent",
    )
    assert "xyzzy123" in positive  # always verbatim, nothing can rewrite/drop it
    print("c17 OK: isEnhance/is_enhance gone; context is always used verbatim")


# ---------------------------------------------------------------------------
# c18 — outfit build_prompt: outfit_detail appended after the tier prose
# ---------------------------------------------------------------------------
def test_outfit_detail_appended_after_tier_prose():
    base = outfit_ep.build_prompt(OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW)
    detailed = outfit_ep.build_prompt(
        OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW,
        outfit_detail="charcoal pinstripe, fitted blazer",
    )
    assert "charcoal pinstripe, fitted blazer" in detailed
    assert "charcoal pinstripe, fitted blazer" not in base
    # It sharpens the lead sentence: sits before the identity clause.
    identity = pc.identity_clause("the outfit and clothing")
    assert identity in detailed
    assert detailed.index("charcoal pinstripe") < detailed.index(identity)
    # Omitting it reproduces the exact unchanged prompt (back-compat).
    assert outfit_ep.build_prompt(OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW) == base
    print("c18 OK: outfit_detail appended after the tier prose, before the identity clause")


# ---------------------------------------------------------------------------
# c19 — outfit build_prompt: outfit_detail also appended on the NAKED branch
# ---------------------------------------------------------------------------
def test_outfit_detail_appended_on_naked_branch_too():
    detailed = outfit_ep.build_prompt(
        OutfitType.NAKED, None, NudityLevel.HIGH, outfit_detail="a thin gold anklet only",
    )
    assert detailed.startswith("Remove all clothing")
    assert "a thin gold anklet only" in detailed
    print("c19 OK: outfit_detail also appended on the NAKED branch")


# ---------------------------------------------------------------------------
# c20 — outfit build_prompt: replace_mode swaps the dressed-branch lead-in
# ---------------------------------------------------------------------------
def test_outfit_replace_mode_swaps_lead_in():
    standard = outfit_ep.build_prompt(OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW)
    replaced = outfit_ep.build_prompt(
        OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW, replace_mode=True,
    )
    assert "Change the person's outfit to:" in standard
    assert "Remove the person's current clothing completely and replace it with:" in replaced
    assert "no piece of the previous outfit may remain visible" in replaced
    assert "Change the person's outfit to:" not in replaced
    # Rest of the prompt (identity clause, "only change" instruction) is unaffected.
    assert "only change the clothing, nothing else" in replaced

    # replace_mode is a no-op on the NAKED branch: it already reads as a removal.
    naked_standard = outfit_ep.build_prompt(OutfitType.NAKED, None, NudityLevel.HIGH)
    naked_replace = outfit_ep.build_prompt(OutfitType.NAKED, None, NudityLevel.HIGH, replace_mode=True)
    assert naked_standard == naked_replace
    print("c20 OK: replace_mode swaps the dressed-branch lead-in; NAKED branch unaffected")


# ---------------------------------------------------------------------------
# c21 — build_pose_prompt: activity/expression appended; base unchanged when
# both are None (back-compat: /v1/edit/pose never sets them)
# ---------------------------------------------------------------------------
def test_pose_prompt_activity_and_expression_appended():
    base = pose_ep.build_pose_prompt(PoseType.SITTING)
    with_both = pose_ep.build_pose_prompt(
        PoseType.SITTING, activity="pouring coffee", expression="sleepy soft smile",
    )
    assert with_both == base + ", while pouring coffee, sleepy soft smile expression"

    only_activity = pose_ep.build_pose_prompt(PoseType.SITTING, activity="pouring coffee")
    assert only_activity == base + ", while pouring coffee"

    only_expression = pose_ep.build_pose_prompt(PoseType.SITTING, expression="sleepy soft smile")
    assert only_expression == base + ", sleepy soft smile expression"

    # Base prompt is byte-identical when both are omitted, or explicitly None.
    explicit_none = pose_ep.build_pose_prompt(PoseType.SITTING, activity=None, expression=None)
    assert explicit_none == base
    print("c21 OK: activity/expression appended when given; base unchanged when both None")


# ---------------------------------------------------------------------------
# c22 — build_pose_prompt: lighting phrase-ified + appended; back-compat when
# None/unrecognized (W3: batch photos always rendering bright — the pose step
# is the only step that fully re-diffuses the frame, so it's the one place a
# lighting clause can actually re-light the person).
# ---------------------------------------------------------------------------
def test_pose_prompt_lighting_appended():
    base = pose_ep.build_pose_prompt(PoseType.SITTING)

    lit = pose_ep.build_pose_prompt(PoseType.SITTING, lighting="moody_dim")
    assert lit == base + ", in moody dim low-key lighting"

    # Raw enum-value string is never injected verbatim — only the phrase-ified
    # text from services.scene_vocab.LIGHTING_PHRASES.
    assert "moody_dim" not in lit

    # None -> byte-identical to the base prompt (back-compat).
    assert pose_ep.build_pose_prompt(PoseType.SITTING, lighting=None) == base

    # Unrecognized value -> gracefully skipped (no clause appended, no raw
    # string injected), never a crash.
    unknown = pose_ep.build_pose_prompt(PoseType.SITTING, lighting="not_a_real_lighting_value")
    assert unknown == base
    assert "not_a_real_lighting_value" not in unknown

    # Omitting the base-call params entirely (today's /v1/edit/pose call shape)
    # still yields the exact unchanged prompt.
    assert pose_ep.build_pose_prompt(PoseType.SITTING) == base
    print("c22 OK: lighting phrase-ified + appended; None/unrecognized leave the prompt unchanged")


# ---------------------------------------------------------------------------
# c23 — build_pose_prompt: time_of_day phrase-ified + appended; back-compat;
# combines with activity/expression/lighting in the documented append order
# (activity, expression, lighting, time_of_day).
# ---------------------------------------------------------------------------
def test_pose_prompt_time_of_day_appended_and_combines_with_lighting():
    base = pose_ep.build_pose_prompt(PoseType.SITTING)

    # "golden_hour" (underscored raw value) vs "during golden hour" (spaced
    # phrase) — a clean pair for the no-raw-leak assertion below.
    golden = pose_ep.build_pose_prompt(PoseType.SITTING, time_of_day="golden_hour")
    assert golden == base + ", during golden hour"
    assert "golden_hour" not in golden

    # None -> byte-identical (back-compat).
    assert pose_ep.build_pose_prompt(PoseType.SITTING, time_of_day=None) == base

    # Unrecognized value -> gracefully skipped.
    unknown = pose_ep.build_pose_prompt(PoseType.SITTING, time_of_day="not_a_real_tod_value")
    assert unknown == base
    assert "not_a_real_tod_value" not in unknown

    # Full combination: activity, expression, lighting, time_of_day all append
    # in that order (mirrors workers.pipeline_worker._build_step_workflow's
    # pose branch, which passes all four through from PipelineEditRequest).
    combo = pose_ep.build_pose_prompt(
        PoseType.SITTING,
        activity="pouring coffee",
        expression="sleepy soft smile",
        lighting="moody_dim",
        time_of_day="night",
    )
    assert combo == (
        base
        + ", while pouring coffee"
        + ", sleepy soft smile expression"
        + ", in moody dim low-key lighting"
        + ", late at night"
    )
    print(
        "c23 OK: time_of_day phrase-ified + appended; None/unrecognized unchanged; "
        "combines with activity/expression/lighting in append order"
    )


# ---------------------------------------------------------------------------
# c24 — outfit build_prompt: lighting phrase-ified + appended after
# outfit_detail (both branches); back-compat when None/unrecognized.
# ---------------------------------------------------------------------------
def test_outfit_prompt_lighting_appended_after_outfit_detail():
    base = outfit_ep.build_prompt(OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW)

    lit = outfit_ep.build_prompt(
        OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW, lighting="candlelit",
    )
    # Lighting is inserted into the LEAD sentence (same region as
    # outfit_detail), before the identity clause — not appended at the very
    # end of the whole joined prompt. Stripping the clause back out reproduces
    # the base prompt exactly.
    assert "flickering candlelight" in lit
    assert lit.replace(", in flickering candlelight", "", 1) == base
    # Raw enum-value string never leaks ("candlelit" is not a substring of the
    # phrase "flickering candlelight" — they diverge after "candlel").
    assert "candlelit" not in lit

    # Sits AFTER outfit_detail on the same lead sentence, before the identity
    # clause (mirrors c18's outfit_detail placement check).
    detailed_and_lit = outfit_ep.build_prompt(
        OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW,
        outfit_detail="charcoal pinstripe, fitted blazer", lighting="candlelit",
    )
    identity = pc.identity_clause("the outfit and clothing")
    assert "charcoal pinstripe, fitted blazer" in detailed_and_lit
    assert "flickering candlelight" in detailed_and_lit
    assert (
        detailed_and_lit.index("charcoal pinstripe")
        < detailed_and_lit.index("flickering candlelight")
        < detailed_and_lit.index(identity)
    )

    # NAKED branch also gets the lighting clause (outfit_detail applies there
    # too — c19 — and lighting follows the same both-branches treatment).
    naked_lit = outfit_ep.build_prompt(OutfitType.NAKED, None, NudityLevel.HIGH, lighting="candlelit")
    assert naked_lit.startswith("Remove all clothing")
    assert "flickering candlelight" in naked_lit

    # None -> byte-identical (back-compat).
    assert outfit_ep.build_prompt(OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW, lighting=None) == base

    # Unrecognized value -> gracefully skipped.
    unknown = outfit_ep.build_prompt(
        OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW, lighting="not_a_real_lighting_value",
    )
    assert unknown == base
    assert "not_a_real_lighting_value" not in unknown
    print(
        "c24 OK: outfit lighting phrase-ified + appended after outfit_detail on both "
        "branches; None/unrecognized leave the prompt unchanged"
    )


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
        test_kink_and_relationship_phrase_coverage,
        test_prepare_outfit_workflow_negative_prompt_reaches_node_117,
        test_requests_accept_negative_prompt,
        test_edit_negative_nudity_suppression_levels,
        test_has_banned_style_words,
        test_outfit_low_tier_has_no_exposure_language,
        test_generation_prompt_option_fidelity,
        test_venice_generation_enhancement_removed,
        test_outfit_detail_appended_after_tier_prose,
        test_outfit_detail_appended_on_naked_branch_too,
        test_outfit_replace_mode_swaps_lead_in,
        test_pose_prompt_activity_and_expression_appended,
        test_pose_prompt_lighting_appended,
        test_pose_prompt_time_of_day_appended_and_combines_with_lighting,
        test_outfit_prompt_lighting_appended_after_outfit_detail,
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
