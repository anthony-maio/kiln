# Kiln Release Notes

## Highlights
- [ ] Local single-user workflow
- [ ] Release readiness report (JSON + Markdown export)
- [ ] Candidate-aware project runs
- [ ] Automated stages shipped in this release

## What changed

### Added
- 

### Changed
- 

### Fixed
- 

## Upgrade notes
- Python dependencies: `pip install -r requirements.txt`
- Seed endpoint is disabled by default. Enable only when needed:
  - `KILN_ENABLE_SEED_ENDPOINT=true`

## Known limitations
- Local single-user only.
- Safety automation is a prompt suite, not a full external safety harness.
- Serving is a smoke check, not a throughput benchmark.
- Kiln does not download or convert model artifacts for you.

## Verification checklist
- [ ] `pytest -q` passes
- [ ] `python -m py_compile api_server.py kiln_backend/models.py kiln_backend/storage.py kiln_backend/jobs.py kiln_backend/policy.py kiln_backend/runtimes.py kiln_backend/executors/base.py kiln_backend/executors/benchmarks.py kiln_backend/executors/documentation.py kiln_backend/executors/packaging.py kiln_backend/executors/safety.py kiln_backend/executors/serving.py adapters/lm_eval_adapter.py`
- [ ] `node --check app.js`
- [ ] Docker quickstart works on clean machine
