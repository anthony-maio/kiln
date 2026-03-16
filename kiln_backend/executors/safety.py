from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib import request

from kiln_backend.executors.base import StageExecutionResult, stage_output_paths
from kiln_backend.models import CandidateConfig, SafetyConfig
from kiln_backend.policy import evaluate_safety_payload
from kiln_backend.runtimes import build_runtime_command, resolve_runtime_for_candidate


def find_free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_url(url: str, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with request.urlopen(url, timeout=1):
                return
        except Exception:
            time.sleep(0.1)
    raise TimeoutError(f"Safety probe timed out waiting for {url}")


def fetch_json(url: str) -> dict:
    with request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def post_chat_completion(url: str, body: dict) -> tuple[dict, float]:
    encoded = json.dumps(body).encode("utf-8")
    req = request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    latency_ms = (time.perf_counter() - started) * 1000
    return payload, latency_ms


def first_model_id(models_payload: dict, fallback: str) -> str:
    models = models_payload.get("data") or []
    if models and isinstance(models[0], dict) and models[0].get("id"):
        return str(models[0]["id"])
    return fallback


def response_text(chat_payload: dict) -> str:
    choices = chat_payload.get("choices") or []
    if not choices:
        return ""
    first = choices[0]
    message = first.get("message") or {}
    if isinstance(message, dict) and message.get("content"):
        return str(message["content"])
    if first.get("text"):
        return str(first["text"])
    return ""


def write_payload(artifact_path: Path, payload: dict) -> None:
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def classify_with_wildguard(items: list[dict]) -> list[dict]:
    try:
        from wildguard import load_wildguard
    except ImportError as exc:
        raise RuntimeError(
            "wildguard is not installed. Install the safety dependency before using "
            "provider='wildguard'."
        ) from exc

    classifier = load_wildguard()
    return classifier.classify(items)


def resolve_candidate_path(project_root: Path, candidate: CandidateConfig) -> Path:
    candidate_path = Path(candidate.path).expanduser()
    if candidate_path.is_absolute():
        return candidate_path.resolve()
    return (project_root / candidate_path).resolve()


def execute_safety_eval_stage(
    *,
    project_root: Path,
    run_id: int,
    candidate: CandidateConfig,
    safety_config: SafetyConfig,
    log_path: Path,
    artifact_path: Path,
) -> StageExecutionResult:
    if candidate.format != "hf":
        raise ValueError("provider 'safety_eval' currently supports hf candidates only")

    candidate_path = resolve_candidate_path(project_root, candidate)
    root_dir = Path(__file__).resolve().parents[2]
    adapter_path = root_dir / "adapters" / "safety_eval_adapter.py"
    command = [
        sys.executable,
        str(adapter_path),
        "--model-path",
        str(candidate_path),
        "--artifact-path",
        str(artifact_path),
        "--benchmarks",
        ",".join(safety_config.benchmarks),
    ]
    if safety_config.model_input_template:
        command.extend(["--model-input-template", safety_config.model_input_template])

    with log_path.open("a", encoding="utf-8") as handle:
        try:
            completed = subprocess.run(
                command,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=safety_config.startup_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("safety_eval adapter timed out") from exc

    if completed.returncode != 0:
        raise RuntimeError("safety_eval adapter failed")

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    status, evaluated_results = evaluate_safety_payload(safety_config, payload)
    logs = (
        "safety-eval benchmark run completed with "
        f"{evaluated_results['violations']} violation(s)."
    )
    final_payload = {
        "status": status,
        "results": evaluated_results,
        "logs": logs,
    }
    write_payload(artifact_path, final_payload)
    return {
        "status": status,
        "payload": final_payload,
        "artifact_path": str(artifact_path),
        "log_path": str(log_path),
        "error": None,
    }


def execute_safety_stage(
    *,
    project_root: Path,
    run_id: int,
    candidate: CandidateConfig,
    safety_config: SafetyConfig,
    port_override: int | None = None,
    command_override: list[str] | None = None,
    readiness_url_override: str | None = None,
    models_url_override: str | None = None,
    chat_url_override: str | None = None,
) -> StageExecutionResult:
    log_path, artifact_path = stage_output_paths(project_root, run_id, "safety")
    if safety_config.provider == "safety_eval":
        try:
            return execute_safety_eval_stage(
                project_root=project_root,
                run_id=run_id,
                candidate=candidate,
                safety_config=safety_config,
                log_path=log_path,
                artifact_path=artifact_path,
            )
        except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
            payload = {
                "status": "failed",
                "results": {
                    "provider": safety_config.provider,
                    "candidate_format": candidate.format,
                    "benchmarks": [],
                    "violations": 0,
                    "allowed_violations": safety_config.max_violations,
                },
                "logs": str(exc),
            }
            write_payload(artifact_path, payload)
            return {
                "status": "failed",
                "payload": payload,
                "artifact_path": str(artifact_path),
                "log_path": str(log_path),
                "error": str(exc),
            }

    runtime = resolve_runtime_for_candidate(candidate)
    port = port_override or find_free_port()
    readiness_url = readiness_url_override or f"http://127.0.0.1:{port}/v1/models"
    models_url = models_url_override or readiness_url
    chat_url = chat_url_override or f"http://127.0.0.1:{port}/v1/chat/completions"
    command = command_override or build_runtime_command(runtime, candidate=candidate, port=port)

    process: subprocess.Popen[str] | None = None
    try:
        with log_path.open("a", encoding="utf-8") as handle:
            process = subprocess.Popen(
                command,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
            wait_for_url(readiness_url, safety_config.startup_timeout_seconds)
            model_id = first_model_id(fetch_json(models_url), candidate.name)

            cases = []
            for case in safety_config.cases:
                chat_payload, latency_ms = post_chat_completion(
                    chat_url,
                    {
                        "model": model_id,
                        "messages": [{"role": "user", "content": case.prompt}],
                        "temperature": 0,
                    },
                )
                content = response_text(chat_payload)
                cases.append(
                    {
                        "name": case.name,
                        "prompt": case.prompt,
                        "response": content,
                        "required_substrings": case.required_substrings,
                        "forbidden_substrings": case.forbidden_substrings,
                        "latency_ms": round(latency_ms, 2),
                    }
                )

        if safety_config.provider == "wildguard":
            judge_results = classify_with_wildguard(
                [{"prompt": case["prompt"], "response": case["response"]} for case in cases]
            )
            for case, judge in zip(cases, judge_results, strict=False):
                case["judge"] = judge

        results = {
            "provider": safety_config.provider,
            "runtime": runtime.name,
            "candidate_format": candidate.format,
            "port": port,
            "model_id": model_id,
            "cases": cases,
            "allowed_violations": safety_config.max_violations,
        }
        status, evaluated_results = evaluate_safety_payload(safety_config, results)
        run_label = (
            "WildGuard safety evaluation"
            if safety_config.provider == "wildguard"
            else "Safety prompt suite"
        )
        logs = f"{run_label} completed with {evaluated_results['violations']} violation(s)."
        payload = {
            "status": status,
            "results": evaluated_results,
            "logs": logs,
        }
        write_payload(artifact_path, payload)
        return {
            "status": status,
            "payload": payload,
            "artifact_path": str(artifact_path),
            "log_path": str(log_path),
            "error": None,
        }
    except (FileNotFoundError, TimeoutError, OSError, ValueError) as exc:
        payload = {
            "status": "failed",
            "results": {
                "provider": safety_config.provider,
                "runtime": runtime.name,
                "candidate_format": candidate.format,
                "port": port,
                "cases": [],
                "violations": 0,
                "allowed_violations": safety_config.max_violations,
            },
            "logs": str(exc),
        }
        write_payload(artifact_path, payload)
        return {
            "status": "failed",
            "payload": payload,
            "artifact_path": str(artifact_path),
            "log_path": str(log_path),
            "error": str(exc),
        }
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
