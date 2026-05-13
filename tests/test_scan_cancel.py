"""Tests for scan cancellation on new submission."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient

from src.models.scan import AuditAgentResult, FormFieldMatch


async def _mock_stream(brokers=None, identity=None):
    for b in brokers or []:
        yield AuditAgentResult(
            name=b["name"],
            search_url=b["search_url"],
            status_code=200,
            content_length=5000,
            message=None,
            input_fields_found=["email"],
            matched_inputs=[
                FormFieldMatch(identity_field="email", form_input="email", found=True),
            ],
        )


def test_new_scan_cancels_running_scans(client: TestClient, auth_header, db_url: str):
    """Submitting a new scan should cancel any RUNNING broker_field_scans for that user."""
    user_id = client.get("/me", cookies=auth_header).json()["user_id"]
    execution_id = str(uuid4())
    bfs_id = str(uuid4())
    expires_at = datetime.now(UTC) + timedelta(days=30)

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, version FROM brokers LIMIT 1")
        broker_id, version = cur.fetchone()

        cur.execute(
            "INSERT INTO scan_executions (id, user_id, version, expires_at, name) "
            "VALUES (%s, %s, %s, %s, %s)",
            (execution_id, user_id, version, expires_at, None),
        )
        cur.execute(
            "INSERT INTO broker_field_scans "
            "(id, field_name, field_type, broker_id, state, found, expires_at, user_id) "
            "VALUES (%s, %s, %s, %s, 'RUNNING', false, %s, %s)",
            (bfs_id, f"agent:test:{uuid4().hex}", "email", str(broker_id), expires_at, user_id),
        )
        cur.execute(
            "INSERT INTO scan_execution_results (execution_id, broker_field_scan_id, source) "
            "VALUES (%s, %s, 'FRESH')",
            (execution_id, bfs_id),
        )
        conn.commit()

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
            json={"broker_keys": ["spokeo"], "save": True, "email": "test@example.com"},
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            list(resp.iter_lines())

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT state FROM broker_field_scans WHERE id = %s", (bfs_id,))
        assert cur.fetchone()[0] == "CANCELLED"
        cur.execute("SELECT state FROM scan_executions WHERE id = %s", (execution_id,))
        assert cur.fetchone()[0] == "CANCELLED"
