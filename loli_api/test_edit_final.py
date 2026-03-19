#!/usr/bin/env python3
"""
Test script for edit_final.json workflow.
Runs multiple clothing-edit tests against ComfyUI and sends results to Google Chat.

Usage:
    python test_edit_final.py                              # all prompts, single source
    python test_edit_final.py --image test5.png            # explicit single source
    python test_edit_final.py --images test5.png test6.png # random source per test
    python test_edit_final.py --range 1-5                  # run subset
    python test_edit_final.py --list                       # list dataset
"""
import argparse
import copy
import json
import logging
import os
import random
import sys
import time
import uuid

import requests
from dotenv import load_dotenv

# Project root on sys.path so services can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.comfyui_client import ComfyUIClient
from services.supabase_storage_service import SupabaseStorageService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (loaded from .env)
# ---------------------------------------------------------------------------
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

COMFYUI_SERVER = os.getenv("COMFYUI_SERVER_ADDRESS", "127.0.0.1:8188")
WEBHOOK_URL = (
    os.getenv("CHAT_WEBHOOK_URL")
    or os.getenv("GOOGLE_CHAT_RESPONSE_WEBHOOK_URL", "")
).strip()
WORKFLOW_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "workflows", "test_final_API.json"
)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET_NAME", "images_generated")

COMFYUI_INPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ComfyUI", "input")

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------
PROMPT_TEMPLATE = "Change the masking part to {clothes}, keep body proportion, change nothing else, sexy wearings"

