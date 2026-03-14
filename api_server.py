#!/usr/bin/env python3
"""Kiln API server."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse

from kiln_backend.jobs import JobRunner
from kiln_backend.models import (
    APP_VERSION,
    DEFAULT_CORS_ORIGINS,
    IncidentCreate,
    ModelCreate,
    ProjectConfig,
    ProjectCreate,
    ProjectRunCreate,
    REAL_INTEGRATIONS,
    RunCreate,
    STAGE_DEFINITIONS,
    StageUpdate,
    STATIC_DIR,
    TERMINAL_STAGE_STATUSES,
)
from kiln_backend.storage import (
    apply_stage_completion,
    build_release_report,
    create_project_run,
    default_project_config,
    ensure_absolute_project_root,
    get_db,
    get_job_with_relations,
    get_run_with_stages,
    init_db,
    load_project_config_from_path,
    load_project_detail,
    log_activity,
    mark_stage_running,
    render_release_report_markdown,
    row_to_dict,
    rows_to_list,
    seed_demo_data,
    simulate_run,
    sync_project_record,
    utc_now_iso,
    write_project_config,
    write_report_artifacts,
)

JOB_RUNNER: Optional[JobRunner] = None


def get_cors_origins() -> list[str]:
    raw = os.environ.get("KILN_CORS_ORIGINS", "").strip()
    if not raw:
        return DEFAULT_CORS_ORIGINS
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    if "*" in origins:
        return ["*"]
    return origins or DEFAULT_CORS_ORIGINS


def seed_endpoint_enabled() -> bool:
    return os.environ.get("KILN_ENABLE_SEED_ENDPOINT", "").lower() == "true"


@asynccontextmanager
async def lifespan(_: FastAPI):
    global JOB_RUNNER
    init_db()
    seed_demo_data()
    JOB_RUNNER = JobRunner()
    JOB_RUNNER.start()
    try:
        yield
    finally:
        if JOB_RUNNER is not None:
            JOB_RUNNER.stop()
            JOB_RUNNER = None


app = FastAPI(
    title="Kiln",
    description="Local-first release gate for open-source model builders.",
    version=APP_VERSION,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/dashboard")
def get_dashboard():
    db = get_db()
    try:
        models_count = db.execute("SELECT COUNT(*) FROM models").fetchone()[0]
        projects_count = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        runs_count = db.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
        passed_runs = db.execute(
            "SELECT COUNT(*) FROM pipeline_runs WHERE status='passed'"
        ).fetchone()[0]
        failed_runs = db.execute(
            "SELECT COUNT(*) FROM pipeline_runs WHERE status='failed'"
        ).fetchone()[0]
        active_jobs = db.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')"
        ).fetchone()[0]
        open_incidents = db.execute(
            "SELECT COUNT(*) FROM incidents WHERE status='open'"
        ).fetchone()[0]
        recent_activity = rows_to_list(
            db.execute("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT 20").fetchall()
        )
        recent_models = rows_to_list(
            db.execute("SELECT * FROM models ORDER BY created_at DESC LIMIT 5").fetchall()
        )
        recent_projects = rows_to_list(
            db.execute("SELECT * FROM projects ORDER BY updated_at DESC LIMIT 5").fetchall()
        )
        stages_summary = rows_to_list(
            db.execute(
                """
                SELECT stage_key, stage_name,
                       SUM(CASE WHEN status='passed' THEN 1 ELSE 0 END) AS passed,
                       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                       SUM(CASE WHEN status='warning' THEN 1 ELSE 0 END) AS warnings,
                       COUNT(*) AS total
                FROM pipeline_stages
                GROUP BY stage_key, stage_name
                ORDER BY MIN(stage_order)
                """
            ).fetchall()
        )
        return {
            "stats": {
                "total_models": models_count,
                "total_projects": projects_count,
                "total_runs": runs_count,
                "passed_runs": passed_runs,
                "failed_runs": failed_runs,
                "active_jobs": active_jobs,
                "pass_rate": round(passed_runs / max(runs_count, 1) * 100, 1),
                "open_incidents": open_incidents,
            },
            "recent_activity": recent_activity,
            "models": recent_models,
            "projects": recent_projects,
            "stages_summary": stages_summary,
        }
    finally:
        db.close()


@app.get("/api/models")
def list_models():
    db = get_db()
    try:
        models = rows_to_list(db.execute("SELECT * FROM models ORDER BY created_at DESC").fetchall())
        for model in models:
            model["latest_run"] = row_to_dict(
                db.execute(
                    """
                    SELECT id, status, completed_at
                    FROM pipeline_runs
                    WHERE model_id=?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (model["id"],),
                ).fetchone()
            )
            model["run_count"] = db.execute(
                "SELECT COUNT(*) FROM pipeline_runs WHERE model_id=?",
                (model["id"],),
            ).fetchone()[0]
        return models
    finally:
        db.close()


