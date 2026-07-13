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
  c32 build_pose_prompt: identity_anchors (D1) appended immediately after
      pose_identity_clause() as "She has {anchors}; keep these and her body
      proportions and build exactly as in image 1, completely unchanged.";
      absent (byte-identical base prompt) when None/empty.
  c33 outfit build_prompt: identity_anchors (D1) appended right after
      pc.identity_clause(...) on BOTH branches (NAKED and dressed) as "she has
      {anchors}, kept exactly unchanged"; absent when None/empty.

(c7, c8, c15 covered `has_contradiction`/`MAX_SCENE_WORDS`/`scene_preserves_hint`
— all removed with the Venice generation-scene-writer on 2026-07-08. c11 is the
"Bonus regression" test below, unrelated to Venice — kept.)

Runs under pytest AND under plain ``python tests/test_prompt_assembly.py`` (the
__main__ block invokes each test function; pytest is not required).
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

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
from models.requests import (  # noqa: E402
    PersonaOptions, OutfitEditRequest, PoseEditRequest, BackgroundEditRequest,
)
from services.character_anchors import populate_identity_anchors  # noqa: E402
from services import attribute_phrases as ap  # noqa: E402
from services import prompt_constants as pc  # noqa: E402
from services import prompt_generator as pg  # noqa: E402
from services import scene_vocab as sv  # noqa: E402
from services.outfit_vocab import OUTFIT_DESCRIPTIONS  # noqa: E402
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
    # B1: the old "Adapt the background…" licence-to-re-invent sentence is REPLACED
    # by an explicit keep-the-background instruction.
    assert (
        "Keep the same background, location and environment as image 1, adjusting "
        "only perspective to fit the new pose." in prompt
    )
    assert "Adapt the background and environment to suit the pose naturally." not in prompt
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
# c20 — outfit build_prompt: prompt_mode="replace" swaps the dressed-branch
# lead-in; "standard" (and the default / an unknown value) keep the neutral
# change lead byte-for-byte — no drift from the pre-PR2 replace_mode=False/True
# behavior now that the bool became the prompt_mode string.
# ---------------------------------------------------------------------------
def test_outfit_replace_mode_swaps_lead_in():
    default = outfit_ep.build_prompt(OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW)
    standard = outfit_ep.build_prompt(
        OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW, prompt_mode="standard",
    )
    replaced = outfit_ep.build_prompt(
        OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW, prompt_mode="replace",
    )
    # "standard" is byte-identical to the default call (former replace_mode=False).
    assert standard == default
    assert "Change the person's outfit to:" in standard
    assert "Remove the person's current clothing completely and replace it with:" in replaced
    assert "no piece of the previous outfit may remain visible" in replaced
    assert "Change the person's outfit to:" not in replaced
    # Rest of the prompt (identity clause, "only change" instruction) is unaffected.
    assert "only change the clothing, nothing else" in replaced
    # An unrecognized mode also falls back to the standard lead.
    assert outfit_ep.build_prompt(
        OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW, prompt_mode="bogus",
    ) == default

    # "replace" is a no-op on the NAKED branch: it already reads as a removal, so
    # NAKED+replace is byte-identical to NAKED+standard (former replace_mode=True).
    naked_standard = outfit_ep.build_prompt(OutfitType.NAKED, None, NudityLevel.HIGH)
    naked_replace = outfit_ep.build_prompt(OutfitType.NAKED, None, NudityLevel.HIGH, prompt_mode="replace")
    assert naked_standard == naked_replace
    print("c20 OK: prompt_mode replace swaps the dressed lead-in; standard/unknown == default; NAKED unaffected")


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
# c25 — outfit build_prompt: prompt_mode="nude_base" (NAKED branch) renders the
# NEUTRAL anatomical reference body instead of the arousal-styled NAKED tier
# prose, and hardens the removal lead so no stray strap survives. The dressed
# branch and the standard NAKED branch are unchanged (nude_base only ever pairs
# with NAKED).
# ---------------------------------------------------------------------------
def test_outfit_nude_base_mode_neutral_body():
    from services.outfit_vocab import NUDE_BASE_BODY_DESCRIPTION

    nb = outfit_ep.build_prompt(OutfitType.NAKED, None, NudityLevel.HIGH, prompt_mode="nude_base")

    # Neutral reference body + hardened removal lead (kills the leftover-strap bug).
    assert nb.startswith(
        "Remove all clothing completely so that no garment, bra, strap, or "
        "underwear remains anywhere"
    )
    assert NUDE_BASE_BODY_DESCRIPTION in nb
    assert "matte" in nb                 # natural matte skin (anti-shine)
    assert "matches her face" in nb      # RELATIVE tone anchor (not absolute)
    assert "no garment, bra, strap" in nb

    # The arousal-styled NAKED tier prose ("...swollen aroused pussy lips...", plus
    # shine words) must be gone. "non-aroused" legitimately appears (the calm body
    # IS the point), so assert the tier's actual arousal wording is absent rather
    # than the bare "aroused" token.
    assert "swollen" not in nb
    assert "glistening" not in nb
    assert "aroused pussy" not in nb
    assert "non-aroused" in nb           # the neutral state is stated positively

    # nude_base is a no-op on the DRESSED branch: it falls through to the standard
    # change lead, byte-identical to the default call.
    dressed_default = outfit_ep.build_prompt(OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW)
    dressed_nb = outfit_ep.build_prompt(
        OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW, prompt_mode="nude_base",
    )
    assert dressed_nb == dressed_default

    # The STANDARD NAKED branch is untouched — still the arousal-styled tier prose.
    naked_standard = outfit_ep.build_prompt(OutfitType.NAKED, None, NudityLevel.HIGH)
    assert "swollen aroused pussy lips" in naked_standard
    assert naked_standard != nb
    print("c25 OK: nude_base renders the neutral reference body + hardened removal; dressed/standard paths unchanged")


