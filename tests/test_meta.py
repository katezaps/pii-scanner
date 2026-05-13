"""Tests for /signup, /login, /me, /health endpoints."""

from __future__ import annotations

import psycopg
from fastapi.testclient import TestClient


def test_health_no_auth_required(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_signup_and_login(client: TestClient, db_url: str):
    """Full auth round-trip: signup, login, verify credentials."""
    signup = client.post("/signup", json={"name": "roundtrip-user", "password": "testpass123"})
    assert signup.status_code == 201

    login = client.post("/login", json={"name": "roundtrip-user", "password": "testpass123"})
    assert login.status_code == 200
    assert login.json()["name"] == "roundtrip-user"

    bad_pw = client.post("/login", json={"name": "roundtrip-user", "password": "wrong"})
    assert bad_pw.status_code == 401

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE name = %s", ("roundtrip-user",))
        conn.commit()
