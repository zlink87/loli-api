"""
Local filesystem storage service with signed URL generation.
"""
import os
import uuid
import hmac
import hashlib
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from PIL import Image
import io
import logging

logger = logging.getLogger(__name__)


class StorageService:
    """
    Handles local filesystem storage and signed URL generation.
    Provides time-limited access to generated images via HMAC-signed tokens.
    """

    def __init__(
        self,
        storage_dir: str,
        signing_secret: str,
        base_url: str,
        default_expiry_minutes: int = 60
    ):
        """
        Initialize storage service.

        Args:
            storage_dir: Base directory for storing images
            signing_secret: Secret key for HMAC signing
            base_url: Base URL for generating preview URLs
            default_expiry_minutes: Default URL expiration time
        """
        self.storage_dir = os.path.abspath(storage_dir)
        self.signing_secret = signing_secret.encode()
        self.base_url = base_url.rstrip('/')
        self.default_expiry_minutes = default_expiry_minutes

        # Ensure storage directory exists
        os.makedirs(self.storage_dir, exist_ok=True)
        logger.info(f"Storage initialized at: {self.storage_dir}")

    def save_image(
        self,
        image_data: bytes,
        job_id: str,
        format: str = "PNG"
    ) -> Tuple[str, str]:
        """
        Save image bytes to filesystem.

        Args:
            image_data: Raw image bytes
            job_id: Job ID for organizing files
            format: Image format (PNG, JPEG, etc.)

        Returns:
            Tuple of (relative_path, sha256_hash)
        """
        # Create date-based subdirectory
        date_dir = datetime.now().strftime("%Y/%m/%d")
        full_dir = os.path.join(self.storage_dir, date_dir)
        os.makedirs(full_dir, exist_ok=True)

        # Generate unique filename
        ext = format.lower()
        if ext == "jpeg":
            ext = "jpg"
        filename = f"{job_id}_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join(full_dir, filename)

        # Calculate hash before saving
        sha256_hash = hashlib.sha256(image_data).hexdigest()

        # Save image
        image = Image.open(io.BytesIO(image_data))
        image.save(filepath, format=format, optimize=True)

        # Return relative path
        relative_path = os.path.join(date_dir, filename)
        logger.info(f"Saved image: {relative_path} ({len(image_data)} bytes)")

        return relative_path, sha256_hash

    def get_image_path(self, relative_path: str) -> str:
        """
        Get absolute path for a relative image path.

        Args:
            relative_path: Relative path within storage

        Returns:
            Absolute filesystem path
        """
        return os.path.join(self.storage_dir, relative_path)

    def image_exists(self, relative_path: str) -> bool:
        """
        Check if image exists.

        Args:
            relative_path: Relative path within storage

        Returns:
            True if exists, False otherwise
        """
        return os.path.isfile(self.get_image_path(relative_path))

    def get_image_data(self, relative_path: str) -> Optional[bytes]:
        """
        Read image data from storage.

        Args:
            relative_path: Relative path within storage

        Returns:
            Image bytes or None if not found
        """
        filepath = self.get_image_path(relative_path)
        if not os.path.isfile(filepath):
            return None

        with open(filepath, 'rb') as f:
            return f.read()

    def generate_signed_url(
        self,
        relative_path: str,
        expiry_minutes: Optional[int] = None
    ) -> Tuple[str, datetime]:
        """
        Generate a time-limited signed URL for image access.

        Args:
            relative_path: Relative path to the image
            expiry_minutes: Optional custom expiry time

        Returns:
            Tuple of (signed_url, expiration_datetime)
        """
        expiry_minutes = expiry_minutes or self.default_expiry_minutes
        # Use a timezone-aware UTC datetime: datetime.utcnow() is naive, and
        # naive.timestamp() assumes LOCAL time, so on a non-UTC host the expiry
        # lands hours in the past and every token is born expired (validation
        # compares against time.time(), which is true UTC). Aware -> correct.
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)
        expires_timestamp = int(expires_at.timestamp())

        # Create token: HMAC(secret, path + expires)
        message = f"{relative_path}:{expires_timestamp}"
        signature = hmac.new(
            self.signing_secret,
            message.encode(),
            hashlib.sha256
        ).hexdigest()[:32]  # Use first 32 chars for shorter URLs

        # Build URL
        token = f"{expires_timestamp}.{signature}"
        # URL encode the path
        from urllib.parse import quote
        encoded_path = quote(relative_path, safe='')
        url = f"{self.base_url}/v1/preview/{token}?path={encoded_path}"

        return url, expires_at

    def validate_signed_url(self, token: str, path: str) -> bool:
        """
        Validate a signed URL token.

        Args:
            token: The signed token from URL
            path: The image path from URL

        Returns:
            True if token is valid and not expired
        """
        try:
            parts = token.split('.')
            if len(parts) != 2:
                logger.warning(f"Invalid token format: {token[:20]}...")
                return False

            expires_timestamp = int(parts[0])
            provided_signature = parts[1]

            # Check expiration
            if time.time() > expires_timestamp:
                logger.warning(f"Token expired: {expires_timestamp}")
                return False

            # Verify signature
            message = f"{path}:{expires_timestamp}"
            expected_signature = hmac.new(
                self.signing_secret,
                message.encode(),
                hashlib.sha256
            ).hexdigest()[:32]

            if not hmac.compare_digest(provided_signature, expected_signature):
                logger.warning("Token signature mismatch")
                return False

            return True

        except (ValueError, TypeError) as e:
            logger.warning(f"Token validation error: {e}")
            return False

    def delete_image(self, relative_path: str) -> bool:
        """
        Delete an image from storage.

        Args:
            relative_path: Relative path to the image

        Returns:
            True if deleted, False if not found
        """
        filepath = self.get_image_path(relative_path)
        if os.path.isfile(filepath):
            os.remove(filepath)
            logger.info(f"Deleted image: {relative_path}")
            return True
        return False

    def cleanup_old_images(self, max_age_days: int = 7) -> int:
        """
        Remove images older than max_age_days.

        Args:
            max_age_days: Maximum age in days

        Returns:
            Number of images removed
        """
        cutoff = time.time() - (max_age_days * 86400)
        removed = 0

        for root, dirs, files in os.walk(self.storage_dir):
            for filename in files:
                filepath = os.path.join(root, filename)
                try:
                    if os.path.getmtime(filepath) < cutoff:
                        os.remove(filepath)
                        removed += 1
                except OSError as e:
                    logger.warning(f"Failed to remove {filepath}: {e}")

        logger.info(f"Cleaned up {removed} old images")
        return removed

    def get_storage_stats(self) -> dict:
        """
        Get storage statistics.

        Returns:
            Dict with file count, total size, etc.
        """
        total_files = 0
        total_size = 0

        for root, dirs, files in os.walk(self.storage_dir):
            for filename in files:
                filepath = os.path.join(root, filename)
                try:
                    total_files += 1
                    total_size += os.path.getsize(filepath)
                except OSError:
                    pass

        return {
            "total_files": total_files,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "storage_dir": self.storage_dir
        }