# ---------------------------------------------------------------------------
# c26 — scene_vocab.strip_companions: companion truncation, crowd-noun removal
# with dangling-word cleanup, clean passthrough, None/empty handling.
# ---------------------------------------------------------------------------
def test_strip_companions():
    # 1. Companion tail truncation — everything from "with <someone>" is dropped.
    assert sv.strip_companions("practicing a new dance with a partner") == "practicing a new dance"
    assert sv.strip_companions("dancing with a partner") == "dancing"
    assert sv.strip_companions("chatting with a couple of colleagues") == "chatting"
    assert sv.strip_companions("reading a book with her friends in a cafe") == "reading a book"

    # 2. Crowd nouns removed with the dangling connector ("full of"/"with") trimmed —
    # NOT left as "a lively street full of".
    assert sv.strip_companions("a lively street full of passersby") == "a lively street"
    assert sv.strip_companions("a busy plaza with onlookers") == "a busy plaza"

    # 3. Nothing meaningful left -> None.
    assert sv.strip_companions("with a group of friends") is None
    assert sv.strip_companions("surrounded by a crowd") is None

    # 4. Clean passthrough (no companion/crowd phrasing) is unchanged.
    assert sv.strip_companions("pouring her first coffee") == "pouring her first coffee"
    assert sv.strip_companions("standing by the window at dawn") == "standing by the window at dawn"

    # 5. None / empty / whitespace-only -> None.
    assert sv.strip_companions(None) is None
    assert sv.strip_companions("") is None
    assert sv.strip_companions("   ") is None
    print("c26 OK: strip_companions truncates companions, removes crowds w/ cleanup, passes clean text, handles None/empty")


# ---------------------------------------------------------------------------
# c27 — build_pose_prompt B1 guards: keep-background sentence (NOT "Adapt the
# background"), always-on solo constraint (even bare interactive call), location
# phrase rendered when given, activity companion-stripping.
# ---------------------------------------------------------------------------
def test_pose_prompt_keep_background_solo_and_location():
    base = pose_ep.build_pose_prompt(PoseType.SITTING)

    # Keep-background REPLACES the old adapt-the-background licence.
    assert (
        "Keep the same background, location and environment as image 1, adjusting "
        "only perspective to fit the new pose." in base
    )
    assert "Adapt the background and environment to suit the pose naturally." not in base

    # Solo constraint ALWAYS present — even the bare interactive /v1/edit/pose call.
    solo = "She is completely alone in the frame — exactly one person, no other people."
    assert solo in base

    # Location phrase appended right after the keep-background sentence when given
    # (raw enum value -> phrase; the raw string never leaks).
    located = pose_ep.build_pose_prompt(PoseType.SITTING, location="home_bedroom")
    assert "The scene is a cozy sunlit bedroom with soft bedding and warm decor." in located
    assert "home_bedroom" not in located
    # Unknown/None location -> no clause, byte-identical to base.
    assert pose_ep.build_pose_prompt(PoseType.SITTING, location="not_a_location") == base
    assert pose_ep.build_pose_prompt(PoseType.SITTING, location=None) == base

    # Activity companion-stripping: "dancing with a partner" -> "dancing" (no "partner").
    danced = pose_ep.build_pose_prompt(PoseType.SITTING, activity="dancing with a partner")
    assert ", while dancing" in danced
    assert "partner" not in danced
    # A companion-only activity contributes no clause at all.
    companions_only = pose_ep.build_pose_prompt(PoseType.SITTING, activity="with a group of friends")
    assert companions_only == base
    print("c27 OK: keep-background replaces adapt; solo always present; location rendered; activity companion-stripped")


# ---------------------------------------------------------------------------
# c27b — build_pose_prompt pose_detail (C1a): the freeform director sentence
# REPLACES the enum description in "The target pose is: {…}" (the enum still
# picks the reference image); None/empty/companion-only falls back to the enum
# text exactly; companion phrasing is stripped from a mixed detail.
# ---------------------------------------------------------------------------
def test_pose_prompt_pose_detail_replaces_enum_description():
    base = pose_ep.build_pose_prompt(PoseType.SITTING)
    enum_desc = pose_ep.POSE_DESCRIPTIONS[PoseType.SITTING]
    assert f"The target pose is: {enum_desc}." in base

    # The freeform sentence replaces the enum description — and ONLY it: the rest
    # of the prompt (keep-background, solo, …) is byte-identical.
    custom = "curled up on the sofa, mug in both hands, knees tucked"
    detailed = pose_ep.build_pose_prompt(PoseType.SITTING, pose_detail=custom)
    assert f"The target pose is: {custom}." in detailed
    assert enum_desc not in detailed
    assert detailed == base.replace(enum_desc, custom)

    # Fallback: None / empty / whitespace -> the enum text exactly as today.
    assert pose_ep.build_pose_prompt(PoseType.SITTING, pose_detail=None) == base
    assert pose_ep.build_pose_prompt(PoseType.SITTING, pose_detail="   ") == base

    # Companion phrasing is stripped from the detail before it lands (solo frame).
    danced = pose_ep.build_pose_prompt(
        PoseType.SITTING, pose_detail="slow dancing barefoot with a partner"
    )
    assert "The target pose is: slow dancing barefoot." in danced
    assert "partner" not in danced
    # A companion-only detail contributes nothing -> enum-text fallback.
    assert pose_ep.build_pose_prompt(
        PoseType.SITTING, pose_detail="with a group of friends"
    ) == base
    print("c27b OK: pose_detail replaces the enum description; None/companion-only fall back; companions stripped")


