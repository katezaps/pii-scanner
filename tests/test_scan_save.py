"""Tests for scan save/fetch round-trip and duplicate name detection."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import psycopg
from fastapi.testclient import TestClient

from src.models.scan import AuditAgentResult, FormFieldMatch


def _parse_sse(text: str) -> list[dict]:
    events = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("event:"):
            current["event"] = line[len("event:") :].strip()
        elif line.startswith("data:"):
            current["data"] = line[len("data:") :].strip()
        elif line == "" and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


async def _mock_stream(brokers=None, identity=None):
    for b in brokers or []:
        yield AuditAgentResult(
            name=b["name"],
            search_url=b["search_url"],
            status_code=200,
            content_length=5000,
            message=None,
            input_fields_found=["email", "name"],
            matched_inputs=[
                FormFieldMatch(identity_field="email", form_input="email", found=True),
                FormFieldMatch(identity_field="name", form_input="name", found=False),
            ],
        )


def test_save_true_persists_results_to_fetch(client: TestClient, auth_header, db_url: str):
    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_mock_stream),
        patch(
            "src.api.audit.resolve_brokers",
            new_callable=AsyncMock,
            return_value=[{"name": "Spokeo", "search_url": "https://www.spokeo.com/search"}],
        ),
    ):
        with client.stream(
            "POST", "/audit",
            json={"broker_keys": ["spokeo"], "save": True, "email": "test@example.com", "name": "Jane Doe"},
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            list(resp.iter_lines())

    fetch_resp = client.get("/fetch", cookies=auth_header)
    assert fetch_resp.status_code == 200
    data = fetch_resp.json()
    email_results = [r for r in data["results"] if r["field_type"] == "email"]
    assert len(email_results) == 1
    assert email_results[0]["found"] is True


def test_save_false_does_not_persist(client: TestClient, auth_header, db_url: str):
    user_id = client.get("/me", cookies=auth_header).json()["user_id"]
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM scan_executions WHERE user_id = %s", (user_id,))
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
            "POST", "/audit",
            json={"broker_keys": ["spokeo"], "save": False, "email": "test@example.com"},
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            list(resp.iter_lines())

    assert client.get("/fetch", cookies=auth_header).status_code == 404


def test_duplicate_scan_name_returns_409(client: TestClient, auth_header):
    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_mock_stream),
        patch(
            "src.api.audit.resolve_brokers",
            new_callable=AsyncMock,
            return_value=[{"name": "Spokeo", "search_url": "https://www.spokeo.com/search"}],
        ),
    ):
        with client.stream(
            "POST", "/audit",
            json={"broker_keys": ["spokeo"], "save": True, "scan_name": "dup_test", "email": "test@example.com"},
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            list(resp.iter_lines())

    resp = client.post(
        "/audit",
        json={"broker_keys": ["spokeo"], "save": True, "scan_name": "dup_test", "email": "test@example.com"},
        cookies=auth_header,
    )
    assert resp.status_code == 409


def test_fetch_response_shape(client: TestClient, auth_header, db_url: str):
    """Verify /fetch returns all expected fields including opt_out_url."""
    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_mock_stream),
        patch(
            "src.api.audit.resolve_brokers",
            new_callable=AsyncMock,
            return_value=[{"name": "Spokeo", "search_url": "https://www.spokeo.com/search"}],
        ),
    ):
        with client.stream(
            "POST", "/audit",
            json={"broker_keys": ["spokeo"], "save": True, "scan_name": "shape_test", "email": "test@example.com"},
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            list(resp.iter_lines())

    data = client.get("/fetch", cookies=auth_header).json()
    assert "execution_id" in data
    assert "expires_at" in data
    assert "summary" in data
    assert data["summary"]["found_count"] >= 0

    field_results = [r for r in data["results"] if r["field_type"] != "_status"]
    assert len(field_results) > 0
    r = field_results[0]
    assert set(r.keys()) >= {
        "broker_id", "broker_key", "broker_name", "search_url",
        "field_type", "state", "found", "opt_out_url",
    }


def test_expired_scans_excluded_from_fetch(client: TestClient, auth_header, db_url: str):
    """Scans with expires_at in the past should not appear in /fetch."""
    user_id = client.get("/me", cookies=auth_header).json()["user_id"]

    # Insert an expired execution directly
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    exec_id = str(uuid4())
    expired = datetime.now(UTC) - timedelta(days=1)

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT version FROM brokers ORDER BY version DESC LIMIT 1")
        version = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO scan_executions (id, user_id, version, expires_at, state, name) "
            "VALUES (%s, %s, %s, %s, 'SUCCESS', 'expired_test')",
            (exec_id, user_id, version, expired),
        )
        conn.commit()

    try:
        scans = client.get("/fetch/scans", cookies=auth_header).json()["scans"]
        expired_ids = [s["execution_id"] for s in scans if s["name"] == "expired_test"]
        assert len(expired_ids) == 0
    finally:
        with psycopg.connect(db_url) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM scan_executions WHERE id = %s", (exec_id,))
            conn.commit()
