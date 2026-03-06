# 🔥 Kiln

**Open-source LLMOps pipeline manager. Take models from training to production.**

Kiln orchestrates the 8 stages between "my model trained" and "my model is in production": academic benchmarks, safety evaluation, documentation, packaging, inference serving, monitoring, incident response, and continuous improvement.

Ships with **mock mode** for instant demos and **pluggable backends** for real evaluation pipelines.

---

## Quick Start

### Docker (Recommended)

```bash
git clone https://github.com/anthonymiao/kiln.git
cd kiln
docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080). Demo data is auto-seeded.

### Local (No Docker)

```bash
git clone https://github.com/anthonymiao/kiln.git
cd kiln
pip install -r requirements.txt
python api_server.py
```

Open [http://localhost:8000](http://localhost:8000).

---

## What It Does

Kiln manages the full model-to-production lifecycle through 8 pipeline stages:

| # | Stage | What It Does | Real-Mode Tools |
|---|-------|-------------|-----------------|
| 1 | **Academic Benchmarks** | MMLU, HellaSwag, ARC, WinoGrande, TruthfulQA, GSM8K | [lm-eval-harness](https://github.com/EleutherAI/lm-eval-harness) |
| 2 | **Safety Evaluation** | Toxicity, bias (CrowS-Pairs), truthfulness, red teaming | [Perspective API](https://perspectiveapi.com/), [HarmBench](https://github.com/centerforaisafety/HarmBench) |
| 3 | **Documentation** | Model card checklist, NIST AI RMF alignment, intended use | HuggingFace model card template |
| 4 | **Packaging** | HuggingFace upload, GGUF/AWQ quantization variants | [llama.cpp](https://github.com/ggerganov/llama.cpp), [AutoAWQ](https://github.com/casper-hansen/AutoAWQ) |
| 5 | **Inference Serving** | API endpoint health, latency metrics (TTFT, TPOT), load testing | [vLLM](https://github.com/vllm-project/vllm), [TGI](https://github.com/huggingface/text-generation-inference) |
| 6 | **Production Monitoring** | Drift detection, toxicity sampling, performance tracking | [Prometheus](https://prometheus.io/) + [Grafana](https://grafana.com/), [whylogs](https://whylabs.ai/) |
| 7 | **Incident Response** | Incident tracking, severity, runbook status, kill switch verification | Custom |
| 8 | **Continuous Improvement** | Action items, review schedules, feedback collection | Custom |

### Two Modes

- **Mock Mode** — Generates realistic simulated results instantly. No GPU, no API keys. Perfect for demos, learning, and portfolio display.
- **Real Mode** — Plugs into actual evaluation frameworks. Requires GPU access and API credentials. (Adapter interfaces in development.)

---

## Features

- **Pipeline Visualization** — Visual flow of all 8 stages with status, duration, and clickable drill-down
- **Benchmark Dashboard** — Score bars with pass/fail thresholds, baseline comparisons, and ablation summaries
- **Safety Reports** — Toxicity metrics, bias breakdown by category (gender, race, religion, etc.), red team status
- **Documentation Checklist** — Track model card completeness with NIST AI RMF alignment
- **Packaging Tracker** — Monitor HuggingFace upload and quantized variant status (GGUF, AWQ, BF16)
- **Serving Metrics** — TTFT, TPOT, throughput, GPU utilization, KV cache stats, load test results
- **Monitoring Dashboard** — Drift detection, error rates, toxicity sampling, uptime
- **Incident Management** — Track incidents by severity (P0-P3), resolution status, postmortems
- **Model Registry** — Register and manage multiple models with run history
- **Dark/Light Mode** — Full theme support
- **Run Comparison** — Start new pipeline runs and compare results across versions

---

## Architecture

```
┌──────────────────────────────────────────────┐
│                  Browser                      │
│  Dashboard, Pipeline View, Stage Details      │
│  (HTML/CSS/JS — no build step required)       │
└────────────────────┬─────────────────────────┘
                     │ REST API
┌────────────────────▼─────────────────────────┐
│              FastAPI Backend                   │
│  /api/dashboard  /api/models  /api/runs       │
│  /api/incidents  /api/activity                 │
│  Mock data generator + real adapter interface  │
└────────────────────┬─────────────────────────┘
                     │
┌────────────────────▼─────────────────────────┐
│              SQLite Database                   │
│  models, pipeline_runs, pipeline_stages,       │
│  incidents, activity_log                       │
└──────────────────────────────────────────────┘
```

**Zero build tools.** The frontend is plain HTML, CSS, and vanilla JavaScript. No npm, no webpack, no React. Just open `index.html`.

**Two dependencies.** The entire backend needs only `fastapi` and `uvicorn`. That's it.

---

## API Reference

### Dashboard
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/dashboard` | Aggregated stats, recent activity, models |
| GET | `/api/health` | Health check |

