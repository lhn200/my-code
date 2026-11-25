"""Long-term memory content rules: normalization, hashing, sensitivity and TTL."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any

KINDS: tuple[str, ...] = ("preference", "goal", "fact", "constraint")
STATUSES: tuple[str, ...] = ("active", "pending_confirmation", "archived")


class MemoryContentError(ValueError):
    """Content violates the memory content contract."""


class SensitiveContentError(MemoryContentError):
    """Content contains a category that must never be stored."""


def normalize_content(text: Any, limit: int, *, strict: bool = False) -> str:
    """Collapse whitespace and enforce the length limit."""
    if not isinstance(text, str):
        raise MemoryContentError("content must be a string")
    collapsed = " ".join(text.split())
    if not collapsed:
        raise MemoryContentError("content must not be blank")
    if len(collapsed) > limit:
        if strict:
            raise MemoryContentError(f"content must be at most {limit} characters")
        collapsed = collapsed[:limit].rstrip()
    return collapsed


def content_hash(user_id: str, kind: str, content: str) -> str:
    raw = f"{user_id}{kind}{content}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def status_for_confidence(confidence: float, settings: Any) -> str | None:
    if confidence >= settings.memory_min_confidence:
        return "active"
    if confidence >= settings.memory_pending_confidence:
        return "pending_confirmation"
    return None


def expires_at_for(kind: str, updated_at: datetime, settings: Any) -> str | None:
    """Return the ISO expiry derived from the per-kind TTL; None means never."""
    days = settings.ttl_days_for(kind)
    if days <= 0:
        return None
    moment = updated_at
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment + timedelta(days=days)).astimezone(timezone.utc).isoformat()


_SENSITIVE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)|(?<!\d)\d{15}(?!\d)")),
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("bank_card", re.compile(r"(?<!\d)\d{16,19}(?!\d)")),
    ("credential", re.compile(r"密码|口令|验证码|api[_ -]?key|secret|token", re.IGNORECASE)),
    ("address", re.compile(r"(住址|家庭地址|详细地址|现居|家住|居住在)")),
    ("health", re.compile(r"病史|疾病|医疗|体检|残疾|抑郁|高血压|糖尿病|怀孕|孕期|备孕|手术")),
    ("marital", re.compile(r"已婚|未婚|离异|丧偶|生育|子女|孩子")),
    ("ethnicity", re.compile(r"民族|汉族|回族|壮族|维吾尔族|蒙古族|藏族")),
    ("religion", re.compile(r"宗教|信仰|佛教|基督教|伊斯兰教|天主教|道教")),
    ("political", re.compile(r"政治面貌|党员|共青团员|民主党派")),
)


def detect_sensitive(text: str) -> str | None:
    """Return the matched sensitive category, or None when the text is safe."""
    if not text:
        return None
    for category, pattern in _SENSITIVE_RULES:
        if pattern.search(text):
            return category
    return None


__all__ = [
    "KINDS",
    "STATUSES",
    "MemoryContentError",
    "SensitiveContentError",
    "content_hash",
    "detect_sensitive",
    "expires_at_for",
    "normalize_content",
    "status_for_confidence",
]
