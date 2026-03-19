"""
Face identity preservation service.
Extracts and caches face crops from source images for use with IP-Adapter FaceID
in ComfyUI edit workflows.

Phase 1: Face extraction and caching infrastructure.
Phase 2 (future): Full IP-Adapter FaceID workflow integration (requires GPU testing).
"""
import io
import logging
import uuid
from typing import Dict, Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)


class FaceIdentityService:
    """
    Extract and cache face references for identity preservation across edits.

    Currently provides face crop extraction from source images.
    Future: will integrate with IP-Adapter FaceID nodes in ComfyUI workflows
    to ensure character identity remains consistent during pose/outfit/environment edits.

    Available ComfyUI infrastructure (installed but not yet wired):
    - IP-Adapter FaceID: ip-adapter-faceid-plusv2_sd15.bin
    - CLIP Vision: CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors
    - Face Analysis: comfyui_faceanalysis (InsightFace) custom node
    - Face Bounding Box: rect custom node (FaceBoundingBox, RectSelect, RectFill)
    """

    def __init__(self, comfyui_input_dir: str):
        """
        Initialize face identity service.

        Args:
            comfyui_input_dir: Path to ComfyUI input directory for uploading face crops
        """
        self.input_dir = comfyui_input_dir
        self._cache: Dict[str, str] = {}  # source_url -> face_crop_filename

    def get_cached_face(self, source_url: str) -> Optional[str]:
        """
        Get cached face reference filename for a source image URL.

        Args:
            source_url: URL of the original source image

        Returns:
            ComfyUI filename of the face crop, or None if not cached
        """
        return self._cache.get(source_url)

    def extract_face_crop(self, image_bytes: bytes, source_url: str) -> Optional[str]:
        """
        Extract a face crop from image bytes and save to ComfyUI input directory.
        Uses a simple center-upper region crop as a heuristic face region.

        For full face detection, IP-Adapter FaceID should be used in the ComfyUI
        workflow itself (via InsightFace nodes), which handles detection on GPU.

        Args:
            image_bytes: Raw image bytes
            source_url: URL of the source image (for caching)

        Returns:
            Filename of the saved face crop in ComfyUI input dir, or None on failure
        """
        try:
            img = Image.open(io.BytesIO(image_bytes))
            w, h = img.size

            # Heuristic face crop: upper-center region (top 40% of image, center 60% width)
            crop_x1 = int(w * 0.2)
            crop_x2 = int(w * 0.8)
            crop_y1 = 0
            crop_y2 = int(h * 0.4)

            face_crop = img.crop((crop_x1, crop_y1, crop_x2, crop_y2))

            # Save to ComfyUI input directory
            filename = f"face_ref_{uuid.uuid4().hex[:12]}.png"
            import os
            filepath = os.path.join(self.input_dir, filename)
            face_crop.save(filepath, "PNG")

            self._cache[source_url] = filename
            logger.info(f"Extracted face crop: {filename} ({crop_x2-crop_x1}x{crop_y2-crop_y1}px)")
            return filename

        except Exception as e:
            logger.warning(f"Failed to extract face crop: {e}")
            return None

    def clear_cache(self) -> None:
        """Clear the face reference cache."""
        self._cache.clear()

    def get_stats(self) -> dict:
        """Get cache statistics."""
        return {
            "cached_faces": len(self._cache),
        }
