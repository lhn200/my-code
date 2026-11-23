"""Token counting with a deterministic fallback when tiktoken is unavailable."""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

_CJK_MIN = 0x2E80
_CJK_MAX = 0x9FFF
_SAFETY_FACTOR = 1.15

_encoding = None
_encoding_resolved = False


def _resolve_encoding():
    global _encoding, _encoding_resolved
    if _encoding_resolved:
        return _encoding
    _encoding_resolved = True
    try:
        import tiktoken

        _encoding = tiktoken.get_encoding("cl100k_base")
    except Exception as exc:  # pragma: no cover - depends on optional dependency
        logger.warning("tiktoken unavailable, fallback estimation in use: %s", exc)
        _encoding = None
    return _encoding


def _estimate(text: str) -> int:
    if not text:
        return 0
    cjk = sum(1 for char in text if _CJK_MIN <= ord(char) <= _CJK_MAX)
    other = len(text) - cjk
    return math.ceil(cjk + other / 3.5 + 4)


def count_tokens(text: str) -> int:
    """Return an estimated token count, applying a 1.15 safety margin."""
    if not text:
        return 0
    encoding = _resolve_encoding()
    if encoding is None:
        return math.ceil(_estimate(text) * _SAFETY_FACTOR)
    try:
        return math.ceil(len(encoding.encode(text)) * _SAFETY_FACTOR)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("token encoding failed, fallback to character estimate: %s", exc)
        return len(text)
