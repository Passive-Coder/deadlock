from fastapi.testclient import TestClient
import pytest

from deadlock.api import create_app
from deadlock.config import Settings


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, roots=[tmp_path], mediator="disabled"))
    # No lifespan: no discovery or background processes are started by API contract tests.
    yield TestClient(app)
    app.state.runner.analytics.db.close()


def test_local_request_boundary_and_csrf(client):
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/runs", json={}).status_code == 403
    assert (
        client.post(
            "/api/runs", json={}, headers={"X-Deadlock-Control": "1", "Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )
    assert client.get("/api/state", headers={"Host": "evil.invalid"}).status_code == 403
    assert client.post("/api/runs", json={}, headers={"X-Deadlock-Control": "1"}).status_code == 200


def test_operator_endpoints_and_export(client):
    headers = {"X-Deadlock-Control": "1"}
    created = client.post("/api/runs", json={"scenario": "canonical"}, headers=headers).json()
    assert created["status"] == "RUNNING"
    assert client.get("/api/state").json()["run"]["id"] == created["id"]
    assert client.get("/api/runs/export").json()["id"] == created["id"]
    assert "attachment" in client.get("/api/runs/export").headers["content-disposition"]
    assert client.post("/api/runs/stop", json={}, headers=headers).json()["status"] == "CANCELLED"
    assert len(client.get("/api/runs/history").json()) == 1


def test_nonexistent_and_outside_scope_actions_rejected(client):
    headers = {"X-Deadlock-Control": "1"}
    assert (
        client.post(
            "/api/agents", json={"provider": "shell", "cwd": "/tmp", "prompt": "anything"}, headers=headers
        ).status_code
        == 422
    )
    assert client.post("/api/agents/999/control", json={"action": "stop"}, headers=headers).status_code == 409
    assert client.get("/api/runs/anything/artifacts/.env").status_code == 404
    assert client.get("/api/does-not-exist").status_code == 404
