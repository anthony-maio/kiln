from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR
CONFIG_FILENAME = "kiln.yaml"
APP_VERSION = "0.2.0"

DEFAULT_CORS_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]
TERMINAL_STAGE_STATUSES = {"passed", "failed", "warning", "skipped"}
JOB_TERMINAL_STATUSES = {"completed", "failed", "canceled"}
MANUAL_STAGE_KEYS = {
    "safety",
    "documentation",
    "packaging",
    "serving",
    "monitoring",
    "incidents",
    "improvement",
}
REAL_INTEGRATIONS = {
    "benchmarks": "lm-eval-harness adapter",
}
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
STAGE_NAME_BY_KEY = {key: name for key, name, _ in STAGE_DEFINITIONS}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelCreate(StrictModel):
    name: str
    repo_id: Optional[str] = None
    parameters: Optional[str] = None
    architecture: Optional[str] = None
    description: Optional[str] = None


class RunCreate(StrictModel):
    model_id: int
    mode: Literal["mock", "real"] = "mock"


class StageUpdate(StrictModel):
    status: Literal["passed", "failed", "warning", "skipped"]
    results: Optional[dict] = None
    logs: Optional[str] = None


class IncidentCreate(StrictModel):
    model_id: int
    severity: Literal["P0", "P1", "P2", "P3"]
    title: str
    description: Optional[str] = None


class ProjectCreate(StrictModel):
    root_path: str


class ProjectModelConfig(StrictModel):
    name: str
    repo_id: Optional[str] = None
    parameters: Optional[str] = None
    architecture: Optional[str] = None
    description: Optional[str] = None


class BenchmarkTaskConfig(StrictModel):
    name: str
    min_score: Optional[float] = Field(default=None, ge=0, le=1)


class BenchmarksConfig(StrictModel):
    provider: Literal["lm_eval"]
    model: str
    model_args: str
    tasks: list[BenchmarkTaskConfig]
    device: Optional[str] = None
    num_fewshot: int = Field(default=0, ge=0)
    batch_size: str = "auto"
    timeout_minutes: int = Field(default=120, ge=1, le=1440)


class ManualStagesConfig(StrictModel):
    safety: Literal["required", "skip"]
    documentation: Literal["required", "skip"]
    packaging: Literal["required", "skip"]
    serving: Literal["required", "skip"]
    monitoring: Literal["required", "skip"]
    incidents: Literal["required", "skip"]
    improvement: Literal["required", "skip"]


class ReportConfig(StrictModel):
    output_dir: str


class ProjectConfig(StrictModel):
    version: Literal[1]
    model: ProjectModelConfig
    benchmarks: BenchmarksConfig
    manual_stages: ManualStagesConfig
    report: ReportConfig

