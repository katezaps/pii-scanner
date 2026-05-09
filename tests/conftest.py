"""Pytest fixtures for the v0 test suite.

The suite has a single integration test that needs a running Postgres,
applied migrations, seeded brokers, a test user, a valid bearer token,
and a FastAPI TestClient. These fixtures wire that up and tear it down.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from src.core.config import get_settings
from src.core.crypto import hash_token
from src.main import create_app


@pytest.fixture(scope="session")
def db_url() -> str:
    return get_settings().database_url


@pytest.fixture(scope="session")
def test_user(db_url: str) -> Iterator[tuple[str, str]]:
    """Provision a fresh user + token for the test session.

    Yields ``(user_id, plaintext_token)``. The user is deleted on teardown,
    which cascades to tokens and any executions/results created during the
    test.
    """
    user_id = uuid4()
    token_id = uuid4()
    plaintext = secrets.token_urlsafe(32)
    hashed = hash_token(plaintext)

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (id, name) VALUES (%s, %s)",
            (str(user_id), "test-user"),
        )
        cur.execute(
            """
            INSERT INTO api_tokens (id, user_id, token_hash, name)
            VALUES (%s, %s, %s, %s)
            """,
            (str(token_id), str(user_id), hashed, "integration-test"),
        )
        conn.commit()

    yield str(user_id), plaintext

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        # Delete this user's execution results
        cur.execute(
            "DELETE FROM scan_execution_results ser "
            "USING scan_executions se "
            "WHERE ser.execution_id = se.id AND se.user_id = %s",
            (str(user_id),),
        )
        # Detach field scans owned by this user so CASCADE doesn't fail
        cur.execute(
            "UPDATE broker_field_scans SET user_id = NULL WHERE user_id = %s",
            (str(user_id),),
        )
        cur.execute("DELETE FROM scan_executions WHERE user_id = %s", (str(user_id),))
        cur.execute("DELETE FROM users WHERE id = %s", (str(user_id),))
        # Clean orphaned field scans
        cur.execute(
            "DELETE FROM broker_field_scans bfs "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM scan_execution_results ser "
            "  WHERE ser.broker_field_scan_id = bfs.id"
            ")"
        )
        conn.commit()


@pytest.fixture
def auth_header(test_user) -> dict[str, str]:
    """Return cookies dict for authenticated requests."""
    _, token = test_user
    return {"pii_scanner_token": token}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app, cookies={}) as c:
        yield c
