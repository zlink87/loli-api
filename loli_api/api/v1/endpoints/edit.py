"""
Image edit endpoint.
POST /v1/edit/image - Edit an input image using ComfyUI workflow.
"""
import base64
import json
import logging
import time
import uuid
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status

from auth.dependencies import get_current_user
from config import settings
from services.comfyui_client import ComfyUIClient
from services.runpod_client import RunPodServerlessClient
from services.storage_service import StorageService
from services.notification_service import NotificationService
from models.responses import EditImageResponse, EditResultItem
from PIL import Image
import io

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Edit"])

_comfyui_client: Optional[ComfyUIClient] = None
_runpod_client: Optional[RunPodServerlessClient] = None
_storage_service: Optional[StorageService] = None
_notification_service: Optional[NotificationService] = None
_edit_workflow_path: Optional[str] = None
_edit_workflow_template: Optional[dict] = None


def set_comfyui_client(comfyui_client: ComfyUIClient) -> None:
    """Set ComfyUI client instance (called from main.py)."""
    global _comfyui_client
    _comfyui_client = comfyui_client


def set_runpod_client(runpod_client: RunPodServerlessClient) -> None:
    """Set RunPod client instance (called from main.py)."""
    global _runpod_client
    _runpod_client = runpod_client


def get_runpod_client() -> RunPodServerlessClient:
    """Get RunPod client instance."""
    if _runpod_client is None:
        raise RuntimeError("RunPod client not initialized")
    return _runpod_client


def set_storage_service(storage_service: StorageService) -> None:
    """Set storage service instance (called from main.py)."""
    global _storage_service
    _storage_service = storage_service


def set_notification_service(notification_service: NotificationService) -> None:
    """Set notification service instance (called from main.py)."""
    global _notification_service
    _notification_service = notification_service


def set_edit_workflow_path(workflow_path: str) -> None:
    """Set and load edit workflow template (called from main.py)."""
    global _edit_workflow_path, _edit_workflow_template
    _edit_workflow_path = workflow_path

    try:
        with open(workflow_path, 'r', encoding='utf-8') as f:
            _edit_workflow_template = json.load(f)
        logger.info(f"Loaded edit workflow template: {workflow_path}")
    except Exception as e:
        logger.error(f"Failed to load edit workflow: {e}")
        _edit_workflow_template = None


def get_comfyui_client() -> ComfyUIClient:
    """Get ComfyUI client instance."""
    if _comfyui_client is None:
        raise RuntimeError("ComfyUI client not initialized")
    return _comfyui_client


def get_storage_service() -> StorageService:
    """Get storage service instance."""
    if _storage_service is None:
        raise RuntimeError("Storage service not initialized")
    return _storage_service


def get_notification_service() -> Optional[NotificationService]:
    """Get notification service instance."""
    return _notification_service


def get_edit_workflow_template() -> dict:
    """Get edit workflow template."""
    if _edit_workflow_template is None:
        raise RuntimeError("Edit workflow template not initialized")
    return _edit_workflow_template


