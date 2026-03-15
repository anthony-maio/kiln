# Pre-Release Pipeline Design

**Date:** 2026-03-13

## Goal

Expand Kiln from a local release checklist with one automated benchmark stage into a real local pre-release pipeline for model builders.

The pipeline should stay local-only and single-user. It should not become a hosted control plane, a package manager, or a post-release monitoring system. It should execute real local gates, record structured evidence, and generate honest release reports.

## Validated scope decisions

- Pre-release only
- Local execution only
- One candidate per run
- Multiple candidates per project
- Explicit candidate declaration in `kiln.yaml`
- Benchmarks and serving are separate gates
- Runtime resolution is format-aware with manual override
- No automatic format conversion
- No artifact download in the first implementation pass
- Safety remains manual in phase 1 and becomes automated later

## Project and candidate model

A project represents one model workspace. That workspace may contain several candidate artifacts under evaluation at the same time, such as a base Hugging Face checkpoint, a post-trained checkpoint, and one or more GGUF exports.

`kiln.yaml` should move from a single-artifact schema to a candidate-based schema. Each candidate must be declared explicitly with:

- `name`
- `format`
- `path`
- optional runtime override
- candidate-specific benchmark settings
- candidate-specific serving settings

Kiln should not infer format, runtime, or path semantics from filenames. That would become brittle immediately.

Each run targets exactly one candidate. The run record should snapshot the candidate name, format, path, and resolved runtime at creation time so historical runs remain reproducible even after config changes.

## Pipeline shape

The core pre-release pipeline should be:

1. `benchmarks`
2. `safety`
3. `documentation`
4. `packaging`
5. `serving`

`monitoring`, `incident response`, and `improvement` leave the critical path. They can return later as follow-up artifacts, but they should not remain first-class release gates in the next implementation.

Each stage should follow the same execution contract:

- one executor
- one structured JSON artifact
- one log file
- one policy decision
- one report section

Manual input remains available, but only as an explicit override path with notes. It should not remain the default path for automated stages.

## Execution model

Kiln should keep a single local worker queue. That is the right default for a local machine and protects users from launching several GPU-heavy jobs at once.

Every stage job should move through the same lifecycle:

`queued -> running -> passed | warning | failed | canceled`

Executors collect facts. Policies convert those facts into a stage result. This separation matters:

- benchmark executor returns raw scores
- documentation executor returns missing sections and metadata problems
- serving executor returns startup, health, and latency results
- packaging executor returns missing artifacts and shape problems

Policy layers then decide whether those facts are failures or warnings.

All stage artifacts should live under the run directory:

- `.kiln/logs/run-<id>/<stage>.log`
- `.kiln/artifacts/run-<id>/<stage>.json`
- `.kiln/reports/run-<id>.md`
- `.kiln/reports/run-<id>.json`

## Runtime-aware serving

Serving must be honest about format compatibility. Kiln should not claim universal runtime support.

Default runtime resolution:

- `gguf` -> `llama.cpp`
- `hf` -> `vllm`
- `hf` with explicit override -> `sglang`

Invalid format/runtime combinations fail at config validation or run setup time.

The serving stage is a deployability probe, not a throughput benchmark. It should:

1. allocate an ephemeral local port
2. spawn the selected runtime
3. wait for readiness
4. send a small set of smoke requests
5. record startup and request latency
6. shut the runtime down cleanly

Kiln should not manage runtime installation, weight download, or conversion in this phase.

## Phase plan

### Phase 1

Ship a real pre-release gate with:

- candidate-aware config and runs
- automated benchmarks
- automated serving checks
- automated documentation checks
- automated packaging checks
- manual safety with explicit reporting

### Phase 2

Replace manual safety with a real safety executor that follows the same executor and policy contract as the other stages.

## Non-goals

- hosted mode
- multi-user auth
- remote workers
- automatic model download
- format conversion
- publish-to-Hub automation
- post-release monitoring in the critical path

## Why this design

This design turns Kiln into a real local release gate without turning it into three separate products at once. It keeps the system honest, narrow, and technically defensible. It also sets up a stable executor architecture that can absorb later safety and publishing work without redoing the whole backend.