### Models
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/models` | List all models |
| GET | `/api/models/{id}` | Model details with runs and incidents |
| POST | `/api/models` | Register a new model |

### Pipeline Runs
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/runs` | List runs (filter by `model_id`, `status`) |
| GET | `/api/runs/{id}` | Run details with all stage results |
| POST | `/api/runs` | Start a new run (`mode`: "mock" or "real") |

### Pipeline Stages
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/runs/{id}/stages/{key}/start` | Mark stage as running |
| POST | `/api/runs/{id}/stages/{key}/complete` | Complete stage with results |

### Incidents
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/incidents` | List incidents (filter by `model_id`, `status`) |
| POST | `/api/incidents` | Create incident |

### Utility
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/activity` | Activity log (default 30 entries) |
| POST | `/api/seed` | Reset and reseed demo data |

---

## Extending Kiln

### Adding a Real Backend Adapter

To connect a real evaluation tool (e.g., lm-eval-harness), create an adapter that:

1. Accepts a model identifier and stage configuration
2. Runs the actual evaluation
3. Returns results in Kiln's expected JSON format
4. Calls `POST /api/runs/{id}/stages/{key}/complete` with the results

Example adapter structure:

```python
# adapters/benchmarks.py

import subprocess
import json

def run_benchmarks(model_id: str, run_id: int, api_url: str):
    """Run lm-eval-harness and report results to Kiln."""

    # Run the evaluation
    result = subprocess.run([
        "lm_eval", "--model", "hf",
        "--model_args", f"pretrained={model_id},dtype=bfloat16",
        "--tasks", "mmlu,hellaswag,arc_challenge,winogrande,truthfulqa_mc2,gsm8k",
        "--batch_size", "auto",
        "--output_path", "./eval_results"
    ], capture_output=True)

    # Parse results and format for Kiln
    results = parse_lm_eval_output("./eval_results")

    # Report back to Kiln
    import requests
    requests.post(
        f"{api_url}/api/runs/{run_id}/stages/benchmarks/complete",
        json={"status": "passed", "results": results}
    )
```

### Adding Custom Stages

Modify `STAGE_DEFINITIONS` in `api_server.py`:

```python
STAGE_DEFINITIONS = [
    ("benchmarks", "Academic Benchmarks", 1),
    ("safety", "Safety Evaluation", 2),
    # ... existing stages ...
    ("custom_eval", "My Custom Evaluation", 9),  # Add your stage
]
```

Then add a corresponding renderer in `app.js`:

```javascript
case "custom_eval":
  return renderCustomEvalResults(results);
```

---

## Project Structure

```
kiln/
├── api_server.py       # FastAPI backend (pipeline orchestration, mock data, SQLite)
├── index.html          # Dashboard entry point
├── base.css            # CSS reset and base styles
├── style.css           # Design tokens and component styles
├── app.js              # Frontend application (vanilla JS, no framework)
├── Dockerfile          # Container definition
├── docker-compose.yml  # One-command deployment
├── requirements.txt    # Python dependencies (fastapi, uvicorn)
├── LICENSE             # MIT
└── README.md           # This file
```

**Total size: ~120KB.** No node_modules. No build artifacts. No framework overhead.

---

## Contributing

Contributions welcome. Some ideas:

- [ ] **Real adapters** — Connect lm-eval-harness, Perspective API, HarmBench
- [ ] **Webhook notifications** — Slack/Discord alerts on stage completion or failure
- [ ] **Model comparison** — Side-by-side benchmark comparison across model versions
- [ ] **Export** — PDF/CSV export of pipeline reports
- [ ] **CI/CD integration** — GitHub Actions workflow that triggers pipeline runs on model push
- [ ] **User auth** — Multi-user support with role-based access
- [ ] **Scheduled runs** — Cron-based automatic re-evaluation

---

## Background

Training a model is maybe 20% of the work. The other 80% is everything that happens after: evaluating whether it's safe, benchmarking it against the field, packaging it for deployment, monitoring it in production, and having a plan for when things go wrong.

This project was born from writing an [LLMOps production pipeline document](https://github.com/anthonymiao/kiln/blob/main/docs/LLMOPS_PIPELINE.md) for [Eve-3-SABER-1B](https://huggingface.co/anthonym21/Eve-3-SABER-1B), a 1B parameter dense transformer with novel SABER attention architecture. Rather than let the pipeline live as a static document, Kiln makes it interactive, visual, and reusable for any model.

---

## License

MIT — see [LICENSE](LICENSE).

---

**Built by [Anthony Maio](https://making-minds.ai) — Making Minds AI**