# ---------------------------------------------------------------------------
# c28 — build_pose_prompt outfit continuity: a plain garment reads "wearing X …",
# a NAKED-tier text reads "she is completely naked … keep her state of dress" (never
# "wearing completely naked").
# ---------------------------------------------------------------------------
def test_pose_prompt_outfit_continuity_phrasing():
    base = pose_ep.build_pose_prompt(PoseType.SITTING)

    # Plain garment -> "wearing {text}; keep her state of dress and every garment …".
    garment = "a tailored charcoal business suit"
    g = pose_ep.build_pose_prompt(PoseType.SITTING, outfit_text=garment)
    assert f"In image 1 she is wearing {garment}; keep her state of dress and every garment exactly as in image 1, fully intact." in g

    # NAKED-tier text (starts with a state-of-dress word) -> "she is {text}; keep her
    # state of dress exactly …" — must NOT become "wearing completely naked".
    naked_tier = OUTFIT_DESCRIPTIONS[OutfitType.NAKED][NudityLevel.HIGH]
    assert naked_tier.startswith("completely naked")
    n = pose_ep.build_pose_prompt(PoseType.SITTING, outfit_text=naked_tier)
    assert f"In image 1 she is {naked_tier}; keep her state of dress exactly as in image 1." in n
    assert "wearing completely naked" not in n

    # "topless"/"wearing"-led texts also take the state-word phrasing.
    topless_tier = OUTFIT_DESCRIPTIONS[OutfitType.NAKED][NudityLevel.MEDIUM]
    assert topless_tier.startswith("topless")
    t = pose_ep.build_pose_prompt(PoseType.SITTING, outfit_text=topless_tier)
    assert f"In image 1 she is {topless_tier}; keep her state of dress exactly as in image 1." in t
    assert "wearing topless" not in t

    # None -> no continuity sentence, byte-identical to base.
    assert pose_ep.build_pose_prompt(PoseType.SITTING, outfit_text=None) == base
    print("c28 OK: outfit continuity uses 'wearing X' for garments and 'she is X' for NAKED-tier text")


# ---------------------------------------------------------------------------
# c29 — outfit_continuity_text: detail is ADDITIVELY comma-joined AHEAD of the
# tier prose (caption + graded prose, dedupe when identical); tier-prose
# fallback when no detail; None outfit -> None.
# ---------------------------------------------------------------------------
def test_outfit_continuity_text():
    # outfit_detail (stripped) is prefixed AHEAD of the graded tier prose (additive),
    # so the pose step preserves BOTH the caption garment AND the graded exposure.
    tier_low = OUTFIT_DESCRIPTIONS[OutfitType.BUSINESS_SUIT][NudityLevel.LOW]
    assert (
        outfit_ep.outfit_continuity_text(
            OutfitType.BUSINESS_SUIT, NudityLevel.LOW, "  charcoal wool pantsuit  "
        )
        == f"charcoal wool pantsuit, {tier_low}"
    )
    # HIGH level -> the caption plus the HIGH tier prose.
    tier_high = OUTFIT_DESCRIPTIONS[OutfitType.BUSINESS_SUIT][NudityLevel.HIGH]
    assert (
        outfit_ep.outfit_continuity_text(
            OutfitType.BUSINESS_SUIT, NudityLevel.HIGH, "charcoal wool pantsuit"
        )
        == f"charcoal wool pantsuit, {tier_high}"
    )
    # Dedupe: a detail identical to the tier prose is emitted once, not doubled.
    assert (
        outfit_ep.outfit_continuity_text(OutfitType.BUSINESS_SUIT, NudityLevel.HIGH, tier_high)
        == tier_high
    )
    # No detail -> the OUTFIT_DESCRIPTIONS tier prose at the requested level.
    assert (
        outfit_ep.outfit_continuity_text(OutfitType.BUSINESS_SUIT, NudityLevel.HIGH, None)
        == OUTFIT_DESCRIPTIONS[OutfitType.BUSINESS_SUIT][NudityLevel.HIGH]
    )
    # Empty/whitespace detail is treated as absent -> tier prose.
    assert (
        outfit_ep.outfit_continuity_text(OutfitType.BIKINI, NudityLevel.LOW, "   ")
        == OUTFIT_DESCRIPTIONS[OutfitType.BIKINI][NudityLevel.LOW]
    )
    # None outfit -> None (no outfit step, nothing to preserve).
    assert outfit_ep.outfit_continuity_text(None, NudityLevel.LOW, None) is None
    assert outfit_ep.outfit_continuity_text(None, NudityLevel.HIGH, "ignored") is None
    print("c29 OK: outfit_continuity_text: caption + tier prose (additive, dedupe), tier fallback, None outfit -> None")


