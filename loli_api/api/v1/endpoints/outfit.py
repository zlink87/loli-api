"""
Outfit edit endpoint.
POST /v1/edit/outfit - Create async outfit edit job using ComfyUI workflow.
"""
import copy
import json
import logging
import random
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl

from auth.dependencies import get_current_user
from models.enums import OutfitType, AccessoryType, JobStatus, NudityLevel
from models.requests import OutfitEditRequest
from models.responses import JobCreateResponse
from services.notification_service import NotificationService
from services import prompt_constants as pc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Outfit Edit"])

# ---------------------------------------------------------------------------
# Global service instances (set from main.py)
# ---------------------------------------------------------------------------
_job_manager = None
_notification_service: Optional[NotificationService] = None
_outfit_workflow_path: Optional[str] = None
_outfit_workflow_template: Optional[dict] = None


# ---------------------------------------------------------------------------
# Outfit Mapping - Maps simple names to detailed descriptions
# ---------------------------------------------------------------------------
OUTFIT_DESCRIPTIONS: Dict[OutfitType, Dict[NudityLevel, str]] = {
    OutfitType.RED_EVENING_GOWN: {
        NudityLevel.LOW: "a stunning red evening gown with a plunging neckline showing deep cleavage, fabric hugging every curve tightly, thigh-high slit revealing toned leg",
        NudityLevel.MEDIUM: "a plunging red evening gown with neckline dropping low to bare the inner swell of both breasts, thin fabric clinging to erect nipples, thigh-high slit parting to reveal bare hip and upper thigh",
        NudityLevel.HIGH: "a scandalously plunging red evening gown with fabric so thin it clings wetly to every curve, deep neckline dropping below the navel to bare the inner swell of both breasts, thigh-high slit parting to reveal bare hip and the shadow of bare sex with each slow step",
    },
    OutfitType.LITTLE_BLACK_DRESS: {
        NudityLevel.LOW: "a tight little black dress with a low-cut front showing cleavage, hem riding high on the thighs, side cut-outs hinting at sideboob",
        NudityLevel.MEDIUM: "a wickedly short little black dress with plunging front barely containing spilling breasts, sideboob exposed through deep cut-outs, hem high enough to flash the curve of bare ass cheeks",
        NudityLevel.HIGH: "a wickedly short little black dress that rides high enough to flash bare ass cheeks, plunging front barely containing spilling breasts, side cut-outs exposing sideboob and the curve under each nipple",
    },
    OutfitType.WHITE_SUMMER_DRESS: {
        NudityLevel.LOW: "a thin white summer dress that hints at the silhouette underneath in bright light, no bra so the shape of nipples is faintly visible, hem fluttering above the knees",
        NudityLevel.MEDIUM: "a whisper-thin white summer dress that turns semi-transparent in light, nipples clearly visible through the fabric, hem fluttering just below the curve of the ass",
        NudityLevel.HIGH: "a whisper-thin, almost transparent white summer dress that turns completely see-through in light, no bra or panties so hard nipples and the dark triangle of pubic hair are clearly visible, hem fluttering just below the curve of the ass",
    },
    OutfitType.FLORAL_MAXI_DRESS: {
        NudityLevel.LOW: "a deep-wrap floral maxi dress with a loose tie showing generous cleavage and the curve of breasts, fabric flowing and hinting at the body underneath",
        NudityLevel.MEDIUM: "a deep-wrap floral maxi dress tied loosely, slipping open to expose bare breasts and smooth skin whenever she moves",
        NudityLevel.HIGH: "a deep-wrap floral maxi dress tied so loosely it constantly slips open, fully exposing heavy breasts and the smooth mound between parted thighs whenever she moves",
    },
    OutfitType.COCKTAIL_DRESS: {
        NudityLevel.LOW: "a glittering sequined silver cocktail dress with halter neck, deep front showing cleavage, fabric shimmering against curves",
        NudityLevel.MEDIUM: "a glittering sequined silver cocktail dress with halter straps, front open to the navel exposing bare skin between breasts, sequins sparkling against erect nipples visible through thin fabric",
        NudityLevel.HIGH: "a glittering sequined silver cocktail dress with halter straps that beg to be untied, front open from collarbone to crotch, sequins sparkling against bare skin and erect nipples",
    },
    OutfitType.BODYCON_DRESS: {
        NudityLevel.LOW: "a skin-tight navy bodycon dress hugging every curve, fabric stretched over breasts and hips, hem riding up to mid-thigh",
        NudityLevel.MEDIUM: "an obscenely tight navy bodycon dress molded to every curve, nipples and the outline of the body clearly visible, riding up to expose the lower curve of ass cheeks",
        NudityLevel.HIGH: "an obscenely tight navy bodycon dress molded like liquid latex to every inch, riding up to expose lower ass cheeks and the clear outline of swollen labia",
    },
    OutfitType.BUSINESS_SUIT: {
        NudityLevel.LOW: "a tailored black business suit with blazer unbuttoned over a sheer blouse, deep cleavage visible, trousers fitted tightly around hips",
        NudityLevel.MEDIUM: "a tailored black business suit worn unbuttoned with no blouse underneath, breasts partially exposed and framed by lapels, trousers slung low on the hips",
        NudityLevel.HIGH: "a severely tailored black business suit worn completely unbuttoned, no blouse or bra underneath so full breasts hang free, trousers slung dangerously low to show the top of the pubic cleft",
    },
    OutfitType.BLAZER_TROUSERS: {
        NudityLevel.LOW: "a sharp grey blazer worn open over a lace bralette showing cleavage, matching trousers fitted low on the hips",
        NudityLevel.MEDIUM: "a sharp grey blazer worn open over bare skin, breasts partially visible between the lapels, matching trousers unfastened and low on the hips revealing bare lower belly",
        NudityLevel.HIGH: "a sharp grey blazer worn open over nothing but skin, breasts fully exposed, matching trousers unfastened and pulled down just enough to reveal the bare lower belly and hint of slit",
    },
    OutfitType.PENCIL_SKIRT_SET: {
        NudityLevel.LOW: "a skin-tight pencil skirt with a sheer blouse knotted high, showing midriff and the outline of a lace bra, skirt hugging hips tightly",
        NudityLevel.MEDIUM: "a skin-tight pencil skirt with sheer blouse knotted high to display underboob, nipples visible through the fabric, skirt zipper partially down in the back",
        NudityLevel.HIGH: "a skin-tight pencil skirt with the zipper fully down the back exposing round bare ass, sheer blouse knotted high to permanently display underboob and stiff nipples",
    },
    OutfitType.TUXEDO: {
        NudityLevel.LOW: "a feminine black satin-lapel tuxedo with no shirt underneath, waistcoat showing deep cleavage, trousers fitted low on hips",
        NudityLevel.MEDIUM: "a feminine black satin-lapel tuxedo with no shirt, waistcoat open to bare cleavage to the navel, trousers cut low enough to show hip bones",
        NudityLevel.HIGH: "a feminine black satin-lapel tuxedo reimagined slutty: no shirt, waistcoat open to bare cleavage to navel, trousers cut so low the cleft of the buttocks and hip bones are on full display",
    },
    OutfitType.DENIM_JACKET_JEANS: {
        NudityLevel.LOW: "a cropped denim jacket over a tiny bralette showing cleavage and midriff, low-rise jeans hugging hips tightly",
        NudityLevel.MEDIUM: "a cropped denim jacket flung open over bare skin, breasts partially visible, low-rise jeans unbuttoned and tugged down showing hip bones and lower belly",
        NudityLevel.HIGH: "a cropped denim jacket flung open over bare breasts, nipples peeking out, low-rise jeans unbuttoned and tugged down past the pubic bone to show smooth shaved mound",
    },
    OutfitType.GRAPHIC_TEE_SHORTS: {
        NudityLevel.LOW: "a tiny cropped graphic tee showing underboob and midriff, micro denim shorts hugging tightly and riding up on the thighs",
        NudityLevel.MEDIUM: "a tiny cropped graphic tee ending right under the nipples with breasts nearly spilling out, micro denim shorts so tight they ride up and cling to every curve",
        NudityLevel.HIGH: "a tiny cropped graphic tee ending right under the nipples, breasts almost fully out, micro denim shorts so tight they dig into the ass crack and camel-toe prominently",
    },
    OutfitType.HOODIE_JOGGERS: {
        NudityLevel.LOW: "an oversized hoodie worn unzipped showing cleavage and bare skin underneath, joggers slung low on the hips",
        NudityLevel.MEDIUM: "an oversized hoodie worn unzipped to the navel with nothing underneath, breasts partially visible, joggers pulled down low on the hips exposing hip bones",
        NudityLevel.HIGH: "an oversized hoodie worn unzipped to the navel with nothing underneath, heavy breasts spilling free, joggers pulled down to mid-thigh exposing wet pussy",
    },
    OutfitType.FLANNEL_SHIRT: {
        NudityLevel.LOW: "a large flannel shirt worn open and tied under the bust, showing cleavage and toned midriff, lace underwear peeking out",
        NudityLevel.MEDIUM: "a large flannel shirt worn open and tied high under bare breasts, nipples partially visible, wearing only a tiny lace thong below",
        NudityLevel.HIGH: "a huge flannel shirt worn open and tied high under bare breasts, black lace thong pulled aside to reveal glistening folds",
    },
    OutfitType.CROP_TOP_CARGO: {
        NudityLevel.LOW: "a tiny white crop top showing underboob and toned midriff, low-slung cargo pants unbuttoned at the waist",
        NudityLevel.MEDIUM: "a minuscule white crop top sliced high exposing the entire underboob and lower curve of breasts, cargo pants unbuttoned and gaping open",
        NudityLevel.HIGH: "a minuscule white crop top sliced so high the entire underboob and lower curve of breasts are exposed, cargo pants unbuttoned and gaping open at the front",
    },
    OutfitType.YOGA_OUTFIT: {
        NudityLevel.LOW: "a tight black sports bra with deep cut-outs showing sideboob, high-waisted leggings clinging to every curve",
        NudityLevel.MEDIUM: "a barely-there black sports bra with large cut-outs leaving most of each breast bare, nipples nearly exposed, high-cut leggings with mesh panels",
        NudityLevel.HIGH: "a barely-there black sports bra with massive cut-outs leaving nipples and most of each breast bare, high-cut leggings split at the crotch for easy access",
    },
    OutfitType.TENNIS_OUTFIT: {
        NudityLevel.LOW: "a short white tennis skirt flashing toned thighs with each move, fitted polo cropped to show midriff, sporty and flirtatious",
        NudityLevel.MEDIUM: "a scandalously short white tennis skirt flashing bare ass with every bounce, polo cropped and unbuttoned showing cleavage and underboob",
        NudityLevel.HIGH: "a scandalously short white tennis skirt that flashes bare ass and pussy with every bounce, polo cropped and unbuttoned to navel with breasts jiggling free",
    },
    OutfitType.RUNNING_GEAR: {
        NudityLevel.LOW: "a neon tank top with deep side slits showing sideboob, tiny compression shorts hugging curves tightly",
        NudityLevel.MEDIUM: "a neon tank sliced open at sides exposing bare breasts bouncing freely, tiny compression shorts riding up to expose the lower curve of ass cheeks",
        NudityLevel.HIGH: "a neon tank sliced open at sides and front so breasts bounce completely exposed, tiny compression shorts cut into a thong exposing ass cheeks and labia",
    },
    OutfitType.GYM_SET: {
        NudityLevel.LOW: "a glossy purple micro sports bra and matching bike shorts, fabric stretched tight over curves, showing deep cleavage and toned midriff",
        NudityLevel.MEDIUM: "a glossy purple micro sports bra that barely covers nipples with matching bike shorts pulled tight, underboob and sideboob on display",
        NudityLevel.HIGH: "a glossy purple micro sports bra that only covers nipples and matching bike shorts with wide crotchless opening, pussy and ass fully on display",
    },
    OutfitType.ONE_PIECE_SWIMSUIT: {
        NudityLevel.LOW: "a high-leg black one-piece swimsuit with plunging neckline and side cut-outs, showing cleavage and sideboob, fabric hugging every curve",
        NudityLevel.MEDIUM: "a high-leg black one-piece with extreme plunges and side cut-outs exposing sideboob, nipples nearly visible through thin fabric, cut high on the hips",
        NudityLevel.HIGH: "a high-leg black one-piece with extreme plunges and side cut-outs that remove all coverage of side-boob, nipples, and most of the pubic mound",
    },
    OutfitType.BIKINI: {
        NudityLevel.LOW: "a scarlet string bikini with small triangles showing generous cleavage, strings tied at the hips, flirtatious and revealing",
        NudityLevel.MEDIUM: "a scarlet micro-string bikini with tiny triangles barely covering nipples, strings pulled tight on the hips, nearly everything exposed",
        NudityLevel.HIGH: "a scarlet micro-string bikini — tiniest triangles imaginable barely covering nipples, strings pulled aside to leave labia and clit piercing exposed",
    },
    OutfitType.LEATHER_JACKET: {
        NudityLevel.LOW: "a black leather biker jacket worn open over a lace bralette, showing cleavage and toned midriff, tight leather pants",
        NudityLevel.MEDIUM: "a black leather biker jacket worn open over bare skin, breasts partially exposed, wearing nothing else below but a tiny thong",
        NudityLevel.HIGH: "a black leather biker jacket worn wide open over bare skin, full breast and nipple exposure, paired with only a visible clit ring and nothing else",
    },
    OutfitType.TRENCH_COAT: {
        NudityLevel.LOW: "a belted beige trench coat slightly open showing bare collarbone, hint of cleavage, and bare legs underneath suggesting nudity beneath",
        NudityLevel.MEDIUM: "a belted beige trench coat hanging open revealing bare breasts and smooth skin, belt barely keeping it together, nude underneath",
        NudityLevel.HIGH: "a belted beige trench coat worn completely open and nude underneath — full-frontal nudity, breasts swaying, pussy glistening as she walks",
    },
    OutfitType.PUFFER_JACKET: {
        NudityLevel.LOW: "an oversized pastel puffer jacket partially unzipped showing bare skin and cleavage underneath, hinting at nudity beneath",
        NudityLevel.MEDIUM: "an oversized pastel puffer jacket unzipped low with nothing underneath, breasts partially visible every time it parts, bare skin beneath",
        NudityLevel.HIGH: "an oversized pastel puffer jacket unzipped to the crotch with nothing underneath, breasts and bare sex revealed every time it parts",
    },
    OutfitType.FUR_COAT: {
        NudityLevel.LOW: "a plush faux fur coat draped off one shoulder, revealing bare skin and the curve of one breast, wearing a tiny thong underneath",
        NudityLevel.MEDIUM: "a plush faux fur coat left hanging open off the shoulders, revealing bare skin and erect nipples, wearing only a tiny thong",
        NudityLevel.HIGH: "a plush faux fur coat left hanging open off the shoulders, revealing only bare skin, erect nipples, and a tiny thong pulled to the side",
    },
    OutfitType.KIMONO: {
        NudityLevel.LOW: "a silk kimono loosely tied, falling open at the chest to reveal deep cleavage and smooth skin, obi barely holding it together",
        NudityLevel.MEDIUM: "a silk kimono worn loosely untied, fallen open to expose bare breasts and smooth stomach, obi loose around the waist",
        NudityLevel.HIGH: "a silk kimono worn completely untied and fallen open down the front, heavy breasts and dripping pussy on full display, obi loose around the waist",
    },
    OutfitType.SARI: {
        NudityLevel.LOW: "a sheer orange-gold sari draped low on the hips, tiny blouse showing deep cleavage and midriff, fabric hinting at the body beneath",
        NudityLevel.MEDIUM: "a sheer orange-gold sari draped low below the navel, tiny blouse cropped to bare underboob, nipples nearly visible through the fabric",
        NudityLevel.HIGH: "a sheer orange-gold sari draped obscenely low below the pubic bone, tiny blouse cropped to bare underboob and hard nipples",
    },
    OutfitType.CHEONGSAM: {
        NudityLevel.LOW: "a skin-tight red silk cheongsam with high slits showing toned thighs, front buttons partially undone revealing cleavage",
        NudityLevel.MEDIUM: "a skin-tight red silk cheongsam with slits rising to the hip, front buttons undone to the navel exposing deep cleavage and bare skin",
        NudityLevel.HIGH: "a skin-tight red silk cheongsam with slits rising to the waist, front buttons undone to below the navel exposing deep cleavage and bare mound",
    },
    OutfitType.HANBOK: {
        NudityLevel.LOW: "a pastel hanbok with jeogori slightly open showing collarbone and hint of cleavage, chima flowing with a slit revealing toned thigh",
        NudityLevel.MEDIUM: "a pastel hanbok with jeogori cropped and open showing bare breasts partially, chima slit to hip revealing bare thigh and hip",
        NudityLevel.HIGH: "a pastel hanbok with jeogori cropped and pushed below the breasts, chima slit to hip revealing bare thigh, ass, and side of pussy",
    },
    OutfitType.DIRNDL: {
        NudityLevel.LOW: "a tight-laced dirndl bodice pushing up generous cleavage, skirt short enough to show thighs, flirtatious and traditional",
        NudityLevel.MEDIUM: "a tight-laced dirndl bodice shoved down to expose bare breasts, skirt scandalously short showing the curve of bare ass",
        NudityLevel.HIGH: "a tight-laced dirndl bodice shoved down below both breasts, skirt flipped up or scandalously short to expose dripping sex and round ass",
    },
    OutfitType.SEQUIN_TOP_SKIRT: {
        NudityLevel.LOW: "a sparkling sequin crop top showing cleavage and midriff, micro black skirt hugging hips tightly and riding high on the thighs",
        NudityLevel.MEDIUM: "a sparkling sequin crop top ending below the nipples with no bra, nipples visible, micro black skirt constantly riding up to flash bare skin",
        NudityLevel.HIGH: "a sparkling sequin crop top ending below the nipples with no bra, micro black skirt constantly riding up to flash bare pussy and ass",
    },
    OutfitType.VELVET_DRESS: {
        NudityLevel.LOW: "a deep burgundy velvet dress with plunging neckline showing cleavage, back open to mid-back, fabric hugging curves",
        NudityLevel.MEDIUM: "a deep burgundy velvet dress with neckline plunging to the waist, breasts partially exposed on each side, back completely bare to the tailbone",
        NudityLevel.HIGH: "a deep burgundy velvet dress with neckline plunging past both breasts to the waist, back completely bare to the tailbone",
    },
    OutfitType.SATIN_SLIP_DRESS: {
        NudityLevel.LOW: "a champagne satin slip dress with thin straps, fabric clinging to curves, short hem showing thighs, nipples hinted through the satin",
        NudityLevel.MEDIUM: "a champagne satin slip so short it rides above mid-thigh, thin straps fallen off one shoulder leaving one breast nearly bare, nipples hard through the fabric",
        NudityLevel.HIGH: "a champagne satin slip so short it rides above the ass cheeks, thin straps fallen off shoulders leaving breasts fully bare and nipples hard",
    },
    OutfitType.JUMPSUIT: {
        NudityLevel.LOW: "a sleek black jumpsuit with plunging front showing cleavage to the navel, side cut-outs at the waist exposing bare skin",
        NudityLevel.MEDIUM: "a sleek black jumpsuit with plunging front to the navel, sides completely cut out exposing sideboob and hip bones, braless",
        NudityLevel.HIGH: "a sleek black jumpsuit with plunging front diving to the pubic bone, sides completely cut out from armpit to hip exposing sideboob and hip bones",
    },
    OutfitType.POLKA_DOT_DRESS_50S: {
        NudityLevel.LOW: "a 1950s polka dot swing dress with sweetheart neckline pushed low showing cleavage, skirt hemmed short to show thighs",
        NudityLevel.MEDIUM: "a 1950s polka dot swing dress with sweetheart neckline pulled down exposing bare breasts, skirt hemmed very short flashing bare thighs",
        NudityLevel.HIGH: "a 1950s polka dot swing dress with sweetheart neckline yanked down below both breasts, skirt hemmed micro-short to flash everything",
    },
    OutfitType.BELL_BOTTOMS_70S: {
        NudityLevel.LOW: "low-slung 1970s bell bottoms showing hip bones, sheer bohemian blouse unbuttoned to show cleavage and lace bra",
        NudityLevel.MEDIUM: "low-slung 1970s bell bottoms worn open at front showing bare lower belly, sheer bohemian blouse completely unbuttoned with breasts visible through the fabric",
        NudityLevel.HIGH: "low-slung 1970s bell bottoms worn open at front with no panties, sheer bohemian blouse completely unbuttoned to bare breasts",
    },
    OutfitType.POWER_SUIT_80S: {
        NudityLevel.LOW: "a bold 1980s power suit worn open over a lace bralette, strong shoulders, skirt short showing toned thighs and garter straps",
        NudityLevel.MEDIUM: "a bold 1980s power suit worn open with breasts partially exposed between the lapels, skirt hiked high to show bare thighs and garter straps",
        NudityLevel.HIGH: "a bold 1980s power suit worn open — breasts fully out, strong shoulders framing erect nipples, skirt hiked to show bare ass and garters",
    },
    OutfitType.SILK_PAJAMAS: {
        NudityLevel.LOW: "a pale blue silk pajama set with top unbuttoned showing cleavage and bare skin, bottoms slung low on the hips",
        NudityLevel.MEDIUM: "a pale blue silk pajama set worn wide open, breasts exposed between the lapels, bottoms pulled low showing hip bones and bare lower belly",
        NudityLevel.HIGH: "a pale blue silk pajama set worn wide open, bottoms tugged down to thighs exposing wet pussy and hard nipples",
    },
    OutfitType.LACE_BODYSUIT: {
        NudityLevel.LOW: "a sheer black lace bodysuit with strategic coverage, nipples and skin visible through the lace pattern, hugging every curve",
        NudityLevel.MEDIUM: "a sheer black lace bodysuit with open cups exposing bare breasts and nipples, lace barely covering between the thighs",
        NudityLevel.HIGH: "a sheer black lace bodysuit with open cups and crotchless design, nipples and dripping folds completely uncovered",
    },
    OutfitType.SATIN_ROBE: {
        NudityLevel.LOW: "a deep red satin robe loosely tied, slipping off one shoulder to reveal bare skin and the curve of one breast, belt barely holding it closed",
        NudityLevel.MEDIUM: "a deep red satin robe slipping off both shoulders, hanging open to reveal bare breasts and smooth stomach, loosely belted",
        NudityLevel.HIGH: "a deep red satin robe slipping off both shoulders and hanging open, revealing bare breasts, stomach, and glistening sex",
    },
    OutfitType.OVERSIZED_STREETWEAR: {
        NudityLevel.LOW: "an oversized cropped hoodie showing underboob and midriff, baggy cargos slung low on the hips showing hip bones",
        NudityLevel.MEDIUM: "an oversized cropped hoodie barely covering underboob with nipples peeking, baggy cargos unbuttoned and open at front showing bare lower belly",
        NudityLevel.HIGH: "an oversized cropped hoodie barely covering underboob, baggy cargos unbuttoned and open at front showing bare mound",
    },
    OutfitType.BOMBER_JACKET_FIT: {
        NudityLevel.LOW: "a cropped bomber jacket open over a tiny bralette showing cleavage, low-slung skinny jeans hugging hips tightly",
        NudityLevel.MEDIUM: "a cropped bomber jacket flung open over bare skin, breasts partially bouncing free, low-slung skinny jeans revealing hip bones and bare lower belly",
        NudityLevel.HIGH: "a cropped bomber jacket flung open over bare bouncing breasts, low-slung skinny jeans revealing the top of the pubic slit",
    },
    OutfitType.NURSE_UNIFORM: {
        NudityLevel.LOW: "a tight white nurse minidress with buttons straining over cleavage, skirt short showing thighs, suggestive and flirtatious",
        NudityLevel.MEDIUM: "a tight white nurse minidress unbuttoned to show bare breasts between the lapels, skirt so short it barely covers, no underwear",
        NudityLevel.HIGH: "a slutty white nurse minidress unbuttoned to the waist, breasts spilling out, skirt so short bare ass and pussy peek from behind",
    },
    OutfitType.SCHOOL_UNIFORM: {
        NudityLevel.LOW: "a naughty schoolgirl outfit: blouse tied high showing midriff and cleavage, micro-pleated skirt barely covering, thigh-high stockings",
        NudityLevel.MEDIUM: "a naughty schoolgirl outfit: blouse tied under bare breasts with nipples exposed, micro-pleated skirt so short it flashes bare ass",
        NudityLevel.HIGH: "a naughty schoolgirl outfit: blouse tied under bare breasts, micro-pleated skirt flipped up exposing dripping pussy and round ass",
    },
    OutfitType.MILITARY_UNIFORM: {
        NudityLevel.LOW: "a tight military dress uniform with jacket partially open showing cleavage, skirt short showing thighs and garter straps",
        NudityLevel.MEDIUM: "a tight military dress uniform with jacket open to show bare breasts between the lapels, skirt hiked high showing bare thighs and garter straps",
        NudityLevel.HIGH: "a tight military dress uniform with jacket open to navel, breasts fully out, skirt hiked high to bare ass and garter straps",
    },
    OutfitType.CHEF_UNIFORM: {
        NudityLevel.LOW: "a cropped white chef jacket showing cleavage and midriff, tiny black shorts hugging curves tightly",
        NudityLevel.MEDIUM: "a cropped white chef jacket worn open with breasts partially visible, tiny black shorts pulled low showing hip bones and bare lower belly",
        NudityLevel.HIGH: "a cropped white chef jacket worn open with breasts hanging free, tiny black shorts pulled down or aside to reveal wet folds",
    },
    OutfitType.NAKED: {
        NudityLevel.LOW: "wearing only a sheer see-through covering draped loosely over the body, curves and silhouette fully visible, nipples and intimate areas hinted through the fabric",
        NudityLevel.MEDIUM: "topless with bare breasts and hard nipples exposed, wearing only a tiny thong, smooth skin glistening",
        NudityLevel.HIGH: "completely naked, glistening skin, hard nipples, swollen aroused pussy lips parted slightly, body on full explicit display",
    },
}


