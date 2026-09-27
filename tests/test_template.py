"""Render the template in a few configurations and run each result's own checks."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from copier import run_copy

TEMPLATE = Path(__file__).resolve().parents[1]

VARIANTS = {
    "defaults": {},
    "minimal": {
        "kb_name": "cookbook",
        "obsidian": False,
        "claude_code": False,
        "github_ci": False,
        "domains": {
            "baking": {"title": "Baking", "description": "Bread and pastry."},
            "baking/sourdough": {"title": "Sourdough", "description": "Wild-yeast breads."},
        },
    },
}


def render(tmp_path: Path, answers: dict) -> Path:
    dst = tmp_path / "kb-instance"
    run_copy(str(TEMPLATE), dst, data=answers, defaults=True, unsafe=True, quiet=True, vcs_ref="HEAD")
    return dst


def run(cmd: list[str], cwd: Path) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, f"{' '.join(cmd)} failed:\n{result.stdout}\n{result.stderr}"
    return result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required to run the rendered tooling")
@pytest.mark.parametrize("variant", VARIANTS)
def test_rendered_knowledge_base_is_conformant(tmp_path: Path, variant: str) -> None:
    dst = render(tmp_path, VARIANTS[variant])
    assert (dst / ".copier-answers.yml").is_file()
    assert "okf_version" in (dst / "kb" / "index.md").read_text()
    assert "0 error(s), 0 warning(s)" in run(["uv", "run", "--quiet", "kb", "check"], dst)
    run(["uv", "run", "--quiet", "kb", "index", "--check"], dst)
    run(["uv", "run", "--quiet", "pytest", "-q"], dst)
    leftovers = [p for p in dst.rglob("*") if "{%" in p.name or "{{" in p.name or p.suffix == ".jinja"]
    assert leftovers == []
    if shutil.which("just"):
        name = VARIANTS[variant].get("kb_name", "my-kb")
        assert run(["just", "--evaluate", "qmd_collection"], dst).strip() == name


@pytest.mark.parametrize("domains", [
    {"My Domain": {"title": "x", "description": "y"}},
    {"physics/quantum": {"title": "Q", "description": "Quantum."}},
    {"ok": {"title": "Only a title"}},
])
def test_invalid_domains_are_rejected(tmp_path: Path, domains: dict) -> None:
    with pytest.raises(ValueError, match="Validation error for question 'domains'"):
        render(tmp_path, {"domains": domains, "run_setup": False})


@pytest.mark.skipif(shutil.which("uv") is None or shutil.which("git") is None, reason="needs uv and git")
def test_update_keeps_owned_files_and_updates_managed_ones(tmp_path: Path) -> None:
    from copier import run_update

    src = tmp_path / "template-repo"
    shutil.copytree(TEMPLATE, src, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache"))
    git = lambda *a, cwd=src: run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd)  # noqa: E731
    git("init", "-q"), git("add", "-A"), git("commit", "-qm", "v1"), git("tag", "v0.0.1")
    dst = tmp_path / "instance"
    run_copy(str(src), dst, defaults=True, unsafe=True, quiet=True, vcs_ref="v0.0.1")
    git("init", "-q", cwd=dst), git("add", "-A", cwd=dst), git("commit", "-qm", "init", cwd=dst)
    owned = dst / "schema" / "vocabulary.yaml"
    owned.write_text(owned.read_text() + "# local edit\n")
    git("commit", "-qam", "local", cwd=dst)
    justfile = src / "template" / "justfile"
    justfile.write_text(justfile.read_text() + "\n# upstream change\n")
    (src / "template" / "schema" / "vocabulary.yaml").write_text("# upstream would clobber\n")
    git("commit", "-qam", "v2"), git("tag", "v0.0.2")
    run_update(dst, defaults=True, unsafe=True, quiet=True, overwrite=True, vcs_ref="v0.0.2")
    assert "# local edit" in owned.read_text()
    assert "# upstream change" in (dst / "justfile").read_text()
    assert "_commit: v0.0.2" in (dst / ".copier-answers.yml").read_text()


def test_optional_parts_are_omitted(tmp_path: Path) -> None:
    dst = render(tmp_path, {**VARIANTS["minimal"], "run_setup": False})
    for path in (".claude", "CLAUDE.md", ".github", "kb/.obsidian", "kb/_templates", "docs/obsidian-setup.md"):
        assert not (dst / path).exists(), path
    assert "Obsidian vault" not in (dst / "AGENTS.md").read_text()
