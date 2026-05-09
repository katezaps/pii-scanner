"""SQL query loader.

Reads .sql files from src/db/sql/ and caches them as strings.
Usage: ``from src.db.queries import sql`` then ``sql("scan_cache_hit")``.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

_SQL_DIR = Path(__file__).resolve().parent / "sql"


@cache
def sql(name: str) -> str:
    """Load and cache a SQL query by filename (without .sql extension)."""
    path = _SQL_DIR / f"{name}.sql"
    return path.read_text(encoding="utf-8").strip()