@router.post(
    "/edit/image",
    response_model=EditImageResponse,
    status_code=status.HTTP_200_OK,
    summary="Edit an image using ComfyUI",
    description="""
Submit an input image to the edit workflow and receive signed preview URL(s).

This endpoint processes the edit synchronously and returns when the result is ready.
    """,
    responses={
        200: {
            "description": "Image edited successfully",
            "model": EditImageResponse
        },
        400: {"description": "Invalid input"},
        401: {"description": "Unauthorized - Invalid or missing JWT token"},
        415: {"description": "Unsupported media type"},
        500: {"description": "Internal server error"}
    }
)
async def edit_image(
    file: UploadFile = File(..., description="Input image file"),
    prompt: Optional[str] = Form(default=None, description="Optional prompt override"),
    negativePrompt: Optional[str] = Form(default=None, description="Optional negative prompt override"),
    seed: Optional[int] = Form(default=None, description="Optional seed override"),
    inputUrl: Optional[str] = Form(default=None, description="Optional input image URL for logging"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Edit an uploaded image using the ComfyUI edit workflow.
    """
    if seed is not None and (seed < 1 or seed > 1000000000):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Seed must be between 1 and 1,000,000,000"
        )

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing filename"
        )

    content_type = (file.content_type or "").lower()
    if content_type not in ("image/png", "image/jpeg", "image/jpg", "image/webp"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported image type"
        )

    read_start = time.monotonic()
    image_bytes = await file.read()
    read_duration = time.monotonic() - read_start
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file"
        )
    logger.info("Read upload bytes: filename=%s size=%s duration=%.3fs", file.filename, len(image_bytes), read_duration)

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            width, height = img.size
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image file"
        )

    width = (width // 8) * 8
    height = (height // 8) * 8

    edit_id = f"edit_{uuid.uuid4().hex[:12]}"
    start_time = time.monotonic()
    runpod = get_runpod_client()
    storage = get_storage_service()
    notification_service = get_notification_service()
    workflow_template = get_edit_workflow_template()

    content_type = file.content_type or "image/png"
    if inputUrl:
        logger.info("[%s] Input image URL: %s", edit_id, inputUrl)

    # Stage the uploaded image as a RunPod input.images[] entry (base64) and
    # reference it by name in the edit workflow's LoadImage node.
    image_name = f"{edit_id}_{file.filename or 'input.png'}"
    images_input = [
        {
            "name": image_name,
            "image": f"data:{content_type};base64,{base64.b64encode(image_bytes).decode('ascii')}",
        }
    ]

    workflow = ComfyUIClient.prepare_edit_workflow(
        workflow_template,
        image_name,
        seed=seed,
        prompt=prompt,
        negative_prompt=negativePrompt,
        width=width,
        height=height,
    )
    logger.info(f"[{edit_id}] Workflow prepared, submitting to RunPod...")

    try:
        # Non-blocking: submit + async poll (does not freeze the event loop).
        job_doc = await runpod.run_and_wait(
            workflow,
            images=images_input,
            execution_timeout_ms=settings.RUNPOD_EXECUTION_TIMEOUT_MS,
            ttl_ms=settings.RUNPOD_TTL_MS,
            poll_interval_seconds=settings.RUNPOD_POLL_INTERVAL_SECONDS,
        )
        outputs = RunPodServerlessClient.parse_output(job_doc.get("output"))
        logger.info(f"[{edit_id}] RunPod complete, {len(outputs)} image(s)")
    except Exception as e:
        logger.error(f"Edit failed for {edit_id}: {e}", exc_info=True)
        if notification_service:
            total_duration = time.monotonic() - start_time
            await notification_service.send_job_failed(
                job_id=edit_id,
                user_id=current_user.get("sub", "anonymous"),
                error_message=str(e),
                error_code="EDIT_FAILED",
                total_duration=total_duration
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process edit request"
        )

    if not outputs:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No images returned from workflow"
        )

    results: List[EditResultItem] = []
    expires_at = None
    for out in outputs:
        if out.get("url"):
            # Worker uploaded directly to S3/Supabase.
            results.append(EditResultItem(previewUrl=out["url"], sha256=None))
        elif out.get("data"):
            image_data = base64.b64decode(out["data"])
            relative_path, image_hash = storage.save_image(image_data, edit_id)
            preview_url, expires_at = storage.generate_signed_url(relative_path)
            results.append(EditResultItem(previewUrl=preview_url, sha256=image_hash))

    if notification_service and results:
        total_duration = time.monotonic() - start_time
        output_urls = [item.previewUrl for item in results if item.previewUrl]
        await notification_service.send_edit_completed(
            edit_id=edit_id,
            filename=file.filename,
            input_url=inputUrl,
            image_urls=output_urls,
            total_duration=total_duration
        )

    return EditImageResponse(
        editId=edit_id,
        results=results,
        expiresAt=expires_at
    )
