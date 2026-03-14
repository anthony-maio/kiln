from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path
from urllib import request

from kiln_backend.executors.base import StageExecutionResult, stage_output_paths
from kiln_backend.models import CandidateConfig
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
    raise TimeoutError(f"Serving probe timed out waiting for {url}")


def fetch_url(url: str) -> float:
    start = time.perf_counter()
    with request.urlopen(url, timeout=5):
        pass
    return (time.perf_counter() - start) * 1000


def write_payload(artifact_path: Path, payload: dict) -> None:
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def execute_serving_stage(
    *,
    project_root: Path,
    run_id: int,
    candidate: CandidateConfig,
    port_override: int | None = None,
    command_override: list[str] | None = None,
    readiness_url_override: str | None = None,
    smoke_url_override: str | None = None,
) -> StageExecutionResult:
    runtime = resolve_runtime_for_candidate(candidate)
    log_path, artifact_path = stage_output_paths(project_root, run_id, "serving")
    port = port_override or find_free_port()
    readiness_url = readiness_url_override or f"http://127.0.0.1:{port}/v1/models"
    smoke_url = smoke_url_override or readiness_url
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
            wait_for_url(readiness_url, candidate.serving.startup_timeout_seconds)
            smoke_latency_ms = fetch_url(smoke_url)

        status = "passed"
        if (
            candidate.serving.max_latency_ms is not None
            and smoke_latency_ms > candidate.serving.max_latency_ms
        ):
            status = "warning"

        payload = {
            "status": status,
            "results": {
                "runtime": runtime.name,
                "candidate_format": candidate.format,
                "port": port,
                "readiness_url": readiness_url,
                "smoke_url": smoke_url,
                "smoke_latency_ms": round(smoke_latency_ms, 2),
            },
            "logs": f"Serving probe succeeded for runtime {runtime.name}.",
        }
        write_payload(artifact_path, payload)
        return {
            "status": status,
            "payload": payload,
            "artifact_path": str(artifact_path),
            "log_path": str(log_path),
            "error": None,
        }
    except FileNotFoundError as exc:
        payload = {
            "status": "failed",
            "results": {
                "runtime": runtime.name,
                "candidate_format": candidate.format,
                "port": port,
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
    except TimeoutError as exc:
        payload = {
            "status": "failed",
            "results": {
                "runtime": runtime.name,
                "candidate_format": candidate.format,
                "port": port,
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
