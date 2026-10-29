"""HTTP client for the local Ollama chat API."""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
_HEALTH_TIMEOUT = httpx.Timeout(3.0, connect=2.0)


class OllamaServiceError(Exception):
    """Base error for Ollama calls. failure_code is safe to store."""

    failure_code = "ollama_error"


class OllamaUnavailableError(OllamaServiceError):
    failure_code = "ollama_unavailable"


class OllamaTimeoutError(OllamaServiceError):
    failure_code = "ollama_timeout"


class OllamaModelError(OllamaServiceError):
    failure_code = "ollama_model_error"


class InvalidModelOutputError(OllamaServiceError):
    failure_code = "invalid_model_output"


class OllamaService:
    """Call Ollama and return parsed JSON. Prompts and email bodies are not logged."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def check_reachable(self) -> bool:
        """Return whether Ollama's version endpoint responds. The body is discarded."""
        try:
            async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
                response = await client.get(f"{self._settings.ollama_base_url}/api/version")
        except httpx.HTTPError as exc:
            logger.warning("Ollama health check failed: %s", exc.__class__.__name__)
            return False
        if response.status_code != 200:
            logger.warning("Ollama health check returned HTTP %s", response.status_code)
            return False
        return True

    async def chat_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        operation: str,
        num_predict: int = 400,
    ) -> dict[str, Any]:
        """Request one JSON object. operation is a short name such as classification."""
        payload = {
            "model": self._settings.ollama_model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0, "num_predict": num_predict},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        timeout = httpx.Timeout(
            self._settings.ollama_timeout_seconds,
            connect=self._settings.ollama_connect_timeout_seconds,
        )
        logger.info(
            "Ollama request started operation=%s model=%s",
            operation,
            self._settings.ollama_model,
        )
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self._settings.ollama_base_url}/api/chat",
                    json=payload,
                )
        except httpx.ReadTimeout:
            logger.warning("Ollama request timed out operation=%s", operation)
            raise OllamaTimeoutError("Ollama did not respond in time") from None
        except httpx.ConnectError:
            logger.warning("Ollama is unreachable operation=%s", operation)
            raise OllamaUnavailableError("Ollama is unreachable") from None
        except httpx.TimeoutException:
            logger.warning("Ollama request timed out operation=%s", operation)
            raise OllamaTimeoutError("Ollama did not respond in time") from None
        except httpx.HTTPError:
            logger.warning("Ollama request failed operation=%s", operation)
            raise OllamaUnavailableError("Ollama is unreachable") from None

        if response.status_code != 200 or _response_error(response):
            logger.warning(
                "Ollama request failed operation=%s status=%s",
                operation,
                response.status_code,
            )
            raise OllamaModelError("Ollama could not complete the request")

        content = _message_content(response)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Ollama returned invalid JSON operation=%s", operation)
            raise InvalidModelOutputError("model output was not valid JSON") from None
        if not isinstance(parsed, dict):
            logger.warning("Ollama returned a non-object operation=%s", operation)
            raise InvalidModelOutputError("model output was not a JSON object")
        return parsed


def load_prompt(filename: str) -> str:
    """Read a prompt file by name. The filename is not taken from email content."""
    return _read_prompt(filename)


@lru_cache
def _read_prompt(filename: str) -> str:
    path = _PROMPT_DIR / filename
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        logger.error("Prompt file could not be read: %s", filename)
        raise OllamaServiceError("prompt file is unavailable") from None
    if not text:
        raise OllamaServiceError("prompt file is empty")
    return text


def _response_error(response: httpx.Response) -> bool:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return True
    return isinstance(payload, dict) and bool(payload.get("error")) and "message" not in payload


def _message_content(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        raise InvalidModelOutputError("model output was not valid JSON") from None
    if not isinstance(payload, dict):
        raise InvalidModelOutputError("model output was not a JSON object")
    message = payload.get("message")
    if not isinstance(message, dict):
        raise InvalidModelOutputError("model output was missing a message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise InvalidModelOutputError("model output was empty")
    return content