@app.get("/api/models/{model_id}")
def get_model(model_id: int):
    db = get_db()
    try:
        model = row_to_dict(db.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone())
        if not model:
            raise HTTPException(404, "Model not found")
        model["runs"] = rows_to_list(
            db.execute(
                "SELECT * FROM pipeline_runs WHERE model_id=? ORDER BY created_at DESC",
                (model_id,),
            ).fetchall()
        )
        model["incidents"] = rows_to_list(
            db.execute(
                "SELECT * FROM incidents WHERE model_id=? ORDER BY created_at DESC",
                (model_id,),
            ).fetchall()
        )
        model["projects"] = rows_to_list(
            db.execute(
                "SELECT id, name, root_path, config_status, updated_at FROM projects WHERE model_id=?",
                (model_id,),
            ).fetchall()
        )
        return model
    finally:
        db.close()


@app.post("/api/models", status_code=201)
def create_model(model: ModelCreate):
    db = get_db()
    try:
        cursor = db.execute(
            """
            INSERT INTO models (name, repo_id, parameters, architecture, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                model.name,
                model.repo_id,
                model.parameters,
                model.architecture,
                model.description,
                utc_now_iso(),
            ),
        )
        model_id = cursor.lastrowid
        log_activity(db, "model_registered", f"{model.name} registered", model_id)
        db.commit()
        return row_to_dict(db.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone())
    finally:
        db.close()


@app.get("/api/projects")
def list_projects():
    db = get_db()
    try:
        rows = rows_to_list(db.execute("SELECT id FROM projects ORDER BY updated_at DESC, id DESC").fetchall())
        return [load_project_detail(db, row["id"]) for row in rows]
    finally:
        db.close()


@app.post("/api/projects", status_code=201)
def create_project(project: ProjectCreate):
    root_path = ensure_absolute_project_root(project.root_path)
    config_path = root_path / "kiln.yaml"
    db = get_db()
    try:
        existing = db.execute(
            "SELECT id FROM projects WHERE root_path=?",
            (str(root_path),),
        ).fetchone()
        if existing:
            raise HTTPException(409, "Project already exists")

        if not config_path.exists():
            write_project_config(config_path, default_project_config(root_path))
        cursor = db.execute(
            """
            INSERT INTO projects (name, root_path, config_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                root_path.name,
                str(root_path),
                str(config_path),
                utc_now_iso(),
                utc_now_iso(),
            ),
        )
        project_id = cursor.lastrowid
        db.commit()
        return sync_project_record(db, project_id, create_default_if_missing=True)
    finally:
        db.close()


@app.get("/api/projects/{project_id}")
def get_project(project_id: int):
    db = get_db()
    try:
        return load_project_detail(db, project_id)
    finally:
        db.close()


@app.put("/api/projects/{project_id}/config")
def update_project_config(project_id: int, config: ProjectConfig):
    db = get_db()
    try:
        project = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
        if not project:
            raise HTTPException(404, "Project not found")
        write_project_config(Path(project["config_path"]), config)
        updated = sync_project_record(db, project_id, create_default_if_missing=False)
        if updated["config_status"] != "valid":
            raise HTTPException(422, updated["config_error"])
        return updated
    finally:
        db.close()


