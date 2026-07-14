"""
Deterministic enum -> rich phrase maps for prompt assembly.

The admin selects discrete persona attributes (enums); these maps turn each into a
descriptive photographic phrase so the positive prompt is built deterministically
from the admin's selections, with no model in the loop for the core identity tokens.
Lookups are by the enum's string value and degrade to "" for unknown/None values.
"""
from typing import Optional


def _val(v) -> Optional[str]:
    """Normalize an enum or string to its lowercase value, or None."""
    if v is None:
        return None
    return getattr(v, "value", v)


# --- Scaffold (medium/lens only) ----------------------------------------------
# Framing lives in the shot block (services/camera_vocab.py), lighting/polish in
# the workflow-side photo-style wrapper (prompt_constants.PHOTO_STYLE_TEMPLATES).
STYLE_PHRASES = {
    "realistic": "ultra-realistic professional photograph, 85mm lens, sharp focus, "
                 "photorealistic skin texture",
    "anime": "high-quality anime illustration, clean line art, vibrant cel shading, "
             "detailed, masterpiece",
}

# --- Locked identity block ---------------------------------------------------
# One entry per EthnicityType value (models/enums.py). Each describes ONLY skin
# tone + facial/bone structure + a heritage adjective — NEVER hair color/texture
# or eye color (those are separate persona fields — HAIR_*/EYE_COLOR_PHRASES — and
# a heritage phrase that named them would fight the admin's explicit choice). The
# 5 legacy entries are byte-identical to the original 5-value map for back-compat.
ETHNICITY_PHRASES = {
    # --- legacy (unchanged) ---
    "caucasian": "a Caucasian woman with fair skin",
    "asian": "an East Asian woman with light skin",
    "black_afro": "a Black woman with warm dark-brown skin",
    "latina": "a Latina woman with warm tan skin",
    "arab": "a Middle Eastern woman with olive skin",
    # --- European ---
    "nordic": "a Nordic woman with fair soft-matte skin and softly angular features",
    "slavic": "a Slavic woman with fair skin, high cheekbones and gently rounded features",
    "baltic": "a Baltic woman with very fair cool-toned skin and refined angular features",
    "western_european": "a Western European woman with fair neutral-toned skin and classic refined features",
    "mediterranean": "a Mediterranean woman with warm olive skin and expressive sculpted features",
    # --- Asian ---
    "japanese": "a Japanese woman with light matte ivory skin and delicate refined features",
    "korean": "a Korean woman with light even-toned matte skin and soft elegant features",
    "chinese": "a Chinese woman with light warm-toned skin and graceful refined features",
    "southeast_asian": "a Southeast Asian woman with warm golden-tan skin and soft rounded features",
    "south_asian": "a South Asian woman with warm brown skin and striking defined features",
    "central_asian": "a Central Asian woman with light golden skin and softly blended Eurasian features",
    # --- Middle East / North Africa ---
    "persian": "a Persian woman with light olive skin and elegant defined features",
    "turkish": "a Turkish woman with warm olive skin and strong graceful features",
    "north_african": "a North African woman with golden-bronze skin and defined elegant features",
    # --- African ---
    "west_african": "a West African woman with deep rich ebony skin and full striking features",
    "east_african": "an East African woman with deep warm-brown skin and tall elegant bone structure",
    "horn_of_africa": "a woman of Horn of Africa heritage with rich copper-brown skin and finely sculpted features",
    "afro_caribbean": "an Afro-Caribbean woman with warm deep-brown skin and vibrant full features",
    # --- Americas ---
    "brazilian": "a Brazilian woman with warm bronze skin and softly sculpted features",
    # --- Mixed ---
    "mixed_heritage": "a woman of mixed heritage with warm golden-tan skin and harmoniously blended features",
}

