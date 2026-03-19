"""
Prompt generation service using xAI Grok-4.
Transforms PersonaOptions into detailed visual descriptions for Z-Image Turbo.
Outputs plain text prompts (not JSON).
"""
import httpx
import logging
from typing import Optional, Tuple

from models.requests import PersonaOptions

logger = logging.getLogger(__name__)

# xAI Grok pricing per 1M tokens (USD)
# Format: {"model": {"input": price_per_1M, "output": price_per_1M}}
GROK_PRICING = {
    # Grok 4 models
    "grok-4-1-fast-reasoning": {"input": 0.20, "cached":0.05, "output": 0.50},
    "grok-4-1-fast-non-reasoning": {"input": 0.20, "cached":0.05, "output": 0.50},
    "grok-4-fast-reasoning": {"input": 0.20, "cached":0.05, "output": 0.50},
    "grok-4-fast-non-reasoning": {"input": 0.20, "cached":0.05, "output": 0.50},
    "grok-4-0709": {"input": 3.00, "cached":0.75, "output": 15.00},
    "grok-code-fast-1": {"input": 0.20, "cached":0.02, "output": 1.50},
    # Grok 3 models
    "grok-3": {"input": 3.00, "cached":0.75, "output": 15.00},
    "grok-3-mini": {"input": 0.30, "cached":0.075, "output": 0.50},
}

# System prompt for Z-Image Turbo - outputs plain text descriptions
SYSTEM_PROMPT = '''You are a specialized prompt engineer a fast diffusion image generation model that generates highly realistic images indistinguishable from real human photographs. Your sole task is to create detailed, structured prompts for NSFW adult content featuring consenting adult in sexual or erotic scenarios.
WORKFLOW:
1. LOCK CORE ELEMENTS: 
   - Extract and preserve specified attributes - ethnicity, age, body type, hair, eyes, clothing/outfit as occupation, breast size. These are unchangeable constraints. Ignore kinks
   - Respect user prompt/ context, rewrite to the OUTPUT format

2. DEFINE COMPOSITION:
   - Shot type: full-body, medium shot, close-up, wide shot
   - Camera angle: front view, 45-degree angle, profile view, slightly from above/below
   - Lens specification: 35mm (wide), 50mm (standard), 85mm (portrait), 135mm (telephoto)

3. INJECT PROFESSIONAL DETAILS (always include these enhancements):
   - Image quality & aesthetic: masterpiece aesthetic, highly detailed, beautiful composition
   - Skin & photo tone: warm skin tone, warm photographic tones
   - Lighting: soft warm light that gently reflects facial features, flattering cinematic warm lighting
   - Body & face quality: professional model appearance, perfect body proportions, perfectly proportioned face, diverse and attractive facial features
   - Expression: alluring and kind facial expression, gentle seductive look with kindness, looks directly into the camera.

4. NUDITY LEVEL (based on context):
   - Revealing: low-cut, sheer fabrics, emphasizing curves
   - Partially covered: strategic concealment with hands, fabric, shadows
   - Nude: partial exposure with artistic lighting and poses, do not show nipples or vagina

OUTPUT RULES:
Be objective and concrete in all descriptions
NO metaphors, similes, or emotional/poetic language except for the fixed aesthetic terms above
NO negative phrasing — describe only what IS present
If text appears in scene, enclose exact text in double quotes ""
Target length: 180-280 words, structured and precise
Generate the ENTIRE prompt in the language determined by the ethnicity + nationality mapping above

PROMPT STRUCTURE (in the target language):
[Subject: age, ethnicity label woman, body type, breast size, professional model appearance, perfect proportions] + [Hair: style, color, texture] + [Eyes: color, alluring kind expression] + [Face: diverse attractive features] + [Clothing/state with fabric textures] + [Pose and body language] + [Environment with spatial depth] + [Lighting: soft warm light reflecting features, warm cinematic tones] + [Skin: warm skin tone, detailed pores and texture] + [Overall aesthetic: masterpiece aesthetic, beautiful composition, warm photo tones] + [Material textures throughout]

CLEANUP CONSTRAINTS (add at end, in the target language):
correct human anatomy, natural body proportions, sharp focus, smooth skin texture, no extra limbs, no distorted features, plain background, no logos, no watermarks

OUTPUT: Generate ONLY the final visual description prompt in the target language. No explanations, no analysis, no additional text.
'''


