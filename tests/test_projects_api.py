import importlib
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_app(
    tmp_path,
    monkeypatch,
    *,
    seed_enabled=False,
    adapter_dry_run=False,
    adapter_dry_run_delay_seconds=None,
    adapter_force_failure=False,
):
    db_path = tmp_path / "kiln-test.db"
    monkeypatch.setenv("KILN_DB_PATH", str(db_path))
    monkeypatch.delenv("KILN_CORS_ORIGINS", raising=False)

    if seed_enabled:
        monkeypatch.setenv("KILN_ENABLE_SEED_ENDPOINT", "true")
    else:
        monkeypatch.delenv("KILN_ENABLE_SEED_ENDPOINT", raising=False)

    if adapter_dry_run:
        monkeypatch.setenv("KILN_LM_EVAL_DRY_RUN", "true")
    else:
        monkeypatch.delenv("KILN_LM_EVAL_DRY_RUN", raising=False)

    if adapter_dry_run_delay_seconds is not None:
        monkeypatch.setenv(
            "KILN_LM_EVAL_DRY_RUN_SLEEP_SECONDS",
            str(adapter_dry_run_delay_seconds),
        )
    else:
        monkeypatch.delenv("KILN_LM_EVAL_DRY_RUN_SLEEP_SECONDS", raising=False)

    if adapter_force_failure:
        monkeypatch.setenv("KILN_LM_EVAL_FORCE_FAILURE", "true")
    else:
        monkeypatch.delenv("KILN_LM_EVAL_FORCE_FAILURE", raising=False)

    if "api_server" in sys.modules:
        del sys.modules["api_server"]

    import api_server

    return importlib.reload(api_server)


def wait_for_job_completion(client, job_id, timeout_seconds=10):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in ("completed", "failed", "canceled"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"Job {job_id} did not complete in time")


def wait_for_run_jobs_terminal(client, run_id, expected_count, timeout_seconds=15):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        jobs = [job for job in client.get("/api/jobs").json() if job["run_id"] == run_id]
        if len(jobs) >= expected_count and all(
            job["status"] in ("completed", "failed", "canceled") for job in jobs
        ):
            return jobs
        time.sleep(0.1)
    raise AssertionError(f"Run {run_id} jobs did not reach terminal state in time")


def build_valid_config(model_name="Workspace Model", repo_id="org/workspace-model"):
    return {
        "version": 1,
        "model": {
            "name": model_name,
            "repo_id": repo_id,
            "parameters": "7B",
            "architecture": "Mistral",
            "description": "Config-managed model",
        },
        "benchmarks": {
            "provider": "lm_eval",
            "model": "hf",
            "model_args": f"pretrained={repo_id}",
            "tasks": [
                {"name": "hellaswag", "min_score": 0.75},
                {"name": "arc_easy", "min_score": 0.70},
            ],
            "device": "cuda:0",
            "num_fewshot": 0,
            "batch_size": "auto",
            "timeout_minutes": 5,
        },
        "manual_stages": {
            "safety": "required",
            "documentation": "required",
            "packaging": "required",
            "serving": "skip",
            "monitoring": "skip",
            "incidents": "skip",
            "improvement": "skip",
        },
        "report": {
            "output_dir": ".kiln/reports",
        },
    }


