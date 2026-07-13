"""
Trait profile writer — Venice authors a character's durable trait sheet (WS-B) as
structured JSON from her persona enums + bio, then everything is run through
`TraitProfile.coerce` (difflib repair + caps + NAKED-strip). Mirrors PersonaWriter:

  * PER-FIELD: only the requested fields are generated/returned (default: all).
  * REAL ALLOWED VALUES: each field spec interpolates the actual enum values so
    Venice picks from the legal vocabulary; near-misses are difflib-repaired and
    unknowns dropped by TraitProfile.coerce.
  * TASTE DRIVES PREFERENCES: the likes/dislikes specs instruct Venice to keep
    likes/dislikes CONSISTENT with the chosen wardrobe styles / interior_style /
    palette (per user intent — taste drives preferences).
  * NEVER RAISES: VeniceClient swallows errors; on any miss/garbage we fall back
    to deterministic tables (personality->demeanor+interior_style, occupation->
    wardrobe_styles, taste/occupation/kinks->likes/dislikes, zodiac via
    zlib.crc32(character_id) % 12), so the caller always gets a usable profile.

Outfit/location TAGS Venice may pick are validated against the real enums; the
style->outfit mapping (outfit_vocab) is deliberately NOT used here — the writer
emits wardrobe STYLE tags, never resolves them to garments (that is a later phase).
"""
from __future__ import annotations

import json
import logging
import re
import zlib
from typing import Any, Dict, List, Optional, Tuple

from models.enums import (
    DemeanorType,
    InteriorStyleType,
    LocationType,
    OutfitType,
    PaletteType,
    WardrobeStyleType,
    ZodiacType,
)
from models.requests import PersonaOptions
from models.trait_profile import ALL_TRAIT_FIELDS, TraitProfile
from services.venice_client import VeniceClient

logger = logging.getLogger(__name__)


# --- allowed value lists (interpolated into the field specs) ---
_WARDROBE_VALUES = [e.value for e in WardrobeStyleType]
_OUTFIT_VALUES = [e.value for e in OutfitType if e != OutfitType.NAKED]
_LOCATION_VALUES = [e.value for e in LocationType]
_DEMEANOR_VALUES = [e.value for e in DemeanorType]
_INTERIOR_VALUES = [e.value for e in InteriorStyleType]
_PALETTE_VALUES = [e.value for e in PaletteType]
_ZODIAC_ORDER = [e.value for e in ZodiacType]


def _joined(values: List[str]) -> str:
    return ", ".join(values)


