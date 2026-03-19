"""
Google Chat notification service for job status updates.
"""
import httpx
import json
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


class NotificationService:
    """Send notifications to Google Chat webhook."""

    def __init__(self, response_webhook_url: str = "", payload_webhook_url: str = ""):
        """
        Initialize notification service.

        Args:
            response_webhook_url: Google Chat webhook URL for job completion responses
            payload_webhook_url: Google Chat webhook URL for incoming user payloads
        """
        self.response_webhook_url = response_webhook_url
        self.payload_webhook_url = payload_webhook_url
        self._response_enabled = bool(response_webhook_url)
        self._payload_enabled = bool(payload_webhook_url)

    async def send_request_received(
        self,
        user_id: str,
        request_payload: Any
    ) -> bool:
        """
        Send notification when a new request is received from user.
        Sent to PAYLOAD webhook.

        Args:
            user_id: User ID
            request_payload: The original request payload

        Returns:
            True if sent successfully
        """
        if not self._payload_enabled:
            return False

        try:
            payload_str = json.dumps(request_payload, indent=2, ensure_ascii=False)
            message = (
                f"📥 *NEW REQUEST*\n"
                f"👤 *User:* `{user_id}`\n\n"
                f"```\n{payload_str}\n```"
            )
            return await self._send_message(message, use_payload_webhook=True)
        except Exception as e:
            logger.warning(f"Failed to send request received notification: {e}")
            return False

    async def send_job_completed(
        self,
        job_id: str,
        user_id: str,
        prompt_duration: float,
        image_duration: float,
        total_duration: float,
        preview_url: str,
        prompt_used: Optional[str] = None,
        request_payload: Optional[Any] = None,
        response_data: Optional[dict] = None,
        timestamps: Optional[dict] = None,
        token_usage: Optional[dict] = None,
        seed_used: Optional[int] = None
    ) -> bool:
        """
        Send job completion notification to RESPONSE webhook with image card.

        Args:
            job_id: Job ID
            user_id: User ID
            prompt_duration: Time spent generating prompt (seconds)
            image_duration: Time spent generating image (seconds)
            total_duration: Total job time (seconds)
            preview_url: Image preview URL
            prompt_used: The prompt that was used (optional)
            request_payload: The original user request payload (optional)
            response_data: ResponseData dict with id and url for callback (optional)
            timestamps: JobTimestamps dict with job lifecycle timestamps (optional)
            token_usage: Token usage and cost info from Grok API (optional)
            seed_used: The seed used for image generation (optional)

        Returns:
            True if sent successfully
        """
        if not self._response_enabled:
            return False

        # Build Job Details widgets
        job_details_widgets = [
            {
                "decoratedText": {
                    "topLabel": "Job ID",
                    "text": job_id
                }
            },
            {
                "decoratedText": {
                    "topLabel": "User",
                    "text": user_id
                }
            },
            {
                "decoratedText": {
                    "topLabel": "Duration",
                    "text": f"Prompt: {prompt_duration:.2f}s | Image: {image_duration:.2f}s | Total: {total_duration:.2f}s"
                }
            },
            {
                "decoratedText": {
                    "topLabel": "Seed",
                    "text": str(seed_used) if seed_used is not None else "Not set"
                }
            }
        ]

        # Add Generated Prompt to Job Details
        if prompt_used:
            job_details_widgets.append({"divider": {}})
            job_details_widgets.append({
                "decoratedText": {
                    "topLabel": "Generated Prompt",
                    "text": prompt_used,
                    "wrapText": True
                }
            })

        # Add Request Payload to Job Details
        if request_payload:
            try:
                payload_str = json.dumps(request_payload, indent=2, ensure_ascii=False)
                job_details_widgets.append({"divider": {}})
                job_details_widgets.append({
                    "decoratedText": {
                        "topLabel": "Request Payload",
                        "text": f"<pre>{payload_str}</pre>",
                        "wrapText": True
                    }
                })
            except Exception as e:
                logger.warning(f"Failed to serialize request payload: {e}")

        # Add Response Data (Callback) to Job Details
        if response_data:
            try:
                response_data_str = json.dumps(response_data, indent=2, ensure_ascii=False)
                job_details_widgets.append({"divider": {}})
                job_details_widgets.append({
                    "decoratedText": {
                        "topLabel": "Response Data (Callback)",
                        "text": f"<pre>{response_data_str}</pre>",
                        "wrapText": True
                    }
                })
            except Exception as e:
                logger.warning(f"Failed to serialize response data: {e}")

        # Add Timestamps to Job Details
        if timestamps:
            job_details_widgets.append({"divider": {}})
            if timestamps.get("jobCreatedAt"):
                job_details_widgets.append({
                    "decoratedText": {
                        "topLabel": "Job Created",
                        "text": timestamps["jobCreatedAt"]
                    }
                })
            if timestamps.get("promptGeneratedAt"):
                job_details_widgets.append({
                    "decoratedText": {
                        "topLabel": "Prompt Generated",
                        "text": timestamps["promptGeneratedAt"]
                    }
                })
            if timestamps.get("imageGeneratedAt"):
                job_details_widgets.append({
                    "decoratedText": {
                        "topLabel": "Image Generated",
                        "text": timestamps["imageGeneratedAt"]
                    }
                })
            if timestamps.get("jobCompletedAt"):
                job_details_widgets.append({
                    "decoratedText": {
                        "topLabel": "Job Completed",
                        "text": timestamps["jobCompletedAt"]
                    }
                })

        # Add Grok API Usage to Job Details
        if token_usage:
            job_details_widgets.append({"divider": {}})
            job_details_widgets.append({
                "decoratedText": {
                    "topLabel": "Grok Model",
                    "text": token_usage.get("model", "N/A")
                }
            })
            job_details_widgets.append({
                "decoratedText": {
                    "topLabel": "Tokens",
                    "text": f"In: {token_usage.get('prompt_tokens', 0):,} (cached: {token_usage.get('cached_tokens', 0):,}) | Out: {token_usage.get('completion_tokens', 0):,} | Reasoning: {token_usage.get('reasoning_tokens', 0):,} | Total: {token_usage.get('total_tokens', 0):,}"
                }
            })
            job_details_widgets.append({
                "decoratedText": {
                    "topLabel": "Cost (USD)",
                    "text": f"In: ${token_usage.get('input_cost', 0):.6f} | Out: ${token_usage.get('output_cost', 0):.6f} | Cached: ${token_usage.get('cached_cost', 0):.6f} | Total: ${token_usage.get('total_cost', 0):.6f}"
                }
            })

        # Build card sections - Job Details is collapsible
        sections = [
            {
                "header": "Job Details",
                "collapsible": True,
                "uncollapsibleWidgetsCount": 4,  # Show Job ID, User, Duration, Seed by default
                "widgets": job_details_widgets
            }
        ]

        # Add image section
        sections.append({
            "header": "Generated Image",
            "widgets": [
                {
                    "image": {
                        "imageUrl": preview_url,
                        "altText": f"Generated image for job {job_id}"
                    }
                },
                {
                    "buttonList": {
                        "buttons": [
                            {
                                "text": "Open Image",
                                "onClick": {
                                    "openLink": {
                                        "url": preview_url
                                    }
                                }
                            }
                        ]
                    }
                }
            ]
        })

        # Build card message
        card_message = {
            "cardsV2": [
                {
                    "cardId": f"job-{job_id}",
                    "card": {
                        "header": {
                            "title": "✅ JOB SUCCEEDED",
                            "subtitle": f"Job {job_id} completed successfully"
                        },
                        "sections": sections
                    }
                }
            ]
        }

        return await self._send_card(card_message)

    async def send_edit_completed(
        self,
        edit_id: str,
        filename: str,
        input_url: Optional[str],
        image_urls: list[str],
        total_duration: float,
        user_id: Optional[str] = None,
        image_duration: Optional[float] = None,
        prompt_used: Optional[str] = None,
        seed_used: Optional[int] = None,
        request_payload: Optional[Any] = None,
        timestamps: Optional[dict] = None
    ) -> bool:
        """
        Send edit completion notification to RESPONSE webhook with image card.

        Args:
            edit_id: Edit request identifier
            filename: Original filename
            input_url: Optional input image URL
            image_urls: Output image URLs
            total_duration: Total edit time (seconds)
            user_id: User ID (optional)
            image_duration: Time spent generating image (optional)
            prompt_used: The prompt that was used (optional)
            seed_used: The seed used for generation (optional)
            request_payload: The original request payload dict (optional)
            timestamps: Job lifecycle timestamps dict (optional)

        Returns:
            True if sent successfully
        """
        if not self._response_enabled:
            return False
        if not image_urls:
            return False

        # Build Job Details widgets
        detail_widgets = [
            {
                "decoratedText": {
                    "topLabel": "Job ID",
                    "text": edit_id
                }
            }
        ]

        if user_id:
            detail_widgets.append({
                "decoratedText": {
                    "topLabel": "User",
                    "text": user_id
                }
            })

        duration_text = f"Total: {total_duration:.2f}s"
        if image_duration is not None:
            duration_text = f"Image: {image_duration:.2f}s | {duration_text}"
        detail_widgets.append({
            "decoratedText": {
                "topLabel": "Duration",
                "text": duration_text
            }
        })

        if seed_used is not None:
            detail_widgets.append({
                "decoratedText": {
                    "topLabel": "Seed",
                    "text": str(seed_used)
                }
            })

        # Add prompt
        if prompt_used:
            detail_widgets.append({"divider": {}})
            detail_widgets.append({
                "decoratedText": {
                    "topLabel": "Prompt Used",
                    "text": prompt_used,
                    "wrapText": True
                }
            })

        # Add request payload
        if request_payload:
            try:
                payload_str = json.dumps(request_payload, indent=2, ensure_ascii=False)
                detail_widgets.append({"divider": {}})
                detail_widgets.append({
                    "decoratedText": {
                        "topLabel": "Request Payload",
                        "text": f"<pre>{payload_str}</pre>",
                        "wrapText": True
                    }
                })
            except Exception as e:
                logger.warning(f"Failed to serialize request payload: {e}")

        # Add timestamps
        if timestamps:
            detail_widgets.append({"divider": {}})
            for label, value in timestamps.items():
                if value:
                    detail_widgets.append({
                        "decoratedText": {
                            "topLabel": label,
                            "text": value
                        }
                    })

        uncollapsible_count = 3  # Job ID, Duration, (User if present)
        if user_id:
            uncollapsible_count = 4

        sections = [
            {
                "header": "Job Details",
                "collapsible": True,
                "uncollapsibleWidgetsCount": uncollapsible_count,
                "widgets": detail_widgets
            }
        ]

        # Build output image widgets
        image_widgets = []
        for url in image_urls:
            logger.info(f"[EDIT NOTIFICATION] Image URL being sent: {url}")
            image_widgets.append({
                "image": {
                    "imageUrl": url,
                    "altText": f"Output for {filename}"
                }
            })
            image_widgets.append({
                "buttonList": {
                    "buttons": [
                        {
                            "text": "Open Image",
                            "onClick": {
                                "openLink": {
                                    "url": url
                                }
                            }
                        }
                    ]
                }
            })

        # Add input image section if available
        if input_url:
            sections.append({
                "header": "Input Image",
                "widgets": [
                    {
                        "image": {
                            "imageUrl": input_url,
                            "altText": f"Input image: {filename}"
                        }
                    },
                    {
                        "buttonList": {
                            "buttons": [
                                {
                                    "text": "Open Input Image",
                                    "onClick": {
                                        "openLink": {
                                            "url": input_url
                                        }
                                    }
                                }
                            ]
                        }
                    }
                ]
            })

        # Add output images section
        sections.append({
            "header": "Output Images",
            "widgets": image_widgets
        })

        card_message = {
            "cardsV2": [
                {
                    "cardId": f"edit-{edit_id}",
                    "card": {
                        "header": {
                            "title": "✅ OUTFIT EDIT SUCCEEDED",
                            "subtitle": f"Job {edit_id} ({total_duration:.2f}s)"
                        },
                        "sections": sections
                    }
                }
            ]
        }

        return await self._send_card(card_message)

    async def send_job_failed(
        self,
        job_id: str,
        user_id: str,
        error_message: str,
        error_code: str,
        total_duration: float
    ) -> bool:
        """
        Send job failure notification to RESPONSE webhook.

        Args:
            job_id: Job ID
            user_id: User ID
            error_message: Error description
            error_code: Error code
            total_duration: Total job time before failure (seconds)

        Returns:
            True if sent successfully
        """
        if not self._response_enabled:
            return False

        # Send notification to RESPONSE webhook
        message = (
            f"❌ *JOB FAILED*\n\n"
            f"📋 *Job ID:* `{job_id}`\n"
            f"👤 *User:* `{user_id}`\n"
            f"⚠️ *Error Code:* `{error_code}`\n"
            f"💬 *Error:* {error_message}\n"
            f"⏱️ *Duration:* {total_duration:.2f}s"
        )

        return await self._send_message(message)

    async def _send_message(self, text: str, use_payload_webhook: bool = False) -> bool:
        """
        Send text message to Google Chat webhook.

        Args:
            text: Message text (supports Google Chat markdown)
            use_payload_webhook: If True, send to payload webhook instead of response webhook

        Returns:
            True if sent successfully
        """
        webhook_url = self.payload_webhook_url if use_payload_webhook else self.response_webhook_url
        return await self._send_to_webhook(webhook_url, {"text": text})

    async def _send_card(self, card_payload: dict) -> bool:
        """
        Send card message to Google Chat webhook (response webhook).

        Args:
            card_payload: Card message payload with cardsV2 format

        Returns:
            True if sent successfully
        """
        return await self._send_to_webhook(self.response_webhook_url, card_payload)

    async def _send_to_webhook(self, webhook_url: str, payload: dict) -> bool:
        """
        Send payload to Google Chat webhook.

        Args:
            webhook_url: Webhook URL
            payload: JSON payload to send

        Returns:
            True if sent successfully
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    webhook_url,
                    json=payload,
                    timeout=10.0
                )

                if response.status_code == 200:
                    logger.debug("Notification sent successfully")
                    return True
                else:
                    logger.warning(
                        f"Failed to send notification: {response.status_code} - {response.text}"
                    )
                    return False

        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            return False
