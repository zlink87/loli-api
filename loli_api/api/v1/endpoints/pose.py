"""
Pose edit endpoint.
POST /v1/edit/pose - Create async pose edit job using ComfyUI workflow.
"""
import copy
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from config import settings
from auth.dependencies import get_current_user
from models.enums import PoseType, JobStatus, NudityLevel, OutfitType
from models.requests import PoseEditRequest
from models.responses import JobCreateResponse
from services import pose_assets
from services import prompt_constants as pc
from services import scene_vocab as sv
from services.character_anchors import populate_identity_anchors
from services.notification_service import NotificationService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Pose Edit"])

# ---------------------------------------------------------------------------
# Global service instances (set from main.py)
# ---------------------------------------------------------------------------
_job_manager = None
_notification_service: Optional[NotificationService] = None
_pose_workflow_path: Optional[str] = None
_pose_workflow_template: Optional[dict] = None
# Optional (Supabase-gated) character store, wired in router.configure_services.
# Used only to auto-populate identityAnchors from PoseEditRequest.characterId;
# None (store not configured) degrades gracefully — see populate_identity_anchors.
_character_store = None


# ---------------------------------------------------------------------------
# Pose Descriptions - Text descriptions of each target pose, injected into the
# workflow prompt (node 114). The reference image itself is resolved and shipped
# per-request via services/pose_assets.py (worker_filename -> node 170).
#
# The canonical map now lives in services/pose_assets.py (single source of truth,
# so services and scripts never import from api/); re-exported here for back-compat
# (`pose_ep.POSE_DESCRIPTIONS` and `from api.v1.endpoints.pose import POSE_DESCRIPTIONS`).
# ---------------------------------------------------------------------------
POSE_DESCRIPTIONS: Dict[PoseType, str] = pose_assets.POSE_DESCRIPTIONS


# ---------------------------------------------------------------------------
# Service configuration functions (called from main.py via router)
# ---------------------------------------------------------------------------
def set_job_manager(job_manager) -> None:
    global _job_manager
    _job_manager = job_manager


def set_notification_service(service: NotificationService) -> None:
    global _notification_service
    _notification_service = service


def set_character_store(store) -> None:
    """Set the (optional) character store used to resolve identityAnchors."""
    global _character_store
    _character_store = store


def set_pose_workflow_path(workflow_path: str) -> None:
    global _pose_workflow_path, _pose_workflow_template
    _pose_workflow_path = workflow_path
    try:
        with open(workflow_path, 'r', encoding='utf-8') as f:
            _pose_workflow_template = json.load(f)
        logger.info(f"Loaded pose workflow template: {workflow_path}")
    except Exception as e:
        logger.error(f"Failed to load pose workflow: {e}")
        _pose_workflow_template = None


def get_job_manager():
    if _job_manager is None:
        raise RuntimeError("Job manager not initialized")
    return _job_manager


def get_notification_service() -> Optional[NotificationService]:
    return _notification_service


# State-of-UNDRESS lead words: text that BEGINS with one of these describes a naked-class
# state of dress (NAKED-tier continuity prose), not a garment. SINGLE source of truth for
# both the strict-solo prefix fallback (_pose_keeps_strict_solo) and build_pose_prompt's
# continuity phrasing below — they used to carry two hand-maintained tuples that diverged.
_UNDRESS_PREFIXES = ("completely naked", "topless", "fully nude", "nude", "naked")


# ---------------------------------------------------------------------------
# Helper functions (used by PoseBackgroundWorker via import)
# ---------------------------------------------------------------------------
def _pose_keeps_strict_solo(
    nudity_level: Optional[NudityLevel],
    outfit_text: Optional[str],
    outfit_enum: Optional[str] = None,
) -> bool:
    """
    WS-STAGE Part B nudity guard: True when the item is explicit enough that even a PUBLIC
    venue must keep the STRICT solo clause — we never place a crowd, even a soft-focus one,
    around explicit content. True when the nudity level is HIGH, OR the outfit is the NAKED
    enum.

    The outfit is checked by ENUM VALUE (``outfit_enum``) when the caller threads it (the
    batch pipeline does), which is robust even when outfit_continuity_text PREPENDS a caption
    detail — "a sheer open wrap, topless…" — that would defeat a prose-prefix sniff of
    ``outfit_text``. Only when ``outfit_enum`` is None (interactive callers that don't thread
    it) does it FALL BACK to sniffing ``outfit_text``'s leading state-of-undress word. Every
    other case -> False (the public-venue crowd clause may apply). None/unknown nudity + a
    normal garment -> False.
    """
    nl = str(getattr(nudity_level, "value", nudity_level) or "").lower()
    if nl == NudityLevel.HIGH.value:
        return True
    if outfit_enum is not None:
        return outfit_enum == OutfitType.NAKED.value
    # Fallback (interactive callers): sniff the continuity prose's leading state-of-undress
    # word. "wearing …" is a DRESSED garment and is deliberately NOT in _UNDRESS_PREFIXES.
    ot = (outfit_text or "").strip().lower()
    return ot.startswith(_UNDRESS_PREFIXES)


