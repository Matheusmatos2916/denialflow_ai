from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from denialflow_ai.api.auth import create_access_token
from denialflow_ai.api.app import create_app
from denialflow_ai.core.config import reset_settings_cache


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db = tmp_path / "auth_test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    monkeypatch.setenv("JWT_AUTH_ENABLED", "true")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-jwt")
    monkeypatch.setenv("API_ACCESS_TOKEN", "static-test-token")
    monkeypatch.setenv("AGENTOPS_API_KEY", "")
    monkeypatch.setenv("AGENTOPS_ENABLED", "false")
    reset_settings_cache()
    with TestClient(create_app()) as c:
        yield c
    reset_settings_cache()


def test_health_public(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_protected_without_token(client: TestClient):
    r = client.get("/v1/metrics/dashboard")
    assert r.status_code == 401


def test_protected_with_static_token(client: TestClient):
    r = client.get(
        "/v1/metrics/dashboard",
        headers={"Authorization": "Bearer static-test-token"},
    )
    assert r.status_code == 200


def test_protected_with_jwt(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db = tmp_path / "jwt_only.db"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    monkeypatch.setenv("JWT_AUTH_ENABLED", "true")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-jwt")
    monkeypatch.setenv("API_ACCESS_TOKEN", "")
    monkeypatch.setenv("AGENTOPS_ENABLED", "false")
    reset_settings_cache()
    token = create_access_token(subject="pytest")
    with TestClient(create_app()) as c:
        r = c.get(
            "/v1/metrics/dashboard",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
    reset_settings_cache()


def test_invalid_token(client: TestClient):
    r = client.get(
        "/v1/metrics/dashboard",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert r.status_code == 401


def test_auth_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db = tmp_path / "auth_off.db"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    monkeypatch.setenv("JWT_AUTH_ENABLED", "false")
    monkeypatch.setenv("API_ACCESS_TOKEN", "")
    monkeypatch.setenv("JWT_SECRET", "")
    monkeypatch.setenv("AGENTOPS_ENABLED", "false")
    reset_settings_cache()
    with TestClient(create_app()) as c:
        r = c.get("/v1/metrics/dashboard")
        assert r.status_code == 200
    reset_settings_cache()


def test_startup_fails_without_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_ACCESS_TOKEN", "")
    monkeypatch.setenv("JWT_SECRET", "")
    reset_settings_cache()
    from denialflow_ai.core.config import get_settings

    with pytest.raises(ValueError, match="API_ACCESS_TOKEN"):
        get_settings().validate_auth_config()
    reset_settings_cache()
