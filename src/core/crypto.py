"""Argon2id hashing for bearer tokens and passwords.

Token hashes use the high-level password-hash API (with embedded random
salt) because tokens are looked up by hash and verified via ``verify``,
not by deterministic equality. Passwords use the same hasher.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_token_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=32768,  # 32 MiB — tokens verified per request, lighter
    parallelism=2,
    hash_len=32,
)


def hash_token(token: str) -> str:
    """Hash a bearer token using Argon2id with random salt (non-deterministic)."""
    return _token_hasher.hash(token)


def verify_token(token: str, hashed: str) -> bool:
    """Constant-time verify a bearer token against a stored hash."""
    try:
        _token_hasher.verify(hashed, token)
        return True
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def hash_password(password: str) -> str:
    """Hash a user password using Argon2id with random salt."""
    return _token_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a stored Argon2id hash."""
    try:
        _token_hasher.verify(hashed, password)
        return True
    except VerifyMismatchError:
        return False
    except Exception:
        return False