# ---------------------------------------------------------------------------
# c30 — build_prompt prompt_mode="dress" (additive dressing on a nude source):
# dressed branch uses the dress lead; NAKED+dress falls back to the removal lead.
# ---------------------------------------------------------------------------
def test_outfit_dress_mode_lead():
    dressed = outfit_ep.build_prompt(
        OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW, prompt_mode="dress",
    )
    assert "The person is currently completely nude; dress them in:" in dressed
    assert "render the clothing fully and realistically on the body exactly as described" in dressed
    # It is a distinct lead from standard/replace on the dressed branch.
    assert "Change the person's outfit to:" not in dressed
    assert "Remove the person's current clothing completely and replace it with:" not in dressed
    # Rest of the dressed-branch prompt (identity clause, "only change") intact.
    assert "only change the clothing, nothing else" in dressed

    # NAKED IGNORES "dress" (dressing a NAKED target is a contradiction): it falls
    # through to the standard removal lead, byte-identical to the default NAKED call.
    naked_default = outfit_ep.build_prompt(OutfitType.NAKED, None, NudityLevel.HIGH)
    naked_dress = outfit_ep.build_prompt(
        OutfitType.NAKED, None, NudityLevel.HIGH, prompt_mode="dress",
    )
    assert naked_dress == naked_default
    assert naked_dress.startswith("Remove all clothing")
    assert "dress them in" not in naked_dress
    print("c30 OK: dress mode uses the nude-source dress lead; NAKED+dress falls back to the removal lead")


# ---------------------------------------------------------------------------
# c31 — outfit build_prompt: detail_dominant is ADDITIVE — the caption LEADS the
# garment description and the graded per-nudity-tier prose is appended after it
# (caption AND tier prose), so explicitness is not weakened. The generic
# _DETAIL_DOMINANT_EXPOSURE clause is NOT used when the enum has tier prose.
# ---------------------------------------------------------------------------
def test_outfit_detail_dominant_renders_caption_plus_tier_prose():
    T, N = OutfitType, NudityLevel
    # The caption LEADS and the graded tier prose is appended additively after it.
    tier_med = OUTFIT_DESCRIPTIONS[T.BUSINESS_SUIT][N.MEDIUM]
    dom = outfit_ep.build_prompt(
        T.BUSINESS_SUIT, None, N.MEDIUM,
        outfit_detail="a flowing chiffon dress", detail_dominant=True,
    )
    # Both the caption AND the graded MEDIUM tier prose are present.
    assert "a flowing chiffon dress" in dom
    assert tier_med in dom
    assert dom.count("a flowing chiffon dress") == 1
    # Caption leads; the tier prose follows it on the lead sentence.
    assert dom.index("a flowing chiffon dress") < dom.index(tier_med)
    # The generic garment-neutral exposure clause is NOT substituted in (enum has prose).
    assert "worn partially open with real exposure of bare skin" not in dom

    # LOW: caption + graded LOW tier prose (no generic exposure clause).
    tier_low = OUTFIT_DESCRIPTIONS[T.BUSINESS_SUIT][N.LOW]
    dom_low = outfit_ep.build_prompt(
        T.BUSINESS_SUIT, None, N.LOW,
        outfit_detail="a flowing chiffon dress", detail_dominant=True,
    )
    assert "a flowing chiffon dress" in dom_low
    assert tier_low in dom_low
    for clause in (
        "worn to tease", "real exposure of bare skin",
        "nearly spilling free", "barely covering anything",
    ):
        assert clause not in dom_low
    assert dom_low.count("a flowing chiffon dress") == 1

    # HIGH: caption + graded HIGH tier prose (the actual explicit garment text, not a
    # generic clause).
    tier_high = OUTFIT_DESCRIPTIONS[T.BUSINESS_SUIT][N.HIGH]
    dom_high = outfit_ep.build_prompt(
        T.BUSINESS_SUIT, None, N.HIGH,
        outfit_detail="a flowing chiffon dress", detail_dominant=True,
    )
    assert "a flowing chiffon dress" in dom_high
    assert tier_high in dom_high
    assert "barely covering anything, breasts and intimate areas fully exposed" not in dom_high

    # Works with prompt_mode="dress": the dress lead phrasing is kept, fed the caption,
    # and the graded tier prose is still appended additively.
    dom_dress = outfit_ep.build_prompt(
        T.BUSINESS_SUIT, None, N.MEDIUM, outfit_detail="a flowing chiffon dress",
        prompt_mode="dress", detail_dominant=True,
    )
    assert dom_dress.startswith("The person is currently completely nude; dress them in: a flowing chiffon dress")
    assert tier_med in dom_dress

    # Guardrails: with detail_dominant but an EMPTY detail, fall back to tier prose
    # unchanged (the flag only fires when there is a caption to be dominant with).
    assert outfit_ep.build_prompt(T.BUSINESS_SUIT, None, N.LOW, detail_dominant=True) == \
        outfit_ep.build_prompt(T.BUSINESS_SUIT, None, N.LOW)
    print("c31 OK: detail_dominant is additive — caption leads, graded tier prose appended; LOW/empty unchanged")


