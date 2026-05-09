"""Tests for /signup, /login, /me, /health endpoints."""

from __future__ import annotations

import psycopg
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_no_auth_required(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "broker_version" in data


# ---------------------------------------------------------------------------
# /me
# ---------------------------------------------------------------------------


def test_me_requires_auth(client: TestClient):
    resp = client.get("/me")
    assert resp.status_code == 401


def test_me_returns_user_info(client: TestClient, auth_header):
    resp = client.get("/me", cookies=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "user_id" in data
    assert "name" in data
    assert "token_id" in data


# ---------------------------------------------------------------------------
# /signup
# ---------------------------------------------------------------------------


def test_signup_creates_user(client: TestClient, db_url: str):
    resp = client.post(
        "/signup",
        json={
            "name": "signup-test-user",
            "password": "testpass123",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "signup-test-user"

    # Cleanup
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE name = %s", ("signup-test-user",))
        conn.commit()


def test_signup_rejects_duplicate_name(client: TestClient, db_url: str):
    client.post(
        "/signup",
        json={
            "name": "dup-test-user",
            "password": "testpass123",
        },
    )
    resp = client.post(
        "/signup",
        json={
            "name": "dup-test-user",
            "password": "testpass456",
        },
    )
    assert resp.status_code == 409

    # Cleanup
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE name = %s", ("dup-test-user",))
        conn.commit()


def test_signup_rejects_short_password(client: TestClient):
    resp = client.post(
        "/signup",
        json={
            "name": "short-pw-user",
            "password": "short",
        },
    )
    assert resp.status_code == 400


def test_signup_rejects_empty_name(client: TestClient):
    resp = client.post(
        "/signup",
        json={
            "name": "",
            "password": "testpass123",
        },
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /login
# ---------------------------------------------------------------------------


def test_login_valid_credentials(client: TestClient, db_url: str):
    # Create a user via signup first
    signup_resp = client.post(
        "/signup",
        json={
            "name": "login-test-user",
            "password": "testpass123",
        },
    )
    assert signup_resp.status_code == 201

    resp = client.post(
        "/login",
        json={
            "name": "login-test-user",
            "password": "testpass123",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "login-test-user"
    assert "user_id" in data

    # Cleanup
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE name = %s", ("login-test-user",))
        conn.commit()


def test_login_wrong_password(client: TestClient, db_url: str):
    client.post(
        "/signup",
        json={
            "name": "badpw-test-user",
            "password": "testpass123",
        },
    )

    resp = client.post(
        "/login",
        json={
            "name": "badpw-test-user",
            "password": "wrongpassword",
        },
    )
    assert resp.status_code == 401

    # Cleanup
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE name = %s", ("badpw-test-user",))
        conn.commit()


def test_login_nonexistent_user(client: TestClient):
    resp = client.post(
        "/login",
        json={
            "name": "does-not-exist",
            "password": "testpass123",
        },
    )
    assert resp.status_code == 401