# ---------------------------------------------------------------------------
# Accessories Mapping
# ---------------------------------------------------------------------------
ACCESSORY_DESCRIPTIONS: Dict[AccessoryType, str] = {
    AccessoryType.NECKLACE: "wearing an elegant necklace",
    AccessoryType.EARRINGS: "wearing stylish earrings",
    AccessoryType.GLASSES: "wearing fashionable glasses",
    AccessoryType.HAT: "wearing a stylish hat",
    AccessoryType.SUNGLASSES: "wearing trendy sunglasses",
}


# ---------------------------------------------------------------------------
# Service configuration functions (called from main.py)
# ---------------------------------------------------------------------------
def set_job_manager(job_manager) -> None:
    """Set job manager instance."""
    global _job_manager
    _job_manager = job_manager


def set_notification_service(service: NotificationService) -> None:
    """Set notification service instance."""
    global _notification_service
    _notification_service = service


def set_outfit_workflow_path(workflow_path: str) -> None:
    """Set and load outfit workflow template."""
    global _outfit_workflow_path, _outfit_workflow_template
    _outfit_workflow_path = workflow_path

    try:
        with open(workflow_path, 'r', encoding='utf-8') as f:
            _outfit_workflow_template = json.load(f)
        logger.info(f"Loaded outfit workflow template: {workflow_path}")
    except Exception as e:
        logger.error(f"Failed to load outfit workflow: {e}")
        _outfit_workflow_template = None


