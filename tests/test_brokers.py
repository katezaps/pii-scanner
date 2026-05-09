"""Tests for GET /brokers."""

from __future__ import annotations

import psycopg
import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Unit-style tests (seeded DB, no multi-version setup)
# ---------------------------------------------------------------------------


def test_brokers_requires_auth(client: TestClient):
    resp = client.get("/brokers")
    assert resp.status_code == 401


def test_brokers_returns_200(client: TestClient, auth_header):
    resp = client.get("/brokers", cookies=auth_header)
    assert resp.status_code == 200


def test_brokers_response_shape(client: TestClient, auth_header):
    data = client.get("/brokers", cookies=auth_header).json()
    assert "version" in data
    assert "brokers" in data
    assert isinstance(data["brokers"], list)
    assert len(data["brokers"]) > 0


def test_brokers_fields(client: TestClient, auth_header):
    """Each broker must have exactly version, key, name, search_url — no id."""
    data = client.get("/brokers", cookies=auth_header).json()
    expected_keys = {"version", "key", "name", "search_url", "created_at"}
    for broker in data["brokers"]:
        assert set(broker.keys()) == expected_keys


def test_brokers_no_id_exposed(client: TestClient, auth_header):
    """The internal UUID must never appear in the response."""
    data = client.get("/brokers", cookies=auth_header).json()
    for broker in data["brokers"]:
        assert "id" not in broker


def test_brokers_version_matches_top_level(client: TestClient, auth_header):
    data = client.get("/brokers", cookies=auth_header).json()
    for broker in data["brokers"]:
        assert broker["version"] == data["version"]


def test_brokers_sorted_by_name(client: TestClient, auth_header):
    data = client.get("/brokers", cookies=auth_header).json()
    names = [b["name"] for b in data["brokers"]]
    assert names == sorted(names)


# ---------------------------------------------------------------------------
# Integration: multi-version filtering
# ---------------------------------------------------------------------------


@pytest.fixture
def _seed_two_versions(db_url: str):
    """Insert a second broker version and verify only it is returned."""
    import uuid

    v2_brokers = [
        (str(uuid.uuid4()), 2, "newbroker", "NewBroker", "https://newbroker.example.com"),
    ]

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        for row in v2_brokers:
            cur.execute(
                "INSERT INTO brokers (id, version, key, name, search_url) "
                "VALUES (%s, %s, %s, %s, %s)",
                row,
            )
        conn.commit()

    yield v2_brokers

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM brokers WHERE version = 2")
        conn.commit()


def test_only_highest_version_returned(client: TestClient, auth_header, _seed_two_versions):
    """After inserting version 2, /brokers must return only version-2 brokers
    and none from version 1."""
    data = client.get("/brokers", cookies=auth_header).json()

    assert data["version"] == 2
    keys = {b["key"] for b in data["brokers"]}
    assert keys == {"newbroker"}

    # Version 1 brokers must not appear
    v1_keys = {"spokeo", "whitepages", "beenverified", "radaris", "mylife"}
    assert keys.isdisjoint(v1_keys)
