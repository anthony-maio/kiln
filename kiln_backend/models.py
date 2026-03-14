from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR
CONFIG_FILENAME = "kiln.yaml"
APP_VERSION = "0.3.0-rc1"

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
PROJECT_REAL_INTEGRATIONS = {
    "benchmarks": "lm-eval-harness adapter",
    "documentation": "repo documentation executor",
    "packaging": "artifact packaging executor",
    "serving": "runtime smoke executor",
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
PROJECT_STAGE_DEFINITIONS = [
    ("benchmarks", "Academic Benchmarks", 1),
    ("safety", "Safety Evaluation", 2),
    ("documentation", "Documentation", 3),
    ("packaging", "Packaging & Distribution", 4),
    ("serving", "Inference Serving", 5),
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


class ProjectRunCreate(StrictModel):
    candidate_name: Optional[str] = None


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


class CandidateBenchmarksConfig(BenchmarksConfig):
    pass


class CandidateServingConfig(StrictModel):
    enabled: bool = False
    runtime: Optional[Literal["vllm", "sglang", "llama_cpp"]] = None
    model_args: Optional[str] = None
    startup_timeout_seconds: int = Field(default=120, ge=1)
    smoke_prompts: list[str] = Field(default_factory=list)
    max_latency_ms: Optional[int] = Field(default=None, ge=1)


class SafetyCaseConfig(StrictModel):
    name: str
    prompt: str
    required_substrings: list[str] = Field(default_factory=list)
    forbidden_substrings: list[str] = Field(default_factory=list)


class SafetyConfig(StrictModel):
    provider: Literal["prompt_suite"]
    max_violations: int = Field(default=0, ge=0)
    startup_timeout_seconds: int = Field(default=120, ge=1)
    cases: list[SafetyCaseConfig] = Field(min_length=1)


class CandidateConfig(StrictModel):
    name: str
    format: Literal["hf", "gguf"]
    path: str
    runtime: Optional[Literal["vllm", "sglang", "llama_cpp"]] = None
    benchmarks: CandidateBenchmarksConfig
    serving: CandidateServingConfig = Field(default_factory=CandidateServingConfig)

    @model_validator(mode="after")
    def validate_runtime_overrides(self):
        allowed_runtimes = {
            "hf": {"vllm", "sglang"},
            "gguf": {"llama_cpp"},
        }[self.format]

        if self.runtime and self.runtime not in allowed_runtimes:
            raise ValueError(
                f"runtime {self.runtime!r} is not valid for candidate format {self.format!r}"
            )

        if self.serving.runtime and self.serving.runtime not in allowed_runtimes:
            raise ValueError(
                f"serving runtime {self.serving.runtime!r} is not valid for candidate format {self.format!r}"
            )

        if self.runtime and self.serving.runtime and self.runtime != self.serving.runtime:
            raise ValueError("candidate runtime and serving runtime must match when both are set")

        return self


class ProjectConfig(StrictModel):
    version: Literal[1, 2]
    model: ProjectModelConfig
    benchmarks: Optional[BenchmarksConfig] = None
    safety: Optional[SafetyConfig] = None
    manual_stages: Optional[ManualStagesConfig] = None
    candidates: Optional[list[CandidateConfig]] = None
    report: ReportConfig

    @model_validator(mode="after")
    def validate_versioned_shape(self):
        if self.version == 1:
            if self.benchmarks is None or self.manual_stages is None:
                raise ValueError("version 1 config requires benchmarks and manual_stages")
            return self

        if not self.candidates:
            raise ValueError("version 2 config requires at least one candidate")

        return self

