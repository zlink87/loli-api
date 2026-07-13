"""
Pydantic models for Character Trait Profiles (WS-B).

A trait profile is the durable per-character "RPG character sheet": wardrobe
styles, favorite / never-worn outfits, favored / avoided locations, demeanor,
home interior style + palette, likes/dislikes, zodiac, plus display-only text
(backstory, home_description, quirks). It BIASES the existing enum/pool machinery
so every character lives a distinct visual life — profile data NEVER enters a
render prompt as free text (backstory/home_description are display + LLM-context
ONLY) and NEVER touches nudity controls (nudity belongs to the batch controls).

The whole profile is stored as one jsonb blob on `character_trait_profiles`
(migration 0004). Generation is PER-FIELD, mirroring the persona feature: the
caller lists which fields to (re)generate — defaulting to all — and only those
are written; untouched fields are preserved by the store's never-clobber merge.

`TraitProfile.coerce()` is the tolerant entry point: it repairs near-miss enum
values via difflib (reimplemented locally, NOT imported from story_planner),
drops unknowns, and never raises — so a garbage LLM value or a stale stored blob
always yields a valid profile. Direct `TraitProfile(...)` construction is for
known-good data (Pydantic's strict enum coercion).
"""
from __future__ import annotations

import difflib
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import (
    DemeanorType,
    InteriorStyleType,
    LocationType,
    OutfitType,
    PaletteType,
    WardrobeStyleType,
    ZodiacType,
)
from .persona import PersonaEnrichment
from .requests import PersonaOptions


# ---------------------------------------------------------------------------
# Field caps (single source of truth — reused by validators and tests).
# ---------------------------------------------------------------------------
MAX_WARDROBE_STYLES = 3
MAX_FAVORITE_OUTFITS = 5
MAX_NEVER_WEARS = 8
MAX_FAVORITE_LOCATIONS = 5
MAX_AVOIDED_LOCATIONS = 8
MAX_DEMEANOR = 2
MAX_LIKES = 12
MAX_DISLIKES = 12
MAX_QUIRKS = 6
MAX_BACKSTORY_CHARS = 800
MAX_HOME_DESCRIPTION_CHARS = 400
_MAX_ITEM_CHARS = 120  # per like/dislike/quirk string

# Public profile-card ("chat FE display") caps.
MAX_SHORT_DESCRIPTION_CHARS = 220
MAX_DISPLAY_OCCUPATION_CHARS = 40
MAX_DISPLAY_PERSONALITY = 4
MAX_DISPLAY_HOBBIES = 5
_MAX_DISPLAY_PERSONALITY_ITEM = 24
_MAX_DISPLAY_HOBBY_ITEM = 32
_DEFAULT_LANGUAGE = "English"


class TraitField(str, Enum):
    """The trait-profile fields the writer can (re)generate, per-field."""

    wardrobe_styles = "wardrobe_styles"
    favorite_outfits = "favorite_outfits"
    never_wears = "never_wears"
    favorite_locations = "favorite_locations"
    avoided_locations = "avoided_locations"
    demeanor = "demeanor"
    interior_style = "interior_style"
    color_palette = "color_palette"
    likes = "likes"
    dislikes = "dislikes"
    zodiac = "zodiac"
    backstory = "backstory"
    home_description = "home_description"
    quirks = "quirks"
    # Public profile-card (chat FE display) fields.
    short_description = "short_description"
    display_occupation = "display_occupation"
    display_personality = "display_personality"
    display_hobbies = "display_hobbies"
    language = "language"


ALL_TRAIT_FIELDS = tuple(f.value for f in TraitField)

# The subset of fields that flatten into the public character_profile_cards table
# (FE-readable). zodiac is mirrored from the profile alongside these.
CARD_FIELDS = (
    "short_description",
    "display_occupation",
    "display_personality",
    "display_hobbies",
    "language",
)


# ---------------------------------------------------------------------------
# Local tolerant coercion helpers (mirrors story_planner._coerce_enum's difflib
# repair; reimplemented here so models/ never imports from services/).
# ---------------------------------------------------------------------------
def _enum_value(v: Any) -> Any:
    return getattr(v, "value", v)


