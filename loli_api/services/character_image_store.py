"""
CharacterImageStore — writes generated batch photos into the REAL product
tables the chat app reads:

  * character_images       — the photo gallery attached to a character
  * chat_persona_actions   — quick actions that surface one photo in chat

One succeeded batch item produces one character_images row plus one
chat_persona_actions row pointing at it, so a completed batch leaves the
character fully chat-ready (once the admin publishes it).
"""
import asyncio
import logging
import re
from typing import Iterable, List, Optional

from supabase import Client

logger = logging.getLogger(__name__)

_IMAGES = "character_images"
_ACTIONS = "chat_persona_actions"

# image_type the chat app expects for batch-generated gallery photos.
GENERATED_IMAGE_TYPE = "gallery"
# provider recorded on generated rows.
GENERATED_PROVIDER = "runpod-comfyui"

# chat_persona_actions.label is a short button caption.
_MAX_LABEL_LEN = 40


def action_label(
    beat_description: Optional[str],
    arc_title: Optional[str],
    scene_index: int,
) -> str:
    """Short quick-action caption: beat description, else arc title, else Photo N."""
    text = (beat_description or "").strip() or (arc_title or "").strip()
    if not text:
        return f"Photo {scene_index + 1}"
    if len(text) > _MAX_LABEL_LEN:
        text = text[: _MAX_LABEL_LEN - 1].rstrip() + "…"
    return text


# chat_persona_actions.trigger_keywords: tokens a chat runtime matches against
# conversation context to pick a relevant photo. Small, deliberately conservative
# stopword list — the <3-char length filter already catches most junk articles/
# prepositions, so this only needs the ones long enough to survive that.
_KEYWORD_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "with",
    "her", "his", "by", "for", "from",
    "she", "he", "it", "its", "is", "are", "was", "were", "be", "been",
    "being", "this", "that", "these", "those", "as", "but",
}
_MAX_KEYWORDS = 16
_MIN_KEYWORD_LEN = 3
_KEYWORD_SPLIT_RE = re.compile(r"[^a-zA-Z0-9]+")

# Raw scene_spec jsonb keys read for keywords, in order. Deliberately excludes
# nudityLevel and narrative — neither is a useful chat-matching signal.
_SCENE_KEYWORD_FIELDS = ("location", "outfit", "outfit_detail", "time_of_day", "activity", "setting")


def action_keywords(
    scene_spec: Optional[dict] = None,
    *,
    extra_texts: Iterable[Optional[str]] = (),
) -> List[str]:
    """
    Chat-matching keywords for a quick action: tokenized from the photo's RAW
    scene_spec jsonb dict (location/outfit/outfit_detail/time_of_day/activity/
    setting), plus any extra_texts (e.g. a beat description, motion, or label).

    Never parses scene_spec with SceneSpec — a malformed/legacy dict, or None,
    just yields fewer tokens instead of raising. Tokens are lowercased, split on
    underscores/punctuation, deduped (first-seen order), and capped at
    _MAX_KEYWORDS.
    """
    texts: List[str] = []
    if isinstance(scene_spec, dict):
        for key in _SCENE_KEYWORD_FIELDS:
            value = scene_spec.get(key)
            if isinstance(value, str):
                texts.append(value)
    for text in extra_texts:
        if text:
            texts.append(text)

    keywords: List[str] = []
    seen = set()
    for text in texts:
        for token in _KEYWORD_SPLIT_RE.split(text):
            token = token.lower()
            if len(token) < _MIN_KEYWORD_LEN or token in _KEYWORD_STOPWORDS:
                continue
            if token in seen:
                continue
            seen.add(token)
            keywords.append(token)
            if len(keywords) >= _MAX_KEYWORDS:
                return keywords
    return keywords


