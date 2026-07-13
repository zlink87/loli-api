"""
Tests for TraitProfileWriter (WS-B): keyless deterministic output (stable,
taste-coherent), fields=None -> all, per-field regen, Venice JSON path
(coerce + per-field fill + provider labelling), garbage-JSON fallback, cap/NAKED
enforcement on Venice output, and the taste-consistency instruction in the prompt.

Runs under pytest or directly: python loli_api/tests/test_trait_profile_writer.py
"""
import asyncio

from models.enums import OutfitType, WardrobeStyleType, ZodiacType
from models.requests import PersonaOptions
from models.trait_profile import ALL_TRAIT_FIELDS
from services.trait_profile_writer import TraitProfileWriter


def _persona():
    return PersonaOptions(
        ethnicity="latina", age=24, hairStyle="straight", hairColor="black",
        eyeColor="brown", bodyType="curvy", breastSize="medium", name="Nora",
        occupation="dancer", personality="temptress", relationship="sugar_baby",
        kinks=["playful_teasing", "cuddling"],
    )


def _persona_culture(culture):
    return PersonaOptions(
        ethnicity="latina", age=24, hairStyle="straight", hairColor="black",
        eyeColor="brown", bodyType="curvy", breastSize="medium", name="Nora",
        occupation="dancer", personality="temptress", relationship="sugar_baby",
        kinks=["playful_teasing", "cuddling"], culture=culture,
    )


def _writer(api_key=""):
    return TraitProfileWriter(api_key=api_key)


def _fake_chat(payload):
    async def chat(messages, **kw):
        return payload, {}
    return chat


# --- deterministic (no key) ---
def test_deterministic_returns_only_requested_fields():
    w = _writer()
    fields = ["wardrobe_styles", "demeanor", "likes"]
    values, provider = asyncio.run(w.write(_persona(), fields, {}, character_id="c1"))
    assert provider == "deterministic"
    assert set(values.keys()) == set(fields)


def test_fields_none_generates_all():
    w = _writer()
    values, _ = asyncio.run(w.write(_persona(), None, {}, character_id="c1"))
    assert set(values.keys()) == set(ALL_TRAIT_FIELDS)


def test_empty_fields_returns_empty():
    w = _writer()
    values, provider = asyncio.run(w.write(_persona(), [], {}, character_id="c1"))
    assert values == {} and provider == "deterministic"


def test_deterministic_is_hash_stable():
    w = _writer()
    v1, _ = asyncio.run(w.write(_persona(), None, {}, character_id="c-123"))
    v2, _ = asyncio.run(w.write(_persona(), None, {}, character_id="c-123"))
    assert v1 == v2
    # zodiac is a valid sign and stable for the same character_id
    assert v1["zodiac"] in {z.value for z in ZodiacType}


def test_deterministic_zodiac_seed_varies_by_character():
    w = _writer()
    seeds = {asyncio.run(w.write(_persona(), ["zodiac"], {}, character_id=f"c-{i}"))[0]["zodiac"]
             for i in range(30)}
    # crc32 % 12 across 30 distinct ids should yield several different signs.
    assert len(seeds) >= 3


def test_deterministic_taste_is_coherent():
    # temptress -> luxury_glam interior -> jewel_tones palette; dancer -> glamorous/sporty
    w = _writer()
    v, _ = asyncio.run(w.write(_persona(), None, {}, character_id="c1"))
    assert v["interior_style"] == "luxury_glam"
    assert v["color_palette"] == "jewel_tones"
    assert "glamorous" in v["wardrobe_styles"]
    # likes seeded from the interior-style taste table (luxury_glam) -> champagne is present
    assert any("champagne" in x for x in v["likes"])
    # the writer emits STYLE tags, not outfits (outfit_vocab deferred)
    assert v["favorite_outfits"] == [] and v["never_wears"] == []


def test_deterministic_never_emits_naked():
    w = _writer()
    v, _ = asyncio.run(w.write(_persona(), None, {}, character_id="c1"))
    assert "naked" not in v["favorite_outfits"] and "naked" not in v["never_wears"]


# --- user prompt construction ---
def test_user_prompt_lists_allowed_values_and_taste_consistency():
    w = _writer()
    prompt = w._build_user_prompt(_persona(), ["wardrobe_styles", "likes", "dislikes"], {}, None)
    # real allowed enum values interpolated
    assert "elegant" in prompt and "streetwear" in prompt
    # taste-consistency instruction present for likes/dislikes
    assert "CONSISTENT" in prompt
    assert "interior_style" in prompt
    # the character facts are included
    assert "temptress" in prompt


def test_user_prompt_includes_bio_context():
    w = _writer()
    prompt = w._build_user_prompt(_persona(), ["backstory"], {}, "A night-shift dancer.")
    assert "night-shift dancer" in prompt