def _coerce_enum(enum_cls, value):
    """Coerce a raw value to an enum, repairing near-misses via difflib. None-safe."""
    if value is None:
        return None
    if isinstance(value, enum_cls):
        return value
    raw = _enum_value(value)
    if raw is None:
        return None
    raw = str(raw).strip().lower()
    if not raw:
        return None
    valid = {e.value: e for e in enum_cls}
    if raw in valid:
        return valid[raw]
    match = difflib.get_close_matches(raw, list(valid.keys()), n=1, cutoff=0.6)
    if match:
        return valid[match[0]]
    return None


def _coerce_enum_list(enum_cls, values) -> list:
    """Coerce each item to an enum, DROPPING unknowns (difflib-repaired first)."""
    if values is None:
        return []
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple, set)):
        values = [values]
    out = []
    for v in values:
        coerced = _coerce_enum(enum_cls, v)
        if coerced is not None:
            out.append(coerced)
    return out


def _coerce_str_list(values) -> List[str]:
    """Normalize a free-text list: stringify, strip, clamp per-item, drop empties."""
    if values is None:
        return []
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple, set)):
        values = [values]
    out: List[str] = []
    for v in values:
        s = str(v).strip()[:_MAX_ITEM_CHARS]
        if s:
            out.append(s)
    return out


def _coerce_text(value) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _dedupe(items: list) -> list:
    """Order-preserving de-dupe (works for enums or strings)."""
    seen: set = set()
    out: list = []
    for it in items or []:
        key = it.lower() if isinstance(it, str) else it
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


