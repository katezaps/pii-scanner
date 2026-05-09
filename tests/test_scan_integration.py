"""Integration tests for the full scan flow.

These tests hit the real DB and auth pipeline with a mocked OpenAI agent,
verifying the complete lifecycle: SSE event sequence, multi-broker fan-out,
identity field acceptance, and error propagation.
"""

from __future__ import annotations

import json
import secrets
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from src.core.crypto import hash_token
from src.models.scan import AuditAgentResult, FormFieldMatch


@pytest.fixture
def isolated_auth(db_url: str):
    """Create an isolated user with no scan history for cache tests."""
    user_id = uuid4()
    token_id = uuid4()
    plaintext = secrets.token_urlsafe(32)
    hashed = hash_token(plaintext)

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (id, name) VALUES (%s, %s)",
            (str(user_id), f"scan-test-{user_id}"),
        )
        cur.execute(
            "INSERT INTO api_tokens (id, user_id, token_hash, name) VALUES (%s, %s, %s, %s)",
            (str(token_id), str(user_id), hashed, "scan-test"),
        )
        conn.commit()

    yield {"pii_scanner_token": plaintext}, str(user_id)

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (str(user_id),))
        cur.execute(
            "DELETE FROM broker_field_scans bfs WHERE NOT EXISTS "
            "(SELECT 1 FROM scan_execution_results ser WHERE ser.broker_field_scan_id = bfs.id)"
        )
        conn.commit()


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


# ---------------------------------------------------------------------------
# Mock agent streams
# ---------------------------------------------------------------------------


async def _multi_broker_stream(broker_keys=None, identity=None):
    """Yields one result per broker key, simulating a real multi-broker scan."""
    for key in broker_keys or []:
        yield AuditAgentResult(
            name=key.capitalize(),
            search_url=f"https://www.{key}.com/search",
            status_code=200,
            content_length=8000,
            message=None,
            input_fields_found=["name", "email"],
            matched_inputs=[
                FormFieldMatch(identity_field="email", form_input="email"),
            ]
            if identity and "email" in identity
            else [],
        )


async def _stream_with_failure(broker_keys=None, identity=None):
    """First broker succeeds, second fails."""
    keys = broker_keys or []
    if len(keys) >= 1:
        yield AuditAgentResult(
            name=keys[0].capitalize(),
            search_url=f"https://www.{keys[0]}.com/search",
            status_code=200,
            content_length=5000,
            message=None,
            input_fields_found=["name"],
            matched_inputs=[],
        )
    if len(keys) >= 2:
        yield AuditAgentResult(
            name=keys[1].capitalize(),
            search_url=f"https://www.{keys[1]}.com/search",
            status_code=None,
            content_length=None,
            message="Scan timed out.",
            input_fields_found=[],
            matched_inputs=[],
        )


async def _stream_with_exception(broker_keys=None, identity=None):
    """Raises an exception mid-stream."""
    yield AuditAgentResult(
        name="Spokeo",
        search_url="https://www.spokeo.com/search",
        status_code=200,
        content_length=5000,
        message=None,
        input_fields_found=["name"],
        matched_inputs=[],
    )
    raise RuntimeError("agent crashed")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_full_scan_event_sequence(client: TestClient, auth_header, db_url: str):
    """A scan against two brokers should produce: started, result, result, done."""
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT key FROM brokers WHERE version = (SELECT MAX(version) FROM brokers) LIMIT 2"
        )
        broker_keys = [row[0] for row in cur.fetchall()]

    assert len(broker_keys) >= 2, "Need at least 2 seeded brokers"

    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_multi_broker_stream),
        patch(
            "src.api.audit.resolve_brokers",
            new_callable=AsyncMock,
            return_value=[
                {"name": k.capitalize(), "search_url": f"https://www.{k}.com/search"}
                for k in broker_keys
            ],
        ),
    ):
        with client.stream(
            "POST",
            "/audit",
            json={"broker_keys": broker_keys, "save": False},
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            body = resp.read().decode()

    events = _parse_sse(body)
    event_types = [e["event"] for e in events]

    assert event_types[0] == "started"
    assert event_types[-1] == "done"
    assert event_types.count("result") == 2

    # Verify started event lists the brokers
    started_data = json.loads(events[0]["data"])
    assert len(started_data["brokers"]) == 2

    # Verify each result has the expected shape
    for e in events:
        if e["event"] == "result":
            data = json.loads(e["data"])
            assert "name" in data
            assert "search_url" in data
            assert "status_code" in data
            assert "input_fields_found" in data
            assert "matched_inputs" in data


def test_scan_with_identity_fields(client: TestClient, isolated_auth):
    """Identity fields should appear in started event and flow to agent results."""
    cookies, _ = isolated_auth
    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_multi_broker_stream),
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
                "save": False,
                "email": "user@example.com",
                "name": "Jane Doe",
            },
            cookies=cookies,
        ) as resp:
            assert resp.status_code == 200
            body = resp.read().decode()

    events = _parse_sse(body)
    started_data = json.loads(events[0]["data"])

    accepted_types = {a["field_type"] for a in started_data["accepted"]}
    assert accepted_types == {"email", "name"}

    # The mock stream returns a match for email when identity has email
    result_data = json.loads(events[1]["data"])
    assert len(result_data["matched_inputs"]) == 1
    assert result_data["matched_inputs"][0]["identity_field"] == "email"


