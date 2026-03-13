#!/usr/bin/env python3
"""Run lm-eval-harness benchmarks and report results."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib import request


def api_post(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def write_result_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def maybe_force_failure() -> None:
    if os.environ.get("KILN_LM_EVAL_FORCE_FAILURE", "").lower() == "true":
        raise RuntimeError("Forced lm-eval adapter failure")


def maybe_sleep_for_dry_run() -> None:
    seconds = os.environ.get("KILN_LM_EVAL_DRY_RUN_SLEEP_SECONDS", "").strip()
    if seconds:
        time.sleep(float(seconds))


def parse_task_score(metrics: dict) -> float | None:
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
            return float(value)
    for value in metrics.values():
        if isinstance(value, (int, float)):
            return float(value)
    return None


def parse_lm_eval_results(results_path: Path) -> tuple[dict, str]:
    payload = json.loads(results_path.read_text(encoding="utf-8"))
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


def find_latest_result_file(output_dir: Path) -> Path:
    candidates = list(output_dir.rglob("*.json"))
    if not candidates:
        raise FileNotFoundError(f"No JSON result file found in {output_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def run_lm_eval(args: argparse.Namespace) -> tuple[int, str, str]:
    if shutil.which("lm_eval") is None:
        raise RuntimeError(
            "lm_eval is not installed. Install optional adapter dependencies with "
            "'pip install -r requirements-adapter-lm-eval.txt'."
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "lm_eval",
        "--model",
        args.model,
        "--model_args",
        args.model_args or f"pretrained={args.model_id}",
        "--tasks",
        args.tasks,
        "--batch_size",
        args.batch_size,
        "--num_fewshot",
        str(args.num_fewshot),
        "--output_path",
        str(output_dir),
    ]
    if args.device:
        command.extend(["--device", args.device])
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return completed.returncode, completed.stdout, completed.stderr


def deliver_result(
    args: argparse.Namespace,
    payload: dict,
    *,
    start_stage: bool = False,
) -> None:
    if args.result_json:
        write_result_payload(Path(args.result_json), payload)
        return

    if not args.api_url or args.run_id is None:
        raise RuntimeError("Either --result-json or both --api-url and --run-id are required")

    if start_stage:
        try:
            api_post(f"{args.api_url}/api/runs/{args.run_id}/stages/benchmarks/start", {})
        except Exception:
            pass
    api_post(
        f"{args.api_url}/api/runs/{args.run_id}/stages/benchmarks/complete",
        payload,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", required=True, help="Hugging Face model id")
    parser.add_argument("--run-id", type=int, help="Kiln run id")
    parser.add_argument("--api-url", help="Kiln API base URL")
    parser.add_argument("--result-json", help="Write completion payload to this path instead of using the API")
    parser.add_argument("--tasks", default="mmlu,hellaswag,arc_challenge,winogrande,truthfulqa_mc2,gsm8k")
    parser.add_argument("--output-dir", default="./eval_results")
    parser.add_argument("--model", default="hf")
    parser.add_argument("--model-args")
    parser.add_argument("--device")
    parser.add_argument("--num-fewshot", type=int, default=0)
    parser.add_argument("--batch-size", default="auto")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dry_run = args.dry_run or os.environ.get("KILN_LM_EVAL_DRY_RUN", "").lower() == "true"

    try:
        maybe_force_failure()
        if dry_run:
            maybe_sleep_for_dry_run()
            benchmarks = []
            for task_name in [task.strip() for task in args.tasks.split(",") if task.strip()]:
                benchmarks.append({"name": task_name, "score": 100.0, "status": "pass"})
            payload = {
                "status": "passed",
                "results": {
                    "benchmarks": benchmarks,
                    "tool": "lm-eval-harness (dry-run)",
                },
                "logs": "Dry run completed.",
            }
            deliver_result(args, payload, start_stage=not args.result_json)
            return

        deliver_result(args, {"status": "running"}, start_stage=True)
        return_code, stdout, stderr = run_lm_eval(args)
        if return_code != 0:
            payload = {
                "status": "failed",
                "results": {"tool": "lm-eval-harness", "benchmarks": []},
                "logs": stderr[-4000:],
            }
            deliver_result(args, payload)
            raise RuntimeError(f"lm_eval failed: {stderr}")

        result_file = find_latest_result_file(Path(args.output_dir))
        results, status = parse_lm_eval_results(result_file)
        payload = {
            "status": status,
            "results": results,
            "logs": stdout[-4000:],
        }
        deliver_result(args, payload)
    except Exception as exc:
        if args.result_json:
            write_result_payload(
                Path(args.result_json),
                {
                    "status": "failed",
                    "results": {"tool": "lm-eval-harness", "benchmarks": []},
                    "logs": str(exc),
                },
            )
        else:
            raise


if __name__ == "__main__":
    main()
