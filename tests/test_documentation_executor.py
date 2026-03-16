import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kiln_backend.executors.documentation import execute_documentation_stage


def write_readme(
    repo_root: Path,
    *,
    include_sections: bool = True,
    include_evaluation: bool = True,
):
    sections = ""
    if include_sections:
        sections += "\n## Usage\nExample.\n\n## Limitations\nSome limits.\n"
    if include_evaluation:
        sections += "\n## Evaluation Summary\nHellaSwag: 80.0\n"
    (repo_root / "README.md").write_text(
        "# Demo Model\n" + sections,
        encoding="utf-8",
    )


def write_model_card(repo_root: Path, *, include_sections: bool = True):
    sections = ""
    if include_sections:
        sections = (
            "\n## Intended Use\nText.\n"
            "\n## Limitations\nSome limits.\n"
            "\n## Evaluation Data\nHellaSwag.\n"
        )
    (repo_root / "MODEL_CARD.md").write_text(
        "# Model Card\n" + sections,
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


def test_execute_documentation_stage_fails_when_readme_is_missing_release_sections(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_readme(repo_root, include_sections=False, include_evaluation=False)
    write_model_card(repo_root)

    result = execute_documentation_stage(project_root=repo_root, run_id=23)

    assert result["status"] == "failed"
    payload = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert "## Usage" in payload["results"]["missing_required_readme_sections"]
    assert "## Evaluation Summary" in payload["results"]["missing_required_readme_sections"]


def test_execute_documentation_stage_warns_when_model_card_is_missing_recommended_sections(
    tmp_path,
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_readme(repo_root)
    write_model_card(repo_root, include_sections=False)

    result = execute_documentation_stage(project_root=repo_root, run_id=24)

    assert result["status"] == "warning"
    payload = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert "## Intended Use" in payload["results"]["missing_recommended_model_card_sections"]
    assert "## Evaluation Data" in payload["results"]["missing_recommended_model_card_sections"]


def test_execute_documentation_stage_passes_with_release_ready_docs(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_readme(repo_root)
    write_model_card(repo_root)

    result = execute_documentation_stage(project_root=repo_root, run_id=25)

    assert result["status"] == "passed"
    assert Path(result["artifact_path"]).exists()
    assert Path(result["log_path"]).exists()