# Just the SKIN-TONE descriptor for each ethnicity — the visual attribute pulled
# out of ETHNICITY_PHRASES above, with the demographic label ("a Black woman")
# deliberately dropped. Edits repaint the body (outfit denoise 0.85-0.9, pose
# denoise 1.0 full-frame) while ReActor restores only the face, so without a skin
# tone in the edit prompt a dark-skinned character comes back with a white body.
# This map feeds scene_mapper.identity_anchor_text so the edit prompts carry
# "warm dark-brown skin" (a paintable attribute) rather than the label — which
# would fight the render the same way an age-down word does. Keyed by the
# EthnicityType enum value (models/enums.py).
SKIN_TONE_PHRASES = {
    # --- legacy (unchanged) ---
    "caucasian": "fair skin",
    "asian": "light skin",
    "black_afro": "warm dark-brown skin",
    "latina": "warm tan skin",
    "arab": "olive skin",
    # --- European ---
    "nordic": "fair soft-matte skin",
    "slavic": "fair skin",
    "baltic": "very fair cool-toned skin",
    "western_european": "fair neutral-toned skin",
    "mediterranean": "warm olive skin",
    # --- Asian ---
    "japanese": "light matte ivory skin",
    "korean": "light even-toned matte skin",
    "chinese": "light warm-toned skin",
    "southeast_asian": "warm golden-tan skin",
    "south_asian": "warm brown skin",
    "central_asian": "light golden skin",
    # --- Middle East / North Africa ---
    "persian": "light olive skin",
    "turkish": "warm olive skin",
    "north_african": "golden-bronze skin",
    # --- African ---
    "west_african": "deep rich ebony skin",
    "east_african": "deep warm-brown skin",
    "horn_of_africa": "rich copper-brown skin",
    "afro_caribbean": "warm deep-brown skin",
    # --- Americas ---
    "brazilian": "warm bronze skin",
    # --- Mixed ---
    "mixed_heritage": "warm golden-tan skin",
}

HAIR_STYLE_PHRASES = {
    "straight": "long straight hair",
    "bangs": "hair with blunt bangs",
    "curly": "curly hair",
    "bun": "hair styled in a neat bun",
    "short": "short hair",
    "ponytail": "hair tied in a ponytail",
}

HAIR_COLOR_PHRASES = {
    "brunette": "brunette",
    "blonde": "blonde",
    "black": "black",
    "redhead": "red",
    "pink": "pink",
}

EYE_COLOR_PHRASES = {
    "brown": "brown eyes",
    "blue": "blue eyes",
    "green": "green eyes",
}

BODY_TYPE_PHRASES = {
    "skinny": "slim slender figure",
    "athletic": "toned athletic figure",
    "average": "average natural figure",
    "curvy": "curvy hourglass figure",
    "bbw": "full-figured voluptuous body",
}

BREAST_SIZE_PHRASES = {
    "small": "small breasts",
    "medium": "medium breasts",
    "large": "large breasts",
    "extra_large": "very large breasts",
}

# Pubic-hair grooming descriptors, keyed by PubicHairType value (models/enums.py).
# Matte doctrine (no gloss/shine vocabulary — same discipline as the nude-base
# anti-gloss clauses): these describe grooming/hair only, never a wet/oily/glossy
# finish. Consumed ONLY where the genital area is exposed (nude base always;
# generation/batch NAKED-class at HIGH nudity), via pubic_hair_phrase() below —
# never in the always-on identity block. A None/unknown value resolves to the
# SHAVED phrase (see pubic_hair_phrase), the product default.
PUBIC_HAIR_PHRASES = {
    "shaved": "completely smooth shaved pubic area",
    "trimmed": "neatly trimmed short pubic hair",
    "landing_strip": "a narrow neatly groomed strip of pubic hair",
    "natural": "naturally groomed soft pubic hair",
    "full": "full natural untrimmed pubic hair",
}

# --- Persona flavor ----------------------------------------------------------
PERSONALITY_PHRASES = {
    "nympho": "a sultry, seductive expression",
    "lover": "a warm, affectionate expression",
    "submissive": "a soft, demure expression",
    "dominant": "a confident, commanding expression",
    "temptress": "a teasing, alluring expression",
    "innocent": "an innocent, sweet expression",
    "caregiver": "a gentle, caring expression",
    "experimenter": "a curious, playful expression",
    "mean": "a cold, aloof expression",
    "confidant": "a friendly, trusting expression",
    "shy": "a shy, bashful expression",
    "queen": "a regal, elegant expression",
}

