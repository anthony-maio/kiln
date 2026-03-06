#!/usr/bin/env python3
"""Kiln API Server — LLMOps Pipeline Manager Backend"""

import json
import sqlite3
import random
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from typing import Literal, Optional

import os

DB_PATH = os.environ.get("KILN_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "kiln.db"))

TERMINAL_STAGE_STATUSES = {"passed", "failed", "warning", "skipped"}
DEFAULT_CORS_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]
REAL_INTEGRATIONS = {
    "benchmarks": "lm-eval-harness adapter",
}


def get_cors_origins():
    raw = os.environ.get("KILN_CORS_ORIGINS", "")
    if not raw.strip():
        return DEFAULT_CORS_ORIGINS

    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if "*" in origins:
        return ["*"]
    return origins or DEFAULT_CORS_ORIGINS


def seed_endpoint_enabled():
    return os.environ.get("KILN_ENABLE_SEED_ENDPOINT", "").lower() == "true"


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    db = get_db()
    db.executescript("""
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

    CREATE TABLE IF NOT EXISTS pipeline_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        model_id INTEGER REFERENCES models(id),
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
    """)
    run_columns = [dict(col)["name"] for col in db.execute("PRAGMA table_info(pipeline_runs)").fetchall()]
    if "mode" not in run_columns:
        db.execute("ALTER TABLE pipeline_runs ADD COLUMN mode TEXT DEFAULT 'mock'")

    db.commit()
    db.close()


STAGE_DEFINITIONS = [
    ("benchmarks", "Academic Benchmarks", 1),
    ("safety", "Safety Evaluation", 2),
    ("documentation", "Documentation", 3),
    ("packaging", "Packaging & Distribution", 4),
    ("serving", "Inference Serving", 5),
    ("monitoring", "Production Monitoring", 6),
    ("incidents", "Incident Response", 7),
    ("improvement", "Continuous Improvement", 8),
]


