"""Tests for `kb obsidian setup` (downloads are faked)."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from kbtools import obsidian
from kbtools.bundle import Bundle

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FILES = {"main.js": b"console.log('x')", "manifest.json": b'{"id": "p", "version": "1.0.0"}'}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURES / "schema", tmp_path / "schema")
    shutil.copy(REPO / "schema" / "frontmatter.schema.json", tmp_path / "schema")
    (tmp_path / "kb" / ".obsidian").mkdir(parents=True)
    (tmp_path / "kb" / ".obsidian" / "community-plugins.json").write_text('["req"]\n', newline="\n")
    (tmp_path / "tools").mkdir()
    pins = {
        "req": {
            "name": "Req",
            "repo": "o/req",
            "version": "1.0.0",
            "license": "MIT",
            "required": True,
            "sha256": {k: hashlib.sha256(v).hexdigest() for k, v in FILES.items()},
        },
        "opt": {
            "name": "Opt",
            "repo": "o/opt",
            "version": "1.0.0",
            "license": "GPL-3.0",
            "required": False,
            "sha256": {k: hashlib.sha256(v).hexdigest() for k, v in FILES.items()},
        },
    }
    (tmp_path / "tools" / "obsidian-plugins.json").write_text(json.dumps({"plugins": pins}), newline="\n")
    return tmp_path


def fake_fetch(calls: list[str], files: dict[str, bytes] = FILES):
    def fetch(url: str) -> bytes:
        calls.append(url)
        return files[url.rsplit("/", 1)[1]]

    return fetch


def test_installs_listed_and_added_plugins(repo: Path, capsys) -> None:
    calls: list[str] = []
    assert obsidian.setup(Bundle(repo / "kb", repo), ["opt"], fetch=fake_fetch(calls)) == 0
    plugins = repo / "kb" / ".obsidian" / "plugins"
    assert (plugins / "req" / "main.js").read_bytes() == FILES["main.js"]
    assert (plugins / "opt" / "manifest.json").is_file()
    assert json.loads((repo / "kb" / ".obsidian" / "community-plugins.json").read_text()) == ["req", "opt"]
    assert "https://github.com/o/req/releases/download/1.0.0/main.js" in calls
    assert "Trigger Templater on new file creation" in capsys.readouterr().out
    calls.clear()
    obsidian.setup(Bundle(repo / "kb", repo), [], fetch=fake_fetch(calls))
    assert calls == []  # same version already installed: nothing downloaded


def test_checksum_mismatch_writes_nothing(repo: Path) -> None:
    bad = dict(FILES, **{"main.js": b"tampered"})
    with pytest.raises(SystemExit, match="checksum mismatch"):
        obsidian.setup(Bundle(repo / "kb", repo), [], fetch=fake_fetch([], bad))
    assert not (repo / "kb" / ".obsidian" / "plugins" / "req").exists()


def test_required_plugins_come_back_and_unknown_ids_are_reported(repo: Path, capsys) -> None:
    (repo / "kb" / ".obsidian" / "community-plugins.json").write_text('["someone-elses"]\n', newline="\n")
    obsidian.setup(Bundle(repo / "kb", repo), [], fetch=fake_fetch([]))
    assert json.loads((repo / "kb" / ".obsidian" / "community-plugins.json").read_text()) == ["req", "someone-elses"]
    assert "someone-elses: no pin" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="no pin for nope"):
        obsidian.setup(Bundle(repo / "kb", repo), ["nope"], fetch=fake_fetch([]))


def test_shipped_pins_are_well_formed() -> None:
    pins = json.loads((REPO / "tools" / "obsidian-plugins.json").read_text())["plugins"]
    assert {p for p, s in pins.items() if s["required"]} == {"templater-obsidian", "better-markdown-links"}
    for spec in pins.values():
        assert {"main.js", "manifest.json"} <= set(spec["sha256"]) <= set(obsidian.ASSETS)
        assert all(len(h) == 64 for h in spec["sha256"].values())


def test_newer_install_is_kept_and_force_restores_the_pin(repo: Path) -> None:
    folder = repo / "kb" / ".obsidian" / "plugins" / "req"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text('{"version": "1.2.0"}', newline="\n")
    (folder / "styles.css").write_text("old", newline="\n")
    calls: list[str] = []
    obsidian.setup(Bundle(repo / "kb", repo), [], fetch=fake_fetch(calls))
    assert calls == [] and "1.2.0" in (folder / "manifest.json").read_text()
    obsidian.setup(Bundle(repo / "kb", repo), [], force=True, fetch=fake_fetch(calls))
    assert (folder / "manifest.json").read_bytes() == FILES["manifest.json"]
    assert not (folder / "styles.css").exists()  # the pinned release ships no styles.css


def test_failed_add_leaves_the_listing_alone(repo: Path) -> None:
    listing = repo / "kb" / ".obsidian" / "community-plugins.json"
    bad = dict(FILES, **{"main.js": b"tampered"})
    with pytest.raises(SystemExit, match="checksum mismatch"):
        obsidian.setup(Bundle(repo / "kb", repo), ["opt"], fetch=fake_fetch([], bad))
    assert json.loads(listing.read_text()) == ["req"]


def test_invalid_listing_and_network_errors_are_clear(repo: Path) -> None:
    listing = repo / "kb" / ".obsidian" / "community-plugins.json"
    listing.write_text('{"not": "a list"}', newline="\n")
    with pytest.raises(SystemExit, match="must be a JSON list"):
        obsidian.setup(Bundle(repo / "kb", repo), [], fetch=fake_fetch([]))
    listing.write_text('["req"]', newline="\n")

    def offline(url: str) -> bytes:
        return obsidian._download("http://127.0.0.1:9/nothing")

    with pytest.raises(SystemExit, match="cannot download"):
        obsidian.setup(Bundle(repo / "kb", repo), [], fetch=offline)
