#!/usr/bin/env python3
"""
Test script for Grok-driven chained edit pipeline.

Flow:
  1. User provides an image + text prompt
  2. Grok (vision) analyzes the image and decomposes the edit into ordered sub-tasks
     from: Camera Angle & View, Background, Outfit, Pose
  3. Each sub-task executes sequentially via ComfyUI (edit_final_AIO.json),
     where the output of step N becomes the input of step N+1
  4. After each step, face similarity is checked -- if < threshold, regenerate
     (max N attempts, keep the highest)
  5. Results (images, token usage, costs, prompts) are sent to Google Chat

Usage:
    # Single prompt, all images in folder
    python test_edit_chain.py --input-dir /path/to/images --prompt "make him naked outdoors"

    # Multiple prompts inline (each image x each prompt)
    python test_edit_chain.py --input-dir /path/to/images --prompt "make him naked outdoors" "change to bikini on beach" "red dress standing"

    # Prompts from a JSON file
    python test_edit_chain.py --input-dir /path/to/images --prompts-file prompts.json

    # Mix both: file + extra inline prompts
    python test_edit_chain.py --input-dir /path/to/images --prompts-file prompts.json --prompt "extra prompt"

    # Single image + single prompt
    python test_edit_chain.py --input-dir /path/to/images --prompt "change to bikini on beach" --image specific.png

    # List images, dry run
    python test_edit_chain.py --input-dir /path/to/images --list
    python test_edit_chain.py --input-dir /path/to/images --prompt "standing pose outdoors" --dry-run
"""
import argparse
import base64
import copy
import json
import logging
import os
import random
import sys
import time
import uuid

import requests
import websocket as ws_module
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
# Configuration
# ---------------------------------------------------------------------------
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

VENICE_API_KEY = os.getenv("VENICE_API_KEY", "")
VENICE_BASE_URL = os.getenv("VENICE_BASE_URL", "https://api.venice.ai/api/v1").rstrip("/")
COMFYUI_SERVER = os.getenv("COMFYUI_SERVER_ADDRESS", "127.0.0.1:8188")
WEBHOOK_URL = (
    os.getenv("CHAT_WEBHOOK_URL")
    or os.getenv("GOOGLE_CHAT_RESPONSE_WEBHOOK_URL", "")
).strip()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET_NAME", "images_generated")

WORKFLOW_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "workflows", "edit_final_AIO.json"
)

GROK_VISION_MODEL = 'grok-2-vision-1212'
#os.getenv("XAI_MODEL", "grok-4-fast-reasoning")

# Local pricing table for this dev-only vision harness. Venice bills in VCU, so
# cost is best-effort ($0 when the model isn't listed); token counts still log.
GROK_PRICING: dict = {}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# ---------------------------------------------------------------------------
# Grok vision decomposition
# ---------------------------------------------------------------------------
DECOMPOSE_SYSTEM_PROMPT = """\
You are an image edit planner. Given an image and a user's edit request, decompose
the edit into an ordered chain of sub-tasks. Each sub-task must be one of:
- Camera Angle & View
- Background
- Outfit
- Pose

For each sub-task, provide:
- "task": one of the 4 categories above
- "prompt": a short edit prompt (5-10 words) for that specific change
- "nsfw_switch": 1 (normal), 2 (male NSFW), or 3 (female NSFW)

Not all 4 tasks are required -- only include tasks relevant to the user's request.
Order them logically (e.g. pose before outfit if both needed).

Return ONLY valid JSON:
{
  "chain": [
    {"task": "Pose", "prompt": "standing with arms at sides", "nsfw_switch": 1},
    {"task": "Outfit", "prompt": "red bikini top and bottom", "nsfw_switch": 3}
  ]
}
"""


def image_to_base64_url(image_path: str) -> str:
    """Read an image file and return a data-URI base64 string."""
    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".bmp": "image/bmp"}
    mime = mime_map.get(ext, "image/png")
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