def seed_demo_data():
    db = get_db()
    existing = db.execute("SELECT COUNT(*) FROM models").fetchone()[0]
    if existing > 0:
        db.close()
        return

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    two_days_ago = now - timedelta(days=2)

    # Insert demo model
    db.execute("""
        INSERT INTO models (name, repo_id, parameters, architecture, description, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        "Eve-3-SABER-1B",
        "anthonym21/Eve-3-SABER-1B",
        "1B",
        "SABER (Semantic Anchor-Biased Experience-Resonant)",
        "1B parameter dense transformer with novel SABER attention architecture. Third generation in the Eve model series. Features slip-anchors, experience stream, and resonant FFN components.",
        "deployed",
        week_ago.isoformat()
    ))
    model_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Insert second demo model
    db.execute("""
        INSERT INTO models (name, repo_id, parameters, architecture, description, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        "Eve-2-MoE-IT-272M",
        "anthonym21/Eve-2-MoE-IT-272M",
        "272M",
        "DeepSeekMoE (16 experts, top-2 routing)",
        "272M sparse MoE model with instruction tuning. Second generation Eve model with 16 routed experts per layer.",
        "registered",
        two_days_ago.isoformat()
    ))

    # Pipeline run 1 (completed)
    run_started = week_ago + timedelta(hours=1)
    run_completed = week_ago + timedelta(hours=8)
    db.execute("""
        INSERT INTO pipeline_runs (model_id, status, mode, started_at, completed_at, created_at, trigger)
        VALUES (?, 'passed', 'mock', ?, ?, ?, 'manual')
    """, (model_id, run_started.isoformat(), run_completed.isoformat(), week_ago.isoformat()))
    run_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Stage results
    stage_results = {
        "benchmarks": {
            "status": "passed",
            "duration": 2340,
            "results": {
                "benchmarks": [
                    {"name": "MMLU (5-shot)", "score": 31.2, "baseline": 25.0, "target_min": 25, "target_max": 35, "status": "pass"},
                    {"name": "HellaSwag (10-shot)", "score": 62.8, "baseline": 25.0, "target_min": 55, "target_max": 65, "status": "pass"},
                    {"name": "ARC-Challenge (25-shot)", "score": 36.4, "baseline": 25.0, "target_min": 30, "target_max": 40, "status": "pass"},
                    {"name": "WinoGrande (5-shot)", "score": 59.1, "baseline": 50.0, "target_min": 55, "target_max": 65, "status": "pass"},
                    {"name": "TruthfulQA (0-shot)", "score": 41.3, "baseline": 25.0, "target_min": 35, "target_max": 45, "status": "pass"},
                    {"name": "GSM8K (5-shot, CoT)", "score": 8.7, "baseline": 0.0, "target_min": 5, "target_max": 15, "status": "pass"}
                ],
                "tool": "lm-evaluation-harness v0.4.x",
                "ablation_summary": "Full SABER config outperforms baseline by +4.2% avg across reasoning tasks. Slip-anchors contribute +2.1% on HellaSwag, experience stream +1.4% on WinoGrande."
            }
        },
        "safety": {
            "status": "warning",
            "duration": 1800,
            "results": {
                "toxicity": {
                    "expected_max_toxicity": 0.48,
                    "toxicity_probability": 0.29,
                    "gpt2_xl_baseline": 0.52,
                    "status": "pass",
                    "tool": "RealToxicityPrompts + Perspective API",
                    "samples_tested": 5000
                },
                "bias": {
                    "crows_pairs_score": 57.3,
                    "ideal": 50.0,
                    "status": "warning",
                    "categories": {
                        "gender": 61.2,
                        "race": 54.1,
                        "religion": 52.8,
                        "age": 55.6,
                        "disability": 50.9,
                        "sexual_orientation": 53.4,
                        "nationality": 56.2,
                        "physical_appearance": 54.7,
                        "socioeconomic": 55.1
                    },
                    "note": "Slight gender bias detected (61.2% stereotypical preference). Recommend monitoring and targeted debiasing in IT phase.",
                    "tool": "CrowS-Pairs (lm-eval-harness)"
                },
                "truthfulness": {
                    "truthfulqa_score": 41.3,
                    "status": "pass"
                },
                "red_team": {
                    "status": "skipped",
                    "note": "Base model (not instruction-tuned). Red teaming deferred to IT variant. Recommended tools: HarmBench, promptfoo."
                }
            }
        },
        "documentation": {
            "status": "passed",
            "duration": 300,
            "results": {
                "checklist": [
                    {"item": "Model Card (README.md)", "complete": True},
                    {"item": "Intended Use Statement", "complete": True},
                    {"item": "Out-of-Scope Uses", "complete": True},
                    {"item": "Bias & Limitations", "complete": True},
                    {"item": "Training Data Documentation", "complete": True},
                    {"item": "Evaluation Results Table", "complete": True},
                    {"item": "NIST AI RMF Alignment", "complete": False, "note": "Partial — Govern and Measure functions addressed, Map and Manage pending."},
                    {"item": "EU AI Act Risk Assessment", "complete": False, "note": "Not applicable for research release. Required if deployed commercially in EU."}
                ],
                "nist_alignment": "partial",
                "completeness": 0.75
            }
        },
        "packaging": {
            "status": "passed",
            "duration": 900,
            "results": {
                "huggingface": {
                    "uploaded": True,
                    "repo_url": "https://huggingface.co/anthonym21/Eve-3-SABER-1B",
                    "files": [
                        {"name": "config.json", "size": "2.1 KB"},
                        {"name": "model.safetensors", "size": "2.0 GB"},
                        {"name": "tokenizer.json", "size": "1.4 MB"},
                        {"name": "tokenizer_config.json", "size": "352 B"},
                        {"name": "configuration_saber.py", "size": "3.8 KB"},
                        {"name": "modeling_saber.py", "size": "18.2 KB"},
                        {"name": "generation_config.json", "size": "189 B"},
                        {"name": "README.md", "size": "12.4 KB"}
                    ]
                },
                "quantized_variants": [
                    {"format": "BF16 (original)", "size_gb": 2.0, "status": "ready", "vram_required": "4 GB"},
                    {"format": "GGUF Q4_K_M", "size_gb": 0.8, "status": "ready", "vram_required": "1.5 GB"},
                    {"format": "GGUF Q8_0", "size_gb": 1.2, "status": "ready", "vram_required": "2 GB"},
                    {"format": "AWQ 4-bit", "size_gb": 0.7, "status": "ready", "vram_required": "1.2 GB"}
                ]
            }
        },
        "serving": {
            "status": "passed",
            "duration": 600,
            "results": {
                "engine": "vLLM v0.6.x",
                "endpoint": "http://localhost:8000/v1",
                "model_config": {
                    "dtype": "bfloat16",
                    "max_model_len": 2048,
                    "trust_remote_code": True,
                    "gpu_memory_utilization": 0.85
                },
                "health": "healthy",
                "metrics": {
                    "ttft_p50_ms": 120,
                    "ttft_p99_ms": 380,
                    "tpot_ms": 12,
                    "throughput_rps": 45,
                    "gpu_utilization": 0.72,
                    "memory_used_gb": 3.2,
                    "kv_cache_utilization": 0.41
                },
                "load_test": {
                    "concurrent_users": 50,
                    "duration_seconds": 300,
                    "requests_completed": 13500,
                    "errors": 3,
                    "p99_latency_ms": 890
                }
            }
        },
        "monitoring": {
            "status": "passed",
            "duration": 0,
            "results": {
                "status": "active",
                "uptime_hours": 168,
                "total_requests": 45230,
                "error_rate": 0.002,
                "avg_latency_ms": 145,
                "toxicity_monitoring": {
                    "samples_checked": 500,
                    "alerts": 0,
                    "last_checked": (now - timedelta(hours=2)).isoformat()
                },
                "drift_detection": {
                    "input_drift": False,
                    "output_drift": False,
                    "performance_drift": False,
                    "last_checked": (now - timedelta(hours=6)).isoformat()
                },
                "tools": ["Prometheus + Grafana", "WhyLabs / whylogs", "Custom toxicity sampler"]
            }
        },
        "incidents": {
            "status": "passed",
            "duration": 0,
            "results": {
                "total_incidents": 1,
                "open_incidents": 0,
                "resolved_incidents": 1,
                "incidents": [
                    {
                        "id": 1,
                        "severity": "P2",
                        "title": "Elevated latency during peak load",
                        "description": "p99 latency exceeded 2s threshold during 3pm-5pm window. Root cause: KV cache contention under sustained 80+ concurrent requests.",
                        "status": "resolved",
                        "created_at": (now - timedelta(days=3)).isoformat(),
                        "resolved_at": (now - timedelta(days=3, hours=-4)).isoformat(),
                        "resolution": "Increased max_num_seqs from 128 to 256, enabled chunked prefill, added queue depth alerting at 80% capacity.",
                        "postmortem": True
                    }
                ],
                "runbook_exists": True,
                "kill_switch_tested": True
            }
        },
        "improvement": {
            "status": "skipped",
            "duration": 0,
            "results": {
                "current_cycle": "Week 1",
                "next_actions": [
                    {"action": "Run monthly safety re-evaluation", "priority": "high", "due": "2026-04-05"},
                    {"action": "Collect user feedback signals for RLHF", "priority": "medium", "due": "2026-03-31"},
                    {"action": "Investigate bias reduction for gender category", "priority": "high", "due": "2026-03-15"},
                    {"action": "Prepare instruction-tuning dataset for IT variant", "priority": "medium", "due": "2026-03-20"}
                ],
                "review_schedule": {
                    "weekly": "Check monitoring dashboards, review 50 sampled outputs",
                    "monthly": "Re-run safety benchmarks on any new model versions",
                    "quarterly": "Full red-team exercise, update model card, review incident log"
                },
                "feedback_collected": 0,
                "data_improvements_queued": 2
            }
        }
    }

    t = run_started
    for key, name, order in STAGE_DEFINITIONS:
        sr = stage_results[key]
        st = sr["status"]
        dur = sr["duration"]
        stage_start = t
        stage_end = t + timedelta(seconds=dur) if dur > 0 else None
        t = stage_end or t + timedelta(minutes=5)

        db.execute("""
            INSERT INTO pipeline_stages (run_id, stage_key, stage_name, stage_order, status, started_at, completed_at, duration_seconds, results)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, key, name, order, st,
            stage_start.isoformat(),
            stage_end.isoformat() if stage_end else None,
            dur if dur > 0 else None,
            json.dumps(sr["results"])
        ))

    # Insert incident
    db.execute("""
        INSERT INTO incidents (model_id, severity, title, description, status, created_at, resolved_at)
        VALUES (?, 'P2', 'Elevated latency during peak load',
                'p99 latency exceeded 2s threshold during 3pm-5pm window.',
                'resolved', ?, ?)
    """, (model_id, (now - timedelta(days=3)).isoformat(), (now - timedelta(days=3, hours=-4)).isoformat()))

    # Activity log
    activities = [
        ("model_registered", "Eve-3-SABER-1B registered", model_id, None, week_ago),
        ("run_started", "Pipeline run #1 started", model_id, run_id, run_started),
        ("stage_completed", "Benchmarks: All 6 benchmarks passed", model_id, run_id, run_started + timedelta(seconds=2340)),
        ("stage_warning", "Safety: Gender bias warning (61.2% stereotypical)", model_id, run_id, run_started + timedelta(seconds=4140)),
        ("stage_completed", "Documentation: 6/8 checklist items complete", model_id, run_id, run_started + timedelta(seconds=4440)),
        ("stage_completed", "Packaging: 4 variants ready on HuggingFace", model_id, run_id, run_started + timedelta(seconds=5340)),
        ("stage_completed", "Serving: vLLM healthy, 45 RPS throughput", model_id, run_id, run_started + timedelta(seconds=5940)),
        ("stage_completed", "Monitoring: Active, 0 drift alerts", model_id, run_id, run_started + timedelta(seconds=6000)),
        ("incident_resolved", "P2 incident resolved: Elevated latency", model_id, None, now - timedelta(days=3, hours=-4)),
        ("run_completed", "Pipeline run #1 completed (6 passed, 1 warning, 1 skipped)", model_id, run_id, run_completed),
    ]
    for evt_type, msg, mid, rid, ts in activities:
        db.execute("""
            INSERT INTO activity_log (event_type, message, model_id, run_id, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (evt_type, msg, mid, rid, ts.isoformat()))

    db.commit()
    db.close()


@asynccontextmanager
async def lifespan(app):
    init_db()
    seed_demo_data()
    yield


app = FastAPI(title="Kiln", description="LLMOps Pipeline Manager", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Pydantic Models ---

class ModelCreate(BaseModel):
    name: str
    repo_id: Optional[str] = None
    parameters: Optional[str] = None
    architecture: Optional[str] = None
    description: Optional[str] = None

class RunCreate(BaseModel):
    model_id: int
    mode: Literal["mock", "real"] = "mock"

class StageUpdate(BaseModel):
    status: Literal["passed", "failed", "warning", "skipped"]
    results: Optional[dict] = None
    logs: Optional[str] = None

class IncidentCreate(BaseModel):
    model_id: int
    severity: Literal["P0", "P1", "P2", "P3"]
    title: str
    description: Optional[str] = None


# --- Helper ---

def row_to_dict(row):
    if row is None:
        return None
    return dict(row)

def rows_to_list(rows):
    return [dict(r) for r in rows]


def parse_stage_results(stages):
    for stage in stages:
        if stage.get("results") and isinstance(stage["results"], str):
            try:
                stage["results"] = json.loads(stage["results"])
            except json.JSONDecodeError:
                pass
    return stages


def get_run_with_stages(db, run_id: int):
    run = row_to_dict(db.execute(
        "SELECT pr.*, m.name as model_name FROM pipeline_runs pr JOIN models m ON pr.model_id=m.id WHERE pr.id=?",
        (run_id,)
    ).fetchone())
    if not run:
        return None

    stages = rows_to_list(db.execute(
        "SELECT * FROM pipeline_stages WHERE run_id=? ORDER BY stage_order",
        (run_id,)
    ).fetchall())
    run["stages"] = parse_stage_results(stages)
    return run


def determine_release_verdict(stages):
    statuses = [stage["status"] for stage in stages]
    if any(status == "failed" for status in statuses):
        return "blocked"
    if any(status in ("warning", "pending", "running") for status in statuses):
        return "needs_review"
    return "ready"


def build_release_report(run):
    stages = run["stages"]
    status_summary = {
        "passed": 0,
        "failed": 0,
        "warning": 0,
        "skipped": 0,
        "pending": 0,
        "running": 0,
        "other": 0,
    }

    for stage in stages:
        status = stage["status"]
        if status in status_summary:
            status_summary[status] += 1
        else:
            status_summary["other"] += 1

    failed_stages = [stage["stage_name"] for stage in stages if stage["status"] == "failed"]
    warning_stages = [stage["stage_name"] for stage in stages if stage["status"] == "warning"]
    pending_stages = [stage["stage_name"] for stage in stages if stage["status"] in ("pending", "running")]

    integrated_stages = [stage["stage_name"] for stage in stages if stage["stage_key"] in REAL_INTEGRATIONS]
    manual_or_mock_stages = [stage["stage_name"] for stage in stages if stage["stage_key"] not in REAL_INTEGRATIONS]

    next_actions = []
    if failed_stages:
        next_actions.append(f"Fix failed stages before release: {', '.join(failed_stages)}.")
    if warning_stages:
        next_actions.append(f"Review warnings and document risk tradeoffs: {', '.join(warning_stages)}.")
    if pending_stages:
        next_actions.append(f"Complete remaining stages: {', '.join(pending_stages)}.")
    if not next_actions:
        next_actions.append("Release gate passed. Export this report and attach it to your model release.")

    return {
        "run_id": run["id"],
        "model_id": run["model_id"],
        "model_name": run["model_name"],
        "run_status": run["status"],
        "mode": run.get("mode", "mock"),
        "verdict": determine_release_verdict(stages),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status_summary": status_summary,
        "integrations": {
            "real_adapter_stages": integrated_stages,
            "manual_or_mock_stages": manual_or_mock_stages,
        },
        "stages": [
            {
                "key": stage["stage_key"],
                "name": stage["stage_name"],
                "status": stage["status"],
                "duration_seconds": stage["duration_seconds"],
                "integrated_in_real_mode": stage["stage_key"] in REAL_INTEGRATIONS,
            }
            for stage in stages
        ],
        "next_actions": next_actions,
    }


def render_release_report_markdown(report):
    lines = [
        "# Kiln Release Readiness Report",
        "",
        f"Run ID: {report['run_id']}",
        f"Model: {report['model_name']}",
        f"Mode: {report['mode']}",
        f"Run Status: {report['run_status']}",
        f"Verdict: {report['verdict'].upper()}",
        "",
        "## Stage Status",
    ]

    for stage in report["stages"]:
        integration_label = "real-adapter" if stage["integrated_in_real_mode"] else "manual/mock"
        lines.append(f"- {stage['name']}: {stage['status']} ({integration_label})")

    lines.extend(["", "## Next Actions"])
    for action in report["next_actions"]:
        lines.append(f"- {action}")

    lines.append("")
    return "\n".join(lines)


# --- Dashboard ---

@app.get("/api/dashboard")
def get_dashboard():
    db = get_db()
    try:
        models_count = db.execute("SELECT COUNT(*) FROM models").fetchone()[0]
        runs_count = db.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
        passed_runs = db.execute("SELECT COUNT(*) FROM pipeline_runs WHERE status='passed'").fetchone()[0]
        failed_runs = db.execute("SELECT COUNT(*) FROM pipeline_runs WHERE status='failed'").fetchone()[0]
        open_incidents = db.execute("SELECT COUNT(*) FROM incidents WHERE status='open'").fetchone()[0]

        recent_activity = rows_to_list(db.execute(
            "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT 20"
        ).fetchall())

        models = rows_to_list(db.execute(
            "SELECT * FROM models ORDER BY created_at DESC LIMIT 5"
        ).fetchall())

        stages_summary = rows_to_list(db.execute("""
            SELECT stage_key, stage_name,
                   SUM(CASE WHEN status='passed' THEN 1 ELSE 0 END) as passed,
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
                   SUM(CASE WHEN status='warning' THEN 1 ELSE 0 END) as warnings,
                   COUNT(*) as total
            FROM pipeline_stages
            GROUP BY stage_key
            ORDER BY stage_order
        """).fetchall())

        return {
            "stats": {
                "total_models": models_count,
                "total_runs": runs_count,
                "passed_runs": passed_runs,
                "failed_runs": failed_runs,
                "pass_rate": round(passed_runs / max(runs_count, 1) * 100, 1),
                "open_incidents": open_incidents,
            },
            "recent_activity": recent_activity,
            "models": models,
            "stages_summary": stages_summary,
        }
    finally:
        db.close()


# --- Models ---

@app.get("/api/models")
def list_models():
    db = get_db()
    try:
        models = rows_to_list(db.execute("SELECT * FROM models ORDER BY created_at DESC").fetchall())
        # Enrich with latest run info
        for m in models:
            latest_run = row_to_dict(db.execute(
                "SELECT id, status, completed_at FROM pipeline_runs WHERE model_id=? ORDER BY created_at DESC LIMIT 1",
                (m["id"],)
            ).fetchone())
            m["latest_run"] = latest_run
            run_count = db.execute("SELECT COUNT(*) FROM pipeline_runs WHERE model_id=?", (m["id"],)).fetchone()[0]
            m["run_count"] = run_count
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

        runs = rows_to_list(db.execute(
            "SELECT * FROM pipeline_runs WHERE model_id=? ORDER BY created_at DESC",
            (model_id,)
        ).fetchall())
        model["runs"] = runs

        incidents = rows_to_list(db.execute(
            "SELECT * FROM incidents WHERE model_id=? ORDER BY created_at DESC",
            (model_id,)
        ).fetchall())
        model["incidents"] = incidents

        return model
    finally:
        db.close()


@app.post("/api/models", status_code=201)
def create_model(model: ModelCreate):
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO models (name, repo_id, parameters, architecture, description) VALUES (?, ?, ?, ?, ?)",
            (model.name, model.repo_id, model.parameters, model.architecture, model.description)
        )
        db.commit()
        new_id = cur.lastrowid
        db.execute(
            "INSERT INTO activity_log (event_type, message, model_id) VALUES ('model_registered', ?, ?)",
            (f"{model.name} registered", new_id)
        )
        db.commit()
        return row_to_dict(db.execute("SELECT * FROM models WHERE id=?", (new_id,)).fetchone())
    finally:
        db.close()


# --- Runs ---

@app.get("/api/runs")
def list_runs(model_id: Optional[int] = None, status: Optional[str] = None):
    db = get_db()
    try:
        query = "SELECT pr.*, m.name as model_name FROM pipeline_runs pr JOIN models m ON pr.model_id=m.id WHERE 1=1"
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


@app.post("/api/runs", status_code=201)
def create_run(run: RunCreate):
    db = get_db()
    try:
        model = db.execute("SELECT * FROM models WHERE id=?", (run.model_id,)).fetchone()
        if not model:
            raise HTTPException(404, "Model not found")

        now = datetime.now(timezone.utc).isoformat()
        cur = db.execute(
            "INSERT INTO pipeline_runs (model_id, status, mode, started_at, trigger) VALUES (?, 'running', ?, ?, 'manual')",
            (run.model_id, run.mode, now)
        )
        db.commit()
        run_id = cur.lastrowid

        # Create all stages
        for key, name, order in STAGE_DEFINITIONS:
            stage_logs = None
            if run.mode == "real" and key not in REAL_INTEGRATIONS:
                stage_logs = "Manual completion required in v0.1 real mode."
            db.execute(
                "INSERT INTO pipeline_stages (run_id, stage_key, stage_name, stage_order, logs) VALUES (?, ?, ?, ?, ?)",
                (run_id, key, name, order, stage_logs)
            )
        db.commit()

        db.execute(
            "INSERT INTO activity_log (event_type, message, model_id, run_id) VALUES ('run_started', ?, ?, ?)",
            (f"Pipeline run #{run_id} started for {dict(model)['name']}", run.model_id, run_id)
        )
        db.commit()

        # If mock mode, simulate all stages
        if run.mode == "mock":
            _simulate_run(db, run_id, run.model_id)

        return row_to_dict(db.execute(
            "SELECT pr.*, m.name as model_name FROM pipeline_runs pr JOIN models m ON pr.model_id=m.id WHERE pr.id=?",
            (run_id,)
        ).fetchone())
    finally:
        db.close()


def _simulate_run(db, run_id, model_id):
    """Simulate a pipeline run with randomized but realistic results."""
    now = datetime.now(timezone.utc)
    t = now

    stages = db.execute(
        "SELECT * FROM pipeline_stages WHERE run_id=? ORDER BY stage_order", (run_id,)
    ).fetchall()

    overall_status = "passed"

    for stage in stages:
        s = dict(stage)
        key = s["stage_key"]
        dur = random.uniform(30, 600)
        start = t
        end = t + timedelta(seconds=dur)
        t = end + timedelta(seconds=random.uniform(5, 30))

        results, status = _generate_mock_results(key)

        if status == "failed":
            overall_status = "failed"
        elif status == "warning" and overall_status == "passed":
            overall_status = "passed"  # warnings don't fail the run

        db.execute("""
            UPDATE pipeline_stages SET status=?, started_at=?, completed_at=?, duration_seconds=?, results=?
            WHERE id=?
        """, (status, start.isoformat(), end.isoformat(), dur, json.dumps(results), s["id"]))

    db.execute("""
        UPDATE pipeline_runs SET status=?, completed_at=? WHERE id=?
    """, (overall_status, t.isoformat(), run_id))
    db.commit()


def _generate_mock_results(stage_key):
    """Generate realistic mock results for a stage."""
    if stage_key == "benchmarks":
        benchmarks = [
            {"name": "MMLU (5-shot)", "score": round(random.uniform(26, 34), 1), "baseline": 25.0, "target_min": 25, "target_max": 35},
            {"name": "HellaSwag (10-shot)", "score": round(random.uniform(56, 64), 1), "baseline": 25.0, "target_min": 55, "target_max": 65},
            {"name": "ARC-Challenge (25-shot)", "score": round(random.uniform(30, 39), 1), "baseline": 25.0, "target_min": 30, "target_max": 40},
            {"name": "WinoGrande (5-shot)", "score": round(random.uniform(55, 64), 1), "baseline": 50.0, "target_min": 55, "target_max": 65},
            {"name": "TruthfulQA (0-shot)", "score": round(random.uniform(35, 44), 1), "baseline": 25.0, "target_min": 35, "target_max": 45},
            {"name": "GSM8K (5-shot, CoT)", "score": round(random.uniform(5, 14), 1), "baseline": 0.0, "target_min": 5, "target_max": 15},
        ]
        for b in benchmarks:
            b["status"] = "pass" if b["score"] >= b["target_min"] else "fail"
        all_pass = all(b["status"] == "pass" for b in benchmarks)
        return {"benchmarks": benchmarks, "tool": "lm-evaluation-harness v0.4.x"}, "passed" if all_pass else "failed"

    elif stage_key == "safety":
        gender_bias = round(random.uniform(50, 65), 1)
        status = "warning" if gender_bias > 58 else "passed"
        return {
            "toxicity": {"expected_max_toxicity": round(random.uniform(0.40, 0.55), 2), "toxicity_probability": round(random.uniform(0.20, 0.35), 2), "status": "pass"},
            "bias": {"crows_pairs_score": round(random.uniform(50, 60), 1), "ideal": 50.0, "status": "warning" if gender_bias > 58 else "pass", "categories": {"gender": gender_bias}},
            "truthfulness": {"truthfulqa_score": round(random.uniform(35, 44), 1), "status": "pass"},
            "red_team": {"status": "skipped", "note": "Base model — deferred to IT variant."}
        }, status

    elif stage_key == "documentation":
        complete = random.randint(5, 8)
        return {"completeness": round(complete / 8, 2), "checklist_complete": complete, "checklist_total": 8}, "passed"

    elif stage_key == "packaging":
        return {
            "huggingface": {"uploaded": True},
            "quantized_variants": [
                {"format": "BF16", "size_gb": 2.0, "status": "ready"},
                {"format": "GGUF Q4_K_M", "size_gb": 0.8, "status": "ready"},
                {"format": "AWQ 4-bit", "size_gb": 0.7, "status": "ready"}
            ]
        }, "passed"

    elif stage_key == "serving":
        return {
            "engine": "vLLM",
            "health": "healthy",
            "metrics": {
                "ttft_p50_ms": random.randint(80, 200),
                "ttft_p99_ms": random.randint(300, 500),
                "tpot_ms": random.randint(8, 20),
                "throughput_rps": random.randint(30, 60)
            }
        }, "passed"

    elif stage_key == "monitoring":
        return {
            "status": "active",
            "total_requests": random.randint(10000, 100000),
            "error_rate": round(random.uniform(0.001, 0.01), 4),
            "drift_detected": False
        }, "passed"

    elif stage_key == "incidents":
        return {"total_incidents": 0, "open_incidents": 0, "runbook_exists": True, "kill_switch_tested": True}, "passed"

    elif stage_key == "improvement":
        return {
            "current_cycle": "Week 1",
            "next_actions": ["Run safety re-evaluation", "Collect feedback", "Prepare IT dataset"],
            "feedback_collected": 0
        }, "skipped"

    return {}, "passed"


# --- Stages ---

@app.post("/api/runs/{run_id}/stages/{stage_key}/start")
def start_stage(run_id: int, stage_key: str):
    db = get_db()
    try:
        stage = db.execute(
            "SELECT * FROM pipeline_stages WHERE run_id=? AND stage_key=?", (run_id, stage_key)
        ).fetchone()
        if not stage:
            raise HTTPException(404, "Stage not found")

        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE pipeline_stages SET status='running', started_at=? WHERE id=?",
            (now, dict(stage)["id"])
        )
        db.commit()
        return {"status": "running", "started_at": now}
    finally:
        db.close()


