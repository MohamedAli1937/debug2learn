from __future__ import annotations

import json
import logging
from typing import Any

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    genai = None  # type: ignore
    GENAI_AVAILABLE = False

from debug2learn.config.settings import AppConfig

logger = logging.getLogger(__name__)


def is_gemini_quota_error(error: Exception) -> bool:
    """Return whether Gemini rejected a request because its quota was exhausted."""
    message = str(error).lower()
    return "quota" in message or "resource_exhausted" in message or "429" in message


class BaseAgent:
    """
    Base class for all AI agents.
    
    Provides:
    - Gemini API client initialization
    - Common send/receive methods
    - JSON response parsing
    - Error handling
    """

    def __init__(self, config: AppConfig, system_prompt: str = ""):
        self.config = config
        self.system_prompt = system_prompt
        self._model: Any | None = None
        self._setup_client()

    def _setup_client(self):
        """Initialize the Gemini API client if library and key are available."""
        if not GENAI_AVAILABLE or not self.config.gemini.api_key:
            self._model = None
            return

        genai.configure(api_key=self.config.gemini.api_key)
        
        generation_config = genai.GenerationConfig(
            temperature=self.config.gemini.temperature,
            max_output_tokens=self.config.gemini.max_output_tokens,
        )

        self._model = genai.GenerativeModel(
            model_name=self.config.gemini.model,
            generation_config=generation_config,
            system_instruction=self.system_prompt if self.system_prompt else None,
        )

    async def _send(self, prompt: str) -> str:
        """Send a prompt to Gemini and return the text response."""
        if self._model is None:
            raise RuntimeError("Gemini model not initialized")
        
        try:
            response = await self._model.generate_content_async(prompt)
            return response.text or ""
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise

    def _send_sync(self, prompt: str) -> str:
        """Synchronous version of _send for simpler CLI usage."""
        if self._model is None:
            raise RuntimeError("Gemini model not initialized")
        
        try:
            response = self._model.generate_content(prompt)
            return response.text or ""
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise

    def _parse_json_response(self, response: str) -> dict[str, Any]:
        """
        Extract and parse JSON from the LLM response.
        
        Handles cases where the model wraps JSON in markdown code blocks.
        """
        text = response.strip()
        
        # Remove markdown code block wrappers
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        
        text = text.strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON within the response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            
            logger.warning("Failed to parse JSON from response, returning raw text")
            return {"raw_response": response}

    def _build_prompt(self, **kwargs: str) -> str:
        """Build a prompt from keyword arguments formatted as sections."""
        parts = []
        for key, value in kwargs.items():
            if value:
                header = key.replace("_", " ").title()
                parts.append(f"## {header}\n{value}")
        return "\n\n".join(parts)
