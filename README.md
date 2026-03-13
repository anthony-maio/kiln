# Kiln

**Local-first release gate for open-source model builders.**

Kiln gives you a repeatable release checklist for your LLM — right on your machine. Point it at a model repo, define pass/fail thresholds in a `kiln.yaml`, and run an 8-stage release check that combines automated benchmarks with manual sign-offs. When you're done, export a Markdown or JSON release report directly into the repo.

No cloud account. No API keys for Kiln itself. Just a local server, a browser, and your models.

---

## Features

- **Projects-first workspace** — add local repo paths and manage them from one dashboard
- **`kiln.yaml` as source of truth** — repo-owned config defines benchmarks, thresholds, and which manual stages to require
- **Automated benchmarks** — runs [lm-eval-harness](https://github.com/EleutherAI/lm-evaluation-harness) in the background and evaluates results against your thresholds
- **8-stage release pipeline** — benchmarks, safety, documentation, packaging, serving, monitoring, incident response, and continuous improvement
- **Release verdicts** — `ready`, `needs_review`, or `blocked` based on stage outcomes
- **Report export** — generates Markdown and JSON artifacts written to your repo
- **Incident tracking** — log and review model incidents alongside release data
- **Dark/light theme** — works how you work

## Quickstart

### Docker (recommended)

```bash
git clone https://github.com/anthony-maio/kiln.git
cd kiln
docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080).

### Local

```bash
git clone https://github.com/anthony-maio/kiln.git
cd kiln
pip install -r requirements.txt
python api_server.py
```

Open [http://localhost:8000](http://localhost:8000). Requires Python 3.11+.

## How it works

1. **Add a project** — point Kiln at your local model repo
2. **Configure** — Kiln scaffolds a `kiln.yaml`, or you bring your own
3. **Run a release check** — benchmarks execute automatically; manual stages wait for you
4. **Review & sign off** — complete each required stage in the run detail view
5. **Export** — write the release report into your repo under `.kiln/reports/`

### Verdict logic

| Verdict | Condition |
|---------|-----------|
| `ready` | All stages passed or skipped |
| `needs_review` | No failures, but some stages are pending, running, or have warnings |
| `blocked` | Any stage failed |

## `kiln.yaml`

Every project is configured with a `kiln.yaml` at the repo root. See [docs/examples/kiln.yaml](docs/examples/kiln.yaml) for the full schema.

```yaml
version: 1

model:
  name: "My Model"
  repo_id: "org/model"
  parameters: "7B"
  architecture: "Mistral"

benchmarks:
  provider: "lm_eval"
  model: "hf"
  model_args: "pretrained=org/model"
  tasks:
    - name: "hellaswag"
      min_score: 0.75
    - name: "arc_easy"
      min_score: 0.70
  device: "cuda:0"
  batch_size: "auto"
  timeout_minutes: 120

manual_stages:
  safety: "required"
  documentation: "required"
  packaging: "required"
  serving: "skip"
  monitoring: "skip"
  incidents: "skip"
  improvement: "skip"

report:
  output_dir: ".kiln/reports"
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `KILN_DB_PATH` | `./kiln.db` | SQLite database path |
| `KILN_CORS_ORIGINS` | localhost only | Comma-separated allowed origins |
| `KILN_ENABLE_SEED_ENDPOINT` | `false` | Enable `POST /api/seed` for demo data |

## API reference

<details>
<summary>Expand full API reference</summary>

### Projects

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/projects` | List all projects |
| `POST` | `/api/projects` | Add a project (provide `root_path`) |
| `GET` | `/api/projects/{id}` | Project detail with config |
| `PUT` | `/api/projects/{id}/config` | Update `kiln.yaml` |
| `POST` | `/api/projects/{id}/sync` | Re-read config from disk |
| `POST` | `/api/projects/{id}/runs` | Start a release check |

### Jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/jobs` | List jobs |
| `GET` | `/api/jobs/{id}` | Job detail |
| `POST` | `/api/jobs/{id}/cancel` | Cancel a running job |

### Runs

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/runs` | List runs |
| `GET` | `/api/runs/{id}` | Run detail with stages |
| `POST` | `/api/runs` | Create a run (legacy) |
| `GET` | `/api/runs/{id}/release-report` | JSON report |
| `GET` | `/api/runs/{id}/release-report?format=markdown` | Markdown report |
| `POST` | `/api/runs/{id}/export-report` | Write report to repo |

### Stages

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/runs/{id}/stages/{key}/start` | Mark stage as running |
| `POST` | `/api/runs/{id}/stages/{key}/complete` | Complete with status |

### Models & incidents

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/models` | List models |
| `GET` | `/api/models/{id}` | Model detail |
| `POST` | `/api/models` | Create a model |
| `GET` | `/api/incidents` | List incidents |
| `POST` | `/api/incidents` | Report an incident |

### Utilities

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/dashboard` | Dashboard summary |
| `GET` | `/api/activity` | Activity log |

</details>

## Development

```bash
pip install -r requirements-dev.txt
pytest -q
```

CI runs syntax checks, the test suite, and a Docker build on every push. See [.github/workflows/ci.yml](.github/workflows/ci.yml).

## Scope & limitations

v0.2 is intentionally narrow:

- **Local single-user only** — no auth, no multi-user
- **One automated stage** — only benchmarks run automatically via lm-eval-harness
- **No hosted mode** — runs on your machine
- **No remote execution** — jobs run locally

Other stages (safety, documentation, packaging, etc.) are tracked manually in the UI.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), and [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
