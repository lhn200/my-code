"""Unified API error semantics."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        fields: Iterable[Mapping[str, str]] | None = None,
        thread_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = [dict(field) for field in (fields or [])]
        self.thread_id = thread_id

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "error": {
                "code": self.code,
                "message": self.message,
                "fields": self.fields,
            }
        }
        if self.thread_id:
            body["thread_id"] = self.thread_id
        return body


def field_error(field: str, error_type: str, message: str) -> dict[str, str]:
    return {"field": field, "type": error_type, "message": message}


def too_many_jobs(limit: int) -> ApiError:
    return ApiError(
        422,
        "too_many_jobs",
        f"at most {limit} jobs are allowed per run",
        fields=[field_error("jobs", "too_many_jobs", f"at most {limit} jobs per run")],
    )


def thread_not_found(thread_id: str) -> ApiError:
    return ApiError(404, "thread_not_found", f"run {thread_id} was not found")


def snapshot_not_found(checkpoint_id: str) -> ApiError:
    return ApiError(404, "snapshot_not_found", f"checkpoint {checkpoint_id} was not found")


def internal_error(thread_id: str | None = None) -> ApiError:
    return ApiError(
        500,
        "internal_error",
        "internal error; retry later or contact support with the thread_id",
        thread_id=thread_id,
    )


def _format_loc(loc: tuple[Any, ...]) -> str:
    parts = list(loc)
    if parts and parts[0] in {"body", "query", "path", "header", "cookie"}:
        parts = parts[1:]
    rendered = ""
    for part in parts:
        if isinstance(part, int):
            rendered += f"[{part}]"
        elif rendered:
            rendered += f".{part}"
        else:
            rendered = str(part)
    return rendered or "body"


_TYPE_MAP = {
    "extra_forbidden": "unexpected_field",
    "missing": "missing",
    "string_type": "string_type",
    "int_type": "int_type",
    "float_type": "float_type",
    "bool_type": "bool_type",
    "list_type": "list_type",
    "dict_type": "object_type",
}


def validation_fields(errors: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Convert FastAPI/Pydantic errors into stable, field-level entries."""
    converted: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for error in errors:
        field = _format_loc(tuple(error.get("loc") or ()))
        raw_type = str(error.get("type") or "invalid")
        error_type = _TYPE_MAP.get(raw_type, raw_type)
        message = str(error.get("msg") or "invalid value")
        key = (field, error_type)
        if key in seen:
            continue
        seen.add(key)
        converted.append(field_error(field, error_type, message))
    return sorted(converted, key=lambda item: (item["field"], item["type"]))


__all__ = [
    "ApiError",
    "field_error",
    "internal_error",
    "snapshot_not_found",
    "thread_not_found",
    "too_many_jobs",
    "validation_fields",
]