# Per-field instruction the model is told for that field. Enum fields list their
# REAL allowed values; likes/dislikes are told to stay consistent with the taste.
_FIELD_SPECS: Dict[str, Dict[str, str]] = {
    "wardrobe_styles": {
        "instruction": (
            "1-3 wardrobe STYLE tags that fit her, chosen ONLY from: "
            f"[{_joined(_WARDROBE_VALUES)}]. JSON array of strings."
        ),
    },
    "favorite_outfits": {
        "instruction": (
            "0-5 specific outfit values she loves to wear, chosen ONLY from: "
            f"[{_joined(_OUTFIT_VALUES)}]. Never include 'naked'. JSON array of strings."
        ),
    },
    "never_wears": {
        "instruction": (
            "0-8 outfit values she would never wear, chosen ONLY from: "
            f"[{_joined(_OUTFIT_VALUES)}]. Never include 'naked'. JSON array of strings."
        ),
    },
    "favorite_locations": {
        "instruction": (
            "1-5 location values she gravitates to, chosen ONLY from: "
            f"[{_joined(_LOCATION_VALUES)}]. JSON array of strings."
        ),
    },
    "avoided_locations": {
        "instruction": (
            "0-8 location values she avoids, chosen ONLY from: "
            f"[{_joined(_LOCATION_VALUES)}]. JSON array of strings."
        ),
    },
    "demeanor": {
        "instruction": (
            "1-2 demeanor tags describing how she carries herself, chosen ONLY from: "
            f"[{_joined(_DEMEANOR_VALUES)}]. JSON array of strings."
        ),
    },
    "interior_style": {
        "instruction": (
            "ONE home interior style that matches her taste, chosen ONLY from: "
            f"[{_joined(_INTERIOR_VALUES)}]. A single string."
        ),
    },
    "color_palette": {
        "instruction": (
            "ONE color palette for her home/style, chosen ONLY from: "
            f"[{_joined(_PALETTE_VALUES)}]. A single string."
        ),
    },
    "likes": {
        "instruction": (
            "Up to 12 short things she likes (nouns/short phrases, e.g. 'iced matcha', "
            "'vinyl records'). Keep them CONSISTENT with her chosen wardrobe styles, "
            "interior_style and color_palette — her taste drives her preferences. "
            "JSON array of strings."
        ),
    },
    "dislikes": {
        "instruction": (
            "Up to 12 short things she dislikes. Keep them CONSISTENT with her taste — "
            "the natural opposites of her interior_style / color_palette / wardrobe. "
            "JSON array of strings."
        ),
    },
    "zodiac": {
        "instruction": (
            "ONE zodiac sign that fits her personality, chosen ONLY from: "
            f"[{_joined(_ZODIAC_ORDER)}]. A single string."
        ),
    },
    "backstory": {
        "instruction": (
            "A short third-person background narrative (<=800 chars). DISPLAY / "
            "LLM-context ONLY — it is NEVER rendered into an image, so it may be "
            "descriptive prose. Present tense, tasteful. Her heritage is given in the "
            "CHARACTER facts above — you MAY give her a matching nationality, name and "
            "cultural flavor (e.g. a Baltic heritage -> a Lithuanian background), but "
            "keep it natural and never contradict her other options."
        ),
    },
    "home_description": {
        "instruction": (
            "A short description of her home (<=400 chars), consistent with her "
            "interior_style + color_palette. DISPLAY / chat ONLY — NEVER rendered "
            "into an image."
        ),
    },
    "quirks": {
        "instruction": (
            "Up to 6 short personality quirks (display-only), e.g. 'always cold', "
            "'collects postcards'. JSON array of strings."
        ),
    },
    # --- public profile card (human-facing chat FE copy) ---
    "short_description": {
        "instruction": (
            "A 2-3 sentence dating-profile HOOK (<=220 chars) derived from her "
            "backstory/bio, e.g. 'Wealthy Russian heiress, accustomed to luxury and "
            "used to getting exactly what she wants... she enjoys indulging in every "
            "pleasure life has to offer.' Write it as an enticing intro the reader sees "
            "FIRST — a teaser, NOT a summary. Her heritage (in the CHARACTER facts) may "
            "inform a nationality/cultural flavor here, consistent with the backstory. "
            "No AI-speak, and do NOT use the raw enum words verbatim. A single string."
        ),
    },
    "display_occupation": {
        "instruction": (
            "A humanized job TITLE (<=40 chars), e.g. 'Heiress and Socialite' — never "
            "the raw enum value like 'heiress'. A single string."
        ),
    },
    "display_personality": {
        "instruction": (
            "2-4 human personality adjectives (each <=24 chars), e.g. "
            "['Well-educated','Spoiled','Charming'], consistent with her personality and "
            "backstory. JSON array of strings."
        ),
    },
    "display_hobbies": {
        "instruction": (
            "2-5 short hobby/interest phrases (each <=32 chars), e.g. "
            "['Exclusive parties','Five-star hotels','Shopping'], consistent with her "
            "likes. JSON array of strings."
        ),
    },
    "language": {
        "instruction": "Her primary language as a single word, e.g. 'English'. A string.",
    },
}

TRAIT_FIELDS = tuple(_FIELD_SPECS.keys())

TRAIT_SYSTEM_PROMPT = (
    "You are a character designer for an 18+ AI-companion app. Given a character's "
    "fixed persona options and bio, you author her durable TRAIT SHEET: her taste in "
    "clothing, places, home style, and preferences. This sheet biases how her photos "
    "are composed, so choices must be COHERENT — a sporty, minimalist character does "
    "not favor ballgowns.\n\n"
    "HARD RULES:\n"
    "- Output ONLY a single valid JSON object whose keys are EXACTLY the requested "
    "field names and whose values match each field's stated type. No markdown, no "
    "commentary, no extra keys.\n"
    "- For enum fields, choose ONLY from the listed allowed values (exact strings).\n"
    "- Never include 'naked' in any outfit list — nudity is controlled elsewhere.\n"
    "- Keep likes/dislikes consistent with her chosen taste (interior_style, "
    "color_palette, wardrobe_styles).\n"
    "- The card fields (short_description, display_occupation, display_personality, "
    "display_hobbies) are HUMAN-FACING display copy for her public profile: natural, "
    "enticing, NO AI-speak, and NEVER the raw enum words verbatim."
)