def build_candidate_config(
    model_name="Workspace Model",
    repo_id="org/workspace-model",
):
    return {
        "version": 2,
        "model": {
            "name": model_name,
            "repo_id": repo_id,
            "parameters": "7B",
            "architecture": "Mistral",
            "description": "Config-managed model",
        },
        "candidates": [
            {
                "name": "base-hf",
                "format": "hf",
                "path": "./artifacts/base-hf",
                "runtime": "vllm",
                "benchmarks": {
                    "provider": "lm_eval",
                    "model": "hf",
                    "model_args": f"pretrained={repo_id}",
                    "tasks": [
                        {"name": "hellaswag", "min_score": 0.75},
                        {"name": "arc_easy", "min_score": 0.70},
                    ],
                    "device": "cuda:0",
                    "num_fewshot": 0,
                    "batch_size": "auto",
                    "timeout_minutes": 5,
                },
                "serving": {
                    "enabled": True,
                    "runtime": "vllm",
                    "model_args": f"--model {repo_id}",
                    "startup_timeout_seconds": 120,
                    "smoke_prompts": ["Say hello."],
                    "max_latency_ms": 5000,
                },
            },
            {
                "name": "q4-gguf",
                "format": "gguf",
                "path": "./artifacts/q4.gguf",
                "runtime": "llama_cpp",
                "benchmarks": {
                    "provider": "lm_eval",
                    "model": "hf",
                    "model_args": f"pretrained={repo_id}",
                    "tasks": [
                        {"name": "hellaswag", "min_score": 0.70},
                    ],
                    "device": "cuda:0",
                    "num_fewshot": 0,
                    "batch_size": "auto",
                    "timeout_minutes": 5,
                },
                "serving": {
                    "enabled": True,
                    "runtime": "llama_cpp",
                    "model_args": "--ctx-size 4096",
                    "startup_timeout_seconds": 120,
                    "smoke_prompts": ["Say hello."],
                    "max_latency_ms": 5000,
                },
            },
        ],
        "report": {
            "output_dir": ".kiln/reports",
        },
    }


def create_project(client, root_path):
    response = client.post("/api/projects", json={"root_path": str(root_path)})
    assert response.status_code == 201
    return response.json()


def materialize_candidate_paths(repo_root, payload):
    for candidate in payload.get("candidates", []):
        candidate_path = (repo_root / candidate["path"]).resolve()
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        if candidate["format"] == "hf":
            candidate_path.mkdir(parents=True, exist_ok=True)
        else:
            candidate_path.write_text("fake gguf payload", encoding="utf-8")


