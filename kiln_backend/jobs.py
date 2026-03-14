from __future__ import annotations

import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Optional

from kiln_backend.executors.benchmarks import finalize_benchmark_stage, prepare_benchmark_stage
from kiln_backend.executors.documentation import execute_documentation_stage
from kiln_backend.executors.packaging import execute_packaging_stage
from kiln_backend.executors.safety import execute_safety_stage
from kiln_backend.executors.serving import execute_serving_stage
from kiln_backend.storage import (
    apply_stage_completion,
    benchmark_config_for_run,
    get_candidate_from_config,
    get_db,
    get_project_config_for_project,
    mark_stage_running,
    row_to_dict,
    update_job_status,
    utc_now_iso,
)


class JobRunner:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._pending: deque[int] = deque()
        self._active_job_id: Optional[int] = None
        self._active_process: Optional[subprocess.Popen[str]] = None
        self._cancel_requested: set[int] = set()
        self._stop_requested = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        with self._condition:
            self._stop_requested = True
            self._condition.notify_all()
            if self._active_process is not None and self._active_process.poll() is None:
                self._active_process.terminate()
        self._thread.join(timeout=5)

    def enqueue(self, job_id: int) -> None:
        with self._condition:
            self._pending.append(job_id)
            self._condition.notify()

    def cancel(self, job_id: int) -> bool:
        with self._condition:
            if self._active_job_id == job_id:
                self._cancel_requested.add(job_id)
                if self._active_process is not None and self._active_process.poll() is None:
                    self._active_process.terminate()
                return True

            if job_id in self._pending:
                self._pending = deque(item for item in self._pending if item != job_id)
                self._cancel_requested.add(job_id)

        db = get_db()
        try:
            job = row_to_dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            if not job:
                return False
            update_job_status(
                db,
                job_id,
                status="canceled",
                error="Canceled before execution",
                completed_at=utc_now_iso(),
            )
            apply_stage_completion(
                db,
                job["run_id"],
                job["job_type"],
                "warning",
                results={"canceled": True},
                logs=f"{job['job_type'].title()} job canceled before execution.",
            )
            return True
        finally:
            db.close()

    def _final_job_status(self, stage_status: str) -> str:
        return "failed" if stage_status == "failed" else "completed"

    def _complete_stage_job(self, db, job: dict, stage_key: str, result: dict) -> None:
        apply_stage_completion(
            db,
            job["run_id"],
            stage_key,
            result["status"],
            results=result["payload"].get("results"),
            logs=result["payload"].get("logs"),
        )
        update_job_status(
            db,
            job["id"],
            status=self._final_job_status(result["status"]),
            error=result.get("error") if result["status"] == "failed" else None,
            completed_at=utc_now_iso(),
            log_path=result.get("log_path"),
        )

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._stop_requested:
                    self._condition.wait()
                if self._stop_requested:
                    return
                job_id = self._pending.popleft()
                self._active_job_id = job_id

            try:
                self._execute_job(job_id)
            finally:
                with self._condition:
                    self._active_job_id = None
                    self._active_process = None
                    self._cancel_requested.discard(job_id)

    def _execute_job(self, job_id: int) -> None:
        db = get_db()
        try:
            job = row_to_dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            if not job or job["status"] == "canceled":
                return

            project = row_to_dict(
                db.execute("SELECT * FROM projects WHERE id=?", (job["project_id"],)).fetchone()
            )
            if not project:
                update_job_status(
                    db,
                    job_id,
                    status="failed",
                    error="Project not found",
                    completed_at=utc_now_iso(),
                )
                return

            run = row_to_dict(
                db.execute("SELECT * FROM pipeline_runs WHERE id=?", (job["run_id"],)).fetchone()
            )
            if not run:
                update_job_status(
                    db,
                    job_id,
                    status="failed",
                    error="Run not found",
                    completed_at=utc_now_iso(),
                )
                return

            config = get_project_config_for_project(project)
            if config is None:
                update_job_status(
                    db,
                    job_id,
                    status="failed",
                    error="Project config is invalid",
                    completed_at=utc_now_iso(),
                )
                apply_stage_completion(
                    db,
                    job["run_id"],
                    job["job_type"],
                    "failed",
                    results={"job_type": job["job_type"]},
                    logs="Project config is invalid.",
                )
                return
            stage_key = job["job_type"]
            project_root = Path(project["root_path"])
            mark_stage_running(db, job["run_id"], stage_key)

            if stage_key == "benchmarks":
                benchmarks_config = benchmark_config_for_run(config, run.get("candidate_name"))
                prepared = prepare_benchmark_stage(
                    project_root=project_root,
                    run_id=job["run_id"],
                    model_id=config.model.repo_id or config.model.name,
                    benchmarks_config=benchmarks_config,
                )

                update_job_status(
                    db,
                    job_id,
                    status="running",
                    command=prepared.command_json(),
                    started_at=utc_now_iso(),
                    log_path=str(prepared.log_path),
                )

                with prepared.log_path.open("a", encoding="utf-8") as handle:
                    process = subprocess.Popen(
                        prepared.command,
                        stdout=handle,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    with self._condition:
                        self._active_process = process
                    update_job_status(db, job_id, status="running", pid=process.pid)

                    try:
                        return_code = process.wait(timeout=benchmarks_config.timeout_minutes * 60)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        result = finalize_benchmark_stage(
                            prepared,
                            1,
                            error_message=(
                                f"Benchmark job timed out after {benchmarks_config.timeout_minutes} minutes."
                            ),
                        )
                        self._complete_stage_job(db, job, stage_key, result)
                        update_job_status(
                            db,
                            job_id,
                            status="failed",
                            error=f"Timed out after {benchmarks_config.timeout_minutes} minutes",
                            completed_at=utc_now_iso(),
                        )
                        return

                if job_id in self._cancel_requested:
                    result = finalize_benchmark_stage(
                        prepared,
                        1,
                        error_message="Benchmark job canceled by user.",
                    )
                    apply_stage_completion(
                        db,
                        job["run_id"],
                        stage_key,
                        "warning",
                        results=result["payload"].get("results"),
                        logs=result["payload"].get("logs"),
                    )
                    update_job_status(
                        db,
                        job_id,
                        status="canceled",
                        error="Canceled by user",
                        completed_at=utc_now_iso(),
                    )
                    return

                result = finalize_benchmark_stage(prepared, return_code)
                self._complete_stage_job(db, job, stage_key, result)
                if return_code != 0:
                    update_job_status(
                        db,
                        job_id,
                        status="failed",
                        error=f"Adapter exited with code {return_code}",
                        completed_at=utc_now_iso(),
                    )
                return

            update_job_status(
                db,
                job_id,
                status="running",
                started_at=utc_now_iso(),
            )

            candidate = get_candidate_from_config(config, run.get("candidate_name"))
            if stage_key == "documentation":
                result = execute_documentation_stage(project_root=project_root, run_id=job["run_id"])
            elif stage_key == "safety":
                if candidate is None:
                    raise RuntimeError("Safety automation requires a version 2 candidate config")
                if config.safety is None:
                    raise RuntimeError("Safety automation is not configured for this project")
                result = execute_safety_stage(
                    project_root=project_root,
                    run_id=job["run_id"],
                    candidate=candidate,
                    safety_config=config.safety,
                )
            elif stage_key == "packaging":
                if candidate is None:
                    raise RuntimeError("Packaging automation requires a version 2 candidate config")
                result = execute_packaging_stage(
                    project_root=project_root,
                    run_id=job["run_id"],
                    candidate=candidate,
                )
            elif stage_key == "serving":
                if candidate is None:
                    raise RuntimeError("Serving automation requires a version 2 candidate config")
                result = execute_serving_stage(
                    project_root=project_root,
                    run_id=job["run_id"],
                    candidate=candidate,
                )
            else:
                raise RuntimeError(f"Unsupported job_type: {stage_key}")

            self._complete_stage_job(db, job, stage_key, result)
        except Exception as exc:  # pragma: no cover - operational fallback
            try:
                update_job_status(
                    db,
                    job_id,
                    status="failed",
                    error=str(exc),
                    completed_at=utc_now_iso(),
                )
                job = row_to_dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
                if job:
                    apply_stage_completion(
                        db,
                        job["run_id"],
                        job["job_type"],
                        "failed",
                        results={"job_type": job["job_type"]},
                        logs=str(exc),
                    )
            except Exception:
                pass
        finally:
            db.close()
