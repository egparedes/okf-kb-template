"""Claude Code hooks. Exit code 2 feeds stderr back to the agent."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .bundle import TOUCHED, Bundle, record_touched
from .check import Checker


def _payload() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def _touched(bundle: Bundle) -> Path:
    return bundle.repo_root / TOUCHED


def post_edit(bundle: Bundle) -> int:
    """After Write/Edit: remember the file and validate it if it is part of the bundle."""
    payload = _payload()
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or (payload.get("tool_response") or {}).get("filePath")
    if not file_path:
        return 0
    path = Path(file_path).resolve()
    if path.suffix != ".md" or not path.is_file() or bundle.root not in path.parents:
        return 0
    if not os.environ.get("CLAUDECODE"):
        os.environ["CLAUDECODE"] = "1"  # the hook itself runs inside Claude Code
    record_touched(bundle.repo_root, [path])
    errors = [d for d in Checker(bundle).check_files([bundle.document(path)]) if d.is_error]
    if not errors:
        return 0
    print("kb check found problems in the file you just edited:", file=sys.stderr)
    for diagnostic in errors:
        print(f"  {diagnostic}", file=sys.stderr)
    return 2


def _changed_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all", "--", "kb"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    entries = result.stdout.split("\0")
    files, skip = [], False
    for entry in entries:
        if skip:  # the second path of a rename record
            skip = False
            continue
        if len(entry) > 3:
            files.append(entry[3:])
            skip = entry[0] in "RC"
    return files


def stop(bundle: Bundle) -> int:
    """Before the agent finishes: the pages it edited must validate, and knowledge edits must be logged.

    Only files this session wrote through Write/Edit are checked, so notes the
    human is editing in Obsidian never block an unrelated agent session.
    """
    payload = _payload()
    if payload.get("stop_hook_active"):
        return 0
    touched_file = _touched(bundle)
    if not touched_file.is_file():
        return 0
    touched = sorted({Path(p) for p in touched_file.read_text(encoding="utf-8").splitlines() if p.strip()})
    touched = [p for p in touched if p.is_file()]
    problems: list[str] = []
    checker = Checker(bundle)
    errors = [d for d in checker.check_files([bundle.document(p) for p in touched]) if d.is_error]
    checker.diagnostics = []
    checker.check_indexes()
    folders = {p.parent for p in touched}  # their indexes and every ancestor index up to the root
    errors += [
        d for d in checker.diagnostics
        if any((bundle.root / d.path).parent in (f, *f.parents) for f in folders)
    ]
    problems += [str(d) for d in errors[:30]]
    if len(errors) > 30:
        problems.append(f"... and {len(errors) - 30} more (run `just check`)")
    personal = tuple(bundle.root / folder for folder in bundle.config.personal_folders)
    knowledge_edits = [
        p for p in touched
        if p.name not in ("index.md", "log.md") and not any(folder in p.parents for folder in personal)
    ]
    if knowledge_edits and "kb/log.md" not in _changed_files(bundle.repo_root):
        problems.append(
            "knowledge pages changed but kb/log.md has no entry: run `uv run kb log <Op> \"<message with /links>\"`"
        )
    if not problems:
        touched_file.unlink()
        return 0
    print("Before finishing, fix the knowledge base:", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    return 2
