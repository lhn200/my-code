"""Role prompt package."""

from .loader import (
    HUMAN_TEMPLATE_MARKER,
    PromptBundle,
    PromptLoadError,
    ROLES,
    SAFETY_PREFIX,
    build_messages,
    load_prompts,
    wrap_untrusted,
)

__all__ = [
    "HUMAN_TEMPLATE_MARKER",
    "PromptBundle",
    "PromptLoadError",
    "ROLES",
    "SAFETY_PREFIX",
    "build_messages",
    "load_prompts",
    "wrap_untrusted",
]