# ---------------------------------------------------------------------------
# Clothes dataset – each entry is (label, clothes_description)
# ---------------------------------------------------------------------------
CLOTHES_DATASET = [
    ("Red Evening Gown", "a scandalously plunging red evening gown with fabric so thin it clings wetly to every curve, deep neckline dropping below the navel to bare the inner swell of both breasts, thigh-high slit parting to reveal bare hip and the shadow of bare sex with each slow step"),
    ("Little Black Dress", "a wickedly short little black dress that rides high enough to flash bare ass cheeks, plunging front barely containing spilling breasts, side cut-outs exposing sideboob and the curve under each nipple"),
    ("White Summer Dress", "a whisper-thin, almost transparent white summer dress that turns completely see-through in light, no bra or panties so hard nipples and the dark triangle of pubic hair are clearly visible, hem fluttering just below the curve of the ass"),
    ("Floral Maxi Dress", "a deep-wrap floral maxi dress tied so loosely it constantly slips open, fully exposing heavy breasts and the smooth mound between parted thighs whenever she moves"),
    ("Cocktail Dress", "a glittering sequined silver cocktail dress with halter straps that beg to be untied, front open from collarbone to crotch, sequins sparkling against bare skin and erect nipples"),
    ("Bodycon Dress", "an obscenely tight navy bodycon dress molded like liquid latex to every inch, riding up to expose lower ass cheeks and the clear outline of swollen labia"),

    # -- Formal / Business --
    ("Business Suit", "a severely tailored black business suit worn completely unbuttoned, no blouse or bra underneath so full breasts hang free, trousers slung dangerously low to show the top of the pubic cleft"),
    ("Blazer & Trousers", "a sharp grey blazer worn open over nothing but skin, breasts fully exposed, matching trousers unfastened and pulled down just enough to reveal the bare lower belly and hint of slit"),
    ("Pencil Skirt Set", "a skin-tight pencil skirt with the zipper fully down the back exposing round bare ass, sheer blouse knotted high to permanently display underboob and stiff nipples"),
    ("Tuxedo", "a feminine black satin-lapel tuxedo reimagined slutty: no shirt, waistcoat open to bare cleavage to navel, trousers cut so low the cleft of the buttocks and hip bones are on full display"),

    # -- Casual --
    ("Denim Jacket & Jeans", "a cropped denim jacket flung open over bare breasts, nipples peeking out, low-rise jeans unbuttoned and tugged down past the pubic bone to show smooth shaved mound"),
    ("Graphic Tee & Shorts", "a tiny cropped graphic tee ending right under the nipples, breasts almost fully out, micro denim shorts so tight they dig into the ass crack and camel-toe prominently"),
    ("Hoodie & Joggers", "an oversized hoodie worn unzipped to the navel with nothing underneath, heavy breasts spilling free, joggers pulled down to mid-thigh exposing wet pussy"),
    ("Flannel Shirt", "a huge flannel shirt worn open and tied high under bare breasts, black lace thong pulled aside to reveal glistening folds"),
    ("Crop Top & Cargo Pants", "a minuscule white crop top sliced so high the entire underboob and lower curve of breasts are exposed, cargo pants unbuttoned and gaping open at the front"),

    # -- Sportswear --
    ("Yoga Outfit", "a barely-there black sports bra with massive cut-outs leaving nipples and most of each breast bare, high-cut leggings split at the crotch for easy access"),
    ("Tennis Outfit", "a scandalously short white tennis skirt that flashes bare ass and pussy with every bounce, polo cropped and unbuttoned to navel with breasts jiggling free"),
    ("Running Gear", "a neon tank sliced open at sides and front so breasts bounce completely exposed, tiny compression shorts cut into a thong exposing ass cheeks and labia"),
    ("Gym Set", "a glossy purple micro sports bra that only covers nipples and matching bike shorts with wide crotchless opening, pussy and ass fully on display"),

    # -- Swimwear --
    ("One-Piece Swimsuit", "a high-leg black one-piece with extreme plunges and side cut-outs that remove all coverage of side-boob, nipples, and most of the pubic mound"),
    ("Bikini", "a scarlet micro-string bikini — tiniest triangles imaginable barely covering nipples, strings pulled aside to leave labia and clit piercing exposed"),

    # -- Outerwear --
    ("Leather Jacket", "a black leather biker jacket worn wide open over bare skin, full breast and nipple exposure, paired with only a visible clit ring and nothing else"),
    ("Trench Coat", "a belted beige trench coat worn completely open and nude underneath — full-frontal nudity, breasts swaying, pussy glistening as she walks"),
    ("Puffer Jacket", "an oversized pastel puffer jacket unzipped to the crotch with nothing underneath, breasts and bare sex revealed every time it parts"),
    ("Fur Coat", "a plush faux fur coat left hanging open off the shoulders, revealing only bare skin, erect nipples, and a tiny thong pulled to the side"),

    # -- Traditional / Cultural --
    ("Kimono", "a silk kimono worn completely untied and fallen open down the front, heavy breasts and dripping pussy on full display, obi loose around the waist"),
    ("Sari", "a sheer orange-gold sari draped obscenely low below the pubic bone, tiny blouse cropped to bare underboob and hard nipples"),
    ("Cheongsam", "a skin-tight red silk cheongsam with slits rising to the waist, front buttons undone to below the navel exposing deep cleavage and bare mound"),
    ("Hanbok", "a pastel hanbok with jeogori cropped and pushed below the breasts, chima slit to hip revealing bare thigh, ass, and side of pussy"),
    ("Dirndl", "a tight-laced dirndl bodice shoved down below both breasts, skirt flipped up or scandalously short to expose dripping sex and round ass"),

    # -- Evening / Party --
    ("Sequin Top & Skirt", "a sparkling sequin crop top ending below the nipples with no bra, micro black skirt constantly riding up to flash bare pussy and ass"),
    ("Velvet Dress", "a deep burgundy velvet dress with neckline plunging past both breasts to the waist, back completely bare to the tailbone"),
    ("Satin Slip Dress", "a champagne satin slip so short it rides above the ass cheeks, thin straps fallen off shoulders leaving breasts fully bare and nipples hard"),
    ("Jumpsuit", "a sleek black jumpsuit with plunging front diving to the pubic bone, sides completely cut out from armpit to hip exposing sideboob and hip bones"),

    # -- Vintage / Retro --
    ("50s Polka Dot Dress", "a 1950s polka dot swing dress with sweetheart neckline yanked down below both breasts, skirt hemmed micro-short to flash everything"),
    ("70s Bell Bottoms", "low-slung 1970s bell bottoms worn open at front with no panties, sheer bohemian blouse completely unbuttoned to bare breasts"),
    ("80s Power Suit", "a bold 1980s power suit worn open — breasts fully out, strong shoulders framing erect nipples, skirt hiked to show bare ass and garters"),

    # -- Lingerie / Sleepwear --
    ("Silk Pajamas", "a pale blue silk pajama set worn wide open, bottoms tugged down to thighs exposing wet pussy and hard nipples"),
    ("Lace Bodysuit", "a sheer black lace bodysuit with open cups and crotchless design, nipples and dripping folds completely uncovered"),
    ("Satin Robe", "a deep red satin robe slipping off both shoulders and hanging open, revealing bare breasts, stomach, and glistening sex"),

    # -- Streetwear --
    ("Oversized Streetwear", "an oversized cropped hoodie barely covering underboob, baggy cargos unbuttoned and open at front showing bare mound"),
    ("Bomber Jacket Fit", "a cropped bomber jacket flung open over bare bouncing breasts, low-slung skinny jeans revealing the top of the pubic slit"),

    # -- Uniform --
    ("Nurse Uniform", "a slutty white nurse minidress unbuttoned to the waist, breasts spilling out, skirt so short bare ass and pussy peek from behind"),
    ("School Uniform", "a naughty schoolgirl outfit: blouse tied under bare breasts, micro-pleated skirt flipped up exposing dripping pussy and round ass"),
    ("Military Uniform", "a tight military dress uniform with jacket open to navel, breasts fully out, skirt hiked high to bare ass and garter straps"),
    ("Chef Uniform", "a cropped white chef jacket worn open with breasts hanging free, tiny black shorts pulled down or aside to reveal wet folds"),]


