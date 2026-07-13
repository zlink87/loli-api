"""
Culture / subculture vocabulary — single source of truth for CultureType content.

One CultureSpec per CultureType member, bundling the character's styling render
phrase, the wardrobe / outfit / location / pose biases it steers toward, its home
interior style + palette, default demeanor, and LLM persona flavor (a one-line fact
plus likes/dislikes). Later stages (prompt/writer/batch wiring) read from HERE — this
module owns every per-culture datum so a new culture is added in exactly one place.

Imports ONLY models.enums (no other service), so it stays a leaf vocabulary module
like attribute_phrases / scene_vocab.

RENDER-PHRASE contract (follows ETHNICITY_PHRASES in services/attribute_phrases.py):
each `render_phrase` describes MAKEUP + styling/jewelry ONLY. It must NEVER name
hair color/texture, eye color, skin tone, an age-down word, a banned glamour-filler
word (see prompt_constants.has_banned_style_words), or a concrete garment noun —
clothing is owned by the outfit clause, and hair/eyes/skin/age are owned by the
character's own persona fields, which a culture phrase must not fight. The hygiene
invariants are enforced by tests/test_culture_vocab.py.

All accessors are tolerant: they accept an enum member or its raw string value
(case / whitespace / underscore normalized, like attribute_phrases.skin_tone_phrase)
and degrade to ""/empty/None on unknown or None input — never raising.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from models.enums import (
    CultureType,
    WardrobeStyleType,
    OutfitType,
    LocationType,
    PoseType,
    InteriorStyleType,
    PaletteType,
    DemeanorType,
)


@dataclass(frozen=True)
class CultureSpec:
    """Everything the app knows about one culture (see module docstring)."""
    label: str                              # human display label
    render_phrase: str                      # makeup/styling clause (hygiene-tested)
    wardrobe_styles: frozenset              # WardrobeStyleType, 1-3
    favored_outfits: frozenset              # OutfitType, never NAKED
    favored_locations: frozenset            # LocationType
    interior_style: InteriorStyleType       # a key of scene_vocab.INTERIOR_ROOM_PHRASES
    color_palette: PaletteType              # a key of scene_vocab.PALETTE_PHRASES
    demeanor: tuple                         # 1-2 DemeanorType
    persona_hint: str                       # one LLM fact line
    likes: tuple                            # short interest strings
    dislikes: tuple = ()
    favored_poses: frozenset = field(default_factory=frozenset)  # PoseType


CULTURE_SPECS: Dict[CultureType, CultureSpec] = {
    CultureType.GOTH: CultureSpec(
        label="Goth",
        render_phrase=(
            "goth styling, matte complexion makeup, dramatic black winged eyeliner, "
            "smoky charcoal shadow, deep plum-black lipstick, dark nail polish, and silver jewelry"
        ),
        wardrobe_styles=frozenset({WardrobeStyleType.EDGY, WardrobeStyleType.GLAMOROUS}),
        favored_outfits=frozenset({
            OutfitType.VELVET_DRESS, OutfitType.LEATHER_JACKET, OutfitType.LACE_BODYSUIT,
            OutfitType.LITTLE_BLACK_DRESS, OutfitType.SATIN_SLIP_DRESS,
        }),
        favored_locations=frozenset({
            LocationType.BAR, LocationType.NIGHTCLUB, LocationType.HOME_BEDROOM, LocationType.CITY_STREET,
        }),
        interior_style=InteriorStyleType.INDUSTRIAL_LOFT,
        color_palette=PaletteType.BOLD_DARK,
        demeanor=(DemeanorType.MYSTERIOUS, DemeanorType.SULTRY),
        persona_hint="she is goth — dark romantic aesthetic, alternative music, candlelit nights and vintage horror",
        likes=("gothic rock", "horror films", "candlelit rooms", "old cemeteries", "dark poetry"),
        dislikes=("bright daylight", "small talk"),
    ),
    CultureType.PUNK: CultureSpec(
        label="Punk",
        render_phrase=(
            "punk styling, bold smudged black eyeliner, dark matte lips, "
            "studded and safety-pin accessories, and chipped dark nail polish"
        ),
        wardrobe_styles=frozenset({WardrobeStyleType.EDGY, WardrobeStyleType.STREETWEAR}),
        favored_outfits=frozenset({
            OutfitType.LEATHER_JACKET, OutfitType.GRAPHIC_TEE_SHORTS,
            OutfitType.DENIM_JACKET_JEANS, OutfitType.CROP_TOP_CARGO,
        }),
        favored_locations=frozenset({
            LocationType.CITY_STREET, LocationType.BAR, LocationType.ROOFTOP, LocationType.NIGHTCLUB,
        }),
        interior_style=InteriorStyleType.INDUSTRIAL_LOFT,
        color_palette=PaletteType.BOLD_DARK,
        demeanor=(DemeanorType.CONFIDENT, DemeanorType.ENERGETIC),
        persona_hint="she is punk — DIY rebellion, mosh pits, loud guitars and anti-establishment attitude",
        likes=("punk gigs", "vinyl records", "DIY zines", "skateboarding"),
        dislikes=("authority", "conformity"),
    ),
    CultureType.E_GIRL: CultureSpec(
        label="E-Girl",
        render_phrase=(
            "e-girl styling, heavy winged eyeliner, rosy blush swept across the nose, "
            "glossy lips, and layered chain necklaces"
        ),
        wardrobe_styles=frozenset({WardrobeStyleType.EDGY, WardrobeStyleType.GIRLY}),
        favored_outfits=frozenset({
            OutfitType.CROP_TOP_CARGO, OutfitType.GRAPHIC_TEE_SHORTS,
            OutfitType.HOODIE_JOGGERS, OutfitType.OVERSIZED_STREETWEAR,
        }),
        favored_locations=frozenset({
            LocationType.HOME_BEDROOM, LocationType.CITY_STREET, LocationType.CAFE,
        }),
        interior_style=InteriorStyleType.ARTSY_ECLECTIC,
        color_palette=PaletteType.JEWEL_TONES,
        demeanor=(DemeanorType.PLAYFUL, DemeanorType.SHY),
        persona_hint="she is an e-girl — extremely online, gaming streams, anime edits and late-night group calls",
        likes=("gaming streams", "anime", "video edits", "energy drinks", "K-pop"),
        dislikes=("early mornings",),
    ),
    CultureType.GRUNGE: CultureSpec(
        label="Grunge",
        render_phrase=(
            "grunge styling, smudged undone eyeliner, matte complexion makeup, "
            "muted nude lips, and stacked layered rings"
        ),
        wardrobe_styles=frozenset({WardrobeStyleType.EDGY, WardrobeStyleType.CASUAL_MINIMAL}),
        favored_outfits=frozenset({
            OutfitType.FLANNEL_SHIRT, OutfitType.DENIM_JACKET_JEANS,
            OutfitType.GRAPHIC_TEE_SHORTS, OutfitType.LEATHER_JACKET,
        }),
        favored_locations=frozenset({
            LocationType.CITY_STREET, LocationType.BAR, LocationType.HOME_LIVING_ROOM, LocationType.PARK,
        }),
        interior_style=InteriorStyleType.INDUSTRIAL_LOFT,
        color_palette=PaletteType.EARTHY_GREEN,
        demeanor=(DemeanorType.CONFIDENT, DemeanorType.COZY),
        persona_hint="she is grunge — 90s slacker cool, thrifted layers, garage bands and rainy-day playlists",
        likes=("90s alt-rock", "thrift shopping", "coffee shops", "film photography"),
        dislikes=("fast fashion",),
    ),
    CultureType.Y2K: CultureSpec(
        label="Y2K",
        render_phrase=(
            "Y2K styling, frosted glossy lips, shimmering pastel eyeshadow, "
            "playful body glitter, and butterfly clips as sparkly accents"
        ),
        wardrobe_styles=frozenset({WardrobeStyleType.GIRLY, WardrobeStyleType.GLAMOROUS}),
        favored_outfits=frozenset({
            OutfitType.CROP_TOP_CARGO, OutfitType.SEQUIN_TOP_SKIRT,
            OutfitType.BODYCON_DRESS, OutfitType.GRAPHIC_TEE_SHORTS,
        }),
        favored_locations=frozenset({
            LocationType.NIGHTCLUB, LocationType.CITY_STREET, LocationType.POOLSIDE, LocationType.CAFE,
        }),
        interior_style=InteriorStyleType.GIRLY_PASTEL,
        color_palette=PaletteType.SOFT_PASTELS,
        demeanor=(DemeanorType.PLAYFUL, DemeanorType.CONFIDENT),
        persona_hint="she is Y2K — early-2000s pop nostalgia, flip phones, glitter and bubblegum club tracks",
        likes=("pop nostalgia", "roller rinks", "flip phones", "glitter", "bubblegum pop"),
    ),
    CultureType.COTTAGECORE: CultureSpec(
        label="Cottagecore",
        render_phrase=(
            "cottagecore styling, fresh natural makeup, soft rosy cheeks, a dewy luminous finish, "
            "a hint of mascara, and delicate floral accents"
        ),
        wardrobe_styles=frozenset({WardrobeStyleType.BOHEMIAN, WardrobeStyleType.GIRLY}),
        favored_outfits=frozenset({
            OutfitType.FLORAL_MAXI_DRESS, OutfitType.WHITE_SUMMER_DRESS, OutfitType.POLKA_DOT_DRESS_50S,
        }),
        favored_locations=frozenset({
            LocationType.GARDEN, LocationType.FOREST_TRAIL, LocationType.PARK, LocationType.HOME_KITCHEN,
        }),
        interior_style=InteriorStyleType.RUSTIC_WARM,
        color_palette=PaletteType.EARTHY_GREEN,
        demeanor=(DemeanorType.COZY, DemeanorType.SHY),
        persona_hint="she is cottagecore — slow rural living, baking bread, wildflower foraging and handwritten letters",
        likes=("baking", "gardening", "wildflower picking", "reading by the window", "herbal tea"),
        dislikes=("city noise",),
        favored_poses=frozenset({PoseType.SITTING, PoseType.EATING, PoseType.COOKING}),
    ),
    CultureType.DARK_ACADEMIA: CultureSpec(
        label="Dark Academia",
        render_phrase=(
            "dark academia styling, understated matte makeup, soft brown eyeshadow, "
            "muted rosewood lips, and subtle antique gold jewelry"
        ),
        wardrobe_styles=frozenset({WardrobeStyleType.ELEGANT, WardrobeStyleType.PROFESSIONAL}),
        favored_outfits=frozenset({
            OutfitType.BLAZER_TROUSERS, OutfitType.PENCIL_SKIRT_SET,
            OutfitType.TRENCH_COAT, OutfitType.BUSINESS_SUIT,
        }),
        favored_locations=frozenset({
            LocationType.LIBRARY, LocationType.CLASSROOM, LocationType.CAFE, LocationType.CITY_STREET,
        }),
        interior_style=InteriorStyleType.ARTSY_ECLECTIC,
        color_palette=PaletteType.WARM_NEUTRALS,
        demeanor=(DemeanorType.ELEGANT, DemeanorType.MYSTERIOUS),
        persona_hint="she is dark academia — old libraries, classic literature, black coffee and candlelit study",
        likes=("classic literature", "museum visits", "black coffee", "handwritten notes", "chess"),
        dislikes=("loud parties",),
    ),
    CultureType.OLD_MONEY: CultureSpec(
        label="Old Money",
        render_phrase=(
            "old-money styling, polished natural makeup, soft neutral tones, a refined matte finish, "
            "understated lips, and classic pearl jewelry"
        ),
        wardrobe_styles=frozenset({WardrobeStyleType.ELEGANT, WardrobeStyleType.GLAMOROUS}),
        favored_outfits=frozenset({
            OutfitType.BLAZER_TROUSERS, OutfitType.COCKTAIL_DRESS,
            OutfitType.TRENCH_COAT, OutfitType.TENNIS_OUTFIT,
        }),
        favored_locations=frozenset({
            LocationType.LUXURY_LOUNGE, LocationType.RESTAURANT, LocationType.POOLSIDE, LocationType.GARDEN,
        }),
        interior_style=InteriorStyleType.LUXURY_GLAM,
        color_palette=PaletteType.CRISP_WHITE,
        demeanor=(DemeanorType.ELEGANT, DemeanorType.CONFIDENT),
        persona_hint="she is old money — quiet luxury, tennis club afternoons, heirloom pearls and understated taste",
        likes=("tennis", "sailing", "fine dining", "art galleries", "horseback riding"),
        dislikes=("flashy logos",),
    ),
    CultureType.STREETWEAR_BADDIE: CultureSpec(
        label="Streetwear Baddie",
        render_phrase=(
            "streetwear baddie styling, sculpted defined brows, long dramatic lashes, glossy nude lips, "
            "gold hoop earrings, and long manicured nails"
        ),
        wardrobe_styles=frozenset({WardrobeStyleType.STREETWEAR, WardrobeStyleType.GLAMOROUS}),
        favored_outfits=frozenset({
            OutfitType.OVERSIZED_STREETWEAR, OutfitType.BOMBER_JACKET_FIT,
            OutfitType.CROP_TOP_CARGO, OutfitType.BODYCON_DRESS,
        }),
        favored_locations=frozenset({
            LocationType.CITY_STREET, LocationType.ROOFTOP, LocationType.NIGHTCLUB, LocationType.CAR_INTERIOR,
        }),
        interior_style=InteriorStyleType.MODERN_MINIMAL,
        color_palette=PaletteType.BOLD_DARK,
        demeanor=(DemeanorType.CONFIDENT, DemeanorType.SULTRY),
        persona_hint="she is a streetwear baddie — hype sneakers, confident selfies, city nightlife and bold self-styling",
        likes=("sneaker drops", "hip-hop", "city nightlife", "photography"),
        dislikes=("dress codes",),
    ),
    CultureType.KAWAII_HARAJUKU: CultureSpec(
        label="Kawaii Harajuku",
        render_phrase=(
            "kawaii Harajuku styling, doll-like rounded blush, glittery pastel eyeshadow, "
            "glossy pink lips, and colorful playful clips"
        ),
        wardrobe_styles=frozenset({WardrobeStyleType.GIRLY, WardrobeStyleType.STREETWEAR}),
        favored_outfits=frozenset({
            OutfitType.SEQUIN_TOP_SKIRT, OutfitType.GRAPHIC_TEE_SHORTS,
            OutfitType.WHITE_SUMMER_DRESS, OutfitType.CROP_TOP_CARGO,
        }),
        favored_locations=frozenset({
            LocationType.CAFE, LocationType.CITY_STREET, LocationType.HOME_BEDROOM, LocationType.PARK,
        }),
        interior_style=InteriorStyleType.GIRLY_PASTEL,
        color_palette=PaletteType.SOFT_PASTELS,
        demeanor=(DemeanorType.PLAYFUL, DemeanorType.ENERGETIC),
        persona_hint="she is kawaii Harajuku — pastel cuteness, plushies, bubble tea and playful street fashion",
        likes=("bubble tea", "plush toys", "cute cafes", "sticker collecting", "arcades"),
    ),
    CultureType.GYARU: CultureSpec(
        label="Gyaru",
        render_phrase=(
            "gyaru styling, dramatic false lashes, sharply contoured nose, glossy nude lips, "
            "and long decorated nails"
        ),
        wardrobe_styles=frozenset({WardrobeStyleType.GLAMOROUS, WardrobeStyleType.GIRLY}),
        favored_outfits=frozenset({
            OutfitType.BODYCON_DRESS, OutfitType.SEQUIN_TOP_SKIRT,
            OutfitType.BIKINI, OutfitType.COCKTAIL_DRESS,
        }),
        favored_locations=frozenset({
            LocationType.NIGHTCLUB, LocationType.BEACH, LocationType.CITY_STREET, LocationType.SALON,
        }),
        interior_style=InteriorStyleType.LUXURY_GLAM,
        color_palette=PaletteType.JEWEL_TONES,
        demeanor=(DemeanorType.CONFIDENT, DemeanorType.PLAYFUL),
        persona_hint="she is gyaru — bold glam confidence, karaoke nights, purikura and unapologetic self-expression",
        likes=("karaoke", "photo booths", "shopping", "nail art", "clubbing"),
        dislikes=("dull routines",),
    ),
    CultureType.BOHO_HIPPIE: CultureSpec(
        label="Boho Hippie",
        render_phrase=(
            "boho hippie styling, natural glowing makeup, softly flushed cheeks, "
            "layered beaded necklaces, stacked bracelets, and delicate anklets"
        ),
        wardrobe_styles=frozenset({WardrobeStyleType.BOHEMIAN}),
        favored_outfits=frozenset({
            OutfitType.BELL_BOTTOMS_70S, OutfitType.FLORAL_MAXI_DRESS,
            OutfitType.WHITE_SUMMER_DRESS, OutfitType.KIMONO,
        }),
        favored_locations=frozenset({
            LocationType.BEACH, LocationType.PARK, LocationType.FOREST_TRAIL, LocationType.GARDEN,
        }),
        interior_style=InteriorStyleType.COZY_BOHEMIAN,
        color_palette=PaletteType.EARTHY_GREEN,
        demeanor=(DemeanorType.COZY, DemeanorType.PLAYFUL),
        persona_hint="she is boho hippie — free-spirited wandering, festivals, crystals and barefoot beach sunsets",
        likes=("music festivals", "beach bonfires", "yoga", "crystals", "road trips"),
        dislikes=("rigid schedules",),
    ),
    CultureType.PINUP_ROCKABILLY: CultureSpec(
        label="Pinup Rockabilly",
        render_phrase=(
            "pinup rockabilly styling, matte red lips, sharp winged eyeliner, "
            "boldly defined brows, and a signature beauty mark"
        ),
        wardrobe_styles=frozenset({WardrobeStyleType.GLAMOROUS, WardrobeStyleType.GIRLY}),
        favored_outfits=frozenset({
            OutfitType.POLKA_DOT_DRESS_50S, OutfitType.PENCIL_SKIRT_SET,
            OutfitType.ONE_PIECE_SWIMSUIT, OutfitType.LITTLE_BLACK_DRESS,
        }),
        favored_locations=frozenset({
            LocationType.BAR, LocationType.POOLSIDE, LocationType.PHOTO_STUDIO, LocationType.HOME_KITCHEN,
        }),
        interior_style=InteriorStyleType.ARTSY_ECLECTIC,
        color_palette=PaletteType.JEWEL_TONES,
        demeanor=(DemeanorType.PLAYFUL, DemeanorType.SULTRY),
        persona_hint="she is pinup rockabilly — retro 50s glamour, vintage cars, swing dancing and vinyl records",
        likes=("swing dancing", "vintage cars", "vinyl records", "retro diners"),
        dislikes=("modern minimalism",),
        favored_poses=frozenset({PoseType.STANDING_LEANING, PoseType.KNEELING}),
    ),
    CultureType.ROCKER_BIKER: CultureSpec(
        label="Rocker Biker",
        render_phrase=(
            "rocker biker styling, smoky charcoal eyeshadow, bold defined liner, "
            "studded metal accessories, and dark nail polish"
        ),
        wardrobe_styles=frozenset({WardrobeStyleType.EDGY}),
        favored_outfits=frozenset({
            OutfitType.LEATHER_JACKET, OutfitType.DENIM_JACKET_JEANS,
            OutfitType.GRAPHIC_TEE_SHORTS, OutfitType.LITTLE_BLACK_DRESS,
        }),
        favored_locations=frozenset({
            LocationType.BAR, LocationType.NIGHTCLUB, LocationType.STAGE, LocationType.CITY_STREET,
        }),
        interior_style=InteriorStyleType.INDUSTRIAL_LOFT,
        color_palette=PaletteType.BOLD_DARK,
        demeanor=(DemeanorType.CONFIDENT, DemeanorType.SULTRY),
        persona_hint="she is a rocker biker — open-road freedom, live gigs, motorcycles and rebellious swagger",
        likes=("live rock shows", "motorcycles", "road trips", "whiskey bars"),
        dislikes=("quiet nights in",),
    ),
    CultureType.RAVE_FESTIVAL: CultureSpec(
        label="Rave Festival",
        render_phrase=(
            "rave festival styling, iridescent highlighter, glitter on the cheekbones, "
            "neon eyeliner accents, and rhinestone details"
        ),
        wardrobe_styles=frozenset({
            WardrobeStyleType.STREETWEAR, WardrobeStyleType.SPORTY, WardrobeStyleType.GIRLY,
        }),
        favored_outfits=frozenset({
            OutfitType.SEQUIN_TOP_SKIRT, OutfitType.CROP_TOP_CARGO,
            OutfitType.BIKINI, OutfitType.BODYCON_DRESS,
        }),
        favored_locations=frozenset({
            LocationType.NIGHTCLUB, LocationType.STAGE, LocationType.ROOFTOP, LocationType.POOLSIDE,
        }),
        interior_style=InteriorStyleType.ARTSY_ECLECTIC,
        color_palette=PaletteType.JEWEL_TONES,
        demeanor=(DemeanorType.ENERGETIC, DemeanorType.PLAYFUL),
        persona_hint="she is rave festival — all-night dancing, EDM drops, neon lights and boundless energy",
        likes=("EDM festivals", "light shows", "dancing", "neon fashion", "afterparties"),
        dislikes=("sitting still",),
    ),
    CultureType.SPORTY_GYM: CultureSpec(
        label="Sporty Gym",
        render_phrase=(
            "sporty gym styling, fresh-faced minimal makeup, softly defined brows, "
            "a natural dewy finish, and tinted lip balm"
        ),
        wardrobe_styles=frozenset({WardrobeStyleType.SPORTY}),
        favored_outfits=frozenset({
            OutfitType.GYM_SET, OutfitType.YOGA_OUTFIT,
            OutfitType.RUNNING_GEAR, OutfitType.TENNIS_OUTFIT,
        }),
        favored_locations=frozenset({
            LocationType.GYM, LocationType.YOGA_STUDIO, LocationType.PARK, LocationType.POOLSIDE,
        }),
        interior_style=InteriorStyleType.MODERN_MINIMAL,
        color_palette=PaletteType.CRISP_WHITE,
        demeanor=(DemeanorType.ENERGETIC, DemeanorType.CONFIDENT),
        persona_hint="she is sporty gym — early workouts, protein smoothies, personal-best chasing and active outdoors",
        likes=("weight training", "morning runs", "smoothies", "hiking", "yoga"),
        dislikes=("junk food",),
        favored_poses=frozenset({PoseType.JOGGING, PoseType.SQUATTING}),
    ),
}


def _coerce_culture(v) -> Optional[CultureType]:
    """
    Coerce an enum member or raw value to a CultureType, tolerant of
    case / surrounding whitespace / hyphen-vs-underscore. None / unknown -> None
    (never raises), so a garbage or future stored value degrades to "no culture".
    """
    if v is None:
        return None
    if isinstance(v, CultureType):
        return v
    key = str(getattr(v, "value", v)).strip().lower().replace("-", "_").replace(" ", "_")
    try:
        return CultureType(key)
    except (ValueError, TypeError):
        return None


def spec_for(culture) -> Optional[CultureSpec]:
    """The CultureSpec for a culture (enum or value), or None when unknown/None."""
    c = _coerce_culture(culture)
    if c is None:
        return None
    return CULTURE_SPECS.get(c)


def culture_render_phrase(culture) -> str:
    """The makeup/styling render clause for a culture; "" when unknown/None."""
    spec = spec_for(culture)
    return spec.render_phrase if spec else ""


def culture_wardrobe_styles(culture) -> Set[WardrobeStyleType]:
    """The culture's biased WardrobeStyleType set; empty when unknown/None."""
    spec = spec_for(culture)
    return set(spec.wardrobe_styles) if spec else set()


