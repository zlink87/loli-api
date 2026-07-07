"""
Preview image endpoint.
GET /v1/preview/{token} - Serve image with signed URL validation.
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
import logging
from urllib.parse import unquote

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Preview"])

# These will be injected from main.py
_storage_service = None


def set_storage_service(storage_service):
    """Set the storage service instance (called from main.py)."""
    global _storage_service
    _storage_service = storage_service


def get_storage_service():
    """Get the storage service instance."""
    if _storage_service is None:
        raise RuntimeError("Storage service not initialized")
    return _storage_service


@router.get(
    "/preview/{token}",
    summary="Get preview image",
    description="""
Access a preview image using a signed token.

The token is time-limited and contains an HMAC signature for security.
Tokens are generated when a job succeeds and expire after the configured time (default: 60 minutes).

**Note:** This endpoint does not require JWT authentication - the signed token IS the authentication.
    """,
    responses={
        200: {
            "description": "Image file",
            "content": {
                "image/png": {},
                "image/jpeg": {}
            }
        },
        401: {
            "description": "Invalid or expired token"
        },
        404: {
            "description": "Image not found"
        }
    }
)
async def get_preview(
    token: str,
    path: str = Query(..., description="Image path (URL encoded)")
):
    """
    Serve a preview image if the signed token is valid.

    The token format is: `{expires_timestamp}.{hmac_signature}`

    **Parameters:**
    - `token`: The signed token (from URL path)
    - `path`: The image path (from query parameter)

    **Returns:**
    - Image file with appropriate content-type
    """
    storage = get_storage_service()

    # URL decode the path
    decoded_path = unquote(path)

    # Validate token
    if not storage.validate_signed_url(token, decoded_path):
        logger.warning(f"Invalid or expired token for path: {decoded_path[:50]}...")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired preview token"
        )

    # Check if image exists
    if not storage.image_exists(decoded_path):
        logger.warning(f"Image not found: {decoded_path}")
        raise HTTPException(
            status_code=404,
            detail="Image not found"
        )

    # Get file path
    filepath = storage.get_image_path(decoded_path)

    # Determine media type from extension
    media_type = "image/png"
    if decoded_path.lower().endswith((".jpg", ".jpeg")):
        media_type = "image/jpeg"
    elif decoded_path.lower().endswith(".webp"):
        media_type = "image/webp"
    elif decoded_path.lower().endswith(".mp4"):
        media_type = "video/mp4"
    elif decoded_path.lower().endswith(".webm"):
        media_type = "video/webm"
    elif decoded_path.lower().endswith(".gif"):
        media_type = "image/gif"

    # Generate filename for download
    filename = decoded_path.split("/")[-1]

    logger.debug(f"Serving preview: {decoded_path}")

    return FileResponse(
        filepath,
        media_type=media_type,
        filename=filename,
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff"
        }
    )


@router.head(
    "/preview/{token}",
    summary="Check preview image exists",
    description="Check if a preview image exists and token is valid (HEAD request).",
    responses={
        200: {
            "description": "Image exists"
        },
        401: {
            "description": "Invalid or expired token"
        },
        404: {
            "description": "Image not found"
        }
    }
)
async def check_preview(
    token: str,
    path: str = Query(..., description="Image path (URL encoded)")
):
    """
    Check if a preview image exists (HEAD request).

    Useful for checking token validity without downloading the full image.
    """
    storage = get_storage_service()
    decoded_path = unquote(path)

    # Validate token
    if not storage.validate_signed_url(token, decoded_path):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired preview token"
        )

    # Check if image exists
    if not storage.image_exists(decoded_path):
        raise HTTPException(
            status_code=404,
            detail="Image not found"
        )

    return Response(status_code=200)
