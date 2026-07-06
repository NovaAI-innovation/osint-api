"""Pytest fixtures for the OSINT-api test harness.

Imports the project modules and provides a few mocks commonly used across
the service tests: a fake DB session, a fake redis client, and a
plain Python subprocess stub for the tool runner.
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

# Make the project root importable so worker/main.py and gateway/main.py
# imports resolve.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture
def fake_session():
    """A MagicMock SQLAlchemy session. Tracks add/commit but never touches a DB."""
    s = MagicMock()
    # Default: query(...).filter(...).first() returns None so the "row not found"
    # branches in create_profile / process_job run.
    s.query.return_value.filter.return_value.first.return_value = None
    return s


@pytest.fixture
def fake_redis():
    """A MagicMock redis client. rpush/lpush return None without raising."""
    r = MagicMock()
    r.rpush.return_value = None
    r.lpush.return_value = None
    return r
