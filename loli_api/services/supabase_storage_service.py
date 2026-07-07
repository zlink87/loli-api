"""
Supabase Storage Service for uploading images to cloud storage.

Storage path convention:
    images_generated/character_creation/{id}.png

Where:
    - images_generated: bucket name
    - character_creation/: folder for character images
    - {id}: comes from request payload (request.id)
"""
import hashlib
import logging
from io import BytesIO
from typing import Optional, Tuple, Union

from PIL import Image
import numpy as np
from supabase import create_client, Client

logger = logging.getLogger(__name__)


class SupabaseStorageService:
    """
    Service for uploading and managing images in Supabase Storage.

    Follows the convention:
        bucket: images_generated
        path: character_creation/{id}.png
    """

    def __init__(
        self,
        supabase_url: str,
        supabase_key: str,
        bucket_name: str = "images_generated"
    ):
        """
        Initialize Supabase storage service.

        Args:
            supabase_url: Supabase project URL
            supabase_key: Supabase service role key
            bucket_name: Storage bucket name (default: images_generated)
        """
        self.bucket_name = bucket_name
        self.client: Client = create_client(supabase_url, supabase_key)
        logger.info(f"Supabase storage initialized: bucket={bucket_name}")

    def upload_image(
        self,
        image: Union[bytes, Image.Image, np.ndarray],
        image_id: str,
        folder: str = "character_creation"
    ) -> Tuple[str, str]:
        """
        Upload image to Supabase storage and return public URL.

        Args:
            image: Image data - can be bytes, PIL Image, or numpy array
            image_id: ID from request payload (used as filename)
            folder: Folder path within bucket (default: character_creation)

        Returns:
            Tuple of (public_url, sha256_hash)

        Raises:
            ValueError: If image type is unsupported
            Exception: If upload fails
        """
        # Convert input to PIL Image
        if isinstance(image, bytes):
            pil_image = Image.open(BytesIO(image))
        elif isinstance(image, np.ndarray):
            pil_image = Image.fromarray(image)
        elif isinstance(image, Image.Image):
            pil_image = image
        else:
            raise ValueError(f"Unsupported image type: {type(image)}")

        # Convert PIL Image -> bytes (PNG format)
        buffer = BytesIO()
        pil_image.save(buffer, format="PNG")
        buffer.seek(0)
        image_bytes = buffer.getvalue()

        # Calculate SHA256 hash
        sha256_hash = hashlib.sha256(image_bytes).hexdigest()

        # Build storage path: {folder}/{image_id}.png
        file_path = f"{folder}/{image_id}.png"

        logger.info(f"Uploading image to Supabase: {file_path}")

        # Upload to Supabase with upsert (overwrite if exists)
        try:
            self.client.storage.from_(self.bucket_name).upload(
                path=file_path,
                file=image_bytes,
                file_options={
                    "content-type": "image/png",
                    "upsert": "true",
                },
            )
        except Exception as e:
            logger.error(f"Supabase upload failed: {e}")
            raise

        # Get public URL
        public_url = self.client.storage.from_(self.bucket_name).get_public_url(file_path)

        logger.info(f"Image uploaded successfully: {public_url}")

        return public_url, sha256_hash

    def upload_video(
        self,
        video: bytes,
        video_id: str,
        folder: str = "character_videos",
        ext: str = "mp4",
        content_type: str = "video/mp4",
    ) -> Tuple[str, str]:
        """
        Upload video bytes to Supabase storage and return the public URL.

        Raw-bytes upload — NEVER through PIL (that would corrupt the video). The
        bucket must allow the video MIME type (Supabase Storage → bucket settings).

        Args:
            video: Raw video bytes (mp4/webm)
            video_id: ID used as the filename (typically the job id)
            folder: Folder path within the bucket
            ext: File extension (mp4, webm)
            content_type: MIME type to store/serve

        Returns:
            Tuple of (public_url, sha256_hash)
        """
        if not isinstance(video, (bytes, bytearray)):
            raise ValueError(f"upload_video expects bytes, got {type(video)}")
        video_bytes = bytes(video)

        sha256_hash = hashlib.sha256(video_bytes).hexdigest()

        ext = (ext or "mp4").lstrip(".").lower()
        file_path = f"{folder}/{video_id}.{ext}"

        logger.info(f"Uploading video to Supabase: {file_path} ({len(video_bytes)} bytes)")

        try:
            self.client.storage.from_(self.bucket_name).upload(
                path=file_path,
                file=video_bytes,
                file_options={
                    "content-type": content_type or "video/mp4",
                    "upsert": "true",
                },
            )
        except Exception as e:
            logger.error(f"Supabase video upload failed: {e}")
            raise

        public_url = self.client.storage.from_(self.bucket_name).get_public_url(file_path)
        logger.info(f"Video uploaded successfully: {public_url}")

        return public_url, sha256_hash

    def delete_image(self, file_path: str) -> bool:
        """
        Delete an image from Supabase storage.

        Args:
            file_path: Path within bucket (e.g., character_creation/abc123.png)

        Returns:
            True if deleted, False otherwise
        """
        try:
            self.client.storage.from_(self.bucket_name).remove([file_path])
            logger.info(f"Image deleted from Supabase: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete image from Supabase: {e}")
            return False

    def image_exists(self, file_path: str) -> bool:
        """
        Check if an image exists in Supabase storage.

        Args:
            file_path: Path within bucket

        Returns:
            True if exists, False otherwise
        """
        try:
            # List files in the folder
            folder = "/".join(file_path.split("/")[:-1])
            filename = file_path.split("/")[-1]

            result = self.client.storage.from_(self.bucket_name).list(folder)

            for item in result:
                if item.get("name") == filename:
                    return True
            return False
        except Exception as e:
            logger.error(f"Error checking image existence: {e}")
            return False

    def get_public_url(self, file_path: str) -> str:
        """
        Get the public URL for an image.

        Args:
            file_path: Path within bucket

        Returns:
            Public URL string
        """
        return self.client.storage.from_(self.bucket_name).get_public_url(file_path)

    def get_storage_stats(self) -> dict:
        """
        Get storage statistics (limited info available from Supabase).

        Returns:
            Dict with storage info
        """
        try:
            # List all files in character_creation folder
            files = self.client.storage.from_(self.bucket_name).list("character_creation")
            file_count = len(files) if files else 0

            return {
                "bucket": self.bucket_name,
                "folder": "character_creation",
                "file_count": file_count,
                "storage_type": "supabase"
            }
        except Exception as e:
            logger.error(f"Error getting storage stats: {e}")
            return {
                "bucket": self.bucket_name,
                "storage_type": "supabase",
                "error": str(e)
            }