# --- Venice JSON path ---
def test_venice_all_fields_present_is_provider_venice():
    w = _writer(api_key="k")
    w._client.chat = _fake_chat(
        '{"wardrobe_styles":["elegant","edgy"],"demeanor":["sultry"]}'
    )
    values, provider = asyncio.run(
        w.write(_persona(), ["wardrobe_styles", "demeanor"], {}, character_id="c1")
    )
    assert provider == "venice"
    assert values["wardrobe_styles"] == ["elegant", "edgy"]
    assert values["demeanor"] == ["sultry"]


def test_venice_partial_fills_missing_and_is_mixed():
    w = _writer(api_key="k")
    # demeanor absent from the JSON -> filled deterministically -> mixed
    w._client.chat = _fake_chat('{"wardrobe_styles":["edgy"]}')
    values, provider = asyncio.run(
        w.write(_persona(), ["wardrobe_styles", "demeanor"], {}, character_id="c1")
    )
    assert values["wardrobe_styles"] == ["edgy"]
    assert values["demeanor"]  # deterministic fill (temptress -> sultry/playful)
    assert provider == "mixed"


def test_venice_bad_json_falls_back_deterministic():
    w = _writer(api_key="k")
    w._client.chat = _fake_chat("sorry, I can't do that")
    values, provider = asyncio.run(w.write(_persona(), ["wardrobe_styles"], {}, character_id="c1"))
    assert provider == "deterministic"
    assert values["wardrobe_styles"]  # deterministic (dancer)


def test_venice_output_is_capped_and_naked_stripped():
    w = _writer(api_key="k")
    # 5 styles (cap 3) + naked in favorites (stripped by coerce)
    w._client.chat = _fake_chat(
        '{"wardrobe_styles":["elegant","glamorous","sporty","edgy","girly"],'
        '"favorite_outfits":["naked","bikini"]}'
    )
    values, _ = asyncio.run(
        w.write(_persona(), ["wardrobe_styles", "favorite_outfits"], {}, character_id="c1")
    )
    assert len(values["wardrobe_styles"]) == 3
    assert "naked" not in values["favorite_outfits"]
    assert "bikini" in values["favorite_outfits"]


def test_venice_repairs_near_miss_enum():
    w = _writer(api_key="k")
    w._client.chat = _fake_chat('{"zodiac":"leoo"}')  # difflib -> leo
    values, provider = asyncio.run(w.write(_persona(), ["zodiac"], {}, character_id="c1"))
    assert values["zodiac"] == "leo"
    assert provider == "venice"


def test_enabled_flag():
    assert _writer("").enabled is False
    assert _writer("k").enabled is True


# --- enrichment folded into deterministic likes/dislikes ---
def test_enrichment_likes_flow_into_deterministic():
    w = _writer()
    values, _ = asyncio.run(
        w.write(_persona(), ["likes"], {"likes": ["salsa dancing"]}, character_id="c1")
    )
    assert any("salsa dancing" in x for x in values["likes"])


# --- public profile card (deterministic fallback) ---
def test_deterministic_card_fields_non_empty_and_human():
    w = _writer()
    card = ["short_description", "display_occupation", "display_personality",
            "display_hobbies", "language"]
    v, _ = asyncio.run(w.write(_persona(), card, {}, character_id="c1"))
    assert v["short_description"] and len(v["short_description"]) <= 220
    assert v["display_occupation"] and "_" not in v["display_occupation"]  # humanized
    assert 2 <= len(v["display_personality"]) <= 4
    assert all(x and len(x) <= 24 for x in v["display_personality"])
    assert 2 <= len(v["display_hobbies"]) <= 5
    assert all(x and len(x) <= 32 for x in v["display_hobbies"])
    assert v["language"] == "English"


def test_deterministic_display_occupation_humanized_title():
    w = _writer()
    p = PersonaOptions(
        ethnicity="caucasian", age=30, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="curvy", breastSize="medium", name="Ana",
        occupation="boss_ceo", personality="queen", relationship="boss",
    )
    v, _ = asyncio.run(w.write(p, ["display_occupation"], {}, character_id="c1"))
    assert v["display_occupation"] == "CEO and Boss"  # from the humanized-title table


def test_card_hobbies_prefer_enrichment():
    w = _writer()
    v, _ = asyncio.run(
        w.write(_persona(), ["display_hobbies"],
                {"hobbies": ["Sailing", "Painting"]}, character_id="c1")
    )
    assert "Sailing" in v["display_hobbies"] and "Painting" in v["display_hobbies"]


def test_venice_card_field_flows_and_is_clamped():
    w = _writer(api_key="k")
    w._client.chat = _fake_chat('{"short_description":"%s"}' % ("z" * 400))
    v, provider = asyncio.run(w.write(_persona(), ["short_description"], {}, character_id="c1"))
    assert len(v["short_description"]) == 220
    assert provider == "venice"


