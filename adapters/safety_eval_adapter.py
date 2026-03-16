from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def normalize_key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


TARGET_METRIC_KEYS = {
    "macroasr",
    "asr",
    "successrate",
    "attacksuccessrate",
}


def find_success_rate(node: Any) -> float | None:
    if isinstance(node, (int, float)):
        return float(node)

    if isinstance(node, dict):
        for key, value in node.items():
            normalized = normalize_key(str(key))
            if normalized in TARGET_METRIC_KEYS:
                if isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, dict):
                    for nested_key in ("mean", "value", "score"):
                        nested = value.get(nested_key)
                        if isinstance(nested, (int, float)):
                            return float(nested)
            nested_result = find_success_rate(value)
            if nested_result is not None:
                return nested_result

    if isinstance(node, list):
        for item in node:
            nested_result = find_success_rate(item)
            if nested_result is not None:
                return nested_result

    return None


def normalize_report(raw_report: dict[str, Any], benchmarks: list[str]) -> dict[str, Any]:
    normalized = {
        "provider": "safety_eval",
        "benchmarks": [],
    }

    results_section = raw_report.get("results") if isinstance(raw_report.get("results"), dict) else {}
    for benchmark in benchmarks:
        benchmark_payload = None
        if isinstance(raw_report.get(benchmark), dict):
            benchmark_payload = raw_report[benchmark]
        elif isinstance(results_section.get(benchmark), dict):
            benchmark_payload = results_section[benchmark]
        else:
            benchmark_payload = raw_report

        normalized["benchmarks"].append(
            {
                "name": benchmark,
                "success_rate": find_success_rate(benchmark_payload),
                "raw_metrics": benchmark_payload,
            }
        )

    return normalized


def run_real_adapter(
    *,
    model_path: str,
    benchmarks: list[str],
    artifact_path: Path,
    model_input_template: str | None,
) -> None:
    safety_eval_root = os.environ.get("KILN_SAFETY_EVAL_PATH")
    if not safety_eval_root:
        raise RuntimeError(
            "KILN_SAFETY_EVAL_PATH is not set. Point it at a local checkout of allenai/safety-eval."
        )

    safety_eval_python = os.environ.get("KILN_SAFETY_EVAL_PYTHON", sys.executable)
    eval_script = Path(safety_eval_root) / "evaluation" / "eval.py"
    if not eval_script.exists():
        raise RuntimeError(f"safety-eval entrypoint not found: {eval_script}")

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kiln-safety-eval-") as temp_dir:
        report_path = Path(temp_dir) / "report.json"
        details_path = Path(temp_dir) / "details.json"
        persisted_report_path = artifact_path.parent / f"{artifact_path.stem}.raw-report.json"
        persisted_details_path = artifact_path.parent / f"{artifact_path.stem}.individual-results.json"
        command = [
            safety_eval_python,
            str(eval_script),
            "generators",
            "--use_vllm",
            "--model_name_or_path",
            model_path,
            "--tasks",
            ",".join(benchmarks),
            "--report_output_path",
            str(report_path),
            "--save_individual_results_path",
            str(details_path),
        ]
        if model_input_template:
            command.extend(["--model_input_template_path_or_name", model_input_template])

        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            raise RuntimeError("safety-eval harness returned a non-zero exit code")

        raw_report = json.loads(report_path.read_text(encoding="utf-8"))
        normalized = normalize_report(raw_report, benchmarks)
        shutil.copyfile(report_path, persisted_report_path)
        shutil.copyfile(details_path, persisted_details_path)
        normalized["raw_report_path"] = str(persisted_report_path)
        normalized["individual_results_path"] = str(persisted_details_path)
        artifact_path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")


def run_dry_run(*, benchmarks: list[str], artifact_path: Path) -> None:
    success_rate = float(os.environ.get("KILN_SAFETY_EVAL_DRY_RUN_SUCCESS_RATE", "0.05"))
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": "safety_eval",
        "benchmarks": [
            {
                "name": benchmark,
                "success_rate": round(success_rate, 4),
                "raw_metrics": {"macro ASR": round(success_rate, 4)},
            }
            for benchmark in benchmarks
        ],
        "raw_report_path": None,
        "individual_results_path": None,
    }
    artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run safety-eval and normalize its results for Kiln.")
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--artifact-path", required=True)
    parser.add_argument("--benchmarks", required=True)
    parser.add_argument("--model-input-template")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_path = Path(args.artifact_path).resolve()
    benchmarks = [item.strip() for item in args.benchmarks.split(",") if item.strip()]
    if not benchmarks:
        raise RuntimeError("At least one benchmark is required")

    if os.environ.get("KILN_SAFETY_EVAL_DRY_RUN", "").lower() == "true":
        run_dry_run(benchmarks=benchmarks, artifact_path=artifact_path)
        return 0

    run_real_adapter(
        model_path=args.model_path,
        benchmarks=benchmarks,
        artifact_path=artifact_path,
        model_input_template=args.model_input_template,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
