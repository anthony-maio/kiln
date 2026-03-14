import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kiln_backend.executors.benchmarks import execute_benchmark_stage
from kiln_backend.models import CandidateBenchmarksConfig
from kiln_backend.policy import evaluate_benchmark_payload


def build_benchmarks_config(min_score=0.75):
    return CandidateBenchmarksConfig.model_validate(
        {
            "provider": "lm_eval",
            "model": "hf",
            "model_args": "pretrained=org/model",
            "tasks": [
                {"name": "hellaswag", "min_score": min_score},
            ],
            "device": "cuda:0",
            "num_fewshot": 0,
            "batch_size": "auto",
            "timeout_minutes": 5,
        }
    )


def test_execute_benchmark_stage_writes_artifact_and_log(tmp_path, monkeypatch):
    monkeypatch.setenv("KILN_LM_EVAL_DRY_RUN", "true")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    result = execute_benchmark_stage(
        project_root=repo_root,
        run_id=7,
        model_id="org/model",
        benchmarks_config=build_benchmarks_config(),
    )

    artifact_path = Path(result["artifact_path"])
    log_path = Path(result["log_path"])

    assert result["status"] == "passed"
    assert artifact_path.exists()
    assert log_path.exists()

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["results"]["benchmarks"][0]["name"] == "hellaswag"


def test_evaluate_benchmark_payload_marks_threshold_failures():
    status, payload = evaluate_benchmark_payload(
        build_benchmarks_config(min_score=0.75),
        {
            "benchmarks": [
                {"name": "hellaswag", "score": 70.0},
            ],
            "tool": "lm-eval-harness",
        },
    )

    assert status == "failed"
    assert payload["benchmarks"][0]["status"] == "fail"
    assert payload["benchmarks"][0]["target_min"] == 75.0