# ---------------------------------------------------------------------------
# Deterministic fallback tables (keyed by raw enum values / humanized labels).
# ---------------------------------------------------------------------------
_PERSONALITY_DEMEANOR: Dict[str, List[str]] = {
    "nympho": ["sultry", "confident"],
    "lover": ["cozy", "elegant"],
    "submissive": ["shy", "cozy"],
    "dominant": ["confident", "mysterious"],
    "temptress": ["sultry", "playful"],
    "innocent": ["shy", "playful"],
    "caregiver": ["cozy", "elegant"],
    "experimenter": ["playful", "energetic"],
    "mean": ["mysterious", "confident"],
    "confidant": ["cozy", "confident"],
    "shy": ["shy", "cozy"],
    "queen": ["elegant", "confident"],
}
_DEFAULT_DEMEANOR = ["confident"]

_PERSONALITY_INTERIOR_STYLE: Dict[str, str] = {
    "nympho": "luxury_glam",
    "lover": "cozy_bohemian",
    "submissive": "girly_pastel",
    "dominant": "industrial_loft",
    "temptress": "luxury_glam",
    "innocent": "girly_pastel",
    "caregiver": "rustic_warm",
    "experimenter": "artsy_eclectic",
    "mean": "modern_minimal",
    "confidant": "scandinavian_light",
    "shy": "scandinavian_light",
    "queen": "luxury_glam",
}
_DEFAULT_INTERIOR_STYLE = "scandinavian_light"

_INTERIOR_STYLE_PALETTE: Dict[str, str] = {
    "cozy_bohemian": "warm_neutrals",
    "modern_minimal": "crisp_white",
    "luxury_glam": "jewel_tones",
    "rustic_warm": "earthy_green",
    "scandinavian_light": "crisp_white",
    "industrial_loft": "bold_dark",
    "girly_pastel": "soft_pastels",
    "artsy_eclectic": "jewel_tones",
}
_DEFAULT_PALETTE = "warm_neutrals"

_OCCUPATION_WARDROBE: Dict[str, List[str]] = {
    "student": ["casual_minimal", "girly"],
    "dancer": ["glamorous", "sporty"],
    "model": ["glamorous", "elegant"],
    "stripper": ["glamorous", "edgy"],
    "maid": ["professional", "girly"],
    "cam_girl": ["girly", "glamorous"],
    "boss_ceo": ["professional", "elegant"],
    "babysitter_au_pair": ["casual_minimal", "cozy_lounge"],
    "pornstar": ["glamorous", "edgy"],
    "streamer": ["streetwear", "casual_minimal"],
    "bartender": ["edgy", "streetwear"],
    "tech_engineer": ["casual_minimal", "streetwear"],
    "lifeguard": ["sporty", "casual_minimal"],
    "cashier": ["casual_minimal", "girly"],
    "massage_therapist": ["casual_minimal", "cozy_lounge"],
    "nurse": ["professional", "casual_minimal"],
    "secretary": ["professional", "elegant"],
    "yoga_instructor": ["sporty", "cozy_lounge"],
    "fitness_coach": ["sporty", "casual_minimal"],
    "cook": ["professional", "casual_minimal"],
    "artist": ["bohemian", "edgy"],
    "movie_star_actress": ["glamorous", "elegant"],
    "doctor": ["professional", "elegant"],
    "librarian": ["casual_minimal", "cozy_lounge"],
    "spy": ["elegant", "edgy"],
    "police_officer": ["professional", "sporty"],
    "soldier": ["sporty", "professional"],
    "lawyer": ["professional", "elegant"],
    "hairdresser": ["edgy", "girly"],
    "dentist": ["professional", "casual_minimal"],
    "singer_musician": ["glamorous", "edgy"],
    "gynecologist": ["professional", "elegant"],
    "writer": ["bohemian", "cozy_lounge"],
    "flight_attendant": ["professional", "elegant"],
    "professional_athlete": ["sporty", "streetwear"],
    "scientist": ["professional", "casual_minimal"],
    "florist": ["bohemian", "girly"],
    "makeup_artist": ["glamorous", "girly"],
    "photographer": ["streetwear", "edgy"],
    "social_worker": ["casual_minimal", "cozy_lounge"],
    "designer": ["edgy", "elegant"],
    "pharmacist": ["professional", "casual_minimal"],
    "nutritionist": ["sporty", "casual_minimal"],
    "teacher": ["professional", "girly"],
}
_DEFAULT_WARDROBE = ["casual_minimal"]

