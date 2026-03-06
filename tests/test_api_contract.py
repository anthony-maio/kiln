import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_app(tmp_path, monkeypatch, seed_enabled=False):
    db_path = tmp_path / "kiln-test.db"
    monkeypatch.setenv("KILN_DB_PATH", str(db_path))
    if seed_enabled:
        monkeypatch.setenv("KILN_ENABLE_SEED_ENDPOINT", "true")
    else:
        monkeypatch.delenv("KILN_ENABLE_SEED_ENDPOINT", raising=False)
    monkeypatch.delenv("KILN_CORS_ORIGINS", raising=False)

    if "api_server" in sys.modules:
        del sys.modules["api_server"]

    import api_server

    return importlib.reload(api_server)


def create_real_run(client):
    response = client.post("/api/runs", json={"model_id": 1, "mode": "real"})
    assert response.status_code == 201
    return response.json()["id"]


def complete_stage(client, run_id, stage_key, status):
    response = client.post(
        f"/api/runs/{run_id}/stages/{stage_key}/complete",
        json={"status": status, "results": {"stage": stage_key, "status": status}},
    )
    assert response.status_code == 200


def test_create_run_rejects_invalid_mode(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)
    with TestClient(module.app) as client:
        response = client.post("/api/runs", json={"model_id": 1, "mode": "banana"})
        assert response.status_code == 422


def test_complete_stage_rejects_invalid_status(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)
    with TestClient(module.app) as client:
        run_id = create_real_run(client)
        response = client.post(
            f"/api/runs/{run_id}/stages/benchmarks/complete",
            json={"status": "totally_done"},
        )
        assert response.status_code == 422


def test_run_stays_running_while_stages_pending(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)
    with TestClient(module.app) as client:
        run_id = create_real_run(client)
        complete_stage(client, run_id, "benchmarks", "passed")

        run_response = client.get(f"/api/runs/{run_id}")
        assert run_response.status_code == 200
        run = run_response.json()

        assert run["status"] == "running"
        assert any(stage["status"] == "pending" for stage in run["stages"])


def test_create_incident_returns_404_for_missing_model(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)
    with TestClient(module.app) as client:
        response = client.post(
            "/api/incidents",
            json={
                "model_id": 999999,
                "severity": "P1",
                "title": "No model",
            },
        )
        assert response.status_code == 404


def test_create_incident_rejects_invalid_severity(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)
    with TestClient(module.app) as client:
        response = client.post(
            "/api/incidents",
            json={
                "model_id": 1,
                "severity": "SEVERE",
                "title": "Bad severity",
            },
        )
        assert response.status_code == 422


def test_seed_endpoint_forbidden_by_default(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch, seed_enabled=False)
    with TestClient(module.app) as client:
        response = client.post("/api/seed")
        assert response.status_code == 403


def test_seed_endpoint_enabled_by_env(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch, seed_enabled=True)
    with TestClient(module.app) as client:
        response = client.post("/api/seed")
        assert response.status_code == 200
        assert response.json()["status"] == "seeded"


def test_release_report_verdicts_and_markdown_export(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)
    stage_keys = [stage[0] for stage in module.STAGE_DEFINITIONS]

    with TestClient(module.app) as client:
        blocked_run_id = create_real_run(client)
        for key in stage_keys:
            status = "failed" if key == "safety" else "passed"
            complete_stage(client, blocked_run_id, key, status)
        blocked_report = client.get(f"/api/runs/{blocked_run_id}/release-report").json()
        assert blocked_report["verdict"] == "blocked"

        review_run_id = create_real_run(client)
        for key in stage_keys:
            status = "warning" if key == "safety" else "passed"
            complete_stage(client, review_run_id, key, status)
        review_report = client.get(f"/api/runs/{review_run_id}/release-report").json()
        assert review_report["verdict"] == "needs_review"

        ready_run_id = create_real_run(client)
        for key in stage_keys:
            complete_stage(client, ready_run_id, key, "passed")
        ready_report = client.get(f"/api/runs/{ready_run_id}/release-report").json()
        assert ready_report["verdict"] == "ready"

        markdown_response = client.get(
            f"/api/runs/{ready_run_id}/release-report",
            params={"format": "markdown"},
        )
        assert markdown_response.status_code == 200
        assert "text/markdown" in markdown_response.headers["content-type"]
        assert "Verdict: READY" in markdown_response.text


def test_mock_run_uses_only_terminal_stage_statuses(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)
    with TestClient(module.app) as client:
        response = client.post("/api/runs", json={"model_id": 1, "mode": "mock"})
        assert response.status_code == 201

        run_id = response.json()["id"]
        run = client.get(f"/api/runs/{run_id}").json()

        assert run["status"] in ("passed", "failed")
        assert all(stage["status"] in module.TERMINAL_STAGE_STATUSES for stage in run["stages"])
