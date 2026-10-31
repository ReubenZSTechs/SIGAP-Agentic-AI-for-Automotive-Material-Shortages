"""CORS: every origin is allowed, also on unexpected server errors (otherwise the browser shows "cannot connect")."""
from fastapi.testclient import TestClient

from app.main import app as fastapi_app


def test_any_origin_is_allowed_and_responses_carry_server_timing(client):
    r = client.get("/health", headers={"Origin": "https://example.com"})
    assert r.headers["access-control-allow-origin"] == "*"
    pre = client.options("/api/v1/hub/missions", headers={"Origin": "https://anything.example",
                                                          "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == "*"
    r = client.get("/api/v1/suppliers", headers={"Origin": "https://example.com"})
    assert r.headers["server-timing"].startswith('db;desc="')


def test_unexpected_error_is_json_500_with_cors_headers():
    def boom():
        raise RuntimeError("boom")
    fastapi_app.add_api_route("/__boom", boom)
    try:
        with TestClient(fastapi_app, raise_server_exceptions=False) as c:
            r = c.get("/__boom", headers={"Origin": "https://example.com", "Accept-Language": "en"})
        assert r.status_code == 500 and r.json() == {"detail": "An unexpected server error occurred"}
        assert r.headers["access-control-allow-origin"] == "*"
    finally:
        fastapi_app.router.routes[:] = [rt for rt in fastapi_app.router.routes if getattr(rt, "path", "") != "/__boom"]