_INTERIOR_STYLE_LIKES: Dict[str, List[str]] = {
    "cozy_bohemian": ["scented candles", "vinyl records", "houseplants", "chai lattes"],
    "modern_minimal": ["clean design", "black coffee", "quiet spaces", "matcha"],
    "luxury_glam": ["champagne", "designer heels", "gold jewelry", "spa days"],
    "rustic_warm": ["fresh bread", "open fires", "wool blankets", "farmers markets"],
    "scandinavian_light": ["morning light", "linen sheets", "filter coffee", "long walks"],
    "industrial_loft": ["craft beer", "street art", "espresso", "record stores"],
    "girly_pastel": ["fresh flowers", "strawberry milk", "soft blankets", "rom-coms"],
    "artsy_eclectic": ["gallery openings", "thrifted finds", "poetry", "red wine"],
}

_INTERIOR_STYLE_DISLIKES: Dict[str, List[str]] = {
    "cozy_bohemian": ["sterile spaces", "harsh fluorescent light", "fast food"],
    "modern_minimal": ["clutter", "loud patterns", "knick-knacks"],
    "luxury_glam": ["cheap fabrics", "dive bars", "messy rooms"],
    "rustic_warm": ["plastic decor", "crowded cities", "cold minimalism"],
    "scandinavian_light": ["dark rooms", "clutter", "heavy perfume"],
    "industrial_loft": ["pastel decor", "twee cafes", "small talk"],
    "girly_pastel": ["horror movies", "dark colors", "rough edges"],
    "artsy_eclectic": ["beige everything", "corporate offices", "small talk"],
}

_OCCUPATION_LIKES: Dict[str, List[str]] = {
    "student": ["late-night study", "cheap ramen"],
    "dancer": ["choreography", "stage lights"],
    "model": ["photoshoots", "runway shows"],
    "nurse": ["quiet night shifts", "strong coffee"],
    "yoga_instructor": ["sunrise flows", "green smoothies"],
    "fitness_coach": ["morning runs", "protein shakes"],
    "artist": ["sketchbooks", "gallery visits"],
    "writer": ["old bookstores", "rainy afternoons"],
    "cook": ["farmers markets", "sharp knives"],
    "bartender": ["cocktail nights", "live music"],
    "librarian": ["old books", "quiet libraries"],
    "photographer": ["golden hour", "film cameras"],
    "florist": ["fresh blooms", "garden centers"],
    "teacher": ["stationery", "slow Sunday mornings"],
}

_KINK_LIKES: Dict[str, List[str]] = {
    "playful_teasing": ["flirty banter"],
    "cuddling": ["lazy cuddles"],
    "slow_sensual": ["slow evenings"],
    "dirty_talk": ["whispered secrets"],
    "roleplay": ["dressing up"],
    "shy_flirting": ["stolen glances"],
}

# --- public profile card deterministic fallbacks ---
# Humanized job titles where a plain .title() reads poorly; everything else falls
# back to occupation.replace('_', ' ').title().
_OCCUPATION_TITLE: Dict[str, str] = {
    "boss_ceo": "CEO and Boss",
    "cam_girl": "Cam Model",
    "movie_star_actress": "Movie Star",
    "singer_musician": "Singer and Musician",
    "babysitter_au_pair": "Au Pair",
    "tech_engineer": "Software Engineer",
    "professional_athlete": "Professional Athlete",
    "police_officer": "Police Officer",
    "flight_attendant": "Flight Attendant",
    "social_worker": "Social Worker",
    "massage_therapist": "Massage Therapist",
    "yoga_instructor": "Yoga Instructor",
    "fitness_coach": "Fitness Coach",
    "makeup_artist": "Makeup Artist",
}
_DEFAULT_OCCUPATION_TITLE = "Socialite"