def get_job_manager():
    """Get job manager instance."""
    if _job_manager is None:
        raise RuntimeError("Job manager not initialized")
    return _job_manager


def get_notification_service() -> Optional[NotificationService]:
    """Get notification service instance."""
    return _notification_service


# ---------------------------------------------------------------------------
# Helper functions (used by OutfitBackgroundWorker via import)
# ---------------------------------------------------------------------------
def _outfit_change_lead(outfit: OutfitType, outfit_desc: str) -> str:
    """
    Lead sentence for a (dressed) outfit change.

    Uses the neutral verb "Change the person's outfit to:" rather than
    "Dress the person in ...". At MEDIUM/HIGH nudity the OUTFIT_DESCRIPTIONS
    text describes open, absent, or barely-present clothing, which directly
    contradicts an instruction to "dress" the person; the neutral verb stays
    accurate at every nudity level. ``outfit`` is accepted for signature
    stability / future per-outfit tuning.
    """
    return f"Change the person's outfit to: {outfit_desc}"


def build_prompt(outfit: OutfitType, accessories: Optional[List[AccessoryType]], nudity_level: NudityLevel = NudityLevel.LOW) -> str:
    """
    Build the positive prompt from outfit and accessories.
    Ensures the person's face, hair, and physical features are never altered.

    Args:
        outfit: The outfit type
        accessories: Optional list of accessories
        nudity_level: Nudity level (low, medium, high)

    Returns:
        Complete prompt string
    """
    outfit_levels = OUTFIT_DESCRIPTIONS.get(outfit)
    if outfit_levels:
        outfit_desc = outfit_levels.get(nudity_level, outfit_levels[NudityLevel.LOW])
    else:
        outfit_desc = str(outfit.value)

    if outfit == OutfitType.NAKED:
        prompt_parts = [
            f"Remove all clothing, the person should be {outfit_desc}",
            pc.identity_clause("the clothing and covering"),
            "only change the clothing and covering, nothing else",
        ]
    else:
        prompt_parts = [
            _outfit_change_lead(outfit, outfit_desc),
            pc.identity_clause("the outfit and clothing"),
            "only change the clothing, nothing else",
        ]

    if accessories:
        accessory_parts = [
            ACCESSORY_DESCRIPTIONS.get(acc, str(acc.value))
            for acc in accessories
        ]
        prompt_parts.append(", ".join(accessory_parts))

    return ", ".join(prompt_parts)


