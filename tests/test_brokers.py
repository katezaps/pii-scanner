"""Tests for GET /brokers endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_brokers_returns_200(client: TestClient, auth_header):
    resp = client.get("/brokers", cookies=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data
    assert len(data["brokers"]) > 0


def test_brokers_fields(client: TestClient, auth_header):
    """Each broker must have the expected fields — no id exposed."""
    data = client.get("/brokers", cookies=auth_header).json()
    expected_keys = {"version", "key", "name", "search_url", "created_at", "opt_out_url", "opt_out_url_source"}
    for broker in data["brokers"]:
        assert set(broker.keys()) == expected_keys


def test_only_highest_version_returned(client: TestClient, auth_header):
    data = client.get("/brokers", cookies=auth_header).json()
    top = data["version"]
    for b in data["brokers"]:
        assert b["version"] == top


def test_brokers_json_parses_and_matches_db(client: TestClient, auth_header):
    """brokers.json should parse and its entries should match what's seeded in the DB."""
    import json
    from pathlib import Path

    brokers_path = Path(__file__).resolve().parents[1] / "brokers" / "brokers.json"
    manifest = json.loads(brokers_path.read_text(encoding="utf-8"))
    assert "version" in manifest
    assert len(manifest["brokers"]) > 0

    for entry in manifest["brokers"]:
        assert "key" in entry
        assert "name" in entry
        assert "search_url" in entry

    # DB should have at least as many brokers as the JSON
    data = client.get("/brokers", cookies=auth_header).json()
    db_keys = {b["key"] for b in data["brokers"]}
    json_keys = {b["key"] for b in manifest["brokers"]}
    assert json_keys <= db_keys
