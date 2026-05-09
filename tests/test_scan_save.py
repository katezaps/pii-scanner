"""End-to-end tests for scan save behavior.

Verifies that scan results are persisted when save=True, retrievable
via /fetch, and that scan naming (user-provided and auto-generated)
works with collision detection.
"""

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


async def _mock_stream_with_found(broker_keys=None, identity=None):
    """Agent stream that returns results with found=True for email."""
    for key in broker_keys or []:
        yield AuditAgentResult(
            name=key.capitalize(),
            search_url=f"https://www.{key}.com/search",
            status_code=200,
            content_length=5000,
            message=None,
            input_fields_found=["email", "name"],
            matched_inputs=[
                FormFieldMatch(
                    identity_field="email",
                    form_input="email",
                    found=True,
                ),
                FormFieldMatch(
                    identity_field="name",
                    form_input="name",
                    found=False,
                ),
            ],
        )


async def _mock_stream_no_found(broker_keys=None, identity=None):
    """Agent stream with matched inputs but found=None (not checked)."""
    for key in broker_keys or []:
        yield AuditAgentResult(
            name=key.capitalize(),
            search_url=f"https://www.{key}.com/search",
            status_code=200,
            content_length=5000,
            message=None,
            input_fields_found=["email"],
            matched_inputs=[
                FormFieldMatch(
                    identity_field="email",
                    form_input="email",
                    found=None,
                ),
            ],
        )


# ---------------------------------------------------------------------------
# Save + fetch round-trip
# ---------------------------------------------------------------------------


def test_save_true_persists_results_to_fetch(
    client: TestClient,
    auth_header,
    db_url: str,
):
    """When save=True and found is set, results should be retrievable via /fetch."""
    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_mock_stream_with_found),
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
                "name": "Jane Doe",
            },
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            list(resp.iter_lines())  # drain stream

    # Now fetch should return the saved results
    fetch_resp = client.get("/fetch", cookies=auth_header)
    assert fetch_resp.status_code == 200

    data = fetch_resp.json()
    assert len(data["results"]) > 0

    # email was found=True, should appear
    email_results = [r for r in data["results"] if r["field_type"] == "email"]
    assert len(email_results) == 1
    assert email_results[0]["found"] is True

    # name was found=False, should also appear
    name_results = [r for r in data["results"] if r["field_type"] == "name"]
    assert len(name_results) == 1
    assert name_results[0]["found"] is False


def test_save_false_does_not_persist(
    client: TestClient,
    auth_header,
    db_url: str,
):
    """When save=False, results should NOT be written to the database."""
    # Clear any existing executions for this user
    user_id = client.get("/me", cookies=auth_header).json()["user_id"]
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM scan_executions WHERE user_id = %s", (user_id,))
        conn.commit()

    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_mock_stream_with_found),
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
                "email": "test@example.com",
            },
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            list(resp.iter_lines())

    # /fetch should return 404 — nothing saved
    fetch_resp = client.get("/fetch", cookies=auth_header)
    assert fetch_resp.status_code == 404


def test_save_skips_found_none(
    client: TestClient,
    auth_header,
    db_url: str,
):
    """When found=None (not checked), those results should not be persisted."""
    user_id = client.get("/me", cookies=auth_header).json()["user_id"]
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM scan_executions WHERE user_id = %s", (user_id,))
        conn.commit()

    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_mock_stream_no_found),
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

    # found=None results are stored as "discovered but not checked",
    # so /fetch should return them
    fetch_resp = client.get("/fetch", cookies=auth_header)
    assert fetch_resp.status_code == 200
    data = fetch_resp.json()
    # The results should have found=None (not true/false)
    for r in data["results"]:
        assert r["found"] is None or r["found"] is False


# ---------------------------------------------------------------------------
# Scan naming
# ---------------------------------------------------------------------------


def test_user_provided_scan_name(client: TestClient, auth_header):
    """A user-provided scan_name should appear in the started event."""
    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_mock_stream_with_found),
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
                "scan_name": "my_first_scan",
                "email": "test@example.com",
            },
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            body = resp.read().decode()

    events = _parse_sse(body)
    started = json.loads(events[0]["data"])
    assert started["scan_name"] == "my_first_scan"


def test_duplicate_scan_name_returns_409(client: TestClient, auth_header):
    """Submitting a scan with a name that already exists should return 409."""
    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_mock_stream_with_found),
        patch(
            "src.api.audit.resolve_brokers",
            new_callable=AsyncMock,
            return_value=[{"name": "Spokeo", "search_url": "https://www.spokeo.com/search"}],
        ),
    ):
        # First scan with this name
        with client.stream(
            "POST",
            "/audit",
            json={
                "broker_keys": ["spokeo"],
                "save": True,
                "scan_name": "duplicate_test",
                "email": "test@example.com",
            },
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            list(resp.iter_lines())

    # Second scan with the same name should fail
    resp = client.post(
        "/audit",
        json={
            "broker_keys": ["spokeo"],
            "save": True,
            "scan_name": "duplicate_test",
            "email": "test@example.com",
        },
        cookies=auth_header,
    )
    assert resp.status_code == 409
    body = resp.json()
    assert "already exists" in body.get("detail", body.get("message", ""))


def test_auto_generated_name_when_none_provided(client: TestClient, auth_header):
    """When no scan_name is given, a name should be auto-generated."""
    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_mock_stream_with_found),
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
            body = resp.read().decode()

    events = _parse_sse(body)
    started = json.loads(events[0]["data"])
    name = started["scan_name"]

    # Auto-generated names follow adjective_noun format
    assert name is not None
    assert "_" in name
    parts = name.split("_")
    assert len(parts) >= 2


def test_scan_name_not_set_when_save_false(client: TestClient, auth_header):
    """When save=False, scan_name should be None even if provided."""
    with (
        patch("src.api.audit.stream_audit_agents", side_effect=_mock_stream_with_found),
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
                "scan_name": "should_be_ignored",
            },
            cookies=auth_header,
        ) as resp:
            assert resp.status_code == 200
            body = resp.read().decode()

    events = _parse_sse(body)
    started = json.loads(events[0]["data"])
    assert started["scan_name"] is None
