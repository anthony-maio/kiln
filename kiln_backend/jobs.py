from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Optional

from kiln_backend.models import ROOT_DIR
from kiln_backend.storage import (
    apply_stage_completion,
    get_db,
    get_job_with_relations,
    get_project_config_for_project,
    row_to_dict,
    tail_text_file,
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
                "benchmarks",
                "warning",
                results={"tool": "lm-eval-harness", "benchmarks": []},
                logs="Benchmark job canceled before execution.",
            )
            return True
        finally:
            db.close()

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
                    "benchmarks",
                    "failed",
                    results={"tool": "lm-eval-harness", "benchmarks": []},
                    logs="Project config is invalid.",
                )
                return

            logs_dir = (Path(project["root_path"]) / ".kiln" / "logs").resolve()
            eval_dir = (
                Path(project["root_path"]) / ".kiln" / "eval_results" / f"run-{job['run_id']}"
            ).resolve()
            logs_dir.mkdir(parents=True, exist_ok=True)
            eval_dir.mkdir(parents=True, exist_ok=True)

            log_path = logs_dir / f"run-{job['run_id']}-benchmarks.log"
            result_path = logs_dir / f"run-{job['run_id']}-benchmarks-result.json"
            command = [
                sys.executable,
                str(ROOT_DIR / "adapters" / "lm_eval_adapter.py"),
                "--model-id",
                config.model.repo_id or config.model.name,
                "--tasks",
                ",".join(task.name for task in config.benchmarks.tasks),
                "--output-dir",
                str(eval_dir),
                "--result-json",
                str(result_path),
                "--model",
                config.benchmarks.model,
                "--model-args",
                config.benchmarks.model_args,
                "--batch-size",
                config.benchmarks.batch_size,
                "--num-fewshot",
                str(config.benchmarks.num_fewshot),
            ]
            if config.benchmarks.device:
                command.extend(["--device", config.benchmarks.device])

            update_job_status(
                db,
                job_id,
                status="running",
                command=json.dumps(command),
                started_at=utc_now_iso(),
                log_path=str(log_path),
            )

            env = os.environ.copy()
            with log_path.open("a", encoding="utf-8") as handle:
                process = subprocess.Popen(
                    command,
                    cwd=ROOT_DIR,
                    env=env,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                with self._condition:
                    self._active_process = process
                update_job_status(db, job_id, status="running", pid=process.pid)

                try:
                    return_code = process.wait(timeout=config.benchmarks.timeout_minutes * 60)
                except subprocess.TimeoutExpired:
                    process.kill()
                    apply_stage_completion(
                        db,
                        job["run_id"],
                        "benchmarks",
                        "failed",
                        results={"tool": "lm-eval-harness", "benchmarks": []},
                        logs=f"Benchmark job timed out after {config.benchmarks.timeout_minutes} minutes.",
                    )
                    update_job_status(
                        db,
                        job_id,
                        status="failed",
                        error=f"Timed out after {config.benchmarks.timeout_minutes} minutes",
                        completed_at=utc_now_iso(),
                    )
                    return

            log_tail = tail_text_file(log_path)
            if job_id in self._cancel_requested:
                apply_stage_completion(
                    db,
                    job["run_id"],
                    "benchmarks",
                    "warning",
                    results={"tool": "lm-eval-harness", "benchmarks": []},
                    logs=log_tail or "Benchmark job canceled.",
                )
                update_job_status(
                    db,
                    job_id,
                    status="canceled",
                    error="Canceled by user",
                    completed_at=utc_now_iso(),
                )
                return

            if return_code != 0:
                apply_stage_completion(
                    db,
                    job["run_id"],
                    "benchmarks",
                    "failed",
                    results={"tool": "lm-eval-harness", "benchmarks": []},
                    logs=log_tail,
                )
                update_job_status(
                    db,
                    job_id,
                    status="failed",
                    error=f"Adapter exited with code {return_code}",
                    completed_at=utc_now_iso(),
                )
                return

            payload = json.loads(result_path.read_text(encoding="utf-8"))
            apply_stage_completion(
                db,
                job["run_id"],
                "benchmarks",
                payload.get("status", "failed"),
                results=payload.get("results"),
                logs=payload.get("logs") or log_tail,
            )
            final_job_status = "completed" if payload.get("status") == "passed" else "failed"
            update_job_status(
                db,
                job_id,
                status=final_job_status,
                error=None if final_job_status == "completed" else "Adapter returned failed status",
                completed_at=utc_now_iso(),
            )
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
                        "benchmarks",
                        "failed",
                        results={"tool": "lm-eval-harness", "benchmarks": []},
                        logs=str(exc),
                    )
            except Exception:
                pass
        finally:
            db.close()
