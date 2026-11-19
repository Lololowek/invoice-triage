"""OpenAI-compatible chat client. Works with OpenAI, vLLM, Ollama, llama.cpp server.

Configuration comes from the environment only; no keys in code:
    LLM_MODEL            required
    LLM_BASE_URL         e.g. http://localhost:11434/v1 (Ollama); unset = api.openai.com
    LLM_API_KEY          local servers ignore it, the client needs a non-empty string
    LLM_RESPONSE_FORMAT  json_schema (default) | json_object
    LLM_ANSWER_FORMAT    compact (default) | full - see llm/mapping.py
    LLM_EXTRA_BODY       optional JSON merged into the request body
    LLM_TIMEOUT_S        default 180
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from openai import OpenAI


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMSettings:
    model: str
    base_url: str | None = None
    api_key: str = "not-needed"
    response_format: Literal["json_schema", "json_object"] = "json_schema"
    answer_format: Literal["compact", "full"] = "compact"
    timeout_s: float = 180.0
    extra_body: dict[str, Any] | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> LLMSettings:
        model = env.get("LLM_MODEL", "").strip()
        if not model:
            raise ConfigError(
                "LLM_MODEL is not set. Copy .env.example to .env in the working directory "
                "(it is read automatically), or run with --oracle for an offline run."
            )
        response_format = env.get("LLM_RESPONSE_FORMAT", "json_schema").strip()
        if response_format not in ("json_schema", "json_object"):
            raise ConfigError(
                f"LLM_RESPONSE_FORMAT must be json_schema or json_object, got {response_format!r}"
            )
        answer_format = env.get("LLM_ANSWER_FORMAT", "compact").strip()
        if answer_format not in ("compact", "full"):
            raise ConfigError(f"LLM_ANSWER_FORMAT must be compact or full, got {answer_format!r}")
        extra_raw = env.get("LLM_EXTRA_BODY", "").strip()
        try:
            extra_body = json.loads(extra_raw) if extra_raw else None
        except json.JSONDecodeError as e:
            raise ConfigError(f"LLM_EXTRA_BODY is not valid JSON: {e}") from e
        return cls(
            model=model,
            base_url=env.get("LLM_BASE_URL") or None,
            api_key=env.get("LLM_API_KEY") or "not-needed",
            response_format=response_format,  # type: ignore[arg-type]
            answer_format=answer_format,  # type: ignore[arg-type]
            timeout_s=float(env.get("LLM_TIMEOUT_S", "180")),
            extra_body=extra_body,
        )


class ChatClient(Protocol):
    """Anything that turns chat messages into a JSON string. Tests use a scripted fake."""

    name: str

    def complete(
        self, messages: list[dict[str, str]], json_schema: dict[str, Any], schema_name: str
    ) -> str: ...


class OpenAICompatibleClient:
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings
        self.name = settings.model
        self._client = OpenAI(
            base_url=settings.base_url, api_key=settings.api_key, timeout=settings.timeout_s
        )

    def complete(
        self, messages: list[dict[str, str]], json_schema: dict[str, Any], schema_name: str
    ) -> str:
        if self.settings.response_format == "json_schema":
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": json_schema, "strict": True},
            }
        else:
            response_format = {"type": "json_object"}
        response = self._client.chat.completions.create(
            model=self.settings.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=0,
            response_format=response_format,  # type: ignore[arg-type]
            extra_body=self.settings.extra_body,
        )
        return response.choices[0].message.content or ""
