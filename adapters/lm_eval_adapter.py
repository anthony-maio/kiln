#!/usr/bin/env python3
"""Run lm-eval-harness benchmarks and report results back to Kiln."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib import request


def api_post(url, payload):
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def find_latest_result_file(output_dir):
    candidates = list(Path(output_dir).rglob("*.json"))
    if not candidates:
        raise FileNotFoundError(f"No JSON result file found in {output_dir}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def parse_task_score(metrics):
    preferred = [
        "acc_norm,none",
        "acc,none",
        "exact_match,strict-match",
        "exact_match,none",
        "f1,none",
    ]
    for key in preferred:
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            return value

    for value in metrics.values():
        if isinstance(value, (int, float)):
            return value

    return None


def parse_lm_eval_results(results_path):
    with open(results_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    task_results = payload.get("results", {})
    benchmarks = []
    for task_name, metrics in task_results.items():
        if not isinstance(metrics, dict):
            continue

        score = parse_task_score(metrics)
        if score is None:
            continue

        normalized_score = score * 100 if score <= 1 else score
        benchmarks.append(
            {
                "name": task_name,
                "score": round(float(normalized_score), 2),
                "status": "pass",
            }
        )

    status = "passed" if benchmarks else "failed"
    return {
        "benchmarks": benchmarks,
        "tool": "lm-eval-harness",
        "result_file": str(results_path),
    }, status


def run_lm_eval(model_id, tasks, output_dir):
    if shutil.which("lm_eval") is None:
        raise RuntimeError(
            "lm_eval is not installed. Install optional adapter dependencies with "
            "'pip install -r requirements-adapter-lm-eval.txt'."
        )

    os.makedirs(output_dir, exist_ok=True)
    command = [
        "lm_eval",
        "--model",
        "hf",
        "--model_args",
        f"pretrained={model_id}",
        "--tasks",
        tasks,
        "--batch_size",
        "auto",
        "--output_path",
        output_dir,
    ]

    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return completed.returncode, completed.stdout, completed.stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", required=True, help="Hugging Face model id")
    parser.add_argument("--run-id", required=True, type=int, help="Kiln run id")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Kiln API base URL")
    parser.add_argument(
        "--tasks",
        default="mmlu,hellaswag,arc_challenge,winogrande,truthfulqa_mc2,gsm8k",
        help="Comma-separated lm-eval task list",
    )
    parser.add_argument("--output-dir", default="./eval_results", help="lm-eval output directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip lm_eval execution and only validate API wiring",
    )
    args = parser.parse_args()

    start_url = f"{args.api_url}/api/runs/{args.run_id}/stages/benchmarks/start"
    complete_url = f"{args.api_url}/api/runs/{args.run_id}/stages/benchmarks/complete"

    try:
        api_post(start_url, {})
    except Exception as exc:  # pragma: no cover - operational logging
        print(f"Failed to start benchmark stage: {exc}", file=sys.stderr)

    if args.dry_run:
        mock_results = {
            "benchmarks": [{"name": "dry_run", "score": 100.0, "status": "pass"}],
            "tool": "lm-eval-harness (dry-run)",
        }
        api_post(complete_url, {"status": "passed", "results": mock_results})
        print("Dry run completed.")
        return

    return_code, stdout, stderr = run_lm_eval(args.model_id, args.tasks, args.output_dir)
    if return_code != 0:
        api_post(
            complete_url,
            {
                "status": "failed",
                "results": {"tool": "lm-eval-harness", "benchmarks": []},
                "logs": stderr[-4000:],
            },
        )
        raise RuntimeError(f"lm_eval failed: {stderr}")

    result_file = find_latest_result_file(args.output_dir)
    results, status = parse_lm_eval_results(result_file)
    api_post(
        complete_url,
        {
            "status": status,
            "results": results,
            "logs": stdout[-4000:],
        },
    )
    print(f"Benchmarks reported for run {args.run_id}. Status: {status}")


if __name__ == "__main__":
    main()