def build_pose_prompt(
    pose: PoseType,
    activity: Optional[str] = None,
    expression: Optional[str] = None,
    lighting: Optional[str] = None,
    time_of_day: Optional[str] = None,
    outfit_text: Optional[str] = None,
    location: Optional[str] = None,
    pose_detail: Optional[str] = None,
    identity_anchors: Optional[str] = None,
    scene_text: Optional[str] = None,
    dress_mode: bool = False,
    staging: Optional[str] = None,
    nudity_level: Optional[NudityLevel] = None,
    outfit_enum: Optional[str] = None,
    face_ref_conditioning: bool = False,
) -> str:
    """
    Build a dynamic text prompt for the pose workflow based on pose type.

    B1 (scene/outfit fidelity): the pose step is the LAST pipeline step and fully
    re-diffuses the whole frame (edit_pose_action.json: denoise 1.0, cfg 1, negatives
    inert via ConditioningZeroOut — so ONLY positive-prompt text can steer it). With
    no outfit/scene/solo language it stochastically strips clothing, re-invents the
    location, and paints in extra people from an activity like "dancing with a
    partner". This builder now carries three positive-prompt guards against that:
    a keep-the-background instruction (replacing the old "adapt the background"
    licence to re-invent it), an optional state-of-dress continuity sentence, an
    optional scene-location anchor, and an ALWAYS-ON solo constraint.

    Args:
        pose: The pose type
        activity: Optional identity-free action phrase (e.g. SceneSpec.activity,
            routed here by scene_mapper when a pose step is active) appended as
            ", while {activity}". Run through services.scene_vocab.strip_companions()
            first (defensive) so multi-person phrasing ("… with a partner",
            "… full of passersby") can't paint extra people into the solo frame;
            if that leaves nothing meaningful the clause is skipped. None = unchanged
            base prompt (interactive /v1/edit/pose never sets this).
        expression: Optional facial expression/mood or gaze state (e.g.
            SceneSpec.expression) rendered as ", her expression: {expression}".
            WS-S: the earlier ", {expression} expression" template appended the literal
            word "expression", which read fine for a bare adjective ("serious") but
            turned the multi-word candid pool states ("focused on what she's doing",
            "soft smile at the camera") into junk ("… doing expression"); the
            "her expression:" lead-in renders every state cleanly. Expression/mood
            ONLY — never facial features. Has no effect on non-posed items: the face there is
            byte-locked by the composite-back in prepare_outfit_workflow, so
            there is nothing for a prompted expression to act on outside a pose
            step. None = unchanged base prompt.
        lighting: Optional raw lighting enum-VALUE string (e.g.
            PipelineEditRequest.lighting, sourced from SceneSpec.lighting —
            values like "moody_dim"/"candlelit"/"neon"). Phrase-ified here via
            services.scene_vocab.lighting_phrase() — the SAME LIGHTING_PHRASES
            map scene_mapper.build_scene_background_text uses for the
            background step, so tone matches. WS-S de-bloat (5b): lighting and
            time_of_day now merge into ONE trailing clause ("{time} in {lighting}",
            e.g. "late at night in moody dim low-key lighting") instead of two
            separate ", in {lighting}" / ", {time}" clauses. This is the primary fix for batch photos
            always rendering bright: the pose step is the only pipeline step
            that fully re-diffuses the frame (denoise=1.0), so it is the one
            place a lighting clause can actually re-light the person instead
            of just the (person-masked-out) background. None, or a value
            absent from the map, leaves the prompt unchanged — never injects
            a raw enum string like "moody_dim" into the prompt.
        time_of_day: Optional raw time-of-day enum-VALUE string (e.g.
            PipelineEditRequest.timeOfDay, sourced from SceneSpec.time_of_day —
            values like "evening"/"night"/"golden_hour"). Phrase-ified via
            services.scene_vocab.time_of_day_phrase() and merged with lighting
            into the single trailing clause described above (the phrase already
            carries its own preposition, e.g. "at sunset" / "late at night").
            Same graceful-skip behavior as lighting.
        outfit_text: Optional garment/state-of-dress text the reposed frame must
            preserve — the outfit continuity fix. Produced by
            api.v1.endpoints.outfit.outfit_continuity_text() (the outfit_detail, or
            the outfit's nudity tier prose) and threaded here by
            workers.pipeline_worker so the full re-diffusion keeps what the outfit
            step actually rendered instead of stripping it. Phrasing adapts to the
            text: a plain garment becomes "In image 1 she is wearing {outfit_text};
            keep her state of dress and every garment exactly as in image 1, fully
            intact.", while text that already begins with a state-of-dress word
            ("completely naked"/"topless"/"wearing"/"nude" — i.e. NAKED-tier prose)
            becomes "In image 1 she is {outfit_text}; keep her state of dress exactly
            as in image 1." so a NAKED tier never reads as "wearing completely
            naked". None (no outfit step / interactive caller) appends nothing.
        location: Optional raw location enum-VALUE string (e.g.
            PipelineEditRequest.location, sourced from SceneSpec.location — values
            like "home_bedroom"/"beach"/"cafe"). Phrase-ified via
            services.scene_vocab.location_phrase() (the SAME LOCATION_PHRASES map
            the background step uses) and appended right after the keep-background
            sentence as "The scene is {location phrase}." to re-anchor the scene the
            full re-diffusion must stay in. None, or a value absent from the map,
            appends nothing (never injects a raw enum string).
        pose_detail: Optional identity-free freeform body-position/action sentence
            (e.g. SceneSpec.pose_detail via PipelineEditRequest.poseDetail). When it
            survives strip_companions (same defensive scrub as ``activity``), it
            REPLACES the canned POSE_DESCRIPTIONS[pose] text in the "The target pose
            is: {…}" sentence — the pose ENUM still picks the reference image
            (image 2); the freeform text only sharpens the described target so the
            director's own wording drives the render instead of ~16 baked phrases.
            None/empty (or companion-only after the scrub) falls back to
            POSE_DESCRIPTIONS[pose] exactly as today. Everything else in the prompt
            (keep-background, solo, outfit continuity, …) is unchanged.
        identity_anchors: Optional concrete identity-attribute phrase for THIS
            character (e.g. from services.scene_mapper.identity_anchor_text —
            "straight blonde hair, green eyes, curvy build with medium breasts").
            D1: the pose step fully re-diffuses the frame guided only by the generic
            pose_identity_clause() ("keep the original ... hair style, hair color,
            eye color ..."), which binds weakly on this distilled model — hair
            structure/color and body proportions drift photo-to-photo as a result.
            When set, rendered as "She has {anchors}; keep these and her body
            proportions and build exactly as in image 1, completely unchanged."
            WS-S de-bloat (5a): when anchors are present they REPLACE the generic
            pose_identity_clause() sentence (the anchors carry the same content, but
            concretely), rather than stacking on top of it. None/empty (interactive
            /v1/edit/pose and any caller without a character profile) keeps the
            generic clause — unchanged behavior.
        scene_text: Optional composed scene/background text (the single-pass batch
            path passes PipelineEditRequest.prompt here). When set, it REPLACES the
            "Keep the same background, location and environment as image 1…" sentence
            AND the "The scene is {location}." anchor with "Place her in: {scene_text}."
            — because in single-pass mode there is no prior background step to "keep",
            the pose step composes the scene from scratch. None (multi-step / interactive
            callers, where the background step already rendered the scene) leaves the
            keep-background + location-anchor wording byte-identical to before.
        dress_mode: Single-pass additive dressing. Default False keeps the
            state-of-dress CONTINUITY phrasing for ``outfit_text`` ("In image 1 she is
            wearing {garment}; keep her state of dress…") used when an outfit step
            already dressed the body. True (single-pass, source = nude base) flips the
            garment branch to an ADDITIVE lead ("Dress her in: {garment}; render the
            clothing fully and realistically on her body.", mirroring
            outfit._outfit_dress_lead) since there is no garment on the nude base to
            keep. The NAKED/undress-prose branch is unaffected: "In image 1 she is
            {prose}; keep her state of dress exactly as in image 1." is literally true
            against a nude-base source, so it stays verbatim in both modes.
        staging: Optional scenery-anchored fragment (e.g. SceneSpec.staging via
            PipelineEditRequest.stagingText — "perched on a bar stool at the counter")
            naming the concrete surface/furniture the pose uses. WS-STAGE: with only the
            venue named ("a vibrant nightclub…") the full-frame re-diffusion improvised
            absurd surfaces (sitting on the bar counter); this names the seat/surface
            instead. Appended to the "The target pose is: {…}" sentence — but ONLY in the
            MULTI-step path (``scene_text`` is None). In single-pass the staging already
            rides the composed "Place her in: {scene_text}" clause, so appending here too
            would DUPLICATE it; the append is suppressed there. None appends nothing.
        nudity_level: Optional NudityLevel (or its value) for the WS-STAGE Part-B solo
            policy. A public-venue scene normally swaps the strict "completely alone" solo
            clause for a "clear subject / anonymous strangers in the soft-focus background"
            clause — BUT a HIGH nudity level (or a naked-class ``outfit_text``) KEEPS the
            strict clause everywhere, so a crowd is never placed around explicit content.
            None -> treated as non-explicit (interactive callers pass none; their location
            is also None -> strict clause anyway).
        outfit_enum: Optional outfit ENUM VALUE (e.g. PipelineEditRequest.outfit's value)
            for the WS-STAGE Part-B solo policy. Threaded by the batch pipeline so
            _pose_keeps_strict_solo can detect the NAKED tier by its enum value rather than
            by prose-prefix — robust even when outfit_continuity_text prepends a caption
            detail ("a sheer open wrap, topless…") that a prefix sniff would miss. None
            (interactive callers) falls back to sniffing ``outfit_text``, unchanged behavior.
        face_ref_conditioning: WS-F. True ONLY when the loaded pose template feeds the
            hero face donor (node 210) into the prompt ENCODERS as a third conditioning
            image (image3) — i.e. ``pose_2511_skinlora_faceref_API.json``, detected by
            ``pose_template_has_face_ref_conditioning``. On that graph the hero's facial
            structure is available to the diffusion itself (not just the downstream ReActor
            stamp), so this adds one sentence binding the rendered face to image 3, fixing
            the identity slip where facial structure derived from the random-face nude base.
            False (default; the 3-step and interactive graphs have no image3 encoder input)
            appends nothing, so their prompt stays byte-identical.

    Returns:
        A descriptive prompt string for the ComfyUI workflow
    """
    desc = POSE_DESCRIPTIONS.get(pose, "natural pose")
    # Freeform pose text (C1a): the director's own body-position sentence replaces
    # the canned enum description; companion-scrubbed like `activity` so a stray
    # "… with a partner" can't paint an extra person into the solo frame.
    pose_detail_clean = sv.strip_companions(pose_detail)
    if pose_detail_clean and pose_detail_clean.strip():
        desc = pose_detail_clean.strip()
    # WS-STAGE: name the concrete surface/furniture in the target-pose sentence so the
    # full re-diffusion doesn't improvise an absurd seat. MULTI-step path ONLY: in
    # single-pass (scene_text set) the staging already rides the "Place her in:
    # {scene_text}" clause below, so appending here too would duplicate it.
    staging_clean = (staging or "").strip()
    if staging_clean and not (scene_text and scene_text.strip()):
        desc = f"{desc}, {staging_clean}"
    # Keep-the-background instruction (below) REPLACES the former "Adapt the background
    # and environment to suit the pose naturally." — that sentence was the licence the
    # full re-diffusion used to re-invent the location (bedroom -> road).
    prompt = (
        f"Make the person in image 1 do the exact same pose of the person in image 2. "
        f"The target pose is: {desc}. "
    )
    # WS-F: on the faceref graph the hero face donor (node 210) is wired into the prompt
    # ENCODERS as image3, so the diffusion itself can lock facial structure/hairline to
    # the real hero instead of deriving it from the (now random-faced) nude base — the
    # face-slip fix. Inserted right after the target-pose sentence, exactly once; the flag
    # is False on graphs without an image3 encoder input, so nothing is appended there.
    if face_ref_conditioning:
        prompt += (
            f"Her face, facial structure, and hairline are exactly those of the person "
            f"in image 3; render that same face. "
        )
    # WS-S de-bloat (5a): concrete per-character anchors (skin/hair/eyes/build) bind
    # far better than the generic pose_identity_clause() on this distilled model, and
    # they carry the SAME content specifically — so when present they REPLACE that
    # generic sentence instead of stacking on top of it (~155 chars saved). The face
    # is locked separately by the ReActor pass; outfit continuity is carried by
    # outfit_text below. No anchors (interactive /v1/edit/pose, or an un-profiled
    # character) -> keep the generic clause so identity is still anchored.
    anchors = (identity_anchors or "").strip()
    if anchors:
        prompt += (
            f"She has {anchors}; keep these and her body proportions and build "
            f"exactly as in image 1, completely unchanged. "
        )
    else:
        prompt += f"{pc.pose_identity_clause()}. "
    prompt += f"The new pose should match image 2 accurately. "
    # Scene: single-pass composes the scene from scratch ("Place her in: …") because no
    # background step ran; otherwise keep image 1's background and anchor the location.
    # (scene_text subsumes the location, so the "The scene is …" anchor is skipped there.)
    if scene_text and scene_text.strip():
        prompt += f"Place her in: {scene_text.strip()}."
    else:
        prompt += (
            f"Keep the same background, location and environment as image 1, adjusting "
            f"only perspective to fit the new pose."
        )
        # Scene-location anchor, right after the keep-background sentence.
        location_text = sv.location_phrase(location)
        if location_text:
            prompt += f" The scene is {location_text}."
    # State-of-dress. NAKED-tier prose already begins with a state word, so phrase it as
    # "she is {text}" (not "she is wearing completely naked …") — literally true against a
    # nude-base source, so it stays verbatim in dress_mode too. For a real garment,
    # dress_mode (single-pass on a nude base) dresses ADDITIVELY since there is no garment
    # to keep; the default keeps state-of-dress continuity (an outfit step already dressed).
    if outfit_text and outfit_text.strip():
        garment = outfit_text.strip()
        # Text that already leads with a state-of-dress word (a naked-class _UNDRESS_PREFIXES
        # lead, or the dressed "wearing …") is phrased "she is {text}" as-is; anything else is
        # a bare garment that gets the "she is wearing {text}" lead (branch 3).
        if garment.lower().startswith(_UNDRESS_PREFIXES + ("wearing",)):
            prompt += (
                f" In image 1 she is {garment}; keep her state of dress exactly as "
                f"in image 1."
            )
        elif dress_mode:
            prompt += (
                f" Dress her in: {garment}; render the clothing fully and "
                f"realistically on her body."
            )
        else:
            prompt += (
                f" In image 1 she is wearing {garment}; keep her state of dress and "
                f"every garment exactly as in image 1, fully intact."
            )
    # Solo constraint (ALWAYS present) + trailing scene descriptors, composed as ONE
    # clean sentence. WS-S junk fix (4): the expression renders as "her expression:
    # {state}" — the old ", {state} expression" tail turned multi-word candid states
    # like "focused on what she's doing" into junk ("… doing expression"). WS-S
    # de-bloat (5b): lighting + time-of-day merge into a single clause. Composing the
    # tail as part of the solo sentence also drops the old "…no other people., while…"
    # period-then-comma artifact. Every tail bit is non-empty (guarded), so no ", ,".
    #
    # WS-STAGE Part B: an inherently-populated PUBLIC venue makes a strict "completely
    # alone" instruction self-contradictory (the model rendered a nightclub crowd anyway),
    # so there she becomes the clear subject with anonymous strangers kept in the
    # soft-focus background. Private venues keep the STRICT clause. NUDITY GUARD: HIGH
    # nudity or a naked-class outfit KEEPS strict solo everywhere — never a crowd around
    # explicit content. location None/unknown (interactive callers) -> private -> strict.
    if sv.is_public_venue(location) and not _pose_keeps_strict_solo(
        nudity_level, outfit_text, outfit_enum
    ):
        solo = (
            "She is the clear subject, sharp and in focus; any other people are anonymous "
            "strangers in the soft-focus background, never interacting with her, never "
            "touching her, no other person near the camera"
        )
    else:
        solo = "She is completely alone in the frame — exactly one person, no other people"
    tail: List[str] = []
    # Defensive companion scrub before the activity clause folds in (a stray
    # "… with a partner" would otherwise re-add the extra person the solo forbids).
    activity_clean = sv.strip_companions(activity)
    if activity_clean and activity_clean.strip():
        tail.append(f"while {activity_clean.strip()}")
    if expression and expression.strip():
        tail.append(f"her expression: {expression.strip()}")
    lighting_text = sv.lighting_phrase(lighting)
    time_of_day_text = sv.time_of_day_phrase(time_of_day)
    if lighting_text and time_of_day_text:
        tail.append(f"{time_of_day_text} in {lighting_text}")
    elif lighting_text:
        tail.append(f"in {lighting_text}")
    elif time_of_day_text:
        tail.append(time_of_day_text)
    if tail:
        prompt += f" {solo}, " + ", ".join(tail) + "."
    else:
        prompt += f" {solo}."
    return prompt


