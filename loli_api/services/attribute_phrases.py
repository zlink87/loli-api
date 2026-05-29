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


# --- Scaffold (shot/format) --------------------------------------------------
STYLE_PHRASES = {
    "realistic": "ultra-realistic professional photograph, full-body shot, 85mm lens, "
                 "natural soft lighting, sharp focus, high detail, photorealistic skin texture",
    "anime": "high-quality anime illustration, full-body, clean line art, vibrant cel shading, "
             "detailed, masterpiece",
}

# --- Locked identity block ---------------------------------------------------
ETHNICITY_PHRASES = {
    "caucasian": "a Caucasian woman with fair skin",
    "asian": "an East Asian woman with light skin",
    "black_afro": "a Black woman with warm dark-brown skin",
    "latina": "a Latina woman with warm tan skin",
    "arab": "a Middle Eastern woman with olive skin",
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

RELATIONSHIP_PHRASES = {
    "girlfriend": "girlfriend vibe",
    "wife": "elegant married woman",
    "mistress": "alluring mistress",
    "sugar_baby": "glamorous look",
    "teacher": "refined teacher look",
    "student": "youthful student look",
    "boss": "powerful boss look",
    "neighbour": "approachable everyday look",
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
}

# Kinks contribute mood/atmosphere only; kept tasteful and descriptive.
KINK_PHRASES = {
    "shy_flirting": "shy flirtatious mood",
    "playful_teasing": "playful teasing mood",
    "cuddling": "intimate affectionate mood",
    "slow_sensual": "slow sensual mood",
    "dirty_talk": "sultry confident mood",
    "roleplay": "playful roleplay theme",
    "dominant": "dominant mood",
    "obedience": "submissive mood",
}


def phrase(mapping: dict, value, default: str = "") -> str:
    """Look up a phrase by enum/value, returning default if absent."""
    key = _val(value)
    if key is None:
        return default
    return mapping.get(key, default)


def age_phrase(age: Optional[int]) -> str:
    """Photographic age descriptor (always 18+)."""
    if not age:
        return ""
    return f"{int(age)} years old"


def hair_phrase(hair_style, hair_color) -> str:
    """Combine hair color + style, e.g. 'blonde long straight hair'."""
    color = phrase(HAIR_COLOR_PHRASES, hair_color)
    style = phrase(HAIR_STYLE_PHRASES, hair_style)
    if color and style:
        # Insert color before the noun 'hair' in the style phrase.
        return style.replace("hair", f"{color} hair", 1)
    return style or (f"{color} hair" if color else "")


def kinks_phrase(kinks) -> str:
    """Join up to 3 kink mood phrases."""
    if not kinks:
        return ""
    parts = [phrase(KINK_PHRASES, k) for k in kinks]
    return ", ".join(p for p in parts if p)
