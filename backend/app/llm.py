"""Small async helpers for calling chat models with structured JSON output."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

TModel = TypeVar("TModel", bound=BaseModel)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LLMCallError(RuntimeError):
    """Raised when a model call or its structured output cannot be used."""


class ChatModel(Protocol):
    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any: ...


def message_text(response: Any) -> str:
    """Extract plain text from a chat model response."""
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
        return "\n".join(parts)
    return str(content)


def extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating markdown fences and leading prose."""
    if not isinstance(text, str) or not text.strip():
        raise LLMCallError("model returned an empty response")
    candidates: list[str] = [text.strip()]
    candidates.extend(match.strip() for match in _JSON_BLOCK_RE.findall(text))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise LLMCallError("model response did not contain a valid JSON object")


async def call_json(
    model: ChatModel,
    messages: Any,
    schema: type[TModel],
    attempts: int = 2,
) -> TModel:
    """Call a model and validate JSON output, retrying a limited number of times."""
    last_error: Exception | None = None
    for _ in range(max(1, attempts)):
        try:
            response = await model.ainvoke(messages)
            payload = extract_json(message_text(response))
            return schema.model_validate(payload)
        except (LLMCallError, ValidationError, json.JSONDecodeError) as exc:
            last_error = exc
        except Exception as exc:  # transport / provider errors are retryable
            last_error = exc
    raise LLMCallError(f"model call failed after {max(1, attempts)} attempts: {last_error}")


async def call_text(model: ChatModel, messages: Any, attempts: int = 2) -> str:
    """Call a model for free-form (Markdown) output with limited retries."""
    last_error: Exception | None = None
    for _ in range(max(1, attempts)):
        try:
            response = await model.ainvoke(messages)
            text = message_text(response).strip()
            if text:
                return text
            last_error = LLMCallError("model returned an empty response")
        except Exception as exc:
            last_error = exc
    raise LLMCallError(f"model call failed after {max(1, attempts)} attempts: {last_error}")


__all__ = [
    "ChatModel",
    "LLMCallError",
    "call_json",
    "call_text",
    "extract_json",
    "message_text",
]