# One entry for every RelationshipType value (models/enums.py).
# NOTE: no phrase may contain age-down language (e.g. young-appearance terms) —
# such wording is negated by prompt_constants.ADULT_APPEARANCE_NEGATIVE and would
# fight the model. This is why school_mate/step_daughter/student avoid it.
RELATIONSHIP_PHRASES = {
    "stranger": "intriguing stranger vibe",
    "girlfriend": "girlfriend vibe",
    "sex_friend": "casual flirtatious vibe",
    "school_mate": "casual collegiate style",
    "work_colleague": "professional colleague look",
    "wife": "elegant married woman",
    "mistress": "alluring mistress",
    "friend": "warm friendly vibe",
    "step_sister": "playful familiar vibe",
    "step_mom": "mature confident look",
    "step_daughter": "playful lighthearted vibe",
    "landlord": "confident authoritative look",
    "sugar_baby": "glamorous look",
    "boss": "powerful boss look",
    "teacher": "refined teacher look",
    "student": "collegiate student look",
    "neighbour": "approachable everyday look",
    "mother_in_law": "poised mature look",
    "sister_in_law": "familiar approachable vibe",
}

OCCUPATION_PHRASES = {
    "student": "student",
    "dancer": "dancer",
    "model": "fashion model",
    "stripper": "exotic dancer",
    "maid": "maid",
    "cam_girl": "cam model",
    "boss_ceo": "executive",
    "babysitter_au_pair": "au pair",
    "pornstar": "adult performer",
    "streamer": "online streamer",
    "bartender": "bartender",
    "tech_engineer": "software engineer",
    "lifeguard": "lifeguard",
    "cashier": "cashier",
    "massage_therapist": "massage therapist",
    "nurse": "nurse",
    "secretary": "secretary",
    "yoga_instructor": "yoga instructor",
    "fitness_coach": "fitness coach",
    "cook": "cook",
    "artist": "artist",
    "movie_star_actress": "movie star",
    "doctor": "doctor",
    "librarian": "librarian",
    "spy": "secret agent",
    "police_officer": "police officer",
    "soldier": "soldier",
    "lawyer": "lawyer",
    "hairdresser": "hairdresser",
    "dentist": "dentist",
    "singer_musician": "singer",
    "gynecologist": "physician",
    "writer": "writer",
    "flight_attendant": "flight attendant",
    "professional_athlete": "athlete",
    "scientist": "scientist",
    "florist": "florist",
    "makeup_artist": "makeup artist",
    "photographer": "photographer",
    "social_worker": "social worker",
    "designer": "designer",
    "pharmacist": "pharmacist",
    "nutritionist": "nutritionist",
    "teacher": "teacher",
}

# Kinks contribute mood/atmosphere only; kept tasteful and descriptive.
# One entry for every KinkType value (models/enums.py).
KINK_PHRASES = {
    "bondage": "tense restrained mood",
    "spanking": "playful power-play mood",
    "collar_leash": "submissive dynamic mood",
    "punishment": "stern disciplinary mood",
    "humiliation": "vulnerable blushing mood",
    "public_play": "daring exhibitionist mood",
    "roleplay": "playful roleplay theme",
    "anal_play": "intense intimate mood",
    "oral_play": "sultry intimate mood",
    "cum_play": "heated intimate mood",
    "creampie": "deeply intimate mood",
    "squirting": "intense ecstatic mood",
    "dirty_talk": "sultry confident mood",
    "breeding": "primal passionate mood",
    "edging": "teasing anticipatory mood",
    "obedience": "submissive mood",
    "control": "commanding dominant mood",
    "inexperienced": "shy curious mood",
    "shy_flirting": "shy flirtatious mood",
    "playful_teasing": "playful teasing mood",
    "cuddling": "intimate affectionate mood",
    "slow_sensual": "slow sensual mood",
    "hair_pulling": "rough passionate mood",
}


