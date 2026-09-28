"""Agent hooks (Claude Code, Codex, Gemini CLI) and the agent-configuration repair of `kb setup`.

Events, all reading the hook payload (JSON) on stdin:

- `pre-tool`: before a shell command (or a Codex patch): record the bundle's
  state, so `post-tool` can find the pages the command changed;
- `post-tool`: after it: record and check the changed pages;
- `post-edit`: after a file tool wrote `tool_input.file_path`: record and check it;
- `stop`: before the agent finishes: the session's pages must validate, and
  knowledge edits must be logged.

Problems are reported on stderr with exit code 2, which Claude Code (and, for
`stop`, Codex and Gemini CLI) feeds back to the agent. With `--agent codex`
or `--agent gemini`, `post-*` problems are returned as `additionalContext`
JSON on stdout instead, because those CLIs replace the tool's output with the
stderr of a hook that exits 2.

`python -m kbtools.hooks <event>` is the same as `kb hook <event>`, without
importing the rest of the command line (the shell hooks run on every command).
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .bundle import bundle_dir, find_repo_root
from .fsutil import program, remove_tree
from .session import Session

if TYPE_CHECKING:
    from .bundle import Bundle

EVENTS = ("pre-tool", "post-tool", "post-edit", "stop")
AGENTS = ("claude", "codex", "gemini")
MAX_SHOWN = 30


class _Paths:
    """The two paths the shell hooks need, without loading the bundle's configuration."""

    def __init__(self, root: Path, repo_root: Path):
        self.root, self.repo_root = root.resolve(), repo_root.resolve()


def _payload() -> dict:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _session(bundle: Bundle | _Paths, payload: dict) -> Session:
    return Session(bundle.root, bundle.repo_root, payload.get("session_id"))


def _report(problems: list[str], payload: dict, agent: str, header: str, blocking: bool = False) -> int:
    """Hand `problems` back to the agent in the form its CLI expects (`blocking`: the stop event)."""
    if not problems:
        if agent == "gemini":
            print("{}")  # Gemini CLI parses a hook's stdout as JSON
        return 0
    text = "\n".join([header, *(f"  {p}" for p in problems)])
    if agent == "claude" or blocking:
        print(text, file=sys.stderr)
        return 2
    event = payload.get("hook_event_name") or ("AfterTool" if agent == "gemini" else "PostToolUse")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))
    return 0


def _full(bundle: Bundle | _Paths) -> Bundle:
    """The bundle with its configuration and file listing (the shell hooks start with bare paths)."""
    from .bundle import Bundle

    return bundle if isinstance(bundle, Bundle) else Bundle(bundle.root, bundle.repo_root)


def _part_of_bundle(bundle: Bundle | _Paths, rels: list[str]) -> tuple[Bundle | _Paths, list[str]]:
    """(full bundle, `rels` without files the bundle leaves out): dot-folders, gitignored files.

    Deleted pages stay: they still count as changes. The dot-folder test is
    free; only when paths remain is the file listing (one `git ls-files`) read.
    """
    rels = [r for r in rels if not any(part.startswith(".") for part in r.split("/")[:-1])]
    if not rels:
        return bundle, rels
    full = _full(bundle)
    return full, [r for r in rels if r in full.files or not (full.root / r).exists()]


def _check(bundle: Bundle | _Paths, rels: list[str]) -> list[str]:
    """Errors in the given bundle pages (only the files: no bundle-wide checks)."""
    from .check import Checker

    bundle, rels = _part_of_bundle(bundle, rels)
    paths = [bundle.root / r for r in rels if r.endswith(".md") and (bundle.root / r).is_file()]
    if not paths:
        return []
    full = _full(bundle)  # already loaded when pages remain
    errors = [d for d in Checker(full).check_files([full.document(p) for p in paths]) if d.is_error]
    shown = [str(d) for d in errors[:MAX_SHOWN]]
    if len(errors) > MAX_SHOWN:
        shown.append(f"... and {len(errors) - MAX_SHOWN} more (run `uv run poe check`)")
    return shown


def pre_tool(bundle: Bundle | _Paths, agent: str = "claude") -> int:
    """Before a shell command: remember log.md (first event of the session) and the bundle's files."""
    payload = _payload()
    try:
        session = _session(bundle, payload)
        session.start()
        session.snapshot(payload.get("tool_use_id"))
    except Exception as exc:  # exit 2 here would block every shell command, so never fail
        print(f"kb hook pre-tool: {exc}", file=sys.stderr)
    return _report([], payload, agent, "")


