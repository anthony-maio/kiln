## Summary
- Describe what changed.

## Why
- Explain the user-visible impact.

## Verification
- [ ] `pytest -q`
- [ ] `python -m py_compile api_server.py kiln_backend/models.py kiln_backend/storage.py kiln_backend/jobs.py kiln_backend/policy.py kiln_backend/runtimes.py kiln_backend/executors/base.py kiln_backend/executors/benchmarks.py kiln_backend/executors/documentation.py kiln_backend/executors/packaging.py kiln_backend/executors/safety.py kiln_backend/executors/serving.py adapters/lm_eval_adapter.py`
- [ ] `node --check app.js`

## Notes
- Risks, follow-ups, or migration details.
