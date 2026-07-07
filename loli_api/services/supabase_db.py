"""
Supabase Postgres (PostgREST) client for the Character Batches feature.

Uses the service-role key, so it BYPASSES row-level security — the API is
single-admin and every route is gated behind require_admin instead of per-user
data isolation. A single shared client is created lazily; blocking calls are
wrapped in asyncio.to_thread by the stores (mirroring SupabaseStorageService
usage).
"""
import logging
from typing import Optional

from supabase import create_client, Client

from config import settings

logger = logging.getLogger(__name__)

_client: Optional[Client] = None


def get_supabase_db_client() -> Client:
    """Return the shared service-role Supabase client. Raises if not configured."""
    global _client
    if _client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError(
                "Supabase DB not configured: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY"
            )
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
        logger.info("Supabase DB client initialized (service role)")
    return _client


def is_configured() -> bool:
    return bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)