def culture_favored_outfits(culture) -> Set[OutfitType]:
    """The culture's favored OutfitType set (never NAKED); empty when unknown/None."""
    spec = spec_for(culture)
    return set(spec.favored_outfits) if spec else set()


def culture_favored_locations(culture) -> Set[LocationType]:
    """The culture's favored LocationType set; empty when unknown/None."""
    spec = spec_for(culture)
    return set(spec.favored_locations) if spec else set()


def culture_favored_poses(culture) -> Set[PoseType]:
    """The culture's favored PoseType set (often empty by design); empty when unknown/None."""
    spec = spec_for(culture)
    return set(spec.favored_poses) if spec else set()


def culture_interior_style(culture) -> Optional[InteriorStyleType]:
    """The culture's home InteriorStyleType, or None when unknown/None."""
    spec = spec_for(culture)
    return spec.interior_style if spec else None


def culture_color_palette(culture) -> Optional[PaletteType]:
    """The culture's home PaletteType, or None when unknown/None."""
    spec = spec_for(culture)
    return spec.color_palette if spec else None


def culture_demeanor(culture) -> List[DemeanorType]:
    """The culture's 1-2 default DemeanorType(s) as a list; empty when unknown/None."""
    spec = spec_for(culture)
    return list(spec.demeanor) if spec else []


def culture_hint(culture) -> str:
    """
    A one-line LLM fact for the culture, formatted "<Label> — <persona_hint>";
    "" when unknown/None.
    """
    spec = spec_for(culture)
    return f"{spec.label} — {spec.persona_hint}" if spec else ""


def culture_label(culture) -> str:
    """The human display label for a culture; "" when unknown/None."""
    spec = spec_for(culture)
    return spec.label if spec else ""