class PromptGenerator:
    """
    Service for generating image prompts using xAI Grok-4.
    Transforms PersonaOptions into detailed visual descriptions.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.x.ai/v1",
        model: str = "grok-3-mini",
        timeout: float = 100.0
    ):
        """
        Initialize prompt generator.

        Args:
            api_key: xAI API key
            base_url: API base URL
            model: Model name to use
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.timeout = timeout

    async def generate_prompt(
        self,
        persona: PersonaOptions,
        context: Optional[str] = None
    ) -> Tuple[str, Optional[dict]]:
        """
        Generate prompt from persona options.

        Args:
            persona: Character persona configuration
            context: Optional additional context (e.g., "After a long shift, relaxing at home")

        Returns:
            Tuple of (prompt, token_usage) where token_usage is a dict with:
                - model: Model name used
                - prompt_tokens: Input token count
                - completion_tokens: Output token count
                - total_tokens: Total token count
                - input_cost: Cost for input tokens (USD)
                - output_cost: Cost for output tokens (USD)
                - total_cost: Total cost (USD)
            token_usage is None if fallback prompt was used.

        Raises:
            RuntimeError: If API call fails
        """
        user_prompt = self._build_user_prompt(persona, context)

        logger.info(f"Generating prompt for character: {persona.name}")
        logger.debug(f"User prompt: {user_prompt}")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.7,
                        "max_tokens": 1500
                    },
                    timeout=self.timeout
                )
                response.raise_for_status()
                result = response.json()

                # Log token usage and cost
                usage = result.get("usage", {})
                logger.debug(f"Raw usage response: {usage}")
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", 0)

                # Get detailed token breakdowns from nested objects (xAI API structure)
                prompt_details = usage.get("prompt_tokens_details", {})
                cached_tokens = prompt_details.get("cached_tokens", 0)

                completion_details = usage.get("completion_tokens_details", {})
                reasoning_tokens = completion_details.get("reasoning_tokens", 0)

                # Calculate cost based on model pricing
                # Note: prompt_tokens INCLUDES cached_tokens, so we subtract to avoid double-charging
                pricing = GROK_PRICING.get(self.model, {"input": 0, "cached": 0, "output": 0})
                #non_cached_input = prompt_tokens - cached_tokens
                input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
                cached_cost = (cached_tokens / 1_000_000) * pricing["cached"]
                # Reasoning tokens are charged at output rate
                output_cost = ((completion_tokens + reasoning_tokens) / 1_000_000) * pricing["output"]
                total_cost = input_cost + cached_cost + output_cost

                logger.info(
                    f"[Grok API] Model: {self.model} | "
                    f"Tokens - prompt: {prompt_tokens} (cached: {cached_tokens}), completion: {completion_tokens}, reasoning: {reasoning_tokens}, total: {total_tokens} | "
                    f"Cost: ${total_cost:.6f} (in: ${input_cost:.6f}, cached: ${cached_cost:.6f}, out: ${output_cost:.6f})"
                )

                # Build token usage info
                token_usage = {
                    "model": self.model,
                    "prompt_tokens": prompt_tokens,
                    "cached_tokens": cached_tokens,
                    "completion_tokens": completion_tokens,
                    "reasoning_tokens": reasoning_tokens,
                    "total_tokens": total_tokens,
                    "input_cost": input_cost,
                    "cached_cost": cached_cost,
                    "output_cost": output_cost,
                    "total_cost": total_cost
                }

                # Extract response content
                content = result["choices"][0]["message"]["content"]
                prompt = content.strip()
                logger.info(f"Generated prompt: {len(prompt)} chars")
                logger.debug(f"Prompt content: {prompt[:200]}...")
                return prompt, token_usage

        except httpx.HTTPStatusError as e:
            logger.error(f"xAI API HTTP error: {e.response.status_code} - {e.response.text}")
            logger.warning(f"Using fallback prompt for character: {persona.name}")
            return self._build_fallback_prompt(persona, context), None

        except httpx.TimeoutException:
            logger.error("xAI API timeout")
            logger.warning(f"Using fallback prompt for character: {persona.name}")
            return self._build_fallback_prompt(persona, context), None

        except (KeyError, IndexError) as e:
            logger.error(f"Failed to parse API response: {e}")
            logger.warning(f"Using fallback prompt for character: {persona.name}")
            return self._build_fallback_prompt(persona, context), None

        except Exception as e:
            logger.error(f"xAI API error: {e}")
            logger.warning(f"Using fallback prompt for character: {persona.name}")
            return self._build_fallback_prompt(persona, context), None

    def _build_user_prompt(
        self,
        persona: PersonaOptions,
        context: Optional[str] = None
    ) -> str:
        """
        Build the user prompt from persona options.
        Format: simple key-value pairs without dashes.

        Args:
            persona: Character persona configuration
            context: Optional additional context

        Returns:
            Formatted user prompt string
        """
        parts = ["Persona:"]

        # Style (from persona.style)
        parts.append(f"Style: {persona.style.value}")

        # Core attributes (always include)
        parts.append(f"Ethnicity: {persona.ethnicity.value.replace('_', ' ').title()}")
        parts.append(f"Age: {persona.age}yo")
        parts.append(f"Iris Color: {persona.eyeColor.value.title()}")
        parts.append(f"Body Type: {persona.bodyType.value}")
        parts.append(f"Breast Size: {persona.breastSize.value.title()}")
        parts.append(f"Hair Style: {persona.hairStyle.value.title()}")
        parts.append(f"Hair Color: {persona.hairColor.value.title()}")

        # Optional attributes
        if persona.occupation:
            occupation_display = persona.occupation.value.replace('_', ' ').title()
            parts.append(f"Occupation: {occupation_display}")

        if persona.personality:
            parts.append(f"Personality: {persona.personality.value.title()}")

        if persona.relationship:
            relationship_display = persona.relationship.value.replace('_', ' ').title()
            parts.append(f"Relationship: {relationship_display}")

        if persona.kinks and len(persona.kinks) > 0:
            kink_values = [k.value.replace('_', ' ').title() for k in persona.kinks]
            parts.append(f"Kinks: {', '.join(kink_values)}")

        # Add context/nudity level if provided
        if context:
            parts.append(f"Nudity Level: {context}")

        return "\n".join(parts)

    def _build_fallback_prompt(
        self,
        persona: PersonaOptions,
        context: Optional[str] = None
    ) -> str:
        """
        Build a fallback prompt if LLM fails.
        Plain text format optimized for Z-Image Turbo.

        Args:
            persona: Character persona configuration
            context: Optional scene context

        Returns:
            Basic prompt string
        """
        age_desc = f"{persona.age} year old"
        ethnicity = persona.ethnicity.value.replace("_", " ")
        hair = f"{persona.hairColor.value} {persona.hairStyle.value} hair"
        eyes = f"{persona.eyeColor.value} eyes"
        body = persona.bodyType.value
        breast = persona.breastSize.value

        # Build prompt following Z-Image Turbo structure
        prompt = (
            f"Full-body shot, front view, 85mm portrait lens, "
            f"{age_desc} {ethnicity} woman, {body} body type, {breast} breasts, "
            f"{hair}, {eyes}, "
            f"natural skin texture with visible pores, "
            f"soft diffused daylight, warm color palette, "
            f"soft blurred background, sharp subject focus, "
            f"correct human anatomy, natural body proportions, "
            f"sharp focus, smooth skin texture, no extra limbs, "
            f"no distorted features, plain background, no logos, no watermarks"
        )

        if persona.occupation:
            occupation = persona.occupation.value.replace('_', ' ')
            prompt = prompt.replace("woman,", f"woman ({occupation}),")

        if context:
            prompt = f"{prompt}, {context}"

        return prompt
