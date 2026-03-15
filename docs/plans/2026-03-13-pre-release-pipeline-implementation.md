# Pre-Release Pipeline Phase 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expand Kiln into a real local pre-release pipeline with candidate-aware runs and automated benchmark, serving, documentation, and packaging stages while keeping safety explicit and manual.

**Architecture:** Replace the single-artifact project schema with an explicit candidate list, snapshot the selected candidate into each run, and move stage execution behind a shared executor-and-policy contract. Keep one local worker, resolve serving runtime from candidate format with override support, and write stage artifacts and logs into repo-local `.kiln` directories.

**Tech Stack:** FastAPI, Pydantic, SQLite, PyYAML, subprocess-based executors, vanilla JS frontend, pytest.

---

## Preconditions

- Commit or stash the current docs-only changes before implementation work starts.
- Create a dedicated worktree before touching feature code.
- Treat this as a phase-1 plan. Safety automation is intentionally out of scope here.

### Task 1: Introduce candidate-aware config models

**Files:**
- Modify: `D:\Development\Kiln\kiln_backend\models.py`
- Modify: `D:\Development\Kiln\kiln_backend\storage.py`
- Modify: `D:\Development\Kiln\docs\examples\kiln.yaml`
- Test: `D:\Development\Kiln\tests\test_projects_api.py`

**Step 1: Write the failing tests**

Add tests for:
- valid config with multiple candidates
- rejection of configs without candidates
- rejection of unknown candidate formats
- rejection of invalid runtime override for a format

Example test shape:

```python
def test_put_project_config_accepts_multiple_candidates(...):
    payload = build_candidate_config()
    response = client.put(f"/api/projects/{project_id}/config", json=payload)
    assert response.status_code == 200
```

**Step 2: Run the targeted tests**

Run: `pytest tests/test_projects_api.py -k candidate -v`
Expected: FAIL because candidate-aware schema does not exist yet.

**Step 3: Implement the config schema**

Add:
- `CandidateConfig`
- `CandidateBenchmarksConfig`
- `CandidateServingConfig`
- `ProjectConfig.version = 2`

Keep read compatibility for version-1 config if practical. If not, fail with a clear upgrade error and ship a migration helper in a later task.

**Step 4: Update config load/write helpers**

Update:
- default config generation
- YAML serialization
- project config validation
- example config

**Step 5: Re-run the targeted tests**

Run: `pytest tests/test_projects_api.py -k candidate -v`
Expected: PASS

**Step 6: Commit**

```bash
git add kiln_backend/models.py kiln_backend/storage.py docs/examples/kiln.yaml tests/test_projects_api.py
git commit -m "feat: add candidate-aware project config"
```

### Task 2: Snapshot candidate selection into each run

**Files:**
- Modify: `D:\Development\Kiln\kiln_backend\storage.py`
- Modify: `D:\Development\Kiln\kiln_backend\models.py`
- Modify: `D:\Development\Kiln\api_server.py`
- Test: `D:\Development\Kiln\tests\test_projects_api.py`

**Step 1: Write the failing tests**

Add tests for:
- `POST /api/projects/{id}/runs` requires `candidate_name`
- selected candidate metadata is copied into the run
- missing candidate path fails before queueing jobs

Example:

```python
def test_project_run_snapshots_candidate_metadata(...):
    response = client.post(f"/api/projects/{project_id}/runs", json={"candidate_name": "q4_gguf"})
    assert response.status_code == 201
    assert response.json()["run"]["candidate_name"] == "q4_gguf"
```

**Step 2: Run the targeted tests**

Run: `pytest tests/test_projects_api.py -k snapshots_candidate -v`
Expected: FAIL

**Step 3: Add DB columns and API shape**

Add run columns:
- `candidate_name`
- `candidate_format`
- `candidate_path`
- `resolved_runtime`

Update the request model for project-backed run creation to accept `candidate_name`.

**Step 4: Implement run creation**

Resolve the selected candidate from config, validate the local path, resolve the runtime, and snapshot everything into the run record.

**Step 5: Re-run the targeted tests**

Run: `pytest tests/test_projects_api.py -k 'candidate or snapshots_candidate' -v`
Expected: PASS

**Step 6: Commit**

```bash
git add kiln_backend/storage.py kiln_backend/models.py api_server.py tests/test_projects_api.py
git commit -m "feat: snapshot candidate metadata into runs"
```

### Task 3: Replace hard-coded benchmark jobs with a generic executor contract

**Files:**
- Create: `D:\Development\Kiln\kiln_backend\executors\__init__.py`
- Create: `D:\Development\Kiln\kiln_backend\executors\base.py`
- Create: `D:\Development\Kiln\kiln_backend\executors\benchmarks.py`
- Create: `D:\Development\Kiln\kiln_backend\policy.py`
- Modify: `D:\Development\Kiln\kiln_backend\jobs.py`
- Modify: `D:\Development\Kiln\kiln_backend\storage.py`
- Test: `D:\Development\Kiln\tests\test_projects_api.py`
- Create: `D:\Development\Kiln\tests\test_stage_execution.py`

