"""Tests for scan cancellation on new submission.

When a user submits a new scan while a previous one is still running,
any RUNNING broker_field_scans for that user should be set to CANCELLED.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient

from src.core.config import get_settings
from src.models.scan import AuditAgentResult, FormFieldMatch


async def _mock_stream(broker_keys=None, identity=None):
    for key in broker_keys or []:
        yield AuditAgentResult(
            name=key.capitalize(),
            search_url=f"https://www.{key}.com/search",
            status_code=200,
            content_length=5000,
            message=None,
            input_fields_found=["email"],
            matched_inputs=[
                FormFieldMatch(identity_field="email", form_input="email", found=True),
            ],
        )


def _insert_running_scan(db_url: str, user_id: str) -> tuple[str, str]:
    """Insert a RUNNING broker_field_scan linked to an execution.

    Returns (execution_id, bfs_id) so callers can assert on them.
    """
    settings = get_settings()
    execution_id = str(uuid4())
    bfs_id = str(uuid4())
    expires_at = datetime.now(UTC) + timedelta(days=30)

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        # Get a real broker id from the seeded data
        cur.execute("SELECT id FROM brokers LIMIT 1")
        broker_id = cur.fetchone()[0]

        cur.execute("SELECT version FROM brokers ORDER BY version DESC LIMIT 1")
        version = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO scan_executions (id, user_id, version, expires_at, name) "
            "VALUES (%s, %s, %s, %s, %s)",
            (execution_id, user_id, version, expires_at, None),
        )
        cur.execute(
            "INSERT INTO broker_field_scans "
            "(id, field_name, field_type, broker_id, "
            "state, found, expires_at, user_id) "
            "VALUES (%s, %s, %s, %s, 'RUNNING', false, %s, %s)",
            (
                bfs_id,
                f"agent:test:{uuid4().hex}",
                "email",
                str(broker_id),
                expires_at,
                user_id,
            ),
        )
        cur.execute(
            "INSERT INTO scan_execution_results (execution_id, broker_field_scan_id, source) "
            "VALUES (%s, %s, 'FRESH')",
            (execution_id, bfs_id),
        )
        conn.commit()

    return execution_id, bfs_id


def test_new_scan_cancels_running_scans(
    client: TestClient,
    auth_header,
    db_url: str,
):
    """Submitting a new scan should cancel any RUNNING broker_field_scans for that user."""
    user_id = client.get("/me", cookies=auth_header).json()["user_id"]
    exec_id, bfs_id = _insert_running_scan(db_url, user_id)

    # Verify the row is RUNNING
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT state FROM broker_field_scans WHERE id = %s", (bfs_id,))
        assert cur.fetchone()[0] == "RUNNING"

    # Submit a new scan — this should cancel the RUNNING row
    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_mock_stream),
        patch(
            "src.api.audit.resolve_brokers",
            new_callable=AsyncMock,
            return_value=[{"name": "Spokeo", "search_url": "https://www.spokeo.com/search"}],
        ),
    ):
        with client.stream(
            "POST",
            "/audit",
            json={
                "broker_keys": ["spokeo"],
                "save": True,
                "email": "test@example.com",
            },
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            list(resp.iter_lines())

    # The previously-RUNNING row should now be CANCELLED
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT state FROM broker_field_scans WHERE id = %s", (bfs_id,))
        assert cur.fetchone()[0] == "CANCELLED"

        # The execution itself should also be CANCELLED
        cur.execute("SELECT state FROM scan_executions WHERE id = %s", (exec_id,))
        assert cur.fetchone()[0] == "CANCELLED"


def test_completed_scans_not_cancelled(
    client: TestClient,
    auth_header,
    db_url: str,
):
    """Only RUNNING rows should be cancelled — SUCCESS rows must be left alone."""
    user_id = client.get("/me", cookies=auth_header).json()["user_id"]
    _, running_bfs_id = _insert_running_scan(db_url, user_id)

    # Also insert a SUCCESS row for the same user
    settings = get_settings()
    success_bfs_id = str(uuid4())
    expires_at = datetime.now(UTC) + timedelta(days=30)

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM brokers LIMIT 1")
        broker_id = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO broker_field_scans "
            "(id, field_name, field_type, broker_id, "
            "state, found, expires_at, user_id) "
            "VALUES (%s, %s, %s, %s, 'SUCCESS', true, %s, %s)",
            (
                success_bfs_id,
                f"agent:test:{uuid4().hex}",
                "email",
                str(broker_id),
                expires_at,
                user_id,
            ),
        )
        conn.commit()

    # Submit a new scan
    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_mock_stream),
        patch(
            "src.api.audit.resolve_brokers",
            new_callable=AsyncMock,
            return_value=[{"name": "Spokeo", "search_url": "https://www.spokeo.com/search"}],
        ),
    ):
        with client.stream(
            "POST",
            "/audit",
            json={
                "broker_keys": ["spokeo"],
                "save": True,
                "email": "test@example.com",
            },
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            list(resp.iter_lines())

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        # RUNNING row should be CANCELLED
        cur.execute("SELECT state FROM broker_field_scans WHERE id = %s", (running_bfs_id,))
        assert cur.fetchone()[0] == "CANCELLED"

        # SUCCESS row should still be SUCCESS
        cur.execute("SELECT state FROM broker_field_scans WHERE id = %s", (success_bfs_id,))
        assert cur.fetchone()[0] == "SUCCESS"


async def _empty_stream(broker_keys=None, identity=None):
    """Stream that yields nothing — simulates instant cancellation."""
    return
    yield  # noqa: F401 — makes this an async generator


def test_cancelled_scan_visible_in_fetch(
    client: TestClient,
    db_url: str,
):
    """A saved scan cancelled before any brokers finish should appear
    in /fetch/scans with per-broker CANCELLED state in /fetch results."""
    # Create an isolated user so other tests don't interfere
    import secrets

    from src.core.crypto import hash_token

    user_id = str(uuid4())
    token_id = str(uuid4())
    plaintext = secrets.token_urlsafe(32)
    hashed = hash_token(plaintext)

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (id, name) VALUES (%s, %s)",
            (user_id, f"cancel-fetch-{user_id}"),
        )
        cur.execute(
            "INSERT INTO api_tokens (id, user_id, token_hash, name) VALUES (%s, %s, %s, %s)",
            (token_id, user_id, hashed, "cancel-fetch"),
        )
        conn.commit()

    headers = {"pii_scanner_token": plaintext}

    # Get two real broker keys from the DB
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT key, name, search_url FROM brokers "
            "WHERE version = (SELECT MAX(version) FROM brokers) "
            "ORDER BY name LIMIT 2"
        )
        broker_rows = cur.fetchall()

    assert len(broker_rows) >= 2, "Need at least 2 seeded brokers"
    broker_keys = [r[0] for r in broker_rows]
    broker_list = [{"name": r[1], "search_url": r[2]} for r in broker_rows]

    # Start a saved scan that completes with zero broker results
    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_empty_stream),
        patch("src.api.audit.resolve_brokers", new_callable=AsyncMock, return_value=broker_list),
    ):
        with client.stream(
            "POST",
            "/audit",
            json={
                "broker_keys": broker_keys,
                "save": True,
                "email": "test@example.com",
            },
            cookies=headers,
        ) as resp:
            assert resp.status_code == 200
            resp.read()

    # Verify it appears in /fetch/scans
    scans_resp = client.get("/fetch/scans", cookies=headers)
    assert scans_resp.status_code == 200
    scans = scans_resp.json()["scans"]
    assert len(scans) == 1

    scan = scans[0]
    assert scan["broker_count"] == 2
    assert scan["incomplete_count"] == 2

    # Verify per-broker CANCELLED state in /fetch
    fetch_resp = client.get(
        f"/fetch?execution_id={scan['execution_id']}",
        cookies=headers,
    )
    assert fetch_resp.status_code == 200
    results = fetch_resp.json()["results"]

    # Each broker gets two _status rows: a pre-created RUNNING marker
    # (field_name includes execution_id) and a CANCELLED row persisted
    # when the broker is missing from stream results.  Both use
    # field_type="_status" but different field_name values, so the
    # upsert creates separate rows.
    status_rows = [r for r in results if r["field_type"] == "_status"]
    assert len(status_rows) == 4
    cancelled = [r for r in status_rows if r["state"] == "CANCELLED"]
    assert len(cancelled) >= 2

    # Cleanup: delete execution results first, then field scans, then user
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM scan_execution_results ser "
            "USING scan_executions se "
            "WHERE ser.execution_id = se.id AND se.user_id = %s",
            (user_id,),
        )
        cur.execute(
            "DELETE FROM broker_field_scans WHERE user_id = %s",
            (user_id,),
        )
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
