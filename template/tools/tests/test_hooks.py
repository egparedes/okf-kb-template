"""Tests for the agent hooks, session tracking, `kb new` actors, `kb log` entries and the skills link."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from kbtools import hooks, indexgen, pages, session
from kbtools.bundle import TOUCHED, Bundle, load_yaml
from kbtools.check import Checker

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

PAGE = """---
type: Concept
title: {title}
description: {title} in one sentence.
tags: [test]
status: stable
generated: {{ by: test/0, at: 2026-09-25T12:00:00Z }}
---

{body}
"""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "kb-repo"  # tmp_path itself can play an enclosing repository
    shutil.copytree(FIXTURES / "schema", root / "schema")
    shutil.copy(REPO / "schema" / "frontmatter.schema.json", root / "schema")
    (root / "kb").mkdir()
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("KB_ACTOR", raising=False)
    return root


def write(repo: Path, rel: str, title: str = "Page", body: str = "") -> Path:
    path = repo / "kb" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PAGE.format(title=title, body=body), encoding="utf-8")
    return path


def fresh(repo: Path) -> Bundle:
    return Bundle(repo / "kb", repo)


def hook(monkeypatch, repo: Path, event: str, agent: str = "claude", **payload) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    return hooks.run(event, agent, fresh(repo))


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True, capture_output=True)


# -- Stop: the log check without git (B7) -------------------------------------------------


@pytest.mark.parametrize("vcs", ["none", "git", "nested"])
def test_stop_log_check_needs_no_git(repo: Path, monkeypatch, capsys, vcs: str) -> None:
    if vcs == "git":
        git(repo, "init", "-q")
    elif vcs == "nested":  # the knowledge base is a subfolder of another repository
        git(repo.parent, "init", "-q")
    page = write(repo, "systems/a.md", "A")
    indexgen.write(fresh(repo))
    assert hook(monkeypatch, repo, "post-edit", session_id="s1", tool_input={"file_path": str(page)}) == 0
    assert hook(monkeypatch, repo, "stop", session_id="s1") == 2
    assert "log.md has no new entry" in capsys.readouterr().err
    pages.add_log_entry(fresh(repo), "update", "Added [A](/systems/a.md).")
    assert hook(monkeypatch, repo, "stop", session_id="s1") == 0
    assert not (repo / session.STATE / "s1").exists()


def test_mid_session_commit_does_not_block_and_old_log_edits_do_not_count(repo: Path, monkeypatch) -> None:
    git(repo, "init", "-q")
    pages.add_log_entry(fresh(repo), "update", "the human's uncommitted entry")  # before the session
    page = write(repo, "systems/a.md", "A")
    indexgen.write(fresh(repo))
    hook(monkeypatch, repo, "post-edit", session_id="s1", tool_input={"file_path": str(page)})
    assert hook(monkeypatch, repo, "stop", session_id="s1") == 2  # the human's edit is not this session's entry
    pages.add_log_entry(fresh(repo), "update", "Added [A](/systems/a.md).")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "agent commits mid-session")
    assert hook(monkeypatch, repo, "stop", session_id="s1") == 0


def test_sessions_do_not_share_touched_pages(repo: Path, monkeypatch) -> None:
    broken = write(repo, "systems/a.md", "A", "See [[Wiki]].")
    indexgen.write(fresh(repo))
    hook(monkeypatch, repo, "post-edit", session_id="one", tool_input={"file_path": str(broken)})
    assert hook(monkeypatch, repo, "stop", session_id="one") == 2
    assert hook(monkeypatch, repo, "stop", session_id="one", stop_hook_active=True) == 0  # no endless loop
    assert hook(monkeypatch, repo, "stop", session_id="two") == 0  # another session is not blocked
    assert hook(monkeypatch, repo, "stop", session_id="one") == 2  # but the first one still is


def test_stale_touched_paths_are_dropped(repo: Path, monkeypatch, tmp_path: Path) -> None:
    (repo / TOUCHED).parent.mkdir(parents=True, exist_ok=True)
    moved_away = tmp_path / "old-location" / "kb" / "systems" / "a.md"  # the repository was moved
    write(repo, "systems/a.md", "A", "See [[Wiki]].")  # the same page at the new location is not claimed
    (repo / TOUCHED).write_text(f"{moved_away}\n{repo / 'README.md'}\n../outside.md\n", encoding="utf-8")
    assert hook(monkeypatch, repo, "stop") == 0
    assert not (repo / TOUCHED).exists()


def test_kb_commands_are_claimed_by_the_running_session(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")
    hook(monkeypatch, repo, "pre-tool", session_id="s1", tool_use_id="t1")
    created = pages.new_page(fresh(repo), "Concept", "systems/new.md", "New", "New.", [], "test/0")
    created.write_text(created.read_text() + "\nSee [[Wiki]].\n")
    hook(monkeypatch, repo, "post-tool", session_id="s1", tool_use_id="t1")
    assert not (repo / TOUCHED).exists()
    assert "systems/new.md" in (repo / session.STATE / "s1" / "touched").read_text()
    assert hook(monkeypatch, repo, "stop", session_id="other") == 0
    assert hook(monkeypatch, repo, "stop", session_id="s1") == 2


# -- shell commands (S7) ----------------------------------------------------------------


def test_shell_changes_are_recorded_and_checked(repo: Path, monkeypatch, capsys) -> None:
    keep = write(repo, "systems/keep.md", "Keep")
    gone = write(repo, "systems/gone.md", "Gone")
    indexgen.write(fresh(repo))
    assert hook(monkeypatch, repo, "pre-tool", session_id="s", tool_use_id="t1") == 0
    # what `sed -i`, `cat >` or `rm` would do
    keep.write_text(keep.read_text() + "\nSee [[Wiki]].\n", encoding="utf-8")
    write(repo, "systems/new.md", "New")
    gone.unlink()
    (repo / "kb" / ".obsidian").mkdir()
    (repo / "kb" / ".obsidian" / "notes.md").write_text("not a page")
    assert hook(monkeypatch, repo, "post-tool", session_id="s", tool_use_id="t1") == 2
    err = capsys.readouterr().err
    assert "systems/keep.md" in err and "H032" in err and "new.md" not in err
    touched = (repo / session.STATE / "s" / "touched").read_text().split()
    assert sorted(touched) == ["systems/gone.md", "systems/keep.md", "systems/new.md"]
    assert hook(monkeypatch, repo, "stop", session_id="s") == 2  # errors, stale index, no log entry


def test_shell_command_without_changes_is_quiet(repo: Path, monkeypatch, capsys) -> None:
    write(repo, "systems/a.md", "A")
    assert hook(monkeypatch, repo, "pre-tool", session_id="s", tool_use_id="t") == 0
    assert hook(monkeypatch, repo, "post-tool", session_id="s", tool_use_id="t") == 0
    assert hook(monkeypatch, repo, "post-tool", session_id="s", tool_use_id="never-started") == 0
    assert capsys.readouterr().err == ""
    assert hook(monkeypatch, repo, "stop", session_id="s") == 0


def test_parallel_shell_commands_keep_their_own_snapshots(repo: Path, monkeypatch) -> None:
    hook(monkeypatch, repo, "pre-tool", session_id="s", tool_use_id="a")
    write(repo, "systems/a.md", "A")
    hook(monkeypatch, repo, "pre-tool", session_id="s", tool_use_id="b")
    write(repo, "systems/b.md", "B")
    hook(monkeypatch, repo, "post-tool", session_id="s", tool_use_id="b")
    hook(monkeypatch, repo, "post-tool", session_id="s", tool_use_id="a")
    assert set((repo / session.STATE / "s" / "touched").read_text().split()) == {"systems/a.md", "systems/b.md"}


def test_unchanged_content_does_not_count(repo: Path, monkeypatch) -> None:
    same = write(repo, "systems/same.md", "Same")
    back = write(repo, "systems/back.md", "Back")
    hook(monkeypatch, repo, "pre-tool", session_id="s", tool_use_id="t")
    text = same.read_text()
    same.write_text(text)  # rewritten with the same text (a new mtime)
    os.utime(same, ns=(1, 1))
    original = back.read_text()
    back.write_text("changed")
    back.write_text(original)  # changed and changed back, like `git stash; …; git stash pop`
    hook(monkeypatch, repo, "post-tool", session_id="s", tool_use_id="t")
    assert not (repo / session.STATE / "s" / "touched").exists()


@pytest.mark.parametrize("cache", ["[1, 2]", "not json", None])
def test_hash_cache_is_optional(repo: Path, monkeypatch, cache: str | None) -> None:
    hashes = repo / session.STATE / session.HASHES
    hashes.parent.mkdir(parents=True)
    if cache is not None:
        hashes.write_text(cache)
    real_replace = os.replace

    def locked(src, dst):  # Windows: the cache is open in another hook
        if str(dst).endswith(session.HASHES):
            raise PermissionError("in use")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", locked)
    hook(monkeypatch, repo, "pre-tool", session_id="s", tool_use_id="t")
    write(repo, "systems/a.md", "A")
    hook(monkeypatch, repo, "post-tool", session_id="s", tool_use_id="t")
    assert (repo / session.STATE / "s" / "touched").read_text().split() == ["systems/a.md"]
    assert not list(hashes.parent.glob("*.tmp"))


def test_clear_removes_stale_temporary_files(repo: Path) -> None:
    state = repo / session.STATE
    state.mkdir(parents=True)
    old, new = state / f"{session.HASHES}.1.tmp", state / f"{session.HASHES}.2.tmp"
    old.write_text("{}"), new.write_text("{}")
    os.utime(old, (1, 1))
    session.Session(repo / "kb", repo, "s").clear()
    assert not old.exists() and new.exists()


def test_overlapping_commands_without_ids_share_the_first_snapshot(repo: Path, monkeypatch) -> None:
    hook(monkeypatch, repo, "pre-tool", "gemini", session_id="g")
    write(repo, "systems/a.md", "A")  # the first command changes a page while a second one starts
    hook(monkeypatch, repo, "pre-tool", "gemini", session_id="g")
    write(repo, "systems/b.md", "B")
    hook(monkeypatch, repo, "post-tool", "gemini", session_id="g")
    hook(monkeypatch, repo, "post-tool", "gemini", session_id="g")
    assert set((repo / session.STATE / "g" / "touched").read_text().split()) == {"systems/a.md", "systems/b.md"}


@pytest.mark.parametrize("argv", [["pre-tool", "--agent", "nobody"], ["pre-tool", "--bogus"], ["pre-tool"]])
def test_pre_tool_never_blocks(tmp_path: Path, monkeypatch, capsys, argv: list[str]) -> None:
    monkeypatch.delenv("KB_REPO_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)  # not inside a knowledge base
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert hooks.main(argv) == 0
    with pytest.raises(SystemExit):
        hooks.main(["stop", "--bogus"])  # other events report usage errors as usual


def test_pre_tool_survives_unwritable_state(repo: Path, monkeypatch) -> None:
    (repo / ".cache").write_text("a file where the cache folder should be")
    assert hook(monkeypatch, repo, "pre-tool", session_id="s") == 0


def test_missing_bundle_folder_answers_gemini_with_json(repo: Path, capsys) -> None:
    shutil.rmtree(repo / "kb")
    assert hooks.run("post-tool", "gemini", hooks._Paths(repo / "kb", repo)) == 0
    assert capsys.readouterr().out.strip() == "{}"


@pytest.mark.parametrize("agent", ["codex", "gemini"])
def test_other_agents_get_problems_as_context(repo: Path, monkeypatch, capsys, agent: str) -> None:
    event = "AfterTool" if agent == "gemini" else "PostToolUse"
    hook(monkeypatch, repo, "pre-tool", agent, session_id="s")
    capsys.readouterr()
    write(repo, "systems/a.md", "A", "See [[Wiki]].")
    assert hook(monkeypatch, repo, "post-tool", agent, session_id="s", hook_event_name=event) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == event
    assert "systems/a.md" in out["hookSpecificOutput"]["additionalContext"]
    assert hook(monkeypatch, repo, "stop", agent, session_id="s") == 2  # stop blocks the same way everywhere


def test_gemini_success_prints_json(repo: Path, monkeypatch, capsys) -> None:
    assert hook(monkeypatch, repo, "pre-tool", "gemini", session_id="s") == 0
    assert hook(monkeypatch, repo, "stop", "gemini", session_id="s") == 0
    assert capsys.readouterr().out.split() == ["{}", "{}"]


def test_files_outside_the_bundle_listing_are_not_pages(repo: Path, monkeypatch, capsys) -> None:
    git(repo, "init", "-q")
    (repo / ".gitignore").write_text("kb/private/\n")
    indexgen.write(fresh(repo))
    ignored = repo / "kb" / "private" / "draft.md"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("no frontmatter\n")
    trash = repo / "kb" / ".trash" / "old.md"
    trash.parent.mkdir(parents=True)
    trash.write_text("no frontmatter\n")
    for path in (ignored, trash):  # a file tool writes them: not checked, not recorded
        assert hook(monkeypatch, repo, "post-edit", session_id="s", tool_input={"file_path": str(path)}) == 0
    assert hook(monkeypatch, repo, "pre-tool", session_id="s", tool_use_id="t") == 0
    ignored.write_text("changed, still no frontmatter\n")  # a shell command changes it
    assert hook(monkeypatch, repo, "post-tool", session_id="s", tool_use_id="t") == 0
    assert hook(monkeypatch, repo, "stop", session_id="s") == 0  # nothing to check, nothing to log
    assert capsys.readouterr().err == ""


def test_relative_file_path_and_log_edit_first(repo: Path, monkeypatch) -> None:
    page = write(repo, "systems/a.md", "A")
    indexgen.write(fresh(repo))
    pages.add_log_entry(fresh(repo), "update", "Added [A](/systems/a.md).")
    # the first thing the agent edited was log.md itself (with a file tool)
    hook(monkeypatch, repo, "post-edit", session_id="s", tool_input={"file_path": "kb/log.md"}, cwd=str(repo))
    hook(monkeypatch, repo, "post-edit", session_id="s", tool_input={"file_path": str(page)}, tool_response="text")
    assert hook(monkeypatch, repo, "stop", session_id="s") == 0


def test_module_entry_point_needs_no_bundle_config(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("KB_REPO_ROOT", str(repo))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "m"})))
    assert hooks.main(["pre-tool", "--agent", "gemini"]) == 0
    assert (repo / session.STATE / "m" / "pre-last.json").is_file()


# -- kb new: actors and generated (A3) ---------------------------------------------------------


def test_actor_pattern_matches_the_schema() -> None:
    schema = json.loads((REPO / "schema" / "frontmatter.schema.json").read_text(encoding="utf-8"))
    assert pages.ACTOR.pattern == schema["$defs"]["actor"]["pattern"]


@pytest.mark.parametrize(("given", "expected"), [
    ("claude-code/claude-opus-5-5[1m]", "claude-code/claude-opus-5-5"),
    ("claude-code/opus", "claude-code/opus"),
    ("human:me", "human:me"),
    ("codex/gpt-5.5:high", "codex/gpt-5.5:high"),
])
def test_new_page_writes_valid_generated(repo: Path, given: str, expected: str) -> None:
    path = pages.new_page(fresh(repo), "Concept", "systems/x.md", "X", "X.", [], given)
    fm = load_yaml(path.read_text(encoding="utf-8").split("---")[1])
    assert fm["generated"]["by"] == expected
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", fm["generated"]["at"])
    assert "generated: { by: " in path.read_text(encoding="utf-8")
    indexgen.write(fresh(repo))
    assert [str(d) for d in Checker(fresh(repo)).check_all() if d.is_error] == []


@pytest.mark.parametrize("actor", ["claude code", "x/y, extra: 1", "x/y }", "claude-code/", "human:Me", "x/y\nz: 1", "#x/y"])
def test_invalid_actors_are_rejected(repo: Path, monkeypatch, actor: str) -> None:
    with pytest.raises(SystemExit, match="not an actor"):
        pages.new_page(fresh(repo), "Concept", "systems/x.md", "X", "X.", [], actor)
    monkeypatch.setenv("KB_ACTOR", actor)
    with pytest.raises(SystemExit, match="KB_ACTOR"):
        pages.resolve_actor(None)
    assert not (repo / "kb" / "systems" / "x.md").exists()


def test_generated_in_extra_frontmatter_is_replaced(repo: Path) -> None:
    path = pages.new_page(fresh(repo), "Concept", "systems/x.md", "X", "X.", [], "test/0",
                          extra={"generated": {"by": "evil", "at": "x"}})
    assert load_yaml(path.read_text(encoding="utf-8").split("---")[1])["generated"]["by"] == "test/0"


# -- kb log (B9) --------------------------------------------------------------------------


@pytest.mark.parametrize("message", ["first\n## 2020-01-01\n* **Update**: forged", "a\r\nb", "a\u2028## 2020-01-01"])
def test_log_messages_stay_on_one_line(repo: Path, message: str) -> None:
    pages.add_log_entry(fresh(repo), "update", message)
    text = (repo / "kb" / "log.md").read_text(encoding="utf-8")
    assert text.count("\n## ") == 1 and len([l for l in text.splitlines() if l.startswith("* ")]) == 1
    assert not [d for d in Checker(fresh(repo)).check_all() if d.code == "O005"]


@pytest.mark.parametrize(("op", "message"), [("Update\n## 2020-01-01", "x"), ("", "x"), ("update", " \n ")])
def test_log_rejects_bad_ops_and_empty_messages(repo: Path, op: str, message: str) -> None:
    with pytest.raises(SystemExit):
        pages.add_log_entry(fresh(repo), op, message)
    assert not (repo / "kb" / "log.md").exists()


# -- .claude/skills on Windows checkouts ------------------------------------------------------


def _placeholder(repo: Path) -> Path:
    skills = repo / ".agents" / "skills" / "kb-ingest"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: kb-ingest\n---\n")
    link = repo / ".claude" / "skills"
    link.parent.mkdir()
    link.write_text("../.agents/skills")  # what git writes with core.symlinks=false
    return link


def test_skills_placeholder_becomes_a_link(repo: Path) -> None:
    link = _placeholder(repo)
    git(repo, "init", "-q")
    git(repo, "config", "core.symlinks", "false")  # as Git for Windows without symlink support
    blob = subprocess.run(["git", "hash-object", "-w", str(link)], cwd=repo, capture_output=True, text=True).stdout.strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},.claude/skills")  # tracked as a symlink
    git(repo, "commit", "-qm", "checkout")

    def status() -> str:
        return subprocess.run(["git", "status", "--porcelain", "--", ".claude"], cwd=repo,
                              capture_output=True, text=True).stdout

    assert status() == ""
    assert "symlink" in (hooks.repair_skills_link(repo) or "")
    assert (link / "kb-ingest" / "SKILL.md").is_file()
    assert status() == ""
    assert hooks.repair_skills_link(repo) is None  # nothing left to do


def test_skills_placeholder_falls_back_to_a_copy(repo: Path, monkeypatch) -> None:
    link = _placeholder(repo)

    def no_symlinks(*args, **kwargs):
        raise OSError("symbolic links are not available")

    monkeypatch.setattr(os, "symlink", no_symlinks)
    monkeypatch.setattr(os, "name", "posix")
    assert "copy" in (hooks.repair_skills_link(repo) or "")
    assert (link / "kb-ingest" / "SKILL.md").is_file() and not link.is_symlink()
    (repo / ".agents" / "skills" / "kb-query").mkdir()
    (repo / ".agents" / "skills" / "kb-query" / "SKILL.md").write_text("x")
    assert "refreshed" in (hooks.repair_skills_link(repo) or "")
    assert (link / "kb-query" / "SKILL.md").is_file()


def test_dangling_skills_link_is_replaced(repo: Path, tmp_path: Path) -> None:
    link = _placeholder(repo)
    link.unlink()
    link.symlink_to(tmp_path / "moved-away" / "skills", target_is_directory=True)  # like a junction after a move
    assert "broken" in (hooks.repair_skills_link(repo) or "")
    assert link.is_symlink() and (link / "kb-ingest" / "SKILL.md").is_file()


@pytest.mark.parametrize("content", [None, "something else", "dir"])
def test_skills_repair_leaves_other_files_alone(repo: Path, content: str | None) -> None:
    link = _placeholder(repo)
    if content is None:
        link.unlink()
    elif content == "dir":
        link.unlink()
        link.mkdir()
    else:
        link.write_text(content)
    assert hooks.repair_skills_link(repo) is None