**Step 1: Write the failing tests**

Add tests for:
- executor writes `.kiln/artifacts/run-<id>/benchmarks.json`
- executor writes `.kiln/logs/run-<id>/benchmarks.log`
- policy maps raw benchmark scores to `passed` or `failed`

**Step 2: Run the targeted tests**

Run: `pytest tests/test_stage_execution.py -v`
Expected: FAIL because executor and policy modules do not exist.

**Step 3: Implement the base contract**

Define a base executor result shape:

```python
class StageExecutionResult(TypedDict):
    status: str
    artifact_path: str
    log_path: str
    payload: dict
```

Keep executor code responsible for facts, not policy.

**Step 4: Port benchmarks onto the new contract**

Move the current `lm_eval_adapter.py` subprocess flow into `executors/benchmarks.py`, then let `policy.py` decide the final stage status from thresholds.

**Step 5: Re-run the tests**

Run: `pytest tests/test_stage_execution.py tests/test_projects_api.py -k benchmark -v`
Expected: PASS

**Step 6: Commit**

```bash
git add kiln_backend/executors kiln_backend/policy.py kiln_backend/jobs.py kiln_backend/storage.py tests/test_stage_execution.py tests/test_projects_api.py
git commit -m "refactor: add generic stage executor contract"
```

### Task 4: Add the serving executor with runtime resolution

**Files:**
- Create: `D:\Development\Kiln\kiln_backend\runtimes.py`
- Create: `D:\Development\Kiln\kiln_backend\executors\serving.py`
- Modify: `D:\Development\Kiln\kiln_backend\jobs.py`
- Modify: `D:\Development\Kiln\kiln_backend\policy.py`
- Create: `D:\Development\Kiln\tests\test_serving_executor.py`

**Step 1: Write the failing tests**

Add tests for:
- `gguf` resolves to `llama.cpp`
- `hf` resolves to `vllm`
- explicit `sglang` override works for `hf`
- invalid `gguf + vllm` fails validation
- missing runtime binary returns a clear failure
- serving probe timeout marks the stage failed

Use tiny stub server processes for the smoke tests instead of launching real model runtimes in CI.

**Step 2: Run the targeted tests**

Run: `pytest tests/test_serving_executor.py -v`
Expected: FAIL

**Step 3: Implement runtime resolution**

Add a small resolver that accepts candidate format plus optional override and returns:
- runtime name
- launch command template
- validation errors

**Step 4: Implement the serving executor**

Behavior:
- allocate a free local port
- spawn the runtime subprocess
- wait for readiness
- hit the smoke endpoint
- capture latency and response success
- write artifact and log files
- shut down the process

**Step 5: Re-run the targeted tests**

Run: `pytest tests/test_serving_executor.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add kiln_backend/runtimes.py kiln_backend/executors/serving.py kiln_backend/jobs.py kiln_backend/policy.py tests/test_serving_executor.py
git commit -m "feat: add serving executor with runtime resolution"
```

### Task 5: Add the documentation executor

**Files:**
- Create: `D:\Development\Kiln\kiln_backend\executors\documentation.py`
- Modify: `D:\Development\Kiln\kiln_backend\policy.py`
- Create: `D:\Development\Kiln\tests\test_documentation_executor.py`

**Step 1: Write the failing tests**

Add tests for:
- missing `README.md` fails
- missing model card fails or warns according to policy
- missing advisory sections return warnings, not failures

**Step 2: Run the targeted tests**

Run: `pytest tests/test_documentation_executor.py -v`
Expected: FAIL

**Step 3: Implement the executor**

Start simple:
- check file presence
- check a small set of required sections
- emit concrete missing items in JSON

Do not add an LLM-based linter.

**Step 4: Re-run the targeted tests**

Run: `pytest tests/test_documentation_executor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add kiln_backend/executors/documentation.py kiln_backend/policy.py tests/test_documentation_executor.py
git commit -m "feat: add documentation executor"
```

### Task 6: Add the packaging executor

**Files:**
- Create: `D:\Development\Kiln\kiln_backend\executors\packaging.py`
- Modify: `D:\Development\Kiln\kiln_backend\policy.py`
- Create: `D:\Development\Kiln\tests\test_packaging_executor.py`

**Step 1: Write the failing tests**

Add tests for:
- missing candidate artifact path fails
- missing required release files fail or warn by policy
- packaging executor writes structured artifact output

**Step 2: Run the targeted tests**

Run: `pytest tests/test_packaging_executor.py -v`
Expected: FAIL

**Step 3: Implement the executor**

Keep scope narrow:
- verify candidate path exists
- verify expected artifact files for the selected format
- verify a minimal release-shaped repo

Do not publish anywhere in this phase.

**Step 4: Re-run the targeted tests**

Run: `pytest tests/test_packaging_executor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add kiln_backend/executors/packaging.py kiln_backend/policy.py tests/test_packaging_executor.py
git commit -m "feat: add packaging executor"
```