class TraitProfile(BaseModel):
    """The durable per-character trait sheet (bias vocab; never render free text)."""

    wardrobe_styles: List[WardrobeStyleType] = Field(default_factory=list)
    favorite_outfits: List[OutfitType] = Field(default_factory=list)
    never_wears: List[OutfitType] = Field(default_factory=list)
    favorite_locations: List[LocationType] = Field(default_factory=list)
    avoided_locations: List[LocationType] = Field(default_factory=list)
    demeanor: List[DemeanorType] = Field(default_factory=list)
    interior_style: Optional[InteriorStyleType] = None
    color_palette: Optional[PaletteType] = None
    likes: List[str] = Field(default_factory=list)
    dislikes: List[str] = Field(default_factory=list)
    zodiac: Optional[ZodiacType] = None
    backstory: Optional[str] = Field(
        default=None,
        max_length=MAX_BACKSTORY_CHARS,
        description="Short background narrative — DISPLAY + LLM-context ONLY, never rendered.",
    )
    home_description: Optional[str] = Field(
        default=None,
        max_length=MAX_HOME_DESCRIPTION_CHARS,
        description="Description of her home — DISPLAY + chat ONLY, never rendered.",
    )
    quirks: List[str] = Field(default_factory=list, description="Short quirks — display-only.")

    # --- public profile card (chat FE display; never rendered into image prompts) ---
    short_description: Optional[str] = Field(
        default=None,
        max_length=MAX_SHORT_DESCRIPTION_CHARS,
        description="2-3 sentence dating-profile HOOK — DISPLAY ONLY, never rendered.",
    )
    display_occupation: Optional[str] = Field(
        default=None,
        max_length=MAX_DISPLAY_OCCUPATION_CHARS,
        description="Humanized job title, e.g. 'Heiress and Socialite' — display-only.",
    )
    display_personality: List[str] = Field(
        default_factory=list, description="2-4 human personality adjectives — display-only."
    )
    display_hobbies: List[str] = Field(
        default_factory=list, description="2-5 short hobby/interest phrases — display-only."
    )
    language: str = Field(default=_DEFAULT_LANGUAGE, description="Primary language (display).")

    # --- per-field cleanup (dedupe + NAKED strip + cap) ---
    @field_validator("favorite_outfits", "never_wears")
    @classmethod
    def _strip_naked_and_dedupe(cls, v):
        # NAKED never belongs in wardrobe taste — nudity is a batch control, not a
        # garment preference. Strip it from BOTH favorites and never_wears.
        cleaned = [o for o in _dedupe(v) if o != OutfitType.NAKED]
        return cleaned

    @field_validator("wardrobe_styles", "favorite_locations", "avoided_locations", "demeanor")
    @classmethod
    def _dedupe_enum_lists(cls, v):
        return _dedupe(v)

    @field_validator("likes", "dislikes", "quirks")
    @classmethod
    def _clean_str_lists(cls, v):
        cleaned = [str(s).strip()[:_MAX_ITEM_CHARS] for s in (v or []) if str(s).strip()]
        return _dedupe(cleaned)

    @field_validator("display_personality")
    @classmethod
    def _clean_display_personality(cls, v):
        cleaned = [str(s).strip()[:_MAX_DISPLAY_PERSONALITY_ITEM] for s in (v or []) if str(s).strip()]
        return _dedupe(cleaned)

    @field_validator("display_hobbies")
    @classmethod
    def _clean_display_hobbies(cls, v):
        cleaned = [str(s).strip()[:_MAX_DISPLAY_HOBBY_ITEM] for s in (v or []) if str(s).strip()]
        return _dedupe(cleaned)

    @field_validator("language", mode="before")
    @classmethod
    def _default_language(cls, v):
        s = (str(v).strip() if v is not None else "")[:60]
        return s or _DEFAULT_LANGUAGE

    @model_validator(mode="after")
    def _apply_overlap_and_caps(self):
        # never_wears beats favorites: a garment she'll never wear can't be a favorite.
        if self.never_wears:
            blocked = set(self.never_wears)
            self.favorite_outfits = [o for o in self.favorite_outfits if o not in blocked]
        # Caps (applied last so overlap removal can't push a list back over its cap).
        self.wardrobe_styles = self.wardrobe_styles[:MAX_WARDROBE_STYLES]
        self.favorite_outfits = self.favorite_outfits[:MAX_FAVORITE_OUTFITS]
        self.never_wears = self.never_wears[:MAX_NEVER_WEARS]
        self.favorite_locations = self.favorite_locations[:MAX_FAVORITE_LOCATIONS]
        self.avoided_locations = self.avoided_locations[:MAX_AVOIDED_LOCATIONS]
        self.demeanor = self.demeanor[:MAX_DEMEANOR]
        self.likes = self.likes[:MAX_LIKES]
        self.dislikes = self.dislikes[:MAX_DISLIKES]
        self.quirks = self.quirks[:MAX_QUIRKS]
        self.display_personality = self.display_personality[:MAX_DISPLAY_PERSONALITY]
        self.display_hobbies = self.display_hobbies[:MAX_DISPLAY_HOBBIES]
        return self

    @classmethod
    def coerce(cls, raw: Any) -> "TraitProfile":
        """
        Build a TraitProfile from a raw/dirty mapping (LLM JSON or a stored jsonb
        blob), repairing near-miss enum values via difflib and DROPPING unknowns.
        Never raises — the tolerant entry point used everywhere reads happen.
        """
        if not isinstance(raw, dict):
            raw = {}
        data: Dict[str, Any] = {
            "wardrobe_styles": _coerce_enum_list(WardrobeStyleType, raw.get("wardrobe_styles")),
            "favorite_outfits": _coerce_enum_list(OutfitType, raw.get("favorite_outfits")),
            "never_wears": _coerce_enum_list(OutfitType, raw.get("never_wears")),
            "favorite_locations": _coerce_enum_list(LocationType, raw.get("favorite_locations")),
            "avoided_locations": _coerce_enum_list(LocationType, raw.get("avoided_locations")),
            "demeanor": _coerce_enum_list(DemeanorType, raw.get("demeanor")),
            "interior_style": _coerce_enum(InteriorStyleType, raw.get("interior_style")),
            "color_palette": _coerce_enum(PaletteType, raw.get("color_palette")),
            "zodiac": _coerce_enum(ZodiacType, raw.get("zodiac")),
            "likes": _coerce_str_list(raw.get("likes")),
            "dislikes": _coerce_str_list(raw.get("dislikes")),
            "quirks": _coerce_str_list(raw.get("quirks")),
            "backstory": (_coerce_text(raw.get("backstory")) or None),
            "home_description": (_coerce_text(raw.get("home_description")) or None),
            "short_description": _coerce_text(raw.get("short_description")),
            "display_occupation": _coerce_text(raw.get("display_occupation")),
            "display_personality": _coerce_str_list(raw.get("display_personality")),
            "display_hobbies": _coerce_str_list(raw.get("display_hobbies")),
            "language": _coerce_text(raw.get("language")) or _DEFAULT_LANGUAGE,
        }
        # Length-clamp the display text before construction (max_length would raise).
        if data["backstory"]:
            data["backstory"] = data["backstory"][:MAX_BACKSTORY_CHARS]
        if data["home_description"]:
            data["home_description"] = data["home_description"][:MAX_HOME_DESCRIPTION_CHARS]
        if data["short_description"]:
            data["short_description"] = data["short_description"][:MAX_SHORT_DESCRIPTION_CHARS]
        if data["display_occupation"]:
            data["display_occupation"] = data["display_occupation"][:MAX_DISPLAY_OCCUPATION_CHARS]
        return cls(**data)