def get_pose_reference(pose: PoseType) -> str:
    """
    Get the reference image filename (flat name) for a pose.

    The actual PNG bytes are shipped per-request as a base64 ``input.images[]``
    entry (see services/pose_assets.py); this returns the flat filename that the
    workflow's LoadImage node (170) should reference.

    Args:
        pose: The pose type

    Returns:
        ComfyUI input filename for the reference pose image
        (e.g. ``pose_ref_sitting.png``)

    Raises:
        ValueError: if ``pose`` is not a known PoseType member (kept for the
            existing 422 mapping in ``edit_pose``).
    """
    if not isinstance(pose, PoseType):
        raise ValueError(f"No reference image for pose: {pose}")
    return pose_assets.worker_filename(pose)


def _is_pose_2511_template(template: dict) -> bool:
    """
    True if this is the Tier-A 2511 pose graph (``pose_2511_API.json``).

    Marker: node "301" is a UNETLoader (the native non-distilled Qwen-Image-Edit-2511
    stack), present on the 2511 pose graph but NOT on the v1 Rapid pose graph
    (edit_pose_action.json loads its checkpoint via CheckpointLoaderSimple at node
    163). Mirrors ``_is_cropstitch_template``'s node-id + class_type approach so a
    single ``prepare_pose_workflow`` can drive BOTH templates and branch only where
    the graphs genuinely differ (the live negative — see the D3 NOTE below).
    """
    node = template.get("301")
    return bool(node and node.get("class_type") == "UNETLoader")


