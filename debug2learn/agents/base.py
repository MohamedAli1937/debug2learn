from __future__ import annotations

import json
import logging
from typing import Any

try:
    from groq import Groq, AsyncGroq
    GROQ_AVAILABLE = True
except ImportError:
    Groq = None  # type: ignore
    AsyncGroq = None  # type: ignore
    GROQ_AVAILABLE = False

from debug2learn.config.settings import AppConfig

logger = logging.getLogger(__name__)


def is_groq_quota_error(error: Exception) -> bool:
    """Return whether Groq rejected a request because its quota or rate limit was exhausted."""
    message = str(error).lower()
    return "quota" in message or "resource_exhausted" in message or "429" in message


class BaseAgent:
    """
    Base class for all AI agents.
    
    Provides:
    - Groq API client initialization
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
        """Initialize the Groq API client if the library and key are available."""
        if not GROQ_AVAILABLE or not self.config.groq.api_key:
            self._model = None
            return

        self._model = Groq(api_key=self.config.groq.api_key)

    async def _send(self, prompt: str) -> str:
        """Send a prompt to Groq and return the text response."""
        if self._model is None:
            raise RuntimeError("Groq model not initialized")
        
        try:
            client = AsyncGroq(api_key=self.config.groq.api_key)
            response = await client.chat.completions.create(
                model=self.config.groq.model,
                messages=self._messages(prompt),
                temperature=self.config.groq.temperature,
                max_tokens=self.config.groq.max_output_tokens,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            raise

    def _send_sync(self, prompt: str) -> str:
        """Synchronous version of _send for simpler CLI usage."""
        if self._model is None:
            raise RuntimeError("Groq model not initialized")
        
        try:
            response = self._model.chat.completions.create(
                model=self.config.groq.model,
                messages=self._messages(prompt),
                temperature=self.config.groq.temperature,
                max_tokens=self.config.groq.max_output_tokens,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            raise

    def _messages(self, prompt: str) -> list[dict[str, str]]:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

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
