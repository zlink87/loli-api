"""
Tests for the B3 garnish — wardrobe/demeanor-biased character generation.

Three slices:
  1a. outfit_vocab.generation_outfit_clause(..., wardrobe_styles=...) narrows the
      seeded default-clothing pool by style tags, with byte-identical parity when
      wardrobe_styles is None/empty (the existing seeded tests already lock the
      no-arg path; these lock the new arg's parity + the narrowing behavior).
  1b. prompt_generator.assemble_generation_prompt / generate_generation_prompt gain
      wardrobe_styles + demeanor pass-throughs; None is byte-identical.
  1c. generate.populate_wardrobe_traits() resolves a characterId -> trait profile ->
      auto-fills wardrobeStyles/demeanor, best-effort (never overrides an explicit
      value, never raises).

Runs under pytest or directly: python loli_api/tests/test_generation_wardrobe_traits.py
"""
import asyncio

from models.enums import NudityLevel, WardrobeStyleType, DemeanorType
from models.requests import GenerateImageRequest, PersonaOptions
from services import camera_vocab as cv
from services import outfit_vocab as ov
from services import prompt_generator as pg


def _persona():
    return PersonaOptions(
        name="Nova", ethnicity="asian", age=26, hairStyle="ponytail", hairColor="black",
        eyeColor="brown", bodyType="average", breastSize="medium",
    )


# ---------------------------------------------------------------------------
# 1a — generation_outfit_clause wardrobe parity + narrowing
# ---------------------------------------------------------------------------
def test_generation_clause_wardrobe_none_is_byte_identical():
    # wardrobe_styles None / [] must not change the seeded draw at any level/seed.
    for level in NudityLevel:
        for seed in (1, 7, 13, 42, 99):
            base = ov.generation_outfit_clause(None, level, variety_seed=seed)
            same = ov.generation_outfit_clause(None, level, variety_seed=seed, wardrobe_styles=None)
            empty = ov.generation_outfit_clause(None, level, variety_seed=seed, wardrobe_styles=[])
            assert base == same == empty, (level, seed)
    # Variety-off path ignores wardrobe entirely (branch not taken).
    for level in NudityLevel:
        assert ov.generation_outfit_clause(None, level) == \
            ov.generation_outfit_clause(None, level, wardrobe_styles=[WardrobeStyleType.SPORTY])
    # A specific outfit ignores wardrobe (OUTFIT_DESCRIPTIONS path).
    from models.enums import OutfitType
    assert ov.generation_outfit_clause(OutfitType.BUSINESS_SUIT, NudityLevel.LOW, variety_seed=3) == \
        ov.generation_outfit_clause(
            OutfitType.BUSINESS_SUIT, NudityLevel.LOW, variety_seed=3,
            wardrobe_styles=[WardrobeStyleType.SPORTY],
        )


def test_generation_clause_wardrobe_narrows_pool_to_matching_entries():
    # cozy_lounge tags SOME (not all) LOW entries -> the filter is a proper subset,
    # so a biased draw must never land on a non-matching entry and must be able to
    # reach every matching one.
    style = WardrobeStyleType.COZY_LOUNGE
    level = NudityLevel.LOW
    pool = ov._GENERATION_DEFAULT_CLOTHING_POOL[level]
    tags = ov._GENERATION_POOL_STYLE_TAGS[level]
    eligible = {pool[i] for i, fs in enumerate(tags) if style in fs}
    ineligible = set(pool) - eligible
    assert eligible and ineligible, "test needs a proper subset to be meaningful"

    guard = ov._GENERATION_COVERAGE_GUARD.get(level, "")
    seen = set()
    for seed in range(200):
        clause = ov.generation_outfit_clause(None, level, variety_seed=seed, wardrobe_styles=[style])
        garment = clause[: -len(guard)] if guard and clause.endswith(guard) else clause
        assert garment in eligible, (seed, garment)
        seen.add(garment)
    assert seen == eligible, "biased draw should reach every matching entry across seeds"


