"""Tests for the kb tooling, run against small throwaway bundles and the real kb/."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from kbtools import indexgen, linkfix, pages
from kbtools.bundle import Bundle, bundle_dir
from kbtools.check import Checker

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

GOOD_FM = """---
type: Concept
title: {title}
description: {title} in one sentence.
tags: [test]
status: stable
generated: {{ by: test/0, at: 2026-09-25T12:00:00Z }}
{extra}---
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURES / "schema", tmp_path / "schema")
    shutil.copy(REPO / "schema" / "frontmatter.schema.json", tmp_path / "schema")
    (tmp_path / "kb").mkdir()
    return tmp_path


def write(repo: Path, rel: str, text: str) -> Path:
    path = repo / "kb" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def page(title: str, body: str = "", extra: str = "") -> str:
    return GOOD_FM.format(title=title, extra=extra) + "\n" + body


def codes(repo: Path) -> list[str]:
    return [d.code for d in Checker(Bundle(repo / "kb", repo)).check_all()]


def fresh(repo: Path) -> Bundle:
    return Bundle(repo / "kb", repo)


# -- OKF conformance ---------------------------------------------------------


def test_missing_frontmatter_and_type_are_conformance_errors(repo: Path) -> None:
    write(repo, "systems/a.md", "# no frontmatter\n")
    write(repo, "systems/b.md", "---\ntitle: B\n---\nbody\n")
    found = codes(repo)
    assert "O001" in found and "O002" in found


def test_frontmatter_only_allowed_in_root_index(repo: Path) -> None:
    write(repo, "systems/index.md", '---\nokf_version: "0.2"\n---\n# Pages\n')
    write(repo, "index.md", '---\nokf_version: "0.2"\nextra: 1\n---\n# Pages\n')
    diagnostics = Checker(fresh(repo)).check_all()
    assert {str(d.path) for d in diagnostics if d.code == "O003"} == {"systems/index.md", "index.md"}


def test_log_dates_must_be_newest_first(repo: Path) -> None:
    write(repo, "log.md", "# Log\n\n## 2026-01-01\n\n* a\n\n## 2026-02-01\n\n* b\n")
    assert "O005" in codes(repo)


def test_generated_bundle_is_clean(repo: Path) -> None:
    write(repo, "systems/dns.md", page("DNS", "See [TCP](/systems/tcp.md).\n"))
    write(repo, "systems/tcp.md", page("TCP"))
    indexgen.write(fresh(repo))
    assert codes(repo) == []
    root = (repo / "kb" / "index.md").read_text()
    assert root.startswith('---\nokf_version: "0.2"\n---\n')
    assert "* [Systems](./systems/index.md) - " in root
    assert "* [DNS](./dns.md) - DNS in one sentence." in (repo / "kb/systems/index.md").read_text()


def test_stale_index_is_reported(repo: Path) -> None:
    indexgen.write(fresh(repo))
    write(repo, "systems/new.md", page("New"))
    assert "H040" in codes(repo)


# -- house rules ---------------------------------------------------------------


def test_footnotes_must_match_sources(repo: Path) -> None:
    extra = "sources:\n  - id: good\n    resource: https://example.com\n"
    write(repo, "systems/a.md", page("A", "Claim.[^good] Other.[^bad]\n\n[^good]: Example\n", extra))
    found = codes(repo)
    assert "H020" in found and "H021" in found


def test_numeric_and_text_source_ids_do_not_crash_the_check(repo: Path) -> None:
    """A YAML number as a source id (the schema reports it) next to a text id used to raise TypeError."""
    extra = (
        "sources:\n  - id: 7\n    resource: https://example.com/7\n  - id: good\n    resource: https://example.com\n"
    )
    write(repo, "systems/a.md", page("A", "Claim.\n", extra))
    found = codes(repo)
    assert found.count("W020") == 2 and "H010" in found


def test_relation_needs_prose_link(repo: Path) -> None:
    write(repo, "systems/b.md", page("B"))
    write(repo, "systems/a.md", page("A", "No link here.\n", 'depends_on: ["[B](/systems/b.md)"]\n'))
    assert "H031" in codes(repo)
    write(repo, "systems/a.md", page("A", "Builds on [B](/systems/b.md).\n", 'depends_on: ["[B](/systems/b.md)"]\n'))
    assert "H031" not in codes(repo)


def test_type_placement_and_vocabulary(repo: Path) -> None:
    write(repo, "systems/s.md", page("S").replace("type: Concept", "type: Source"))
    write(repo, "systems/x.md", page("X").replace("type: Concept", "type: Gizmo"))
    found = codes(repo)
    assert "H012" in found and "H013" in found and "H011" in found


def test_links_in_code_are_ignored(repo: Path) -> None:
    write(repo, "systems/a.md", page("A", "`[x](nowhere.md)`\n\n```md\n[y](../../escape.md)\n```\n"))
    indexgen.write(fresh(repo))
    assert codes(repo) == []


