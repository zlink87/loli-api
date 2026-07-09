"""
Pydantic models for Character Nude Bases.

A nude base is ONE identity-locked nude/underwear render per character, generated
from the clothed hero via the existing outfit-edit machinery and stored in the
loli-api-owned character_nude_bases table (see migration 0003). Batches start each
scene's edit chain from it (when present) so dressing is ADDITIVE — see
services/nude_base_store.py and api/v1/endpoints/nude_base.py.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class NudeBaseRead(BaseModel):
    """One character_nude_bases row (store read model)."""

    id: str
    character_id: str
    source_image_url: Optional[str] = None
    image_url: Optional[str] = None
    image_hash: Optional[str] = None
    job_id: Optional[str] = None
    status: str = "pending"
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class NudeBaseStatusResponse(BaseModel):
    """
    API response for the nude-base endpoints (POST create + GET status).

    ``status`` walks pending -> succeeded | failed. ``jobId`` is the outfit_edit
    job to poll (also surfaced so the admin can watch it via GET /v1/jobs/{id}
    exactly like any other edit). ``imageUrl`` is populated once succeeded.
    """

    characterId: str = Field(..., description="The character this nude base belongs to")
    status: str = Field(..., description="pending | succeeded | failed")
    jobId: Optional[str] = Field(
        default=None, description="The outfit_edit job generating the base (poll it or GET this endpoint)"
    )
    imageUrl: Optional[str] = Field(
        default=None, description="The generated nude-base URL — set once status is 'succeeded'"
    )
    error: Optional[str] = Field(default=None, description="Failure detail when status is 'failed'")
    createdAt: Optional[datetime] = Field(default=None)
    updatedAt: Optional[datetime] = Field(default=None)