# ---------------------------------------------------------------------------
# Request / response models (cloned from models/persona.py; reuse PersonaEnrichment).
# ---------------------------------------------------------------------------
def _dedupe_fields(v: Optional[List[TraitField]]) -> Optional[List[TraitField]]:
    """De-dupe requested fields (order-preserving). None means 'all fields'."""
    if v is None:
        return None
    seen: set = set()
    out: List[TraitField] = []
    for f in v:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


class TraitProfileGenerateRequest(BaseModel):
    """Body for POST /v1/characters/{id}/trait-profile/generate — generate + persist."""

    fields: Optional[List[TraitField]] = Field(
        default=None,
        description="Which fields to (re)generate. None (default) = ALL fields. Others untouched.",
    )
    enrichment: PersonaEnrichment = Field(
        default_factory=PersonaEnrichment,
        description="Transient likes/dislikes/interests/hobbies/language (not stored)",
    )
    dry_run: bool = Field(
        default=False, description="Generate + return only; do NOT write anything"
    )

    _v_fields = field_validator("fields")(_dedupe_fields)


class TraitProfileUpdate(BaseModel):
    """Body for PUT /v1/characters/{id}/trait-profile — manual per-field edit.

    Every field is optional; only fields actually sent (model exclude_unset) are
    written, so a manual edit is also never-clobber. provider is recorded as 'manual'.
    """

    wardrobe_styles: Optional[List[WardrobeStyleType]] = None
    favorite_outfits: Optional[List[OutfitType]] = None
    never_wears: Optional[List[OutfitType]] = None
    favorite_locations: Optional[List[LocationType]] = None
    avoided_locations: Optional[List[LocationType]] = None
    demeanor: Optional[List[DemeanorType]] = None
    interior_style: Optional[InteriorStyleType] = None
    color_palette: Optional[PaletteType] = None
    likes: Optional[List[str]] = None
    dislikes: Optional[List[str]] = None
    zodiac: Optional[ZodiacType] = None
    backstory: Optional[str] = Field(default=None, max_length=MAX_BACKSTORY_CHARS)
    home_description: Optional[str] = Field(default=None, max_length=MAX_HOME_DESCRIPTION_CHARS)
    quirks: Optional[List[str]] = None
    short_description: Optional[str] = Field(default=None, max_length=MAX_SHORT_DESCRIPTION_CHARS)
    display_occupation: Optional[str] = Field(default=None, max_length=MAX_DISPLAY_OCCUPATION_CHARS)
    display_personality: Optional[List[str]] = None
    display_hobbies: Optional[List[str]] = None
    language: Optional[str] = None


class TraitProfileRead(BaseModel):
    """A character_trait_profiles row as returned to the admin app."""

    character_id: str
    profile: TraitProfile
    provider: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TraitProfileGenerateResponse(BaseModel):
    """Result of a generate (+persist) call."""

    character_id: str
    profile: Optional[TraitProfile] = None
    generated: Dict[str, Any] = Field(
        default_factory=dict, description="Raw generated field values (also shown for dry_run)"
    )
    generated_fields: List[str] = Field(default_factory=list)
    provider: str = "deterministic"
    persisted: bool = False


class TraitProfilePreviewRequest(BaseModel):
    """Body for POST /v1/trait-profiles/preview — stateless suggestions, no character row."""

    persona: PersonaOptions = Field(..., description="The selected character options")
    fields: Optional[List[TraitField]] = Field(
        default=None, description="Which fields to generate. None = all."
    )
    enrichment: PersonaEnrichment = Field(default_factory=PersonaEnrichment)
    backstory: Optional[str] = Field(
        default=None,
        max_length=4000,
        description="Optional bio/backstory context to flavor derivation (not stored)",
    )

    _v_fields = field_validator("fields")(_dedupe_fields)


class TraitProfilePreviewResponse(BaseModel):
    profile: TraitProfile
    generated: Dict[str, Any] = Field(default_factory=dict)
    provider: str = "deterministic"
