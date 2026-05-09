"""Broker resolution and concurrent agent orchestration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from src.core.config import AppSettings
from src.db.pool import acquire
from src.db.queries import sql
from src.models.scan import AuditAgentResult
from src.services.audit.agent import audit_broker

logger = logging.getLogger(__name__)


async def resolve_brokers(broker_keys: list[str] | None = None) -> list[dict]:
    """Resolve brokers from the database, optionally filtered by keys."""
    async with acquire() as conn:
        async with conn.cursor() as cur:
            if broker_keys is not None:
                await cur.execute(sql("brokers_resolve_by_keys"), (broker_keys,))
            else:
                await cur.execute(sql("brokers_resolve_all"))
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def stream_audit_agents(
    broker_keys: list[str] | None = None,
    identity: dict[str, str] | None = None,
    brokers: list[dict] | None = None,
    *,
    settings: AppSettings | None = None,
) -> AsyncIterator[AuditAgentResult]:
    """Spawn one agent per broker, yield results as each completes.

    The total scan timeout is ``len(brokers) * agent_timeout_seconds``.
    Brokers that haven't finished when the deadline hits are cancelled
    and reported as timed out.

    Pass ``brokers`` directly to skip the DB lookup (used by the CLI).
    Pass ``settings`` to use a specific settings instance (e.g. CLISettings).
    Falls back to WebSettings via get_settings() if not provided.
    """
    if settings is None:
        from src.core.config import get_settings

        settings = get_settings()
    if brokers is None:
        brokers = await resolve_brokers(broker_keys)

    if not brokers:
        logger.warning("No brokers to audit")
        return

    scan_timeout = len(brokers) * settings.agent_timeout_seconds

    logger.info("Starting audit agents for %d brokers (timeout=%ds)", len(brokers), scan_timeout)

    broker_by_task: dict[asyncio.Task, dict] = {}
    for broker in brokers:
        task = asyncio.create_task(
            audit_broker(broker["name"], broker["search_url"], identity, settings=settings),
            name=f"audit-{broker['name']}",
        )
        broker_by_task[task] = broker

    pending = set(broker_by_task.keys())
    deadline = asyncio.get_event_loop().time() + scan_timeout

    while pending:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break

        done, pending = await asyncio.wait(
            pending,
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in done:
            yield task.result()

    # Cancel and await any brokers still running after the deadline.
    # Awaiting cancelled tasks ensures Playwright browser contexts are cleaned up.
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    for task in pending:
        broker = broker_by_task[task]
        # audit_broker catches CancelledError and returns a result with
        # partial matches. Use that if available; otherwise emit a cancellation.
        try:
            result = task.result()
            yield result
        except (asyncio.CancelledError, Exception):
            logger.warning(
                "Scan timeout: broker=%s exceeded %ds total scan limit",
                broker["name"],
                scan_timeout,
            )
            yield AuditAgentResult(
                name=broker["name"],
                search_url=broker["search_url"],
                status_code=None,
                content_length=None,
                message="Cancelled.",
            )

    logger.info("All %d audit agents completed", len(brokers))
