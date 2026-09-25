"""Claude Code hooks. Exit code 2 feeds stderr back to the agent."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .bundle import Bundle
from .check import Checker


def _payload() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def post_edit(bundle: Bundle) -> int:
    """After Write/Edit: validate the touched file if it is part of the bundle."""
    payload = _payload()
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or (payload.get("tool_response") or {}).get("filePath")
    if not file_path:
        return 0
    path = Path(file_path).resolve()
    if path.suffix != ".md" or not path.is_file() or bundle.root not in path.parents:
        return 0
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
    """Before the agent finishes: the bundle must validate and knowledge edits must be logged."""
    payload = _payload()
    if payload.get("stop_hook_active"):
        return 0
    changed = _changed_files(bundle.repo_root)
    if not changed:
        return 0
    problems: list[str] = []
    errors = [d for d in Checker(bundle).check_all() if d.is_error]
    problems += [str(d) for d in errors[:30]]
    if len(errors) > 30:
        problems.append(f"... and {len(errors) - 30} more (run `just check`)")
    personal = tuple(f"kb/{folder}/" for folder in bundle.config.personal_folders)
    knowledge_edits = [
        f for f in changed
        if f.endswith(".md") and f.rsplit("/", 1)[-1] != "index.md" and f != "kb/log.md" and not f.startswith(personal)
    ]
    if knowledge_edits and "kb/log.md" not in changed:
        problems.append(
            "knowledge pages changed but kb/log.md has no entry: run `uv run kb log <Op> \"<message with /links>\"`"
        )
    if not problems:
        return 0
    print("Before finishing, fix the knowledge base:", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    return 2