### Task 7: Wire the phase-1 pipeline and keep safety manual

**Files:**
- Modify: `D:\Development\Kiln\kiln_backend\models.py`
- Modify: `D:\Development\Kiln\kiln_backend\jobs.py`
- Modify: `D:\Development\Kiln\kiln_backend\storage.py`
- Modify: `D:\Development\Kiln\api_server.py`
- Test: `D:\Development\Kiln\tests\test_projects_api.py`
- Test: `D:\Development\Kiln\tests\test_api_contract.py`

**Step 1: Write the failing tests**

Add tests for:
- new runs create the stage set `benchmarks, safety, documentation, packaging, serving`
- safety remains pending/manual by default
- run stays `running` until the manual safety stage becomes terminal
- final verdict uses required automated stages plus manual safety

**Step 2: Run the targeted tests**

Run: `pytest tests/test_projects_api.py tests/test_api_contract.py -k 'safety or stage set or verdict' -v`
Expected: FAIL

**Step 3: Implement stage wiring**

Remove old post-release stages from the phase-1 critical path for new runs. Keep old runs readable if legacy stage rows are present in the database.

**Step 4: Re-run the targeted tests**

Run: `pytest tests/test_projects_api.py tests/test_api_contract.py -k 'safety or stage set or verdict' -v`
Expected: PASS

**Step 5: Commit**

```bash
git add kiln_backend/models.py kiln_backend/jobs.py kiln_backend/storage.py api_server.py tests/test_projects_api.py tests/test_api_contract.py
git commit -m "feat: wire phase-1 pre-release pipeline"
```

### Task 8: Update the UI for candidate selection and executor evidence

**Files:**
- Modify: `D:\Development\Kiln\app.js`
- Modify: `D:\Development\Kiln\index.html`
- Modify: `D:\Development\Kiln\style.css`
- Test: `D:\Development\Kiln\tests\test_projects_api.py`

**Step 1: Add UI-driven expectations to tests**

Add API tests for:
- project detail returns candidates
- run creation rejects missing `candidate_name`
- run detail exposes artifact and log paths

**Step 2: Run the targeted tests**

Run: `pytest tests/test_projects_api.py -k 'candidate_name or artifact or log_path' -v`
Expected: FAIL until backend shape is final.

**Step 3: Update the frontend**

Add:
- candidate selector on project detail
- candidate summary card
- explicit runtime display
- stage artifact and log links on run detail
- manual safety override with notes

Do not add a comparison dashboard yet.

**Step 4: Run checks**

Run:
- `pytest tests/test_projects_api.py -k 'candidate_name or artifact or log_path' -v`
- `node --check app.js`

Expected: PASS

**Step 5: Commit**

```bash
git add app.js index.html style.css tests/test_projects_api.py
git commit -m "feat: add candidate-aware pipeline UI"
```

### Task 9: Update docs, examples, and acceptance tests

**Files:**
- Modify: `D:\Development\Kiln\README.md`
- Modify: `D:\Development\Kiln\CONTRIBUTING.md`
- Modify: `D:\Development\Kiln\docs\examples\kiln.yaml`
- Modify: `D:\Development\Kiln\docs\examples\release-report.md`
- Modify: `D:\Development\Kiln\.github\pull_request_template.md`
- Create: `D:\Development\Kiln\tests\test_phase1_pipeline_smoke.py`

**Step 1: Write the failing smoke test**

Add one integration test that:
- creates a project
- writes a candidate-aware config
- starts a run for one candidate
- exercises automated stages with stubs
- leaves safety manual
- exports a report

**Step 2: Run the smoke test**

Run: `pytest tests/test_phase1_pipeline_smoke.py -v`
Expected: FAIL

**Step 3: Update docs**

Make the public docs say exactly this:
- one project can hold many candidates
- one run targets one candidate
- serving, documentation, and packaging are automated in phase 1
- safety is still manual in phase 1

**Step 4: Run the full check suite**

Run:
- `pytest -q`
- `python -m py_compile api_server.py kiln_backend/models.py kiln_backend/storage.py kiln_backend/jobs.py adapters/lm_eval_adapter.py`
- `node --check app.js`

Expected: PASS

**Step 5: Commit**

```bash
git add README.md CONTRIBUTING.md docs/examples/kiln.yaml docs/examples/release-report.md .github/pull_request_template.md tests/test_phase1_pipeline_smoke.py
git commit -m "docs: update for phase-1 pre-release pipeline"
```

## Acceptance criteria

- A project can declare multiple candidates in `kiln.yaml`
- A run must target exactly one candidate
- Benchmarks, serving, documentation, and packaging execute automatically
- Safety remains manual and explicit
- Every automated stage writes JSON artifacts and log files
- Serving runtime resolution is format-aware and validated
- Reports reflect one candidate per run and cite automated versus manual stages honestly
- Full test suite passes

## Backlog after phase 1

- optional Hugging Face artifact fetch
- automated safety executor
- historical candidate comparison views
- publish preflight for target registries
- post-release monitoring as a separate track