def post_tool(bundle: Bundle | _Paths, agent: str = "claude") -> int:
    """After a shell command: record the pages it created, changed or deleted, and check them."""
    payload = _payload()
    session = _session(bundle, payload)
    session.claim_commands()  # pages `kb` commands recorded belong to the session that ran them
    changed = session.changes(payload.get("tool_use_id"))
    problems = _check(bundle, changed) if changed else []
    return _report(problems, payload, agent, "kb check found problems in pages this command changed:")


def post_edit(bundle: Bundle | _Paths, agent: str = "claude") -> int:
    """After Write/Edit (or write_file/replace): remember the file and validate it if it is in the bundle."""
    payload = _payload()
    tool_input, tool_response = payload.get("tool_input"), payload.get("tool_response")
    file_path = (tool_input.get("file_path") if isinstance(tool_input, dict) else None) or (
        tool_response.get("filePath") if isinstance(tool_response, dict) else None
    )
    if not file_path or not isinstance(file_path, str):
        return _report([], payload, agent, "")
    path = Path(file_path)
    if not path.is_absolute():
        path = Path(payload.get("cwd") or os.getcwd()) / path
    path = path.resolve()
    root = bundle.root.resolve()
    if path.suffix != ".md" or not path.is_file() or root not in path.parents:
        return _report([], payload, agent, "")
    bundle, rels = _part_of_bundle(bundle, [path.relative_to(root).as_posix()])
    if not rels:  # in a dot-folder or gitignored: not a page of the bundle
        return _report([], payload, agent, "")
    session = _session(bundle, payload)
    session.start(log_already_changed=rels[0] == "log.md")  # an edit of log.md before any baseline counts
    session.record([path])
    problems = _check(bundle, rels)
    return _report(problems, payload, agent, "kb check found problems in the file you just edited:")


def stop(bundle: Bundle | _Paths, agent: str = "claude") -> int:
    """Before the agent finishes: the pages it changed must validate, and knowledge edits must be logged.

    Only pages this session changed are checked (through file tools, shell
    commands or `kb` commands), so notes the human is editing in Obsidian
    never block an unrelated agent session.
    """
    from .check import Checker

    payload = _payload()
    session = _session(bundle, payload)
    if payload.get("stop_hook_active"):  # already sent back once: let it stop; the state stays with this session
        return _report([], payload, agent, "")
    bundle, touched = _part_of_bundle(bundle, session.touched())
    if not touched:
        session.clear()
        return _report([], payload, agent, "")
    bundle = _full(bundle)
    root = bundle.root
    problems = _check(bundle, touched)
    checker = Checker(bundle)
    checker.check_indexes()
    folders = {(root / r).parent for r in touched}  # their indexes and every ancestor index up to the root
    index_errors = [
        d for d in checker.diagnostics if d.is_error and any((root / d.path).parent in (f, *f.parents) for f in folders)
    ]
    problems += [str(d) for d in index_errors[:MAX_SHOWN]]
    personal = tuple(root / folder for folder in bundle.config.personal_folders)
    knowledge_edits = [
        r
        for r in touched
        if Path(r).name not in ("index.md", "log.md") and not any(f in (root / r).parents for f in personal)
    ]
    if knowledge_edits and session.log_changed() is False:
        problems.append(
            f"knowledge pages changed but {bundle.show('log.md')} has no new entry: "
            'run `uv run kb log <Op> "<message with /links>"`'
        )
    if not problems:
        session.clear()
    return _report(problems, payload, agent, "Before finishing, fix the knowledge base:", blocking=True)


# -- agent configuration (kb setup) -------------------------------------------------

SKILLS_LINK = Path(".claude") / "skills"
SKILLS_TARGET = "../.agents/skills"
_COPY_MARKER = ".kb-copy-of-agents-skills"


