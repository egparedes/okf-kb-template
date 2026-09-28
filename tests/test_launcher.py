"""Tests for the global `kb` launcher (launcher/src/okf_kb)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "launcher" / "src"
# A stand-in uv that prints what it was asked to do (a .bat wrapper on Windows, found through PATHEXT).
FAKE_UV = 'import os, sys\nprint("uv", *sys.argv[1:], "| root=" + os.environ["KB_REPO_ROOT"], "| cwd=" + os.getcwd())\n'


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def make_kb(path: Path) -> Path:
    (path / "schema").mkdir(parents=True)
    write(path / "schema" / "vocabulary.yaml", "types: {}\n")
    write(path / "pyproject.toml", '[project]\nname = "x-tools"\n')
    return path


def toml_path(path: Path) -> str:
    return f"'{path}'"  # a literal string: Windows backslashes are not escapes


def launch(args: list[str], cwd: Path, tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    script = tmp_path / "fake_uv.py"
    write(script, FAKE_UV)
    if os.name == "nt":
        (fake_bin / "uv.bat").write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8", newline="")
    else:
        write(fake_bin / "uv", f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        (fake_bin / "uv").chmod(0o755)
    base = {k: v for k, v in os.environ.items() if k not in ("KB_DIR", "KB_REPO_ROOT")}
    full_env = dict(base, PATH=f"{fake_bin}{os.pathsep}{base.get('PATH', '')}", PYTHONPATH=str(SRC),
                    XDG_CONFIG_HOME=str(tmp_path / "config"), **env)
    return subprocess.run([sys.executable, "-m", "okf_kb", *args], cwd=cwd, env=full_env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


@pytest.fixture
def kbs(tmp_path: Path) -> dict[str, Path]:
    one, two = make_kb(tmp_path / "one"), make_kb(tmp_path / "two")
    (one / "kb" / "deep").mkdir(parents=True)
    config = tmp_path / "config" / "okf-kb"
    config.mkdir(parents=True)
    write(config / "config.toml", f'default = "two"\n[knowledge-bases]\none = {toml_path(one)}\ntwo = {toml_path(two)}\n')
    return {"one": one, "two": two}


def test_resolution_order(kbs: dict[str, Path], tmp_path: Path) -> None:
    inside = launch(["check", "--strict"], kbs["one"] / "kb" / "deep", tmp_path)
    assert inside.returncode == 0, inside.stderr
    assert f"run --project {kbs['one']} --quiet kb check --strict | root={kbs['one']}" in inside.stdout
    assert f"cwd={kbs['one'] / 'kb' / 'deep'}" in inside.stdout
    assert f"root={kbs['two']}" in launch(["check"], tmp_path, tmp_path).stdout  # default outside any KB
    assert f"root={kbs['one']}" in launch(["-C", "one", "find"], tmp_path, tmp_path).stdout
    assert f"root={kbs['two']}" in launch(["--kb=" + str(kbs["two"]), "find"], kbs["one"], tmp_path).stdout
    assert f"root={kbs['one']}" in launch(["find"], tmp_path, tmp_path, KB_DIR="one").stdout
    assert launch(["--which"], kbs["one"], tmp_path).stdout.strip() == str(kbs["one"])


def test_list_and_errors(kbs: dict[str, Path], tmp_path: Path) -> None:
    listing = launch(["--list"], tmp_path, tmp_path).stdout
    assert f"* two\t{kbs['two']}" in listing and f"  one\t{kbs['one']}" in listing
    bad = launch(["-C", "nope", "check"], tmp_path, tmp_path)
    assert bad.returncode != 0 and "registered: one, two" in bad.stderr
    (tmp_path / "config" / "okf-kb" / "config.toml").unlink()
    lost = launch(["check"], tmp_path, tmp_path)
    assert lost.returncode != 0 and "not inside a knowledge base" in lost.stderr


def test_config_errors_and_guard(kbs: dict[str, Path], tmp_path: Path) -> None:
    config = tmp_path / "config" / "okf-kb" / "config.toml"
    write(config, 'knowledge-bases = "x"\n')
    assert "must map names to path strings" in launch(["--list"], tmp_path, tmp_path).stderr
    write(config, "this is [ not toml\n")
    ok = launch(["-C", str(kbs["one"]), "find"], tmp_path, tmp_path)  # an explicit -C does not need the config
    assert f"root={kbs['one']}" in ok.stdout
    assert "cannot read" in launch(["find"], tmp_path, tmp_path).stderr
    assert "cannot read" in launch(["find"], tmp_path, tmp_path, KB_DIR="work").stderr  # a name needs the config


@pytest.mark.parametrize("broken", ["this is [ not toml\n", 'knowledge-bases = "x"\n', 'default = 3\n'])
def test_broken_config_is_not_needed_for_a_path(kbs: dict[str, Path], tmp_path: Path, broken: str) -> None:
    write(tmp_path / "config" / "okf-kb" / "config.toml", broken)
    for args, cwd, env in (
        (["find"], tmp_path, {"KB_DIR": str(kbs["one"])}),
        (["-C", str(kbs["one"]), "find"], tmp_path, {}),
        (["find"], kbs["one"] / "kb" / "deep", {}),
    ):
        result = launch(args, cwd, tmp_path, **env)
        assert result.returncode == 0 and f"root={kbs['one']}" in result.stdout, result.stderr


def test_config_relative_paths(kbs: dict[str, Path], tmp_path: Path) -> None:
    config = tmp_path / "config" / "okf-kb" / "config.toml"
    (config.parent / "rel").mkdir()
    make_kb(config.parent / "rel" / "kb3")
    write(config, 'default = "gone"\n[knowledge-bases]\ngone = "/nonexistent"\nrel = "rel/kb3"\n')
    assert "default 'gone'" in launch(["find"], tmp_path, tmp_path).stderr
    assert f"root={config.parent / 'rel' / 'kb3'}" in launch(["-C", "rel", "find"], tmp_path, tmp_path).stdout
    assert "needs a path" in launch(["--kb=", "find"], tmp_path, tmp_path).stderr
    assert "neither a knowledge base" in launch(["find"], tmp_path, tmp_path, KB_DIR="/nonexistent").stderr
    guarded = launch(["find"], kbs["one"], tmp_path, OKF_KB_LAUNCHER="1")
    assert guarded.returncode != 0 and "uv run poe setup" in guarded.stderr
