# Kiln

Local-first LLM release gate for open-source model builders.

Kiln helps you track model release readiness across 8 stages, then export a shareable report.  
v0.1 is intentionally small: one real adapter path (benchmarks), local single-user runtime, no auth.

## What v0.1 actually does

- Run lifecycle tracking (`mock` or `real` mode)
- Stage-level status management across 8 pipeline stages
- Release readiness report:
  - JSON: `GET /api/runs/{id}/release-report`
  - Markdown: `GET /api/runs/{id}/release-report?format=markdown`
- Frontend export button for Markdown report downloads
- Real benchmark adapter script for `lm-eval-harness`:
  - [`adapters/lm_eval_adapter.py`](adapters/lm_eval_adapter.py)

## What v0.1 does not do

- Multi-user auth/roles
- Hosted deployment workflow
- Real adapters for all 8 stages

Only the **benchmarks** stage has a real adapter in this release.  
Other stages are manual/mock unless you integrate them.

## Quickstart

### Docker

```bash
git clone https://github.com/anthonymiao/kiln.git
cd kiln
docker compose up --build
```

Open `http://localhost:8080`.

### Local

```bash
git clone https://github.com/anthonymiao/kiln.git
cd kiln
pip install -r requirements.txt
python api_server.py
```

Open `http://localhost:8000`.

## First useful run (real mode)

1. Register a model in the UI.
2. Start a new run with `mode=real`.
3. Run benchmark adapter (example):

```bash
python adapters/lm_eval_adapter.py \
  --model-id your-org/your-model \
  --run-id 1 \
  --api-url http://localhost:8000
```

4. Complete remaining stages manually (or keep as pending/warning).
5. Export release report from run detail view, or call:

```bash
curl "http://localhost:8000/api/runs/1/release-report?format=markdown"
```

## Verdict logic

- `blocked`: any stage is `failed`
- `needs_review`: no failures, but at least one `warning`, `pending`, or `running`
- `ready`: all stages are `passed` or `skipped`

## Configuration

Environment variables:

- `KILN_DB_PATH` (default: `./kiln.db`)
- `KILN_CORS_ORIGINS` (comma-separated; default localhost-only origins)
- `KILN_ENABLE_SEED_ENDPOINT` (`true` to enable `POST /api/seed`; default disabled)

## API reference (v0.1)

### Health and dashboard

- `GET /api/health`
- `GET /api/dashboard`

### Models

- `GET /api/models`
- `GET /api/models/{id}`
- `POST /api/models`

### Runs

- `GET /api/runs`
- `GET /api/runs/{id}`
- `POST /api/runs` (`mode`: `mock | real`)
- `GET /api/runs/{id}/release-report`
- `GET /api/runs/{id}/release-report?format=markdown`

### Stages

- `POST /api/runs/{id}/stages/{key}/start`
- `POST /api/runs/{id}/stages/{key}/complete` (`status`: `passed | failed | warning | skipped`)

### Incidents

- `GET /api/incidents`
- `POST /api/incidents` (`severity`: `P0 | P1 | P2 | P3`)

### Utilities

- `GET /api/activity`
- `POST /api/seed` (disabled unless `KILN_ENABLE_SEED_ENDPOINT=true`)

## Development

```bash
pip install -r requirements-dev.txt
pytest -q
python -m py_compile api_server.py adapters/lm_eval_adapter.py
node --check app.js
```

CI runs the same checks on pull requests.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

MIT. See [LICENSE](LICENSE).