def pose_template_has_face_ref_conditioning(template: dict) -> bool:
    """
    WS-F: True when this pose template feeds the hero face donor (node 210) into the
    prompt ENCODERS as a third conditioning image — i.e. node 114's inputs carry an
    ``image3`` wire (``pose_2511_skinlora_faceref_API.json``). On such a graph the
    diffusion itself can lock facial structure to the real hero, so the caller
    (pipeline_worker) flips ``build_pose_prompt(face_ref_conditioning=True)`` to add the
    matching "render that same face" sentence. Every other pose graph — the 3-step
    skinlora/faceboost variants and the interactive v1/2511 graphs — has no image3
    encoder input (node 210 there feeds ONLY the downstream ReActor stamp, node 200), so
    this returns False and their prompt is unchanged. Detected off node 114 specifically
    (the positive encoder) — the single node whose image3 presence gates the clause.
    """
    return "image3" in template.get("114", {}).get("inputs", {})


# Turbo finishing pass (07-14, ships DARK). The turbofinish pose graph
# (pose_2511_skinlora_faceref_turbofinish_API.json) inserts a LOW-denoise Z-Image-Turbo
# img2img refine between the Qwen VAEDecode (node 8) and the ReActor swap (node 200): a
# plain CLIPTextEncode (node "404", the turbo positive) whose text the preparer mirrors
# from node 114, and a BasicScheduler (node "407") whose ``denoise`` float carries the
# refine strength (graph bakes 0.32). Both node ids are absent from EVERY other pose
# template, so the two writes in prepare_pose_workflow are strictly presence-gated and a
# byte-identical no-op elsewhere. Detected off node 404 specifically (a CLIPTextEncode —
# distinct from node 114's TextEncodeQwenImageEditPlus), mirroring how the face-ref clause
# is detected off node 114.
_TURBO_FINISH_POS_NODE = "404"
_TURBO_FINISH_DENOISE_NODE = "407"


