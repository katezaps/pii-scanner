"""Postgres connection pool managed by the FastAPI lifespan.

We use psycopg3 with its async pool. The pool is created on startup and
closed on shutdown. Request handlers acquire connections via the
``get_db`` dependency which yields a connection from the pool.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from src.core.config import WebSettings

_pool: AsyncConnectionPool | None = None


async def open_pool(settings: WebSettings) -> AsyncConnectionPool:
    """Open the global connection pool. Called from the FastAPI lifespan."""
    global _pool
    if _pool is not None:
        raise RuntimeError("Pool already open")

    _pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=10,
        kwargs={"row_factory": dict_row},
        open=False,
    )
    await _pool.open(wait=True, timeout=10)
    return _pool


async def close_pool() -> None:
    """Close the pool. Called from the FastAPI lifespan."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("Pool is not open")
    return _pool


@asynccontextmanager
async def acquire() -> AsyncGenerator[AsyncConnection, None]:
    """Acquire a connection from the pool."""
    async with get_pool().connection() as conn:
        yield conn


async def db_dependency() -> AsyncGenerator[AsyncConnection, None]:
    """FastAPI dependency yielding a connection per request."""
    async with acquire() as conn:
        yield conn
