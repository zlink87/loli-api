"""
Pydantic models for AI chat-persona / bio generation (Feature 1).

An admin picks the structured character options (appearance + trait enums) and asks
Venice to write the free-text "chat persona" gaps in a Candy.ai voice. The generated
fields map to the product `chat_personas` table plus two `characters` columns:

    system_prompt / greeting_message / tone / style / boundaries / summary / name
        -> chat_personas.<same>
    welcome_message -> characters.welcome_message
    bio             -> characters.context

model_id is request-supplied (NOT generated) and defaults to venice-uncensored.

Generation is PER-FIELD: the caller lists exactly which fields to (re)generate, and
only those are written — fields the caller did not request are never overwritten.
"""
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from .requests import PersonaOptions


class PersonaField(str, Enum):
    """The free-text fields Venice can generate (model_id is excluded — not generated)."""

    system_prompt = "system_prompt"
    greeting_message = "greeting_message"
    tone = "tone"
    style = "style"
    boundaries = "boundaries"
    summary = "summary"
    welcome_message = "welcome_message"
    bio = "bio"
    name = "name"


class PersonaEnrichment(BaseModel):
    """Transient inputs that enrich generation only — NOT stored on the character.

    Mirrors how BatchCreate.likes/dislikes are generation-only. There are no columns
    for these; they only flavor the prompt.
    """

    likes: Optional[List[str]] = Field(default=None, max_length=12)
    dislikes: Optional[List[str]] = Field(default=None, max_length=12)
    interests: Optional[List[str]] = Field(default=None, max_length=12)
    hobbies: Optional[List[str]] = Field(default=None, max_length=12)
    language: Optional[str] = Field(
        default=None, max_length=60, description="Output language (default English)"
    )

    @field_validator("likes", "dislikes", "interests", "hobbies")
    @classmethod
    def _bounded_items(cls, v):
        if not v:
            return v
        cleaned = [str(s).strip()[:120] for s in v if str(s).strip()]
        return cleaned or None


class ChatPersonaRead(BaseModel):
    """A chat_personas row as returned to the admin app."""

    id: str
    name: Optional[str] = None
    system_prompt: Optional[str] = None
    greeting_message: Optional[str] = None
    tone: Optional[str] = None
    style: Optional[str] = None
    boundaries: Optional[str] = None
    summary: Optional[str] = None
    model_id: Optional[str] = None
    is_active: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _validate_fields(v: List[PersonaField]) -> List[PersonaField]:
    if not v:
        raise ValueError("`fields` must list at least one field to generate")
    # De-dupe while preserving order.
    seen: set = set()
    out: List[PersonaField] = []
    for f in v:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


class PersonaGenerateRequest(BaseModel):
    """Body for POST /v1/characters/{id}/persona — generate + persist, per-field."""

    fields: List[PersonaField] = Field(
        ..., description="Which fields to (re)generate and write. Others are untouched."
    )
    enrichment: PersonaEnrichment = Field(
        default_factory=PersonaEnrichment,
        description="Transient likes/dislikes/interests/hobbies/language (not stored)",
    )
    model_id: Optional[str] = Field(
        default=None,
        max_length=80,
        description="chat_personas.model_id to persist (defaults to config when omitted)",
    )
    name: Optional[str] = Field(
        default=None, max_length=60, description="Persona name override (else character name)"
    )
    dry_run: bool = Field(
        default=False, description="Generate + return only; do NOT write anything"
    )

    _v_fields = field_validator("fields")(_validate_fields)


class PersonaGenerateResponse(BaseModel):
    """Result of a generate (+persist) call."""

    character_id: str
    chat_persona_id: Optional[str] = None
    persona: Optional[ChatPersonaRead] = None
    welcome_message: Optional[str] = None
    bio: Optional[str] = None
    generated: Dict[str, str] = Field(
        default_factory=dict, description="Raw generated field values (also shown for dry_run)"
    )
    generated_fields: List[str] = Field(default_factory=list)
    provider: str = "deterministic"
    persisted: bool = False


class PersonaPreviewRequest(BaseModel):
    """Body for POST /v1/personas/preview — stateless suggestions, no character row."""

    persona: PersonaOptions = Field(..., description="The selected character options")
    fields: List[PersonaField] = Field(..., description="Which fields to generate")
    enrichment: PersonaEnrichment = Field(default_factory=PersonaEnrichment)
    model_id: Optional[str] = Field(default=None, max_length=80)
    name: Optional[str] = Field(default=None, max_length=60)

    _v_fields = field_validator("fields")(_validate_fields)


class PersonaPreviewResponse(BaseModel):
    generated: Dict[str, str] = Field(default_factory=dict)
    provider: str = "deterministic"