def test_v01_db_migrates_and_legacy_runs_still_load(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)

    with TestClient(module.app) as client:
        runs_response = client.get("/api/runs")
        assert runs_response.status_code == 200
        runs = runs_response.json()
        assert runs

        db = module.get_db()
        try:
            tables = {
                row["name"]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "projects" in tables
            assert "jobs" in tables

            run_columns = {
                row["name"]
                for row in db.execute("PRAGMA table_info(pipeline_runs)").fetchall()
            }
            assert "project_id" in run_columns
        finally:
            db.close()


def test_create_project_scaffolds_config_and_links_model(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)
    repo_root = tmp_path / "demo-repo"
    repo_root.mkdir()

    with TestClient(module.app) as client:
        project = create_project(client, repo_root)
        assert project["name"] == "demo-repo"
        assert project["config_status"] == "valid"
        assert project["model"]["name"] == "demo-repo"
        assert Path(project["config_path"]).exists()
        assert "version: 1" in Path(project["config_path"]).read_text(encoding="utf-8")


def test_put_project_config_rejects_unknown_top_level_key(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)
    repo_root = tmp_path / "strict-config-repo"
    repo_root.mkdir()

    with TestClient(module.app) as client:
        project = create_project(client, repo_root)
        payload = build_valid_config()
        payload["unexpected"] = True

        response = client.put(f"/api/projects/{project['id']}/config", json=payload)
        assert response.status_code == 422


def test_put_project_config_writes_yaml_and_updates_model(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)
    repo_root = tmp_path / "write-config-repo"
    repo_root.mkdir()

    with TestClient(module.app) as client:
        project = create_project(client, repo_root)
        payload = build_valid_config(
            model_name="Config Driven Model",
            repo_id="anthony-maio/config-driven-model",
        )

        response = client.put(f"/api/projects/{project['id']}/config", json=payload)
        assert response.status_code == 200
        updated = response.json()

        assert updated["config_status"] == "valid"
        assert updated["model"]["name"] == "Config Driven Model"

        config_path = Path(updated["config_path"])
        config_text = config_path.read_text(encoding="utf-8")
        assert "Config Driven Model" in config_text
        assert "anthony-maio/config-driven-model" in config_text


def test_put_project_config_accepts_candidate_aware_schema(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)
    repo_root = tmp_path / "candidate-config-repo"
    repo_root.mkdir()

    with TestClient(module.app) as client:
        project = create_project(client, repo_root)
        payload = build_candidate_config(
            model_name="Candidate Model",
            repo_id="anthony-maio/candidate-model",
        )

        response = client.put(f"/api/projects/{project['id']}/config", json=payload)

        assert response.status_code == 200
        updated = response.json()
        assert updated["config"]["version"] == 2
        assert len(updated["config"]["candidates"]) == 2


def test_put_project_config_rejects_v2_without_candidates(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)
    repo_root = tmp_path / "missing-candidates-repo"
    repo_root.mkdir()

    with TestClient(module.app) as client:
        project = create_project(client, repo_root)
        payload = build_candidate_config()
        payload["candidates"] = []

        response = client.put(f"/api/projects/{project['id']}/config", json=payload)

        assert response.status_code == 422


def test_put_project_config_rejects_unknown_candidate_format(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)
    repo_root = tmp_path / "bad-format-repo"
    repo_root.mkdir()

    with TestClient(module.app) as client:
        project = create_project(client, repo_root)
        payload = build_candidate_config()
        payload["candidates"][0]["format"] = "onnx"

        response = client.put(f"/api/projects/{project['id']}/config", json=payload)

        assert response.status_code == 422


def test_put_project_config_rejects_invalid_runtime_override_for_format(
    tmp_path, monkeypatch
):
    module = load_app(tmp_path, monkeypatch)
    repo_root = tmp_path / "bad-runtime-repo"
    repo_root.mkdir()

    with TestClient(module.app) as client:
        project = create_project(client, repo_root)
        payload = build_candidate_config()
        payload["candidates"][1]["runtime"] = "vllm"

        response = client.put(f"/api/projects/{project['id']}/config", json=payload)

        assert response.status_code == 422


def test_project_run_requires_candidate_name_for_v2_config(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)
    repo_root = tmp_path / "candidate-run-required-repo"
    repo_root.mkdir()

    with TestClient(module.app) as client:
        project = create_project(client, repo_root)
        payload = build_candidate_config()
        materialize_candidate_paths(repo_root, payload)
        config_response = client.put(
            f"/api/projects/{project['id']}/config",
            json=payload,
        )
        assert config_response.status_code == 200

        response = client.post(f"/api/projects/{project['id']}/runs")

        assert response.status_code == 422


def test_project_run_snapshots_candidate_metadata(tmp_path, monkeypatch):
    module = load_app(tmp_path, monkeypatch)
    repo_root = tmp_path / "candidate-snapshot-repo"
    repo_root.mkdir()

    with TestClient(module.app) as client:
        project = create_project(client, repo_root)
        payload = build_candidate_config(
            model_name="Snapshot Model",
            repo_id="anthony-maio/snapshot-model",
        )
        materialize_candidate_paths(repo_root, payload)
        config_response = client.put(
            f"/api/projects/{project['id']}/config",
            json=payload,
        )
        assert config_response.status_code == 200

        response = client.post(
            f"/api/projects/{project['id']}/runs",
            json={"candidate_name": "q4-gguf"},
        )

        assert response.status_code == 201
        run = response.json()["run"]
        assert run["candidate_name"] == "q4-gguf"
        assert run["candidate_format"] == "gguf"
        assert run["resolved_runtime"] == "llama_cpp"
        assert run["candidate_path"].endswith("artifacts\\q4.gguf")


def test_project_run_rejects_missing_candidate_artifact_before_queueing(
    tmp_path, monkeypatch
):
    module = load_app(tmp_path, monkeypatch)
    repo_root = tmp_path / "candidate-missing-path-repo"
    repo_root.mkdir()

    with TestClient(module.app) as client:
        project = create_project(client, repo_root)
        payload = build_candidate_config()
        config_response = client.put(
            f"/api/projects/{project['id']}/config",
            json=payload,
        )
        assert config_response.status_code == 200

        response = client.post(
            f"/api/projects/{project['id']}/runs",
            json={"candidate_name": "base-hf"},
        )

        assert response.status_code == 422
        jobs = client.get("/api/jobs").json()
        assert jobs == []


def test_project_run_creates_job_writes_reports_and_keeps_required_manual_stages_pending(
    tmp_path, monkeypatch
):
    module = load_app(tmp_path, monkeypatch, adapter_dry_run=True)
    repo_root = tmp_path / "project-run-repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# Demo\n\n## Usage\nRun it.\n\n## Limitations\nStill early.\n",
        encoding="utf-8",
    )
    (repo_root / "MODEL_CARD.md").write_text("# Model Card\n", encoding="utf-8")
    (repo_root / "LICENSE").write_text("MIT", encoding="utf-8")

    with TestClient(module.app) as client:
        project = create_project(client, repo_root)
        config_response = client.put(
            f"/api/projects/{project['id']}/config",
            json=build_valid_config(),
        )
        assert config_response.status_code == 200

        response = client.post(f"/api/projects/{project['id']}/runs")
        assert response.status_code == 201
        payload = response.json()

        run_id = payload["run"]["id"]
        jobs = wait_for_run_jobs_terminal(client, run_id, expected_count=2)
        assert {job["job_type"] for job in jobs} == {"benchmarks", "documentation"}

        run_response = client.get(f"/api/runs/{run_id}")
        assert run_response.status_code == 200
        run = run_response.json()
        stages = {stage["stage_key"]: stage for stage in run["stages"]}

        assert [stage["stage_key"] for stage in run["stages"]] == [
            "benchmarks",
            "safety",
            "documentation",
            "packaging",
            "serving",
        ]
        assert run["status"] == "running"
        assert stages["benchmarks"]["status"] == "passed"
        assert stages["documentation"]["status"] == "passed"
        assert stages["safety"]["status"] == "pending"
        assert stages["packaging"]["status"] == "skipped"
        assert stages["serving"]["status"] == "skipped"

        export_response = client.post(f"/api/runs/{run_id}/export-report")
        assert export_response.status_code == 200
        artifact_paths = export_response.json()["artifacts"]
        assert Path(artifact_paths["markdown"]).exists()
        assert Path(artifact_paths["json"]).exists()


