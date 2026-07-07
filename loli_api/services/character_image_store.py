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
from typing import List, Optional

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
    ) -> str:
        """Insert one gallery row; returns the new character_images.id."""
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
    ) -> str:
        """Insert one quick action pointing at a gallery image; returns its id."""
        record = {
            "character_id": character_id,
            "character_image_id": character_image_id,
            "media_url": media_url,
            "media_type": "image",
            "label": label,
            "suggested_prompt": suggested_prompt,
            "trigger_type": "manual",
            "sort_order": sort_order,
            "is_active": True,
        }

        def _insert():
            return self.client.table(_ACTIONS).insert(record).execute()

        res = await asyncio.to_thread(_insert)
        return res.data[0]["id"]
