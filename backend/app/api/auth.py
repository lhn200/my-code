"""Registration, login, logout and current-user endpoints."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, field_validator
from pydantic_core import PydanticCustomError

from ..auth.dependencies import client_ip, get_current_user
from ..auth.jwt import create_access_token
from ..auth.password import dummy_verify, hash_password, verify_password
from ..auth.rate_limit import RateLimitExceeded
from ..db import EmailTakenError, User, connect, create_user, get_user_by_email
from ..errors import email_taken, invalid_credentials, rate_limited

router = APIRouter(tags=["auth"])

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD_LENGTH = 8


class RegisterRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not _EMAIL_PATTERN.match(email):
            raise PydanticCustomError("invalid_email", "email format is invalid")
        return email

    @field_validator("password")
    @classmethod
    def _long_enough(cls, value: str) -> str:
        if len(value) < _MIN_PASSWORD_LENGTH:
            raise PydanticCustomError(
                "password_too_short",
                f"password must be at least {_MIN_PASSWORD_LENGTH} characters",
            )
        return value


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class UserResponse(BaseModel):
    id: str
    email: str
    created_at: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/auth/register", status_code=201)
def register(payload: RegisterRequest, request: Request) -> UserResponse:
    settings = request.app.state.settings
    with connect(settings.checkpoint_db_path) as connection:
        try:
            user = create_user(
                connection, payload.email, hash_password(payload.password)
            )
        except EmailTakenError:
            raise email_taken() from None
    return _user_response(user)


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request) -> TokenResponse:
    settings = request.app.state.settings
    limiter = request.app.state.login_limiter
    try:
        limiter.check(client_ip(request))
    except RateLimitExceeded as exc:
        raise rate_limited(exc.retry_after) from None

    with connect(settings.checkpoint_db_path) as connection:
        found = get_user_by_email(connection, payload.email)
    if found is None:
        dummy_verify()
        raise invalid_credentials()
    user, password_hash = found
    if not verify_password(password_hash, payload.password):
        raise invalid_credentials()

    token = create_access_token(
        user.id,
        secret=settings.jwt_secret,
        expires_minutes=settings.jwt_expires_minutes,
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expires_minutes * 60,
    )


@router.post("/auth/logout", status_code=204)
def logout(user: User = Depends(get_current_user)) -> Response:
    return Response(status_code=204)


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)) -> UserResponse:
    return _user_response(user)


def _user_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, created_at=user.created_at)


__all__ = ["RegisterRequest", "UserResponse", "router"]
