"""
SSRF guard for user-supplied image URLs.

``source_image`` values now travel to a remote RunPod worker that fetches them from
a different network, so an unvalidated URL could make the worker reach internal
services. We require https, reject embedded credentials and private/loopback IP
literals, and (when configured) enforce a host allowlist (the Supabase domain).
"""
import ipaddress
import logging
from typing import List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class SourceImageError(ValueError):
    """Raised when a source_image URL fails validation."""


def _is_blocked_ip(host: str) -> bool:
    """True if host is an IP literal in a private/loopback/link-local/reserved range."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # not an IP literal (a hostname) -> handled by allowlist
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_source_image(url: str, allowed_hosts: Optional[List[str]] = None) -> str:
    """
    Validate a user-supplied source image URL. Returns the URL on success.

    Args:
        url: The source image URL.
        allowed_hosts: Lowercased host allowlist. If None, reads from settings.
                       If empty, host is not restricted (dev) but IP/scheme/credential
                       checks still apply.

    Raises:
        SourceImageError: If the URL is unsafe.
    """
    if allowed_hosts is None:
        # Imported lazily to avoid a circular import at module load.
        from config import settings
        allowed_hosts = settings.source_image_allowed_hosts_list

    if not url or not isinstance(url, str):
        raise SourceImageError("source_image must be a non-empty URL")

    parsed = urlparse(url.strip())

    if parsed.scheme != "https":
        raise SourceImageError("source_image must use https")

    if parsed.username or parsed.password:
        raise SourceImageError("source_image must not contain embedded credentials")

    host = (parsed.hostname or "").lower()
    if not host:
        raise SourceImageError("source_image has no host")

    if _is_blocked_ip(host):
        raise SourceImageError("source_image host is not allowed (private/loopback address)")

    if allowed_hosts:
        # Allow exact host or subdomain of an allowlisted host.
        if not any(host == h or host.endswith("." + h) for h in allowed_hosts):
            raise SourceImageError(f"source_image host '{host}' is not in the allowlist")
    else:
        logger.warning(
            "SOURCE_IMAGE_ALLOWED_HOSTS is empty; source_image host '%s' accepted without "
            "allowlist enforcement (set the allowlist in production)", host
        )

    return url
