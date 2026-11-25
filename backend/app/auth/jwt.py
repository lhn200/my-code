"""JWT access token creation and validation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt as pyjwt

ALGORITHM = "HS256"


class TokenError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def create_access_token(
    user_id: str,
    *,
    secret: str,
    expires_minutes: int,
    now: datetime | None = None,
) -> str:
    issued_at = now or datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=expires_minutes),
    }
    return pyjwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(token: str, *, secret: str) -> str:
    try:
        payload = pyjwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except pyjwt.ExpiredSignatureError as exc:
        raise TokenError("token_expired") from exc
    except pyjwt.InvalidTokenError as exc:
        raise TokenError("token_invalid") from exc
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise TokenError("token_invalid")
    return subject


__all__ = ["ALGORITHM", "TokenError", "create_access_token", "decode_token"]