def test_vocabulary_extends_schema(repo: Path) -> None:
    write(repo, "systems/b.md", page("B"))
    write(
        repo,
        "systems/a.md",
        page("A", "Uses [B](/systems/b.md).\n", 'related: ["[B](/systems/b.md)"]\nisbn: "978-3"\n'),
    )
    indexgen.write(fresh(repo))
    assert codes(repo) == []
    write(repo, "systems/a.md", page("A", "Uses [B](/systems/b.md).\n", 'related: "/systems/b.md"\nisbn: "abc"\n'))
    assert [c for c in codes(repo) if c == "H010"] == ["H010", "H010"]


def test_personal_folders_come_from_taxonomy(repo: Path) -> None:
    assert fresh(repo).config.personal_folders == {"journal"}


# -- link maintenance ------------------------------------------------------------


def test_fix_links_makes_links_bundle_absolute(repo: Path) -> None:
    write(repo, "systems/tcp.md", page("TCP"))
    write(repo, "data/sql.md", page("SQL"))
    path = write(
        repo,
        "systems/dns.md",
        page(
            "DNS",
            "[rel](tcp.md) [vault](data/sql.md#joins) [abs](/systems/tcp.md) [web](https://x.org) `[code](tcp.md)`\n",
            'related: ["[SQL](../data/sql.md)"]\n',
        ),
    )
    linkfix.fix(fresh(repo))
    text = path.read_text()
    assert "[rel](/systems/tcp.md)" in text
    assert "[vault](/data/sql.md#joins)" in text
    assert "`[code](tcp.md)`" in text
    assert 'related: ["[SQL](/data/sql.md)"]' in text


def test_mv_rewrites_inbound_links(repo: Path) -> None:
    write(repo, "systems/tcp.md", page("TCP", "Peer of [DNS](/systems/dns.md).\n"))
    extra = 'related: ["[TCP](/systems/tcp.md)"]\nsources:\n  - id: t\n    resource: /systems/tcp.md\n'
    dns = write(repo, "systems/dns.md", page("DNS", "Uses [TCP](../systems/tcp.md#handshake).[^t]\n\n[^t]: x\n", extra))
    linkfix.move(fresh(repo), "systems/tcp.md", "systems/networking/tcp.md")
    text = dns.read_text()
    assert "[TCP](/systems/networking/tcp.md#handshake)" in text
    assert 'related: ["[TCP](/systems/networking/tcp.md)"]' in text
    assert "resource: /systems/networking/tcp.md" in text
    moved = (repo / "kb/systems/networking/tcp.md").read_text()
    assert "[DNS](/systems/dns.md)" in moved


# -- pages and log ---------------------------------------------------------------


def test_log_entries_are_newest_first(repo: Path) -> None:
    bundle = fresh(repo)
    pages.add_log_entry(bundle, "ingest", "first", day=date(2026, 9, 24))
    pages.add_log_entry(bundle, "update", "second", day=date(2026, 9, 25))
    pages.add_log_entry(bundle, "lint", "third", day=date(2026, 9, 25))
    text = (repo / "kb/log.md").read_text()
    assert text.index("## 2026-09-25") < text.index("## 2026-09-24")
    assert text.index("**Lint**: third") < text.index("**Update**: second")
    assert "O005" not in codes(repo)


def test_new_page_is_valid(repo: Path) -> None:
    pages.new_page(
        fresh(repo),
        "Source",
        "sources/rfc-9110.md",
        "RFC 9110",
        "HTTP semantics.",
        ["http"],
        "test/0",
        resource="https://www.rfc-editor.org/rfc/rfc9110",
    )
    indexgen.write(fresh(repo))
    assert codes(repo) == []
    assert "# Summary" in (repo / "kb/sources/rfc-9110.md").read_text()


# -- the real bundle ---------------------------------------------------------------


def test_repository_bundle_is_clean() -> None:
    diagnostics = Checker(Bundle(REPO / bundle_dir(REPO), REPO)).check_all()
    assert [str(d) for d in diagnostics if d.is_error] == []


# -- regressions from review ----------------------------------------------------


def test_stale_after_without_offset_is_a_diagnostic_not_a_crash(repo: Path) -> None:
    write(repo, "systems/a.md", page("A", extra="stale_after: 2026-01-01\n"))
    write(repo, "systems/b.md", page("B", extra="stale_after: 2020-01-01T00:00:00\n"))
    assert codes(repo).count("H010") == 2


def test_frontmatter_must_close_with_dashes(repo: Path) -> None:
    write(repo, "systems/a.md", "---\ntype: Concept\n...\nbody\n")
    diagnostics = Checker(fresh(repo)).check_all()
    assert any(d.code == "O001" and "not closed" in d.message for d in diagnostics)


def test_log_never_goes_below_a_newer_section(repo: Path) -> None:
    write(repo, "log.md", "# Log\n\n## 2099-01-01\n\n* **Update**: future\n")
    pages.add_log_entry(fresh(repo), "lint", "now")
    text = (repo / "kb/log.md").read_text()
    assert text.count("## ") == 1 and "**Lint**: now" in text