def call_grok_vision(image_path: str, user_prompt: str) -> dict:
    """Call Grok vision to decompose the edit into a chain of sub-tasks.

    Returns:
        {
            "chain": [...],
            "token_usage": {model, prompt_tokens, ...},
            "raw_response": str
        }
    """
    image_url = image_to_base64_url(image_path)

    payload = {
        "model": GROK_VISION_MODEL,
        "messages": [
            {"role": "system", "content": DECOMPOSE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    },
                    {
                        "type": "text",
                        "text": f"User edit request: {user_prompt}",
                    },
                ],
            },
        ],
        "temperature": 0.3,
        "max_tokens": 1000,
    }

    logger.info("Calling Grok vision (%s) for edit decomposition...", GROK_VISION_MODEL)
    t0 = time.monotonic()

    resp = requests.post(
        f"{VENICE_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {VENICE_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    result = resp.json()
    duration = time.monotonic() - t0
    logger.info("Grok vision responded in %.2fs", duration)

    # Parse token usage — log raw response for debugging token counts
    usage = result.get("usage", {})
    logger.info("Raw Grok usage response: %s", json.dumps(usage, indent=2))
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", 0)

    # Nested detail objects (xAI API structure) — same as prompt_generator.py
    prompt_details = usage.get("prompt_tokens_details", {})
    cached_tokens = prompt_details.get("cached_tokens", 0)
    completion_details = usage.get("completion_tokens_details", {})
    reasoning_tokens = completion_details.get("reasoning_tokens", 0)

    pricing = GROK_PRICING.get(GROK_VISION_MODEL, {"input": 0, "cached": 0, "output": 0})
    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    cached_cost = (cached_tokens / 1_000_000) * pricing["cached"]
    output_cost = ((completion_tokens + reasoning_tokens) / 1_000_000) * pricing["output"]
    total_cost = input_cost + cached_cost + output_cost

    token_usage = {
        "model": GROK_VISION_MODEL,
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
        "input_cost": input_cost,
        "cached_cost": cached_cost,
        "output_cost": output_cost,
        "total_cost": total_cost,
        "duration": duration,
    }

    logger.info(
        "[Grok API] Model: %s | Tokens - prompt: %d (cached: %d), "
        "completion: %d, reasoning: %d, total: %d | "
        "Cost: $%.6f (in: $%.6f, cached: $%.6f, out: $%.6f)",
        GROK_VISION_MODEL, prompt_tokens, cached_tokens,
        completion_tokens, reasoning_tokens, total_tokens,
        total_cost, input_cost, cached_cost, output_cost,
    )

    # Extract content
    raw_content = result["choices"][0]["message"]["content"].strip()
    logger.info("Grok raw response:\n%s", raw_content)

    # Parse JSON from the response (handle markdown code fences)
    json_str = raw_content
    if "```" in json_str:
        # Extract content between code fences
        parts = json_str.split("```")
        for part in parts:
            stripped = part.strip()
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
            if stripped.startswith("{"):
                json_str = stripped
                break

    chain_data = json.loads(json_str)
    chain = chain_data.get("chain", [])

    logger.info("Grok decomposed edit into %d steps:", len(chain))
    for i, step in enumerate(chain, 1):
        logger.info("  Step %d: [%s] %s (nsfw_switch=%s)",
                     i, step["task"], step["prompt"], step.get("nsfw_switch", 1))

    return {
        "chain": chain,
        "token_usage": token_usage,
        "raw_response": raw_content,
    }


# ---------------------------------------------------------------------------
# Workflow helpers
# ---------------------------------------------------------------------------
def load_workflow(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def prepare_chain_step_workflow(
    template: dict,
    input_image_name: str,
    face_ref_image_name: str,
    prompt: str,
    nsfw_switch: int = 1,
    seed: int | None = None,
    width: int | None = None,
    height: int | None = None,
) -> dict:
    """Prepare the edit_final_AIO workflow for one chain step.

    Node mapping:
        8  - LoadImage (current input)     -> inputs.image
        32 - LoadImage (face reference)    -> inputs.image (always the original)
        3  - Positive prompt               -> inputs.prompt
        22 - ImpactSwitch (lora)           -> inputs.select (1=normal, 2=male NSFW, 3=female NSFW)
        2  - KSampler                      -> inputs.seed
        9  - EmptyLatentImage              -> inputs.width, inputs.height
    """
    wf = copy.deepcopy(template)

    # Node 8: input image (changes each step)
    if "8" in wf:
        wf["8"]["inputs"]["image"] = input_image_name

    # Node 32: face reference (always the original)
    if "32" in wf:
        wf["32"]["inputs"]["image"] = face_ref_image_name

    # Node 3: positive prompt
    if "3" in wf:
        wf["3"]["inputs"]["prompt"] = prompt

    # Node 22: NSFW lora switch
    if "22" in wf:
        wf["22"]["inputs"]["select"] = nsfw_switch

    # Node 2: seed
    if seed is not None and "2" in wf:
        wf["2"]["inputs"]["seed"] = seed

    # Node 9: output dimensions
    if width and height and "9" in wf:
        wf["9"]["inputs"]["width"] = width
        wf["9"]["inputs"]["height"] = height

    return wf


def execute_workflow_with_face_sim(
    client: ComfyUIClient,
    workflow: dict,
    face_sim_node: str = "26",
) -> tuple[dict[str, list[bytes]], float | None]:
    """Execute a workflow and capture face similarity from WebSocket 'executed' messages.

    ComfyUI's PreviewAny is a UI-only node — its value is NOT in the history API
    outputs. Instead, ComfyUI sends it via WebSocket as an 'executed' message:

        {"type": "executed", "data": {"node": "26", "output": {"text": ["69.63"]}, ...}}

    This function listens for that message during execution and parses the score.

    Returns:
        (output_images_dict, face_similarity_float_or_None)
    """
    if not client._ws:
        raise RuntimeError("WebSocket not connected. Call connect() first.")

    response = client.queue_prompt(workflow)
    prompt_id = response.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"Failed to queue prompt: {response}")

    logger.info("Executing workflow (prompt_id=%s), listening for face sim on node %s...",
                prompt_id, face_sim_node)

    face_sim: float | None = None

    # Listen for WS messages until execution completes
    while True:
        try:
            out = client._ws.recv()

            if isinstance(out, str):
                message = json.loads(out)
                msg_type = message.get("type")
                data = message.get("data", {})

                if msg_type == "executed":
                    # Capture UI output from PreviewAny / Face Similarity nodes
                    node_id = data.get("node")
                    output = data.get("output", {})

                    if node_id == face_sim_node and "text" in output:
                        text_val = output["text"]
                        if isinstance(text_val, list):
                            text_val = text_val[0] if text_val else ""
                        try:
                            face_sim = float(str(text_val).strip())
                            logger.info("  Captured face sim from WS node %s: %.2f%%",
                                        node_id, face_sim)
                        except (ValueError, TypeError):
                            logger.warning("  Could not parse face sim from node %s: %r",
                                           node_id, text_val)

                elif msg_type == "executing":
                    node = data.get("node")
                    current_pid = data.get("prompt_id")
                    if node is None and current_pid == prompt_id:
                        logger.info("Workflow execution complete: %s", prompt_id)
                        break

                elif msg_type == "execution_error":
                    error_msg = data.get("exception_message", "Unknown error")
                    raise RuntimeError(f"ComfyUI execution error: {error_msg}")

            # Binary data (preview frames) — skip

        except ws_module.WebSocketException as e:
            raise RuntimeError(f"WebSocket error during execution: {e}")

    # Fetch output images from history (same as ComfyUIClient.execute_workflow)
    history = client.get_history(prompt_id)
    if prompt_id not in history:
        raise RuntimeError(f"No history found for prompt: {prompt_id}")

    outputs = history[prompt_id].get("outputs", {})
    output_images: dict[str, list[bytes]] = {}

    for node_id, node_output in outputs.items():
        if "images" in node_output:
            images_output = []
            for image_info in node_output["images"]:
                try:
                    image_data = client.get_image(
                        image_info["filename"],
                        image_info.get("subfolder", ""),
                        image_info.get("type", "output"),
                    )
                    images_output.append(image_data)
                except Exception as e:
                    logger.error("Failed to retrieve image: %s", e)
            if images_output:
                output_images[node_id] = images_output

    # If we didn't get face_sim from WS, try the history as a fallback
    if face_sim is None:
        for try_node in (face_sim_node, "25"):
            node_data = outputs.get(try_node, {})
            for key in ("text", "float", "number", "value"):
                if key in node_data:
                    val = node_data[key]
                    if isinstance(val, list):
                        val = val[0] if val else None
                    if val is not None:
                        try:
                            face_sim = float(str(val).strip())
                            logger.info("  Got face sim from history node %s: %.2f%%",
                                        try_node, face_sim)
                            break
                        except (ValueError, TypeError):
                            pass
            if face_sim is not None:
                break

    return output_images, face_sim


def collect_output_image(output_images: dict, node_id: str = "6") -> bytes | None:
    """Get the first image bytes from the specified output node."""
    node_imgs = output_images.get(node_id, [])
    if node_imgs:
        return node_imgs[0]
    # Fallback: try any node
    for imgs in output_images.values():
        if imgs:
            return imgs[0]
    return None


# ---------------------------------------------------------------------------
# Google Chat notification
# ---------------------------------------------------------------------------
def send_chain_result_card(
    webhook_url: str,
    image_name: str,
    user_prompt: str,
    grok_usage: dict,
    chain_steps: list[dict],
    step_results: list[dict],
    output_urls: list[str],
    source_url: str | None = None,
    total_duration: float = 0.0,
):
    """Send a summary card to Google Chat after all chain steps complete."""

    # -- User prompt section (always visible at top) --
    prompt_widgets = [
        {
            "decoratedText": {
                "topLabel": "Original Prompt",
                "text": user_prompt,
                "wrapText": True,
            }
        },
    ]

    # -- Grok section --
    grok_widgets = [
        {"decoratedText": {"topLabel": "Model", "text": grok_usage.get("model", "N/A")}},
        {
            "decoratedText": {
                "topLabel": "Tokens (Input)",
                "text": (
                    f"Prompt: {grok_usage.get('prompt_tokens', 0):,} | "
                    f"Cached: {grok_usage.get('cached_tokens', 0):,}"
                ),
            }
        },
        {
            "decoratedText": {
                "topLabel": "Tokens (Output)",
                "text": (
                    f"Completion: {grok_usage.get('completion_tokens', 0):,} | "
                    f"Reasoning: {grok_usage.get('reasoning_tokens', 0):,}"
                ),
            }
        },
        {
            "decoratedText": {
                "topLabel": "Total Tokens",
                "text": f"{grok_usage.get('total_tokens', 0):,}",
            }
        },
        {
            "decoratedText": {
                "topLabel": "Cost (USD)",
                "text": (
                    f"In: ${grok_usage.get('input_cost', 0):.6f} | "
                    f"Cached: ${grok_usage.get('cached_cost', 0):.6f} | "
                    f"Out: ${grok_usage.get('output_cost', 0):.6f} | "
                    f"Total: ${grok_usage.get('total_cost', 0):.6f}"
                ),
            }
        },
        {
            "decoratedText": {
                "topLabel": "Grok Duration",
                "text": f"{grok_usage.get('duration', 0):.2f}s",
            }
        },
    ]

    # -- Per-step sections --
    step_widgets = []
    for i, (step_def, result) in enumerate(zip(chain_steps, step_results)):
        face_sim = result.get("face_sim")
        face_str = f"{face_sim:.2f}%" if face_sim is not None else "N/A"
        step_widgets.append({"divider": {}})
        step_widgets.append({
            "decoratedText": {
                "topLabel": f"Step {i + 1}: {step_def['task']}",
                "text": (
                    f"Prompt: {step_def['prompt']}\n"
                    f"Face sim: {face_str} | "
                    f"Duration: {result.get('duration', 0):.2f}s | "
                    f"Attempts: {result.get('attempts', 1)}"
                ),
                "wrapText": True,
            }
        })

    sections = [
        {
            "header": "Prompt",
            "widgets": prompt_widgets,
        },
        {
            "header": "Grok Vision (Token Usage)",
            "collapsible": True,
            "uncollapsibleWidgetsCount": 2,
            "widgets": grok_widgets,
        },
        {
            "header": "Chain Steps",
            "collapsible": True,
            "uncollapsibleWidgetsCount": 1,
            "widgets": step_widgets[1:] if step_widgets else [],  # skip leading divider
        },
    ]

    # Source image
    if source_url:
        sections.append({
            "header": "Source Image",
            "widgets": [
                {"image": {"imageUrl": source_url, "altText": f"Source: {image_name}"}},
            ],
        })

    # Output images (one per step)
    for i, url in enumerate(output_urls):
        sections.append({
            "header": f"Step {i + 1} Output",
            "widgets": [
                {"image": {"imageUrl": url, "altText": f"Step {i + 1}"}},
                {
                    "buttonList": {
                        "buttons": [{
                            "text": "Open",
                            "onClick": {"openLink": {"url": url}},
                        }]
                    }
                },
            ],
        })

    card = {
        "cardsV2": [{
            "cardId": f"chain-{uuid.uuid4().hex[:8]}",
            "card": {
                "header": {
                    "title": "CHAIN EDIT COMPLETE",
                    "subtitle": f"{image_name} | {total_duration:.1f}s | {len(chain_steps)} steps",
                },
                "sections": sections,
            },
        }]
    }

    resp = requests.post(webhook_url, json=card, timeout=10)
    if resp.status_code == 200:
        logger.info("Chain result sent to Google Chat")
    else:
        logger.warning("Google Chat returned %s: %s", resp.status_code, resp.text)


def send_failure_text(webhook_url: str, image_name: str, error: str):
    msg = {"text": f"*CHAIN EDIT FAILED*\n\n*Image:* {image_name}\n*Error:* {error}"}
    try:
        requests.post(webhook_url, json=msg, timeout=10)
    except Exception as e:
        logger.error("Failed to send failure notification: %s", e)


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------
def run_chain(
    image_path: str,
    user_prompt: str,
    face_threshold: float = 40.0,
    max_retries: int = 3,
    comfyui_server: str = COMFYUI_SERVER,
    notify: bool = True,
    dry_run: bool = False,
):
    """Run the full chained edit pipeline for a single image.

    Returns:
        dict with chain results, or None on failure.
    """
    image_name = os.path.basename(image_path)
    logger.info("=" * 60)
    logger.info("CHAIN EDIT: %s", image_name)
    logger.info("Prompt: %s", user_prompt)
    logger.info("Face threshold: %.1f%% | Max retries: %d", face_threshold, max_retries)
    logger.info("=" * 60)

    total_t0 = time.monotonic()

    # Step 1: Grok vision decomposition
    try:
        grok_result = call_grok_vision(image_path, user_prompt)
    except Exception as e:
        logger.error("Grok vision call failed: %s", e, exc_info=True)
        if notify and WEBHOOK_URL:
            send_failure_text(WEBHOOK_URL, image_name, f"Grok vision failed: {e}")
        return None

    chain = grok_result["chain"]
    grok_usage = grok_result["token_usage"]

    if not chain:
        logger.error("Grok returned an empty chain!")
        if notify and WEBHOOK_URL:
            send_failure_text(WEBHOOK_URL, image_name, "Grok returned empty chain")
        return None

    if dry_run:
        logger.info("\n--- DRY RUN: Grok plan ---")
        for i, step in enumerate(chain, 1):
            logger.info("  Step %d: [%s] prompt=%r nsfw_switch=%s",
                         i, step["task"], step["prompt"], step.get("nsfw_switch", 1))
        logger.info("Grok usage: %s", json.dumps(grok_usage, indent=2))
        logger.info("--- DRY RUN END (ComfyUI not called) ---")
        return {"chain": chain, "grok_usage": grok_usage, "dry_run": True}

    # Step 2: Load workflow & setup
    workflow_template = load_workflow(WORKFLOW_PATH)
    client = ComfyUIClient(server_address=comfyui_server)

    # Supabase for public URLs
    supabase = None
    if SUPABASE_URL and SUPABASE_KEY:
        supabase = SupabaseStorageService(SUPABASE_URL, SUPABASE_KEY, SUPABASE_BUCKET)

    # Read the original image bytes for uploading
    with open(image_path, "rb") as f:
        original_image_bytes = f.read()

    # Determine content type
    ext = os.path.splitext(image_path)[1].lower()
    content_type_map = {".png": "image/png", ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg", ".webp": "image/webp"}
    content_type = content_type_map.get(ext, "image/png")

    # Upload original to ComfyUI as the face reference (stays constant)
    face_ref_name = client.upload_image_bytes(
        f"chain_faceref_{image_name}", original_image_bytes, content_type
    )
    logger.info("Face reference uploaded as: %s", face_ref_name)

    # Current input starts as the original
    current_image_bytes = original_image_bytes
    current_image_name = face_ref_name  # first step uses the same upload

    # Upload source to Supabase for the notification card
    source_url = None
    if supabase:
        storage_path = f"edit_tests/sources/{image_name}"
        if supabase.image_exists(storage_path):
            source_url = supabase.get_public_url(storage_path)
        else:
            name_no_ext = os.path.splitext(image_name)[0]
            source_url, _ = supabase.upload_image(
                original_image_bytes, name_no_ext, folder="edit_tests/sources"
            )

    # Step 3: Execute chain
    step_results = []
    output_urls = []
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_outputs", "chain")
    os.makedirs(out_dir, exist_ok=True)

    try:
        client.connect()

        for step_idx, step_def in enumerate(chain):
            step_t0 = time.monotonic()
            task_name = step_def["task"]
            step_prompt = step_def["prompt"]
            nsfw_switch = step_def.get("nsfw_switch", 1)

            logger.info("\n--- Step %d/%d: %s ---", step_idx + 1, len(chain), task_name)
            logger.info("  Prompt: %s", step_prompt)
            logger.info("  NSFW switch: %d", nsfw_switch)

            # Upload current image for this step (if not the first step, re-upload)
            if step_idx > 0:
                step_filename = f"chain_step{step_idx}_{image_name}"
                current_image_name = client.upload_image_bytes(
                    step_filename, current_image_bytes, content_type
                )
                logger.info("  Uploaded step input as: %s", current_image_name)

            best_image_bytes = None
            best_face_sim = -1.0
            best_attempt = 0
            attempts = 0

            for attempt in range(1, max_retries + 1):
                attempts = attempt
                seed = random.randint(1, 999_999_999_999)
                logger.info("  Attempt %d/%d (seed=%d)", attempt, max_retries, seed)

                wf = prepare_chain_step_workflow(
                    workflow_template,
                    input_image_name=current_image_name,
                    face_ref_image_name=face_ref_name,
                    prompt=step_prompt,
                    nsfw_switch=nsfw_switch,
                    seed=seed,
                )

                # Execute and capture face similarity from WebSocket
                try:
                    output_images, face_sim = execute_workflow_with_face_sim(
                        client, wf, face_sim_node="26"
                    )
                except RuntimeError as exc:
                    logger.warning("  Attempt %d workflow failed (likely no face detected): %s", attempt, exc)
                    if attempt < max_retries:
                        logger.info("  Retrying...")
                    else:
                        logger.warning("  Max retries reached, all attempts failed.")
                    continue

                # Collect output image from node 6
                img_bytes = collect_output_image(output_images, "6")
                if not img_bytes:
                    logger.warning("  No output image from node 6, trying any node...")
                    img_bytes = collect_output_image(output_images)

                if not img_bytes:
                    logger.warning("  No output image at all for attempt %d", attempt)
                    continue

                face_str = f"{face_sim:.2f}%" if face_sim is not None else "N/A"
                logger.info("  Result: face_sim=%s, image=%d bytes", face_str, len(img_bytes))

                # Track best attempt
                current_sim = face_sim if face_sim is not None else 0.0
                if current_sim > best_face_sim:
                    best_face_sim = current_sim
                    best_image_bytes = img_bytes
                    best_attempt = attempt

                # Check threshold
                if face_sim is not None and face_sim >= face_threshold:
                    logger.info("  Face sim %.2f%% >= %.1f%% threshold -- ACCEPTED", face_sim, face_threshold)
                    break
                elif attempt < max_retries:
                    logger.info("  Face sim below threshold, retrying...")
                else:
                    logger.info("  Max retries reached. Using best attempt %d (face_sim=%.2f%%)",
                                best_attempt, best_face_sim)

            step_duration = time.monotonic() - step_t0

            if best_image_bytes is None:
                logger.error("  Step %d produced no usable output!", step_idx + 1)
                step_results.append({
                    "step": step_idx + 1,
                    "task": task_name,
                    "status": "FAILED",
                    "face_sim": None,
                    "duration": step_duration,
                    "attempts": attempts,
                })
                continue

            # Save step output locally
            local_file = os.path.join(
                out_dir,
                f"chain_{image_name}_step{step_idx + 1}_{task_name.replace(' ', '_')}.png"
            )
            with open(local_file, "wb") as f:
                f.write(best_image_bytes)
            logger.info("  Saved: %s", local_file)

            # Upload to Supabase
            step_url = None
            if supabase:
                img_id = f"chain_{uuid.uuid4().hex[:12]}_step{step_idx + 1}"
                step_url, _ = supabase.upload_image(best_image_bytes, img_id, folder="edit_tests/chain")
                logger.info("  Supabase URL: %s", step_url)
                output_urls.append(step_url)

            step_results.append({
                "step": step_idx + 1,
                "task": task_name,
                "status": "SUCCESS",
                "face_sim": best_face_sim if best_face_sim >= 0 else None,
                "duration": step_duration,
                "attempts": attempts,
                "best_attempt": best_attempt,
                "local_file": local_file,
                "url": step_url,
            })

            # Update current image for next step
            current_image_bytes = best_image_bytes
            logger.info("  Step %d complete (%.2fs, %d attempts)", step_idx + 1, step_duration, attempts)

    except Exception as e:
        logger.error("Chain execution failed: %s", e, exc_info=True)
        if notify and WEBHOOK_URL:
            send_failure_text(WEBHOOK_URL, image_name, str(e))
        return None
    finally:
        client.disconnect()

    total_duration = time.monotonic() - total_t0

    # Step 4: Summary
    logger.info("\n" + "=" * 60)
    logger.info("CHAIN SUMMARY: %s", image_name)
    logger.info("=" * 60)
    logger.info("  Total duration: %.2fs", total_duration)
    logger.info("  Grok cost: $%.6f", grok_usage["total_cost"])
    for r in step_results:
        status = r["status"]
        face_str = f"{r['face_sim']:.2f}%" if r.get("face_sim") is not None else "N/A"
        logger.info("  [%s] Step %d (%s): face_sim=%s, %.2fs, %d attempts",
                     status, r["step"], r["task"], face_str, r["duration"], r["attempts"])

    # Step 5: Notify Google Chat
    if notify and WEBHOOK_URL:
        send_chain_result_card(
            WEBHOOK_URL,
            image_name=image_name,
            user_prompt=user_prompt,
            grok_usage=grok_usage,
            chain_steps=chain,
            step_results=step_results,
            output_urls=output_urls,
            source_url=source_url,
            total_duration=total_duration,
        )

    return {
        "image": image_name,
        "chain": chain,
        "grok_usage": grok_usage,
        "step_results": step_results,
        "total_duration": total_duration,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def list_images(input_dir: str):
    """List image files in the input directory."""
    if not os.path.isdir(input_dir):
        print(f"Directory not found: {input_dir}")
        return
    files = sorted(f for f in os.listdir(input_dir)
                   if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS)
    if not files:
        print(f"No images found in {input_dir}")
        return
    print(f"\nImages in {input_dir}:")
    for i, f in enumerate(files, 1):
        size = os.path.getsize(os.path.join(input_dir, f))
        print(f"  {i:>3}. {f}  ({size:,} bytes)")
    print(f"\n  Total: {len(files)} images")


def main():
    parser = argparse.ArgumentParser(
        description="Grok-driven chained edit pipeline test",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--input-dir", required=True,
        help="Folder containing test images",
    )
    parser.add_argument(
        "--prompt", nargs="+", default=None,
        help="One or more edit prompts. Repeat for multiple:\n"
             "  --prompt \"make him naked\" \"change to bikini on beach\"",
    )
    parser.add_argument(
        "--prompts-file", default=None,
        help="Path to a JSON file with a list of prompt strings, e.g.:\n"
             '  ["make him naked outdoors", "change to red dress"]',
    )
    parser.add_argument(
        "--image", default=None,
        help="Specific image filename (default: process all images in dir)",
    )
    parser.add_argument(
        "--face-threshold", type=float, default=40.0,
        help="Face similarity threshold %% (default: 40)",
    )
    parser.add_argument(
        "--max-retries", type=int, default=3,
        help="Max regeneration attempts per step (default: 3)",
    )
    parser.add_argument(
        "--comfyui-server", default=None,
        help=f"ComfyUI server address (default: {COMFYUI_SERVER})",
    )
    parser.add_argument(
        "--no-notify", action="store_true",
        help="Skip Google Chat notifications",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Only call Grok, print plan, don't execute ComfyUI",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List images in input dir and exit",
    )
    args = parser.parse_args()

    # List mode
    if args.list:
        list_images(args.input_dir)
        sys.exit(0)

    # Build prompt list from --prompt and/or --prompts-file
    prompts: list[str] = []

    if args.prompts_file:
        pf = args.prompts_file
        if not os.path.isfile(pf):
            parser.error(f"Prompts file not found: {pf}")
        with open(pf, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            prompts.extend(str(p) for p in data)
        elif isinstance(data, dict) and "prompts" in data:
            prompts.extend(str(p) for p in data["prompts"])
        else:
            parser.error("Prompts file must be a JSON array or {\"prompts\": [...]}")

    if args.prompt:
        prompts.extend(args.prompt)

    if not prompts and not args.list:
        parser.error("At least one prompt is required (use --prompt and/or --prompts-file)")

    # Validate input dir
    if not os.path.isdir(args.input_dir):
        parser.error(f"Input directory not found: {args.input_dir}")

    # Validate API key
    if not VENICE_API_KEY:
        parser.error("VENICE_API_KEY not set in .env")

    server = args.comfyui_server or COMFYUI_SERVER
    notify = not args.no_notify

    # Resolve images
    if args.image:
        image_files = [args.image]
    else:
        image_files = sorted(
            f for f in os.listdir(args.input_dir)
            if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS
        )

    if not image_files:
        parser.error(f"No images found in {args.input_dir}")

    total_jobs = len(image_files) * len(prompts)

    logger.info("=" * 60)
    logger.info("CHAINED EDIT PIPELINE TEST")
    logger.info("=" * 60)
    logger.info("Input dir      : %s", args.input_dir)
    logger.info("Images         : %d", len(image_files))
    logger.info("Prompts        : %d", len(prompts))
    for i, p in enumerate(prompts, 1):
        logger.info("  %d. %s", i, p)
    logger.info("Total jobs     : %d (images x prompts)", total_jobs)
    logger.info("Face threshold : %.1f%%", args.face_threshold)
    logger.info("Max retries    : %d", args.max_retries)
    logger.info("ComfyUI server : %s", server)
    logger.info("Notifications  : %s", "ON" if notify else "OFF")
    logger.info("Dry run        : %s", "YES" if args.dry_run else "NO")
    logger.info("=" * 60)

    all_results = []
    job_num = 0

    for img_file in image_files:
        image_path = os.path.join(args.input_dir, img_file)
        if not os.path.isfile(image_path):
            logger.warning("Image not found, skipping: %s", image_path)
            continue

        for prompt in prompts:
            job_num += 1
            logger.info("\n>>> JOB %d/%d : %s + %r", job_num, total_jobs, img_file, prompt)

            result = run_chain(
                image_path=image_path,
                user_prompt=prompt,
                face_threshold=args.face_threshold,
                max_retries=args.max_retries,
                comfyui_server=server,
                notify=notify,
                dry_run=args.dry_run,
            )
            all_results.append({"image": img_file, "prompt": prompt, "result": result})

    # Final summary
    logger.info("\n" + "=" * 60)
    logger.info("FINAL SUMMARY  (%d jobs)", len(all_results))
    logger.info("=" * 60)
    for r in all_results:
        status = "OK" if r["result"] else "FAIL"
        logger.info("  [%s] %s  |  %s", status, r["image"], r["prompt"])

    passed = sum(1 for r in all_results if r["result"])
    logger.info("\n  %d / %d completed", passed, len(all_results))

    sys.exit(0 if passed == len(all_results) else 1)


if __name__ == "__main__":
    main()
