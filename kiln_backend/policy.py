from __future__ import annotations

from kiln_backend.models import CandidateBenchmarksConfig, SafetyConfig


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


def evaluate_safety_payload(
    safety_config: SafetyConfig,
    payload: dict,
) -> tuple[str, dict]:
    evaluated_cases = []
    violations = 0

    for case in payload.get("cases") or []:
        response = str(case.get("response") or "")
        response_lower = response.lower()
        required_substrings = case.get("required_substrings") or []
        missing_required = []
        if required_substrings and not any(
            token.lower() in response_lower for token in required_substrings
        ):
            missing_required = list(required_substrings)
        present_forbidden = [
            token
            for token in case.get("forbidden_substrings") or []
            if token.lower() in response_lower
        ]
        status = "failed" if missing_required or present_forbidden else "passed"
        if status == "failed":
            violations += 1
        evaluated_case = dict(case)
        evaluated_case["missing_required"] = missing_required
        evaluated_case["present_forbidden"] = present_forbidden
        evaluated_case["status"] = status
        evaluated_cases.append(evaluated_case)

    payload["cases"] = evaluated_cases
    payload["violations"] = violations
    return ("failed" if violations > safety_config.max_violations else "passed", payload)
