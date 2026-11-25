"""Authentication building blocks: passwords, tokens, rate limiting."""

from __future__ import annotations

from .dependencies import client_ip, get_current_user
from .jwt import TokenError, create_access_token, decode_token
from .password import dummy_verify, hash_password, verify_password
from .rate_limit import LoginRateLimiter, RateLimitExceeded

__all__ = [
    "LoginRateLimiter",
    "RateLimitExceeded",
    "TokenError",
    "client_ip",
    "create_access_token",
    "decode_token",
    "dummy_verify",
    "get_current_user",
    "hash_password",
    "verify_password",
]
