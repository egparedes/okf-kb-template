"""The GitHub Actions pins agree between the template's own workflows and the knowledge base's kb.yml."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB_WORKFLOW = ROOT / "template" / "{% if github_ci %}.github{% endif %}" / "workflows" / "kb.yml"
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+?)@(\S+)(?:\s+#\s*(\S+))?\s*$", re.MULTILINE)


def _pins(path: Path) -> list[tuple[str, str, str | None]]:
    return USES.findall(path.read_text(encoding="utf-8"))


def test_actions_are_pinned_and_agree() -> None:
    """Dependabot updates only .github/workflows/: kb.yml must use the same pins, and only
    actions that a repository workflow uses, so each Dependabot update shows up here."""
    repo_workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    seen: dict[str, set[tuple[str, str | None]]] = {}
    for path in [*repo_workflows, KB_WORKFLOW]:
        pins = _pins(path)
        assert pins, path
        for action, ref, version in pins:
            assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{path.name}: {action}@{ref} is not pinned by commit SHA"
            assert version and re.fullmatch(r"v\d+(\.\d+)*", version), f"{path.name}: {action} lacks a `# vX.Y.Z` comment"
            seen.setdefault(action, set()).add((ref, version))
    disagree = {action: pins for action, pins in seen.items() if len(pins) > 1}
    assert not disagree, f"update kb.yml and every workflow to the same pin: {disagree}"
    tracked = {action for path in repo_workflows for action, _, _ in _pins(path)}
    untracked = {action for action, _, _ in _pins(KB_WORKFLOW)} - tracked
    assert not untracked, f"use these in a workflow under .github/workflows/ so Dependabot updates them: {untracked}"
