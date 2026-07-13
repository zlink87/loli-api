"""
Tests for the scene randomizer (Batch Character Creation).

Covers: deterministic identity-free fallback when Venice is disabled (never raises);
occupation theming; the Venice path scrubbing identity tokens out of the LLM scene; and
falling back on empty/unparseable/scrubbed-to-empty responses. Venice is stubbed on the
writer's client, mirroring how test_video_motion.py exercises the MotionWriter.

Runs under pytest or directly: python loli_api/tests/test_scene_writer.py
"""
import asyncio

from models.requests import PersonaOptions, SceneRandomizeRequest
from services.scene_writer import (
    SceneWriter, SCENE_SYSTEM_PROMPT, _FALLBACK_SCENES, _OCCUPATION_SCENES,
)
from services.prompt_constants import has_banned_style_words
from api.v1.endpoints import scenes as ep


_IDENTITY_WORDS = ("hair", "eyes", "eye ", "asian", "blonde", "brunette", "breast",
                   "woman", "girl", "redhead", "skin")


def _persona(**overrides):
    fields = dict(
        ethnicity="asian", age=26, hairStyle="ponytail", hairColor="blonde",
        eyeColor="brown", name="Sakura",
    )
    fields.update(overrides)
    return PersonaOptions(**fields)


def _assert_identity_free(scene: str):
    low = scene.lower()
    for w in _IDENTITY_WORDS:
        assert w not in low, f"identity token {w!r} leaked into scene: {scene!r}"


# ---------------------------------------------------------------------------
# Deterministic fallback (Venice disabled) — never raises, always identity-free.
# ---------------------------------------------------------------------------
def test_disabled_returns_deterministic_identity_free():
    w = SceneWriter(api_key="")
    assert w.enabled is False
    scene, provider = asyncio.run(w.randomize(persona=_persona(occupation="nurse"), hint="cosy"))
    assert provider == "deterministic"
    assert scene
    _assert_identity_free(scene)


def test_occupation_themes_the_fallback():
    w = SceneWriter(api_key="")
    scene, provider = asyncio.run(w.randomize(persona=_persona(occupation="nurse")))
    assert provider == "deterministic"
    assert scene == _OCCUPATION_SCENES["nurse"]


def test_fallback_varies_by_input():
    # Different hints (no themed occupation) should be able to select different scenes.
    w = SceneWriter(api_key="")
    seen = set()
    for hint in ("morning coffee", "late night city", "beach day", "rainy window", "park walk"):
        scene, _ = asyncio.run(w.randomize(persona=_persona(), hint=hint))
        seen.add(scene)
        assert scene in _FALLBACK_SCENES
    assert len(seen) > 1  # not always the same fallback


def test_no_persona_no_hint_never_raises():
    w = SceneWriter(api_key="")
    scene, provider = asyncio.run(w.randomize())
    assert provider == "deterministic"
    assert scene in _FALLBACK_SCENES


# ---------------------------------------------------------------------------
# Venice path (stubbed client) — scene is scrubbed of identity; misses fall back.
# ---------------------------------------------------------------------------
def _writer_returning(content):
    w = SceneWriter(api_key="k")  # enabled
    assert w.enabled is True

    async def fake_chat(messages, **kwargs):
        return content, {}

    w._client.chat = fake_chat
    return w


def test_venice_scene_is_scrubbed_of_identity():
    w = _writer_returning(
        '{"scene": "a stunning blonde woman relaxing on a sunlit balcony at dusk"}'
    )
    scene, provider = asyncio.run(w.randomize(persona=_persona()))
    assert provider == "venice"
    _assert_identity_free(scene)
    assert "balcony" in scene.lower()  # the scene content itself is preserved


def test_venice_empty_content_falls_back():
    w = _writer_returning(None)
    scene, provider = asyncio.run(w.randomize(persona=_persona(occupation="nurse")))
    assert provider == "deterministic"
    assert scene == _OCCUPATION_SCENES["nurse"]


def test_venice_unparseable_falls_back():
    w = _writer_returning("this is not json at all")
    scene, provider = asyncio.run(w.randomize(persona=_persona(occupation="cook")))
    assert provider == "deterministic"
    assert scene == _OCCUPATION_SCENES["cook"]


def test_venice_scene_scrubbed_to_empty_falls_back():
    # An all-identity scene is scrubbed to nothing -> deterministic fallback instead.
    w = _writer_returning('{"scene": "brunette hair, green eyes"}')
    scene, provider = asyncio.run(w.randomize(persona=_persona(occupation="nurse")))
    assert provider == "deterministic"
    assert scene == _OCCUPATION_SCENES["nurse"]


def test_venice_scene_extracted_from_wrapping_text():
    # Tolerant extraction: JSON embedded in prose still parses.
    w = _writer_returning('Sure! {"scene": "reading in a quiet cafe on a slow afternoon"} enjoy')
    scene, provider = asyncio.run(w.randomize())
    assert provider == "venice"
    assert "cafe" in scene.lower()


# ---------------------------------------------------------------------------
# WS2: the scene sentence must be literal (camera-sees), not flowery mood-prose.
# ---------------------------------------------------------------------------
def test_scene_system_prompt_demands_literal_no_metaphor():
    low = SCENE_SYSTEM_PROMPT.lower()
    assert "camera instruction" in low          # framed as a render instruction, not a story
    assert "metaphor" in low                     # metaphors/similes explicitly banned
    assert "identity-free" in low                # identity firewall preserved
    assert '{"scene": "..."}' in SCENE_SYSTEM_PROMPT  # JSON contract the parser depends on


def test_fallback_scenes_are_literal_no_moodprose_or_style_words():
    # The fallback scene lands VERBATIM in the image prompt, so it must be concrete and must
    # carry no BANNED_STYLE_WORDS (scene_mapper._clean_scene_part drops those wholesale) and
    # no leftover mood-prose adjectives.
    mood_words = ("cozy", "lazy", "serene", "unwinding", "moody", "snug",
                  "tension easing", " calm")
    for scene in list(_FALLBACK_SCENES) + list(_OCCUPATION_SCENES.values()):
        low = scene.lower()
        assert not has_banned_style_words(scene), f"banned style word in fallback: {scene!r}"
        for w in mood_words:
            assert w not in low, f"mood-prose {w!r} survived in fallback: {scene!r}"
        _assert_identity_free(scene)             # still strictly identity-free


# ---------------------------------------------------------------------------
# Endpoint glue — stateless, returns the (scene, provider) verbatim.
# ---------------------------------------------------------------------------
def test_endpoint_returns_scene_and_provider():
    ep.set_scene_writer(SceneWriter(api_key=""))  # deterministic
    body = SceneRandomizeRequest(persona=_persona(occupation="nurse"), hint=None)
    resp = asyncio.run(ep.randomize_scene(body, user={"sub": "admin"}))
    assert resp.provider == "deterministic"
    assert resp.scene == _OCCUPATION_SCENES["nurse"]
    _assert_identity_free(resp.scene)


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
