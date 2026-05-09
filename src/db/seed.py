"""Seed the brokers table from brokers/brokers.json.

For each broker entry in the JSON, ensures a row exists for the file's
declared version. If a row for (version, key) already exists, it is updated
in place (name/search_url corrections). Old versions are never modified.

Run via: ``python -m src.db.seed`` or ``make seed``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from pydantic import BaseModel, Field, ValidationError

from src.core.config import get_settings
from src.core.logging import configure_logging
from src.db.queries import sql

_INSTALLED_PATH = Path(sys.prefix) / "share" / "pii-scanner" / "brokers.json"
_LOCAL_PATH = Path(__file__).resolve().parents[2] / "brokers" / "brokers.json"
BROKERS_PATH = _INSTALLED_PATH if _INSTALLED_PATH.exists() else _LOCAL_PATH

logger = logging.getLogger(__name__)


class _BrokerEntry(BaseModel):
    key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    search_url: str = Field(min_length=1, max_length=2000)


class _BrokerManifest(BaseModel):
    version: int = Field(ge=1)
    brokers: list[_BrokerEntry] = Field(min_length=1)


def _load_brokers() -> _BrokerManifest:
    if not BROKERS_PATH.exists():
        raise FileNotFoundError(f"Brokers file not found: {BROKERS_PATH}")
    raw = json.loads(BROKERS_PATH.read_text(encoding="utf-8"))
    try:
        return _BrokerManifest.model_validate(raw)
    except ValidationError as e:
        raise SystemExit(f"Invalid brokers JSON: {e}") from e


async def _seed(manifest: _BrokerManifest) -> None:
    settings = get_settings()

    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        async with conn.cursor() as cur:
            keys = [b.key for b in manifest.brokers]
            if len(keys) != len(set(keys)):
                raise SystemExit("Duplicate broker keys in brokers JSON")

            inserted = 0
            updated = 0

            for broker in manifest.brokers:
                await cur.execute(
                    sql("seed_upsert_broker"),
                    (
                        uuid4(),
                        manifest.version,
                        broker.key,
                        broker.name,
                        broker.search_url,
                    ),
                )
                row = await cur.fetchone()
                if row and row[0]:
                    inserted += 1
                else:
                    updated += 1

        await conn.commit()

    logger.info(
        "Seed complete: version=%s inserted=%d updated=%d",
        manifest.version,
        inserted,
        updated,
    )
    print(f"Seeded broker version {manifest.version}: {inserted} inserted, {updated} updated")


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    manifest = _load_brokers()
    try:
        asyncio.run(_seed(manifest))
    except Exception as e:
        logger.exception("Seed failed")
        print(f"Seed failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
