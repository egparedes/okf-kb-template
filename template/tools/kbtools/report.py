"""Health report for the lint workflow: coverage, trust, freshness, graph gaps."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from .bundle import Bundle, Document
from .mdlinks import find_links, resolve


def trust_tier(doc: Document) -> str:
    """OKF §5.3: unverified / machine-confirmed / human-reviewed."""
    verified = doc.frontmatter.get("verified")
    if not verified:
        return "unverified"
    events = verified if isinstance(verified, list) else [verified]
    by = [e.get("by", "") for e in events if isinstance(e, dict)]
    return "human-reviewed" if any(str(b).startswith("human:") for b in by) else "machine-confirmed"


def _is_stale(doc: Document, now: datetime) -> bool:
    value = doc.frontmatter.get("stale_after")
    try:
        return isinstance(value, str) and now >= datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):  # malformed or without UTC offset: reported by kb check
        return False


def build(bundle: Bundle) -> str:
    now = datetime.now(timezone.utc)
    concepts = [d for d in bundle.concepts() if not d.frontmatter_error and d.type]
    knowledge = [d for d in concepts if d.rel.parts[0] not in bundle.config.personal_folders]

    inbound: Counter[str] = Counter()
    broken: list[tuple[str, str]] = []
    for doc in bundle.documents:
        if doc.rel.name == "index.md":
            continue
        for link in find_links(doc.body):
            if link.is_external or link.is_anchor_only or not link.path:
                continue
            target = resolve(link.path, doc.folder)
            if target is None:
                continue
            if bundle.exists(target):
                if target != str(doc.rel) and doc.rel.name != "log.md":
                    inbound[target] += 1
            else:
                broken.append((str(doc.rel), link.target))

    lines = ["# Knowledge base report", "", f"Generated {now:%Y-%m-%d %H:%M} UTC.", ""]
    lines += ["## Pages by type", ""]
    for type_name, count in Counter(d.type for d in concepts).most_common():
        lines.append(f"* {type_name}: {count}")
    lines += ["", "## Trust tiers (knowledge pages)", ""]
    for tier, count in Counter(trust_tier(d) for d in knowledge).most_common():
        lines.append(f"* {tier}: {count}")
    lines += ["", "## Status", ""]
    for status, count in Counter(d.frontmatter.get("status", "stable") for d in concepts).most_common():
        lines.append(f"* {status}: {count}")

    def section(title: str, items: list[str]) -> None:
        lines.extend(["", f"## {title} ({len(items)})", ""])
        lines.extend(f"* {item}" for item in items[:200])

    section("Stale pages", [str(d.rel) for d in concepts if _is_stale(d, now)])
    section(
        "Uncited knowledge pages (no `sources`)",
        [str(d.rel) for d in knowledge if d.type not in ("Source", "Person", "Organization") and not d.frontmatter.get("sources")],
    )
    section(
        "Unused sources (Source pages nothing cites)",
        [str(d.rel) for d in knowledge if d.type == "Source" and inbound[str(d.rel)] == 0],
    )
    section("Broken links (wanted pages)", [f"{src} -> {target}" for src, target in sorted(broken)])
    section("Drafts", [str(d.rel) for d in concepts if d.frontmatter.get("status") == "draft"])
    return "\n".join(lines) + "\n"
