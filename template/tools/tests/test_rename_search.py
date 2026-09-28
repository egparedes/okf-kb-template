"""Tests for `kb rename-bundle` edge cases, `kb search` and `kb setup` (no network)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kbtools import rename
from kbtools.bundle import Bundle
from kbtools.cli import main

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(FIXTURES / "schema", tmp_path / "schema")
    shutil.copy(REPO / "schema" / "frontmatter.schema.json", tmp_path / "schema")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo-tools"\n\n[tool.kb]\nbundle = "kb"\n', newline="\n"
    )
    (tmp_path / "kb" / "systems").mkdir(parents=True)
    (tmp_path / "kb" / "systems" / "dns.md").write_text(
        "---\ntype: Concept\ntitle: DNS\ndescription: Names.\ntags: []\nstatus: stable\n"
        "generated: { by: test/0, at: 2026-09-25T12:00:00Z }\n---\n\nDNS resolves names.\n",
        newline="\n",
    )
    (tmp_path / ".copier-answers.yml").write_text(
        "_commit: v9.9.9\n_src_path: /nowhere\nbundle_dir: kb\n", newline="\n"
    )
    monkeypatch.setenv("KB_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("KB_QMD_COLLECTION", raising=False)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def test_rename_untracked_folder_with_a_fake_recopy(repo: Path) -> None:
    touched = repo / ".cache" / "kb-touched.txt"
    touched.parent.mkdir()
    touched.write_text(f"{(repo / 'kb' / 'systems' / 'dns.md').resolve()}\n/elsewhere/kb/x.md\n", newline="\n")
    ok = [sys.executable, "-c", ""]
    assert rename.rename(Bundle(repo / "kb", repo), "notes", recopy_command=ok) == 0
    assert (repo / "notes" / "systems" / "dns.md").is_file() and not (repo / "kb").exists()
    assert (repo / "notes" / "index.md").is_file()  # indexes regenerated in the new folder
    lines = touched.read_text().splitlines()
    assert lines == [str((repo / "notes" / "systems" / "dns.md").resolve()), "/elsewhere/kb/x.md"]


def test_rename_rolls_back_an_untracked_folder(repo: Path) -> None:
    fail = [sys.executable, "-c", "raise SystemExit(3)"]
    with pytest.raises(SystemExit, match="put back"):
        rename.rename(Bundle(repo / "kb", repo), "notes", recopy_command=fail)
    assert (repo / "kb" / "systems" / "dns.md").is_file() and not (repo / "notes").exists()


def test_rename_refusals(repo: Path, capsys) -> None:
    b = Bundle(repo / "kb", repo)
    assert rename.rename(b, "kb") == 0 and "already named" in capsys.readouterr().out
    for name, message in (
        ("Bad_Name", "kebab-case"),
        ("tools", "folder of the repository"),
        ("journal", "standard folder"),
        ("systems", "already has a folder"),
    ):
        with pytest.raises(SystemExit, match=message):
            rename.rename(b, name)
    (repo / ".copier-answers.yml").write_text("bundle_dir: kb\n", newline="\n")
    with pytest.raises(SystemExit, match="no _commit"):
        rename.rename(b, "notes")


def fake_qmd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail: bool = False) -> Path:
    """A stand-in qmd on PATH that logs its arguments: a Python script behind a shell
    wrapper, or behind a .bat wrapper on Windows (where qmd itself is a .cmd shim)."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    log = tmp_path / "qmd.log"
    script = tmp_path / "fake_qmd.py"
    script.write_text(
        "import sys\n"
        f"with open({str(log)!r}, 'a', encoding='utf-8') as fh:\n"
        "    fh.write(' '.join(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:3] == ['collection', 'list']:\n"
        "    print('demo (qmd://demo/)')\n"
        "    sys.exit(0)\n"
        f"sys.exit({4 if fail else 0})\n",
        encoding="utf-8",
        newline="\n",
    )
    if os.name == "nt":
        (bin_dir / "qmd.bat").write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8", newline="")
    else:
        (bin_dir / "qmd").write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8", newline="\n"
        )
        (bin_dir / "qmd").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def test_search_cli(repo: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    for query in ([""], ["   "]):
        with pytest.raises(SystemExit, match="give a query"):
            main(["search", *query])
    with pytest.raises(SystemExit):
        main(["search", "--setup", "--reindex"])
    assert main(["search", "resolves", "names"]) == 0  # no qmd on PATH: the text search
    assert "kb/systems/dns.md:3" in capsys.readouterr().out  # "resolves", "names", "Names."
    log = fake_qmd(tmp_path, monkeypatch)
    assert main(["search", "how", "does", "dns", "work"]) == 0
    assert "query how does dns work -c demo" in log.read_text()


def test_search_setup_reports_qmd_failures(repo: Path, tmp_path: Path, monkeypatch) -> None:
    fake_qmd(tmp_path, monkeypatch, fail=True)
    with pytest.raises(SystemExit, match=r"`qmd collection add .* failed \(exit 4\)"):
        main(["search", "--setup"])


def _which(tools: dict[str, str]):
    return lambda name: tools.get(name)


def test_qmd_npm_shim_runs_its_script_with_node(tmp_path: Path, monkeypatch) -> None:
    """On Windows qmd is `qmd.cmd`, run by cmd.exe: its script is run with node instead."""
    from kbtools import search

    shim = tmp_path / "npm" / "qmd.cmd"
    script = tmp_path / "npm" / "node_modules" / "@tobilu" / "qmd" / "dist" / "qmd.js"
    script.parent.mkdir(parents=True)
    script.write_text("// qmd\n", encoding="utf-8", newline="\n")
    shim.write_text(
        "@ECHO off\r\n...\r\nendLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "
        '"%_prog%"  "%dp0%\\node_modules\\@tobilu\\qmd\\dist\\qmd.js" %*\r\n',
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setattr(search, "which_on_path", _which({"qmd": str(shim), "node": "/bin/node.exe"}))
    argv = search.qmd_argv("query", "a&calc", "-c", "demo")
    assert argv[0] == "/bin/node.exe" and Path(argv[1]).resolve() == script.resolve()
    assert argv[2:] == ["query", "a&calc", "-c", "demo"]


@pytest.mark.parametrize("arg", ["a&calc", "x|y", "%PATH%", 'say "hi"', "wow!", "a^b", "<in", "two\nlines"])
def test_qmd_batch_file_refuses_what_cmd_would_reinterpret(repo: Path, tmp_path: Path, monkeypatch, arg: str) -> None:
    from kbtools import search

    shim = tmp_path / "qmd.bat"
    shim.write_text("@echo off\r\n", encoding="utf-8", newline="\n")  # no npm script to run with node
    monkeypatch.setattr(search, "which_on_path", _which({"qmd": str(shim)}))
    assert search.qmd_argv("query", "plain words (and more)") == [str(shim), "query", "plain words (and more)"]
    with pytest.raises(ValueError, match=r"cmd\.exe would reinterpret"):
        search.qmd_argv("query", arg)
    monkeypatch.setattr(search, "qmd_ready", lambda collection: True)
    with pytest.raises(SystemExit, match="kb search: qmd is the batch file"):
        main(["search", arg])


@pytest.mark.skipif(os.name != "nt", reason="a real .bat file needs Windows")
def test_qmd_batch_file_does_not_run_injected_commands(repo: Path, tmp_path: Path, monkeypatch) -> None:
    log = fake_qmd(tmp_path, monkeypatch)
    marker = tmp_path / "pwned.txt"
    with pytest.raises(SystemExit, match=r"cmd\.exe would reinterpret"):
        main(["search", f"dns&echo x>{marker}"])
    assert not marker.exists()
    assert main(["search", "how", "does", "dns", "work"]) == 0
    assert "query how does dns work -c demo" in log.read_text(encoding="utf-8")


def test_setup_initializes_git_and_hooks(tmp_path: Path, monkeypatch) -> None:
    shutil.copytree(FIXTURES / "schema", tmp_path / "schema")
    shutil.copy(REPO / "schema" / "frontmatter.schema.json", tmp_path / "schema")
    (tmp_path / "kb").mkdir()
    (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n", newline="\n")
    monkeypatch.setenv("KB_REPO_ROOT", str(tmp_path))
    assert main(["setup"]) == 0
    assert (tmp_path / ".git").is_dir() and (tmp_path / ".git" / "hooks" / "pre-commit").is_file()
    assert (tmp_path / "kb" / "index.md").is_file()
