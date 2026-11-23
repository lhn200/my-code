"""Deterministic digests that protect long job descriptions and resumes.

The original text always stays in state. Only when the original would exceed
the model budget do callers send the digest instead, so responsibilities,
hard requirements, keywords, experience, skills and quantified results survive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

JD_DIGEST_LIMIT = 800
RESUME_DIGEST_LIMIT = 1500
_HEAD_RATIO = 0.7

_SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")
_ASCII_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#./_-]{1,}")
_METRIC = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|万|亿|倍|人|个|次|年|月|天|小时)")

_JD_RESPONSIBILITY_HINTS = ("负责", "职责", "工作内容", "日常工作", "参与", "主导")
_JD_REQUIREMENT_HINTS = (
    "任职",
    "要求",
    "资格",
    "必须",
    "至少",
    "熟悉",
    "掌握",
    "精通",
    "本科",
    "硕士",
    "博士",
    "年以上",
    "优先",
)
_RESUME_SKILL_HINTS = ("技能", "技术栈", "熟练掌握", "精通", "熟悉")
_RESUME_EXPERIENCE_HINTS = ("工作经历", "工作经验", "实习经历", "实习经验", "在职")
_RESUME_EDUCATION_HINTS = ("教育", "学历", "毕业", "本科", "硕士", "博士")

_PROFILE_GROUPS: tuple[tuple[str, str], ...] = (
    ("responsibilities", "职责"),
    ("must_have", "硬性要求"),
    ("nice_to_have", "加分项"),
    ("keywords", "关键词"),
)


class DigestError(ValueError):
    """Raised when a required text is empty; callers must not send blank input."""


@dataclass(frozen=True)
class Digest:
    """A bounded representation of a long, protected input.

    ``meta`` intentionally carries no body text so it is safe to persist in
    ``context_budget_meta`` and logs.
    """

    kind: str
    text: str
    original_chars: int
    limit: int
    fallback: bool = False
    truncated: bool = False
    omitted_chars: int = 0

    @property
    def digest_chars(self) -> int:
        return len(self.text)

    def meta(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "limit": self.limit,
            "original_chars": self.original_chars,
            "digest_chars": self.digest_chars,
            "fallback": self.fallback,
            "truncated": self.truncated,
            "omitted_chars": self.omitted_chars,
        }


def build_jd_digest(
    job_text: Any,
    *,
    profile: Mapping[str, Any] | None = None,
    limit: int = JD_DIGEST_LIMIT,
) -> Digest:
    """Return a JD digest of at most ``limit`` characters.

    Existing structured fields (job profile) win over text extraction because
    they are already parsed and deterministic. If neither source yields
    structured content, fall back to head/tail truncation and flag it.
    """
    text = _normalize(job_text)
    if not text:
        raise DigestError("job description is empty")
    if len(text) <= limit:
        return Digest("jd", text, len(text), limit)

    groups = _profile_groups(profile) or _jd_groups(text)
    rendered, dropped = _fit_groups(groups, limit)
    if rendered:
        return Digest(
            "jd",
            rendered,
            len(text),
            limit,
            truncated=True,
            omitted_chars=max(0, len(text) - len(rendered)),
        )

    degraded, omitted = _truncate(text, limit)
    return Digest(
        "jd",
        degraded,
        len(text),
        limit,
        fallback=True,
        truncated=True,
        omitted_chars=omitted,
    )


def build_resume_digest(
    resume_text: Any,
    *,
    limit: int = RESUME_DIGEST_LIMIT,
) -> Digest:
    """Return a resume digest of at most ``limit`` characters.

    Keeps skill lists, work/project experience and quantified results. Falls
    back to head/tail truncation only when nothing structured can be derived.
    """
    text = _normalize(resume_text)
    if not text:
        raise DigestError("resume text is empty")
    if len(text) <= limit:
        return Digest("resume", text, len(text), limit)

    rendered, _dropped = _fit_groups(_resume_groups(text), limit)
    if rendered:
        return Digest(
            "resume",
            rendered,
            len(text),
            limit,
            truncated=True,
            omitted_chars=max(0, len(text) - len(rendered)),
        )

    degraded, omitted = _truncate(text, limit)
    return Digest(
        "resume",
        degraded,
        len(text),
        limit,
        fallback=True,
        truncated=True,
        omitted_chars=omitted,
    )


def digest_meta(*digests: Digest | None) -> dict[str, Any]:
    """Build a body-free summary for ``context_budget_meta``."""
    entries = {item.kind: item.meta() for item in digests if item is not None}
    return {
        "digests": entries,
        "digest_fallback": any(item.fallback for item in digests if item is not None),
    }


def _normalize(text: Any) -> str:
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]


def _profile_groups(profile: Mapping[str, Any] | None) -> list[tuple[str, list[str]]]:
    if not isinstance(profile, Mapping):
        return []
    groups: list[tuple[str, list[str]]] = []
    for key, label in _PROFILE_GROUPS:
        values = profile.get(key)
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, (list, tuple)):
            continue
        items = [str(value).strip() for value in values if str(value).strip()]
        if items:
            groups.append((label, items))
    return groups


def _jd_groups(text: str) -> list[tuple[str, list[str]]]:
    responsibilities: list[str] = []
    requirements: list[str] = []
    seen: set[str] = set()
    for sentence in _sentences(text):
        if sentence in seen:
            continue
        seen.add(sentence)
        if any(hint in sentence for hint in _JD_REQUIREMENT_HINTS):
            requirements.append(sentence)
        elif any(hint in sentence for hint in _JD_RESPONSIBILITY_HINTS):
            responsibilities.append(sentence)

    keywords: list[str] = []
    lowered: set[str] = set()
    for token in _ASCII_TOKEN.findall(text):
        key = token.lower()
        if key in lowered:
            continue
        lowered.add(key)
        keywords.append(token)
        if len(keywords) >= 15:
            break

    groups: list[tuple[str, list[str]]] = []
    if responsibilities:
        groups.append(("职责", responsibilities))
    if requirements:
        groups.append(("硬性要求", requirements))
    if keywords:
        groups.append(("关键词", ["、".join(keywords)]))
    return groups


def _resume_groups(text: str) -> list[tuple[str, list[str]]]:
    buckets: dict[str, list[str]] = {
        "技能": [],
        "工作经历": [],
        "项目经历": [],
        "量化成果": [],
        "教育": [],
        "其他经历": [],
    }
    seen: set[str] = set()
    for sentence in _sentences(text):
        if sentence in seen:
            continue
        seen.add(sentence)
        if any(hint in sentence for hint in _RESUME_SKILL_HINTS):
            label = "技能"
        elif any(hint in sentence for hint in _RESUME_EXPERIENCE_HINTS):
            label = "工作经历"
        elif "项目" in sentence:
            label = "项目经历"
        elif any(hint in sentence for hint in _RESUME_EDUCATION_HINTS):
            label = "教育"
        elif _METRIC.search(sentence):
            label = "量化成果"
        else:
            label = "其他经历"
        buckets[label].append(sentence)
    groups = [(label, items) for label, items in buckets.items() if items]
    if [label for label, _items in groups] == ["其他经历"]:
        return []
    return groups


def _fit_groups(
    groups: Sequence[tuple[str, list[str]]], limit: int
) -> tuple[str, bool]:
    """Render labeled groups while giving every non-empty group a share.

    A plain head-to-tail trim would let the first group eat the whole budget and
    silently drop hard requirements. Shares are proportional to each group's
    natural size, so every category stays represented.
    """
    if not groups:
        return "", False

    full = _render_groups(groups)
    if len(full) <= limit:
        return full, False

    sizes = [len(_render_groups([group])) for group in groups]
    total = sum(sizes) or 1
    floor = max(24, limit // (len(groups) * 4))
    remaining = max(0, limit - floor * len(groups))
    trimmed: list[tuple[str, list[str]]] = []
    for (label, items), size in zip(groups, sizes):
        share = floor + remaining * size // total
        available = max(1, share - len(f"【{label}】"))
        kept: list[str] = []
        used = 0
        for item in items:
            cost = len(item) + (1 if kept else 0)
            if used + cost <= available:
                kept.append(item)
                used += cost
                continue
            spare = available - used - (1 if kept else 0)
            if spare > 20:
                clipped, _omitted = _truncate(item, spare)
                kept.append(clipped)
            break
        if kept:
            trimmed.append((label, kept))

    rendered = _render_groups(trimmed)
    if len(rendered) <= limit:
        return rendered, True
    degraded, _omitted = _truncate(rendered, limit)
    return degraded, True


def _render_groups(groups: Sequence[tuple[str, list[str]]]) -> str:
    return "\n".join(f"【{label}】" + "；".join(items) for label, items in groups)


def _truncate(text: str, limit: int) -> tuple[str, int]:
    """Keep the head 70% and tail 30%, marker included inside ``limit``."""
    if limit <= 0:
        return "", len(text)
    if len(text) <= limit:
        return text, 0
    keep = max(2, limit - 20)
    marker = ""
    for _ in range(5):
        marker = f"\n...[已截断 {len(text) - keep} 字]..."
        candidate = max(2, limit - len(marker))
        if candidate == keep:
            break
        keep = candidate
    head = max(1, int(keep * _HEAD_RATIO))
    tail = max(0, keep - head)
    omitted = len(text) - head - tail
    result = text[:head] + marker + (text[-tail:] if tail else "")
    return result[:limit], omitted


__all__ = [
    "Digest",
    "DigestError",
    "JD_DIGEST_LIMIT",
    "RESUME_DIGEST_LIMIT",
    "build_jd_digest",
    "build_resume_digest",
    "digest_meta",
]
