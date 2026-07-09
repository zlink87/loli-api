"""
Scene randomization endpoint. Admin-only, stateless.

POST /v1/scenes/randomize — Venice writes a short, identity-free scene/environment
sentence the admin drops into a Batch Character Creation draft's `context` field. Never
fails the flow: on any LLM miss it returns a deterministic curated fallback scene.

Modeled on the stateless POST /v1/personas/preview in persona.py.
"""
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from auth.admin import require_admin
from models.requests import SceneRandomizeRequest
from models.responses import SceneRandomizeResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Scenes"])

# Injected from main.py via router.configure_services.
_scene_writer = None


def set_scene_writer(writer) -> None:
    global _scene_writer
    _scene_writer = writer


def _require_writer():
    if _scene_writer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scene writer not configured",
        )
    return _scene_writer


@router.post(
    "/scenes/randomize",
    response_model=SceneRandomizeResponse,
    summary="Generate an identity-free scene sentence (Batch Character Creation)",
    description=(
        "Admin-only, stateless. Returns a short identity-free scene/environment "
        "sentence (environment / activity / mood / time-of-day only) to drop into a "
        "draft's `context`. Never fails: falls back to a deterministic scene "
        "(provider='deterministic') when Venice is unavailable."
    ),
)
async def randomize_scene(
    body: SceneRandomizeRequest,
    user: Dict[str, Any] = Depends(require_admin),
):
    """Generate one identity-free scene sentence. Writes nothing."""
    writer = _require_writer()
    scene, provider = await writer.randomize(persona=body.persona, hint=body.hint)
    return SceneRandomizeResponse(scene=scene, provider=provider)
