from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, TypedDict


class StageExecutionResult(TypedDict):
    status: str
    payload: dict[str, Any]
    artifact_path: str
    log_path: str
    error: Optional[str]


@dataclass(frozen=True)
class PreparedStageCommand:
    stage_key: str
    command: list[str]
    artifact_path: Path
    log_path: Path

    def command_json(self) -> str:
        return json.dumps(self.command)


def stage_output_paths(project_root: Path, run_id: int, stage_key: str) -> tuple[Path, Path]:
    logs_dir = (project_root / ".kiln" / "logs" / f"run-{run_id}").resolve()
    artifacts_dir = (project_root / ".kiln" / "artifacts" / f"run-{run_id}").resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / f"{stage_key}.log", artifacts_dir / f"{stage_key}.json"


def read_log_tail(log_path: Path, limit: int = 4000) -> str:
    if not log_path.exists():
        return ""
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:]

