"""Broker endpoints — listing, opt-out discovery, opt-out persistence."""

from __future__ import annotations

import json
import logging
from typing import Annotated

from agents import Agent, Runner
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from psycopg import AsyncConnection

from src.core.auth import AuthDep
from src.core.config import WebSettings, get_settings
from src.db.pool import acquire, db_dependency
from src.db.queries import sql
from src.models.brokers import BrokerOut, BrokersResponse
from src.services.browser import browser_context
from src.services.tools import make_find_opt_out_tool

logger = logging.getLogger(__name__)

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
                opt_out_url=r["opt_out_url"],
                opt_out_url_source=r["opt_out_url_source"],
            )
            for r in rows
        ],
    )


# ---------------------------------------------------------------------------
# Opt-out URL discovery + persistence
# ---------------------------------------------------------------------------


async def _resolve_broker_search_url(broker_key: str) -> str:
    """Look up the search_url for a broker key. Raises 404 if not found."""
    async with acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql("brokers_resolve_by_keys"), ([broker_key],))
            row = await cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Broker '{broker_key}' not found",
        )
    return row["search_url"]


@router.post(
    "/brokers/{broker_key}/discover-opt-out",
    summary="Run an agent to discover the opt-out URL for a broker",
)
async def discover_opt_out(
    broker_key: str,
    auth: AuthDep,
    settings: Annotated[WebSettings, Depends(get_settings)],
):
    """Spin up a single-tool agent to crawl the broker site for opt-out pages."""
    search_url = await _resolve_broker_search_url(broker_key)
    timeout_ms = settings.page_timeout_seconds * 1000

    try:
        async with browser_context() as ctx:
            agent = Agent(
                name=f"opt-out-discovery-{broker_key}",
                model=settings.openai_model,
                instructions=(
                    "You are discovering the data opt-out or removal page for a data broker. "
                    "Call find_opt_out on the URL provided and report the results as JSON."
                ),
                tools=[make_find_opt_out_tool(ctx, timeout_ms=timeout_ms * 2)],
            )
            result = await Runner.run(
                agent,
                input=f"Find the opt-out page for {search_url}",
            )
    except Exception as e:
        logger.exception("Opt-out discovery failed for %s", broker_key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Discovery failed: {e}",
        )

    # Extract opt-out URL from tool outputs
    opt_out_url = None
    opt_out_pages: list = []
    for item in result.new_items:
        if hasattr(item, "output") and isinstance(item.output, str):
            try:
                tool_out = json.loads(item.output)
                if "opt_out_pages" in tool_out:
                    opt_out_pages = tool_out["opt_out_pages"]
                    if opt_out_pages and isinstance(opt_out_pages[0], dict):
                        opt_out_url = opt_out_pages[0].get("url")
                    break
            except (json.JSONDecodeError, TypeError):
                pass

    return {
        "broker_key": broker_key,
        "search_url": search_url,
        "opt_out_url": opt_out_url,
        "opt_out_pages": opt_out_pages,
        "found": opt_out_url is not None,
    }


class ConfirmOptOutUrl(BaseModel):
    opt_out_url: str


@router.put(
    "/brokers/{broker_key}/opt-out-url",
    summary="Persist a confirmed opt-out URL for a broker",
)
async def confirm_opt_out_url(
    broker_key: str,
    body: ConfirmOptOutUrl,
    auth: AuthDep,
):
    """Save a user-confirmed opt-out URL to the broker row."""
    async with acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                sql("broker_update_opt_out_url"),
                {"broker_key": broker_key, "opt_out_url": body.opt_out_url},
            )
            if cur.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Broker '{broker_key}' not found",
                )
            await conn.commit()
    return {"broker_key": broker_key, "opt_out_url": body.opt_out_url}