def prepare_outfit_workflow(
    template: dict,
    image_name: str,
    prompt: str,
    seed: Optional[int] = None,
    nudity_level: Optional[NudityLevel] = None,
    outfit: Optional[OutfitType] = None,
    negative_prompt: Optional[str] = None,
) -> dict:
    """
    Prepare the outfit workflow with injected parameters.
    Adapts SAM3 masking based on nudity direction for bidirectional outfit changes.

    Key nodes in test_final_API.json:
        108    LoadImage        -> inputs.image   (source image filename)
        16     easy positive    -> inputs.positive (clothing change prompt)
        106    KSampler         -> inputs.seed
        30:19  SAM3Grounding    -> inputs.text_prompt (body/clothing detection)
        29:28  SAM3Grounding    -> inputs.text_prompt (outfit/clothing detection)
        119    GrowMaskWithBlur -> inputs.expand/blur_radius (mask feathering)

    Args:
        template: Base workflow template
        image_name: ComfyUI image filename
        prompt: Positive prompt
        seed: Optional seed value
        nudity_level: Optional nudity level for adaptive masking
        outfit: Optional outfit type for direction detection
        negative_prompt: Optional extra negative prompt terms (appended to
            quality + adult + identity negatives on node 117)

    Returns:
        Prepared workflow dict
    """
    wf = copy.deepcopy(template)

    # Node 108: Source image
    if "108" in wf:
        wf["108"]["inputs"]["image"] = image_name
        logger.debug(f"Set node 108 image: {image_name}")

    # Node 16: Positive prompt
    if "16" in wf:
        wf["16"]["inputs"]["positive"] = prompt
        logger.debug(f"Set node 16 prompt: {prompt[:50]}...")

    # Node 117: Negative prompt (quality + adult + identity preservation + user override)
    if "117" in wf:
        wf["117"]["inputs"]["negative"] = pc.edit_negative(negative_prompt)
        logger.debug("Set node 117 negative (quality + adult + identity)")

    # Node 106: Seed
    if seed is not None and "106" in wf:
        wf["106"]["inputs"]["seed"] = seed
        logger.debug(f"Set node 106 seed: {seed}")

    # Adaptive SAM3 masking based on nudity direction
    if nudity_level == NudityLevel.HIGH or outfit == OutfitType.NAKED:
        # Going toward nudity: target clothing to remove
        if "30:19" in wf:
            wf["30:19"]["inputs"]["text_prompt"] = "clothing, outfit, dress, shirt, pants, underwear, bra"
            logger.debug("SAM3 30:19: targeting clothing for removal")
        if "29:28" in wf:
            wf["29:28"]["inputs"]["text_prompt"] = "fabric, garment, covering"
            logger.debug("SAM3 29:28: targeting fabric/garments")
    elif nudity_level == NudityLevel.LOW:
        # Dressing up (possibly from nude): target body areas to cover
        if "30:19" in wf:
            wf["30:19"]["inputs"]["text_prompt"] = "torso, chest, waist, hips, body, not face, not hair"
            logger.debug("SAM3 30:19: targeting body areas for dressing")
        if "29:28" in wf:
            wf["29:28"]["inputs"]["text_prompt"] = "skin, bare body, exposed area, not face, not hair"
            logger.debug("SAM3 29:28: targeting exposed skin")
        # Increase mask coverage for dressing transitions
        if "119" in wf:
            wf["119"]["inputs"]["expand"] = 10
            wf["119"]["inputs"]["blur_radius"] = 8
            logger.debug("Increased mask grow for dressing transition")

    # Default (MEDIUM or unspecified): keep workflow defaults ("torso and curves" / "outfit/clothes")

    return wf


