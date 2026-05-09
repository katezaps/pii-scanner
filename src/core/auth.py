"""Cookie-based authentication via FastAPI dependencies.

The standard pattern: extract token from httponly cookie, look up its
hash in api_tokens, verify, attach the resolved AuthContext to the request.

Token verification uses Argon2 which is intentionally slow. To avoid hashing
on every request, we cache valid (token -> AuthContext) mappings in memory
for a short TTL. Cache is in-process only; no external store.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response, status
from psycopg import AsyncConnection

from src.core.crypto import verify_token
from src.db.pool import db_dependency
from src.db.queries import sql

COOKIE_NAME = "pii_scanner_token"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Resolved authentication for the current request."""

    user_id: UUID
    user_name: str | None
    token_id: UUID
    token_name: str | None


# In-memory cache: token_plaintext -> (AuthContext, expires_at)
# Keyed on plaintext only because we never persist this; flushed on restart.
_TOKEN_CACHE_TTL_SECONDS = 60
_token_cache: dict[str, tuple[AuthContext, float]] = {}


def _cache_get(token: str) -> AuthContext | None:
    entry = _token_cache.get(token)
    if entry is None:
        return None
    ctx, expires_at = entry
    if expires_at < time.monotonic():
        _token_cache.pop(token, None)
        return None
    return ctx


def _cache_put(token: str, ctx: AuthContext) -> None:
    _token_cache[token] = (ctx, time.monotonic() + _TOKEN_CACHE_TTL_SECONDS)


def set_auth_cookie(response: Response, token: str) -> None:
    """Set the httponly auth cookie on a response."""
    from src.core.config import get_settings

    settings = get_settings()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        max_age=COOKIE_MAX_AGE,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Clear the auth cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")


async def require_auth(
    request: Request,
    conn: Annotated[AsyncConnection, Depends(db_dependency)],
) -> AuthContext:
    """Validate token from httponly cookie and return AuthContext, or raise 401."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing auth cookie",
        )

    cached = _cache_get(token)
    if cached is not None:
        return cached

    # Argon2 verify is expensive. To avoid an O(N) scan over all tokens, we
    # store a SHA256 prefix as a lookup index in v1+. For v0, with a tiny
    # number of active tokens, we accept the linear scan.
    async with conn.cursor() as cur:
        await cur.execute(sql("auth_get_active_tokens"))
        rows = await cur.fetchall()

    for row in rows:
        if verify_token(token, row["token_hash"]):
            ctx = AuthContext(
                user_id=row["user_id"],
                user_name=row["user_name"],
                token_id=row["id"],
                token_name=row["name"],
            )
            _cache_put(token, ctx)

            # Best-effort last_used_at update — fire-and-forget within the
            # request connection. Failures don't block auth.
            try:
                async with conn.cursor() as cur:
                    await cur.execute(sql("auth_update_last_used"), (row["id"],))
                    await conn.commit()
            except Exception:
                await conn.rollback()

            return ctx

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid auth cookie",
    )


AuthDep = Annotated[AuthContext, Depends(require_auth)]