# Human personality adjectives per personality enum (display_personality fallback).
_PERSONALITY_ADJECTIVES: Dict[str, List[str]] = {
    "nympho": ["Passionate", "Uninhibited", "Bold"],
    "lover": ["Warm", "Affectionate", "Romantic"],
    "submissive": ["Gentle", "Obliging", "Sweet"],
    "dominant": ["Commanding", "Assertive", "Self-assured"],
    "temptress": ["Alluring", "Playful", "Magnetic"],
    "innocent": ["Sweet", "Curious", "Wholesome"],
    "caregiver": ["Nurturing", "Kind", "Attentive"],
    "experimenter": ["Adventurous", "Curious", "Open-minded"],
    "mean": ["Sharp-witted", "Cool", "Unapologetic"],
    "confidant": ["Trustworthy", "Warm", "Grounded"],
    "shy": ["Reserved", "Soft-spoken", "Thoughtful"],
    "queen": ["Regal", "Poised", "Commanding"],
}
_DEFAULT_ADJECTIVES = ["Charming", "Confident"]
_DEFAULT_HOBBIES = ["Traveling", "Good company"]


# Heritage -> example nationalities the writer MAY use for a character's
# nationality/name/cultural flavor in her (display-only) backstory + short
# description. Keyed by EthnicityType value; unknown/None -> "" (no hint, degrades
# safely). This is narrative flavor ONLY — it never enters a render prompt (the
# render-side skin/bone descriptor lives in attribute_phrases.ETHNICITY_PHRASES).
_HERITAGE_NATIONALITY_HINT: Dict[str, str] = {
    # --- legacy (broad buckets — looser hints) ---
    "caucasian": "European",
    "asian": "East Asian",
    "black_afro": "of the African diaspora",
    "latina": "Latina (e.g. Mexican, Colombian, Argentinian)",
    "arab": "Arab / Middle Eastern (e.g. Lebanese, Emirati, Jordanian)",
    # --- European ---
    "nordic": "Scandinavian (e.g. Swedish, Norwegian, Danish, Finnish)",
    "slavic": "Slavic (e.g. Russian, Ukrainian, Polish)",
    "baltic": "Baltic (e.g. Lithuanian, Latvian, Estonian)",
    "western_european": "Western European (e.g. French, German, Dutch)",
    "mediterranean": "Mediterranean (e.g. Italian, Greek, Spanish)",
    # --- Asian ---
    "japanese": "Japanese",
    "korean": "Korean",
    "chinese": "Chinese",
    "southeast_asian": "Southeast Asian (e.g. Thai, Filipina, Vietnamese)",
    "south_asian": "South Asian (e.g. Indian, Pakistani, Sri Lankan)",
    "central_asian": "Central Asian (e.g. Kazakh, Uzbek, Mongolian)",
    # --- Middle East / North Africa ---
    "persian": "Persian (Iranian)",
    "turkish": "Turkish",
    "north_african": "North African (e.g. Moroccan, Egyptian, Tunisian)",
    # --- African ---
    "west_african": "West African (e.g. Nigerian, Ghanaian, Senegalese)",
    "east_african": "East African (e.g. Kenyan, Tanzanian, Ugandan)",
    "horn_of_africa": "of the Horn of Africa (e.g. Ethiopian, Somali, Eritrean)",
    "afro_caribbean": "Afro-Caribbean (e.g. Jamaican, Trinidadian, Haitian)",
    # --- Americas ---
    "brazilian": "Brazilian",
    # --- Mixed ---
    "mixed_heritage": "of mixed heritage",
}


def _heritage_hint(ethnicity) -> str:
    """
    A short 'heritage: <label> (e.g. nationalities)' hint for the fact sheet, or ''
    when ethnicity is unset. Falls back to the humanized enum label for any value
    not in the hint table so new/unknown values still degrade to a usable hint.
    """
    key = _val(ethnicity)
    if not key:
        return ""
    return _HERITAGE_NATIONALITY_HINT.get(key) or key.replace("_", " ")


def _val(value) -> str:
    """Raw enum/string value ('' for None)."""
    if value is None:
        return ""
    return str(getattr(value, "value", value)).strip()