# ---------------------------------------------------------------------------
# c31b — outfit build_prompt: detail_dominant fallback when the outfit enum is
# ABSENT from OUTFIT_DESCRIPTIONS (no tier prose) — the garment-neutral
# _DETAIL_DOMINANT_EXPOSURE clause still carries the nudity ramp.
# ---------------------------------------------------------------------------
def test_outfit_detail_dominant_missing_enum_uses_exposure_fallback():
    N = NudityLevel
    # A synthetic outfit not present in OUTFIT_DESCRIPTIONS (and != NAKED) exercises
    # the no-tier-prose fallback branch. Must be hashable (used as a dict key via
    # OUTFIT_DESCRIPTIONS.get), so a plain object instance rather than SimpleNamespace.
    class _FakeOutfit:
        value = "mystery_couture_gown"

    fake_outfit = _FakeOutfit()

    dom = outfit_ep.build_prompt(
        fake_outfit, None, N.MEDIUM,
        outfit_detail="a flowing chiffon dress", detail_dominant=True,
    )
    assert "a flowing chiffon dress" in dom
    # No tier prose exists -> the garment-neutral exposure clause carries the ramp.
    assert "worn partially open with real exposure of bare skin" in dom

    # HIGH -> the top exposure clause.
    dom_high = outfit_ep.build_prompt(
        fake_outfit, None, N.HIGH,
        outfit_detail="a flowing chiffon dress", detail_dominant=True,
    )
    assert "barely covering anything, breasts and intimate areas fully exposed" in dom_high

    # LOW -> no exposure clause appended (fully clothed).
    dom_low = outfit_ep.build_prompt(
        fake_outfit, None, N.LOW,
        outfit_detail="a flowing chiffon dress", detail_dominant=True,
    )
    for clause in (
        "worn to tease", "real exposure of bare skin",
        "nearly spilling free", "barely covering anything",
    ):
        assert clause not in dom_low
    print("c31b OK: detail_dominant missing-enum fallback still emits _DETAIL_DOMINANT_EXPOSURE")


# ---------------------------------------------------------------------------
# c32 — build_pose_prompt: identity_anchors (D1) appended immediately after
# pose_identity_clause(); absent when None/empty (back-compat).
# ---------------------------------------------------------------------------
def test_pose_prompt_identity_anchors_appended():
    base = pose_ep.build_pose_prompt(PoseType.SITTING)
    anchors = "straight blonde hair, green eyes, curvy build with medium breasts"

    anchored = pose_ep.build_pose_prompt(PoseType.SITTING, identity_anchors=anchors)
    expected_clause = (
        f"She has {anchors}; keep these and her body proportions and build "
        f"exactly as in image 1, completely unchanged."
    )
    assert expected_clause in anchored
    # Placed immediately adjacent to the generic pose_identity_clause().
    clause = pc.pose_identity_clause()
    assert anchored.index(clause) < anchored.index(expected_clause)
    assert f"{clause}. {expected_clause}" in anchored
    # And still ahead of "The new pose should match image 2 accurately."
    assert anchored.index(expected_clause) < anchored.index("The new pose should match image 2 accurately.")

    # None/empty -> byte-identical to the base prompt (back-compat).
    assert pose_ep.build_pose_prompt(PoseType.SITTING, identity_anchors=None) == base
    assert pose_ep.build_pose_prompt(PoseType.SITTING, identity_anchors="   ") == base
    print("c32 OK: identity_anchors appended right after pose_identity_clause(); absent when None/empty")


# ---------------------------------------------------------------------------
# c33 — outfit build_prompt: identity_anchors (D1) appended right after
# pc.identity_clause(...) on BOTH branches; absent when None/empty.
# ---------------------------------------------------------------------------
def test_outfit_prompt_identity_anchors_appended():
    anchors = "straight blonde hair, green eyes, curvy build with medium breasts"
    expected_clause = f"she has {anchors}, kept exactly unchanged"

    # Dressed branch.
    base_dressed = outfit_ep.build_prompt(OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW)
    dressed = outfit_ep.build_prompt(
        OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW, identity_anchors=anchors,
    )
    assert expected_clause in dressed
    identity = pc.identity_clause("the outfit and clothing")
    assert dressed.index(identity) < dressed.index(expected_clause)
    assert outfit_ep.build_prompt(
        OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW, identity_anchors=None,
    ) == base_dressed
    assert outfit_ep.build_prompt(
        OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW, identity_anchors="   ",
    ) == base_dressed

    # NAKED branch.
    base_naked = outfit_ep.build_prompt(OutfitType.NAKED, None, NudityLevel.HIGH)
    naked = outfit_ep.build_prompt(
        OutfitType.NAKED, None, NudityLevel.HIGH, identity_anchors=anchors,
    )
    assert expected_clause in naked
    naked_identity = pc.identity_clause("the clothing and covering")
    assert naked.index(naked_identity) < naked.index(expected_clause)
    assert outfit_ep.build_prompt(
        OutfitType.NAKED, None, NudityLevel.HIGH, identity_anchors=None,
    ) == base_naked
    print("c33 OK: identity_anchors appended right after pc.identity_clause(...) on both branches; absent when None/empty")