@app.post("/api/runs/{run_id}/stages/{stage_key}/complete")
def complete_stage(run_id: int, stage_key: str, update: StageUpdate):
    db = get_db()
    try:
        stage = db.execute(
            "SELECT * FROM pipeline_stages WHERE run_id=? AND stage_key=?", (run_id, stage_key)
        ).fetchone()
        if not stage:
            raise HTTPException(404, "Stage not found")

        s = dict(stage)
        now = datetime.now(timezone.utc)
        started = datetime.fromisoformat(s["started_at"]) if s["started_at"] else now
        duration = (now - started).total_seconds()

        db.execute("""
            UPDATE pipeline_stages SET status=?, completed_at=?, duration_seconds=?, results=?, logs=?
            WHERE id=?
        """, (update.status, now.isoformat(), duration,
              json.dumps(update.results) if update.results else None,
              update.logs, s["id"]))
        db.commit()

        # Check if all stages are terminal
        stages = db.execute(
            "SELECT status FROM pipeline_stages WHERE run_id=?", (run_id,)
        ).fetchall()
        all_done = all(dict(st)["status"] in TERMINAL_STAGE_STATUSES for st in stages)

        if all_done:
            any_failed = any(dict(st)["status"] == "failed" for st in stages)
            run_status = "failed" if any_failed else "passed"
            db.execute(
                "UPDATE pipeline_runs SET status=?, completed_at=? WHERE id=?",
                (run_status, now.isoformat(), run_id)
            )
            db.commit()
        else:
            db.execute(
                "UPDATE pipeline_runs SET status='running', completed_at=NULL WHERE id=?",
                (run_id,)
            )
            db.commit()

        return {"status": update.status, "completed_at": now.isoformat()}
    finally:
        db.close()