def test_generation_clause_style_absent_from_pool_falls_back_to_full_pool():
    # SPORTY tags NO generation-pool entry (the pool is everyday-real garments), so the
    # filter empties -> full pool -> byte-identical to the no-wardrobe draw. This is the
    # plan's 'sporty' scenario: it degrades to the full pool rather than emptying.
    level = NudityLevel.LOW
    for seed in range(60):
        base = ov.generation_outfit_clause(None, level, variety_seed=seed)
        sporty = ov.generation_outfit_clause(
            None, level, variety_seed=seed, wardrobe_styles=[WardrobeStyleType.SPORTY]
        )
        assert base == sporty, seed


def test_generation_clause_wardrobe_tolerates_raw_string_and_unknown():
    level = NudityLevel.MEDIUM
    for seed in range(30):
        by_enum = ov.generation_outfit_clause(
            None, level, variety_seed=seed, wardrobe_styles=[WardrobeStyleType.GLAMOROUS]
        )
        by_str = ov.generation_outfit_clause(
            None, level, variety_seed=seed, wardrobe_styles=["glamorous", "not-a-style"]
        )
        assert by_enum == by_str, seed


# ---------------------------------------------------------------------------
# 1b — assemble_generation_prompt / generate_generation_prompt pass-throughs
# ---------------------------------------------------------------------------
def test_assemble_wardrobe_demeanor_none_is_byte_identical():
    persona = _persona()
    for seed in (1, 7, 13, 42, 100):
        base = pg.assemble_generation_prompt(persona, nudity_level=NudityLevel.LOW, variety_seed=seed)
        same = pg.assemble_generation_prompt(
            persona, nudity_level=NudityLevel.LOW, variety_seed=seed,
            wardrobe_styles=None, demeanor=None,
        )
        assert base == same, seed
    # Variety off: wardrobe/demeanor are ignored (no variety branch), so still identical.
    assert pg.assemble_generation_prompt(persona) == pg.assemble_generation_prompt(
        persona, wardrobe_styles=[WardrobeStyleType.GLAMOROUS], demeanor=DemeanorType.SULTRY
    )


def test_generate_generation_prompt_wrapper_none_parity():
    persona = _persona()
    gen = pg.PromptGenerator()
    for seed in (5, 23):
        a = asyncio.run(gen.generate_generation_prompt(
            persona, nudity_level=NudityLevel.LOW, variety_seed=seed))
        b = asyncio.run(gen.generate_generation_prompt(
            persona, nudity_level=NudityLevel.LOW, variety_seed=seed,
            wardrobe_styles=None, demeanor=None))
        assert a == b, seed


def test_assemble_demeanor_biases_expression_pool():
    persona = _persona()
    shy_phrases = {cv.EXPRESSION_PHRASES[v] for v in cv.DEMEANOR_EXPRESSION_POOLS[DemeanorType.SHY]}
    off_pool = set(cv.EXPRESSION_PHRASES.values()) - shy_phrases
    for seed in range(80):
        pos = pg.assemble_generation_prompt(
            persona, nudity_level=NudityLevel.LOW, variety_seed=seed, demeanor=DemeanorType.SHY,
        )[0]
        leaked = [ph for ph in off_pool if ph in pos]
        assert not leaked, (seed, leaked)  # no non-shy expression ever under SHY
    # Demeanor actually changes the outcome vs the default pool for some seed.
    changed = any(
        pg.assemble_generation_prompt(persona, nudity_level=NudityLevel.LOW, variety_seed=s)[0]
        != pg.assemble_generation_prompt(
            persona, nudity_level=NudityLevel.LOW, variety_seed=s, demeanor=DemeanorType.SULTRY)[0]
        for s in range(20)
    )
    assert changed


def test_assemble_wardrobe_biases_clothing_on_variety_path():
    # A wardrobe value narrows the seeded clothing pool inside the full assembler too.
    persona = _persona()
    changed = any(
        pg.assemble_generation_prompt(persona, nudity_level=NudityLevel.MEDIUM, variety_seed=s)[0]
        != pg.assemble_generation_prompt(
            persona, nudity_level=NudityLevel.MEDIUM, variety_seed=s,
            wardrobe_styles=[WardrobeStyleType.GLAMOROUS])[0]
        for s in range(40)
    )
    assert changed