def test_mv_keeps_fragments_quoted_resources_and_rebases(repo: Path) -> None:
    write(repo, "systems/b.md", page("B", "Peer [A](./a.md) and [self](#top)."))
    write(repo, "systems/a.md", page("A"))
    ref = write(
        repo,
        "data/r.md",
        page(
            "R",
            "[B](/systems/b.md 'title')",
            'related: ["[B](/systems/b.md#part)"]\nsources:\n  - id: b\n    resource: "/systems/b.md"\n',
        ),
    )
    linkfix.move(fresh(repo), "systems/b.md", "systems/net/b.md")
    text = ref.read_text()
    assert '"[B](/systems/net/b.md#part)"' in text
    assert 'resource: "/systems/net/b.md"' in text
    assert "[B](/systems/net/b.md 'title')" in text
    moved = (repo / "kb/systems/net/b.md").read_text()
    assert "[A](/systems/a.md)" in moved and "[self](#top)" in moved


def test_new_rejects_paths_outside_the_bundle(repo: Path) -> None:
    with pytest.raises(SystemExit, match="outside"):
        pages.new_page(fresh(repo), "Concept", "../outside.md", "X", "Y.", [], "test/0")


def test_reference_style_links_are_flagged(repo: Path) -> None:
    write(repo, "systems/a.md", page("A", "See [B][b].\n\n[b]: /systems/b.md\n"))
    assert "W033" in codes(repo)


def test_path_arguments_accept_bundle_and_repo_paths(repo: Path) -> None:
    write(repo, "systems/a.md", page("A"))
    b = fresh(repo)
    assert b.path_arg("systems/a.md") == b.path_arg("kb/systems/a.md") == (repo / "kb/systems/a.md").resolve()
    (repo / "README.md").write_text("x", newline="\n")
    assert b.path_arg(str(repo / "README.md")) is None


def test_stop_hook_checks_only_this_sessions_edits(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("CLAUDECODE", raising=False)
    import io
    import json as _json
    import subprocess

    from kbtools import hooks

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    write(repo, "systems/human.md", "---\ntitle: human draft without type\n---\n")
    agent = write(repo, "systems/agent.md", page("Agent"))
    indexgen.write(fresh(repo))
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps({"tool_input": {"file_path": str(agent)}})))
    assert hooks.post_edit(fresh(repo)) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert hooks.stop(fresh(repo)) == 2  # knowledge edit without a log entry
    assert "log.md" in capsys.readouterr().err
    pages.add_log_entry(fresh(repo), "update", "agent page")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert hooks.stop(fresh(repo)) == 0  # the human's broken draft does not block the agent


def test_kb_commands_in_agent_sessions_are_tracked(repo: Path, monkeypatch) -> None:
    import io
    import subprocess

    from kbtools import hooks

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    monkeypatch.setenv("CLAUDECODE", "1")
    created = pages.new_page(fresh(repo), "Concept", "systems/new.md", "New", "New.", [], "test/0")
    created.write_text(created.read_text() + "\nSee [[Wiki]].\n", newline="\n")  # edited via Bash, not the Edit tool
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert hooks.stop(fresh(repo)) == 2


def test_bundle_folder_comes_from_pyproject(tmp_path: Path) -> None:
    assert bundle_dir(tmp_path) == "kb"  # no pyproject.toml
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n\n[tool.kb]\nbundle = "my-notes"\n', newline="\n")
    assert bundle_dir(tmp_path) == "my-notes"
    shutil.copytree(FIXTURES / "schema", tmp_path / "schema")
    shutil.copy(REPO / "schema" / "frontmatter.schema.json", tmp_path / "schema")
    (tmp_path / "my-notes" / "systems").mkdir(parents=True)
    page_path = tmp_path / "my-notes" / "systems" / "a.md"
    page_path.write_text(page("A", "Broken [link](/nowhere.md)."), newline="\n")
    b = Bundle(tmp_path / "my-notes", tmp_path)
    assert b.prefix == "my-notes" and b.show("log.md") == "my-notes/log.md"
    assert b.rel("my-notes/systems/a.md") == b.rel("/systems/a.md") == "systems/a.md"
    assert b.path_arg("my-notes/systems/a.md") == page_path.resolve()
    shown = [str(d) for d in Checker(b).check_files([b.document(page_path)])]
    assert any(line.startswith("my-notes/systems/a.md:") for line in shown), shown


def test_prefix_that_is_also_a_folder_inside_the_bundle(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.kb]\nbundle = "notes"\n', newline="\n")
    shutil.copytree(FIXTURES / "schema", tmp_path / "schema")
    shutil.copy(REPO / "schema" / "frontmatter.schema.json", tmp_path / "schema")
    (tmp_path / "notes" / "notes").mkdir(parents=True)  # a domain folder named like the bundle
    b = Bundle(tmp_path / "notes", tmp_path)
    assert b.rel("notes/new-page.md") == "notes/new-page.md"  # the domain folder exists: read inside the bundle
    assert b.rel("notes/notes/new-page.md") == "notes/new-page.md"  # notes/notes/ does not exist inside
    assert b.rel("/notes/x.md") == "notes/x.md"
