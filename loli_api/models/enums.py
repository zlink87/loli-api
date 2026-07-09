"""
Enum definitions for the Character Image Generation API.
Based on BE-AI-Tasks.docx specifications.
"""
from enum import Enum


class NudityLevel(str, Enum):
    """
    Nudity level for outfit editing — a 5-level ladder, ordered least to most
    explicit: LOW < SUGGESTIVE < MEDIUM < REVEALING < HIGH.

    The low/medium/high string values are unchanged from the original 3-level
    scheme for back-compat (existing stored jsonb/controls still parse as-is);
    SUGGESTIVE and REVEALING are additive values slotted between them.
    """
    LOW = "low"                # fully clothed
    SUGGESTIVE = "suggestive"  # clothed but teasing: tight/short, cleavage, hint of skin
    MEDIUM = "medium"          # partial nudity: unbuttoned/lingerie, some exposure
    REVEALING = "revealing"    # mostly nude: largely exposed, covering little
    HIGH = "high"              # full nudity


class JobStatus(str, Enum):
    """Job processing status."""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StyleType(str, Enum):
    """Visual style for character generation."""
    REALISTIC = "realistic"
    ANIME = "anime"


class EthnicityType(str, Enum):
    """Character ethnicity options."""
    CAUCASIAN = "caucasian"
    ASIAN = "asian"
    BLACK_AFRO = "black_afro"
    LATINA = "latina"
    ARAB = "arab"


class HairStyleType(str, Enum):
    """Hair style options."""
    STRAIGHT = "straight"
    BANGS = "bangs"
    CURLY = "curly"
    BUN = "bun"
    SHORT = "short"
    PONYTAIL = "ponytail"


class HairColorType(str, Enum):
    """Hair color options."""
    BRUNETTE = "brunette"
    BLONDE = "blonde"
    BLACK = "black"
    REDHEAD = "redhead"
    PINK = "pink"


class EyeColorType(str, Enum):
    """Eye color options."""
    BROWN = "brown"
    BLUE = "blue"
    GREEN = "green"


class BodyType(str, Enum):
    """Body type options."""
    SKINNY = "skinny"
    ATHLETIC = "athletic"
    AVERAGE = "average"
    CURVY = "curvy"
    BBW = "bbw"


class BreastSize(str, Enum):
    """Breast size options."""
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    EXTRA_LARGE = "extra_large"


class PersonalityType(str, Enum):
    """Personality options."""
    NYMPHO = "nympho"
    LOVER = "lover"
    SUBMISSIVE = "submissive"
    DOMINANT = "dominant"
    TEMPTRESS = "temptress"
    INNOCENT = "innocent"
    CAREGIVER = "caregiver"
    EXPERIMENTER = "experimenter"
    MEAN = "mean"
    CONFIDANT = "confidant"
    SHY = "shy"
    QUEEN = "queen"


class RelationshipType(str, Enum):
    """Relationship options."""
    STRANGER = "stranger"
    GIRLFRIEND = "girlfriend"
    SEX_FRIEND = "sex_friend"
    SCHOOL_MATE = "school_mate"
    WORK_COLLEAGUE = "work_colleague"
    WIFE = "wife"
    MISTRESS = "mistress"
    FRIEND = "friend"
    STEP_SISTER = "step_sister"
    STEP_MOM = "step_mom"
    STEP_DAUGHTER = "step_daughter"
    LANDLORD = "landlord"
    SUGAR_BABY = "sugar_baby"
    BOSS = "boss"
    TEACHER = "teacher"
    STUDENT = "student"
    NEIGHBOUR = "neighbour"
    MOTHER_IN_LAW = "mother_in_law"
    SISTER_IN_LAW = "sister_in_law"


class OccupationType(str, Enum):
    """Occupation options."""
    STUDENT = "student"
    DANCER = "dancer"
    MODEL = "model"
    STRIPPER = "stripper"
    MAID = "maid"
    CAM_GIRL = "cam_girl"
    BOSS_CEO = "boss_ceo"
    BABYSITTER_AU_PAIR = "babysitter_au_pair"
    PORNSTAR = "pornstar"
    STREAMER = "streamer"
    BARTENDER = "bartender"
    TECH_ENGINEER = "tech_engineer"
    LIFEGUARD = "lifeguard"
    CASHIER = "cashier"
    MASSAGE_THERAPIST = "massage_therapist"
    NURSE = "nurse"
    SECRETARY = "secretary"
    YOGA_INSTRUCTOR = "yoga_instructor"
    FITNESS_COACH = "fitness_coach"
    COOK = "cook"
    ARTIST = "artist"
    MOVIE_STAR_ACTRESS = "movie_star_actress"
    DOCTOR = "doctor"
    LIBRARIAN = "librarian"
    SPY = "spy"
    POLICE_OFFICER = "police_officer"
    SOLDIER = "soldier"
    LAWYER = "lawyer"
    HAIRDRESSER = "hairdresser"
    DENTIST = "dentist"
    SINGER_MUSICIAN = "singer_musician"
    GYNECOLOGIST = "gynecologist"
    WRITER = "writer"
    FLIGHT_ATTENDANT = "flight_attendant"
    PROFESSIONAL_ATHLETE = "professional_athlete"
    SCIENTIST = "scientist"
    FLORIST = "florist"
    MAKEUP_ARTIST = "makeup_artist"
    PHOTOGRAPHER = "photographer"
    SOCIAL_WORKER = "social_worker"
    DESIGNER = "designer"
    PHARMACIST = "pharmacist"
    NUTRITIONIST = "nutritionist"


