"""
Pure, offline helpers that classify a LOADED ComfyUI workflow template: which
rendering tier it is and what sampler settings it carries.

WHY THIS EXISTS: the outfit workflow path resolves through a precedence chain
(Tier-A full-2511 -> Rapid V2 crop-and-stitch -> V1 whole-frame; see main.py) and
a mis-deployed environment (e.g. a CI-built image without the gitignored .env)
can silently fall back to the weakest tier while every log line upstream keeps
printing the same "outfit workflow" text regardless of which file actually
loaded. ``describe_template`` gives callers (pipeline_worker, batch engine,
main.py's startup banner, the /debug/workflow-config endpoint) a single,
testable source of truth for "what did we actually load" instead of everyone
re-deriving it ad hoc.

Deliberately import-free of api.v1.endpoints.* (endpoint modules pull in
FastAPI routing / auth / request models): the crop-stitch check below is a
small, self-contained reimplementation of
``api.v1.endpoints.outfit._is_cropstitch_template`` rather than an import of
it, so this module can be imported from anywhere (workers, main.py, tests)
without dragging in the route stack. Keep the two in sync if the graph's node
IDs ever change.
"""
from typing import Any, Dict, Optional

# Node IDs are stable contract points shared with api/v1/endpoints/outfit.py
# (prepare_outfit_workflow / prepare_outfit_cropstitch_workflow) and
# api/v1/endpoints/pose.py (prepare_pose_workflow) — see those modules' docstrings
# for the full node map of each graph.
_NODE_2511_MARKER = "301"       # UNETLoader — the native 2511 stack (outfit OR pose graph)
_NODE_CROPSTITCH_MARKER = "235"  # InpaintCropImproved — crop-and-stitch graphs (V2 / 2511full)
_NODE_REACTOR_MARKER = "200"     # ReActorFaceSwap — present ONLY on pose graphs (v1 + 2511)
_NODE_SAMPLER_PRIMARY = "106"    # KSampler on outfit/background/V1 graphs
_NODE_SAMPLER_POSE = "3"         # KSampler on the pose graph (edit_pose_action.json / pose_2511)

TIER_2511FULL = "2511full"
TIER_RAPID_CROPSTITCH = "rapid_cropstitch"
# Pose step is classified on its OWN axis (it has no outfit tier concept): the v1
# Rapid pose graph (edit_pose_action.json) falls into TIER_V1 like before, while the
# Tier-A pose graph (pose_2511_API.json) reports TIER_POSE_2511 so batch A/Bs are
# identifiable in character_images.metadata -> workflow_meta -> steps[].tier.
TIER_POSE_2511 = "pose_2511"
TIER_V1 = "v1"
TIER_UNKNOWN = "unknown"

_EMPTY_SAMPLER: Dict[str, Optional[float]] = {"steps": None, "cfg": None, "denoise": None}


def _is_cropstitch_template(template: dict) -> bool:
    """
    True if this is a crop-and-stitch graph (has InpaintCropImproved at node 235).

    Mirrors ``api.v1.endpoints.outfit._is_cropstitch_template`` exactly (same
    node id, same class_type check) — reimplemented locally rather than
    imported so this module stays free of endpoint-layer dependencies (see
    module docstring).
    """
    node = template.get(_NODE_CROPSTITCH_MARKER)
    return bool(node and node.get("class_type") == "InpaintCropImproved")


def _is_pose_template(template: dict) -> bool:
    """
    True if this is a pose graph (has ReActorFaceSwap at node 200).

    Node 200 is ReActorFaceSwap ONLY on the pose graphs (edit_pose_action.json and
    pose_2511_API.json); on every outfit/background template node 200 is a
    SAMModelLoader, so this cleanly separates the pose step's own tier axis from the
    outfit tier chain below. Mirrors ``api.v1.endpoints.pose._is_pose_2511_template``'s
    marker approach (see that module for the pose node map).
    """
    node = template.get(_NODE_REACTOR_MARKER)
    return bool(node and node.get("class_type") == "ReActorFaceSwap")


def _sampler_inputs(template: dict) -> Dict[str, Optional[float]]:
    """
    Read steps/cfg/denoise off the KSampler node.

    Node "106" is the sampler on the outfit/background/V1 graphs; the pose
    graph (edit_pose_action.json) has no node "106" and carries its sampler at
    node "3" instead, so that's the fallback. Any missing node/key yields None
    rather than raising, so a template from an unexpected/future graph shape
    degrades gracefully instead of blowing up observability code.
    """
    node = template.get(_NODE_SAMPLER_PRIMARY)
    if node is None:
        node = template.get(_NODE_SAMPLER_POSE)
    if not isinstance(node, dict):
        return dict(_EMPTY_SAMPLER)

    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        return dict(_EMPTY_SAMPLER)

    return {
        "steps": inputs.get("steps"),
        "cfg": inputs.get("cfg"),
        "denoise": inputs.get("denoise"),
    }


def describe_template(template: Optional[dict]) -> Dict[str, Any]:
    """
    Classify a loaded workflow template's rendering tier + sampler settings.

    Tier detection (checked in order):
      1. POSE graphs (node "200" is ReActorFaceSwap) are classified on their own
         axis BEFORE the outfit chain, since the 2511 pose graph reuses the outfit
         2511 loader block (node "301"):
           * "pose_2511" - a pose graph WITH the native 2511 UNETLoader (node
                           "301"): pose_2511_API.json.
           * "v1"        - a pose graph without it: the distilled Rapid pose graph
                           edit_pose_action.json (unchanged from before).
      2. "2511full"        - node "301" present (UNETLoader for the
                              non-distilled Tier-A Qwen-Image-Edit-2511 model).
      3. "rapid_cropstitch" - no node "301", but node "235" is
                              InpaintCropImproved (the V2 crop-and-stitch graph
                              on the distilled Rapid checkpoint).
      4. "v1"               - none of the above (the original whole-frame
                              graph, or any other template).
      5. "unknown"          - ``template`` is None or empty (nothing loaded).

    Returns:
        {"tier": <one of the five strings above>,
         "sampler": {"steps": int|None, "cfg": float|None, "denoise": float|None}}
    """
    if not template:
        return {"tier": TIER_UNKNOWN, "sampler": dict(_EMPTY_SAMPLER)}

    if _is_pose_template(template):
        # Pose step: its own tier axis. Must be checked before the 2511full branch
        # because the 2511 pose graph reuses node "301" (the outfit 2511 loader).
        tier = TIER_POSE_2511 if _NODE_2511_MARKER in template else TIER_V1
    elif _NODE_2511_MARKER in template:
        tier = TIER_2511FULL
    elif _is_cropstitch_template(template):
        tier = TIER_RAPID_CROPSTITCH
    else:
        tier = TIER_V1

    return {"tier": tier, "sampler": _sampler_inputs(template)}
