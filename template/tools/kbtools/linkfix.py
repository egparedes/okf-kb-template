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

from .bundle import Bundle, Document, parse_document, record_touched
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
    record_touched(bundle.repo_root, [d.path for d in changed])
    return changed


def _bundle_rel(bundle: Bundle, path: str) -> str:
    return bundle.rel(path)


def retarget(bundle: Bundle, old_rel: str, new_rel: str, moved_from: str | None = None) -> list[str]:
    """Rewrite every link to `old_rel` (body, relation keys, sources[].resource) to `/new_rel`.

    `moved_from` is the previous location of a page now at `new_rel`: its own
    relative links were written against that folder and are rebased.
    """
    old_folder = posixpath.dirname(moved_from) if moved_from else None
    new_target = "/" + encode_path(new_rel)
    changed = []
    for path in bundle.markdown_paths():
        doc = parse_document(path, bundle.root)
        if doc.rel.name == "index.md" or doc.frontmatter_error:
            continue
        if str(doc.rel) == old_rel:
            continue
        moved = moved_from is not None and str(doc.rel) == new_rel
        folder = old_folder if moved else doc.folder
        edits: list[tuple[int, int, str]] = []

        def rewrite(target: str, folder: str = folder, moved: bool = moved) -> str | None:
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




def move(bundle: Bundle, old_rel: str, new_rel: str) -> list[str]:
    """Move a page and rewrite every link to it; its own relative links are rebased."""
    old_rel, new_rel = _bundle_rel(bundle, old_rel), _bundle_rel(bundle, new_rel)
    if not new_rel.endswith(".md"):
        new_rel += ".md"
    source, dest = bundle.root / old_rel, bundle.root / new_rel
    if not source.is_file():
        raise SystemExit(f"kb: {source} does not exist")
    case_only = new_rel != old_rel and new_rel.casefold() == old_rel.casefold()
    if dest.exists() and not (case_only and dest.samefile(source)):  # macOS/Windows: Foo.md "exists" as foo.md
        raise SystemExit(f"kb: {dest} already exists")
    if bundle.root.resolve() not in dest.resolve().parents:
        raise SystemExit(f"kb: {new_rel} is outside the bundle")
    dest.parent.mkdir(parents=True, exist_ok=True)
    source.rename(dest)
    bundle.invalidate()
    changed = retarget(bundle, old_rel, new_rel, moved_from=old_rel)
    record_touched(bundle.repo_root, [dest, *(bundle.root / rel for rel in changed)])
    return changed


def _union(first: list, second: list) -> list:
    out = list(first)
    for item in second:
        if item not in out:
            out.append(item)
    return out


def merge(bundle: Bundle, old_rel: str, into_rel: str, actor: str, dry_run: bool = False) -> list[str]:
    """Fold page `old_rel` into `into_rel`: union metadata, retarget links, delete the old page.

    The agent merges the body text into `into_rel` first; this does the bookkeeping.
    """
    import yaml

    from .pages import now_utc

    old_rel, into_rel = _bundle_rel(bundle, old_rel), _bundle_rel(bundle, into_rel)
    old, into = bundle.root / old_rel, bundle.root / into_rel
    root = bundle.root.resolve()
    for path in (old, into):
        if root not in path.resolve().parents or not path.is_file():
            raise SystemExit(f"kb: {path} is not a page in the bundle")
    if old.resolve() == into.resolve():
        raise SystemExit("kb: cannot merge a page into itself")
    old_doc, into_doc = parse_document(old, bundle.root), parse_document(into, bundle.root)
    if old_doc.is_reserved or into_doc.is_reserved:
        raise SystemExit("kb: index.md and log.md cannot be merged")
    if old_doc.frontmatter_error or into_doc.frontmatter_error or not old_doc.type or not into_doc.type:
        raise SystemExit("kb: both pages need valid frontmatter with a type")
    fm, extra = dict(into_doc.frontmatter), old_doc.frontmatter
    aliases = _union(fm.get("aliases") or [], extra.get("aliases") or [])
    if old_doc.title != into_doc.title and old_doc.title not in aliases:
        aliases.append(old_doc.title)
    if aliases:
        fm["aliases"] = aliases
    fm["tags"] = _union(fm.get("tags") or [], extra.get("tags") or [])
    sources = {s["id"]: s for s in fm.get("sources") or [] if isinstance(s, dict) and "id" in s}
    for source in extra.get("sources") or []:
        if not isinstance(source, dict) or "id" not in source:
            continue
        mine = sources.get(source["id"])
        if mine and mine.get("resource") != source.get("resource"):
            raise SystemExit(f"kb: source id `{source['id']}` points to different resources; rename one first")
        sources.setdefault(source["id"], source)
    if sources:
        fm["sources"] = list(sources.values())
    for key in bundle.config.relations:
        values = [v for v in _union(fm.get(key) or [], extra.get(key) or [])
                  if isinstance(v, str) and f"(/{into_rel})" not in v and f"(/{old_rel})" not in v]
        if values:
            fm[key] = values
        else:
            fm.pop(key, None)
    fm.pop("verified", None)  # merged content has not been reviewed yet
    fm["generated"] = {"by": actor, "at": now_utc()}
    plan = [f"merge metadata of {bundle.show(old_rel)} into {bundle.show(into_rel)}", f"delete {bundle.show(old_rel)}"]
    if dry_run:
        linking = sorted(
            str(d.rel) for d in bundle.documents
            if d.rel.name != "index.md" and str(d.rel) != old_rel
            and any(resolve(unquote(t.split("#")[0]), d.folder) == old_rel
                    for t in [l.target for l in find_links(d.body) if not l.is_external] + _FM_LINK.findall(d.text[: d.fm_end]))
        )
        return plan + [f"would update links in {bundle.show(rel)}" for rel in linking] + ["(dry run: nothing written)"]
    header = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=1000)
    into.write_text(f"---\n{header}---\n{into_doc.body}", encoding="utf-8")
    old.unlink()
    bundle.invalidate()
    changed = retarget(bundle, old_rel, into_rel)
    record_touched(bundle.repo_root, [into, *(bundle.root / rel for rel in changed)])
    return plan + [f"updated links in {bundle.show(rel)}" for rel in changed]