def pose_template_has_turbo_finish(template: dict) -> bool:
    """
    True when this pose template carries the Z-Image-Turbo finishing pass — i.e. node 404
    (the turbo positive CLIPTextEncode the preparer mirrors node 114's text into) exists.
    Only pose_2511_skinlora_faceref_turbofinish_API.json ships it; every other pose graph
    returns False, so the turbo writes in prepare_pose_workflow no-op there.
    """
    node = template.get(_TURBO_FINISH_POS_NODE)
    return bool(node) and node.get("class_type") == "CLIPTextEncode"


# WS-N2: style-scaled LoRA strengths. Natural/candid_phone renders otherwise look
# editorial/contrasty because the pose graph's LoRA stack (node 304 URP / 305 NSFW /
# 306 skin) applies its baked strengths identically to every style. For those two styles
# ONLY, the stack is dialed DOWN to the settings.NATURAL_LORA_* values; the -1.0 sentinel
# on any one leaves that node's baked strength alone (skipped from the override dict).
# polished/studio/None -> None (baked strengths untouched). Keyed by ComfyUI node id so
# the result drops straight into prepare_pose_workflow(lora_scales=...) / the outfit
# preparer's lora_scales kwarg — the SAME map drives the pose AND outfit 2511 graphs,
# whose 304/305/306 LoRA nodes are the identical URP/NSFW/skin stack.
#
# Lives HERE (the pose endpoint that already owns build_pose_prompt / prepare_pose_workflow)
# as the single source of truth: pipeline_worker, pose_worker, and outfit_worker all import
# it from here rather than duplicating the decision or importing worker->worker.
_NATURAL_LORA_STYLES = ("natural", "candid_phone")
_NATURAL_LORA_NODE_SETTINGS = (
    ("304", "NATURAL_LORA_URP"),
    ("305", "NATURAL_LORA_NSFW"),
    ("306", "NATURAL_LORA_SKIN"),
)


def _natural_lora_scales(photo_style) -> Optional[Dict[str, float]]:
    """
    Return the {node_id: strength_model} LoRA overrides for a de-synthetic natural/candid
    render, or None for any other style. Accepts a PhotoStyleType or its string value
    (normalized the same way ``apply_edit_photo_style`` normalizes it). Each LoRA node is
    included only when its ``settings.NATURAL_LORA_*`` value is a real strength (>= 0); the
    -1.0 sentinel means "leave that node's baked strength alone" and skips it. A non-natural
    style, or an all-sentinel config, yields None (nothing overridden).
    """
    key = getattr(photo_style, "value", photo_style)
    if key not in _NATURAL_LORA_STYLES:
        return None
    scales: Dict[str, float] = {}
    for nid, attr in _NATURAL_LORA_NODE_SETTINGS:
        v = getattr(settings, attr, -1.0)
        if v is not None and float(v) >= 0:
            scales[nid] = float(v)
    return scales or None