def test_user_prompt_card_specs_forbid_aispeak_and_enum_words():
    w = _writer()
    prompt = w._build_user_prompt(_persona(), ["short_description", "display_occupation"], {}, None)
    assert "HOOK" in prompt
    assert "humanized" in prompt.lower()


# --- ethnicity heritage hint (WS-2, display-only) ---
def _persona_eth(ethnicity):
    return PersonaOptions(
        ethnicity=ethnicity, age=27, hairStyle="straight", hairColor="blonde",
        eyeColor="green", bodyType="average", breastSize="medium", name="Mila",
        occupation="model", personality="lover", relationship="girlfriend",
    )


def test_facts_include_heritage_nationality_hint():
    w = _writer()
    prompt = w._build_user_prompt(_persona_eth("baltic"), ["backstory"], {}, None)
    # the fact sheet carries the heritage + example nationalities...
    assert "heritage:" in prompt
    assert "Baltic" in prompt and "Lithuanian" in prompt
    # ...and the backstory spec invites a matching nationality/name flavor
    assert "matching nationality" in prompt


def test_backstory_and_short_description_specs_mention_heritage():
    from services.trait_profile_writer import _FIELD_SPECS
    assert "heritage" in _FIELD_SPECS["backstory"]["instruction"].lower()
    assert "heritage" in _FIELD_SPECS["short_description"]["instruction"].lower()


def test_deterministic_survives_all_new_ethnicity_values():
    # The deterministic fallback ignores ethnicity, so every value (incl. the 20
    # new ones) must produce a full, coerced profile without raising.
    w = _writer()
    for eth in ("west_african", "baltic", "horn_of_africa", "mixed_heritage",
                "southeast_asian", "central_asian", "brazilian"):
        v, provider = asyncio.run(w.write(_persona_eth(eth), None, {}, character_id="c1"))
        assert provider == "deterministic"
        assert set(v.keys()) == set(ALL_TRAIT_FIELDS)
        assert v["backstory"] and v["short_description"]


def test_heritage_hint_degrades_for_unknown_value():
    # Unknown/None ethnicity -> humanized fallback / 'unspecified', never raises.
    from services.trait_profile_writer import _heritage_hint
    assert _heritage_hint(None) == ""
    assert _heritage_hint("klingon") == "klingon"  # humanized fallback
    assert _heritage_hint("mixed_heritage") == "of mixed heritage"


# --- culture / subculture (Stage 2) ---
def test_facts_include_culture_when_set_and_unspecified_when_not():
    w = _writer()
    with_c = w._build_user_prompt(_persona_culture("goth"), ["backstory"], {}, None)
    assert "culture/subculture:" in with_c
    assert "Goth" in with_c  # culture_hint label leads the fact line
    without_c = w._build_user_prompt(_persona(), ["backstory"], {}, None)
    assert "culture/subculture: unspecified" in without_c


def test_system_prompt_has_culture_fixed_input_rule():
    from services.trait_profile_writer import TRAIT_SYSTEM_PROMPT
    assert "culture/subculture" in TRAIT_SYSTEM_PROMPT
    assert "FIXED" in TRAIT_SYSTEM_PROMPT
    assert "NEVER contradict" in TRAIT_SYSTEM_PROMPT


def test_deterministic_dump_culture_goth_overrides_taste():
    w = _writer()
    v, provider = asyncio.run(w.write(_persona_culture("goth"), None, {}, character_id="c1"))
    assert provider == "deterministic"
    # goth CultureSpec drives the taste fields (over personality/occupation tables).
    assert v["demeanor"][0] == "mysterious"          # demeanor=(MYSTERIOUS, SULTRY), mysterious-first
    assert v["interior_style"] == "industrial_loft"
    assert v["color_palette"] == "bold_dark"
    assert "edgy" in v["wardrobe_styles"]
    # favorite_outfits / favorite_locations are now filled from the spec (were empty).
    assert v["favorite_outfits"] and v["favorite_locations"]
    assert "naked" not in v["favorite_outfits"]
    assert len(v["favorite_outfits"]) <= 5 and len(v["favorite_locations"]) <= 5
    # culture likes LEAD the likes list.
    assert v["likes"][0] == "gothic rock"


def test_deterministic_dump_culture_none_matches_no_culture_field():
    # Passing culture=None must be byte-identical to a persona with no culture field.
    w = _writer()
    a, pa = asyncio.run(w.write(_persona(), None, {}, character_id="c1"))
    b, pb = asyncio.run(w.write(_persona_culture(None), None, {}, character_id="c1"))
    assert a == b and pa == pb
    # And the no-culture path still emits empty favorite_outfits/locations (unchanged).
    assert a["favorite_outfits"] == [] and a["favorite_locations"] == []


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
