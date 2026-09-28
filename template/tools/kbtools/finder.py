"""Frontmatter filter (retrieval tier 2), shared by `kb find` and `kb eval`."""

from __future__ import annotations

from . import report
from .bundle import Bundle, Document


def find_pages(bundle: Bundle, type_: str | None = None, tags: list[str] | None = None, status: str | None = None,
               folder: str | None = None, trust: str | None = None) -> list[Document]:
    """Concepts whose frontmatter matches every given filter, in path order."""
    out = []
    for doc in bundle.concepts():
        fm = doc.frontmatter
        if doc.frontmatter_error or not doc.type:
            continue
        if type_ and doc.type != type_:
            continue
        if tags and not set(tags) <= set(fm.get("tags") or []):
            continue
        if status and fm.get("status", "stable") != status:
            continue
        if folder and not str(doc.rel).startswith(bundle.rel(folder).strip("/") + "/"):
            continue
        if trust and report.trust_tier(doc) != trust:
            continue
        out.append(doc)
    return out