# NOTE (W7 / D3): The v1 pose graph (edit_pose_action.json) has NO negative
# conditioning BY DESIGN — it runs the KSampler at cfg=1 and routes the negative
# branch through ConditioningZeroOut, so any negative-prompt text is mathematically
# inert. On that graph PoseEditRequest.negativePrompt stays accepted-but-unwired:
# the injection block below is gated on ``_is_pose_2511_template`` and NEVER touches
# the v1 template. Do NOT wire a negative into the v1 graph without also raising its
# cfg above 1 AND adding a real negative encoder node — that would change the sampler
# math. The Tier-A pose graph (pose_2511_API.json) satisfies exactly those two
# preconditions (cfg 2.5 + a real TextEncodeQwenImageEditPlus negative at node 115),
# so the negative IS wired there — this is the one place the pose step's negatives
# come alive, and only when that template is loaded.
def prepare_pose_workflow(
    template: dict,
    source_image: str,
    reference_image: str,
    prompt: Optional[str] = None,
    seed: Optional[int] = None,
    debug_save_pre_reactor: bool = False,
    reactor_restore_visibility: float = -1.0,
    reactor_codeformer_weight: float = -1.0,
    negative_prompt: Optional[str] = None,
    nudity_level: Optional[NudityLevel] = None,
    face_ref_image: Optional[str] = None,
    output_megapixels: Optional[float] = None,
    face_restore_model: Optional[str] = None,
    lora_scales: Optional[Dict[str, float]] = None,
    turbo_finish_denoise: Optional[float] = None,
    cfg_scale: Optional[float] = None,
    anatomy_lora_name: Optional[str] = None,
    anatomy_lora_strength: float = 0.0,
) -> dict:
    """
    Prepare the pose workflow with injected parameters.

    Workflow nodes:
        109  LoadImage        -> inputs.image  (source character image = image1)
        170  LoadImage        -> inputs.image  (reference pose image = image2)
        210  LoadImage        -> inputs.image  (WS-S ReActor face donor = the sharp
                                  original hero; node 200.source_image reads it)
        93   ImageScaleToTotalPixels -> inputs.megapixels  (output canvas size;
                                  optional override via ``output_megapixels``)
        114  CLIPTextEncode (or similar) -> inputs.prompt  (positive text prompt)
        115  TextEncodeQwenImageEditPlus -> inputs.prompt  (LIVE negative; 2511 tier ONLY)
        3    KSampler         -> inputs.seed
        8    VAEDecode        -> the PRE-ReActor frame (raw pose regen)
        200  ReActorFaceSwap  -> inputs.face_restore_visibility / codeformer_weight;
                                  source_image (face donor) rewired to node 210
        164  SaveImage        -> the POST-ReActor final output (images=["200",0])
        300  SaveImage        -> WS4.1 debug-only node, injected when
                                  debug_save_pre_reactor=True (images=["8",0])

    This preparer drives BOTH pose templates off the SAME node-id contract
    (109/170/114/3/8/200/164): the v1 Rapid graph (edit_pose_action.json) and the
    Tier-A graph (pose_2511_API.json). The ONLY tier-specific branch is the negative:
    node 115 (a real negative encoder) exists solely on the 2511 graph and is wired
    from ``pc.edit_negative(...)`` only when ``_is_pose_2511_template`` is true. On v1
    (no node 115, cfg 1) nothing is injected, so v1 stays byte-identical to before.

    Args:
        template: Base workflow template
        source_image: ComfyUI filename for source character image
        reference_image: ComfyUI filename for reference pose image
        prompt: Optional text prompt to inject into node 114
        seed: Optional seed value
        debug_save_pre_reactor: WS4.1 diagnostic flag (default OFF). When
            True, injects a second SaveImage node ("300") reading node 8
            (VAEDecode) directly — the pose regen BEFORE the ReActor
            face-swap runs — so it can be compared against the normal node
            164 (post-swap) output to classify face-misalignment causes.
            False (default) leaves the workflow byte-identical to before
            this param existed.
        reactor_restore_visibility: WS4.2 tuning knob (default -1.0 = no
            override). When >= 0, overrides node 200's
            ``face_restore_visibility`` (template default ~0.65) — how strongly
            the CodeFormer-restored face is blended over the raw swap, so a
            LOWER value keeps more of the raw swap's real skin texture.
        reactor_codeformer_weight: WS4.2 tuning knob (default -1.0 = no
            override). When >= 0, overrides node 200's ``codeformer_weight``
            (template default ~0.7). CodeFormer weight is easy to get backwards:
            a HIGHER value stays faithful to the swapped input face (less
            hallucinated repaint), a LOWER value smooths/hallucinates more (the
            plastic look).
        negative_prompt: D3, 2511-tier ONLY. Optional extra negative terms folded
            into ``pc.edit_negative(...)`` and written to node 115's prompt. On the
            v1 graph this is ignored entirely (no node 115; cfg 1 makes negatives
            inert — see the W7/D3 NOTE above). None = the full standard edit negative
            (quality + adult + identity + skin + nudity-tier) with no extra terms.
        nudity_level: D3, 2511-tier ONLY. NudityLevel (or None = 'low') selecting the
            nudity-suppression block inside ``pc.edit_negative(...)`` for node 115.
            Ignored on the v1 graph.
        face_ref_image: WS-S. ComfyUI filename of the DEDICATED face donor for the
            ReActor pass (node 200.source_image reads node 210). This is the sharp
            ORIGINAL hero photo, threaded so the face is swapped from a clean source
            instead of the already-multiply-edited pipeline intermediate (node 109),
            which inswapper's 128px paste otherwise compounds into a blurred/repainted
            face across every batch item. None (interactive /v1/edit/pose, or any
            caller that doesn't supply one) -> node 210 falls back to ``source_image``,
            i.e. byte-identical to the pre-WS-S behavior (ReActor donor == the source).
            No-op when the template has no node 210.
        output_megapixels: Optional output-canvas size for node 93
            (ImageScaleToTotalPixels). When set > 0, overrides node 93's
            ``megapixels`` (both pose graphs bake 1.0) so the full re-diffusion
            renders at a higher resolution — used by the single-pass batch path
            (prod sets ~1.74). None or <= 0 (default) leaves node 93 untouched,
            keeping the template's baked size. No-op when the template has no
            node 93.
        face_restore_model: Dark asset (07-14, ships OFF). Optional override for
            node 200's ``face_restore_model`` (the CodeFormer/GPEN model ReActor
            runs after the raw swap). Falsy/None (default, interactive callers and
            every caller until ops flips ``settings.POSE_REACTOR_FACE_RESTORE_MODEL``)
            leaves the template's baked model (``codeformer-v0.1.0.pth``) untouched.
            A truthy value (e.g. "GPEN-BFR-512.onnx") overrides it — REQUIRES that
            file to exist in facerestore_models/ on the RunPod volume first. No-op
            when the template has no node 200.
        lora_scales: WS-N2. Optional {node_id: strength_model} overrides for the pose
            graph's LoRA stack (node 304 URP / 305 NSFW / 306 skin on the skinlora tier).
            For each node id present in BOTH this dict AND the workflow, writes
            ``wf[nid]["inputs"]["strength_model"] = float(v)`` — used by the batch pipeline
            to dial the whole stack DOWN for natural/candid styles (which otherwise render
            editorial/contrasty because the baked strengths apply identically to every
            style). None/empty (default, and every polished/studio/interactive caller)
            touches nothing. A true no-op on graphs lacking those nodes (the v1 Rapid pose
            graph has none of them), so it never raises there.
        turbo_finish_denoise: Turbo finishing pass (07-14, ships DARK), turbofinish pose
            graph ONLY. Optional override for node 407 (BasicScheduler.denoise) — the
            single scalar carrying the low-denoise Z-Image-Turbo re-skin strength (graph
            bakes 0.32). >= 0 writes node 407's ``denoise``; None / the -1.0 sentinel
            (default, and every caller until ops flips ``settings.POSE_TURBO_FINISH_DENOISE``)
            leaves the baked 0.32 untouched (0.0 is itself a valid denoise, so it can't
            double as "no override"). Independent of this knob, whenever node 404 (the
            turbo positive CLIPTextEncode) is present its text is mirrored from the pose
            positive ``prompt`` so Turbo re-skins under the SAME positive Qwen composed
            under. Both writes are presence-gated: a true no-op (byte-identical) on every
            pose graph without nodes 404/407.

    Returns:
        Prepared workflow dict
    """
    wf = copy.deepcopy(template)

    # Node 109: Source character image
    if "109" in wf:
        wf["109"]["inputs"]["image"] = source_image
        logger.debug(f"Set node 109 source image: {source_image}")

    # Node 170: Reference pose image
    if "170" in wf:
        wf["170"]["inputs"]["image"] = reference_image
        logger.debug(f"Set node 170 reference image: {reference_image}")

    # Node 210 (WS-S): dedicated ReActor face donor. node 200.source_image is rewired
    # in the graph JSON to read node 210 instead of node 109, so the hero's face is
    # swapped from a CLEAN source. Falls back to the step source image when no face ref
    # is supplied (interactive callers), reproducing the pre-WS-S donor==source
    # behavior exactly. Guarded on node presence so templates without 210 (test
    # stand-ins) degrade to a no-op.
    if "210" in wf:
        donor = face_ref_image or source_image
        wf["210"]["inputs"]["image"] = donor
        logger.debug(f"Set node 210 ReActor face donor: {donor}")

    # Node 93 (ImageScaleToTotalPixels): optional output-canvas override. Both pose
    # graphs bake megapixels=1.0; a value > 0 scales the pose-reference-derived latent
    # up so the full re-diffusion renders larger (single-pass batch path). None / <= 0
    # leaves it untouched. Guarded on node presence so a template without 93 no-ops.
    if output_megapixels is not None and output_megapixels > 0 and "93" in wf:
        wf["93"]["inputs"]["megapixels"] = float(output_megapixels)
        logger.debug(f"Set node 93 megapixels: {float(output_megapixels)}")

    # WS-N2: style-scaled LoRA strengths. For each {node_id: strength} pair present in
    # BOTH the dict and this workflow, override that LoRA node's strength_model — the
    # batch path dials the URP/NSFW/skin stack (304/305/306) DOWN for natural/candid so
    # the render stops looking editorial. Guarded on node presence, so it is a true
    # no-op on graphs without those nodes (e.g. the v1 Rapid pose graph); None/empty
    # (the default and every polished/studio/interactive caller) skips the loop entirely.
    if lora_scales:
        for nid, v in lora_scales.items():
            node = wf.get(nid)
            if node and isinstance(node.get("inputs"), dict):
                node["inputs"]["strength_model"] = float(v)
                logger.debug(f"Set node {nid} strength_model: {float(v)}")

    # Node 114: Text prompt
    if prompt is not None and "114" in wf:
        wf["114"]["inputs"]["prompt"] = prompt
        logger.debug(f"Set node 114 prompt: {prompt[:80]}...")

    # Node 404 (turbo finishing pass, ships DARK): the low-denoise Z-Image-Turbo refine
    # re-skins the Qwen render with Turbo's natural prior BEFORE the ReActor swap. Turbo
    # keeps doing NOTHING to composition — Qwen owns pose/outfit/scene — so its positive
    # CLIPTextEncode must carry the SAME text as node 114. Mirror the pose positive prompt
    # into it (node 404's field is ``text``, vs node 114's ``prompt``). Present ONLY on
    # pose_2511_skinlora_faceref_turbofinish_API.json; every other template no-ops.
    if prompt is not None and _TURBO_FINISH_POS_NODE in wf:
        wf[_TURBO_FINISH_POS_NODE]["inputs"]["text"] = prompt
        logger.debug(
            f"Set node {_TURBO_FINISH_POS_NODE} turbo-finish prompt: {prompt[:60]}..."
        )

    # Node 407 (turbo finishing pass): optional refine-strength override. The turbo img2img
    # denoise (BasicScheduler.denoise) is the single scalar tuning how hard Turbo re-skins;
    # the graph bakes 0.32. >= 0 overrides it; None / the -1.0 sentinel leaves the baked
    # value (0.0 is a valid denoise, so it can't be the no-override marker). Presence-gated,
    # so a no-op on every non-turbofinish template.
    if (
        turbo_finish_denoise is not None
        and turbo_finish_denoise >= 0
        and _TURBO_FINISH_DENOISE_NODE in wf
    ):
        wf[_TURBO_FINISH_DENOISE_NODE]["inputs"]["denoise"] = float(turbo_finish_denoise)
        logger.debug(
            f"Set node {_TURBO_FINISH_DENOISE_NODE} turbo-finish denoise: "
            f"{float(turbo_finish_denoise)}"
        )

    # CFG experiment knob (07-14): >0 overrides the sampler's baked cfg on the
    # 2511 tier ONLY (node 3, baked 2.5) so glam/contrast can be A/B'd at
    # 2.0-2.2 via POSE_CFG_SCALE. Double-gated on the 2511 template marker: the
    # distilled v1 Rapid graph samples at cfg 1 BY DESIGN and must never be
    # overridden (any other cfg there wrecks the distilled schedule).
    if (
        cfg_scale is not None
        and cfg_scale > 0
        and _is_pose_2511_template(wf)
        and "3" in wf
    ):
        wf["3"]["inputs"]["cfg"] = float(cfg_scale)
        logger.debug(f"Set node 3 cfg: {float(cfg_scale)} (2511 tier)")

    # Anatomy-detail LoRA slot (07-14, ships DARK): when a LoRA filename is
    # configured AND the caller passed one (the batch path passes it only for
    # explicit-tier items — see pipeline_worker), splice node 307
    # (LoraLoaderModelOnly) into the stack after node 306 (skin LoRA) and
    # repoint every consumer of ["306", 0] to ["307", 0]. Injection (rather
    # than baking the node into the graph JSON) is deliberate: ComfyUI
    # validates LoRA filenames against the volume at job time, so a baked node
    # naming a not-yet-staged file would fail EVERY render — injected, the
    # node exists only on requests that want it, after ops stages the file.
    # Requires the skinlora-family stack (node 306); no-op elsewhere.
    if anatomy_lora_name and "306" in wf and "307" not in wf:
        for node in wf.values():
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                continue
            for key, val in inputs.items():
                if isinstance(val, list) and val == ["306", 0]:
                    inputs[key] = ["307", 0]
        wf["307"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "lora_name": anatomy_lora_name,
                "strength_model": float(anatomy_lora_strength),
                "model": ["306", 0],
            },
        }
        logger.debug(
            f"Injected anatomy LoRA node 307: {anatomy_lora_name} "
            f"@ {float(anatomy_lora_strength)}"
        )

    # Node 115: LIVE negative — Tier-A (2511) pose graph ONLY. The v1 Rapid graph
    # has no node 115 and samples at cfg 1 (negatives inert), so this is gated on
    # the 2511 template marker AND on the node's presence, and never touches v1
    # (see the W7/D3 NOTE above). pc.edit_negative folds the standard
    # quality/adult/identity/skin + nudity-tier negatives with any request extra.
    if _is_pose_2511_template(wf) and "115" in wf:
        wf["115"]["inputs"]["prompt"] = pc.edit_negative(
            negative_prompt, nudity_level=nudity_level
        )
        logger.debug("Set node 115 live negative (2511 pose tier)")

    # Node 3: Seed + quality bump.
    if "3" in wf:
        if seed is not None:
            wf["3"]["inputs"]["seed"] = seed
            logger.debug(f"Set node 3 seed: {seed}")
        # Bump steps for fewer artifacts. The pose step is a full-frame re-diffusion
        # (node 3 denoise=1.0) with no mask to confine it and inert negatives (cfg=1),
        # so it is the dominant source of extra-limb / anatomy artifacts in a batch.
        # More steps is the main lever we have here (denoise can't drop — it's a genuine
        # pose transfer — and cfg can't rise on this distilled checkpoint). 4 -> 8.
        # This is a v1-tier nudge: the Tier-A 2511 pose graph already bakes 20 steps
        # (>= 8), so the guard is a no-op there and leaves its sampler untouched.
        try:
            if int(wf["3"]["inputs"].get("steps", 0)) < 8:
                wf["3"]["inputs"]["steps"] = 8
                logger.debug("Bumped pose KSampler steps to 8")
        except (TypeError, ValueError):
            pass

    # WS4.1: optional pre-ReActor debug capture. Injects a second SaveImage
    # reading directly off node 8 (VAEDecode, the raw pose regen BEFORE the
    # ReActor face-swap) so it can be compared against the normal node 164
    # output (post-swap) when classifying face-misalignment causes (inswapper
    # low-res paste / codeformer over-restoration / blend-seam / head-angle
    # mismatch). Node id "300" is free (see module's verified node map).
    # Mirrors node 164's exact dict shape (inputs/class_type/_meta). Guarded
    # on "8" being present so an unexpected/future template shape degrades to
    # a no-op instead of a KeyError; default False -> no node 300 at all, so
    # the workflow is byte-identical to before this param existed.
    if debug_save_pre_reactor and "8" in wf:
        wf["300"] = {
            "inputs": {
                "images": ["8", 0],
                "filename_prefix": "pose_preface",
            },
            "class_type": "SaveImage",
            "_meta": {"title": "Save Image (pre-ReActor debug)"},
        }
        logger.debug("Injected debug SaveImage node 300 (pre-ReActor frame, prefix=pose_preface)")

    # WS4.2: optional ReActor tuning knobs (node 200). >= 0 overrides the
    # template's baked face_restore_visibility (0.65) / codeformer_weight
    # (0.7); the default -1.0 sentinel leaves them untouched (0.0 is itself
    # a valid override, so it can't double as "no override" here). CodeFormer
    # weight is inverse to intuition: HIGH = faithful to the swap, LOW = plastic;
    # visibility is the restored-over-raw blend (lower = more raw texture).
    # Guarded on "200" being present for the same reason as the debug node above.
    if "200" in wf:
        if reactor_restore_visibility >= 0:
            wf["200"]["inputs"]["face_restore_visibility"] = reactor_restore_visibility
            logger.debug(
                f"Overrode node 200 face_restore_visibility: {reactor_restore_visibility}"
            )
        if reactor_codeformer_weight >= 0:
            wf["200"]["inputs"]["codeformer_weight"] = reactor_codeformer_weight
            logger.debug(
                f"Overrode node 200 codeformer_weight: {reactor_codeformer_weight}"
            )
        # Dark asset (07-14, ships OFF): sharper face-restore model override (GPEN-BFR
        # vs. the template's baked CodeFormer). Falsy/None -> untouched, byte-identical
        # to before this param existed.
        if face_restore_model:
            wf["200"]["inputs"]["face_restore_model"] = face_restore_model
            logger.debug(f"Overrode node 200 face_restore_model: {face_restore_model}")

    return wf


