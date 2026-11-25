"""Single-entry context assembly for session windows.

Every truncation and budget decision lives here. Nodes must pass their rendered
current input and let this module decide what history, summary and memory fit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..config import Settings
from ..prompts.loader import wrap_untrusted
from ..state import ensure_memory_defaults
from .token_budget import count_tokens

SUMMARY_LABELS: tuple[tuple[str, str], ...] = (
    ("facts", "已确认事实"),
    ("open_questions", "未解决问题"),
    ("preferences", "用户偏好"),
    ("constraints", "约束条件"),
    ("decisions", "已做决定"),
)
_HEAD_RATIO = 0.7
_MEMORY_COMPRESS_MARKER = "…[已压缩]"
_SUMMARY_COMPRESS_MARKER = "\n...[摘要已压缩]..."


class ContextOverflow(RuntimeError):
    """The context cannot fit the budget even after every trimming step."""

    def __init__(self, message: str, meta: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.meta = meta or {}


@dataclass(frozen=True)
class AssembledContext:
    messages: list[tuple[str, str]]
    meta: dict[str, Any]


def truncate_message(text: str, max_chars: int) -> tuple[str, int]:
    """Keep the head 70% and tail 30% of an over-long message copy."""
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    if max_chars <= 0 or len(text) <= max_chars:
        return text, 0
    head = int(max_chars * _HEAD_RATIO)
    tail = max_chars - head
    omitted = len(text) - head - tail
    marker = f"\n...[已截断 {omitted} 字]...\n"
    return text[:head] + marker + text[-tail:], omitted


def assemble_context(
    state: Mapping[str, Any],
    settings: Settings,
    current_input: str,
    *,
    memory_enabled: bool = True,
) -> AssembledContext:
    """Assemble memory, summary, recent turns and the current input.

    Sections consume only what they need; trimming only starts when the total
    exceeds the configured budget, in the fixed order memory -> oldest turns ->
    summary. The current input is never dropped.
    """
    state = ensure_memory_defaults(state)
    budget = settings.session_context_budget
    current_text, current_truncated = truncate_message(
        current_input, settings.max_message_chars
    )
    current_tokens = count_tokens(current_text)
    if current_tokens > budget:
        raise ContextOverflow(
            "current input exceeds the session context budget",
            {
                "reason": "current_input_exceeds_budget",
                "budget": {"total": budget},
                "tokens": {"current_input": current_tokens, "total": current_tokens},
            },
        )

    summary_text = _render_summary(state.get("session_summary"))
    memory_entries = _memory_entries(state) if memory_enabled else []
    memory_top = min(len(memory_entries), settings.memory_top_k)
    turns = _pending_turns(state)
    normalized_turns: list[tuple[int, list[tuple[str, str]], int]] = []
    for item in turns:
        messages, truncated = _render_turn(item, settings.max_message_chars)
        if messages:
            normalized_turns.append((int(item["turn"]), messages, truncated))

    def build(
        memory_count: int,
        memory_cap: int,
        keep_turns: int,
        summary_limit: int | None,
    ) -> tuple[AssembledContext, int]:
        memory_text, memory_truncated = _render_memory(
            memory_entries, memory_count, memory_cap
        )
        kept = normalized_turns[-keep_turns:] if keep_turns > 0 else []
        summary_out = summary_text
        summary_compressed = False
        if summary_limit is not None:
            overhead = count_tokens(wrap_untrusted("", "SESSION_SUMMARY")) + 2
            summary_out, summary_compressed = _compress_to_tokens(
                summary_text,
                max(0, summary_limit - overhead),
                _SUMMARY_COMPRESS_MARKER,
            )

        messages: list[tuple[str, str]] = []
        tokens = {
            "memory": 0,
            "summary": 0,
            "recent_turns": 0,
            "current_input": current_tokens,
        }
        if memory_text:
            messages.append(("human", memory_text))
            tokens["memory"] = count_tokens(memory_text)
        if summary_out:
            wrapped = wrap_untrusted(summary_out, "SESSION_SUMMARY")
            messages.append(("human", wrapped))
            tokens["summary"] = count_tokens(wrapped)
        turn_truncated = 0
        for _number, turn_messages, truncated in kept:
            turn_truncated += truncated
            for role, text in turn_messages:
                messages.append((role, text))
                tokens["recent_turns"] += count_tokens(text)
        if current_text:
            messages.append(("human", current_text))

        total = sum(tokens.values())
        tokens["total"] = total
        dropped_turns = len(normalized_turns) - len(kept)
        dropped_memory = memory_top - memory_count
        truncated = bool(
            current_truncated
            or memory_truncated
            or summary_compressed
            or turn_truncated
            or dropped_turns
            or dropped_memory
        )
        meta: dict[str, Any] = {
            "budget": {
                "total": budget,
                "memory": settings.context_memory_tokens,
                "summary": settings.context_summary_tokens,
                "recent_turns": settings.context_recent_turns_tokens,
                "current_input": settings.context_current_input_tokens,
            },
            "tokens": tokens,
            "memory_count": memory_count,
            "memory_char_limit": memory_cap,
            "turn_count": len(kept),
            "dropped_turns": dropped_turns,
            "dropped_memory": dropped_memory,
            "summary_compressed": summary_compressed,
            "truncated": truncated,
            "overflow": False,
        }
        return AssembledContext(messages=messages, meta=meta), total

    # Pending turns are kept in full until a summary exists; after the first
    # summary only the most recent window is replayed verbatim.
    has_summary = bool(summary_text)
    baseline_keep = (
        min(len(normalized_turns), settings.recent_turns_keep)
        if has_summary
        else len(normalized_turns)
    )
    baseline, total = build(
        memory_top, settings.memory_max_content_chars, baseline_keep, None
    )
    if total <= budget:
        return baseline

    # 1. Reduce memory count, then compress each entry.
    counts = sorted({memory_top, min(3, memory_top), min(1, memory_top), 0}, reverse=True)
    caps = sorted(
        {
            settings.memory_max_content_chars,
            min(150, settings.memory_max_content_chars),
            min(100, settings.memory_max_content_chars),
        },
        reverse=True,
    )
    for count in counts:
        for cap in caps:
            if count == memory_top and cap == settings.memory_max_content_chars:
                continue
            candidate, candidate_total = build(count, cap, baseline_keep, None)
            if candidate_total <= budget:
                return candidate

    # 2. Drop the oldest turns, but always keep the configured minimum.
    keep = baseline_keep
    min_keep = min(settings.min_recent_turns, keep)
    while keep > min_keep:
        keep -= 1
        candidate, candidate_total = build(0, caps[-1], keep, None)
        if candidate_total <= budget:
            return candidate

    # 3. Compress the summary as the last resort.
    summary_limit = min(600, settings.context_summary_tokens)
    candidate, candidate_total = build(0, caps[-1], min_keep, summary_limit)
    if candidate_total <= budget:
        return candidate

    overflow_meta = dict(candidate.meta)
    overflow_meta["overflow"] = True
    overflow_meta["reason"] = "budget_exceeded"
    raise ContextOverflow(
        "context budget exceeded after trimming memory, turns and summary",
        overflow_meta,
    )


def _pending_turns(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    through = state.get("summarized_through_turn") or 0
    try:
        through = int(through)
    except (TypeError, ValueError):
        through = 0
    pending: list[dict[str, Any]] = []
    for item in state.get("session_turns") or []:
        if not isinstance(item, Mapping):
            continue
        number = item.get("turn")
        if not isinstance(number, int) or number <= through:
            continue
        pending.append(dict(item))
    pending.sort(key=lambda item: int(item["turn"]))
    return pending


def _memory_entries(state: Mapping[str, Any]) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for item in state.get("memory_context") or []:
        if isinstance(item, Mapping):
            content = str(item.get("content") or "").strip()
            kind = str(item.get("kind") or "fact").strip() or "fact"
        elif isinstance(item, str):
            content = item.strip()
            kind = "fact"
        else:
            continue
        if content:
            entries.append((kind, content))
    return entries


def _render_memory(
    entries: Sequence[tuple[str, str]], count: int, cap: int
) -> tuple[str, bool]:
    if count <= 0:
        return "", False
    lines: list[str] = []
    truncated = False
    for kind, content in list(entries)[:count]:
        if cap > 0 and len(content) > cap:
            content = content[: max(0, cap - len(_MEMORY_COMPRESS_MARKER))] + _MEMORY_COMPRESS_MARKER
            truncated = True
        lines.append(f"- [{kind}] {content}")
    if not lines:
        return "", truncated
    return wrap_untrusted("\n".join(lines), "USER_MEMORY"), truncated


def _render_summary(summary: Any) -> str:
    if not isinstance(summary, Mapping):
        return ""
    lines: list[str] = []
    for key, label in SUMMARY_LABELS:
        values = summary.get(key)
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, (list, tuple)):
            continue
        items = [str(value).strip() for value in values if str(value).strip()]
        if items:
            lines.append(f"{label}：{'；'.join(items)}")
    return "\n".join(lines)


def _render_turn(item: Mapping[str, Any], max_chars: int) -> tuple[list[tuple[str, str]], int]:
    messages: list[tuple[str, str]] = []
    truncated = 0
    if "user" in item or "assistant" in item:
        for key, role in (("user", "human"), ("assistant", "ai")):
            text = item.get(key)
            if isinstance(text, str) and text.strip():
                clipped, omitted = truncate_message(text, max_chars)
                messages.append((role, clipped))
                truncated += omitted
        return messages, truncated
    text = item.get("content")
    if isinstance(text, str) and text.strip():
        role = "ai" if str(item.get("role") or "").lower() in {"assistant", "ai"} else "human"
        clipped, omitted = truncate_message(text, max_chars)
        return [(role, clipped)], omitted
    return messages, truncated


def _compress_to_tokens(text: str, limit: int, marker: str) -> tuple[str, bool]:
    if not text:
        return "", False
    if limit <= 0:
        return marker, True
    if count_tokens(text) <= limit:
        return text, False
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if count_tokens(text[:middle] + marker) <= limit:
            low = middle
        else:
            high = middle - 1
    return text[:low] + marker, True


__all__ = [
    "AssembledContext",
    "ContextOverflow",
    "assemble_context",
    "truncate_message",
]