def test_v2_project_run_automates_docs_and_packaging_and_skips_disabled_serving(
    tmp_path, monkeypatch
):
    module = load_app(tmp_path, monkeypatch, adapter_dry_run=True)
    repo_root = tmp_path / "candidate-pipeline-repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# Demo\n\n## Usage\nRun it.\n\n## Limitations\nStill early.\n",
        encoding="utf-8",
    )
    (repo_root / "MODEL_CARD.md").write_text("# Model Card\n", encoding="utf-8")
    (repo_root / "LICENSE").write_text("MIT", encoding="utf-8")

    with TestClient(module.app) as client:
        project = create_project(client, repo_root)
        payload = build_candidate_config()
        payload["candidates"][0]["serving"]["enabled"] = False
        materialize_candidate_paths(repo_root, payload)
        config_response = client.put(
            f"/api/projects/{project['id']}/config",
            json=payload,
        )
        assert config_response.status_code == 200

        response = client.post(
            f"/api/projects/{project['id']}/runs",
            json={"candidate_name": "base-hf"},
        )
        assert response.status_code == 201
        run_id = response.json()["run"]["id"]

        jobs = wait_for_run_jobs_terminal(client, run_id, expected_count=3)
        assert {job["job_type"] for job in jobs} == {"benchmarks", "documentation", "packaging"}

        run = client.get(f"/api/runs/{run_id}").json()
        stages = {stage["stage_key"]: stage for stage in run["stages"]}

        assert [stage["stage_key"] for stage in run["stages"]] == [
            "benchmarks",
            "safety",
            "documentation",
            "packaging",
            "serving",
        ]
        assert stages["benchmarks"]["status"] == "passed"
        assert stages["documentation"]["status"] == "passed"
        assert stages["packaging"]["status"] == "passed"
        assert stages["safety"]["status"] == "pending"
        assert stages["serving"]["status"] == "skipped"


def test_v2_project_run_defaults_serving_required_when_candidate_enabled(
    tmp_path, monkeypatch
):
    module = load_app(
        tmp_path,
        monkeypatch,
        adapter_dry_run=True,
        adapter_dry_run_delay_seconds=2,
    )
    repo_root = tmp_path / "candidate-serving-default-repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# Demo\n\n## Usage\nRun it.\n\n## Limitations\nStill early.\n",
        encoding="utf-8",
    )
    (repo_root / "MODEL_CARD.md").write_text("# Model Card\n", encoding="utf-8")
    (repo_root / "LICENSE").write_text("MIT", encoding="utf-8")

    with TestClient(module.app) as client:
        project = create_project(client, repo_root)
        payload = build_candidate_config()
        materialize_candidate_paths(repo_root, payload)
        config_response = client.put(
            f"/api/projects/{project['id']}/config",
            json=payload,
        )
        assert config_response.status_code == 200

        response = client.post(
            f"/api/projects/{project['id']}/runs",
            json={"candidate_name": "base-hf"},
        )
        assert response.status_code == 201

        run = response.json()["run"]
        stages = {stage["stage_key"]: stage for stage in run["stages"]}
        assert stages["serving"]["status"] == "pending"

        jobs = [job for job in client.get("/api/jobs").json() if job["run_id"] == run["id"]]
        assert {job["job_type"] for job in jobs} == {
            "benchmarks",
            "documentation",
            "packaging",
            "serving",
        }


