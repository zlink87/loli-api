"""
Venice LLM client — a thin OpenAI-compatible chat/completions wrapper.

Venice (https://venice.ai) exposes an OpenAI-compatible API and hosts uncensored
models, which this pipeline needs for NSFW-tolerant scene writing and story
planning. This is the single provider seam: base_url / model / api_key live here,
so swapping providers later is a one-file change.
"""
import httpx
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class VeniceClient:
    """OpenAI-compatible chat client. Never raises: returns (None, {}) on any error
    so an LLM outage can never break the surrounding generation pipeline."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.venice.ai/api/v1",
        model: str = "venice-uncensored",
        timeout: float = 100.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1500,
        model: Optional[str] = None,
    ) -> Tuple[Optional[str], Dict]:
        """POST /chat/completions. Returns (content, usage). content is None on any
        error or when no api_key is configured; usage is the raw usage object ({} on error)."""
        if not self.api_key:
            return None, {}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model or self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=self.timeout,
                )
                response.raise_for_status()
                result = response.json()
                usage = result.get("usage", {}) or {}
                content = result["choices"][0]["message"]["content"].strip()
                return content, usage
        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.HTTPError) as e:
            logger.error(f"Venice chat HTTP error: {e}")
            return None, {}
        except (KeyError, IndexError) as e:
            logger.error(f"Venice chat parse error: {e}")
            return None, {}
        except Exception as e:  # noqa: BLE001 - never let an LLM call break the pipeline
            logger.error(f"Venice chat error: {e}")
            return None, {}
