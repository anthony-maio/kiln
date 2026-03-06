import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib import request


ROOT = Path(__file__).resolve().parent.parent


def find_free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_server(url, timeout_seconds=20):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with request.urlopen(url, timeout=1):
                return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"Server did not start: {url}")


def api_request(url, method="GET", payload=None):
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=body, headers=headers, method=method)
    with request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def test_lm_eval_adapter_dry_run_smoke(tmp_path):
    port = find_free_port()
    db_path = tmp_path / "adapter-smoke.db"
    env = os.environ.copy()
    env["KILN_DB_PATH"] = str(db_path)
    env["PYTHONUNBUFFERED"] = "1"

    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "api_server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        wait_for_server(f"http://127.0.0.1:{port}/api/health")

        run = api_request(
            f"http://127.0.0.1:{port}/api/runs",
            method="POST",
            payload={"model_id": 1, "mode": "real"},
        )

        completed = subprocess.run(
            [
                sys.executable,
                "adapters/lm_eval_adapter.py",
                "--model-id",
                "dry-run/model",
                "--run-id",
                str(run["id"]),
                "--api-url",
                f"http://127.0.0.1:{port}",
                "--dry-run",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

        run_detail = api_request(f"http://127.0.0.1:{port}/api/runs/{run['id']}")
        benchmarks_stage = next(
            stage for stage in run_detail["stages"] if stage["stage_key"] == "benchmarks"
        )

        assert benchmarks_stage["status"] == "passed"
        assert run_detail["status"] == "running"
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
