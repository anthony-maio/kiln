import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kiln_backend.executors.packaging import execute_packaging_stage
from kiln_backend.models import CandidateConfig


def build_candidate(*, format="hf", path="./artifacts/model"):
    return CandidateConfig.model_validate(
        {
            "name": "candidate",
            "format": format,
            "path": path,
            "runtime": "vllm" if format == "hf" else "llama_cpp",
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
                "runtime": "vllm" if format == "hf" else "llama_cpp",
                "model_args": "--dummy",
                "startup_timeout_seconds": 30,
                "smoke_prompts": ["hello"],
                "max_latency_ms": 5000,
            },
        }
    )


def test_execute_packaging_stage_fails_when_candidate_artifact_is_missing(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    result = execute_packaging_stage(
        project_root=repo_root,
        run_id=31,
        candidate=build_candidate(format="hf"),
    )

    assert result["status"] == "failed"
    payload = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert payload["results"]["artifact_exists"] is False


def test_execute_packaging_stage_fails_when_hf_candidate_is_missing_core_files(tmp_path):
    repo_root = tmp_path / "repo"
    artifact_dir = repo_root / "artifacts" / "model"
    artifact_dir.mkdir(parents=True)
    (repo_root / "LICENSE").write_text("MIT", encoding="utf-8")

    result = execute_packaging_stage(
        project_root=repo_root,
        run_id=32,
        candidate=build_candidate(format="hf"),
    )

    assert result["status"] == "failed"
    payload = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert "config.json" in payload["results"]["missing_required_files"]
    assert "weights" in payload["results"]["missing_required_files"]

def test_execute_packaging_stage_warns_when_hf_candidate_is_missing_tokenizer_assets(tmp_path):
    repo_root = tmp_path / "repo"
    artifact_dir = repo_root / "artifacts" / "model"
    artifact_dir.mkdir(parents=True)
    (repo_root / "LICENSE").write_text("MIT", encoding="utf-8")
    (artifact_dir / "config.json").write_text("{}", encoding="utf-8")
    (artifact_dir / "model.safetensors").write_text("weights", encoding="utf-8")

    result = execute_packaging_stage(
        project_root=repo_root,
        run_id=33,
        candidate=build_candidate(format="hf"),
    )

    assert result["status"] == "warning"
    payload = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert "tokenizer assets" in payload["results"]["missing_recommended_files"]


def test_execute_packaging_stage_passes_with_release_ready_hf_artifact(tmp_path):
    repo_root = tmp_path / "repo"
    artifact_dir = repo_root / "artifacts" / "model"
    artifact_dir.mkdir(parents=True)
    (repo_root / "LICENSE").write_text("MIT", encoding="utf-8")
    (artifact_dir / "config.json").write_text("{}", encoding="utf-8")
    (artifact_dir / "model.safetensors").write_text("weights", encoding="utf-8")
    (artifact_dir / "tokenizer.json").write_text("{}", encoding="utf-8")

    result = execute_packaging_stage(
        project_root=repo_root,
        run_id=34,
        candidate=build_candidate(format="hf"),
    )

    assert result["status"] == "passed"
    assert Path(result["artifact_path"]).exists()
    assert Path(result["log_path"]).exists()


def test_execute_packaging_stage_passes_with_release_ready_gguf_artifact(tmp_path):
    repo_root = tmp_path / "repo"
    artifact_file = repo_root / "artifacts" / "model.gguf"
    artifact_file.parent.mkdir(parents=True)
    artifact_file.write_text("gguf payload", encoding="utf-8")
    (repo_root / "LICENSE").write_text("MIT", encoding="utf-8")

    result = execute_packaging_stage(
        project_root=repo_root,
        run_id=35,
        candidate=build_candidate(format="gguf", path="./artifacts/model.gguf"),
    )

    assert result["status"] == "passed"
    payload = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert payload["results"]["artifact_kind"] == "gguf_file"
