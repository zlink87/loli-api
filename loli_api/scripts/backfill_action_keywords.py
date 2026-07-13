#!/usr/bin/env python3
"""
One-off backfill for chat_persona_actions.trigger_keywords.

Rows created before trigger_keywords existed (or via a manual admin save with no
attached scene) still carry an empty array. This walks chat_persona_actions
(optionally scoped to one character), resolves each row's photo's scene_spec —
hopping to the source still for a video reel whose own character_images row
carries no scene — derives keywords via
services.character_image_store.action_keywords, and writes them back.

Usage examples
--------------
    # Preview what would change, across every character:
    python scripts/backfill_action_keywords.py --dry-run

    # Backfill only rows that are still empty, for one character:
    python scripts/backfill_action_keywords.py --character-id <uuid>

    # Recompute keywords even for rows that already have some:
    python scripts/backfill_action_keywords.py --overwrite

Exit code is non-zero if any row fails to update.
"""
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Make the loli_api package importable when this script is run directly, so we
# can single-source action_keywords and the Supabase client construction.
_LOLI_API_DIR = Path(__file__).resolve().parent.parent
if str(_LOLI_API_DIR) not in sys.path:
    sys.path.insert(0, str(_LOLI_API_DIR))

from services.character_image_store import action_keywords  # noqa: E402
from services.supabase_db import get_supabase_db_client  # noqa: E402

_ACTIONS_TABLE = "chat_persona_actions"
_IMAGES_TABLE = "character_images"
# Page size for listing actions AND the .in_() chunk size for fetching images.
_PAGE_SIZE = 500


def plan_keyword_updates(
    actions: List[dict],
    images_by_id: Dict[str, dict],
    *,
    overwrite: bool = False,
) -> List[Tuple[str, List[str]]]:
    """
    Pure planner (no I/O): decide which chat_persona_actions rows get new
    trigger_keywords and what those keywords are.

    Skips a row that already carries keywords unless ``overwrite=True``. Resolves
    the row's scene from its character_images.metadata.scene_spec; for a video
    action whose own image has no scene_spec, hops to the source still
    (image.source_image_id -> images_by_id) and folds the video image's
    metadata.motion into the extra texts. Always includes the action's label.
    A row whose keywords come out empty is skipped (nothing worth writing).
    """
    updates: List[Tuple[str, List[str]]] = []
    for action in actions:
        existing = action.get("trigger_keywords")
        if existing and not overwrite:
            continue

        image = images_by_id.get(action.get("character_image_id"))
        metadata = (image or {}).get("metadata") or {}
        scene = metadata.get("scene_spec")

        extra_texts: List[Optional[str]] = []
        if action.get("media_type") == "video" and not scene:
            source_id = (image or {}).get("source_image_id")
            source_image = images_by_id.get(source_id) if source_id else None
            if source_image is not None:
                scene = (source_image.get("metadata") or {}).get("scene_spec")
            extra_texts.append(metadata.get("motion"))

        extra_texts.append(action.get("label"))

        kws = action_keywords(scene, extra_texts=extra_texts)
        if not kws:
            continue
        updates.append((action["id"], kws))

    return updates


def _fetch_actions(client, *, character_id: Optional[str] = None) -> List[dict]:
    """Page through chat_persona_actions (500/page), optionally scoped to one character."""
    rows: List[dict] = []
    offset = 0
    while True:
        query = client.table(_ACTIONS_TABLE).select(
            "id, character_id, character_image_id, label, media_type, trigger_keywords"
        )
        if character_id:
            query = query.eq("character_id", character_id)
        res = query.range(offset, offset + _PAGE_SIZE - 1).execute()
        page = res.data or []
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return rows


def _fetch_images(client, image_ids) -> Dict[str, dict]:
    """Fetch character_images rows referenced by ``image_ids``, chunked for .in_()."""
    ids = sorted({i for i in image_ids if i})
    images_by_id: Dict[str, dict] = {}
    for start in range(0, len(ids), _PAGE_SIZE):
        chunk = ids[start:start + _PAGE_SIZE]
        res = (
            client.table(_IMAGES_TABLE)
            .select("id, metadata, source_image_id")
            .in_("id", chunk)
            .execute()
        )
        for row in res.data or []:
            images_by_id[row["id"]] = row
    return images_by_id


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill chat_persona_actions.trigger_keywords from each photo's scene metadata."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned updates without writing anything.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Recompute keywords even for rows that already have some (default: fill empty rows only).",
    )
    parser.add_argument(
        "--character-id",
        default=None,
        help="Limit to one character's quick actions. Default: every character.",
    )
    args = parser.parse_args()

    try:
        client = get_supabase_db_client()
    except RuntimeError as e:
        raise SystemExit(str(e))

    actions = _fetch_actions(client, character_id=args.character_id)
    scope = f" for character {args.character_id}" if args.character_id else ""
    print(f"Fetched {len(actions)} chat_persona_actions row(s){scope}.")

    image_ids = {a.get("character_image_id") for a in actions}
    images_by_id = _fetch_images(client, image_ids)

    # Second pass: pull in any video source stills not already covered, so the
    # planner's source-hop can resolve their scene_spec.
    missing_source_ids = {
        img.get("source_image_id")
        for img in images_by_id.values()
        if img.get("source_image_id") and img.get("source_image_id") not in images_by_id
    }
    if missing_source_ids:
        images_by_id.update(_fetch_images(client, missing_source_ids))

    updates = plan_keyword_updates(actions, images_by_id, overwrite=args.overwrite)
    skipped = len(actions) - len(updates)

    if args.dry_run:
        for action_id, kws in updates:
            print(f"  [dry-run] {action_id}  keywords={kws}")
        print(f"\nPlanned: {len(updates)}  Skipped: {skipped}  (dry-run, nothing written)")
        return 0

    updated = 0
    failed = 0
    for action_id, kws in updates:
        try:
            (
                client.table(_ACTIONS_TABLE)
                .update({"trigger_keywords": kws})
                .eq("id", action_id)
                .execute()
            )
            updated += 1
        except Exception as e:  # noqa: BLE001 - one bad row must not sink the rest
            failed += 1
            print(f"  [FAIL] {action_id}: {e}")

    print(f"\nPlanned: {len(updates)}  Updated: {updated}  Skipped: {skipped}  Failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