# ---------------------------------------------------------------------------
# c34 (WS3) — age_phrase buckets: each carries its number + distinct adult
# vocabulary; no youth/underage words anywhere across the 18-50 range.
# ---------------------------------------------------------------------------
def test_age_phrase_buckets():
    a18, a25, a45 = ap.age_phrase(18), ap.age_phrase(25), ap.age_phrase(45)
    # Number present + three distinct bucket strings (18/25/45 no longer all mid-20s).
    assert "18" in a18 and "25" in a25 and "45" in a45
    assert len({a18, a25, a45}) == 3
    assert "fresh-faced" in a18
    assert "mid-twenties" in a25
    assert "forties" in a45
    # SAFETY: every age is adult-worded, and no youth/underage word ever appears.
    banned = ("teen", "teenage", "adolescent", "child", "girl")
    for age in range(18, 51):
        text = ap.age_phrase(age).lower()
        assert "adult" in text or "woman" in text, f"age {age} not adult-worded: {text!r}"
        for w in banned:
            assert w not in text, f"age {age} contains banned youth word {w!r}: {text!r}"
    # None/0 -> "" (unchanged).
    assert ap.age_phrase(None) == "" and ap.age_phrase(0) == ""
    print("c34 OK: age buckets carry number + distinct adult vocab; no youth words 18-50")


# ---------------------------------------------------------------------------
# c35 (WS3) — default-clothing pool: seeded variety + LOW/SUGGESTIVE coverage
# guard; variety_seed=None returns the legacy single string (kill-switch).
# ---------------------------------------------------------------------------
def test_generation_default_clothing_pool_and_coverage_guard():
    from services.outfit_vocab import (
        generation_outfit_clause,
        _GENERATION_DEFAULT_CLOTHING,
        OUTFIT_DESCRIPTIONS,
    )

    # variety_seed=None -> the legacy single string, byte-identical, for every level.
    for level in NudityLevel:
        assert generation_outfit_clause(None, level) == _GENERATION_DEFAULT_CLOTHING[level]

    # A variety_seed yields >1 distinct default outfit at LOW across a sample of seeds.
    low_variants = {generation_outfit_clause(None, NudityLevel.LOW, variety_seed=s) for s in range(30)}
    assert len(low_variants) > 1, low_variants

    # Coverage guard present at LOW and SUGGESTIVE on the varied default path.
    low_v = generation_outfit_clause(None, NudityLevel.LOW, variety_seed=1)
    sug_v = generation_outfit_clause(None, NudityLevel.SUGGESTIVE, variety_seed=1)
    assert "modest neckline, shoulders and midriff covered" in low_v
    assert "covered except a hint of cleavage" in sug_v
    # MEDIUM+ get NO coverage guard (they are meant to expose).
    med_v = generation_outfit_clause(None, NudityLevel.MEDIUM, variety_seed=1)
    assert "shoulders and midriff covered" not in med_v
    assert "covered except a hint of cleavage" not in med_v

    # Same seed reproducible.
    assert generation_outfit_clause(None, NudityLevel.LOW, variety_seed=7) == \
        generation_outfit_clause(None, NudityLevel.LOW, variety_seed=7)

    # A specific outfit ignores variety_seed (unchanged OUTFIT_DESCRIPTIONS path).
    assert generation_outfit_clause(OutfitType.BUSINESS_SUIT, NudityLevel.LOW, variety_seed=3) == \
        generation_outfit_clause(OutfitType.BUSINESS_SUIT, NudityLevel.LOW)
    assert OUTFIT_DESCRIPTIONS[OutfitType.BUSINESS_SUIT][NudityLevel.LOW] in \
        generation_outfit_clause(OutfitType.BUSINESS_SUIT, NudityLevel.LOW, variety_seed=3)
    print("c35 OK: default-clothing pool varies by seed; coverage guard at LOW/SUGGESTIVE; None=legacy")


# ---------------------------------------------------------------------------
# c36 (WS3) — seeded shot variety: different seeds vary framing; same seed is
# reproducible; variety_seed=None reproduces the waist-up/eye-level hero default
# (kill-switch invariant); an explicit client shot still wins.
# ---------------------------------------------------------------------------
def test_generation_shot_variety_seeded():
    from models.requests import ShotOptions
    from models.enums import ShotFramingType
    from services import camera_vocab as cv

    persona = PersonaOptions(
        name="Nova", ethnicity="asian", age=26, hairStyle="ponytail", hairColor="black",
        eyeColor="brown", bodyType="average", breastSize="medium",
    )
    # Kill-switch: variety_seed=None -> hero default waist-up / eye-level, no pose phrase.
    base = pg.assemble_generation_prompt(persona, nudity_level=NudityLevel.LOW)[0]
    assert "waist-up portrait" in base
    assert "shot at eye level, facing the camera, centered composition" in base
    assert not any(ph in base for ph in cv.POSE_VARIETY_PHRASES)

    # Different seeds vary the framing across a sample.
    framings = set()
    for s in range(40):
        pos = pg.assemble_generation_prompt(persona, nudity_level=NudityLevel.LOW, variety_seed=s)[0]
        framings.add(frozenset(fp for fp in cv.FRAMING_PHRASES.values() if fp in pos))
    assert len(framings) > 1, framings

    # Same seed reproducible.
    assert pg.assemble_generation_prompt(persona, nudity_level=NudityLevel.LOW, variety_seed=13)[0] == \
        pg.assemble_generation_prompt(persona, nudity_level=NudityLevel.LOW, variety_seed=13)[0]

    # An explicit client shot wins even with variety on.
    forced = pg.assemble_generation_prompt(
        persona, shot=ShotOptions(framing=ShotFramingType.FULL_BODY),
        nudity_level=NudityLevel.LOW, variety_seed=13,
    )[0]
    assert "full-body shot, whole figure in frame" in forced
    print("c36 OK: seeded shot variety; None=waist-up/eye-level kill-switch; explicit shot wins")


