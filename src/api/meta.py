"""Meta endpoints: /me, /me/tokens, /login, /signup, /health."""

from __future__ import annotations

import secrets
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from psycopg import AsyncConnection

from src.core.auth import AuthDep, clear_auth_cookie, set_auth_cookie
from src.core.config import get_settings
from src.core.crypto import hash_password, hash_token, verify_password
from src.db.pool import db_dependency
from src.db.queries import sql
from src.models.meta import (
    HealthResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
    SignupRequest,
    SignupResponse,
)

router = APIRouter(tags=["meta"])


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Validate the bearer token and return user info",
)
async def me(auth: AuthDep) -> MeResponse:
    return MeResponse(
        user_id=auth.user_id,
        name=auth.user_name,
        token_id=auth.token_id,
        token_name=auth.token_name,
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Verify username and password",
)
async def login(
    body: LoginRequest,
    response: Response,
    conn: Annotated[AsyncConnection, Depends(db_dependency)],
) -> LoginResponse:
    """Authenticate by name + password. Sets an httponly auth cookie and
    returns user info on success."""
    async with conn.cursor() as cur:
        await cur.execute(sql("meta_get_user_by_name"), (body.name,))
        row = await cur.fetchone()

    if row is None or row["password_hash"] is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not verify_password(body.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Generate token and set as httponly cookie
    async with conn.cursor() as cur:
        await cur.execute(sql("meta_revoke_user_tokens"), (row["id"],))
        token_id = uuid4()
        plaintext = secrets.token_urlsafe(32)
        hashed = hash_token(plaintext)
        await cur.execute(
            sql("meta_insert_token"),
            (token_id, row["id"], hashed, "session"),
        )
        await conn.commit()

    set_auth_cookie(response, plaintext)
    return LoginResponse(user_id=row["id"], name=row["name"])


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=201,
    summary="Create a new user account with password and auto-generated token",
)
async def signup(
    body: SignupRequest,
    response: Response,
    conn: Annotated[AsyncConnection, Depends(db_dependency)],
) -> SignupResponse:
    # Check if name already taken
    async with conn.cursor() as cur:
        await cur.execute(sql("meta_check_name_taken"), (body.name,))
        if await cur.fetchone():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already taken",
            )

    user_id = uuid4()
    token_id = uuid4()
    plaintext = secrets.token_urlsafe(32)
    hashed_token = hash_token(plaintext)
    hashed_password = hash_password(body.password)

    async with conn.cursor() as cur:
        await cur.execute(sql("meta_insert_user"), (user_id, body.name, hashed_password))
        await cur.execute(
            sql("meta_insert_token"),
            (token_id, user_id, hashed_token, "default"),
        )
        await conn.commit()

    set_auth_cookie(response, plaintext)
    return SignupResponse(user_id=user_id, name=body.name)


@router.post(
    "/logout",
    status_code=204,
    summary="Clear auth cookie",
)
async def logout(response: Response) -> None:
    """Clear the httponly auth cookie."""
    clear_auth_cookie(response)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness check (no auth required)",
)
async def health(
    conn: Annotated[AsyncConnection, Depends(db_dependency)],
) -> HealthResponse:
    """Liveness check. Returns the current broker version so the React UI
    can detect a broker update and refresh its cached broker list."""
    async with conn.cursor() as cur:
        await cur.execute(sql("health_broker_version"))
        row = await cur.fetchone()
    assert row is not None
    settings = get_settings()
    return HealthResponse(
        status="ok",
        broker_version=int(row["v"]),
        agent_timeout_seconds=settings.agent_timeout_seconds,
    )
