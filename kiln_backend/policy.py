from __future__ import annotations

from kiln_backend.models import CandidateBenchmarksConfig


def evaluate_benchmark_payload(
    benchmarks_config: CandidateBenchmarksConfig,
    payload: dict,
) -> tuple[str, dict]:
    thresholds = {}
    for task in benchmarks_config.tasks:
        if task.min_score is not None:
            thresholds[task.name] = task.min_score * 100

    if not thresholds:
        return "warning", payload

    benchmarks = payload.get("benchmarks") or []
    matched = False
    any_failed = False

    for benchmark in benchmarks:
        name = benchmark.get("name")
        if name not in thresholds:
            continue
        matched = True
        score = float(benchmark.get("score", 0))
        benchmark["target_min"] = round(thresholds[name], 2)
        benchmark["status"] = "pass" if score >= thresholds[name] else "fail"
        if score < thresholds[name]:
            any_failed = True

    if not matched:
        return "warning", payload
    if any_failed:
        return "failed", payload
    return "passed", payload


def evaluate_documentation_payload(payload: dict) -> str:
    if payload.get("missing_required_files"):
        return "failed"
    if payload.get("missing_recommended_files") or payload.get("missing_recommended_sections"):
        return "warning"
    return "passed"


def evaluate_packaging_payload(payload: dict) -> str:
    if not payload.get("artifact_exists"):
        return "failed"
    if payload.get("missing_recommended_files"):
        return "warning"
    return "passed"
