# Contributing to Kiln

Thanks for contributing.

## Development setup

```bash
git clone https://github.com/anthony-maio/kiln.git
cd kiln
pip install -r requirements-dev.txt
# Optional for local UI testing without lm_eval:
# PowerShell: $env:KILN_LM_EVAL_DRY_RUN="true"
# bash/zsh: export KILN_LM_EVAL_DRY_RUN=true
python api_server.py
```

Open `http://localhost:8000`.

## Tests and checks

Run these before opening a PR:

```bash
pytest -q
python -m py_compile api_server.py kiln_backend/models.py kiln_backend/storage.py kiln_backend/jobs.py kiln_backend/policy.py kiln_backend/runtimes.py kiln_backend/executors/base.py kiln_backend/executors/benchmarks.py kiln_backend/executors/documentation.py kiln_backend/executors/packaging.py kiln_backend/executors/safety.py kiln_backend/executors/serving.py adapters/lm_eval_adapter.py
node --check app.js
```

## Pull requests

- Keep changes focused.
- Add tests for behavior changes.
- Update docs when user-facing behavior changes.
- Keep README and docs brutally honest. Do not document roadmap items as current behavior.
- Use clear commit messages.

## Current scope

Kiln is local-first and single-user.  
Do not add auth, multi-tenant, or hosted deployment assumptions in core flows without prior design discussion.

Project-backed runs automate benchmarks, documentation, packaging, serving, and optional safety prompt suites when the repo config declares them.
Keep docs explicit about which stages are automated for a given release or config.
