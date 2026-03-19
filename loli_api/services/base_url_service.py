"""
Service to sync the BASE_URL from .env to Supabase edge function.
Called on application startup so external services always know the
current Cloudflare tunnel URL.
"""
import logging
import httpx

logger = logging.getLogger(__name__)

SUPABASE_UPDATE_URL = (
    "https://dwehaynbuioxuzvdaify.supabase.co/functions/v1/update-base-url"
)


async def upload_base_url(base_url: str, api_key: str) -> bool:
    """
    POST the current BASE_URL to the Supabase edge function.

    Args:
        base_url: The current tunnel / public URL to register.
        api_key:  The x-api-key for the edge function.

    Returns:
        True if the update succeeded, False otherwise.
    """
    if not base_url:
        logger.warning("BASE_URL is empty, skipping Supabase base-url update")
        return False

    if not api_key:
        logger.warning("SUPABASE_UPDATE_BASE_URL_API_KEY is empty, skipping update")
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                SUPABASE_UPDATE_URL,
                headers={
                    "x-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json={"base_url": base_url},
            )
            response.raise_for_status()
            logger.info(
                f"Successfully updated base URL in Supabase: {base_url} "
                f"(status {response.status_code})"
            )
            return True
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Supabase base-url update failed: {e.response.status_code} - "
            f"{e.response.text}"
        )
        return False
    except httpx.RequestError as e:
        logger.error(f"Supabase base-url update request error: {e}")
        return False