def phrase(mapping: dict, value, default: str = "") -> str:
    """Look up a phrase by enum/value, returning default if absent."""
    key = _val(value)
    if key is None:
        return default
    return mapping.get(key, default)


def skin_tone_phrase(ethnicity) -> Optional[str]:
    """
    The bare skin-tone descriptor for an ethnicity (e.g. ``black_afro`` ->
    "warm dark-brown skin"), or None for an unknown/None value.

    Case- and underscore-tolerant: an enum member, "BLACK_AFRO", or "black-afro"
    all resolve to the ``black_afro`` key. Returns just the paintable skin
    attribute from SKIN_TONE_PHRASES, never the demographic label — see that map's
    note for why the label is excluded from edit prompts.
    """
    key = _val(ethnicity)
    if key is None:
        return None
    key = str(key).strip().lower().replace("-", "_").replace(" ", "_")
    return SKIN_TONE_PHRASES.get(key)


def pubic_hair_phrase(pubic_hair) -> str:
    """
    Grooming descriptor for the pubic area (e.g. ``trimmed`` -> "neatly trimmed
    short pubic hair").

    None/unknown resolves to the SHAVED phrase (the product default) so a persona
    or stored row that predates this field still renders a definite groomed state
    instead of leaving the NSFW-tuned base to improvise anatomy. Case- and
    underscore-tolerant, mirroring ``skin_tone_phrase``: an enum member, "SHAVED",
    or "landing-strip" all resolve. Returns a matte descriptor from
    PUBIC_HAIR_PHRASES (never gloss/shine vocabulary). Always returns a non-empty
    string — callers gate on WHERE it applies (exposed genital area only), not on
    whether it's set.
    """
    key = _val(pubic_hair)
    if key is not None:
        key = str(key).strip().lower().replace("-", "_").replace(" ", "_")
    return PUBIC_HAIR_PHRASES.get(key, PUBIC_HAIR_PHRASES["shaved"])


def age_phrase(age: Optional[int]) -> str:
    """
    Photographic age descriptor (always 18+): the number plus bucket vocabulary,
    so 18/25/45 actually read as different ages instead of a generic mid-twenties.

    SAFETY: every bucket is explicitly adult-worded ("adult"/"woman"); no
    teen/teenage/adolescent/child/girl language (that would be negated by
    prompt_constants.ADULT_APPEARANCE_NEGATIVE and fight the render).
    """
    if not age:
        return ""
    age = int(age)
    if age <= 19:
        return f"{age} years old, youthful fresh-faced young adult woman, smooth clear skin"
    if age <= 23:
        return f"{age} years old, in her early twenties, youthful adult look"
    if age <= 27:
        return f"{age} years old, mid-twenties adult woman"
    if age <= 33:
        return f"{age} years old, late twenties to early thirties, subtly mature adult features"
    if age <= 41:
        return f"{age} years old, in her thirties, mature adult woman"
    return f"{age} years old, in her forties, mature adult woman with natural fine age lines"


def hair_phrase(hair_style, hair_color) -> str:
    """Combine hair color + style, e.g. 'blonde long straight hair'."""
    color = phrase(HAIR_COLOR_PHRASES, hair_color)
    style = phrase(HAIR_STYLE_PHRASES, hair_style)
    if color and style:
        # Insert color before the noun 'hair' in the style phrase.
        return style.replace("hair", f"{color} hair", 1)
    return style or (f"{color} hair" if color else "")


def kinks_phrase(kinks) -> str:
    """
    Join at most 2 kink mood phrases (in the order given).

    Capped deliberately: stacking 3-4 mood clauses ("stern disciplinary mood,
    vulnerable blushing mood, sultry confident mood, ...") muddies the hero-shot
    aesthetic — conflicting moods pull expression and color grading in different
    directions and the cards stop looking like one consistent set.
    """
    if not kinks:
        return ""
    parts = [p for p in (phrase(KINK_PHRASES, k) for k in kinks) if p]
    return ", ".join(parts[:2])
