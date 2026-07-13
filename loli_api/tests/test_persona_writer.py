"""
Tests for PersonaWriter (Feature 1): per-field voice, deterministic fallback,
Venice JSON parsing, per-field fill/clamp, provider labelling.

Runs under pytest or directly: python loli_api/tests/test_persona_writer.py
"""
import asyncio

from models.requests import PersonaOptions
from services import persona_writer as pwmod
from services.persona_writer import PersonaWriter, _FIELD_SPECS


def _persona():
    return PersonaOptions(
        ethnicity="latina", age=24, hairStyle="straight", hairColor="black",
        eyeColor="brown", bodyType="curvy", breastSize="medium", name="Nora",
        occupation="stripper", personality="nympho", relationship="sugar_baby",
        kinks=["oral_play", "punishment"],
    )


def _writer(api_key=""):
    return PersonaWriter(api_key=api_key)


def _fake_chat(payload):
    async def chat(messages, **kw):
        return payload, {}
    return chat


# --- deterministic fallback (no key) ---
def test_deterministic_returns_only_requested_fields():
    w = _writer()
    fields = ["system_prompt", "greeting_message", "bio"]
    values, provider = asyncio.run(w.write(_persona(), fields, {}, name="Nora"))
    assert provider == "deterministic"
    assert set(values.keys()) == set(fields)


def test_deterministic_respects_per_field_voice():
    w = _writer()
    fields = ["system_prompt", "greeting_message", "bio", "summary", "tone", "style"]
    values, _ = asyncio.run(w.write(_persona(), fields, {}, name="Nora"))
    # 3rd person, client-facing description ABOUT her — never "You are" or AI directives
    assert values["system_prompt"].startswith("Nora is a")
    assert "You are" not in values["system_prompt"]
    assert "Never break character" not in values["system_prompt"]
    assert "mention being an AI" not in values["system_prompt"]
    # 1st person, in-character
    assert "I'm" in values["greeting_message"]
    # 3rd person teaser about her
    assert "Nora" in values["bio"]
    assert values["summary"].startswith("A ")
    # adjective lists, not prose
    assert "," in values["tone"] and "." not in values["tone"]
    assert "," in values["style"]


def test_deterministic_welcome_message_action_is_her_own():
    w = _writer()
    values, _ = asyncio.run(w.write(_persona(), ["welcome_message"], {}, name="Nora"))
    # asterisk action describes HER OWN action (first person), never the user's
    assert "*I " in values["welcome_message"]
    assert "*Nora" not in values["welcome_message"]
    assert "*You" not in values["welcome_message"]


def test_empty_fields_returns_empty():
    w = _writer()
    values, provider = asyncio.run(w.write(_persona(), [], {}, name="Nora"))
    assert values == {} and provider == "deterministic"


# --- user prompt construction ---
def test_user_prompt_includes_requested_fields_and_enrichment():
    w = _writer()
    prompt = w._build_user_prompt(
        _persona(), ["bio", "tone"], {"likes": ["dancing"], "dislikes": ["rudeness"]}, "Nora"
    )
    assert '"bio"' in prompt and '"tone"' in prompt
    assert "likes: dancing" in prompt
    assert "dislikes: rudeness" in prompt
    # raw trait labels, humanized (not the image-expression phrases)
    assert "sugar baby" in prompt
    assert "oral play" in prompt


# --- Venice JSON path ---
def test_venice_all_fields_present_is_provider_venice():
    w = _writer(api_key="k")
    w._client.chat = _fake_chat('{"system_prompt":"Nora is a 24-year-old Latina woman.","tone":"bold, teasing"}')
    values, provider = asyncio.run(w.write(_persona(), ["system_prompt", "tone"], {}, name="Nora"))
    assert set(values) == {"system_prompt", "tone"}
    assert values["tone"] == "bold, teasing"
    assert provider == "venice"


def test_venice_partial_fills_missing_and_is_mixed():
    w = _writer(api_key="k")
    w._client.chat = _fake_chat('{"system_prompt":"Nora is a 24-year-old Latina woman."}')
    values, provider = asyncio.run(w.write(_persona(), ["system_prompt", "tone"], {}, name="Nora"))
    assert values["system_prompt"] == "Nora is a 24-year-old Latina woman."
    assert values["tone"] == "playful, flirty"  # deterministic fill
    assert provider == "mixed"


def test_venice_bad_json_falls_back_deterministic():
    w = _writer(api_key="k")
    w._client.chat = _fake_chat("sorry, I can't do that")
    values, provider = asyncio.run(w.write(_persona(), ["system_prompt"], {}, name="Nora"))
    assert provider == "deterministic"
    assert values["system_prompt"].startswith("Nora is a")


def test_venice_value_is_length_clamped():
    w = _writer(api_key="k")
    huge = "x" * 9000
    w._client.chat = _fake_chat('{"system_prompt":"%s"}' % huge)
    values, _ = asyncio.run(w.write(_persona(), ["system_prompt"], {}, name="Nora"))
    assert len(values["system_prompt"]) == _FIELD_SPECS["system_prompt"]["max_chars"]


def test_enabled_flag():
    assert _writer("").enabled is False
    assert _writer("k").enabled is True


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