def test_scan_partial_failure(client: TestClient, isolated_auth):
    """One broker timing out should not prevent other results from streaming."""
    cookies, _ = isolated_auth
    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_stream_with_failure),
        patch(
            "src.api.audit.resolve_brokers",
            new_callable=AsyncMock,
            return_value=[
                {"name": "Spokeo", "search_url": "https://www.spokeo.com/search"},
                {"name": "Radaris", "search_url": "https://radaris.com/p/search"},
            ],
        ),
    ):
        with client.stream(
            "POST",
            "/audit",
            json={"broker_keys": ["spokeo", "radaris"], "save": False},
            cookies=cookies,
        ) as resp:
            assert resp.status_code == 200
            body = resp.read().decode()

    events = _parse_sse(body)
    results = [e for e in events if e["event"] == "result"]
    assert len(results) == 2

    # First broker succeeded
    first = json.loads(results[0]["data"])
    assert first["status_code"] == 200
    assert first["message"] is None

    # Second broker timed out
    second = json.loads(results[1]["data"])
    assert second["status_code"] is None
    assert second["message"] == "Scan timed out."

    # Stream still completed with a done event
    assert events[-1]["event"] == "done"


def test_scan_agent_exception_produces_error_event(client: TestClient, auth_header):
    """If the agent stream raises, an error event should be emitted."""
    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_stream_with_exception),
        patch(
            "src.api.audit.resolve_brokers",
            new_callable=AsyncMock,
            return_value=[
                {"name": "Spokeo", "search_url": "https://www.spokeo.com/search"},
            ],
        ),
    ):
        with client.stream(
            "POST",
            "/audit",
            json={"broker_keys": ["spokeo"], "save": False},
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            body = resp.read().decode()

    events = _parse_sse(body)
    event_types = [e["event"] for e in events]

    assert "started" in event_types
    assert "result" in event_types  # the first result before the crash
    assert "error" in event_types
    assert "done" in event_types


def test_scan_no_identity_still_works(client: TestClient, isolated_auth):
    """A scan without any identity fields should still succeed."""
    auth_header, _ = isolated_auth
    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_multi_broker_stream),
        patch(
            "src.api.audit.resolve_brokers",
            new_callable=AsyncMock,
            return_value=[{"name": "Spokeo", "search_url": "https://www.spokeo.com/search"}],
        ),
    ):
        with client.stream(
            "POST",
            "/audit",
            json={"broker_keys": ["spokeo"], "save": False},
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            body = resp.read().decode()

    events = _parse_sse(body)
    started_data = json.loads(events[0]["data"])
    assert started_data["accepted"] == []

    result_data = json.loads(events[1]["data"])
    assert result_data["matched_inputs"] == []


def test_scan_requires_auth(client: TestClient):
    """Scan endpoint must reject unauthenticated requests."""
    resp = client.post("/audit", json={"broker_keys": ["spokeo"], "save": False})
    assert resp.status_code == 401


def test_scan_rejects_empty_keys(client: TestClient, auth_header):
    resp = client.post("/audit", json={"broker_keys": [], "save": False}, cookies=auth_header)
    assert resp.status_code == 400


def test_scan_identity_passed_to_runner(client: TestClient, auth_header):
    """Verify the identity dict is passed through to stream_audit_agents."""
    mock_fn = AsyncMock()

    async def empty_stream(*args, **kwargs):
        return
        yield  # noqa: F401 - makes this an async generator

    mock_fn.side_effect = empty_stream

    with (
        patch("src.api.audit.stream_audit_agents", mock_fn),
        patch("src.api.audit.resolve_brokers", new_callable=AsyncMock, return_value=[]),
    ):
        resp = client.post(
            "/audit",
            json={
                "broker_keys": ["spokeo"],
                "save": False,
                "email": "a@b.com",
                "name": "Jane",
            },
            cookies=auth_header,
        )

    assert resp.status_code == 200
    mock_fn.assert_called_once_with(
        broker_keys=["spokeo"],
        identity={"email": "a@b.com", "name": "Jane"},
    )
