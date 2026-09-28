"""Creating pages and log entries."""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from .bundle import Bundle, load_yaml, record_touched

LOG_HEADER = "# Update Log\n"
LOG_OPS = ("Ingest", "Query", "Lint", "Update", "Creation", "Deprecation", "Refactor", "Initialization")
_DATE_HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$", re.M)
# The `actor` pattern of schema/frontmatter.schema.json (a test keeps them equal).
ACTOR = re.compile(r"^(human:[a-z0-9._-]+|process:[a-z0-9._-]+|[A-Za-z0-9._-]+/[A-Za-z0-9._:-]+)$")
CONTEXT_SUFFIX = re.compile(r"(?<=[^/\s])\[[0-9A-Za-z]+\]$")  # claude-opus-5-5[1m] -> claude-opus-5-5
_LOG_OP = re.compile(r"[A-Za-z][A-Za-z-]*")


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_actor(actor: str, source: str = "--by") -> str:
    """`actor` if it matches the OKF actor pattern of the frontmatter schema.

    A bracketed suffix on the model, as in Claude Code's `claude-opus-5-5[1m]`
    (the context window), is not part of the model's name: it is dropped.
    """
    actor = actor.strip()
    if "/" in actor:
        actor = CONTEXT_SUFFIX.sub("", actor)
    if not ACTOR.fullmatch(actor):
        raise SystemExit(
            f"kb: {source}: {actor!r} is not an actor; use <tool>/<model> "
            "(e.g. claude-code/claude-opus-5-5), human:<id> or process:<id>"
        )
    return actor


def resolve_actor(by: str | None) -> str:
    actor = by or os.environ.get("KB_ACTOR")
    if not actor:
        raise SystemExit(
            "kb: pass --by or set KB_ACTOR (e.g. claude-code/<model> or human:<id>)"
        )
    return validate_actor(actor, "--by" if by else "KB_ACTOR")


def generated_line(generated: dict[str, str]) -> str:
    """`generated: { by: …, at: … }` in the house flow style, or YAML's own quoting when that is not safe."""
    line = f"generated: {{ by: {generated['by']}, at: {generated['at']} }}\n"
    if load_yaml(line) == {"generated": generated}:
        return line
    return yaml.safe_dump({"generated": generated}, sort_keys=False, allow_unicode=True, width=1000)


def new_page(
    bundle: Bundle,
    type_name: str,
    rel_path: str,
    title: str,
    description: str,
    tags: list[str],
    by: str | None,
    status: str = "draft",
    resource: str | None = None,
    extra: dict | None = None,
    body_intro: str = "",
) -> Path:
    spec = bundle.config.types.get(type_name)
    if spec is None:
        raise SystemExit(f"kb: unknown type `{type_name}`; see schema/vocabulary.yaml")
    rel_path = bundle.rel(rel_path)
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
    for key, value in (extra or {}).items():
        frontmatter.setdefault(key, value)
    frontmatter["tags"] = tags
    frontmatter["status"] = status
    frontmatter.pop("generated", None)
    generated = {"by": resolve_actor(by), "at": now_utc()}
    fm = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True, width=1000)
    fm += generated_line(generated)
    sections = "\n".join(f"# {s}\n" for s in spec.get("sections", []))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm}---\n\n{body_intro}{sections}", encoding="utf-8")
    record_touched(bundle.repo_root, [path])
    return path


def add_log_entry(bundle: Bundle, op: str, message: str, day: date | None = None) -> Path:
    """Add `* **Op**: message` under today's `## YYYY-MM-DD` heading (newest first, OKF §9)."""
    if not _LOG_OP.fullmatch(op):
        raise SystemExit(f"kb log: the operation must be one word, e.g. {', '.join(LOG_OPS)}")
    op = op.capitalize()
    # One entry is one line: line breaks would let a message start a heading or a new entry.
    message = " ".join(part.strip() for part in message.splitlines() if part.strip())
    if not message:
        raise SystemExit("kb log: the message is empty")
    day_str = (day or datetime.now(timezone.utc).date()).isoformat()
    path = bundle.root / "log.md"
    text = path.read_text(encoding="utf-8") if path.exists() else LOG_HEADER
    entry = f"* **{op}**: {message}\n"
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