# ---------------------------------------------------------------------------
# 1c — populate_wardrobe_traits resolver (characterId -> trait profile)
# ---------------------------------------------------------------------------
class _FakeTraitStore:
    def __init__(self, row):
        self._row = row
        self.calls = 0

    async def get(self, character_id):
        self.calls += 1
        return self._row


def test_populate_wardrobe_traits_fills_from_profile():
    from api.v1.endpoints.generate import populate_wardrobe_traits
    row = {"profile": {"wardrobe_styles": ["sporty", "streetwear"],
                       "demeanor": ["playful", "confident"]}}
    store = _FakeTraitStore(row)
    req = GenerateImageRequest(persona=_persona(), characterId="c1")
    asyncio.run(populate_wardrobe_traits(store, req))
    assert req.wardrobeStyles == [WardrobeStyleType.SPORTY, WardrobeStyleType.STREETWEAR]
    assert req.demeanor == DemeanorType.PLAYFUL  # first demeanor of the list


def test_populate_wardrobe_traits_never_overrides_explicit():
    from api.v1.endpoints.generate import populate_wardrobe_traits
    store = _FakeTraitStore({"profile": {"wardrobe_styles": ["sporty"], "demeanor": ["playful"]}})
    req = GenerateImageRequest(
        persona=_persona(), characterId="c1",
        wardrobeStyles=[WardrobeStyleType.ELEGANT], demeanor=DemeanorType.SULTRY,
    )
    asyncio.run(populate_wardrobe_traits(store, req))
    assert req.wardrobeStyles == [WardrobeStyleType.ELEGANT]
    assert req.demeanor == DemeanorType.SULTRY
    assert store.calls == 0  # both explicit -> store never queried


def test_populate_wardrobe_traits_fills_only_missing_field():
    from api.v1.endpoints.generate import populate_wardrobe_traits
    store = _FakeTraitStore({"profile": {"wardrobe_styles": ["sporty"], "demeanor": ["mysterious"]}})
    req = GenerateImageRequest(
        persona=_persona(), characterId="c1", wardrobeStyles=[WardrobeStyleType.ELEGANT],
    )
    asyncio.run(populate_wardrobe_traits(store, req))
    assert req.wardrobeStyles == [WardrobeStyleType.ELEGANT]  # explicit kept
    assert req.demeanor == DemeanorType.MYSTERIOUS            # filled from profile


def test_populate_wardrobe_traits_graceful_degrade():
    from api.v1.endpoints.generate import populate_wardrobe_traits
    persona = _persona()

    # No characterId -> no-op; the store is never queried.
    req = GenerateImageRequest(persona=persona)
    store = _FakeTraitStore({"profile": {"wardrobe_styles": ["sporty"]}})
    asyncio.run(populate_wardrobe_traits(store, req))
    assert req.wardrobeStyles is None and req.demeanor is None and store.calls == 0

    # Store None (not configured) -> no-op.
    req2 = GenerateImageRequest(persona=persona, characterId="c1")
    asyncio.run(populate_wardrobe_traits(None, req2))
    assert req2.wardrobeStyles is None and req2.demeanor is None

    # Unknown character (row None) / empty profile -> no-op.
    req3 = GenerateImageRequest(persona=persona, characterId="c1")
    asyncio.run(populate_wardrobe_traits(_FakeTraitStore(None), req3))
    assert req3.wardrobeStyles is None and req3.demeanor is None
    req3b = GenerateImageRequest(persona=persona, characterId="c1")
    asyncio.run(populate_wardrobe_traits(_FakeTraitStore({"profile": {}}), req3b))
    assert req3b.wardrobeStyles is None and req3b.demeanor is None

    # Store raises -> swallowed, no-op.
    class _Boom:
        async def get(self, cid):
            raise RuntimeError("db down")

    req4 = GenerateImageRequest(persona=persona, characterId="c1")
    asyncio.run(populate_wardrobe_traits(_Boom(), req4))
    assert req4.wardrobeStyles is None and req4.demeanor is None


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
