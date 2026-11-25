from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth.jwt import create_access_token
from app.config import Settings
from app.main import create_app

from tests.auth_utils import DEFAULT_EMAIL, DEFAULT_PASSWORD, login, register


def test_register_creates_account_without_exposing_password(anon_client) -> None:
    response = register(anon_client, "New.User@Example.com ")
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new.user@example.com"
    assert set(body) == {"id", "email", "created_at"}
    assert "password" not in response.text


def test_duplicate_email_is_rejected_case_insensitively(anon_client) -> None:
    assert register(anon_client, "dup@example.com").status_code == 201
    response = register(anon_client, "DUP@example.com")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


def test_invalid_email_and_short_password_are_422(anon_client) -> None:
    bad_email = register(anon_client, "not-an-email")
    assert bad_email.status_code == 422
    fields = {(item["field"], item["type"]) for item in bad_email.json()["error"]["fields"]}
    assert ("email", "invalid_email") in fields

    short = register(anon_client, "short@example.com", "short")
    assert short.status_code == 422
    fields = {(item["field"], item["type"]) for item in short.json()["error"]["fields"]}
    assert ("password", "password_too_short") in fields


def test_login_and_me_round_trip(anon_client) -> None:
    register(anon_client)
    token = login(anon_client)
    response = anon_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == DEFAULT_EMAIL
    assert response.json()["id"]


def test_wrong_password_and_unknown_email_share_error(anon_client) -> None:
    register(anon_client)
    wrong = anon_client.post(
        "/api/auth/login",
        json={"email": DEFAULT_EMAIL, "password": "wrong-password"},
    )
    unknown = anon_client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": DEFAULT_PASSWORD},
    )
    assert wrong.status_code == 401
    assert unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "invalid_credentials"


def test_missing_and_malformed_tokens_are_401(anon_client) -> None:
    missing = anon_client.get("/api/auth/me")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "not_authenticated"
    assert missing.headers["WWW-Authenticate"] == "Bearer"

    malformed = anon_client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not-a-token"}
    )
    assert malformed.status_code == 401
    assert malformed.json()["error"]["code"] == "token_invalid"


def test_expired_token_reports_token_expired(anon_client, settings) -> None:
    me = anon_client.get(
        "/api/auth/me",
        headers={
            "Authorization": "Bearer "
            + create_access_token(
                "some-user",
                secret=settings.jwt_secret,
                expires_minutes=1,
                now=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        },
    )
    assert me.status_code == 401
    assert me.json()["error"]["code"] == "token_expired"


def test_token_signed_with_another_secret_is_invalid(anon_client) -> None:
    token = create_access_token(
        "user-1", secret="a-different-secret", expires_minutes=30
    )
    response = anon_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_invalid"


def test_run_requires_login_and_creates_no_record(anon_client, settings) -> None:
    response = anon_client.post(
        "/api/runs",
        json={
            "goal": "后端",
            "resume_text": "Python",
            "jobs": [{"job_id": "job-1", "title": "Backend", "original_position_text": "Python"}],
        },
    )
    assert response.status_code == 401
    with sqlite3.connect(settings.checkpoint_db_path) as connection:
        rows = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert rows == 0


def test_password_hash_round_trip() -> None:
    from app.auth.password import hash_password, verify_password

    first = hash_password("password123")
    second = hash_password("password123")
    assert first != second
    assert verify_password(first, "password123")
    assert verify_password(second, "password123")
    assert not verify_password(first, "wrong-password")


def test_alg_none_token_is_rejected(anon_client) -> None:
    import jwt as pyjwt

    unsigned = pyjwt.encode(
        {"sub": "user-1", "exp": 9999999999}, key=None, algorithm="none"
    )
    response = anon_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {unsigned}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_invalid"


def test_login_and_register_do_not_log_or_echo_secrets(anon_client, caplog) -> None:
    caplog.set_level("DEBUG")
    register(anon_client)
    login(anon_client)
    failed = anon_client.post(
        "/api/auth/login",
        json={"email": DEFAULT_EMAIL, "password": "wrong-password"},
    )
    assert failed.status_code == 401
    assert "wrong-password" not in failed.text
    assert "password_hash" not in failed.text
    assert "wrong-password" not in caplog.text
    assert DEFAULT_PASSWORD not in caplog.text
    assert "Bearer " not in caplog.text


def test_logout_returns_204(client) -> None:
    assert client.post("/api/auth/logout").status_code == 204


def test_login_rate_limit_blocks_after_limit(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        checkpoint_db_path=tmp_path / "auth.sqlite3",
        upload_dir=tmp_path / "uploads",
        jwt_secret="test-secret",
        login_rate_limit_per_minute=2,
    )
    with TestClient(create_app(settings)) as client:
        register(client)
        first = client.post(
            "/api/auth/login",
            json={"email": DEFAULT_EMAIL, "password": "wrong-password"},
        )
        second = client.post(
            "/api/auth/login",
            json={"email": DEFAULT_EMAIL, "password": "wrong-password"},
        )
        third = client.post(
            "/api/auth/login",
            json={"email": DEFAULT_EMAIL, "password": "wrong-password"},
        )
    assert first.status_code == 401
    assert second.status_code == 401
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "rate_limited"
    assert int(third.headers["Retry-After"]) >= 1


def test_startup_fails_without_jwt_secret(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        checkpoint_db_path=tmp_path / "missing-secret.sqlite3",
        upload_dir=tmp_path / "uploads",
        jwt_secret="",
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        with TestClient(create_app(settings)):
            pass


def test_non_positive_expiry_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(Exception):
        Settings(
            _env_file=None,
            checkpoint_db_path=tmp_path / "bad.sqlite3",
            upload_dir=tmp_path / "uploads",
            jwt_secret="test-secret",
            jwt_expires_minutes=0,
        )


def test_password_is_stored_as_argon2_hash(anon_client, settings) -> None:
    register(anon_client)
    with sqlite3.connect(settings.checkpoint_db_path) as connection:
        row = connection.execute("SELECT password_hash FROM users").fetchone()
    assert row is not None
    assert row[0].startswith("$argon2")
    assert DEFAULT_PASSWORD not in row[0]
