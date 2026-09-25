"""Creating pages and log entries."""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from .bundle import Bundle

LOG_HEADER = "# Update Log\n"
LOG_OPS = ("Ingest", "Query", "Lint", "Update", "Creation", "Deprecation", "Refactor", "Initialization")
_DATE_HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$", re.M)


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_actor(by: str | None) -> str:
    actor = by or os.environ.get("KB_ACTOR")
    if not actor:
        raise SystemExit(
            "kb: pass --by or set KB_ACTOR (e.g. claude-code/<model> or human:<id>)"
        )
    return actor


def new_page(
    bundle: Bundle,
    type_name: str,
    rel_path: str,
    title: str,
    description: str,
    tags: list[str],
    by: str | None,
    status: str = "stable",
    resource: str | None = None,
) -> Path:
    spec = bundle.config.types.get(type_name)
    if spec is None:
        raise SystemExit(f"kb: unknown type `{type_name}`; see schema/vocabulary.yaml")
    rel_path = rel_path.lstrip("/")
    rel_path = rel_path[3:] if rel_path.startswith("kb/") else rel_path
    if not rel_path.endswith(".md"):
        rel_path += ".md"
    path = bundle.root / rel_path
    if bundle.root.resolve() not in path.resolve().parents:
        raise SystemExit(f"kb: {rel_path} is outside the bundle")
    if path.exists():
        raise SystemExit(f"kb: {path} already exists")
    frontmatter: dict = {"type": type_name, "title": title, "description": description}
    if resource:
        frontmatter["resource"] = resource
    frontmatter["tags"] = tags
    frontmatter["status"] = status
    fm = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True, width=1000)
    fm += f"generated: {{ by: {resolve_actor(by)}, at: {now_utc()} }}\n"
    sections = "\n".join(f"# {s}\n" for s in spec.get("sections", []))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm}---\n\n{sections}", encoding="utf-8")
    return path


def add_log_entry(bundle: Bundle, op: str, message: str, day: date | None = None) -> Path:
    """Add `* **Op**: message` under today's `## YYYY-MM-DD` heading (newest first, OKF §9)."""
    op = op.capitalize()
    day_str = (day or datetime.now(timezone.utc).date()).isoformat()
    path = bundle.root / "log.md"
    text = path.read_text(encoding="utf-8") if path.exists() else LOG_HEADER
    entry = f"* **{op}**: {message.strip()}\n"
    first = _DATE_HEADING.search(text)
    if first and first.group(1) >= day_str:  # never create a section below a newer one
        insert_at = first.end() + 1
        if text[insert_at : insert_at + 1] == "\n":
            insert_at += 1
        text = text[:insert_at] + entry + text[insert_at:]
    else:
        section = f"## {day_str}\n\n{entry}\n"
        if first:
            text = text[: first.start()] + section + text[first.start() :]
        else:
            text = text.rstrip("\n") + "\n\n" + section
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
    return path
