"""
Tests for action_keywords (services.character_image_store) and
plan_keyword_updates (scripts.backfill_action_keywords).

action_keywords derives chat_persona_actions.trigger_keywords from a photo's RAW
scene_spec jsonb dict + extra free text; plan_keyword_updates is the pure planner
the one-off backfill script uses to decide which rows to update.

Runs under pytest or directly: python loli_api/tests/test_action_keywords.py
"""
from services.character_image_store import action_keywords
from scripts.backfill_action_keywords import plan_keyword_updates


# ---------------------------------------------------------------------------
# action_keywords
# ---------------------------------------------------------------------------

def _full_scene():
    return {
        "location": "home_kitchen",
        "outfit": "silk_pajamas",
        "outfit_detail": "cream silk trim, loosely tied",
        "time_of_day": "early_morning",
        "activity": "brewing coffee",
        "setting": "sunlight through the window",
        # must never be read
        "nudityLevel": "medium",
        "narrative": "She woke up early and put on the kettle before anyone else was awake.",
    }


def test_full_scene_dict_produces_ordered_deduped_tokens():
    kws = action_keywords(_full_scene())
    assert kws == [
        "home", "kitchen", "silk", "pajamas", "cream", "trim", "loosely",
        "tied", "early", "morning", "brewing", "coffee", "sunlight",
        "through", "window",
    ]
    assert kws.count("silk") == 1  # deduped (also appears in outfit_detail)
    assert "the" not in kws  # stopword, despite being exactly 3 chars
    assert all(len(k) >= 3 for k in kws)


def test_nudity_level_and_narrative_keys_are_never_read():
    kws = action_keywords(_full_scene())
    assert "medium" not in kws  # nudityLevel value
    assert "kettle" not in kws  # narrative text
    assert "awake" not in kws


def test_none_and_empty_scene_yield_no_keywords():
    assert action_keywords(None) == []
    assert action_keywords({}) == []
    assert action_keywords() == []


def test_malformed_scene_dict_never_raises():
    kws = action_keywords({"random_key": "value", "another": 42, "location": 7})
    assert kws == []


def test_non_str_scene_values_ignored():
    scene = {
        "location": 123,
        "outfit": None,
        "outfit_detail": ["not", "a", "string"],
        "time_of_day": "early_morning",
        "activity": {"nested": "dict"},
        "setting": 4.5,
    }
    assert action_keywords(scene) == ["early", "morning"]


def test_extra_texts_only_path():
    kws = action_keywords(None, extra_texts=["Sipping coffee by the window", None, ""])
    assert kws == ["sipping", "coffee", "window"]  # "by"/"the" are stopwords


def test_tokenizes_underscores_and_punctuation():
    kws = action_keywords(None, extra_texts=["silk-pajamas_robe!!loosely,fit"])
    assert kws == ["silk", "pajamas", "robe", "loosely", "fit"]


def test_min_token_length_boundary():
    # "ok"/"ab" (2 chars) dropped; "fit"/"abc" (3 chars) kept.
    kws = action_keywords(None, extra_texts=["ok fit ab abc"])
    assert kws == ["fit", "abc"]


def test_cap_at_max_keywords():
    words = [f"tokenword{i:02d}" for i in range(20)]
    kws = action_keywords(None, extra_texts=[" ".join(words)])
    assert len(kws) == 16
    assert kws == words[:16]


# ---------------------------------------------------------------------------
# plan_keyword_updates
# ---------------------------------------------------------------------------

def _images_fixture():
    return {
        "img-photo": {
            "id": "img-photo",
            "metadata": {"scene_spec": {"location": "home_kitchen", "outfit": "silk_pajamas"}},
            "source_image_id": None,
        },
        "img-video": {
            "id": "img-video",
            # no scene_spec of its own -- must hop to the source still
            "metadata": {"motion": "hair_in_wind"},
            "source_image_id": "img-photo",
        },
    }


def test_plan_fills_only_empty_rows():
    actions = [
        {"id": "a1", "character_id": "c1", "character_image_id": "img-photo",
         "label": "Morning coffee", "media_type": "image", "trigger_keywords": []},
        {"id": "a2", "character_id": "c1", "character_image_id": "img-photo",
         "label": "Already tagged", "media_type": "image", "trigger_keywords": ["existing"]},
    ]
    updates = plan_keyword_updates(actions, _images_fixture())
    ids = [action_id for action_id, _ in updates]
    assert ids == ["a1"]


def test_plan_overwrite_recomputes_tagged_rows():
    actions = [
        {"id": "a2", "character_id": "c1", "character_image_id": "img-photo",
         "label": "Already tagged", "media_type": "image", "trigger_keywords": ["existing"]},
    ]
    updates = plan_keyword_updates(actions, _images_fixture(), overwrite=True)
    assert len(updates) == 1
    action_id, kws = updates[0]
    assert action_id == "a2"
    assert "existing" not in kws  # recomputed, not merged with the stale list
    assert "kitchen" in kws


def test_plan_video_source_hop_includes_motion():
    actions = [
        {"id": "a3", "character_id": "c1", "character_image_id": "img-video",
         "label": "Hair in the wind", "media_type": "video", "trigger_keywords": None},
    ]
    updates = plan_keyword_updates(actions, _images_fixture())
    assert len(updates) == 1
    action_id, kws = updates[0]
    assert action_id == "a3"
    assert "kitchen" in kws and "silk" in kws  # hopped to the source still's scene_spec
    assert "hair" in kws and "wind" in kws  # motion "hair_in_wind" tokenized


def test_plan_missing_image_row_degrades_to_label_only():
    actions = [
        {"id": "a4", "character_id": "c1", "character_image_id": "img-does-not-exist",
         "label": "Cozy afternoon nap", "media_type": "image", "trigger_keywords": []},
    ]
    updates = plan_keyword_updates(actions, _images_fixture())
    assert updates == [("a4", ["cozy", "afternoon", "nap"])]


def test_plan_skips_rows_with_no_derivable_keywords():
    actions = [
        {"id": "a5", "character_id": "c1", "character_image_id": "img-blank",
         "label": "", "media_type": "image", "trigger_keywords": []},
    ]
    images = {"img-blank": {"id": "img-blank", "metadata": {}, "source_image_id": None}}
    assert plan_keyword_updates(actions, images) == []


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
