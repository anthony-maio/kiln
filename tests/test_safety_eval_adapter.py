import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def write_fake_safety_eval(root: Path):
    eval_dir = root / "evaluation"
    eval_dir.mkdir(parents=True)
    (eval_dir / "eval.py").write_text(
        """
import json
import sys
from pathlib import Path

args = sys.argv[1:]
report_path = Path(args[args.index("--report_output_path") + 1])
details_path = Path(args[args.index("--save_individual_results_path") + 1])
tasks = args[args.index("--tasks") + 1].split(",")

report_payload = {
    "results": {
        task: {"metrics": {"macro ASR": 0.05 if task == "harmbench" else 0.02}}
        for task in tasks
    }
}
report_path.write_text(json.dumps(report_payload), encoding="utf-8")
details_path.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
        """.strip(),
        encoding="utf-8",
    )


def test_safety_eval_adapter_persists_real_mode_outputs(tmp_path):
    fake_harness_root = tmp_path / "safety-eval"
    write_fake_safety_eval(fake_harness_root)
    artifact_path = tmp_path / "artifacts" / "safety.json"
    artifact_path.parent.mkdir(parents=True)

    env = os.environ.copy()
    env["KILN_SAFETY_EVAL_PATH"] = str(fake_harness_root)

    completed = subprocess.run(
        [
            sys.executable,
            "adapters/safety_eval_adapter.py",
            "--model-path",
            str(tmp_path / "model"),
            "--artifact-path",
            str(artifact_path),
            "--benchmarks",
            "harmbench,wildguardtest",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["provider"] == "safety_eval"
    assert payload["benchmarks"][0]["success_rate"] == 0.05
    assert payload["benchmarks"][1]["success_rate"] == 0.02

    raw_report_path = Path(payload["raw_report_path"])
    individual_results_path = Path(payload["individual_results_path"])
    assert raw_report_path.exists()
    assert individual_results_path.exists()
