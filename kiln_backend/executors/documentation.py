from __future__ import annotations

import json
from pathlib import Path

from kiln_backend.executors.base import StageExecutionResult, stage_output_paths
from kiln_backend.policy import evaluate_documentation_payload

REQUIRED_FILES = ["README.md"]
RECOMMENDED_FILES = ["MODEL_CARD.md"]
REQUIRED_README_SECTIONS = ["## Usage", "## Limitations", "## Evaluation Summary"]
RECOMMENDED_MODEL_CARD_SECTIONS = ["## Intended Use", "## Limitations", "## Evaluation Data"]


def execute_documentation_stage(*, project_root: Path, run_id: int) -> StageExecutionResult:
    log_path, artifact_path = stage_output_paths(project_root, run_id, "documentation")
    readme_path = project_root / "README.md"
    readme_text = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    model_card_path = project_root / "MODEL_CARD.md"
    model_card_text = model_card_path.read_text(encoding="utf-8") if model_card_path.exists() else ""

    missing_required_files = [
        filename for filename in REQUIRED_FILES if not (project_root / filename).exists()
    ]
    missing_recommended_files = [
        filename for filename in RECOMMENDED_FILES if not (project_root / filename).exists()
    ]
    missing_required_readme_sections = [
        section for section in REQUIRED_README_SECTIONS if section not in readme_text
    ]
    missing_recommended_model_card_sections = [
        section
        for section in RECOMMENDED_MODEL_CARD_SECTIONS
        if model_card_text and section not in model_card_text
    ]

    results = {
        "missing_required_files": missing_required_files,
        "missing_recommended_files": missing_recommended_files,
        "missing_required_readme_sections": missing_required_readme_sections,
        "missing_recommended_model_card_sections": missing_recommended_model_card_sections,
    }
    status = evaluate_documentation_payload(results)
    logs = (
        "Documentation check completed. "
        f"Missing required files: {len(missing_required_files)}. "
        f"Missing required README sections: {len(missing_required_readme_sections)}. "
        f"Missing recommended files: {len(missing_recommended_files)}. "
        f"Missing recommended model card sections: {len(missing_recommended_model_card_sections)}."
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
