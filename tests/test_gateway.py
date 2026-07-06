"""Happy-path tests for gateway.main POST /v1/profiles.

Defines a sqlite-in-memory DATABASE_URL before importing gateway so the
shared.db engine constructor does not try to reach a non-existent
PostgreSQL at module load. SessionLocal and redis_client are patched at
test time so the actual DB and Redis are never touched.
"""
import os
import uuid
from unittest.mock import MagicMock, patch

import pytest

# Force a safe DATABASE_URL and DB_* envs BEFORE importing the gateway.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["DB_HOST"] = ""
os.environ["DB_PORT"] = ""
os.environ["DB_NAME"] = ""
os.environ["DB_USER"] = ""
os.environ["DB_PASSWORD"] = ""

from fastapi.testclient import TestClient

from gateway import main as gw_main


def _make_db_mock(*first_returns):
    """Build a MagicMock SQLAlchemy session whose db.flush() assigns a UUID id.

    The gateway code does:

        profile = Profile(...)
        db.add(profile)
        db.flush()        # <- gateway relies on server-default id assigned here
        job = Job(profile_id=profile.id, ...)

    Mocks do not auto-assign Column defaults, so we side_effect db.add to
    capture the most recently added object and side_effect db.flush to
    assign a uuid if its id is still None.

    *.first_returns is a sequence passed to .first() side_effect so that
    the User and UserCredits lookups return controlled values.
    """
    fake = MagicMock()
    fake.query.return_value.filter.return_value.first.side_effect = list(
        first_returns
    )

    latest = []

    def fake_add(obj):
        latest.append(obj)

    def fake_flush():
        if latest and getattr(latest[-1], "id", None) is None:
            latest[-1].id = uuid.uuid4()

    def fake_refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()

    fake.add.side_effect = fake_add
    fake.flush.side_effect = fake_flush
    fake.refresh.side_effect = fake_refresh
    fake.commit.return_value = None
    return fake


def test_create_profile_rejects_unknown_target_type():
    """Pydantic validation: target_type must be one of the allowed enums."""
    fake_db = _make_db_mock(None, MagicMock(balance=100))
    fake_redis = MagicMock()
    with patch("shared.db.SessionLocal", return_value=fake_db), \
         patch("gateway.main.redis_client", fake_redis):
        client = TestClient(gw_main.app)
        r = client.post(
            "/v1/profiles",
            json={"target": "alice", "target_type": "invalid", "max_depth": 1},
            headers={"api-key": "osint_x"},
        )
    assert r.status_code == 422


def test_create_profile_requires_api_key_header():
    """Missing api-key header -> 422 from FastAPI header validation."""
    fake_db = _make_db_mock()
    fake_redis = MagicMock()
    with patch("shared.db.SessionLocal", return_value=fake_db), \
         patch("gateway.main.redis_client", fake_redis):
        client = TestClient(gw_main.app)
        r = client.post(
            "/v1/profiles",
            json={"target": "alice", "target_type": "username", "max_depth": 1},
        )
    assert r.status_code == 422


def test_create_profile_ok():
    """Happy path: 200 with profile_id and job_id; redis.rpush called."""
    fake_db = _make_db_mock(None, MagicMock(balance=100))
    fake_redis = MagicMock()
    fake_redis.rpush.return_value = None
    with patch("shared.db.SessionLocal", return_value=fake_db), \
         patch("gateway.main.redis_client", fake_redis):
        client = TestClient(gw_main.app)
        r = client.post(
            "/v1/profiles",
            json={"target": "alice", "target_type": "username", "max_depth": 1},
            headers={"api-key": "osint_x"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "profile_id" in body
    assert "job_id" in body
    assert body["status"] == "pending"
    # Gateway pushes the job onto the osint_jobs queue.
    assert fake_redis.rpush.called
    # And the queue name matches the worker's QUEUE_NAME.
    args, kwargs = fake_redis.rpush.call_args
    assert args[0] == "osint_jobs"
