"""Verify the core privacy guarantee: no plaintext PII in the database
after a scan completes.

This is the only test the project ships with. It asserts a real correctness
property — the rest of v0's behavior is exercised manually during
development. If this test passes, the privacy posture documented in
THREAT_MODEL.md is at least plausibly upheld; if it fails, something has
gone seriously wrong.
"""

from __future__ import annotations

from unittest.mock import patch

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from src.models.scan import AuditAgentResult, FormFieldMatch

# Submitted identity values. These are sent to the API as a real scan.
SUBMITTED_IDENTITY = {
    "email": "pii-leak-canary-zzzqqq@example.com",
    "phone": "+12125550101",
    "name": "ZZZ-Plaintext-Canary-Name-ZZZ",
    "address": "9999 Plaintext Canary Avenue, Nowhere, IL 99999",
}

# Distinctive substrings we will hunt for in the DB. These are deliberately
# NOT generic (no bare "example.com", no bare "Avenue") so that finding
# them anywhere in any text column is a real signal of a leak — not a
# false positive from a fixture or library default.
LEAK_NEEDLES = [
    "pii-leak-canary-zzzqqq",
    "12125550101",
    "ZZZ-Plaintext-Canary-Name-ZZZ",
    "Plaintext Canary Avenue",
    "9999 Plaintext Canary",
]


def _scan_every_text_column(db_url: str, needles: list[str]) -> list[tuple[str, str, str]]:
    """Walk every text/varchar/jsonb column in the public schema and return
    any row whose value contains any of the supplied needles.

    Returns a list of (table, column, offending_value) tuples for reporting.
    """
    hits: list[tuple[str, str, str]] = []
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND data_type IN ('text', 'character varying', 'jsonb', 'json')
                  AND table_name NOT LIKE '\\_yoyo%' ESCAPE '\\'
                """
            )
            columns = cur.fetchall()

        for table, col in columns:
            with conn.cursor() as cur:
                query = sql.SQL(
                    "SELECT {col}::text FROM {table} WHERE {col}::text IS NOT NULL"
                ).format(col=sql.Identifier(col), table=sql.Identifier(table))
                cur.execute(query)
                for (value,) in cur.fetchall():
                    for needle in needles:
                        if needle in value:
                            hits.append((table, col, value))
                            break
    return hits


async def _mock_stream(broker_keys=None, identity=None):
    """Mock agent stream that returns a result per broker key.

    Uses broker names from the DB (not keys) so _persist_agent_result
    can look them up. Sets found=True so results are persisted.
    """
    import psycopg

    from src.core.config import get_settings

    with psycopg.connect(get_settings().database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT key, name, search_url FROM brokers "
            "WHERE version = (SELECT MAX(version) FROM brokers)"
        )
        broker_map = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    for key in broker_keys or []:
        name, url = broker_map.get(key, (key, f"https://{key}.example.com/search"))
        yield AuditAgentResult(
            name=name,
            search_url=url,
            status_code=200,
            content_length=1000,
            message=None,
            input_fields_found=["email", "name"],
            matched_inputs=[
                FormFieldMatch(identity_field="email", form_input="email", found=True),
            ],
        )


def test_pii_never_appears_in_database(client: TestClient, auth_header, db_url: str):
    """Submit an identity with distinctive plaintext markers, run a full
    scan, then walk every text column in the database and assert none
    contain those markers."""
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT key FROM brokers WHERE version = (SELECT MAX(version) FROM brokers)")
        broker_keys = [row[0] for row in cur.fetchall()]

    with patch("src.api.audit.stream_audit_agents", side_effect=_mock_stream):
        with client.stream(
            "POST",
            "/audit",
            cookies=auth_header,
            json={
                "broker_keys": broker_keys,
                "save": True,
                **SUBMITTED_IDENTITY,
            },
        ) as resp:
            assert resp.status_code == 200, (
                f"Audit returned {resp.status_code}; cannot verify PII handling"
            )
            # Drain so all writes commit before we inspect
            list(resp.iter_lines())

    # Sanity: the scan actually produced data we can inspect
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM scan_executions")
        (executions,) = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM broker_field_scans")
        (scans,) = cur.fetchone()
    assert executions > 0, "Scan did not produce a scan_executions row"
    assert scans > 0, "Scan did not produce broker_field_scans rows"

    # The actual privacy assertion: no plaintext PII anywhere.
    hits = _scan_every_text_column(db_url, LEAK_NEEDLES)
    if hits:
        report = "\n".join(f"  - {t}.{c}: {v!r}" for t, c, v in hits)
        pytest.fail(
            "Plaintext PII found in database after scan. "
            f"This violates the core privacy guarantee:\n{report}"
        )
