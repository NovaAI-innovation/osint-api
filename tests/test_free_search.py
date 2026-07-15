"""Happy-path tests for the dev free-search endpoint and GET /v1/jobs/{id}.

Same pattern as tests/test_gateway.py: force a safe DATABASE_URL before
importing gateway.main, then patch shared.db.SessionLocal and
gateway.main.redis_client so no real I/O happens.
"""
import os
import uuid
from unittest.mock import MagicMock, patch

# Safe env BEFORE importing gateway
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["DB_HOST"] = ""
os.environ["DB_PORT"] = ""
os.environ["DB_NAME"] = ""
os.environ["DB_USER"] = ""
os.environ["DB_PASSWORD"] = ""
os.environ["OSINT_ENABLE_FREE_SEARCH"] = "true"

from fastapi.testclient import TestClient

from gateway import main as gw_main


def test_healthz_returns_ok():
    """Liveness probe is always 200 with no auth required."""
    client = TestClient(gw_main.app)
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "osint-api-gateway"


def test_free_search_get_username():
    client = TestClient(gw_main.app)
    r = client.get("/dev/free-search", params={"target_type": "username", "target": "alice"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dev_mode"] is True
    assert body["target_type"] == "username"
    assert body["target"] == "alice"
    assert isinstance(body["result"]["matches"], list)


def test_free_search_get_email():
    client = TestClient(gw_main.app)
    r = client.get("/dev/free-search", params={"target_type": "email", "target": "alice@example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["target_type"] == "email"
    assert any("service" in m for m in body["result"]["matches"])


def test_free_search_post():
    client = TestClient(gw_main.app)
    r = client.post("/dev/free-search", json={"target_type": "domain", "target": "example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["target_type"] == "domain"
    assert any(m.get("type") in ("A", "MX", "NS", "TXT") for m in body["result"]["matches"])


def test_free_search_rejects_unknown_type():
    client = TestClient(gw_main.app)
    r = client.get("/dev/free-search", params={"target_type": "bogus", "target": "x"})
    assert r.status_code == 422


def test_free_search_deterministic_seed():
    client = TestClient(gw_main.app)
    r1 = client.get("/dev/free-search", params={"target_type": "username", "target": "alice"})
    r2 = client.get("/dev/free-search", params={"target_type": "username", "target": "alice"})
    assert r1.json()["result"]["seed"] == r2.json()["result"]["seed"]


def test_free_search_404_when_disabled(monkeypatch):
    monkeypatch.setattr(gw_main, "ENABLE_FREE_SEARCH", False)
    client = TestClient(gw_main.app)
    assert client.get("/dev/free-search", params={"target_type": "username", "target": "alice"}).status_code == 404
    assert client.post("/dev/free-search", json={"target_type": "username", "target": "alice"}).status_code == 404


def _make_job(user_id, status="completed"):
    j = MagicMock()
    j.id = uuid.uuid4()
    j.user_id = user_id
    j.profile_id = None
    j.parent_job_id = None
    j.depth = 0
    j.target_type = "username"
    j.target_value = "alice"
    j.requested_tools = ["sherlock"]
    j.status = status
    j.created_at = None
    j.updated_at = None
    j.expires_at = None
    j.results = []
    return j


def test_read_job_404_when_missing():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    with patch("shared.db.SessionLocal", return_value=db):
        client = TestClient(gw_main.app)
        r = client.get(f"/v1/jobs/{uuid.uuid4()}", headers={"api-key": "osint_x"})
    assert r.status_code == 404


def test_read_job_returns_owned_job():
    user = MagicMock(); user.id = uuid.uuid4()
    job = _make_job(user.id)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = job
    # FastAPI captures the get_current_user reference at route-decorator time,
    # so we override the dependency directly via app.dependency_overrides.
    gw_main.app.dependency_overrides[gw_main.get_current_user] = lambda: user
    try:
        with patch("shared.db.SessionLocal", return_value=db):
            client = TestClient(gw_main.app)
            r = client.get(f"/v1/jobs/{job.id}", headers={"api-key": "osint_x"})
    finally:
        gw_main.app.dependency_overrides.pop(gw_main.get_current_user, None)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job_id"] == str(job.id)
    assert body["status"] == "completed"
    assert body["target_value"] == "alice"
    assert body["results"] == []


def test_read_job_403_when_other_user():
    owner = uuid.uuid4()
    user = MagicMock(); user.id = uuid.uuid4()
    job = _make_job(owner)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = job
    gw_main.app.dependency_overrides[gw_main.get_current_user] = lambda: user
    try:
        with patch("shared.db.SessionLocal", return_value=db):
            client = TestClient(gw_main.app)
            r = client.get(f"/v1/jobs/{job.id}", headers={"api-key": "osint_x"})
    finally:
        gw_main.app.dependency_overrides.pop(gw_main.get_current_user, None)
    assert r.status_code == 403


# ---------- CORS middleware (used by the HTML UI on a different port) ----------

def test_cors_preflight_allows_html_origin():
    """The HTML UI on http://localhost:8080 must be allowed to call /v1/profiles.

    A CORS preflight is an OPTIONS request with Origin + Access-Control-Request-Method.
    """
    client = TestClient(gw_main.app)
    r = client.options(
        "/v1/profiles",
        headers={
            "Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,api-key",
        },
    )
    assert r.status_code in (200, 204)
    assert r.headers["access-control-allow-origin"] in ("*", "http://localhost:8080")
    # api-key must be in the allow-headers list (otherwise the real POST is blocked).
    allow_headers = r.headers.get("access-control-allow-headers", "").lower()
    assert "api-key" in allow_headers


def test_cors_actual_response_includes_acao():
    """The actual GET /dev/free-search response carries the CORS header."""
    client = TestClient(gw_main.app)
    r = client.get(
        "/dev/free-search",
        params={"target_type": "username", "target": "alice"},
        headers={"Origin": "http://localhost:8080"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] in ("*", "http://localhost:8080")


def test_cors_respects_configured_origins():
    """When OSINT_CORS_ORIGINS is locked down, only listed origins get the header.

    Builds a throwaway FastAPI app with a custom allow_origins list. Starlette
    freezes the middleware stack at first request, so we cannot mutate
    `gw_main.app` after the gateway has started.
    """
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://app.example.com"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "api-key"],
    )

    @app.get("/healthz")
    def _health():
        return {"status": "ok"}

    client = TestClient(app)
    # Allowed origin: header echoes it back.
    r1 = client.get("/healthz", headers={"Origin": "https://app.example.com"})
    assert r1.headers["access-control-allow-origin"] == "https://app.example.com"
    # Disallowed origin: header must NOT echo it (CORS spec).
    r2 = client.get("/healthz", headers={"Origin": "http://localhost:8080"})
    assert r2.headers.get("access-control-allow-origin") != "http://localhost:8080"
