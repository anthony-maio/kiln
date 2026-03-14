from __future__ import annotations

import shlex
from dataclasses import dataclass

from kiln_backend.models import CandidateConfig


@dataclass(frozen=True)
class RuntimeResolution:
    name: str
    binary: str


def resolve_runtime_for_candidate(candidate: CandidateConfig) -> RuntimeResolution:
    runtime_name = candidate.runtime or candidate.serving.runtime
    if runtime_name is None:
        runtime_name = "llama_cpp" if candidate.format == "gguf" else "vllm"

    binaries = {
        "vllm": "vllm",
        "sglang": "python",
        "llama_cpp": "llama-server",
    }
    return RuntimeResolution(name=runtime_name, binary=binaries[runtime_name])


def build_runtime_command(
    runtime: RuntimeResolution,
    *,
    candidate: CandidateConfig,
    port: int,
) -> list[str]:
    extra_args = shlex.split(candidate.serving.model_args or "")

    if runtime.name == "vllm":
        return [
            runtime.binary,
            "serve",
            candidate.path,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            *extra_args,
        ]

    if runtime.name == "sglang":
        return [
            runtime.binary,
            "-m",
            "sglang.launch_server",
            "--model-path",
            candidate.path,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            *extra_args,
        ]

    return [
        runtime.binary,
        "-m",
        candidate.path,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        *extra_args,
    ]