# ---------------------------------------------------------------------------
# API Endpoint
# ---------------------------------------------------------------------------
@router.post(
    "/edit/pose",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create pose edit job",
    description="""
Submit a pose edit request. Returns immediately with job ID for polling.

The job is queued and processed asynchronously. Use GET /v1/jobs/{jobId} to poll for status.

**Flow:**
1. Submit request with source image and target pose
2. Receive jobId immediately (202 Accepted)
3. Poll GET /v1/jobs/{jobId} for status
4. When status is 'succeeded', access preview_url to see the image
    """,
    responses={
        202: {"description": "Job created successfully", "model": JobCreateResponse},
        401: {"description": "Unauthorized - Invalid or missing JWT token"},
        422: {"description": "Validation error - Invalid request body"},
        429: {"description": "Too many requests - Queue is full"},
        500: {"description": "Internal server error"},
    },
)
async def edit_pose(
    request: PoseEditRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    job_manager = get_job_manager()
    user_id = current_user.get("sub", "anonymous")

    try:
        if job_manager.is_queue_full(job_type="pose_edit"):
            logger.warning(f"Pose queue full, rejecting request from user {user_id}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Pose edit queue is full. Please try again later.",
            )

        # Validate reference image exists for the pose
        try:
            get_pose_reference(request.pose)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )

        # Validate the pose reference asset is actually installed on disk (the POSE PACK ref
        # latch). References ship per-request as base64; a missing PNG means the generator has
        # not been run for this pose yet (e.g. a newly added "dark" pose), so fail fast with a
        # clear 422 instead of a later worker crash. Single-sourced via has_pose_ref so the
        # endpoint gate and the planner pool latch use the exact same predicate.
        if not pose_assets.has_pose_ref(request.pose):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Pose reference not installed for pose '{request.pose.value}'. "
                    f"Run scripts/generate_pose_refs.py."
                ),
            )

        # Trait-aware edit: resolve identityAnchors from characterId when the caller
        # supplied an id but not explicit anchors (best-effort; never raises). The
        # pose step's build_pose_prompt already consumes request.identityAnchors.
        await populate_identity_anchors(_character_store, request)

        # Log payload
        notification_service = get_notification_service()
        if notification_service:
            payload_dict = request.model_dump(mode="json")
            await notification_service.send_request_received(user_id, payload_dict)

        # Create job
        job = await job_manager.create_job(request, user_id, job_type="pose_edit")

        logger.info(
            f"Created pose edit job {job.job_id} for user {user_id} "
            f"(pose: {request.pose.value})"
        )

        return JobCreateResponse(
            jobId=job.job_id,
            status=JobStatus.QUEUED,
            reviewRequired=False,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating pose job for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create pose edit job. Please try again.",
        )