class KinkType(str, Enum):
    """Kink options (max 3 can be selected)."""
    BONDAGE = "bondage"
    SPANKING = "spanking"
    COLLAR_LEASH = "collar_leash"
    PUNISHMENT = "punishment"
    HUMILIATION = "humiliation"
    PUBLIC_PLAY = "public_play"
    ROLEPLAY = "roleplay"
    ANAL_PLAY = "anal_play"
    ORAL_PLAY = "oral_play"
    CUM_PLAY = "cum_play"
    CREAMPIE = "creampie"
    SQUIRTING = "squirting"
    DIRTY_TALK = "dirty_talk"
    BREEDING = "breeding"
    EDGING = "edging"
    OBEDIENCE = "obedience"
    CONTROL = "control"
    INEXPERIENCED = "inexperienced"
    SHY_FLIRTING = "shy_flirting"
    PLAYFUL_TEASING = "playful_teasing"
    CUDDLING = "cuddling"
    SLOW_SENSUAL = "slow_sensual"
    HAIR_PULLING = "hair_pulling"


class OutfitType(str, Enum):
    """Available outfit types for outfit editing."""
    RED_EVENING_GOWN = "red_evening_gown"
    LITTLE_BLACK_DRESS = "little_black_dress"
    WHITE_SUMMER_DRESS = "white_summer_dress"
    FLORAL_MAXI_DRESS = "floral_maxi_dress"
    COCKTAIL_DRESS = "cocktail_dress"
    BODYCON_DRESS = "bodycon_dress"
    BUSINESS_SUIT = "business_suit"
    BLAZER_TROUSERS = "blazer_trousers"
    PENCIL_SKIRT_SET = "pencil_skirt_set"
    TUXEDO = "tuxedo"
    DENIM_JACKET_JEANS = "denim_jacket_jeans"
    GRAPHIC_TEE_SHORTS = "graphic_tee_shorts"
    HOODIE_JOGGERS = "hoodie_joggers"
    FLANNEL_SHIRT = "flannel_shirt"
    CROP_TOP_CARGO = "crop_top_cargo"
    YOGA_OUTFIT = "yoga_outfit"
    TENNIS_OUTFIT = "tennis_outfit"
    RUNNING_GEAR = "running_gear"
    GYM_SET = "gym_set"
    ONE_PIECE_SWIMSUIT = "one_piece_swimsuit"
    BIKINI = "bikini"
    LEATHER_JACKET = "leather_jacket"
    TRENCH_COAT = "trench_coat"
    PUFFER_JACKET = "puffer_jacket"
    FUR_COAT = "fur_coat"
    KIMONO = "kimono"
    SARI = "sari"
    CHEONGSAM = "cheongsam"
    HANBOK = "hanbok"
    DIRNDL = "dirndl"
    SEQUIN_TOP_SKIRT = "sequin_top_skirt"
    VELVET_DRESS = "velvet_dress"
    SATIN_SLIP_DRESS = "satin_slip_dress"
    JUMPSUIT = "jumpsuit"
    POLKA_DOT_DRESS_50S = "polka_dot_dress_50s"
    BELL_BOTTOMS_70S = "bell_bottoms_70s"
    POWER_SUIT_80S = "power_suit_80s"
    SILK_PAJAMAS = "silk_pajamas"
    LACE_BODYSUIT = "lace_bodysuit"
    SATIN_ROBE = "satin_robe"
    OVERSIZED_STREETWEAR = "oversized_streetwear"
    BOMBER_JACKET_FIT = "bomber_jacket_fit"
    NURSE_UNIFORM = "nurse_uniform"
    SCHOOL_UNIFORM = "school_uniform"
    MILITARY_UNIFORM = "military_uniform"
    CHEF_UNIFORM = "chef_uniform"
    NAKED = "naked"


class PoseType(str, Enum):
    """Available pose types for pose editing."""
    STANDING_LEANING = "standing_leaning"
    SITTING = "sitting"
    SITTING_LEGS_WIDE_OPEN = "sitting_legs_wide_open"
    SOFA = "sofa"
    LYING_BACK = "lying_back"
    LYING_STOMACH = "lying_stomach"
    KNEELING = "kneeling"
    BENDING_OVER = "bending_over"
    HANDS_BEHIND_HEAD = "hands_behind_head"
    SQUATTING = "squatting"
    ALL_FOURS = "all_fours"
    SPREAD_LEGS = "spread_legs"
    EATING = "eating"
    JOGGING = "jogging"
    OPENING_FRIDGE = "opening_fridge"
    COOKING = "cooking"


