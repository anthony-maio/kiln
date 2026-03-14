import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kiln_backend.executors.documentation import execute_documentation_stage


def write_readme(repo_root: Path, *, include_sections=True):
    sections = ""
    if include_sections:
        sections = "\n## Usage\nExample.\n\n## Limitations\nSome limits.\n"
    (repo_root / "README.md").write_text(
        "# Demo Model\n" + sections,
        encoding="utf-8",
    )


def test_execute_documentation_stage_fails_without_readme(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    result = execute_documentation_stage(project_root=repo_root, run_id=21)

    assert result["status"] == "failed"
    payload = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert "README.md" in payload["results"]["missing_required_files"]


def test_execute_documentation_stage_warns_without_model_card(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_readme(repo_root)

    result = execute_documentation_stage(project_root=repo_root, run_id=22)

    assert result["status"] == "warning"
    payload = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert "MODEL_CARD.md" in payload["results"]["missing_recommended_files"]


def test_execute_documentation_stage_passes_with_required_docs(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_readme(repo_root)
    (repo_root / "MODEL_CARD.md").write_text(
        "# Model Card\n\n## Intended Use\nText.\n",
        encoding="utf-8",
    )

    result = execute_documentation_stage(project_root=repo_root, run_id=23)

    assert result["status"] == "passed"
    assert Path(result["artifact_path"]).exists()
    assert Path(result["log_path"]).exists()
