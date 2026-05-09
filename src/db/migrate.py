"""Yoyo migration CLI wrapper.

Usage:
    python -m src.db.migrate apply       # apply all pending
    python -m src.db.migrate list        # show migration status

Note: this project does not ship rollback migrations. Schema changes are
delivered as new migrations only. To reset a development database, drop it
and re-apply.
"""

import sys
from pathlib import Path

from yoyo import get_backend, read_migrations

from src.core.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def _backend_url() -> str:
    settings = get_settings()
    return settings.database_url


def apply() -> None:
    backend = get_backend(_backend_url())
    migrations = read_migrations(str(MIGRATIONS_DIR))
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))
    print("Migrations applied.")


def list_status() -> None:
    backend = get_backend(_backend_url())
    migrations = read_migrations(str(MIGRATIONS_DIR))
    applied_ids = {m.id for m in backend.to_rollback(migrations)}
    for m in migrations:
        marker = "[x]" if m.id in applied_ids else "[ ]"
        print(f"{marker} {m.id}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "apply":
        apply()
    elif cmd == "list":
        list_status()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
