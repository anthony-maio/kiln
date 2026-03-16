from __future__ import annotations

import json
from pathlib import Path

from kiln_backend.executors.base import StageExecutionResult, stage_output_paths
from kiln_backend.models import CandidateConfig
from kiln_backend.policy import evaluate_packaging_payload

RECOMMENDED_FILES = ["LICENSE"]
HF_REQUIRED_FILES = ["config.json"]
HF_WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth", ".ckpt")
HF_TOKENIZER_FILES = ("tokenizer.json", "tokenizer.model")
HF_TOKENIZER_FILE_SETS = (("vocab.json", "merges.txt"),)


def resolve_candidate_path(project_root: Path, candidate: CandidateConfig) -> Path:
    candidate_path = Path(candidate.path).expanduser()
    if candidate_path.is_absolute():
        return candidate_path.resolve()
    return (project_root / candidate_path).resolve()


def hf_packaging_results(candidate_path: Path) -> dict:
    required_missing: list[str] = []
    recommended_missing: list[str] = []

    if not candidate_path.exists():
        return {
            "artifact_exists": False,
            "artifact_kind": "missing",
            "missing_required_files": ["candidate artifact directory"],
            "missing_recommended_files": [],
        }

    if not candidate_path.is_dir():
        return {
            "artifact_exists": True,
            "artifact_kind": "invalid",
            "missing_required_files": ["candidate artifact directory"],
            "missing_recommended_files": [],
        }

    for filename in HF_REQUIRED_FILES:
        if not (candidate_path / filename).exists():
            required_missing.append(filename)

    if not any(
        child.is_file() and child.suffix.lower() in HF_WEIGHT_SUFFIXES
        for child in candidate_path.iterdir()
    ):
        required_missing.append("weights")

    has_tokenizer_file = any((candidate_path / name).exists() for name in HF_TOKENIZER_FILES)
    has_tokenizer_pair = any(
        all((candidate_path / filename).exists() for filename in file_set)
        for file_set in HF_TOKENIZER_FILE_SETS
    )
    if not has_tokenizer_file and not has_tokenizer_pair:
        recommended_missing.append("tokenizer assets")

    return {
        "artifact_exists": True,
        "artifact_kind": "hf_directory",
        "missing_required_files": required_missing,
        "missing_recommended_files": recommended_missing,
    }


def gguf_packaging_results(candidate_path: Path) -> dict:
    if not candidate_path.exists():
        return {
            "artifact_exists": False,
            "artifact_kind": "missing",
            "missing_required_files": ["GGUF artifact"],
            "missing_recommended_files": [],
        }

    if candidate_path.is_file():
        missing_required = [] if candidate_path.suffix.lower() == ".gguf" else ["GGUF artifact"]
        return {
            "artifact_exists": True,
            "artifact_kind": "gguf_file",
            "missing_required_files": missing_required,
            "missing_recommended_files": [],
        }

    gguf_files = [child.name for child in candidate_path.glob("*.gguf") if child.is_file()]
    return {
        "artifact_exists": True,
        "artifact_kind": "gguf_directory",
        "missing_required_files": [] if gguf_files else ["GGUF artifact"],
        "missing_recommended_files": [],
        "gguf_files": gguf_files,
    }


def execute_packaging_stage(
    *,
    project_root: Path,
    run_id: int,
    candidate: CandidateConfig,
) -> StageExecutionResult:
    log_path, artifact_path = stage_output_paths(project_root, run_id, "packaging")
    candidate_path = resolve_candidate_path(project_root, candidate)

    results = (
        hf_packaging_results(candidate_path)
        if candidate.format == "hf"
        else gguf_packaging_results(candidate_path)
    )
    results["candidate_path"] = str(candidate_path)
    results["candidate_format"] = candidate.format
    results["missing_recommended_files"].extend(
        filename for filename in RECOMMENDED_FILES if not (project_root / filename).exists()
    )
    status = evaluate_packaging_payload(results)
    logs = (
        "Packaging check completed. "
        f"Artifact kind: {results['artifact_kind']}. "
        f"Missing required files: {len(results['missing_required_files'])}. "
        f"Missing recommended files: {len(results['missing_recommended_files'])}."
    )

    artifact_payload = {
        "status": status,
        "results": results,
        "logs": logs,
    }
    artifact_path.write_text(json.dumps(artifact_payload, indent=2), encoding="utf-8")
    log_path.write_text(logs, encoding="utf-8")

    return {
        "status": status,
        "payload": artifact_payload,
        "artifact_path": str(artifact_path),
        "log_path": str(log_path),
        "error": None,
    }
