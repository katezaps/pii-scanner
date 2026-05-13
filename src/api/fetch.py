"""GET /fetch — retrieve scan results for the authenticated user."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg import AsyncConnection

from src.core.auth import AuthDep
from src.db.pool import db_dependency
from src.db.queries import sql
from src.models.enums import ScanState
from src.models.fetch import (
    FetchResponse,
    FetchResult,
    FetchSummary,
    ScanListItem,
    ScanListResponse,
)

router = APIRouter(tags=["fetch"])


@router.get(
    "/fetch/scans",
    response_model=ScanListResponse,
    summary="List all unexpired scans for the authenticated user",
)
async def list_scans(
    auth: AuthDep,
    conn: Annotated[AsyncConnection, Depends(db_dependency)],
) -> ScanListResponse:
    """Returns all unexpired scan executions for the user."""
    async with conn.cursor() as cur:
        await cur.execute(sql("fetch_all_executions"), (auth.user_id,))
        rows = await cur.fetchall()

    return ScanListResponse(
        scans=[
            ScanListItem(
                execution_id=row["id"],
                name=row["name"],
                state=ScanState(row["state"]),
                expires_at=row["expires_at"],
                broker_count=row["broker_count"],
                found_count=row["found_count"],
                incomplete_count=row["incomplete_count"],
            )
            for row in rows
        ],
    )


@router.get(
    "/fetch",
    response_model=FetchResponse,
    summary="Retrieve scan results for the authenticated user",
)
async def fetch_scan(
    auth: AuthDep,
    conn: Annotated[AsyncConnection, Depends(db_dependency)],
    execution_id: Annotated[UUID | None, Query()] = None,
) -> FetchResponse:
    """Returns scan results. If execution_id is provided, returns that
    specific scan. Otherwise returns the most recent unexpired scan.

    Returns 404 if no matching scan exists.
    """
    if execution_id:
        async with conn.cursor() as cur:
            await cur.execute(
                sql("fetch_execution_by_id"),
                (execution_id, auth.user_id),
            )
            execution = await cur.fetchone()
    else:
        async with conn.cursor() as cur:
            await cur.execute(sql("fetch_latest_execution"), (auth.user_id,))
            execution = await cur.fetchone()

    if execution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No recent scan found",
        )

    async with conn.cursor() as cur:
        await cur.execute(sql("fetch_execution_results"), (execution["id"],))
        rows = await cur.fetchall()

    results = [
        FetchResult(
            broker_id=row["broker_id"],
            broker_key=row["broker_key"],
            broker_name=row["broker_name"],
            search_url=row["search_url"],
            field_type=row["field_type"],
            state=ScanState(row["state"]),
            found=row["found"],
            message=row["message"],
            opt_out_url=row["opt_out_url"],
        )
        for row in rows
    ]

    found_count = sum(1 for r in results if r.found and r.field_type != "_status")
    distinct_brokers = len({r.broker_id for r in results})

    return FetchResponse(
        execution_id=execution["id"],
        name=execution["name"],
        broker_version=execution["version"],
        expires_at=execution["expires_at"],
        results=results,
        summary=FetchSummary(
            total_brokers_scanned=distinct_brokers,
            total_results=len(results),
            found_count=found_count,
        ),
    )