# ---------------------------------------------------------------------------
# API Endpoint
# ---------------------------------------------------------------------------
@router.post(
    "/edit/outfit",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create outfit edit job",
    description="""
Submit an outfit edit request. Returns immediately with job ID for polling.

The job is queued and processed asynchronously. Use GET /v1/jobs/{jobId} to poll for status.

**Flow:**
1. Submit request with source image and outfit type
2. Receive jobId immediately (202 Accepted)
3. Poll GET /v1/jobs/{jobId} for status
4. When status is 'succeeded', access preview_url to see the image
    """,
    responses={
        202: {
            "description": "Job created successfully",
            "model": JobCreateResponse
        },
        401: {"description": "Unauthorized - Invalid or missing JWT token"},
        422: {"description": "Validation error - Invalid request body"},
        429: {"description": "Too many requests - Queue is full"},
        500: {"description": "Internal server error"}
    }
)
async def edit_outfit(
    request: OutfitEditRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Create a new outfit edit job.

    The job is queued immediately and processed asynchronously by the outfit background worker.

    **Request Body:**
    - `source_image` (required): Supabase URL of the source image
    - `outfit` (required): Outfit type to apply
    - `accessories` (optional): List of accessories (max 5)
    - `seed` (optional): Random seed for reproducibility

    **Returns:**
    - `jobId`: Unique identifier to poll for status
    - `status`: Initial status (always "queued")
    """
    job_manager = get_job_manager()
    user_id = current_user.get("sub", "anonymous")

    try:
        # Check queue capacity
        if job_manager.is_queue_full(job_type="outfit_edit"):
            logger.warning(f"Outfit queue full, rejecting request from user {user_id}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Outfit edit queue is full. Please try again later."
            )

        # Send payload to Google Chat webhook for logging
        notification_service = get_notification_service()
        if notification_service:
            payload_dict = request.model_dump(mode="json")
            await notification_service.send_request_received(user_id, payload_dict)

        # Create job
        job = await job_manager.create_job(request, user_id, job_type="outfit_edit")

        logger.info(
            f"Created outfit edit job {job.job_id} for user {user_id} "
            f"(outfit: {request.outfit.value}, "
            f"accessories: {[a.value for a in request.accessories] if request.accessories else []})"
        )

        return JobCreateResponse(
            jobId=job.job_id,
            status=JobStatus.QUEUED,
            reviewRequired=False
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating outfit job for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create outfit edit job. Please try again."
        )
