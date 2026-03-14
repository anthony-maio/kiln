from __future__ import annotations

import json
import os
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import HTTPException
from pydantic import ValidationError

from kiln_backend.policy import evaluate_benchmark_payload
from kiln_backend.models import (
    CONFIG_FILENAME,
    MANUAL_STAGE_KEYS,
    CandidateBenchmarksConfig,
    CandidateConfig,
    ProjectConfig,
    PROJECT_REAL_INTEGRATIONS,
    PROJECT_STAGE_DEFINITIONS,
    REAL_INTEGRATIONS,
    STAGE_DEFINITIONS,
    TERMINAL_STAGE_STATUSES,
)

DEFAULT_DB_PATH = str(Path(__file__).resolve().parent.parent / "kiln.db")
DEFAULT_MANUAL_STAGE_SELECTION = {
    "safety": "required",
    "documentation": "required",
    "packaging": "required",
    "serving": "skip",
    "monitoring": "skip",
    "incidents": "skip",
    "improvement": "skip",
}
AUTOMATED_PROJECT_STAGE_KEYS = {"benchmarks", "documentation", "packaging", "serving"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def row_to_dict(row: sqlite3.Row | None) -> Optional[dict[str, Any]]:
    return dict(row) if row is not None else None


def rows_to_list(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def parse_json_string(raw: Any) -> Any:
    if raw is None or not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def parse_stage_rows(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for stage in stages:
        stage["results"] = parse_json_string(stage.get("results"))
    return stages


def get_db() -> sqlite3.Connection:
    db_path = os.environ.get("KILN_DB_PATH", DEFAULT_DB_PATH)
    db = sqlite3.connect(db_path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def ensure_absolute_project_root(root_path: str) -> Path:
    path = Path(root_path).expanduser()
    if not path.is_absolute():
        raise HTTPException(422, "root_path must be an absolute path")
    if not path.exists() or not path.is_dir():
        raise HTTPException(404, "Project root does not exist")
    return path.resolve()


def init_db() -> None:
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            repo_id TEXT,
            parameters TEXT,
            architecture TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'registered'
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            root_path TEXT NOT NULL UNIQUE,
            config_path TEXT NOT NULL,
            model_id INTEGER REFERENCES models(id),
            config_status TEXT DEFAULT 'valid',
            config_error TEXT,
            last_run_id INTEGER REFERENCES pipeline_runs(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id INTEGER REFERENCES models(id),
            project_id INTEGER REFERENCES projects(id),
            candidate_name TEXT,
            candidate_format TEXT,
            candidate_path TEXT,
            resolved_runtime TEXT,
            status TEXT DEFAULT 'pending',
            mode TEXT DEFAULT 'mock',
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            trigger TEXT DEFAULT 'manual'
        );

        CREATE TABLE IF NOT EXISTS pipeline_stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER REFERENCES pipeline_runs(id),
            stage_key TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            stage_order INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            duration_seconds REAL,
            results JSON,
            logs TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id INTEGER REFERENCES models(id),
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'open',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            model_id INTEGER,
            run_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            run_id INTEGER NOT NULL REFERENCES pipeline_runs(id),
            job_type TEXT NOT NULL,
            status TEXT DEFAULT 'queued',
            command TEXT,
            pid INTEGER,
            log_path TEXT,
            error TEXT,
            queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP
        );
        """
    )

    run_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(pipeline_runs)").fetchall()
    }
    if "mode" not in run_columns:
        db.execute("ALTER TABLE pipeline_runs ADD COLUMN mode TEXT DEFAULT 'mock'")
    if "project_id" not in run_columns:
        db.execute("ALTER TABLE pipeline_runs ADD COLUMN project_id INTEGER REFERENCES projects(id)")
    if "candidate_name" not in run_columns:
        db.execute("ALTER TABLE pipeline_runs ADD COLUMN candidate_name TEXT")
    if "candidate_format" not in run_columns:
        db.execute("ALTER TABLE pipeline_runs ADD COLUMN candidate_format TEXT")
    if "candidate_path" not in run_columns:
        db.execute("ALTER TABLE pipeline_runs ADD COLUMN candidate_path TEXT")
    if "resolved_runtime" not in run_columns:
        db.execute("ALTER TABLE pipeline_runs ADD COLUMN resolved_runtime TEXT")

    project_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(projects)").fetchall()
    }
    if "last_run_id" not in project_columns:
        db.execute("ALTER TABLE projects ADD COLUMN last_run_id INTEGER REFERENCES pipeline_runs(id)")
    if "updated_at" not in project_columns:
        db.execute("ALTER TABLE projects ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

    job_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(jobs)").fetchall()
    }
    if "pid" not in job_columns:
        db.execute("ALTER TABLE jobs ADD COLUMN pid INTEGER")

    db.commit()
    db.close()


def log_activity(
    db: sqlite3.Connection,
    event_type: str,
    message: str,
    model_id: Optional[int] = None,
    run_id: Optional[int] = None,
) -> None:
    db.execute(
        """
        INSERT INTO activity_log (event_type, message, model_id, run_id, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (event_type, message, model_id, run_id, utc_now_iso()),
    )


def default_project_config(root_path: Path) -> ProjectConfig:
    name = root_path.name
    repo_id = f"local/{name}"
    return ProjectConfig.model_validate(
        {
            "version": 1,
            "model": {
                "name": name,
                "repo_id": repo_id,
                "parameters": "7B",
                "architecture": "Mistral",
                "description": "",
            },
            "benchmarks": {
                "provider": "lm_eval",
                "model": "hf",
                "model_args": f"pretrained={repo_id}",
                "tasks": [
                    {"name": "hellaswag", "min_score": 0.75},
                    {"name": "arc_easy", "min_score": 0.70},
                ],
                "device": "cuda:0",
                "num_fewshot": 0,
                "batch_size": "auto",
                "timeout_minutes": 120,
            },
            "manual_stages": {
                "safety": "required",
                "documentation": "required",
                "packaging": "required",
                "serving": "skip",
                "monitoring": "skip",
                "incidents": "skip",
                "improvement": "skip",
            },
            "report": {"output_dir": ".kiln/reports"},
        }
    )


def validate_project_config_payload(payload: Any) -> ProjectConfig:
    try:
        return ProjectConfig.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()) from exc


def get_candidate_from_config(
    config: ProjectConfig, candidate_name: Optional[str]
) -> Optional[CandidateConfig]:
    if config.version == 1:
        return None
    if not candidate_name:
        raise HTTPException(422, "candidate_name is required for version 2 project configs")

    for candidate in config.candidates or []:
        if candidate.name == candidate_name:
            return candidate

    raise HTTPException(422, f"Unknown candidate_name: {candidate_name}")


def resolve_candidate_path(project_root: Path, candidate: CandidateConfig) -> Path:
    candidate_path = Path(candidate.path).expanduser()
    if not candidate_path.is_absolute():
        candidate_path = (project_root / candidate_path).resolve()
    else:
        candidate_path = candidate_path.resolve()
    return candidate_path


def resolve_candidate_runtime(candidate: CandidateConfig) -> str:
    if candidate.runtime:
        return candidate.runtime
    if candidate.serving.runtime:
        return candidate.serving.runtime
    return "llama_cpp" if candidate.format == "gguf" else "vllm"


def manual_stage_selection_for_config(config: ProjectConfig) -> dict[str, str]:
    if config.manual_stages is not None:
        return config.manual_stages.model_dump(mode="python")
    defaults = dict(DEFAULT_MANUAL_STAGE_SELECTION)
    if config.version == 2:
        defaults["serving"] = "required"
    return defaults


def resolve_run_target(
    project: dict[str, Any],
    config: ProjectConfig,
    candidate_name: Optional[str],
) -> dict[str, Any]:
    if config.version == 1:
        return {
            "candidate_name": None,
            "candidate_format": None,
            "candidate_path": None,
            "resolved_runtime": None,
            "benchmarks": config.benchmarks,
            "manual_stages": manual_stage_selection_for_config(config),
        }

    candidate = get_candidate_from_config(config, candidate_name)
    assert candidate is not None
    candidate_path = resolve_candidate_path(Path(project["root_path"]), candidate)
    if not candidate_path.exists():
        raise HTTPException(422, f"Candidate artifact path does not exist: {candidate_path}")

    return {
        "candidate_name": candidate.name,
        "candidate_format": candidate.format,
        "candidate_path": str(candidate_path),
        "resolved_runtime": resolve_candidate_runtime(candidate),
        "benchmarks": candidate.benchmarks,
        "manual_stages": manual_stage_selection_for_config(config),
    }


def benchmark_config_for_run(
    config: ProjectConfig, candidate_name: Optional[str]
) -> CandidateBenchmarksConfig:
    candidate = get_candidate_from_config(config, candidate_name)
    if candidate is None:
        if config.benchmarks is None:
            raise HTTPException(422, "Project config is missing benchmark settings")
        return config.benchmarks
    return candidate.benchmarks


def build_project_stage_plan(
    config: ProjectConfig,
    candidate_name: Optional[str],
) -> list[dict[str, Any]]:
    manual_selection = manual_stage_selection_for_config(config)
    candidate = get_candidate_from_config(config, candidate_name) if config.version == 2 else None
    stage_plan: list[dict[str, Any]] = []

    for stage_key, stage_name, stage_order in PROJECT_STAGE_DEFINITIONS:
        status = "pending"
        logs = "Manual completion required in phase 1."
        job_required = False

        if stage_key == "benchmarks":
            job_required = True
            logs = "Queued for the local job runner."
        elif stage_key == "safety" and config.safety is not None:
            job_required = True
            logs = "Queued for the local job runner."
        elif manual_selection.get(stage_key) == "skip":
            status = "skipped"
            logs = "Skipped per project config."
        elif stage_key == "safety":
            logs = "Manual completion required because no safety prompt suite is configured."
        elif stage_key == "documentation":
            job_required = True
            logs = "Queued for the local job runner."
        elif stage_key == "packaging":
            if candidate is None:
                status = "skipped"
                logs = "Packaging automation requires a version 2 candidate config."
            else:
                job_required = True
                logs = "Queued for the local job runner."
        elif stage_key == "serving":
            if candidate is None:
                status = "skipped"
                logs = "Serving automation requires a version 2 candidate config."
            elif not candidate.serving.enabled:
                status = "skipped"
                logs = "Serving disabled for the selected candidate."
            else:
                job_required = True
                logs = "Queued for the local job runner."

        stage_plan.append(
            {
                "stage_key": stage_key,
                "stage_name": stage_name,
                "stage_order": stage_order,
                "status": status,
                "logs": logs,
                "job_required": job_required,
            }
        )

    return stage_plan


def write_project_config(config_path: Path, config: ProjectConfig) -> None:
    config_path.write_text(
        yaml.safe_dump(
            config.model_dump(mode="python"),
            sort_keys=False,
            allow_unicode=False,
        ),
        encoding="utf-8",
    )


def load_project_config_from_path(config_path: Path) -> ProjectConfig:
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(404, f"Config file not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise HTTPException(422, f"Invalid YAML: {exc}") from exc
    return validate_project_config_payload(raw)


def upsert_model_from_project_config(
    db: sqlite3.Connection,
    config: ProjectConfig,
) -> dict[str, Any]:
    model_data = config.model
    existing = None
    if model_data.repo_id:
        existing = db.execute(
            "SELECT * FROM models WHERE repo_id=?",
            (model_data.repo_id,),
        ).fetchone()
    if existing is None:
        existing = db.execute(
            "SELECT * FROM models WHERE name=?",
            (model_data.name,),
        ).fetchone()

    if existing:
        model_id = existing["id"]
        db.execute(
            """
            UPDATE models
            SET name=?, repo_id=?, parameters=?, architecture=?, description=?
            WHERE id=?
            """,
            (
                model_data.name,
                model_data.repo_id,
                model_data.parameters,
                model_data.architecture,
                model_data.description,
                model_id,
            ),
        )
    else:
        cursor = db.execute(
            """
            INSERT INTO models (name, repo_id, parameters, architecture, description, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'registered', ?)
            """,
            (
                model_data.name,
                model_data.repo_id,
                model_data.parameters,
                model_data.architecture,
                model_data.description,
                utc_now_iso(),
            ),
        )
        model_id = cursor.lastrowid
        log_activity(db, "model_registered", f"{model_data.name} registered", model_id)

    db.commit()
    return row_to_dict(db.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone())


def get_project_config_for_project(project: dict[str, Any]) -> Optional[ProjectConfig]:
    config_path = Path(project["config_path"])
    if not config_path.exists():
        return None
    try:
        return load_project_config_from_path(config_path)
    except HTTPException:
        return None


def load_project_detail(db: sqlite3.Connection, project_id: int) -> dict[str, Any]:
    project = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
    if not project:
        raise HTTPException(404, "Project not found")

    if project.get("model_id"):
        project["model"] = row_to_dict(
            db.execute("SELECT * FROM models WHERE id=?", (project["model_id"],)).fetchone()
        )
    else:
        project["model"] = None

    if project.get("last_run_id"):
        project["last_run"] = get_run_with_stages(db, project["last_run_id"])
    else:
        project["last_run"] = None

    project["jobs"] = rows_to_list(
        db.execute(
            """
            SELECT * FROM jobs
            WHERE project_id=?
            ORDER BY queued_at DESC, id DESC
            LIMIT 10
            """,
            (project_id,),
        ).fetchall()
    )

    config = get_project_config_for_project(project)
    project["config"] = config.model_dump(mode="python") if config else None
    return project


def sync_project_record(
    db: sqlite3.Connection,
    project_id: int,
    *,
    create_default_if_missing: bool,
) -> dict[str, Any]:
    project = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
    if not project:
        raise HTTPException(404, "Project not found")

    config_path = Path(project["config_path"])
    config_status = "valid"
    config_error = None
    model_id = project.get("model_id")

    try:
        if not config_path.exists():
            if not create_default_if_missing:
                raise FileNotFoundError(f"Missing config file: {config_path}")
            write_project_config(config_path, default_project_config(Path(project["root_path"])))

        config = load_project_config_from_path(config_path)
        model = upsert_model_from_project_config(db, config)
        model_id = model["id"]
    except Exception as exc:  # pragma: no cover - handled by API layer
        config_status = "invalid"
        config_error = str(exc)

    db.execute(
        """
        UPDATE projects
        SET model_id=?, config_status=?, config_error=?, updated_at=?
        WHERE id=?
        """,
        (model_id, config_status, config_error, utc_now_iso(), project_id),
    )
    db.commit()
    return load_project_detail(db, project_id)


def get_run_with_stages(db: sqlite3.Connection, run_id: int) -> Optional[dict[str, Any]]:
    run = row_to_dict(
        db.execute(
            """
            SELECT pr.*, m.name AS model_name, p.name AS project_name, p.root_path AS project_root_path
            FROM pipeline_runs pr
            JOIN models m ON pr.model_id=m.id
            LEFT JOIN projects p ON pr.project_id=p.id
            WHERE pr.id=?
            """,
            (run_id,),
        ).fetchone()
    )
    if not run:
        return None

    run["stages"] = parse_stage_rows(
        rows_to_list(
            db.execute(
                "SELECT * FROM pipeline_stages WHERE run_id=? ORDER BY stage_order",
                (run_id,),
            ).fetchall()
        )
    )
    run["automated_stage_keys"] = [
        row["job_type"]
        for row in db.execute(
            "SELECT DISTINCT job_type FROM jobs WHERE run_id=? ORDER BY job_type",
            (run_id,),
        ).fetchall()
    ]

    if run.get("project_id"):
        project = row_to_dict(
            db.execute("SELECT * FROM projects WHERE id=?", (run["project_id"],)).fetchone()
        )
        if project:
            config = get_project_config_for_project(project)
            if config:
                run["report_artifacts"] = compute_report_artifact_paths(project, run_id, config)
    return run


def determine_release_verdict(stages: list[dict[str, Any]]) -> str:
    statuses = [stage["status"] for stage in stages]
    if any(status == "failed" for status in statuses):
        return "blocked"
    if any(status in {"warning", "pending", "running"} for status in statuses):
        return "needs_review"
    return "ready"


def build_release_report(run: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "passed": 0,
        "failed": 0,
        "warning": 0,
        "skipped": 0,
        "pending": 0,
        "running": 0,
        "other": 0,
    }
    for stage in run["stages"]:
        key = stage["status"] if stage["status"] in summary else "other"
        summary[key] += 1

    failed = [stage["stage_name"] for stage in run["stages"] if stage["status"] == "failed"]
    warnings = [stage["stage_name"] for stage in run["stages"] if stage["status"] == "warning"]
    pending = [
        stage["stage_name"]
        for stage in run["stages"]
        if stage["status"] in {"pending", "running"}
    ]

    next_actions = []
    if failed:
        next_actions.append(f"Fix failed stages before release: {', '.join(failed)}.")
    if warnings:
        next_actions.append(f"Review warnings and document risk tradeoffs: {', '.join(warnings)}.")
    if pending:
        next_actions.append(f"Complete remaining stages: {', '.join(pending)}.")
    if not next_actions:
        next_actions.append("Release gate passed. Attach this report to your model release.")

    integrations = (
        set(run.get("automated_stage_keys") or [])
        if run.get("project_id")
        else set(REAL_INTEGRATIONS)
    )
    report = {
        "run_id": run["id"],
        "project_id": run.get("project_id"),
        "project_name": run.get("project_name"),
        "model_id": run["model_id"],
        "model_name": run["model_name"],
        "mode": run.get("mode", "mock"),
        "run_status": run["status"],
        "verdict": determine_release_verdict(run["stages"]),
        "generated_at": utc_now_iso(),
        "status_summary": summary,
        "stages": [],
        "next_actions": next_actions,
    }

    for stage in run["stages"]:
        entry = {
            "key": stage["stage_key"],
            "name": stage["stage_name"],
            "status": stage["status"],
            "duration_seconds": stage.get("duration_seconds"),
            "integrated_in_real_mode": stage["stage_key"] in integrations,
        }
        if stage.get("results") is not None:
            entry["results"] = stage["results"]
        report["stages"].append(entry)

    if run.get("report_artifacts"):
        report["artifacts"] = run["report_artifacts"]
    return report


def render_release_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Kiln Release Readiness Report",
        "",
        f"Run ID: {report['run_id']}",
        f"Model: {report['model_name']}",
    ]
    if report.get("project_name"):
        lines.append(f"Project: {report['project_name']}")
    lines.extend(
        [
            f"Mode: {report['mode']}",
            f"Run Status: {report['run_status']}",
            f"Verdict: {report['verdict'].upper()}",
            "",
            "## Stage Status",
        ]
    )
    for stage in report["stages"]:
        integration = "real-adapter" if stage["integrated_in_real_mode"] else "manual"
        lines.append(f"- {stage['name']}: {stage['status']} ({integration})")
    lines.extend(["", "## Next Actions"])
    for action in report["next_actions"]:
        lines.append(f"- {action}")
    return "\n".join(lines) + "\n"


def compute_report_artifact_paths(
    project: dict[str, Any],
    run_id: int,
    config: Optional[ProjectConfig] = None,
) -> dict[str, str]:
    parsed_config = config or get_project_config_for_project(project)
    if parsed_config is None:
        raise HTTPException(422, "Project config is invalid")
    output_dir = (Path(project["root_path"]) / parsed_config.report.output_dir).resolve()
    return {
        "directory": str(output_dir),
        "markdown": str(output_dir / f"run-{run_id}.md"),
        "json": str(output_dir / f"run-{run_id}.json"),
    }


def write_report_artifacts(db: sqlite3.Connection, run_id: int) -> dict[str, str]:
    run = get_run_with_stages(db, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if not run.get("project_id"):
        raise HTTPException(422, "Run is not associated with a project")

    project = row_to_dict(
        db.execute("SELECT * FROM projects WHERE id=?", (run["project_id"],)).fetchone()
    )
    if not project:
        raise HTTPException(404, "Project not found")

    config = load_project_config_from_path(Path(project["config_path"]))
    artifacts = compute_report_artifact_paths(project, run_id, config)
    output_dir = Path(artifacts["directory"])
    output_dir.mkdir(parents=True, exist_ok=True)

    report = build_release_report(run)
    report["artifacts"] = artifacts
    Path(artifacts["json"]).write_text(json.dumps(report, indent=2), encoding="utf-8")
    Path(artifacts["markdown"]).write_text(
        render_release_report_markdown(report),
        encoding="utf-8",
    )
    return artifacts


def evaluate_benchmark_results(
    db: sqlite3.Connection,
    run_id: int,
    requested_status: str,
    results: Optional[dict[str, Any]],
) -> tuple[str, Optional[dict[str, Any]]]:
    if requested_status != "passed":
        return requested_status, results
    run = get_run_with_stages(db, run_id)
    if not run or not run.get("project_id") or not results:
        return requested_status, results

    project = row_to_dict(
        db.execute("SELECT * FROM projects WHERE id=?", (run["project_id"],)).fetchone()
    )
    if not project:
        return requested_status, results
    config = get_project_config_for_project(project)
    if config is None:
        return requested_status, results

    return evaluate_benchmark_payload(
        benchmark_config_for_run(config, run.get("candidate_name")),
        results,
    )


def refresh_run_status(db: sqlite3.Connection, run_id: int) -> str:
    statuses = [
        row["status"]
        for row in db.execute(
            "SELECT status FROM pipeline_stages WHERE run_id=?",
            (run_id,),
        ).fetchall()
    ]
    if not statuses:
        return "pending"

    if all(status in TERMINAL_STAGE_STATUSES for status in statuses):
        run_status = "failed" if "failed" in statuses else "passed"
        completed_at = utc_now_iso()
    else:
        run_status = "running"
        completed_at = None

    db.execute(
        "UPDATE pipeline_runs SET status=?, completed_at=? WHERE id=?",
        (run_status, completed_at, run_id),
    )
    db.commit()
    return run_status


def mark_stage_running(db: sqlite3.Connection, run_id: int, stage_key: str) -> dict[str, Any]:
    stage = db.execute(
        "SELECT * FROM pipeline_stages WHERE run_id=? AND stage_key=?",
        (run_id, stage_key),
    ).fetchone()
    if not stage:
        raise HTTPException(404, "Stage not found")

    now = utc_now_iso()
    db.execute(
        """
        UPDATE pipeline_stages
        SET status='running', started_at=?, completed_at=NULL, duration_seconds=NULL
        WHERE id=?
        """,
        (now, stage["id"]),
    )
    db.execute(
        "UPDATE pipeline_runs SET status='running', completed_at=NULL WHERE id=?",
        (run_id,),
    )
    db.commit()
    return {"status": "running", "started_at": now}


def apply_stage_completion(
    db: sqlite3.Connection,
    run_id: int,
    stage_key: str,
    requested_status: str,
    *,
    results: Optional[dict[str, Any]] = None,
    logs: Optional[str] = None,
    completed_at: Optional[datetime] = None,
) -> dict[str, Any]:
    stage = db.execute(
        "SELECT * FROM pipeline_stages WHERE run_id=? AND stage_key=?",
        (run_id, stage_key),
    ).fetchone()
    if not stage:
        raise HTTPException(404, "Stage not found")

    final_status = requested_status
    final_results = results
    if stage_key == "benchmarks":
        final_status, final_results = evaluate_benchmark_results(
            db,
            run_id,
            requested_status,
            results,
        )

    now = completed_at or utc_now()
    started_at_raw = stage["started_at"]
    started_at = datetime.fromisoformat(started_at_raw) if started_at_raw else now
    duration = max((now - started_at).total_seconds(), 0)

    db.execute(
        """
        UPDATE pipeline_stages
        SET status=?, completed_at=?, duration_seconds=?, results=?, logs=?
        WHERE id=?
        """,
        (
            final_status,
            now.isoformat(),
            duration,
            json.dumps(final_results) if final_results is not None else None,
            logs,
            stage["id"],
        ),
    )
    db.commit()

    refresh_run_status(db, run_id)
    run = get_run_with_stages(db, run_id)
    if run and run.get("project_id"):
        write_report_artifacts(db, run_id)
    return {"status": final_status, "completed_at": now.isoformat()}


def create_project_run(
    db: sqlite3.Connection,
    project: dict[str, Any],
    config: ProjectConfig,
    *,
    candidate_name: Optional[str] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model = upsert_model_from_project_config(db, config)
    run_target = resolve_run_target(project, config, candidate_name)
    stage_plan = build_project_stage_plan(config, candidate_name)
    started_at = utc_now()
    run_cursor = db.execute(
        """
        INSERT INTO pipeline_runs (
            model_id,
            project_id,
            candidate_name,
            candidate_format,
            candidate_path,
            resolved_runtime,
            status,
            mode,
            started_at,
            created_at,
            trigger
        )
        VALUES (?, ?, ?, ?, ?, ?, 'running', 'real', ?, ?, 'project')
        """,
        (
            model["id"],
            project["id"],
            run_target["candidate_name"],
            run_target["candidate_format"],
            run_target["candidate_path"],
            run_target["resolved_runtime"],
            started_at.isoformat(),
            started_at.isoformat(),
        ),
    )
    run_id = run_cursor.lastrowid

    first_job_id: Optional[int] = None
    for stage in stage_plan:
        stage_started_at = None
        stage_completed_at = started_at.isoformat() if stage["status"] == "skipped" else None
        db.execute(
            """
            INSERT INTO pipeline_stages (
                run_id, stage_key, stage_name, stage_order, status, started_at, completed_at, logs
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                stage["stage_key"],
                stage["stage_name"],
                stage["stage_order"],
                stage["status"],
                stage_started_at,
                stage_completed_at,
                stage["logs"],
            ),
        )
        if stage["job_required"]:
            job_cursor = db.execute(
                """
                INSERT INTO jobs (project_id, run_id, job_type, status, queued_at)
                VALUES (?, ?, ?, 'queued', ?)
                """,
                (project["id"], run_id, stage["stage_key"], started_at.isoformat()),
            )
            if first_job_id is None:
                first_job_id = job_cursor.lastrowid

    db.execute(
        "UPDATE projects SET model_id=?, last_run_id=?, updated_at=? WHERE id=?",
        (model["id"], run_id, utc_now_iso(), project["id"]),
    )
    log_activity(
        db,
        "run_started",
        f"Project run #{run_id} started for {model['name']}",
        model["id"],
        run_id,
    )
    db.commit()
    write_report_artifacts(db, run_id)
    if first_job_id is None:
        raise HTTPException(500, "Project run was created without any automated jobs")
    return get_run_with_stages(db, run_id), get_job_with_relations(db, first_job_id)


def get_job_with_relations(db: sqlite3.Connection, job_id: int) -> Optional[dict[str, Any]]:
    return row_to_dict(
        db.execute(
            """
            SELECT j.*, p.name AS project_name, p.root_path, pr.status AS run_status
            FROM jobs j
            JOIN projects p ON j.project_id=p.id
            JOIN pipeline_runs pr ON j.run_id=pr.id
            WHERE j.id=?
            """,
            (job_id,),
        ).fetchone()
    )


def update_job_status(
    db: sqlite3.Connection,
    job_id: int,
    *,
    status: str,
    pid: Optional[int] = None,
    log_path: Optional[str] = None,
    error: Optional[str] = None,
    command: Optional[str] = None,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
) -> None:
    assignments = ["status=?"]
    params: list[Any] = [status]
    if pid is not None:
        assignments.append("pid=?")
        params.append(pid)
    if log_path is not None:
        assignments.append("log_path=?")
        params.append(log_path)
    if error is not None:
        assignments.append("error=?")
        params.append(error)
    if command is not None:
        assignments.append("command=?")
        params.append(command)
    if started_at is not None:
        assignments.append("started_at=?")
        params.append(started_at)
    if completed_at is not None:
        assignments.append("completed_at=?")
        params.append(completed_at)
    params.append(job_id)
    db.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE id=?", params)
    db.commit()


def tail_text_file(path: Path, limit: int = 4000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:]


def _generate_mock_results(stage_key: str) -> tuple[dict[str, Any], str]:
    if stage_key == "benchmarks":
        benchmarks = [
            {"name": "HellaSwag", "score": round(random.uniform(56, 64), 1), "status": "pass"},
            {"name": "ARC-Easy", "score": round(random.uniform(70, 85), 1), "status": "pass"},
        ]
        return {"benchmarks": benchmarks, "tool": "lm-eval-harness"}, "passed"

    if stage_key == "safety":
        return {"toxicity": {"expected_max_toxicity": 0.42}}, "warning"
    if stage_key == "documentation":
        return {"checklist_complete": 6, "checklist_total": 8}, "passed"
    if stage_key == "packaging":
        return {"huggingface": {"uploaded": True}}, "passed"
    if stage_key == "serving":
        return {"engine": "vLLM", "health": "healthy"}, "passed"
    if stage_key == "monitoring":
        return {"status": "active", "drift_detected": False}, "passed"
    if stage_key == "incidents":
        return {"total_incidents": 0, "open_incidents": 0}, "passed"
    if stage_key == "improvement":
        return {"next_actions": ["Collect feedback"]}, "skipped"
    return {}, "passed"


def simulate_run(db: sqlite3.Connection, run_id: int) -> None:
    stages = db.execute(
        "SELECT * FROM pipeline_stages WHERE run_id=? ORDER BY stage_order",
        (run_id,),
    ).fetchall()
    cursor = utc_now()
    statuses = []
    for stage in stages:
        results, status = _generate_mock_results(stage["stage_key"])
        duration = random.uniform(30, 240)
        start = cursor
        end = start + timedelta(seconds=duration)
        db.execute(
            """
            UPDATE pipeline_stages
            SET status=?, started_at=?, completed_at=?, duration_seconds=?, results=?
            WHERE id=?
            """,
            (
                status,
                start.isoformat(),
                end.isoformat(),
                duration,
                json.dumps(results),
                stage["id"],
            ),
        )
        cursor = end + timedelta(seconds=10)
        statuses.append(status)

    run_status = "failed" if "failed" in statuses else "passed"
    db.execute(
        "UPDATE pipeline_runs SET status=?, completed_at=? WHERE id=?",
        (run_status, cursor.isoformat(), run_id),
    )
    db.commit()


def seed_demo_data() -> None:
    db = get_db()
    existing = db.execute("SELECT COUNT(*) FROM models").fetchone()[0]
    if existing > 0:
        db.close()
        return

    model_created = utc_now() - timedelta(days=7)
    db.execute(
        """
        INSERT INTO models (name, repo_id, parameters, architecture, description, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "Eve-3-SABER-1B",
            "anthonym21/Eve-3-SABER-1B",
            "1B",
            "SABER",
            "Seeded demo model.",
            "deployed",
            model_created.isoformat(),
        ),
    )
    model_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    db.execute(
        """
        INSERT INTO models (name, repo_id, parameters, architecture, description, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "Eve-2-MoE-IT-272M",
            "anthonym21/Eve-2-MoE-IT-272M",
            "272M",
            "DeepSeekMoE",
            "Second seeded demo model.",
            "registered",
            (utc_now() - timedelta(days=2)).isoformat(),
        ),
    )

    run_cursor = db.execute(
        """
        INSERT INTO pipeline_runs (model_id, status, mode, started_at, completed_at, created_at, trigger)
        VALUES (?, 'passed', 'mock', ?, ?, ?, 'manual')
        """,
        (
            model_id,
            (model_created + timedelta(hours=1)).isoformat(),
            (model_created + timedelta(hours=4)).isoformat(),
            model_created.isoformat(),
        ),
    )
    run_id = run_cursor.lastrowid

    for stage_key, stage_name, stage_order in STAGE_DEFINITIONS:
        results, status = _generate_mock_results(stage_key)
        db.execute(
            """
            INSERT INTO pipeline_stages (
                run_id, stage_key, stage_name, stage_order, status, started_at, completed_at, duration_seconds, results
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                stage_key,
                stage_name,
                stage_order,
                status,
                (model_created + timedelta(hours=1)).isoformat(),
                (model_created + timedelta(hours=2)).isoformat(),
                120,
                json.dumps(results),
            ),
        )

    log_activity(db, "run_started", "Seeded demo run completed", model_id, run_id)
    db.commit()
    db.close()