# ---------------------------------------------------------------------------
# c37 (WS3) — pose_text used verbatim and suppresses the seeded pool pick;
# blank/whitespace pose_text falls back to the pool.
# ---------------------------------------------------------------------------
def test_generation_pose_text_verbatim_suppresses_pool():
    from services import camera_vocab as cv

    persona = PersonaOptions(
        name="Nova", ethnicity="asian", age=26, hairStyle="ponytail", hairColor="black",
        eyeColor="brown", bodyType="average", breastSize="medium",
    )
    marker = "balancing a book on her head, arms held out"
    pos = pg.assemble_generation_prompt(
        persona, nudity_level=NudityLevel.LOW, variety_seed=42, pose_text=marker,
    )[0]
    assert marker in pos
    assert not any(ph in pos for ph in cv.POSE_VARIETY_PHRASES)  # pool pick suppressed

    # Whitespace-only pose_text is NOT an override -> pool pick still applied.
    pos_blank = pg.assemble_generation_prompt(
        persona, nudity_level=NudityLevel.LOW, variety_seed=42, pose_text="   ",
    )[0]
    assert any(ph in pos_blank for ph in cv.POSE_VARIETY_PHRASES)
    print("c37 OK: pose_text used verbatim and suppresses the pool pick; blank falls back to pool")


# ---------------------------------------------------------------------------
# c38 (WS3) — flavor gating: kink moods dropped at LOW/SUGGESTIVE, kept at
# MEDIUM+; personality/occupation still express at every level.
# ---------------------------------------------------------------------------
def test_generation_flavor_gating_by_nudity():
    persona = PersonaOptions(
        name="Ivy", ethnicity="latina", age=27, hairStyle="curly", hairColor="black",
        eyeColor="brown", bodyType="curvy", breastSize="large",
        personality="temptress", occupation="dancer", kinks=["bondage", "spanking"],
    )
    kink0 = ap.phrase(ap.KINK_PHRASES, "bondage")
    persona_expr = ap.phrase(ap.PERSONALITY_PHRASES, "temptress")
    occ = ap.phrase(ap.OCCUPATION_PHRASES, "dancer")

    for level in (NudityLevel.LOW, NudityLevel.SUGGESTIVE):
        pos = pg.assemble_generation_prompt(persona, nudity_level=level)[0]
        assert kink0 not in pos, f"{level}: kink mood should be dropped"
        assert persona_expr in pos and occ in pos, f"{level}: personality/occupation dropped"

    for level in (NudityLevel.MEDIUM, NudityLevel.REVEALING, NudityLevel.HIGH):
        pos = pg.assemble_generation_prompt(persona, nudity_level=level)[0]
        assert kink0 in pos, f"{level}: kink mood should be retained (today's behavior)"
    print("c38 OK: kink moods dropped at LOW/SUGGESTIVE, kept at MEDIUM+; personality/occupation always kept")


# ---------------------------------------------------------------------------
# c39 (WS3) — the locked identity block (age + ethnicity/hair/eyes/body/breasts)
# is byte-identical whether or not variety is on, and always present verbatim.
# ---------------------------------------------------------------------------
def test_variety_preserves_locked_identity():
    persona = PersonaOptions(
        name="Mara", ethnicity="black_afro", age=31, hairStyle="bun", hairColor="black",
        eyeColor="brown", bodyType="athletic", breastSize="small",
    )
    _pos_none, _neg, locked_none = pg.assemble_generation_prompt(persona, nudity_level=NudityLevel.LOW)
    for s in (1, 2, 7, 100):
        pos, _n, locked = pg.assemble_generation_prompt(
            persona, nudity_level=NudityLevel.LOW, variety_seed=s
        )
        assert locked == locked_none, f"seed {s}: locked identity changed under variety"
        assert locked in pos, f"seed {s}: locked block not present verbatim"
    # The locked block carries the age bucket + every attribute.
    assert "31 years old" in locked_none
    assert "a Black woman with warm dark-brown skin" in locked_none
    assert "black hair" in locked_none and "brown eyes" in locked_none
    assert "toned athletic figure" in locked_none and "small breasts" in locked_none
    print("c39 OK: locked identity (age + ethnicity/hair/eyes/body/breasts) unchanged by variety")


# ---------------------------------------------------------------------------
# Phase 4 (trait-aware edits) — background build_background_prompt: identity_anchors
# appended after the identity clause; absent when None/empty (back-compat).
# ---------------------------------------------------------------------------
def test_background_prompt_identity_anchors_appended():
    anchors = "warm dark-brown skin, straight black hair, brown eyes, curvy build"
    expected_clause = f"she has {anchors}, kept exactly unchanged"
    base = background_ep.build_background_prompt("a sunny beach")

    anchored = background_ep.build_background_prompt("a sunny beach", identity_anchors=anchors)
    assert expected_clause in anchored
    # Placed right after the identity clause, before the lighting-adapt clause.
    identity = pc.identity_clause("the background and surroundings")
    assert anchored.index(identity) < anchored.index(expected_clause)
    assert anchored.index(expected_clause) < anchored.index("adapt lighting and shadows")

    # None/empty -> byte-identical to the base prompt (back-compat).
    assert background_ep.build_background_prompt("a sunny beach", identity_anchors=None) == base
    assert background_ep.build_background_prompt("a sunny beach", identity_anchors="   ") == base
    print("bg-anchor OK: background identity_anchors appended after identity clause; absent when None/empty")


