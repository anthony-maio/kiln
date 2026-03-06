# Contributing to Kiln

Thanks for contributing.

## Development setup

```bash
git clone https://github.com/anthonymiao/kiln.git
cd kiln
pip install -r requirements-dev.txt
python api_server.py
```

Open `http://localhost:8000`.

## Tests and checks

Run these before opening a PR:

```bash
pytest -q
python -m py_compile api_server.py adapters/lm_eval_adapter.py
node --check app.js
```

## Pull requests

- Keep changes focused.
- Add tests for behavior changes.
- Update docs when user-facing behavior changes.
- Use clear commit messages.

## Scope for v0.1

Kiln v0.1 is local-first and single-user.  
Do not add auth, multi-tenant, or hosted deployment assumptions in core flows without prior design discussion.
