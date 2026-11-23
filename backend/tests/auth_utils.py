"""Helpers for authenticating test clients."""

from __future__ import annotations

DEFAULT_EMAIL = "tester@example.com"
DEFAULT_PASSWORD = "password123"


def register(client, email: str = DEFAULT_EMAIL, password: str = DEFAULT_PASSWORD):
    return client.post(
        "/api/auth/register", json={"email": email, "password": password}
    )


def login(client, email: str = DEFAULT_EMAIL, password: str = DEFAULT_PASSWORD) -> str:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def authenticate(
    client, email: str = DEFAULT_EMAIL, password: str = DEFAULT_PASSWORD
) -> str:
    register(client, email, password)
    token = login(client, email, password)
    client.headers["Authorization"] = f"Bearer {token}"
    return token


__all__ = ["DEFAULT_EMAIL", "DEFAULT_PASSWORD", "authenticate", "login", "register"]
