"""Integration tests for the full scan flow."""

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


async def _multi_broker_stream(brokers=None, identity=None):
    for b in brokers or []:
        yield AuditAgentResult(
            name=b["name"],
            search_url=b["search_url"],
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


def test_full_scan_event_sequence(client: TestClient, auth_header, db_url: str):
    """started → result per broker → done."""
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT key FROM brokers WHERE version = (SELECT MAX(version) FROM brokers) LIMIT 2"
        )
        broker_keys = [row[0] for row in cur.fetchall()]

    assert len(broker_keys) >= 2

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
            "POST", "/audit",
            json={"broker_keys": broker_keys, "save": False},
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            body = resp.read().decode()

    events = _parse_sse(body)
    types = [e["event"] for e in events]
    assert types[0] == "started"
    assert types[-1] == "done"
    assert types.count("result") == 2


def test_scan_requires_auth(client: TestClient):
    resp = client.post("/audit", json={"broker_keys": ["spokeo"], "save": False})
    assert resp.status_code == 401


def test_scan_opt_out_url_flows_through_orchestrator(
    client: TestClient, isolated_auth, db_url: str
):
    """DB opt_out_url flows through the real orchestrator to the SSE result."""
    cookies, _ = isolated_auth
    opt_out = "https://www.spokeo.com/optout"

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE brokers SET opt_out_url = %s, opt_out_url_source = 'GENERATED' "
            "WHERE key = 'spokeo' AND version = (SELECT MAX(version) FROM brokers)",
            (opt_out,),
        )
        conn.commit()

    try:
        async def _fake_audit_broker(name, search_url, identity=None, *, settings, db_opt_out_url=None):
            return AuditAgentResult(
                name=name,
                search_url=search_url,
                status_code=200,
                content_length=5000,
                message=None,
                input_fields_found=["email"],
                matched_inputs=[],
                opt_out_url=db_opt_out_url,
            )

        with patch("src.services.audit.orchestrator.audit_broker", side_effect=_fake_audit_broker):
            with client.stream(
                "POST", "/audit",
                json={"broker_keys": ["spokeo"], "save": False, "email": "a@b.com"},
                cookies=cookies,
            ) as resp:
                assert resp.status_code == 200
                body = resp.read().decode()

        events = _parse_sse(body)
        results = [e for e in events if e["event"] == "result"]
        assert len(results) == 1
        assert json.loads(results[0]["data"])["opt_out_url"] == opt_out

    finally:
        with psycopg.connect(db_url) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE brokers SET opt_out_url = NULL, opt_out_url_source = NULL "
                "WHERE key = 'spokeo' AND version = (SELECT MAX(version) FROM brokers)",
            )
            conn.commit()
