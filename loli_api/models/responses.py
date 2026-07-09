"""
Pydantic response models for the Character Image Generation API.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

from .enums import JobStatus


class JobCreateResponse(BaseModel):
    """Response for POST /v1/generate/image."""

    jobId: str = Field(
        ...,
        description="Unique job identifier"
    )
    status: JobStatus = Field(
        default=JobStatus.QUEUED,
        description="Initial job status"
    )
    reviewRequired: bool = Field(
        default=True,
        description="Whether review is required before saving"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "jobId": "imgjob_abc123",
                "status": "queued",
                "reviewRequired": True
            }
        }


class BatchGenerateItemResult(BaseModel):
    """One dispatched item in a POST /v1/generate/batch response."""

    index: int = Field(..., description="0-based position of this item in the request")
    id: Optional[str] = Field(
        default=None,
        description="Echo of the item's optional GenerateImageRequest.id (client ref)",
    )
    jobId: str = Field(..., description="Job id to poll via GET /v1/jobs/{jobId}")
    status: JobStatus = Field(
        default=JobStatus.QUEUED, description="Initial job status (always queued)"
    )


class BatchGenerateResponse(BaseModel):
    """Response for POST /v1/generate/batch (202 Accepted)."""

    items: List[BatchGenerateItemResult] = Field(
        ..., description="One entry per dispatched item, in request order"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "items": [
                    {"index": 0, "id": "draft-a1", "jobId": "imgjob_abc123", "status": "queued"},
                    {"index": 1, "id": "draft-b2", "jobId": "imgjob_def456", "status": "queued"},
                ]
            }
        }


class SceneRandomizeResponse(BaseModel):
    """Response for POST /v1/scenes/randomize (200 OK)."""

    scene: str = Field(..., description="Identity-free scene sentence for the draft's context")
    provider: str = Field(
        default="deterministic",
        description="'venice' (LLM) or 'deterministic' (fallback) — for display only",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "scene": "After a long hospital shift, unwinding on her apartment balcony under warm evening light",
                "provider": "venice",
            }
        }


class JobResultItem(BaseModel):
    """Individual result item in job output."""

    type: str = Field(
        default="image",
        description="Result type (image/video)"
    )
    previewUrl: str = Field(
        ...,
        description="Time-limited preview URL"
    )
    sha256: Optional[str] = Field(
        default=None,
        description="SHA256 hash of the file"
    )


class EditResultItem(BaseModel):
    """Individual result item for image edit response."""

    type: str = Field(
        default="image",
        description="Result type (image/video)"
    )
    previewUrl: str = Field(
        ...,
        description="Time-limited preview URL"
    )
    sha256: Optional[str] = Field(
        default=None,
        description="SHA256 hash of the file"
    )


class EditImageResponse(BaseModel):
    """Response for POST /v1/edit/image."""

    editId: str = Field(
        ...,
        description="Unique edit request identifier"
    )
    results: List[EditResultItem] = Field(
        ...,
        description="Edited image results"
    )
    expiresAt: datetime = Field(
        ...,
        description="Preview URL expiration time"
    )


class JobStatusResponse(BaseModel):
    """Response for GET /v1/jobs/{jobId}."""

    jobId: str = Field(
        ...,
        description="Job identifier"
    )
    type: str = Field(
        default="text_to_image",
        description="Job type"
    )
    status: JobStatus = Field(
        ...,
        description="Current job status"
    )
    progress: Optional[float] = Field(
        default=None,
        ge=0,
        le=1,
        description="Progress (0.0 to 1.0)"
    )
    results: Optional[List[JobResultItem]] = Field(
        default=None,
        description="Results when succeeded"
    )
    reviewRequired: bool = Field(
        default=True,
        description="Whether review is required"
    )
    expiresAt: Optional[datetime] = Field(
        default=None,
        description="Preview URL expiration time"
    )
    error: Optional["JobError"] = Field(
        default=None,
        description="Error details when failed"
    )

    # Additional metadata
    promptUsed: Optional[str] = Field(
        default=None,
        description="The generated prompt that was used"
    )
    seedUsed: Optional[int] = Field(
        default=None,
        description="The seed value that was used"
    )
    createdAt: Optional[datetime] = Field(
        default=None,
        description="Job creation timestamp"
    )
    updatedAt: Optional[datetime] = Field(
        default=None,
        description="Last update timestamp"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "jobId": "imgjob_abc123",
                "type": "text_to_image",
                "status": "succeeded",
                "progress": 1.0,
                "results": [
                    {
                        "type": "image",
                        "previewUrl": "https://example.com/preview/token123?path=2026/01/09/img.png",
                        "sha256": "abc123..."
                    }
                ],
                "reviewRequired": True,
                "expiresAt": "2026-01-09T16:00:00Z",
                "promptUsed": "A beautiful portrait of...",
                "seedUsed": 12345,
                "createdAt": "2026-01-09T14:00:00Z",
                "updatedAt": "2026-01-09T14:02:00Z"
            }
        }


class JobError(BaseModel):
    """Error details for failed jobs."""

    code: str = Field(
        ...,
        description="Error code"
    )
    message: str = Field(
        ...,
        description="Error message"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "code": "PROVIDER_ERROR",
                "message": "Upstream provider failed"
            }
        }


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str = Field(
        ...,
        description="Error type"
    )
    detail: Optional[str] = Field(
        default=None,
        description="Detailed error message"
    )
    statusCode: int = Field(
        ...,
        description="HTTP status code"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "error": "VALIDATION_ERROR",
                "detail": "Age must be at least 18",
                "statusCode": 422
            }
        }


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(
        default="healthy",
        description="Service status"
    )
    queueSize: int = Field(
        default=0,
        description="Current job queue size"
    )
    version: str = Field(
        default="1.0.0",
        description="API version"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "queueSize": 3,
                "version": "1.0.0"
            }
        }


class JobTimestamps(BaseModel):
    """Timestamps for job lifecycle events."""

    jobCreatedAt: datetime = Field(
        ...,
        description="Timestamp when job was created/queued"
    )
    promptGeneratedAt: Optional[datetime] = Field(
        default=None,
        description="Timestamp when prompt generation completed"
    )
    imageGeneratedAt: Optional[datetime] = Field(
        default=None,
        description="Timestamp when image generation completed"
    )
    jobCompletedAt: Optional[datetime] = Field(
        default=None,
        description="Timestamp when job completed (succeeded or failed)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "jobCreatedAt": "2026-01-13T10:00:00Z",
                "promptGeneratedAt": "2026-01-13T10:00:05Z",
                "imageGeneratedAt": "2026-01-13T10:00:35Z",
                "jobCompletedAt": "2026-01-13T10:00:36Z"
            }
        }


class ResponseData(BaseModel):
    """
    Response data to be sent to callbackUrl after job completion.
    Contains the client-provided ID and the generated image URL.
    """

    id: Optional[str] = Field(
        default=None,
        description="Client-provided ID from the original request"
    )
    url: str = Field(
        ...,
        description="Preview URL of the generated image"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "client-request-001",
                "url": "https://example.com/preview/token123?path=2026/01/13/img.png"
            }
        }


# Update forward references
JobStatusResponse.model_rebuild()
