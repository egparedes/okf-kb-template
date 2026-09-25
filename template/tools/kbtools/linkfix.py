"""Rewrite internal links to the bundle-absolute form `/path/to/page.md`.

Obsidian writes vault-root paths without the leading slash ("Path from vault
folder") and rewrites links in that style on rename; OKF would read those as
file-relative. This fixer resolves each internal link the way a reader most
plausibly meant it and rewrites it as `/…`:

1. relative to the linking file, if that target exists;
2. otherwise relative to the bundle root (Obsidian's vault-path style);
3. otherwise the link is left untouched (reported by `kb check` as broken).

Generated index.md files keep their relative `./` links.
"""

from __future__ import annotations

import posixpath
import re
from urllib.parse import unquote

from .bundle import Bundle, Document, parse_document
from .mdlinks import encode_path, find_links, resolve

_FM_LINK = re.compile(r"\]\((?P<target>[^)\s]+)\)")


def _absolute(bundle: Bundle, target: str, folder: str) -> str | None:
    path, _, fragment = target.partition("#")
    path = unquote(path)
    if not path or path.startswith("/") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", path):
        return None
    candidates = [resolve(path, folder), posixpath.normpath(path)]
    for candidate in candidates:
        if candidate and not candidate.startswith("..") and bundle.exists(candidate):
            new = "/" + encode_path(candidate)
            return f"{new}#{fragment}" if fragment else new
    return None


def fix_text(bundle: Bundle, doc: Document) -> str:
    edits: list[tuple[int, int, str]] = []
    body_start = doc.fm_end
    for link in find_links(doc.body):
        if link.is_external or link.is_anchor_only:
            continue
        new = _absolute(bundle, link.target, doc.folder)
        if new and new != link.target:
            edits.append((body_start + link.start, body_start + link.end, new))
    if doc.has_frontmatter:
        fm_text = doc.text[: doc.fm_end]
        for m in _FM_LINK.finditer(fm_text):
            new = _absolute(bundle, m.group("target"), doc.folder)
            if new and new != m.group("target"):
                edits.append((m.start("target"), m.end("target"), new))
    text = doc.text
    for start, end, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[end:]
    return text


def fix(bundle: Bundle, docs: list[Document] | None = None) -> list[Document]:
    changed = []
    for doc in docs if docs is not None else bundle.documents:
        if doc.rel.name == "index.md" or doc.frontmatter_error:
            continue
        new_text = fix_text(bundle, doc)
        if new_text != doc.text:
            doc.path.write_text(new_text, encoding="utf-8")
            changed.append(doc)
    return changed


def _bundle_rel(path: str) -> str:
    path = path.lstrip("/")
    return path[3:] if path.startswith("kb/") else path


def move(bundle: Bundle, old_rel: str, new_rel: str) -> list[str]:
    """Move a page and rewrite every link to it (body, relation keys, sources[].resource).

    Relative links inside the moved page are rebased to bundle-absolute form.
    """
    old_rel, new_rel = _bundle_rel(old_rel), _bundle_rel(new_rel)
    if not new_rel.endswith(".md"):
        new_rel += ".md"
    source, dest = bundle.root / old_rel, bundle.root / new_rel
    if not source.is_file():
        raise SystemExit(f"kb: {source} does not exist")
    if dest.exists():
        raise SystemExit(f"kb: {dest} already exists")
    if bundle.root.resolve() not in dest.resolve().parents:
        raise SystemExit(f"kb: {new_rel} is outside the bundle")
    dest.parent.mkdir(parents=True, exist_ok=True)
    source.rename(dest)
    old_folder = posixpath.dirname(old_rel)
    new_target = "/" + encode_path(new_rel)
    changed = []
    for path in bundle.markdown_paths():
        doc = parse_document(path, bundle.root)
        if doc.rel.name == "index.md" or doc.frontmatter_error:
            continue
        moved = str(doc.rel) == new_rel
        folder = old_folder if moved else doc.folder
        edits: list[tuple[int, int, str]] = []

        def rewrite(target: str) -> str | None:
            path_part, _, fragment = target.partition("#")
            if not path_part or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", path_part):
                return None
            resolved = resolve(unquote(path_part), folder)
            if resolved == old_rel:
                new = new_target
            elif moved and not path_part.startswith("/") and resolved is not None:
                new = "/" + encode_path(resolved)  # rebase the moved page's relative links
            else:
                return None
            return f"{new}#{fragment}" if fragment else new

        for link in find_links(doc.body):
            new = rewrite(link.target)
            if new:
                edits.append((doc.fm_end + link.start, doc.fm_end + link.end, new))
        fm_text = doc.text[: doc.fm_end]
        for m in _FM_LINK.finditer(fm_text):
            new = rewrite(m.group("target"))
            if new:
                edits.append((m.start("target"), m.end("target"), new))
        for m in re.finditer(r"""(?m)^\s*-?\s*resource:\s*(["']?)(?P<target>[/.][^\s"']*)\1\s*$""", fm_text):
            new = rewrite(m.group("target"))
            if new:
                edits.append((m.start("target"), m.end("target"), new))
        if edits:
            text = doc.text
            for start, end, new in sorted(set(edits), reverse=True):
                text = text[:start] + new + text[end:]
            path.write_text(text, encoding="utf-8")
            changed.append(str(doc.rel))
    return changed