def _label(value) -> str:
    return _val(value).replace("_", " ").strip()


def _norm_field(f) -> str:
    return getattr(f, "value", f)


def _zodiac_for(seed: str) -> str:
    """Deterministic, hash-stable zodiac from a stable seed (character_id/name)."""
    idx = zlib.crc32((seed or "seed").encode("utf-8")) % 12
    return _ZODIAC_ORDER[idx]


class TraitProfileWriter:
    """Generates a character's trait sheet; never raises."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.venice.ai/api/v1",
        model: str = "venice-uncensored",
        temperature: float = 0.7,
        max_tokens: int = 900,
        timeout: float = 100.0,
    ):
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = VeniceClient(api_key, base_url=base_url, model=model, timeout=timeout)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def write(
        self,
        persona: PersonaOptions,
        fields: Optional[List] = None,
        enrichment: Optional[dict] = None,
        *,
        character_id: Optional[str] = None,
        bio: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], str]:
        """
        Return ({field: json-safe value} for exactly the requested fields, provider).

        `fields` None -> ALL trait fields. `character_id` seeds the deterministic
        zodiac (hash-stable). `bio` is optional LLM context (never stored here).
        """
        req = self._resolve_fields(fields)
        if not req:
            return {}, "deterministic"

        det_dump = self._deterministic_dump(persona, enrichment, character_id, bio)

        if not self.enabled:
            return {f: det_dump[f] for f in req}, "deterministic"

        try:
            content, _usage = await self._client.chat(
                [
                    {"role": "system", "content": TRAIT_SYSTEM_PROMPT},
                    {"role": "user", "content": self._build_user_prompt(persona, req, enrichment, bio)},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            parsed = _extract_json_object(content) if content else None
            venice_dump = TraitProfile.coerce(parsed or {}).model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001 - never let generation break the caller
            logger.error(f"TraitProfileWriter Venice path failed; using deterministic: {exc}")
            return {f: det_dump[f] for f in req}, "deterministic"

        out: Dict[str, Any] = {}
        from_venice = 0
        for f in req:
            vval = venice_dump.get(f)
            if _is_present(vval):
                out[f] = vval
                from_venice += 1
            else:
                out[f] = det_dump[f]

        if from_venice == 0:
            provider = "deterministic"
        elif from_venice == len(req):
            provider = "venice"
        else:
            provider = "mixed"
        return out, provider

    def _resolve_fields(self, fields: Optional[List]) -> List[str]:
        if fields is None:
            return list(ALL_TRAIT_FIELDS)
        return [f for f in (_norm_field(x) for x in fields) if f in _FIELD_SPECS]

    def _build_user_prompt(
        self, persona: PersonaOptions, fields: List[str], enrichment: Optional[dict], bio: Optional[str]
    ) -> str:
        facts = self._character_facts(persona, enrichment, bio)
        field_lines = [f'- "{f}": {_FIELD_SPECS[f]["instruction"]}' for f in fields]
        return (
            "CHARACTER:\n" + facts + "\n\n"
            "Author ONLY these fields as a single JSON object with exactly these keys:\n"
            + "\n".join(field_lines)
        )

    def _character_facts(
        self, persona: PersonaOptions, enrichment: Optional[dict], bio: Optional[str]
    ) -> str:
        e = enrichment or {}
        lines = [
            f"name: {persona.name or 'she'}",
            f"age: {persona.age}",
            f"heritage: {_heritage_hint(persona.ethnicity) or 'unspecified'}",
            f"personality: {_label(persona.personality) or 'unspecified'}",
            f"relationship to the user: {_label(persona.relationship) or 'unspecified'}",
            f"occupation: {_label(persona.occupation) or 'unspecified'}",
            f"interests/kinks: {', '.join(_label(k) for k in (persona.kinks or [])) or 'none given'}",
            f"likes (hints): {', '.join(str(x) for x in (e.get('likes') or [])) or 'none given'}",
            f"dislikes (hints): {', '.join(str(x) for x in (e.get('dislikes') or [])) or 'none given'}",
        ]
        if bio and bio.strip():
            lines.append(f"bio/backstory context: {bio.strip()[:800]}")
        if e.get("language"):
            lines.append(f"output language: {e['language']}")
        return "\n".join(lines)

    def _deterministic_dump(
        self,
        persona: PersonaOptions,
        enrichment: Optional[dict],
        character_id: Optional[str],
        bio: Optional[str],
    ) -> Dict[str, Any]:
        """Full-profile deterministic fallback, coerced (caps/clean) and JSON-dumped."""
        e = enrichment or {}
        personality = _val(persona.personality)
        occupation = _val(persona.occupation)
        kinks = [_val(k) for k in (persona.kinks or [])]
        name = persona.name or "She"

        demeanor = _PERSONALITY_DEMEANOR.get(personality, _DEFAULT_DEMEANOR)
        interior_style = _PERSONALITY_INTERIOR_STYLE.get(personality, _DEFAULT_INTERIOR_STYLE)
        color_palette = _INTERIOR_STYLE_PALETTE.get(interior_style, _DEFAULT_PALETTE)
        wardrobe_styles = _OCCUPATION_WARDROBE.get(occupation, _DEFAULT_WARDROBE)

        likes = list(e.get("likes") or [])
        likes += _INTERIOR_STYLE_LIKES.get(interior_style, [])
        likes += _OCCUPATION_LIKES.get(occupation, [])
        for k in kinks:
            likes += _KINK_LIKES.get(k, [])

        dislikes = list(e.get("dislikes") or [])
        dislikes += _INTERIOR_STYLE_DISLIKES.get(interior_style, [])

        zodiac = _zodiac_for(character_id or name)

        occ_label = _label(persona.occupation) or "young woman"
        pers_label = _label(persona.personality) or "warm"
        style_label = interior_style.replace("_", " ")
        palette_label = color_palette.replace("_", " ")
        top_like = (likes[0] if likes else "quiet mornings")

        backstory = (
            f"{name} is a {persona.age}-year-old {occ_label} with a {pers_label} streak. "
            f"She keeps a {style_label} home and is happiest around {top_like}."
        )
        home_description = (
            f"Her place has a {style_label} feel in {palette_label} tones, warm and "
            f"lived-in, styled to match her taste."
        )

        # --- public profile card fields ---
        display_occupation = _OCCUPATION_TITLE.get(occupation) or (
            occ_label.title() if occupation else _DEFAULT_OCCUPATION_TITLE
        )
        display_personality = _PERSONALITY_ADJECTIVES.get(personality, _DEFAULT_ADJECTIVES)
        hobby_src = list(e.get("hobbies") or []) + list(e.get("interests") or []) + likes
        display_hobbies: List[str] = []
        for h in hobby_src:
            t = str(h).strip().title()
            if t and t not in display_hobbies:
                display_hobbies.append(t)
            if len(display_hobbies) >= 5:
                break
        if len(display_hobbies) < 2:
            display_hobbies = (display_hobbies + _DEFAULT_HOBBIES)[:5]
        language = (e.get("language") or "English")
        adj_lower = display_personality[0].lower() if display_personality else "charming"
        likes_phrase = ", ".join(likes[:2]) if likes else "the finer things"
        short_description = (
            f"{display_occupation} with a {adj_lower} spirit. She loves {likes_phrase}, "
            f"and knows how to make every moment feel effortless."
        )

        raw: Dict[str, Any] = {
            "wardrobe_styles": wardrobe_styles,
            "favorite_outfits": [],
            "never_wears": [],
            "favorite_locations": [],
            "avoided_locations": [],
            "demeanor": demeanor,
            "interior_style": interior_style,
            "color_palette": color_palette,
            "likes": likes,
            "dislikes": dislikes,
            "zodiac": zodiac,
            "backstory": backstory,
            "home_description": home_description,
            "quirks": [],
            "short_description": short_description,
            "display_occupation": display_occupation,
            "display_personality": display_personality,
            "display_hobbies": display_hobbies,
            "language": language,
        }
        # Coerce so caps/dedupe/validators apply uniformly, then JSON-dump.
        return TraitProfile.coerce(raw).model_dump(mode="json")


def _is_present(value: Any) -> bool:
    """A generated value counts as 'from Venice' only when it is non-empty."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return len(value) > 0
    return True


def _extract_json_object(raw: Optional[str]) -> Optional[dict]:
    """Tolerant JSON extraction (mirrors persona_writer / story_planner)."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None