class CharacterImageStore:
    def __init__(self, client: Client):
        self.client = client

    async def create_image(
        self,
        character_id: str,
        *,
        image_url: str,
        original_image_url: Optional[str] = None,
        prompt: Optional[str] = None,
        seed: Optional[int] = None,
        outfit: Optional[str] = None,
        accessories: Optional[List[str]] = None,
        metadata: Optional[dict] = None,
        provider: str = GENERATED_PROVIDER,
        image_type: str = GENERATED_IMAGE_TYPE,
        source_image_id: Optional[str] = None,
    ) -> str:
        """Insert one gallery row; returns the new character_images.id.

        For video (reel) rows pass ``image_type="video"`` and ``source_image_id``
        (the still it was generated from — the existing self-FK column).
        """
        record = {
            "character_id": character_id,
            "image_type": image_type,
            "image_url": image_url,
            "original_image_url": original_image_url,
            "provider": provider,
            "prompt": prompt,
            "seed": seed,
            "outfit": outfit,
            "accessories": accessories or [],
            "is_avatar": False,
            "metadata": metadata or {},
        }
        if source_image_id is not None:
            record["source_image_id"] = source_image_id

        def _insert():
            return self.client.table(_IMAGES).insert(record).execute()

        res = await asyncio.to_thread(_insert)
        return res.data[0]["id"]

    async def create_action(
        self,
        character_id: str,
        *,
        character_image_id: str,
        media_url: str,
        label: str,
        suggested_prompt: Optional[str] = None,
        sort_order: int = 0,
        media_type: str = "image",
        is_active: bool = True,
        trigger_keywords: Optional[List[str]] = None,
    ) -> str:
        """Insert one quick action pointing at a gallery image; returns its id.

        For video reels pass ``media_type="video"`` and ``is_active=False`` so the
        clip lands as a draft the admin publishes later (flip via set_action_active).
        ``trigger_keywords`` (see ``action_keywords``) defaults to an empty list.
        """
        record = {
            "character_id": character_id,
            "character_image_id": character_image_id,
            "media_url": media_url,
            "media_type": media_type,
            "label": label,
            "suggested_prompt": suggested_prompt,
            "trigger_type": "manual",
            "sort_order": sort_order,
            "is_active": is_active,
            "trigger_keywords": trigger_keywords or [],
        }

        def _insert():
            return self.client.table(_ACTIONS).insert(record).execute()

        res = await asyncio.to_thread(_insert)
        return res.data[0]["id"]

    async def get_image(self, image_id: str) -> Optional[dict]:
        """Fetch one character_images row by id (used to resolve a chosen still)."""
        def _select():
            return (
                self.client.table(_IMAGES)
                .select("*")
                .eq("id", image_id)
                .limit(1)
                .execute()
            )

        res = await asyncio.to_thread(_select)
        return res.data[0] if res.data else None

    async def list_character_videos(self, character_id: str) -> List[dict]:
        """
        Return the character's reels for the admin review UI, newest first.

        Merges the video rows (character_images where image_type='video') with
        their chat_persona_actions (for actionId + is_active) in Python — one row
        per reel with the fields the admin panel expects.
        """
        def _select_images():
            return (
                self.client.table(_IMAGES)
                .select("*")
                .eq("character_id", character_id)
                .eq("image_type", "video")
                .order("created_at", desc=True)
                .execute()
            )

        def _select_actions():
            return (
                self.client.table(_ACTIONS)
                .select("*")
                .eq("character_id", character_id)
                .eq("media_type", "video")
                .execute()
            )

        images_res, actions_res = await asyncio.gather(
            asyncio.to_thread(_select_images),
            asyncio.to_thread(_select_actions),
        )
        actions_by_image = {
            a.get("character_image_id"): a for a in (actions_res.data or [])
        }

        items: List[dict] = []
        for img in images_res.data or []:
            action = actions_by_image.get(img["id"]) or {}
            meta = img.get("metadata") or {}
            items.append(
                {
                    "characterImageId": img["id"],
                    "actionId": action.get("id"),
                    "videoUrl": img.get("image_url"),
                    "sourceImageId": img.get("source_image_id"),
                    "motion": meta.get("motion"),
                    "seed": img.get("seed"),
                    "isPublished": bool(action.get("is_active")),
                    "createdAt": img.get("created_at"),
                }
            )
        return items

    async def list_character_images(self, character_id: str) -> List[dict]:
        """All gallery/avatar/video rows for a character, newest first."""
        def _select():
            return (
                self.client.table(_IMAGES)
                .select("*")
                .eq("character_id", character_id)
                .order("created_at", desc=True)
                .execute()
            )

        res = await asyncio.to_thread(_select)
        return res.data or []

    async def delete_image(self, character_id: str, image_id: str) -> Optional[dict]:
        """
        Delete one photo from a character's gallery (admin "delete photo").

        Order matters for FK safety:
          1. delete the chat_persona_actions rows pointing at the image;
          2. detach any derived rows (videos generated FROM this still) by
             nulling their source_image_id;
          3. delete the character_images row itself (scoped by character_id).

        Returns the deleted row (so callers can e.g. clean up storage), or None
        if the image doesn't exist for this character. The storage object is
        deliberately left in place — public URLs may be cached by the chat app.
        """
        row = await self.get_image(image_id)
        if not row or row.get("character_id") != character_id:
            return None

        def _delete_actions():
            return (
                self.client.table(_ACTIONS)
                .delete()
                .eq("character_image_id", image_id)
                .execute()
            )

        def _detach_derived():
            return (
                self.client.table(_IMAGES)
                .update({"source_image_id": None})
                .eq("source_image_id", image_id)
                .execute()
            )

        def _delete_image():
            return (
                self.client.table(_IMAGES)
                .delete()
                .eq("id", image_id)
                .eq("character_id", character_id)
                .execute()
            )

        await asyncio.to_thread(_delete_actions)
        await asyncio.to_thread(_detach_derived)
        res = await asyncio.to_thread(_delete_image)
        return res.data[0] if res.data else row

    async def set_avatar(self, character_id: str, image_id: str) -> Optional[str]:
        """
        Make an existing gallery photo the character's avatar (admin "switch
        avatar"). Updates the three avatar URL columns on `characters` (what the
        chat app reads) and maintains the is_avatar flag on character_images.

        Returns the new avatar URL, or None if the image doesn't exist / belongs
        to another character / has no URL.
        """
        row = await self.get_image(image_id)
        if not row or row.get("character_id") != character_id:
            return None
        url = row.get("image_url")
        if not url:
            return None

        def _clear_flags():
            return (
                self.client.table(_IMAGES)
                .update({"is_avatar": False})
                .eq("character_id", character_id)
                .eq("is_avatar", True)
                .execute()
            )

        def _set_flag():
            return (
                self.client.table(_IMAGES)
                .update({"is_avatar": True})
                .eq("id", image_id)
                .execute()
            )

        def _update_character():
            return (
                self.client.table("characters")
                .update({
                    "profile_image_url": url,
                    "avatar_image_url": url,
                    "chat_avatar_url": url,
                })
                .eq("id", character_id)
                .execute()
            )

        await asyncio.to_thread(_clear_flags)
        await asyncio.to_thread(_set_flag)
        res = await asyncio.to_thread(_update_character)
        if not res.data:
            return None
        return url

    async def set_action_active(
        self, action_id: str, character_id: str, is_active: bool = True
    ) -> Optional[dict]:
        """
        Publish/unpublish a reel by flipping chat_persona_actions.is_active.

        Scoped by character_id so an admin can only publish that character's own
        actions. Returns the updated row, or None if not found for this character.
        """
        def _update():
            return (
                self.client.table(_ACTIONS)
                .update({"is_active": is_active})
                .eq("id", action_id)
                .eq("character_id", character_id)
                .execute()
            )

        res = await asyncio.to_thread(_update)
        return res.data[0] if res.data else None
