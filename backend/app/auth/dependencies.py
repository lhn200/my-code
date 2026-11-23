"""FastAPI authentication dependency."""

from __future__ import annotations

from fastapi import Header, Request

from ..db import User, connect, get_user_by_id
from ..errors import auth_error
from .jwt import TokenError, decode_token


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> User:
    if not authorization:
        raise auth_error("not_authenticated", "authentication required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise auth_error("not_authenticated", "authentication required")

    settings = request.app.state.settings
    try:
        user_id = decode_token(token.strip(), secret=settings.jwt_secret)
    except TokenError as exc:
        if exc.code == "token_expired":
            raise auth_error("token_expired", "token has expired") from None
        raise auth_error("token_invalid", "invalid token") from None

    with connect(settings.checkpoint_db_path) as connection:
        user = get_user_by_id(connection, user_id)
    if user is None:
        raise auth_error("token_invalid", "invalid token")
    return user


def client_ip(request: Request) -> str:
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


__all__ = ["client_ip", "get_current_user"]
