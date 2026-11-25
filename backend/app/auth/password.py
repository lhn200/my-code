"""Password hashing with argon2id."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# Pre-computed hash used to keep the "unknown email" login path close in timing.
_DUMMY_PASSWORD = "dummy-password-for-timing"
DUMMY_HASH = _hasher.hash(_DUMMY_PASSWORD)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHash):
        return False


def dummy_verify() -> None:
    """Perform a hash verification so missing accounts cost about the same."""
    verify_password(DUMMY_HASH, _DUMMY_PASSWORD)


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHash:
        return True


__all__ = [
    "DUMMY_HASH",
    "dummy_verify",
    "hash_password",
    "password_needs_rehash",
    "verify_password",
]