# ---------------------------------------------------------------------------
# Phase 4 — server-side identityAnchors population from characterId.
# ---------------------------------------------------------------------------
class _FakeCharacterStore:
    """Minimal async store: get(id) -> character or None (KeyError-safe)."""
    def __init__(self, characters):
        self._characters = characters

    async def get(self, character_id):
        return self._characters.get(character_id)


def _dark_skin_character():
    persona = PersonaOptions(
        ethnicity="black_afro", age=28, hairStyle="straight", hairColor="black",
        eyeColor="brown", bodyType="curvy", breastSize="medium", name="Nia",
    )
    return SimpleNamespace(persona=persona)


def test_populate_identity_anchors_resolves_skin_tone_from_character_id():
    store = _FakeCharacterStore({"c1": _dark_skin_character()})

    # characterId present + no explicit anchors -> populated, skin tone LEADS, and
    # the eventual edit prompt (via build_prompt) carries the skin-tone anchor.
    req = OutfitEditRequest(
        source_image="https://x.supabase.co/i.png",
        outfit=OutfitType.BUSINESS_SUIT, characterId="c1",
    )
    asyncio.run(populate_identity_anchors(store, req))
    assert req.identityAnchors is not None
    assert req.identityAnchors.startswith("warm dark-brown skin")
    prompt = outfit_ep.build_prompt(
        OutfitType.BUSINESS_SUIT, None, NudityLevel.LOW,
        identity_anchors=req.identityAnchors,
    )
    assert "warm dark-brown skin" in prompt

    # Explicit anchors are NEVER overridden.
    req_explicit = OutfitEditRequest(
        source_image="https://x.supabase.co/i.png",
        outfit=OutfitType.BUSINESS_SUIT, characterId="c1",
        identityAnchors="pale skin, red hair",
    )
    asyncio.run(populate_identity_anchors(store, req_explicit))
    assert req_explicit.identityAnchors == "pale skin, red hair"

    # Unknown characterId -> no crash, no anchors.
    req_unknown = OutfitEditRequest(
        source_image="https://x.supabase.co/i.png",
        outfit=OutfitType.BUSINESS_SUIT, characterId="does-not-exist",
    )
    asyncio.run(populate_identity_anchors(store, req_unknown))
    assert req_unknown.identityAnchors is None

    # Store not configured (None) -> no crash, no anchors.
    req_no_store = OutfitEditRequest(
        source_image="https://x.supabase.co/i.png",
        outfit=OutfitType.BUSINESS_SUIT, characterId="c1",
    )
    asyncio.run(populate_identity_anchors(None, req_no_store))
    assert req_no_store.identityAnchors is None

    # No characterId at all -> no-op.
    req_no_id = OutfitEditRequest(
        source_image="https://x.supabase.co/i.png", outfit=OutfitType.BUSINESS_SUIT,
    )
    asyncio.run(populate_identity_anchors(store, req_no_id))
    assert req_no_id.identityAnchors is None
    print("populate OK: resolves from id, respects explicit, tolerates unknown/no-store/no-id")


def test_populate_identity_anchors_pose_and_background_requests():
    # The same helper works for PoseEditRequest and BackgroundEditRequest, and the
    # resolved anchor reaches each step's prompt builder (end-to-end skin-tone anchor).
    store = _FakeCharacterStore({"c1": _dark_skin_character()})

    pose_req = PoseEditRequest(
        source_image="https://x.supabase.co/i.png",
        pose=PoseType.SITTING, characterId="c1",
    )
    asyncio.run(populate_identity_anchors(store, pose_req))
    assert pose_req.identityAnchors.startswith("warm dark-brown skin")
    pose_prompt = pose_ep.build_pose_prompt(
        pose_req.pose, identity_anchors=pose_req.identityAnchors
    )
    assert "warm dark-brown skin" in pose_prompt

    bg_req = BackgroundEditRequest(
        source_image="https://x.supabase.co/i.png",
        prompt="a sunny beach", characterId="c1",
    )
    asyncio.run(populate_identity_anchors(store, bg_req))
    assert bg_req.identityAnchors.startswith("warm dark-brown skin")
    bg_prompt = background_ep.build_background_prompt(
        bg_req.prompt, identity_anchors=bg_req.identityAnchors
    )
    assert "warm dark-brown skin" in bg_prompt
    print("populate-pose-bg OK: helper populates Pose/Background requests; anchor reaches both builders")


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
        test_outfit_nude_base_mode_neutral_body,
        test_strip_companions,
        test_pose_prompt_keep_background_solo_and_location,
        test_pose_prompt_pose_detail_replaces_enum_description,
        test_pose_prompt_outfit_continuity_phrasing,
        test_outfit_continuity_text,
        test_outfit_dress_mode_lead,
        test_outfit_detail_dominant_renders_caption_plus_tier_prose,
        test_outfit_detail_dominant_missing_enum_uses_exposure_fallback,
        test_pose_prompt_identity_anchors_appended,
        test_outfit_prompt_identity_anchors_appended,
        test_age_phrase_buckets,
        test_generation_default_clothing_pool_and_coverage_guard,
        test_generation_shot_variety_seeded,
        test_generation_pose_text_verbatim_suppresses_pool,
        test_generation_flavor_gating_by_nudity,
        test_variety_preserves_locked_identity,
        test_background_prompt_identity_anchors_appended,
        test_populate_identity_anchors_resolves_skin_tone_from_character_id,
        test_populate_identity_anchors_pose_and_background_requests,
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