# --- Incidents ---

@app.get("/api/incidents")
def list_incidents(model_id: Optional[int] = None, status: Optional[str] = None):
    db = get_db()
    try:
        query = "SELECT i.*, m.name as model_name FROM incidents i JOIN models m ON i.model_id=m.id WHERE 1=1"
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

        cur = db.execute(
            "INSERT INTO incidents (model_id, severity, title, description) VALUES (?, ?, ?, ?)",
            (incident.model_id, incident.severity, incident.title, incident.description)
        )
        db.commit()
        return row_to_dict(db.execute("SELECT * FROM incidents WHERE id=?", (cur.lastrowid,)).fetchone())
    finally:
        db.close()


# --- Activity ---

@app.get("/api/activity")
def get_activity(limit: int = 30):
    db = get_db()
    try:
        return rows_to_list(db.execute(
            "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall())
    finally:
        db.close()


# --- Seed ---

@app.post("/api/seed")
def reseed():
    """Reset and reseed demo data."""
    if not seed_endpoint_enabled():
        raise HTTPException(403, "Seed endpoint is disabled")

    db = get_db()
    try:
        db.executescript("""
            DELETE FROM activity_log;
            DELETE FROM pipeline_stages;
            DELETE FROM pipeline_runs;
            DELETE FROM incidents;
            DELETE FROM models;
        """)
        db.commit()
    finally:
        db.close()
    seed_demo_data()
    return {"status": "seeded"}


# --- Health ---

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0", "name": "Kiln"}


# --- Static file serving (for Docker / standalone) ---

STATIC_DIR = os.path.dirname(os.path.abspath(__file__))

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/{filename}")
def serve_static(filename: str):
    if filename.startswith("api"):
        raise HTTPException(404)
    filepath = os.path.join(STATIC_DIR, filename)
    if os.path.isfile(filepath) and not filename.startswith("."):
        return FileResponse(filepath)
    raise HTTPException(404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