class MotionType(str, Enum):
    """Available motion presets for image-to-video (reel) generation."""
    SUBTLE_IDLE = "subtle_idle"
    SLOW_TURN = "slow_turn"
    HAIR_IN_WIND = "hair_in_wind"
    HAIR_FLIP = "hair_flip"
    BLOW_KISS = "blow_kiss"
    WAVE = "wave"
    WALK_TOWARD = "walk_toward"
    LOOK_OVER_SHOULDER = "look_over_shoulder"


class AccessoryType(str, Enum):
    """Available accessory types for outfit editing."""
    NECKLACE = "necklace"
    EARRINGS = "earrings"
    GLASSES = "glasses"
    HAT = "hat"
    SUNGLASSES = "sunglasses"


# ---------------------------------------------------------------------------
# Structured scene vocabulary (Story Batches)
# Used by the story planner to compose coherent, controllable backgrounds.
# Each value has a descriptive phrase in services/attribute_phrases.py.
# ---------------------------------------------------------------------------
class LocationType(str, Enum):
    """Where a scene takes place."""
    # --- home ---
    HOME_BEDROOM = "home_bedroom"
    HOME_LIVING_ROOM = "home_living_room"
    HOME_KITCHEN = "home_kitchen"
    HOME_BATHROOM = "home_bathroom"
    HOME_BALCONY = "home_balcony"
    HOME_OFFICE = "home_office"
    # --- workplace (profession-linked) ---
    OFFICE = "office"
    HOSPITAL_WARD = "hospital_ward"
    CLASSROOM = "classroom"
    PHOTO_STUDIO = "photo_studio"
    GYM = "gym"
    YOGA_STUDIO = "yoga_studio"
    RESTAURANT_KITCHEN = "restaurant_kitchen"
    LIBRARY = "library"
    SALON = "salon"
    STAGE = "stage"
    LAB = "lab"
    # --- outdoors ---
    BEACH = "beach"
    PARK = "park"
    CITY_STREET = "city_street"
    FOREST_TRAIL = "forest_trail"
    ROOFTOP = "rooftop"
    POOLSIDE = "poolside"
    GARDEN = "garden"
    # --- social venues ---
    CAFE = "cafe"
    RESTAURANT = "restaurant"
    BAR = "bar"
    NIGHTCLUB = "nightclub"
    HOTEL_ROOM = "hotel_room"
    LUXURY_LOUNGE = "luxury_lounge"
    CAR_INTERIOR = "car_interior"


class TimeOfDayType(str, Enum):
    """Time of day for a scene."""
    EARLY_MORNING = "early_morning"
    MORNING = "morning"
    DAYTIME = "daytime"
    GOLDEN_HOUR = "golden_hour"
    SUNSET = "sunset"
    EVENING = "evening"
    NIGHT = "night"


class LightingType(str, Enum):
    """Lighting style for a scene."""
    NATURAL_SOFT = "natural_soft"
    BRIGHT_DAYLIGHT = "bright_daylight"
    GOLDEN_WARM = "golden_warm"
    MOODY_DIM = "moody_dim"
    NEON = "neon"
    CANDLELIT = "candlelit"
    STUDIO_SOFTBOX = "studio_softbox"
    BACKLIT_RIM = "backlit_rim"
    OVERCAST = "overcast"


# ---------------------------------------------------------------------------
# Camera / shot vocabulary (hero-shot generation)
# Controls framing, angle, expression and photographic finish of generated
# character images. Each value has a phrase in services/camera_vocab.py.
# ---------------------------------------------------------------------------
class ShotFramingType(str, Enum):
    """How much of the subject is in frame."""
    PORTRAIT_CLOSEUP = "portrait_closeup"
    CHEST_UP = "chest_up"
    WAIST_UP = "waist_up"          # hero-shot default
    THREE_QUARTER = "three_quarter"
    FULL_BODY = "full_body"        # legacy default behavior
    SELFIE = "selfie"


class CameraAngleType(str, Enum):
    """Camera position relative to the subject."""
    EYE_LEVEL = "eye_level"        # default
    HIGH_ANGLE = "high_angle"
    LOW_ANGLE = "low_angle"
    THREE_QUARTER_VIEW = "three_quarter_view"
    SIDE_PROFILE = "side_profile"


class ExpressionType(str, Enum):
    """Explicit facial-expression override (else derived from personality)."""
    SOFT_SMILE = "soft_smile"
    NEUTRAL = "neutral"
    PLAYFUL = "playful"
    SEDUCTIVE = "seductive"
    CONFIDENT = "confident"
    LAUGHING = "laughing"


class PhotoStyleType(str, Enum):
    """Photographic finish applied by the workflow-side style wrapper."""
    NATURAL = "natural"            # batch/edit default: realistic photo, nothing synthetic
    POLISHED = "polished"          # generation default: retouched editorial finish
    STUDIO = "studio"
    CANDID_PHONE = "candid_phone"  # legacy raw/candid phone-cam look
