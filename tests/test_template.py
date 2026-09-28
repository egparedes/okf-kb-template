"""Render the template in a few configurations and run each result's own checks."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from copier import run_copy

TEMPLATE = Path(__file__).resolve().parents[1]

VARIANTS = {
    "defaults": {},
    "custom-folder": {"kb_name": "team-notes", "bundle_dir": "notes-vault"},
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
    answers = VARIANTS[variant]
    bundle = answers.get("bundle_dir", answers.get("kb_name", "my-kb"))  # new knowledge bases: named after kb_name
    dst = render(tmp_path, answers)
    assert (dst / ".copier-answers.yml").is_file()
    assert not (dst / "kb").exists()
    assert "okf_version" in (dst / bundle / "index.md").read_text()
    assert f'bundle = "{bundle}"' in (dst / "pyproject.toml").read_text()
    assert f"{bundle}/.obsidian/plugins/*/*" in (dst / ".gitignore").read_text()
    assert f"^{bundle}/" in (dst / ".pre-commit-config.yaml").read_text()
    assert f"`{bundle}/`" in (dst / "AGENTS.md").read_text()
    assert "0 error(s), 0 warning(s)" in run(["uv", "run", "--quiet", "kb", "check"], dst)
    run(["uv", "run", "--quiet", "kb", "index", "--check"], dst)
    run(["uv", "run", "--quiet", "pytest", "-q"], dst)
    leftovers = [p for p in dst.rglob("*") if "{%" in p.name or "{{" in p.name or p.suffix == ".jinja"]
    assert leftovers == []
    name = VARIANTS[variant].get("kb_name", "my-kb")
    probe = "from kbtools.bundle import Bundle; from kbtools import search; b = Bundle.discover(); print(b.prefix, search.qmd_collection(b))"
    assert run(["uv", "run", "--quiet", "python", "-c", probe], dst).split() == [bundle, name]
    listing = subprocess.run(["uv", "run", "--quiet", "poe"], cwd=dst, capture_output=True, text=True).stdout  # lists, exits 1
    assert all(task in listing for task in ("setup", "check", "ci", "rename-bundle", "obsidian-setup", "search"))
    fake = tmp_path / "fake-bin"  # a stand-in uv that prints its arguments (no network)
    fake.mkdir(exist_ok=True)
    (fake / "uv").write_text('#!/bin/sh\necho "uv $*"\n')
    (fake / "uv").chmod(0o755)
    env = dict(os.environ, PATH=f"{fake}{os.pathsep}{os.environ['PATH']}")
    poe = str(dst / ".venv" / "bin" / "poe")
    out = subprocess.run([poe, "validate-okf"], cwd=dst, env=env, capture_output=True, text=True).stdout
    assert out.rstrip().endswith(f"okf_validate.py {bundle}"), out
    assert not (dst / "justfile").exists() and (dst / "tasks.toml").is_file()


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
    managed = src / "template" / "AGENTS.md.jinja"
    managed.write_text(managed.read_text() + "\n<!-- upstream change -->\n")
    (src / "template" / "schema" / "vocabulary.yaml").write_text("# upstream would clobber\n")
    git("commit", "-qam", "v2"), git("tag", "v0.0.2")
    run_update(dst, defaults=True, unsafe=True, quiet=True, overwrite=True, vcs_ref="v0.0.2")
    assert "# local edit" in owned.read_text()
    assert "<!-- upstream change -->" in (dst / "AGENTS.md").read_text()
    assert "_commit: v0.0.2" in (dst / ".copier-answers.yml").read_text()


def test_optional_parts_are_omitted(tmp_path: Path) -> None:
    dst = render(tmp_path, {**VARIANTS["minimal"], "run_setup": False})
    for path in (".claude", "CLAUDE.md", ".github", "cookbook/.obsidian", "cookbook/_templates", "docs/obsidian-setup.md"):
        assert not (dst / path).exists(), path
    assert "Obsidian vault" not in (dst / "AGENTS.md").read_text()


def _template_repo(tmp_path: Path):
    src = tmp_path / "template-repo"
    shutil.copytree(TEMPLATE, src, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache", "site"))
    git = lambda *a, cwd=src: run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd)  # noqa: E731
    git("init", "-q"), git("add", "-A"), git("commit", "-qm", "v1"), git("tag", "v0.0.1")
    return src, git


def _as_pre_v05(src: Path) -> None:
    """Turn a template checkout into the v0.4 layout: no bundle_dir question, the folder is always kb/."""
    import re

    copier_yml = src / "copier.yml"
    text = copier_yml.read_text()
    text = re.sub(r"\nbundle_dir:\n(?:  .*\n|    .*\n)+", "\n", text)
    copier_yml.write_text(text.replace("{{ bundle_dir }}", "kb"))
    (src / "template" / "{{ bundle_dir }}").rename(src / "template" / "kb")
    for path in (src / "template").rglob("*.jinja"):
        path.write_text(path.read_text().replace("{{ bundle_dir }}", "kb").replace("(bundle_dir ~ '/')", "'kb/'"))
    (src / "template" / "justfile").write_text("# the v0.4 task runner\ncheck:\n    uv run kb check\n")


@pytest.mark.skipif(shutil.which("uv") is None or shutil.which("git") is None, reason="needs uv and git")
def test_update_of_a_pre_v05_knowledge_base_keeps_kb(tmp_path: Path) -> None:
    from copier import run_update

    src = tmp_path / "template-repo"
    shutil.copytree(TEMPLATE, src, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache", "site"))
    git = lambda *a, cwd=src: run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd)  # noqa: E731
    current = tmp_path / "current"
    shutil.copytree(src, current)
    _as_pre_v05(src)
    git("init", "-q"), git("add", "-A"), git("commit", "-qm", "v0.4-like"), git("tag", "v0.0.1")
    dst = tmp_path / "old-instance"
    run_copy(str(src), dst, data={"kb_name": "legacy", "run_setup": False}, defaults=True, unsafe=True, quiet=True, vcs_ref="v0.0.1")
    assert (dst / "kb" / "log.md").is_file() and "bundle_dir" not in (dst / ".copier-answers.yml").read_text()
    git("init", "-q", cwd=dst), git("add", "-A", cwd=dst), git("commit", "-qm", "init", cwd=dst)
    (dst / "justfile").write_text((dst / "justfile").read_text() + "mine:\n    echo local\n")
    git("commit", "-qam", "a local recipe", cwd=dst)
    for item in src.iterdir():  # v0.0.2 = the current template
        if item.name != ".git":
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    shutil.copytree(current, src, dirs_exist_ok=True)
    git("add", "-A"), git("commit", "-qm", "v0.5-like"), git("tag", "v0.0.2")
    run_update(dst, defaults=True, unsafe=True, quiet=True, overwrite=True, vcs_ref="v0.0.2")
    assert (dst / "kb" / "log.md").is_file() and not (dst / "legacy").exists()
    assert 'bundle = "kb"' in (dst / "pyproject.toml").read_text()
    assert "kb/.obsidian/plugins/*/*" in (dst / ".gitignore").read_text()
    assert not (dst / "justfile").exists()  # removed upstream in v0.6: deleted even though edited
    assert "mine:" in run(["git", "show", "HEAD:justfile"], dst)  # recoverable from git, as the docs say
    assert (dst / "tasks.toml").is_file()


@pytest.mark.skipif(not all(shutil.which(t) for t in ("uv", "git")), reason="needs uv and git")
def test_rename_bundle_moves_everything_and_rerenders(tmp_path: Path) -> None:
    src, git = _template_repo(tmp_path)
    dst = tmp_path / "instance"
    run_copy(str(src), dst, data={"kb_name": "demo"}, defaults=True, unsafe=True, quiet=True, vcs_ref="v0.0.1")
    git("init", "-q", cwd=dst), git("add", "-A", cwd=dst), git("commit", "-qm", "init", cwd=dst)
    (dst / "demo" / "general" / "draft-note.md").parent.mkdir(parents=True, exist_ok=True)
    (dst / "demo" / "general" / "draft-note.md").write_text("untracked, not committed")
    template_page = dst / "demo" / "_templates" / "knowledge-page.md"
    template_page.write_text(template_page.read_text() + "\n<!-- local edit -->\n")
    refused = subprocess.run(["uv", "run", "--quiet", "poe", "rename-bundle", "field-notes"], cwd=dst, capture_output=True, text=True)
    assert refused.returncode != 0 and "_templates/knowledge-page.md" in refused.stderr and (dst / "demo").is_dir()
    git("checkout", "--", "demo/_templates", cwd=dst)
    agents = dst / "AGENTS.md"
    agents.write_text(agents.read_text() + "\nA committed local note.\n")
    git("commit", "-qam", "local edit to a managed file", cwd=dst)
    (dst / "demo" / "field-notes").mkdir()
    blocked = subprocess.run(["uv", "run", "--quiet", "poe", "rename-bundle", "field-notes"], cwd=dst, capture_output=True, text=True)
    assert blocked.returncode != 0 and "already has a folder named field-notes" in blocked.stderr
    (dst / "demo" / "field-notes").rmdir()
    out = run(["uv", "run", "--quiet", "poe", "rename-bundle", "field-notes"], dst)
    assert "reverted" in out and "AGENTS.md" in out  # the committed local edit is reported
    staged = run(["git", "diff", "--cached", "--name-status"], dst)
    assert "R100\tdemo/log.md\tfield-notes/log.md" in staged and "M\tpyproject.toml" in staged
    assert "draft-note.md" in run(["git", "status", "--porcelain"], dst).split("??", 1)[-1]  # still untracked
    assert not (dst / "demo").exists()
    assert (dst / "field-notes" / "general" / "draft-note.md").read_text() == "untracked, not committed"
    assert (dst / "field-notes" / "log.md").is_file()
    assert 'bundle = "field-notes"' in (dst / "pyproject.toml").read_text()
    assert "bundle_dir: field-notes" in (dst / ".copier-answers.yml").read_text()
    assert "field-notes/.obsidian/plugins/*/*" in (dst / ".gitignore").read_text()
    assert "`field-notes/`" in (dst / "AGENTS.md").read_text()
    (dst / "field-notes" / "general" / "draft-note.md").unlink()
    run(["uv", "run", "--quiet", "kb", "index"], dst)
    assert "0 error(s)" in run(["uv", "run", "--quiet", "kb", "check"], dst)
    bad = subprocess.run(["uv", "run", "--quiet", "poe", "rename-bundle", "schema"], cwd=dst, capture_output=True, text=True)
    assert bad.returncode != 0 and "already a folder" in bad.stderr


@pytest.mark.parametrize("name", ["general", "schema", "Not_Kebab"])
def test_invalid_bundle_dir_is_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="Validation error for question 'bundle_dir'"):
        render(tmp_path, {"bundle_dir": name, "run_setup": False})


@pytest.mark.skipif(not all(shutil.which(t) for t in ("uv", "git")), reason="needs uv and git")
def test_rename_bundle_rolls_back_when_the_template_is_unreachable(tmp_path: Path) -> None:
    src, git = _template_repo(tmp_path)
    dst = tmp_path / "instance"
    run_copy(str(src), dst, data={"kb_name": "demo"}, defaults=True, unsafe=True, quiet=True, vcs_ref="v0.0.1")
    answers = dst / ".copier-answers.yml"
    answers.write_text(answers.read_text().replace(f"_src_path: {src}", "_src_path: /nonexistent/template"))
    git("init", "-q", cwd=dst), git("add", "-A", cwd=dst), git("commit", "-qm", "init", cwd=dst)
    failed = subprocess.run(["uv", "run", "--quiet", "poe", "rename-bundle", "field-notes"], cwd=dst, capture_output=True, text=True)
    assert failed.returncode != 0 and "put back" in failed.stderr
    assert (dst / "demo" / "log.md").is_file() and not (dst / "field-notes").exists()
    assert run(["git", "status", "--porcelain"], dst).strip() == ""


def test_custom_folder_leaves_no_stray_kb_paths(tmp_path: Path) -> None:
    import re

    dst = render(tmp_path, {"kb_name": "team-notes", "bundle_dir": "notes-vault", "run_setup": False})
    stray = []
    for path in dst.rglob("*"):
        if path.is_dir() or "tests" in path.parts or path.suffix in (".py", ".json", ".base"):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if re.search(r"(?<![\w./-])kb/", line) and "before v0.5" not in line:
                stray.append(f"{path.relative_to(dst)}:{n}: {line.strip()}")
    assert stray == []


@pytest.mark.skipif(not all(shutil.which(t) for t in ("uv", "git")), reason="needs uv and git")
def test_rename_bundle_warns_only_about_real_edits(tmp_path: Path) -> None:
    src, git = _template_repo(tmp_path)
    dst = tmp_path / "instance"
    answers = {"kb_name": "demo", "bundle_dir": "kb", "obsidian": False, "claude_code": False}
    run_copy(str(src), dst, data=answers, defaults=True, unsafe=True, quiet=True, vcs_ref="v0.0.1")
    git("init", "-q", cwd=dst), git("add", "-A", cwd=dst), git("commit", "-qm", "init", cwd=dst)
    # to the knowledge base's own name (kb_name appears in the answers), then to a word used in
    # the text ("notes"), then back to `kb` (the `kb` command appears everywhere): all pure renames
    for old, new in (("kb", "demo"), ("demo", "notes"), ("notes", "kb")):
        out = run(["uv", "run", "--quiet", "poe", "rename-bundle", new], dst)
        assert "WARNING" not in out, (new, out)
        assert (dst / new / "log.md").is_file() and not (dst / old).exists()
        git("commit", "-qm", f"rename to {new}", cwd=dst)
    assert "0 error(s)" in run(["uv", "run", "--quiet", "kb", "check"], dst)


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")
def test_local_tasks_and_paths_with_spaces(tmp_path: Path) -> None:
    dst = render(tmp_path / "with space", {"kb_name": "demo", "run_setup": False})
    (dst / "tasks.toml").write_text((dst / "tasks.toml").read_text() + 'hello = { cmd = "echo local task", help = "A local task" }\n')
    listing = subprocess.run(["uv", "run", "--quiet", "poe"], cwd=dst, capture_output=True, text=True).stdout
    assert "hello" in listing and "A local task" in listing
    fake = tmp_path / "fake-bin"
    fake.mkdir()
    (fake / "lychee").write_text('#!/bin/sh\nfor a in "$@"; do echo "ARG[$a]"; done\n')
    (fake / "lychee").chmod(0o755)
    env = dict(os.environ, PATH=f"{fake}{os.pathsep}{os.environ['PATH']}")
    out = subprocess.run([str(dst / ".venv" / "bin" / "poe"), "links-online"], cwd=dst, env=env, capture_output=True, text=True).stdout
    assert f"ARG[{dst}/demo]" in out and "ARG[demo/**/*.md]" in out, out
