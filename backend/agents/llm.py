"""LLM provider abstraction.

A single, minimal interface (``LLMProvider.complete_json``) keeps the agents
decoupled from any specific vendor. Adding OpenAI/Gemini/etc. is a new
provider class — agent code never has to change.

The deterministic provider is the **always-on** fallback: if no real
provider is configured, or if the real provider fails, the orchestrator
routes through deterministic rules per CLAUDE.md section 41.

The provider contract is intentionally narrow:
    complete_json(system: str, user: str, schema: type[T]) -> T

The provider is responsible for asking the LLM to emit valid JSON, parsing
the response, and validating it against the supplied Pydantic schema.
Anything outside that contract fails fast — agents never see raw text.

See CLAUDE.md sections 19, 20, 21, 41.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """Raised when a provider cannot complete a request.

    Callers should catch this and route to the deterministic fallback.
    """


class LLMProvider(ABC, Generic[T]):
    """Abstract base class for all LLM providers.

    Subclasses implement :meth:`complete_json` and raise
    :class:`LLMUnavailable` on any error.
    """

    @abstractmethod
    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> T:
        """Return a schema-validated instance, or raise :class:`LLMUnavailable`."""


# ---------------------------------------------------------------------------
# Deterministic provider — used in tests and as the always-on fallback.
# ---------------------------------------------------------------------------
class DeterministicProvider(LLMProvider):
    """Returns whatever the agent prepared ahead of time.

    Agents store the fallback output on the provider instance before
    requesting a completion. This lets tests assert exact behavior without
    monkey-patching, and gives the orchestrator a guaranteed-safe path when
    no real LLM is configured.
    """

    def __init__(self) -> None:
        self._queue: list[Any] = []

    def push(self, value: Any) -> None:
        """Queue a pre-built response."""
        self._queue.append(value)

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> T:
        if not self._queue:
            raise LLMUnavailable("DeterministicProvider has no queued response")
        raw = self._queue.pop(0)
        if isinstance(raw, schema):
            return raw
        if isinstance(raw, dict):
            try:
                return schema.model_validate(raw)
            except ValidationError as exc:
                raise LLMUnavailable(
                    f"Deterministic payload failed schema: {exc}"
                ) from exc
        raise LLMUnavailable(
            f"DeterministicProvider received unsupported payload type {type(raw).__name__}"
        )


# ---------------------------------------------------------------------------
# Anthropic provider — used when ANTHROPIC_API_KEY is configured.
# ---------------------------------------------------------------------------
class AnthropicProvider(LLMProvider):
    """Calls the Anthropic SDK. Optional dependency."""

    def __init__(self, *, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        self._api_key = api_key
        self._model = model
        self._client = self._build_client(api_key)

    @staticmethod
    def _build_client(api_key: str):
        try:
            from anthropic import Anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover — exercised only when SDK is present
            raise LLMUnavailable(
                "anthropic SDK not installed; cannot use AnthropicProvider"
            ) from exc
        if not api_key:
            raise LLMUnavailable("ANTHROPIC_API_KEY not configured")
        return Anthropic(api_key=api_key)

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> T:
        instruction = (
            system
            + "\n\nYou MUST respond with a single JSON object that matches the "
            "following Pydantic schema. Do not include any other text.\n\n"
            f"{schema.model_json_schema()}"
        )
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=instruction,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # noqa: BLE001 — convert anything into LLMUnavailable
            logger.warning("AnthropicProvider call failed: %s", exc)
            raise LLMUnavailable(str(exc)) from exc

        text = self._extract_text(response)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMUnavailable(f"LLM returned non-JSON: {text!r}") from exc
        try:
            return schema.model_validate(payload)
        except ValidationError as exc:
            raise LLMUnavailable(f"LLM JSON failed schema: {exc}") from exc

    @staticmethod
    def _extract_text(response: Any) -> str:
        for block in getattr(response, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                return text
        return ""


# ---------------------------------------------------------------------------
# Groq provider — used when LLM_PROVIDER=groq.
# ---------------------------------------------------------------------------
class GroqProvider(LLMProvider):
    """Calls the Groq SDK. Optional dependency."""

    def __init__(self, *, api_key: str, model: str = "llama-3.3-70b-versatile") -> None:
        self._api_key = api_key
        self._model = model
        self._client = self._build_client(api_key)

    @staticmethod
    def _build_client(api_key: str):
        try:
            from groq import Groq  # type: ignore
        except ImportError as exc:
            raise LLMUnavailable(
                "groq SDK not installed; cannot use GroqProvider"
            ) from exc
        if not api_key:
            raise LLMUnavailable("LLM_API_KEY not configured")
        return Groq(api_key=api_key)

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> T:
        instruction = (
            system
            + "\n\nYou MUST respond with a single JSON object that matches the "
            "following Pydantic schema. Do not include any other text.\n\n"
            f"{schema.model_json_schema()}"
        )
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            logger.warning("GroqProvider call failed: %s", exc)
            raise LLMUnavailable(str(exc)) from exc

        text = response.choices[0].message.content or ""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMUnavailable(f"LLM returned non-JSON: {text!r}") from exc
        try:
            return schema.model_validate(payload)
        except ValidationError as exc:
            raise LLMUnavailable(f"LLM JSON failed schema: {exc}") from exc

# ---------------------------------------------------------------------------
# Convenience factory used by the orchestrator.
# ---------------------------------------------------------------------------
def default_provider() -> LLMProvider:
    """Pick the best provider for the current environment.

    Resolution order:
        1. Real provider (Groq or Anthropic) if configured.
        2. Deterministic provider otherwise.
    """
    import os

    api_key = os.environ.get("LLM_API_KEY", "")
    provider_type = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    model = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")

    if api_key:
        try:
            if provider_type == "groq":
                return GroqProvider(api_key=api_key, model=model)
            elif provider_type == "anthropic":
                return AnthropicProvider(api_key=api_key, model=model)
        except LLMUnavailable:
            pass

    return DeterministicProvider()



__all__ = [
    "AnthropicProvider",
    "DeterministicProvider",
    "LLMProvider",
    "LLMUnavailable",
    "default_provider",
]