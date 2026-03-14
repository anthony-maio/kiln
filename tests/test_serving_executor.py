import socket
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kiln_backend.executors.serving import execute_serving_stage
from kiln_backend.models import CandidateConfig
from kiln_backend.runtimes import resolve_runtime_for_candidate


def find_free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def build_candidate(*, format="hf", runtime=None):
    return CandidateConfig.model_validate(
        {
            "name": "candidate",
            "format": format,
            "path": "./artifacts/model" if format == "hf" else "./artifacts/model.gguf",
            "runtime": runtime,
            "benchmarks": {
                "provider": "lm_eval",
                "model": "hf",
                "model_args": "pretrained=org/model",
                "tasks": [{"name": "hellaswag", "min_score": 0.75}],
                "device": "cuda:0",
                "num_fewshot": 0,
                "batch_size": "auto",
                "timeout_minutes": 5,
            },
            "serving": {
                "enabled": True,
                "runtime": runtime,
                "model_args": "--dummy",
                "startup_timeout_seconds": 1,
                "smoke_prompts": ["hello"],
                "max_latency_ms": 5000,
            },
        }
    )


def test_resolve_runtime_defaults_hf_to_vllm():
    candidate = build_candidate(format="hf", runtime=None)
    runtime = resolve_runtime_for_candidate(candidate)
    assert runtime.name == "vllm"


def test_resolve_runtime_allows_sglang_override_for_hf():
    candidate = build_candidate(format="hf", runtime="sglang")
    runtime = resolve_runtime_for_candidate(candidate)
    assert runtime.name == "sglang"


def test_invalid_gguf_runtime_override_fails_validation():
    with pytest.raises(ValidationError):
        build_candidate(format="gguf", runtime="vllm")


def test_execute_serving_stage_fails_when_binary_is_missing(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    result = execute_serving_stage(
        project_root=repo_root,
        run_id=11,
        candidate=build_candidate(format="hf"),
        command_override=["definitely_missing_kiln_runtime"],
    )

    assert result["status"] == "failed"
    logs = (result["payload"]["logs"] or "").lower()
    assert "not found" in logs or "cannot find" in logs


def test_execute_serving_stage_fails_on_readiness_timeout(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    port = find_free_port()

    result = execute_serving_stage(
        project_root=repo_root,
        run_id=12,
        candidate=build_candidate(format="hf"),
        port_override=port,
        command_override=[sys.executable, "-c", "import time; time.sleep(5)"],
        readiness_url_override=f"http://127.0.0.1:{port}/",
        smoke_url_override=f"http://127.0.0.1:{port}/",
    )

    assert result["status"] == "failed"
    assert "timed out" in (result["payload"]["logs"] or "").lower()


def test_execute_serving_stage_passes_with_http_server_probe(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    port = find_free_port()

    result = execute_serving_stage(
        project_root=repo_root,
        run_id=13,
        candidate=build_candidate(format="hf"),
        port_override=port,
        command_override=[
            sys.executable,
            "-m",
            "http.server",
            str(port),
            "--bind",
            "127.0.0.1",
        ],
        readiness_url_override=f"http://127.0.0.1:{port}/",
        smoke_url_override=f"http://127.0.0.1:{port}/",
    )

    assert result["status"] == "passed"
    assert Path(result["artifact_path"]).exists()
    assert Path(result["log_path"]).exists()