# ---------------------------------------------------------------------------
# Source image upload (once at startup)
# ---------------------------------------------------------------------------
def upload_source_images(
    filenames: list[str],
    supabase: SupabaseStorageService,
) -> dict[str, str]:
    """Upload source images to Supabase, skipping those already uploaded.

    Uses a deterministic path (edit_tests/sources/{filename}) so the same
    file is never re-uploaded across runs.

    Returns:
        {filename: public_url} for each source image.
    """
    url_map: dict[str, str] = {}
    for fname in filenames:
        # Deterministic Supabase path — same filename = same path every run
        storage_path = f"edit_tests/sources/{fname}"

        if supabase.image_exists(storage_path):
            public_url = supabase.get_public_url(storage_path)
            url_map[fname] = public_url
            logger.info("Source already in Supabase, skipped upload: %s", fname)
            continue

        local_path = os.path.join(COMFYUI_INPUT_DIR, fname)
        if not os.path.isfile(local_path):
            logger.error("Source image not found: %s", local_path)
            continue

        with open(local_path, "rb") as f:
            data = f.read()

        # Upload using the bare filename (no random suffix) so it's stable
        name_no_ext = os.path.splitext(fname)[0]
        public_url, _ = supabase.upload_image(data, name_no_ext, folder="edit_tests/sources")
        url_map[fname] = public_url
        logger.info("Uploaded source %s -> %s", fname, public_url)

    return url_map


