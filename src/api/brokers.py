"""GET /brokers — current active brokers."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import AsyncConnection

from src.core.auth import AuthDep
from src.db.pool import db_dependency
from src.db.queries import sql
from src.models.brokers import BrokerOut, BrokersResponse

router = APIRouter(tags=["brokers"])


@router.get(
    "/brokers",
    response_model=BrokersResponse,
    summary="Return all active brokers (highest broker version)",
)
async def get_brokers(
    auth: AuthDep,
    conn: Annotated[AsyncConnection, Depends(db_dependency)],
) -> BrokersResponse:
    """Returns brokers belonging to the highest broker version,
    sorted by name for consistent UI ordering."""
    async with conn.cursor() as cur:
        await cur.execute(sql("brokers_max_version"))
        row = await cur.fetchone()

    if row is None or row["v"] is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No brokers available",
        )

    current = int(row["v"])

    async with conn.cursor() as cur:
        await cur.execute(sql("brokers_by_version"), (current,))
        rows = await cur.fetchall()

    return BrokersResponse(
        version=current,
        brokers=[
            BrokerOut(
                version=current,
                key=r["key"],
                name=r["name"],
                search_url=r["search_url"],
                created_at=r["created_at"],
            )
            for r in rows
        ],
    )
