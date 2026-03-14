from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from kiln_backend.executors.base import (
    PreparedStageCommand,
    StageExecutionResult,
    read_log_tail,
    stage_output_paths,
)
from kiln_backend.models import CandidateBenchmarksConfig, ROOT_DIR


def prepare_benchmark_stage(
    *,
    project_root: Path,
    run_id: int,
    model_id: str,
    benchmarks_config: CandidateBenchmarksConfig,
) -> PreparedStageCommand:
    log_path, artifact_path = stage_output_paths(project_root, run_id, "benchmarks")
    eval_dir = (project_root / ".kiln" / "eval_results" / f"run-{run_id}").resolve()
    eval_dir.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        str(ROOT_DIR / "adapters" / "lm_eval_adapter.py"),
        "--model-id",
        model_id,
        "--tasks",
        ",".join(task.name for task in benchmarks_config.tasks),
        "--output-dir",
        str(eval_dir),
        "--result-json",
        str(artifact_path),
        "--model",
        benchmarks_config.model,
        "--model-args",
        benchmarks_config.model_args,
        "--batch-size",
        benchmarks_config.batch_size,
        "--num-fewshot",
        str(benchmarks_config.num_fewshot),
    ]
    if benchmarks_config.device:
        command.extend(["--device", benchmarks_config.device])

    return PreparedStageCommand(
        stage_key="benchmarks",
        command=command,
        artifact_path=artifact_path,
        log_path=log_path,
    )


def finalize_benchmark_stage(
    prepared: PreparedStageCommand,
    return_code: int,
    *,
    error_message: str | None = None,
) -> StageExecutionResult:
    log_tail = read_log_tail(prepared.log_path)

    if prepared.artifact_path.exists():
        payload = json.loads(prepared.artifact_path.read_text(encoding="utf-8"))
    else:
        payload = {
            "status": "failed",
            "results": {"tool": "lm-eval-harness", "benchmarks": []},
            "logs": error_message or log_tail or "Benchmark executor did not produce a payload.",
        }
        prepared.artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if return_code != 0:
        payload["status"] = "failed"
        payload["logs"] = error_message or payload.get("logs") or log_tail
        prepared.artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    elif not payload.get("logs"):
        payload["logs"] = log_tail
        prepared.artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return {
        "status": payload.get("status", "failed"),
        "payload": payload,
        "artifact_path": str(prepared.artifact_path),
        "log_path": str(prepared.log_path),
        "error": error_message if return_code != 0 else None,
    }


def execute_benchmark_stage(
    *,
    project_root: Path,
    run_id: int,
    model_id: str,
    benchmarks_config: CandidateBenchmarksConfig,
) -> StageExecutionResult:
    prepared = prepare_benchmark_stage(
        project_root=project_root,
        run_id=run_id,
        model_id=model_id,
        benchmarks_config=benchmarks_config,
    )
    env = os.environ.copy()
    with prepared.log_path.open("a", encoding="utf-8") as handle:
        completed = subprocess.run(
            prepared.command,
            cwd=ROOT_DIR,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    return finalize_benchmark_stage(prepared, completed.returncode)

