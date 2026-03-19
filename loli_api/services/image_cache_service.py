"""
Image Cache Service for tracking uploaded images with TTL-based cleanup.

Tracks images uploaded to ComfyUI and automatically deletes them
after a period of inactivity (no edits).
"""
import asyncio
import logging
import os
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class CachedImage:
    """Represents a cached image with access tracking."""
    comfyui_filename: str
    original_url: str
    uploaded_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)
    access_count: int = 0

    def touch(self) -> None:
        """Update last access time and increment counter."""
        self.last_accessed_at = time.time()
        self.access_count += 1


class ImageCacheService:
    """
    Service for caching and managing images uploaded to ComfyUI.

    Features:
    - Track images by source URL
    - Update last access time on each use
    - Automatic cleanup of expired images
    - Thread-safe operations
    """

    def __init__(
        self,
        ttl_seconds: int = 1800,  # 30 minutes default
        cleanup_interval_seconds: int = 60,  # Check every minute
        comfyui_input_dir: Optional[str] = None
    ):
        """
        Initialize the image cache service.

        Args:
            ttl_seconds: Time-to-live for cached images (default 30 min)
            cleanup_interval_seconds: How often to check for expired images
            comfyui_input_dir: Path to ComfyUI input directory for file deletion
        """
        self.ttl_seconds = ttl_seconds
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self.comfyui_input_dir = comfyui_input_dir

        self._cache: Dict[str, CachedImage] = {}
        self._lock = threading.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

        logger.info(
            f"ImageCacheService initialized: ttl={ttl_seconds}s, "
            f"cleanup_interval={cleanup_interval_seconds}s"
        )

    def get(self, source_url: str) -> Optional[CachedImage]:
        """
        Get cached image by source URL and update access time.

        Args:
            source_url: The original source URL of the image

        Returns:
            CachedImage if found and touched, None otherwise
        """
        with self._lock:
            cached = self._cache.get(source_url)
            if cached:
                cached.touch()
                logger.debug(
                    f"Cache hit for {source_url}: "
                    f"comfyui_filename={cached.comfyui_filename}, "
                    f"access_count={cached.access_count}"
                )
            return cached

    def put(
        self,
        source_url: str,
        comfyui_filename: str
    ) -> CachedImage:
        """
        Add or update an image in the cache.

        Args:
            source_url: The original source URL
            comfyui_filename: The filename in ComfyUI's input directory

        Returns:
            The created/updated CachedImage
        """
        with self._lock:
            cached = CachedImage(
                comfyui_filename=comfyui_filename,
                original_url=source_url
            )
            self._cache[source_url] = cached
            logger.info(
                f"Cached image: url={source_url[:50]}... -> {comfyui_filename}"
            )
            return cached

    def remove(self, source_url: str) -> bool:
        """
        Remove an image from the cache.

        Args:
            source_url: The original source URL

        Returns:
            True if removed, False if not found
        """
        with self._lock:
            if source_url in self._cache:
                cached = self._cache.pop(source_url)
                self._delete_comfyui_file(cached.comfyui_filename)
                logger.info(f"Removed from cache: {source_url[:50]}...")
                return True
            return False

    def _delete_comfyui_file(self, filename: str) -> bool:
        """
        Delete the actual file from ComfyUI input directory.

        Args:
            filename: The ComfyUI filename

        Returns:
            True if deleted, False otherwise
        """
        if not self.comfyui_input_dir:
            logger.warning("ComfyUI input dir not set, cannot delete file")
            return False

        try:
            file_path = os.path.join(self.comfyui_input_dir, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Deleted ComfyUI input file: {file_path}")
                return True
            else:
                logger.warning(f"File not found for deletion: {file_path}")
                return False
        except Exception as e:
            logger.error(f"Failed to delete file {filename}: {e}")
            return False

    def cleanup_expired(self) -> int:
        """
        Remove all expired images from cache.

        Returns:
            Number of images removed
        """
        now = time.time()
        expired_urls = []

        with self._lock:
            for url, cached in self._cache.items():
                age = now - cached.last_accessed_at
                if age > self.ttl_seconds:
                    expired_urls.append(url)

        removed_count = 0
        for url in expired_urls:
            with self._lock:
                if url in self._cache:
                    cached = self._cache.pop(url)
                    self._delete_comfyui_file(cached.comfyui_filename)
                    removed_count += 1
                    logger.info(
                        f"Expired image removed: {url[:50]}... "
                        f"(age={now - cached.last_accessed_at:.0f}s, "
                        f"accesses={cached.access_count})"
                    )

        if removed_count > 0:
            logger.info(f"Cleanup completed: removed {removed_count} expired images")

        return removed_count

    async def start_cleanup_worker(self) -> None:
        """Start the background cleanup worker."""
        if self._running:
            logger.warning("Cleanup worker already running")
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Image cache cleanup worker started")

    async def stop_cleanup_worker(self) -> None:
        """Stop the background cleanup worker."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        logger.info("Image cache cleanup worker stopped")

    async def _cleanup_loop(self) -> None:
        """Background loop that periodically cleans up expired images."""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval_seconds)
                self.cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}", exc_info=True)

    def get_stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dict with cache stats
        """
        with self._lock:
            now = time.time()
            total_accesses = sum(c.access_count for c in self._cache.values())
            oldest_age = max(
                (now - c.last_accessed_at for c in self._cache.values()),
                default=0
            )

            return {
                "cached_images": len(self._cache),
                "total_accesses": total_accesses,
                "oldest_image_age_seconds": oldest_age,
                "ttl_seconds": self.ttl_seconds,
                "cleanup_interval_seconds": self.cleanup_interval_seconds
            }
