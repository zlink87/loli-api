"""
Tests for GET /v1/options (admin-only, stateless enum/constraint enumeration).

No test in this suite uses FastAPI's TestClient/dependency_overrides (see
test_require_admin.py, test_characters.py) — endpoints are called directly as
plain async functions with an already-resolved `user` dict, same as here.

Runs under pytest or directly: python loli_api/tests/test_options_endpoint.py
"""
import asyncio

from fastapi import HTTPException

from config import settings
from auth.admin import require_admin
from models.enums import EthnicityType, CultureType
from api.v1.endpoints import options as ep

# Only the sub-keys built via ep._opts() are {value,label} pairs; the others
# (aspect_ratios/resolutions/lengths) are raw value lists by design.
_ENUM_KEYS = {
    "persona": [
        "style", "ethnicity", "culture", "hair_style", "hair_color", "eye_color",
        "body_type", "breast_size", "personality", "relationship",
        "occupation", "kinks",
    ],
    "generation": ["nudity_level", "outfit", "pose", "accessory", "photo_style"],
    "scene": [
        "location", "time_of_day", "lighting", "shot_framing",
        "camera_angle", "expression",
    ],
    "video": ["motion"],
    "trait_profile": [
        "wardrobe_style", "demeanor", "zodiac", "interior_style", "color_palette",
    ],
}


def test_endpoint_uses_shared_require_admin_dependency():
    # Proves the router really gates this route through the same dependency
    # test_require_admin.py already covers 401/403 for (no TestClient in this repo).
    assert ep.require_admin is require_admin


def test_non_admin_denied():
    settings.ADMIN_USER_IDS = ""
    raised = False
    try:
        asyncio.run(require_admin(user={"sub": "nobody"}))
    except HTTPException as e:
        raised = e.status_code == 403
    assert raised


def test_admin_can_reach_options():
    settings.ADMIN_USER_IDS = "admin-1"
    user = asyncio.run(require_admin(user={"sub": "admin-1"}))
    body = asyncio.run(ep.get_options(user=user))
    assert set(body.keys()) == {"persona", "generation", "scene", "video", "trait_profile"}


def test_persona_occupation_contains_teacher():
    body = asyncio.run(ep.get_options(user={"sub": "admin-1"}))
    assert {"value": "teacher", "label": "Teacher"} in body["persona"]["occupation"]


def test_persona_constraints():
    body = asyncio.run(ep.get_options(user={"sub": "admin-1"}))
    constraints = body["persona"]["constraints"]
    assert constraints["age"] == {"min": 18, "max": 50}
    assert constraints["kinks_max"] == 3


def test_ethnicity_enum_length_matches():
    body = asyncio.run(ep.get_options(user={"sub": "admin-1"}))
    assert len(body["persona"]["ethnicity"]) == len(EthnicityType)


def test_ethnicity_options_are_exhaustive_and_unique():
    # The regionally-ordered list must contain EVERY enum member exactly once.
    body = asyncio.run(ep.get_options(user={"sub": "admin-1"}))
    values = [e["value"] for e in body["persona"]["ethnicity"]]
    assert len(values) == len(set(values)), "duplicate ethnicity option"
    assert set(values) == {e.value for e in EthnicityType}


def test_culture_options_are_exhaustive_and_unique():
    # The culture dropdown must contain EVERY CultureType member exactly once.
    body = asyncio.run(ep.get_options(user={"sub": "admin-1"}))
    values = [e["value"] for e in body["persona"]["culture"]]
    assert len(values) == len(set(values)), "duplicate culture option"
    assert set(values) == {c.value for c in CultureType}
    # a couple of representative labels are humanized
    assert {"value": "goth", "label": "Goth"} in body["persona"]["culture"]
    assert {"value": "e_girl", "label": "E Girl"} in body["persona"]["culture"]


def test_ethnicity_options_include_new_values_with_labels():
    body = asyncio.run(ep.get_options(user={"sub": "admin-1"}))
    eth = body["persona"]["ethnicity"]
    assert {"value": "slavic", "label": "Slavic"} in eth
    assert {"value": "west_african", "label": "West African"} in eth
    assert {"value": "mixed_heritage", "label": "Mixed Heritage"} in eth


def test_ethnicity_options_ordered_regionally_with_legacy_inside_regions():
    # European group leads (legacy caucasian sits at the END of European), then
    # Asian (legacy asian last in group), then MENA/African/Americas/Mixed.
    body = asyncio.run(ep.get_options(user={"sub": "admin-1"}))
    values = [e["value"] for e in body["persona"]["ethnicity"]]
    pos = {v: i for i, v in enumerate(values)}
    # legacy values are placed inside their region, not all up-front
    assert pos["nordic"] < pos["caucasian"] < pos["japanese"]
    assert pos["chinese"] < pos["asian"] < pos["persian"]
    assert pos["north_african"] < pos["arab"] < pos["west_african"]
    assert pos["afro_caribbean"] < pos["black_afro"] < pos["brazilian"]
    assert pos["brazilian"] < pos["latina"] < pos["mixed_heritage"]
    # mixed_heritage is the final option
    assert values[-1] == "mixed_heritage"


def test_every_option_entry_has_nonempty_value_and_label():
    body = asyncio.run(ep.get_options(user={"sub": "admin-1"}))
    for group, keys in _ENUM_KEYS.items():
        for key in keys:
            for entry in body[group][key]:
                assert entry["value"]
                assert entry["label"]


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