def repair_skills_link(repo_root: Path) -> str | None:
    """Make `.claude/skills` show `.agents/skills` where git checked the symlink out as a text file.

    Git for Windows without symlink support (`core.symlinks=false`) writes a
    symlink as a small file holding its target, which Claude Code cannot use.
    This replaces it with, in order of preference, a symlink, a directory
    junction (Windows; needs no privileges) or a copy (refreshed on each run),
    and tells git to ignore the difference. Returns what was done, or None.
    """
    link, target = repo_root / SKILLS_LINK, repo_root / ".agents" / "skills"
    if not target.is_dir():
        return None
    if os.path.lexists(link) and not link.exists():  # a dangling symlink or junction, e.g. after a move
        try:
            link.unlink()
        except OSError:
            os.rmdir(link)  # a junction on Windows
        how = _link_skills(link, target)
        if how != "a symlink":
            _hide_from_git(repo_root)
        return f"replaced the broken {SKILLS_LINK.as_posix()} link with {how} to .agents/skills"
    if link.is_symlink() or _is_junction(link):
        return None
    if link.is_dir():
        if not (link / _COPY_MARKER).is_file():
            return None  # a real folder someone made: leave it alone
        remove_tree(link)
        _copy_skills(target, link)
        return f"refreshed the copy of .agents/skills in {SKILLS_LINK.as_posix()}"
    if not link.is_file() or link.stat().st_size > 256:
        return None
    if link.read_text(encoding="utf-8", errors="replace").strip().replace("\\", "/") != SKILLS_TARGET:
        return None
    link.unlink()
    how = _link_skills(link, target)
    _hide_from_git(repo_root)
    return f"replaced the {SKILLS_LINK.as_posix()} placeholder file with {how} to .agents/skills"


def _is_junction(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", None)  # Python 3.12+
    return bool(is_junction and is_junction(path))


def _link_skills(link: Path, target: Path) -> str:
    try:
        os.symlink(SKILLS_TARGET.replace("/", os.sep), link, target_is_directory=True)
        return "a symlink"
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False)
        if done.returncode == 0:
            return "a directory junction"
    _copy_skills(target, link)
    return "a copy (run `uv run poe setup` again after the skills change)"


def _copy_skills(target: Path, link: Path) -> None:
    shutil.copytree(target, link)
    (link / _COPY_MARKER).write_text(
        "Copied by `kb setup` from .agents/skills; edit the originals.\n", encoding="utf-8", newline="\n"
    )


def _hide_from_git(repo_root: Path) -> None:
    """Keep the replaced `.claude/skills` out of `git status` (it is tracked as a symlink)."""

    def git(*args: str) -> subprocess.CompletedProcess:
        try:
            command = [program("git"), *args]
        except FileNotFoundError as exc:  # no git: nothing to hide from
            return subprocess.CompletedProcess(args, 127, "", str(exc))
        return subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    if git("ls-files", "--error-unmatch", "--", SKILLS_LINK.as_posix()).returncode != 0:
        return
    git("update-index", "--skip-worktree", "--", SKILLS_LINK.as_posix())
    exclude = git("rev-parse", "--git-path", "info/exclude").stdout.strip()
    if exclude:
        path = Path(exclude) if Path(exclude).is_absolute() else repo_root / exclude
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if "/.claude/skills/" not in text.splitlines():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                text + ("" if not text or text.endswith("\n") else "\n") + "/.claude/skills/\n",
                encoding="utf-8",
                newline="\n",
            )


# -- entry point -----------------------------------------------------------------------

HANDLERS = {"pre-tool": pre_tool, "post-tool": post_tool, "post-edit": post_edit, "stop": stop}


def run(event: str, agent: str = "claude", bundle: Bundle | _Paths | None = None) -> int:
    if bundle is None:
        repo_root = find_repo_root()
        bundle = _Paths(repo_root / bundle_dir(repo_root), repo_root)
    if not Path(bundle.root).is_dir():
        return _report([], {}, agent, "")
    return HANDLERS[event](bundle, agent)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="python -m kbtools.hooks", description="agent hook entry points")
    parser.add_argument("event", choices=EVENTS)
    parser.add_argument("--agent", choices=AGENTS, default="claude", help="the CLI that runs the hook")
    # A pre-tool hook that exits 2 blocks the shell command, and every later one; Codex and
    # Gemini CLI get the problems of the other tool hooks as JSON with exit 0. Whatever goes
    # wrong in those (arguments, a missing repository), they exit 0, so their commands need
    # no shell-specific `|| true` for errors raised here (Codex's commandWindows has none).
    agents = {a.split("=", 1)[1] for a in argv if a.startswith("--agent=")}
    agents |= {value for flag, value in itertools.pairwise(argv) if flag == "--agent"}
    never_fail = "pre-tool" in argv or ("stop" not in argv and bool(agents & {"codex", "gemini"}))
    if not never_fail:
        args = parser.parse_args(argv)
        return run(args.event, args.agent)
    try:
        args = parser.parse_args(argv)
        return run(args.event, args.agent)
    except BaseException as exc:  # noqa: BLE001 - includes argparse's SystemExit
        if isinstance(exc, KeyboardInterrupt):
            raise
        print(f"kb hook {' '.join(argv[:1])}: {exc}", file=sys.stderr)
        if "gemini" in agents:
            print("{}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