@app.post("/api/projects/{project_id}/sync")
def sync_project(project_id: int):
    db = get_db()
    try:
        return sync_project_record(db, project_id, create_default_if_missing=False)
    finally:
        db.close()


@app.post("/api/projects/{project_id}/runs", status_code=201)
def start_project_run(project_id: int, payload: Optional[ProjectRunCreate] = None):
    db = get_db()
    try:
        project = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
        if not project:
            raise HTTPException(404, "Project not found")
        config = load_project_config_from_path(Path(project["config_path"]))
        run, job = create_project_run(
            db,
            project,
            config,
            candidate_name=payload.candidate_name if payload else None,
        )
        if JOB_RUNNER is None:
            raise HTTPException(503, "Job runner is not available")
        queued_jobs = rows_to_list(
            db.execute(
                "SELECT id FROM jobs WHERE run_id=? AND status='queued' ORDER BY id",
                (run["id"],),
            ).fetchall()
        )
        for queued_job in queued_jobs:
            JOB_RUNNER.enqueue(queued_job["id"])
        return {"run": run, "job": job}
    finally:
        db.close()


@app.get("/api/runs")
def list_runs(model_id: Optional[int] = None, status: Optional[str] = None):
    db = get_db()
    try:
        query = """
            SELECT pr.*, m.name AS model_name, p.name AS project_name
            FROM pipeline_runs pr
            JOIN models m ON pr.model_id=m.id
            LEFT JOIN projects p ON pr.project_id=p.id
            WHERE 1=1
        """
        params = []
        if model_id:
            query += " AND pr.model_id=?"
            params.append(model_id)
        if status:
            query += " AND pr.status=?"
            params.append(status)
        query += " ORDER BY pr.created_at DESC"
        return rows_to_list(db.execute(query, params).fetchall())
    finally:
        db.close()


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    db = get_db()
    try:
        run = get_run_with_stages(db, run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        return run
    finally:
        db.close()


@app.get("/api/runs/{run_id}/release-report")
def get_release_report(
    run_id: int,
    report_format: Literal["json", "markdown"] = Query("json", alias="format"),
):
    db = get_db()
    try:
        run = get_run_with_stages(db, run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        report = build_release_report(run)
        if report_format == "markdown":
            return PlainTextResponse(
                render_release_report_markdown(report),
                media_type="text/markdown",
            )
        return report
    finally:
        db.close()


@app.post("/api/runs/{run_id}/export-report")
def export_report(run_id: int):
    db = get_db()
    try:
        return {"run_id": run_id, "artifacts": write_report_artifacts(db, run_id)}
    finally:
        db.close()


@app.post("/api/runs", status_code=201)
def create_run(run: RunCreate):
    db = get_db()
    try:
        model = db.execute("SELECT * FROM models WHERE id=?", (run.model_id,)).fetchone()
        if not model:
            raise HTTPException(404, "Model not found")
        started_at = utc_now_iso()
        cursor = db.execute(
            """
            INSERT INTO pipeline_runs (model_id, status, mode, started_at, created_at, trigger)
            VALUES (?, 'running', ?, ?, ?, 'manual')
            """,
            (run.model_id, run.mode, started_at, started_at),
        )
        run_id = cursor.lastrowid
        for stage_key, stage_name, stage_order in STAGE_DEFINITIONS:
            logs = None
            if run.mode == "real" and stage_key not in REAL_INTEGRATIONS:
                logs = "Manual completion required in v0.2 real mode."
            db.execute(
                """
                INSERT INTO pipeline_stages (run_id, stage_key, stage_name, stage_order, logs)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, stage_key, stage_name, stage_order, logs),
            )
        log_activity(
            db,
            "run_started",
            f"Pipeline run #{run_id} started for {model['name']}",
            run.model_id,
            run_id,
        )
        db.commit()
        if run.mode == "mock":
            simulate_run(db, run_id)
        return row_to_dict(
            db.execute(
                """
                SELECT pr.*, m.name AS model_name
                FROM pipeline_runs pr
                JOIN models m ON pr.model_id=m.id
                WHERE pr.id=?
                """,
                (run_id,),
            ).fetchone()
        )
    finally:
        db.close()


@app.post("/api/runs/{run_id}/stages/{stage_key}/start")
def start_stage(run_id: int, stage_key: str):
    db = get_db()
    try:
        return mark_stage_running(db, run_id, stage_key)
    finally:
        db.close()


@app.post("/api/runs/{run_id}/stages/{stage_key}/complete")
def complete_stage(run_id: int, stage_key: str, update: StageUpdate):
    db = get_db()
    try:
        return apply_stage_completion(
            db,
            run_id,
            stage_key,
            update.status,
            results=update.results,
            logs=update.logs,
        )
    finally:
        db.close()


@app.get("/api/jobs")
def list_jobs():
    db = get_db()
    try:
        return rows_to_list(
            db.execute(
                """
                SELECT j.*, p.name AS project_name, pr.status AS run_status
                FROM jobs j
                JOIN projects p ON j.project_id=p.id
                JOIN pipeline_runs pr ON j.run_id=pr.id
                ORDER BY j.queued_at DESC, j.id DESC
                """
            ).fetchall()
        )
    finally:
        db.close()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    db = get_db()
    try:
        job = get_job_with_relations(db, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return job
    finally:
        db.close()


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    db = get_db()
    try:
        job = row_to_dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
        if not job:
            raise HTTPException(404, "Job not found")
    finally:
        db.close()

    if JOB_RUNNER is None:
        raise HTTPException(503, "Job runner is not available")
    if not JOB_RUNNER.cancel(job_id):
        raise HTTPException(409, "Job cannot be canceled")
    return {"status": "cancel_requested"}


@app.get("/api/incidents")
def list_incidents(model_id: Optional[int] = None, status: Optional[str] = None):
    db = get_db()
    try:
        query = """
            SELECT i.*, m.name AS model_name
            FROM incidents i
            JOIN models m ON i.model_id=m.id
            WHERE 1=1
        """
        params = []
        if model_id:
            query += " AND i.model_id=?"
            params.append(model_id)
        if status:
            query += " AND i.status=?"
            params.append(status)
        query += " ORDER BY i.created_at DESC"
        return rows_to_list(db.execute(query, params).fetchall())
    finally:
        db.close()


@app.post("/api/incidents", status_code=201)
def create_incident(incident: IncidentCreate):
    db = get_db()
    try:
        model = db.execute("SELECT id FROM models WHERE id=?", (incident.model_id,)).fetchone()
        if not model:
            raise HTTPException(404, "Model not found")
        cursor = db.execute(
            """
            INSERT INTO incidents (model_id, severity, title, description, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                incident.model_id,
                incident.severity,
                incident.title,
                incident.description,
                utc_now_iso(),
            ),
        )
        db.commit()
        return row_to_dict(db.execute("SELECT * FROM incidents WHERE id=?", (cursor.lastrowid,)).fetchone())
    finally:
        db.close()


@app.get("/api/activity")
def get_activity(limit: int = 30):
    db = get_db()
    try:
        return rows_to_list(
            db.execute(
                "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        )
    finally:
        db.close()


@app.post("/api/seed")
def reseed():
    if not seed_endpoint_enabled():
        raise HTTPException(403, "Seed endpoint is disabled")
    db = get_db()
    try:
        db.executescript(
            """
            DELETE FROM jobs;
            DELETE FROM activity_log;
            DELETE FROM pipeline_stages;
            DELETE FROM pipeline_runs;
            DELETE FROM projects;
            DELETE FROM incidents;
            DELETE FROM models;
            """
        )
        db.commit()
    finally:
        db.close()
    seed_demo_data()
    return {"status": "seeded"}


@app.get("/api/health")
def health():
    return {"status": "ok", "version": APP_VERSION, "name": "Kiln"}


@app.get("/")
def serve_index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/{filename}")
def serve_static(filename: str):
    if filename.startswith("api"):
        raise HTTPException(404)
    filepath = STATIC_DIR / filename
    if filepath.is_file() and not filename.startswith("."):
        return FileResponse(str(filepath))
    raise HTTPException(404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
