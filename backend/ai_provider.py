from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from backend.config import (
    AI_API_KEY,
    AI_BASE_URL,
    AI_MODEL,
    AI_PROVIDER,
)
from backend.exceptions import ProviderUnavailable

# Simple per-request timeout and retry behavior
DEFAULT_TIMEOUT_SECONDS = 45
DEFAULT_MAX_RETRIES = 2


class BaseProvider:
    name = "unknown"

    def chat(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 2000,
    ) -> str:
        raise NotImplementedError

    def is_available(self) -> bool:
        raise NotImplementedError


class NoProvider(BaseProvider):
    name = "none"

    def chat(self, system: str, user: str, **kwargs: Any) -> str:
        raise ProviderUnavailable()

    def is_available(self) -> bool:
        return False


class OpenAICompatibleProvider(BaseProvider):
    name = "openai-compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        if self.base_url in ("https://api.openai.com/v1", ""):
            return True
        try:
            with httpx.Client(timeout=5.0, follow_redirects=True) as client:
                resp = client.get(self.base_url + "/models", headers={
                    "Authorization": f"Bearer {self.api_key}",
                })
                return resp.status_code in (200, 401, 403, 404)
        except Exception:
            return False

    def chat(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 2000,
    ) -> str:
        model = model or self.model
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        last_error: Exception | None = None
        for attempt in range(1 + self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                    resp = client.post(
                        self.base_url + "/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    )
                if resp.status_code == 429:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                resp.raise_for_status()
                data = resp.json()
                choices = data.get("choices")
                if not choices:
                    raise ProviderUnavailable("Empty chat response from provider")
                content = choices[0].get("message", {}).get("content")
                if not content:
                    raise ProviderUnavailable("Provider returned empty message content")
                return content
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code == 401:
                    raise ProviderUnavailable("AI provider rejected the API key") from exc
                if exc.response.status_code == 404:
                    raise ProviderUnavailable("AI provider endpoint not found") from exc
            except httpx.TimeoutException as exc:
                last_error = exc
            except ProviderUnavailable:
                raise
            except Exception as exc:
                last_error = exc
        raise ProviderUnavailable(f"AI provider request failed: {last_error}")


def build_provider() -> BaseProvider:
    provider = AI_PROVIDER.strip().lower()
    if provider == "none" or provider == "":
        return NoProvider()
    if provider in ("openai-compatible", "openai"):
        return OpenAICompatibleProvider(
            base_url=AI_BASE_URL,
            api_key=AI_API_KEY,
            model=AI_MODEL,
        )
    if provider in ("anthropic-compatible", "anthropic"):
        return OpenAICompatibleProvider(
            base_url=AI_BASE_URL,
            api_key=AI_API_KEY,
            model=AI_MODEL,
        )
    return NoProvider()


def provider_status() -> dict[str, Any]:
    provider = build_provider()
    available = provider.is_available()
    return {
        "provider": AI_PROVIDER or "none",
        "available": available,
        "base_url": AI_BASE_URL if AI_PROVIDER else None,
        "model": AI_MODEL,
    }
