"""Purge expired scan data.

Deletes expired scan_executions (which cascades to scan_execution_results),
then cleans up orphaned broker_field_scans rows that are no longer linked
to any execution.

Run via: ``python -m src.db.purge`` or schedule with cron.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import psycopg

from src.core.config import get_settings
from src.core.logging import configure_logging
from src.db.queries import sql

logger = logging.getLogger(__name__)


async def purge() -> tuple[int, int]:
    """Delete expired executions and orphaned field scans. Returns (executions, scans) deleted."""
    settings = get_settings()

    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql("purge_expired_executions"))
            executions_deleted = cur.rowcount

            await cur.execute(sql("purge_orphaned_field_scans"))
            scans_deleted = cur.rowcount

        await conn.commit()

    logger.info(
        "Purge complete: executions=%d field_scans=%d",
        executions_deleted,
        scans_deleted,
    )
    return executions_deleted, scans_deleted


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    try:
        executions, scans = asyncio.run(purge())
        print(f"Purged {executions} expired executions, {scans} orphaned field scans")
    except Exception as e:
        logger.exception("Purge failed")
        print(f"Purge failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
