from __future__ import annotations

import json
from pathlib import Path

from kiln_backend.executors.base import StageExecutionResult, stage_output_paths
from kiln_backend.models import CandidateConfig
from kiln_backend.policy import evaluate_packaging_payload

RECOMMENDED_FILES = ["LICENSE"]


def resolve_candidate_path(project_root: Path, candidate: CandidateConfig) -> Path:
    candidate_path = Path(candidate.path).expanduser()
    if candidate_path.is_absolute():
        return candidate_path.resolve()
    return (project_root / candidate_path).resolve()


def execute_packaging_stage(
    *,
    project_root: Path,
    run_id: int,
    candidate: CandidateConfig,
) -> StageExecutionResult:
    log_path, artifact_path = stage_output_paths(project_root, run_id, "packaging")
    candidate_path = resolve_candidate_path(project_root, candidate)

    results = {
        "artifact_exists": candidate_path.exists(),
        "candidate_path": str(candidate_path),
        "missing_recommended_files": [
            filename for filename in RECOMMENDED_FILES if not (project_root / filename).exists()
        ],
    }
    status = evaluate_packaging_payload(results)
    logs = "Packaging check completed."

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