# ---------------------------------------------------------------------------
# Workflow helpers
# ---------------------------------------------------------------------------
def load_workflow(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def prepare_workflow(
    template: dict,
    image_name: str,
    prompt: str,
    seed: int | None = None,
) -> dict:
    """Inject parameters into the edit_final workflow.

    Key nodes in edit_final.json:
        108  LoadImage        -> inputs.image   (source image filename)
        16   easy positive    -> inputs.positive (clothing change prompt)
        106  KSampler         -> inputs.seed
    """
    wf = copy.deepcopy(template)

    # Source image
    if "108" in wf:
        wf["108"]["inputs"]["image"] = image_name

    # Positive prompt (clothing change)
    if "16" in wf:
        wf["16"]["inputs"]["positive"] = prompt

    # Seed
    if seed is not None and "106" in wf:
        wf["106"]["inputs"]["seed"] = seed

    return wf


# ---------------------------------------------------------------------------
# Google Chat helpers
# ---------------------------------------------------------------------------
def send_result_card(
    webhook_url: str,
    test_name: str,
    prompt: str,
    output_url: str,
    duration: float,
    seed: int,
    source_url: str | None = None,
    source_name: str | None = None,
):
    """Post a result card with source + output images to Google Chat."""
    sections = [
        {
            "header": "Details",
            "widgets": [
                {
                    "decoratedText": {
                        "topLabel": "Prompt",
                        "text": prompt,
                        "wrapText": True,
                    }
                },
                {
                    "decoratedText": {
                        "topLabel": "Source Image",
                        "text": source_name or "N/A",
                    }
                },
                {
                    "decoratedText": {
                        "topLabel": "Duration",
                        "text": f"{duration:.2f}s",
                    }
                },
            ],
        },
    ]

    # Source image section
    if source_url:
        sections.append({
            "header": "Source",
            "widgets": [
                {
                    "image": {
                        "imageUrl": source_url,
                        "altText": f"Source: {source_name}",
                    }
                },
            ],
        })

    # Output image section
    sections.append({
        "header": "Output",
        "widgets": [
            {
                "image": {
                    "imageUrl": output_url,
                    "altText": test_name,
                }
            },
            {
                "buttonList": {
                    "buttons": [
                        {
                            "text": "Open Output",
                            "onClick": {
                                "openLink": {"url": output_url}
                            },
                        }
                    ]
                }
            },
        ],
    })

    card = {
        "cardsV2": [
            {
                "cardId": f"test-{uuid.uuid4().hex[:8]}",
                "card": {
                    "header": {
                        "title": f"Edit Test: {test_name}",
                        "subtitle": f"Duration: {duration:.2f}s | Seed: {seed}",
                    },
                    "sections": sections,
                },
            }
        ]
    }
    resp = requests.post(webhook_url, json=card, timeout=10)
    if resp.status_code == 200:
        logger.info("Result sent to Google Chat: %s", test_name)
    else:
        logger.warning("Google Chat returned %s: %s", resp.status_code, resp.text)


def send_failure_card(webhook_url: str, test_name: str, prompt: str, error: str):
    msg = {
        "text": (
            f"*EDIT TEST FAILED*\n\n"
            f"*Test:* {test_name}\n"
            f"*Prompt:* {prompt}\n"
            f"*Error:* {error}"
        )
    }
    try:
        requests.post(webhook_url, json=msg, timeout=10)
    except Exception as e:
        logger.error("Failed to send failure notification: %s", e)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------
def run_tests(
    source_images: list[str],
    prompts: list[tuple[str, str]],
):
    """Run tests.

    Args:
        source_images: List of source image filenames (in ComfyUI/input).
                       If len > 1, each test randomly picks one.
        prompts: List of (label, prompt_text) to test.
    """
    logger.info("=" * 60)
    logger.info("edit_final.json  -  Test Suite")
    logger.info("=" * 60)
    logger.info("ComfyUI server : %s", COMFYUI_SERVER)
    logger.info("Webhook        : %s", WEBHOOK_URL[:60] + "..." if WEBHOOK_URL else "(none)")
    logger.info("Workflow       : %s", WORKFLOW_PATH)
    logger.info("Source images  : %s", source_images)
    logger.info("Tests          : %d", len(prompts))
    logger.info("=" * 60)

    workflow_template = load_workflow(WORKFLOW_PATH)

    # Supabase (for public image URLs)
    supabase: SupabaseStorageService | None = None
    if SUPABASE_URL and SUPABASE_KEY:
        supabase = SupabaseStorageService(SUPABASE_URL, SUPABASE_KEY, SUPABASE_BUCKET)
        logger.info("Supabase storage ready")
    else:
        logger.warning("Supabase not configured; images saved locally only")

    # Upload source images once at startup
    source_url_map: dict[str, str] = {}
    if supabase:
        logger.info("Uploading %d source image(s) to Supabase...", len(source_images))
        source_url_map = upload_source_images(source_images, supabase)
        logger.info("Source URLs ready: %s", list(source_url_map.keys()))

    results: list[dict] = []

    for idx, (label, prompt) in enumerate(prompts, 1):
        # Pick source image: single = always the same, multiple = random
        source_image = (
            source_images[0] if len(source_images) == 1
            else random.choice(source_images)
        )
        source_url = source_url_map.get(source_image)

        logger.info("\n--- Test %d/%d: %s ---", idx, len(prompts), label)
        logger.info("  Source : %s", source_image)
        logger.info("  Prompt : %s", prompt)

        seed = random.randint(1, 999_999_999)
        wf = prepare_workflow(workflow_template, source_image, prompt, seed=seed)

        client = ComfyUIClient(server_address=COMFYUI_SERVER)
        t0 = time.monotonic()

        try:
            client.connect()
            output_images = client.execute_workflow(wf)
            duration = time.monotonic() - t0

            logger.info("  Done in %.2fs  nodes=%s", duration, list(output_images.keys()))

            # Collect all output image bytes
            all_bytes: list[bytes] = []
            for imgs in output_images.values():
                all_bytes.extend(imgs)

            if not all_bytes:
                logger.warning("  No output images!")
                results.append({"test": label, "status": "NO_OUTPUT", "duration": duration})
                if WEBHOOK_URL:
                    send_failure_card(WEBHOOK_URL, label, prompt, "No output images")
                continue

            image_data = all_bytes[0]
            logger.info("  Output image size: %d bytes", len(image_data))

            # Save locally
            out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_outputs")
            os.makedirs(out_dir, exist_ok=True)
            local_file = os.path.join(out_dir, f"edit_test_{idx}_{label.replace(' ', '_')}.png")
            with open(local_file, "wb") as f:
                f.write(image_data)
            logger.info("  Saved: %s", local_file)

            # Upload output to Supabase for a public URL
            output_url: str | None = None
            if supabase:
                img_id = f"edit_test_{uuid.uuid4().hex[:12]}"
                output_url, _ = supabase.upload_image(image_data, img_id, folder="edit_tests")
                logger.info("  Supabase URL: %s", output_url)

            # Notify Google Chat
            if WEBHOOK_URL and output_url:
                send_result_card(
                    WEBHOOK_URL, label, prompt, output_url, duration, seed,
                    source_url=source_url, source_name=source_image,
                )
            elif WEBHOOK_URL:
                msg = {
                    "text": (
                        f"*EDIT TEST PASSED*\n\n"
                        f"*Test:* {label}\n*Prompt:* {prompt}\n"
                        f"*Duration:* {duration:.2f}s  *Seed:* {seed}\n"
                        f"_(image saved locally only)_"
                    )
                }
                requests.post(WEBHOOK_URL, json=msg, timeout=10)

            results.append({"test": label, "status": "SUCCESS", "duration": duration, "url": output_url})

        except Exception as exc:
            duration = time.monotonic() - t0
            logger.error("  FAILED: %s", exc, exc_info=True)
            results.append({"test": label, "status": "FAILED", "error": str(exc), "duration": duration})
            if WEBHOOK_URL:
                send_failure_card(WEBHOOK_URL, label, prompt, str(exc))
        finally:
            client.disconnect()

    # ---- Summary ----
    logger.info("\n" + "=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)
    for r in results:
        icon = "PASS" if r["status"] == "SUCCESS" else "FAIL"
        logger.info("  [%s] %s  (%.2fs)", icon, r["test"], r["duration"])

    passed = sum(1 for r in results if r["status"] == "SUCCESS")
    logger.info("\n  %d / %d passed", passed, len(results))
    return passed == len(results)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Test edit_final.json workflow",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    img_group = parser.add_mutually_exclusive_group()
    img_group.add_argument(
        "--image", default=None,
        help="Single source image filename (default: test5.png)",
    )
    img_group.add_argument(
        "--images", nargs="+", default=None,
        help="Multiple source images; each test randomly picks one",
    )
    parser.add_argument("--prompt", default=None, help="Run a single custom prompt")
    parser.add_argument("--label", default="Custom Test", help="Label for --prompt mode")
    parser.add_argument("--seed", type=int, default=None, help="Fixed seed (default: random per test)")
    parser.add_argument(
        "--range", default=None, metavar="FROM-TO",
        help="Run a slice of the dataset, e.g. --range 1-5 (1-indexed)",
    )
    parser.add_argument("--list", action="store_true", help="List all dataset entries and exit")
    args = parser.parse_args()

    # List mode
    if args.list:
        for i, (label, clothes) in enumerate(CLOTHES_DATASET, 1):
            print(f"  {i:>3}. [{label}]  {PROMPT_TEMPLATE.format(clothes=clothes)}")
        print(f"\n  Total: {len(CLOTHES_DATASET)} entries")
        sys.exit(0)

    # Resolve source images
    if args.images:
        source_images = args.images
    else:
        source_images = [args.image or "test5.png"]

    # Build prompt list: [(label, prompt_text), ...]
    if args.prompt:
        prompt_list = [(args.label, args.prompt)]
    else:
        prompt_list = [
            (label, PROMPT_TEMPLATE.format(clothes=clothes))
            for label, clothes in CLOTHES_DATASET
        ]
        # Optional slice
        if args.range:
            parts = args.range.split("-")
            start = int(parts[0]) - 1
            end = int(parts[1]) if len(parts) > 1 else start + 1
            prompt_list = prompt_list[start:end]

    success = run_tests(source_images, prompt_list)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