def test_job_queue_runs_single_worker(tmp_path, monkeypatch):
    module = load_app(
        tmp_path,
        monkeypatch,
        adapter_dry_run=True,
        adapter_dry_run_delay_seconds=1.5,
    )
    repo_one = tmp_path / "queue-repo-one"
    repo_two = tmp_path / "queue-repo-two"
    repo_one.mkdir()
    repo_two.mkdir()

    with TestClient(module.app) as client:
        project_one = create_project(client, repo_one)
        project_two = create_project(client, repo_two)
        client.put(
            f"/api/projects/{project_one['id']}/config",
            json=build_valid_config(model_name="Queue One", repo_id="org/queue-one"),
        )
        client.put(
            f"/api/projects/{project_two['id']}/config",
            json=build_valid_config(model_name="Queue Two", repo_id="org/queue-two"),
        )

        first = client.post(f"/api/projects/{project_one['id']}/runs")
        second = client.post(f"/api/projects/{project_two['id']}/runs")
        assert first.status_code == 201
        assert second.status_code == 201

        second_job_id = second.json()["job"]["id"]
        second_job = client.get(f"/api/jobs/{second_job_id}").json()
        assert second_job["status"] == "queued"


def test_adapter_failure_marks_job_and_benchmark_stage_failed(tmp_path, monkeypatch):
    module = load_app(
        tmp_path,
        monkeypatch,
        adapter_dry_run=True,
        adapter_force_failure=True,
    )
    repo_root = tmp_path / "failure-repo"
    repo_root.mkdir()

    with TestClient(module.app) as client:
        project = create_project(client, repo_root)
        client.put(
            f"/api/projects/{project['id']}/config",
            json=build_valid_config(model_name="Failure Model", repo_id="org/failure"),
        )

        response = client.post(f"/api/projects/{project['id']}/runs")
        assert response.status_code == 201
        payload = response.json()
        job = wait_for_job_completion(client, payload["job"]["id"])

        assert job["status"] == "failed"

        run = client.get(f"/api/runs/{payload['run']['id']}").json()
        benchmarks_stage = next(
            stage for stage in run["stages"] if stage["stage_key"] == "benchmarks"
        )
        assert benchmarks_stage["status"] == "failed"


def test_cancel_running_job_marks_job_canceled_and_stage_warning(tmp_path, monkeypatch):
    module = load_app(
        tmp_path,
        monkeypatch,
        adapter_dry_run=True,
        adapter_dry_run_delay_seconds=5,
    )
    repo_root = tmp_path / "cancel-repo"
    repo_root.mkdir()

    with TestClient(module.app) as client:
        project = create_project(client, repo_root)
        client.put(
            f"/api/projects/{project['id']}/config",
            json=build_valid_config(model_name="Cancel Model", repo_id="org/cancel"),
        )

        response = client.post(f"/api/projects/{project['id']}/runs")
        assert response.status_code == 201
        payload = response.json()

        deadline = time.time() + 5
        current_job = None
        while time.time() < deadline:
            current_job = client.get(f"/api/jobs/{payload['job']['id']}").json()
            if current_job["status"] == "running":
                break
            time.sleep(0.1)

        assert current_job["status"] == "running"

        cancel_response = client.post(f"/api/jobs/{payload['job']['id']}/cancel")
        assert cancel_response.status_code == 200

        final_job = wait_for_job_completion(client, payload["job"]["id"])
        assert final_job["status"] == "canceled"

        run = client.get(f"/api/runs/{payload['run']['id']}").json()
        benchmarks_stage = next(
            stage for stage in run["stages"] if stage["stage_key"] == "benchmarks"
        )
        assert benchmarks_stage["status"] == "warning"

