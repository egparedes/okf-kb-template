"""Rewrite internal links: `kb fix-links`, `kb mv` and `kb merge`.

`kb fix-links` rewrites internal links to the bundle-absolute form `/path/to/page.md`.
Obsidian writes vault-root paths without the leading slash ("Path from vault
folder") and rewrites links in that style on rename; OKF would read those as
file-relative. This fixer resolves each internal link the way a reader most
plausibly meant it and rewrites it as `/…`:

1. relative to the linking file, if that target exists;
2. otherwise relative to the bundle root (Obsidian's vault-path style);
3. otherwise the link is left untouched (reported by `kb check` as broken).

A link is an inline link or image of the body, a reference definition
(`[label]: target`), a frontmatter value `[text](target)` at any depth (the
relation keys, block or flow style), or the value of a `resource` key
(`sources[].resource`) that is not a URL. Frontmatter is edited in place:
only the changed values are rewritten, so comments, anchors, tags and layout
stay (a changed block scalar, `|` or `>`, becomes a double-quoted one).
HTML `href`/`src` attributes and other frontmatter keys (`image:`) are not
links here. Generated index.md files keep their relative `./` links.

`kb mv` and `kb merge` compute every edit first and then apply them all or
nothing (`_commit`): originals are copied to `.cache/kb-backup/` and put back
if a step fails.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

import yaml

from .bundle import RESERVED, Bundle, Document, record_touched
from .mdlinks import Relation, encode_path, parse_relation, resolve

BACKUPS = ".cache/kb-backup"
QUESTIONS = "tools/retrieval-eval/questions.yaml"  # retrieval_eval.QUESTIONS
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_STR_TAG = "tag:yaml.org,2002:str"
_PROPERTIES = re.compile(r"(?:[&!]\S*\s+)*")  # a node's anchor and tag, before its scalar

# A rewrite maps a link target as written (percent-encoded, with its #fragment)
# to its new form, or None to leave it as it is.
Rewrite = Callable[[str], "str | None"]
Edit = tuple[int, int, str]  # replace text[start:end] with the string


# -- finding and rewriting links -------------------------------------------------


def _internal(target: str) -> bool:
    return Relation(key="", text="", target=target).is_internal


def _fm_value(key: object, value: str, rewrite: Rewrite) -> str | None:
    """The new form of a frontmatter string that is a link, or None if it is not one or is unchanged."""
    relation = parse_relation(str(key), value)
    if relation is not None:
        new = rewrite(relation.target) if relation.is_internal else None
        return f"[{relation.text}]({new})" if new and new != relation.target else None
    if key == "resource" and _internal(value.strip()):
        new = rewrite(value.strip())
        return new if new and new != value.strip() else None
    return None


def _changes(value: Any, rewrite: Rewrite, key: object = None) -> bool:
    """True if any link in parsed frontmatter would change (a cheap test before locating it in the text)."""
    if isinstance(value, dict):
        return any(_changes(v, rewrite, k) for k, v in value.items())
    if isinstance(value, list):
        return any(_changes(v, rewrite, key) for v in value)
    return isinstance(value, str) and _fm_value(key, value, rewrite) is not None


def _quoted(value: str, style: str | None) -> str:
    """A YAML scalar for `value` in the given style (block styles become double-quoted); plain only where it reads back unchanged."""
    if style == "'":
        return "'" + value.replace("'", "''") + "'"
    if not style:
        try:
            if yaml.safe_load(f"k: {value}") == {"k": value} and yaml.safe_load(f"k: [{value}]") == {"k": [value]}:
                return value
        except yaml.YAMLError:
            pass
    return json.dumps(value, ensure_ascii=False)  # a JSON string is a YAML double-quoted scalar


def _yaml_edits(raw: str, offset: int, rewrite: Rewrite) -> list[Edit]:
    """Edits to the string scalars of a YAML text that are links; offsets shifted by `offset`."""
    try:
        root = yaml.compose(raw, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return []
    edits: list[Edit] = []
    seen: set[int] = set()  # an alias is the anchored node again: edit it once, where it is written

    def walk(node: yaml.Node | None, key: object) -> None:
        if node is None or id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                walk(v, k.value if isinstance(k, yaml.ScalarNode) else None)
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(item, key)
        elif isinstance(node, yaml.ScalarNode) and node.tag == _STR_TAG:
            new = _fm_value(key, node.value, rewrite)
            if new is not None:
                start, end = node.start_mark.index, node.end_mark.index
                start = _PROPERTIES.match(raw, start, end).end()  # keep `&anchor` and `!!str`
                span = raw[start:end]
                trailing = span[len(span.rstrip()):] if node.style in ("|", ">") else ""  # a block scalar's line ends
                edits.append((offset + start, offset + end, _quoted(new, node.style) + trailing))

    walk(root, None)
    return edits


def _frontmatter_span(doc: Document) -> tuple[int, int]:
    """Offsets of the YAML between the `---` lines."""
    start = doc.text.index("\n") + 1
    end = doc.fm_end - 1 if doc.text[doc.fm_end - 1 : doc.fm_end] == "\n" else doc.fm_end
    return start, doc.text.rfind("\n", 0, end) + 1


def link_edits(doc: Document, rewrite: Rewrite) -> list[Edit]:
    """Edits (offsets in `doc.text`) for every link of a page that `rewrite` changes."""
    edits: list[Edit] = []
    for link in doc.links:
        new = rewrite(link.target) if link.is_internal else None
        if new and new != link.target:
            edits.append((doc.fm_end + link.start, doc.fm_end + link.end, new))
    body = doc.body
    for ref in doc.ref_defs:
        new = rewrite(ref.target) if _internal(ref.target) else None
        if new and new != ref.target:
            start = body.index(ref.target, body.index("]:", ref.start) + 2)
            edits.append((doc.fm_end + start, doc.fm_end + start + len(ref.target), new))
    if doc.has_frontmatter and not doc.frontmatter_error and _changes(doc.frontmatter, rewrite):
        start, end = _frontmatter_span(doc)
        edits += _yaml_edits(doc.text[start:end], start, rewrite)
    return edits


def apply(text: str, edits: Iterable[Edit]) -> str:
    for start, end, new in sorted(set(edits), reverse=True):
        text = text[:start] + new + text[end:]
    return text


def rewrite_text(doc: Document, rewrite: Rewrite) -> str:
    return apply(doc.text, link_edits(doc, rewrite))


# -- kb fix-links ------------------------------------------------------------------


def _absolute(bundle: Bundle, target: str, folder: str) -> str | None:
    path, _, fragment = target.partition("#")
    path = unquote(path)
    if not path or path.startswith("/") or _SCHEME.match(path):
        return None
    candidates = [resolve(path, folder), posixpath.normpath(path)]
    for candidate in candidates:
        if candidate and not candidate.startswith("..") and bundle.exists(candidate):
            new = "/" + encode_path(candidate)
            return f"{new}#{fragment}" if fragment else new
    return None


def fix_text(bundle: Bundle, doc: Document) -> str:
    return rewrite_text(doc, lambda target: _absolute(bundle, target, doc.folder))


def fix(bundle: Bundle, docs: list[Document] | None = None) -> list[Document]:
    changed, writes = [], {}
    for doc in docs if docs is not None else bundle.documents:
        if doc.rel.name == "index.md":
            continue
        new_text = fix_text(bundle, doc)
        if new_text != doc.text:
            writes[doc.path] = new_text
            changed.append(doc)
    _commit(bundle, writes, what="kb fix-links")
    record_touched(bundle.repo_root, [d.path for d in changed])
    return changed


# -- retargeting links to a moved or merged page ---------------------------------------


def _rebase(target: str, folder: str) -> str | None:
    """A relative link target, read from `folder`, as a bundle-absolute one; None if absolute or escaping."""
    path_part, _, fragment = target.partition("#")
    resolved = None if path_part.startswith("/") else resolve(unquote(path_part), folder)
    if not resolved:
        return None
    new = "/" + encode_path(resolved)
    return f"{new}#{fragment}" if fragment else new


def _retarget(target: str, folder: str, old_rel: str, new_target: str, rebase: bool) -> str | None:
    """`new_target` for a link to `old_rel`; with `rebase` (the moved page's own links), other relative links made absolute."""
    path_part, _, fragment = target.partition("#")
    if resolve(unquote(path_part), folder) == old_rel:
        return f"{new_target}#{fragment}" if fragment else new_target
    return _rebase(target, folder) if rebase else None


def retarget(bundle: Bundle, old_rel: str, new_rel: str, overrides: dict[str, Document] | None = None) -> dict[str, str]:
    """New text of every page that links to `old_rel`, with those links pointing to `/new_rel`.

    Reads the bundle as it is (nothing is written). `overrides` replaces the
    parsed page at a path (a merged page's new text). Links in the body,
    reference definitions and frontmatter are rewritten; generated index.md
    files are left to `kb index`.
    """
    new_target = "/" + encode_path(new_rel)
    name = posixpath.basename(old_rel)
    out = {}
    docs = {str(d.rel): d for d in bundle.documents} | (overrides or {})
    for rel, doc in docs.items():
        if rel in (overrides or {}):
            out[rel] = doc.text
        if rel == old_rel or doc.rel.name == "index.md" or name not in unquote(doc.text):
            continue
        text = rewrite_text(doc, lambda t, folder=doc.folder: _retarget(t, folder, old_rel, new_target, False))
        if text != doc.text:
            out[rel] = text
    return out


def _question_edits(path: Path, old: str, new: str) -> str | None:
    """questions.yaml with the `expected` page `old` renamed to `new` (`/x.md`); None if unchanged.

    Only the entries change, so comments stay. Where a question already
    expects `new` (after a merge), or lists `old` again, the entry is removed instead.
    """
    try:
        raw = path.read_text(encoding="utf-8")
        root = yaml.compose(raw, Loader=yaml.SafeLoader)
    except (OSError, yaml.YAMLError):
        return None
    edits: list[Edit] = []
    for expected in _expected_lists(root):
        nodes = [n for n in expected.value if isinstance(n, yaml.ScalarNode)]
        values = [n.value for n in nodes]
        matches = [n for n in nodes if n.value == old]
        if not matches:
            continue
        rename = matches[0] if new not in values else None
        if expected.flow_style and (rename is None or len(matches) > 1):
            kept = ", ".join(_quoted(v, None) for v in dict.fromkeys(new if v == old else v for v in values))
            edits.append((expected.start_mark.index, expected.end_mark.index, f"[{kept}]"))
            continue
        for node in matches:
            start = _PROPERTIES.match(raw, node.start_mark.index, node.end_mark.index).end()
            if node is rename:
                edits.append((start, node.end_mark.index, _quoted(new, node.style)))
                continue
            # a block list: drop the item's line
            line = raw.rfind("\n", 0, node.start_mark.index) + 1
            end = raw.find("\n", node.end_mark.index)
            end = len(raw) if end < 0 else end + 1
            if raw[line : node.start_mark.index].strip() != "-" or raw[node.end_mark.index : end].strip()[:1] not in ("", "#"):
                raise SystemExit(f"kb: cannot update {path}: put `{old}` on a line of its own")
            edits.append((line, end, ""))
    return apply(raw, edits) if edits else None


def _expected_lists(root: yaml.Node | None) -> list[yaml.SequenceNode]:
    """The `expected` lists of a composed questions.yaml."""
    if not isinstance(root, yaml.MappingNode):
        return []
    questions = next((v for k, v in root.value if getattr(k, "value", None) == "questions"), None)
    out = []
    for item in questions.value if isinstance(questions, yaml.SequenceNode) else []:
        if isinstance(item, yaml.MappingNode):
            out += [v for k, v in item.value if getattr(k, "value", None) == "expected" and isinstance(v, yaml.SequenceNode)]
    return out


def _questions(bundle: Bundle, old_rel: str, new_rel: str) -> dict[Path, str]:
    """The retrieval-evaluation questions, if a moved or merged page is expected there."""
    path = bundle.repo_root / QUESTIONS
    text = _question_edits(path, f"/{old_rel}", f"/{new_rel}") if path.is_file() else None
    return {path: text} if text is not None else {}


# -- kb mv ---------------------------------------------------------------------------


def _ignored(bundle: Bundle, path: Path) -> bool:
    """True if git ignores the path (False outside a git work tree)."""
    try:
        result = subprocess.run(["git", "check-ignore", "-q", "--", str(path)], cwd=bundle.root,
                                capture_output=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _destination(bundle: Bundle, old_rel: str, new_arg: str) -> str:
    new_rel = bundle.rel(new_arg)
    if not new_rel:
        raise SystemExit(f"kb: give a new path or folder, not `{new_arg}`")
    suffix = PurePosixPath(old_rel).suffix
    if new_rel in bundle.dirs or new_arg.endswith(("/", "\\")):  # into a folder, keeping the name
        new_rel = posixpath.join(new_rel, posixpath.basename(old_rel))
    elif new_rel and not PurePosixPath(new_rel).suffix:
        new_rel += suffix
    name = PurePosixPath(new_rel)
    if not new_rel or name.suffix.lower() != suffix.lower():
        raise SystemExit(f"kb: {new_arg}: keep the file extension ({suffix or 'none'}); "
                         f"to move into a new folder, end the path with `/`")
    if name.name in RESERVED:
        raise SystemExit(f"kb: {name.name} is reserved (a generated index or the log)")
    if any(part.startswith(".") for part in name.parts):
        raise SystemExit(f"kb: {new_rel} is in a hidden folder, which is not part of the bundle")
    dest = bundle.root / new_rel
    case_only = new_rel != old_rel and new_rel.casefold() == old_rel.casefold()
    if new_rel == old_rel or bundle.exists(new_rel) or (
        dest.exists() and not (case_only and dest.samefile(bundle.root / old_rel))  # macOS/Windows: Foo.md "exists" as foo.md
    ):
        raise SystemExit(f"kb: {bundle.show(new_rel)} already exists")
    if bundle.root not in dest.resolve().parents:
        raise SystemExit(f"kb: {new_rel} is outside the bundle")
    for parent in PurePosixPath(new_rel).parents:
        if str(parent) != "." and (bundle.root / parent).is_file():
            raise SystemExit(f"kb: {bundle.show(parent)} is a file, not a folder")
    if _ignored(bundle, dest) and not _ignored(bundle, bundle.root / old_rel):
        raise SystemExit(f"kb: git ignores {bundle.show(new_rel)}, so it would not be part of the bundle")
    return new_rel


def move(bundle: Bundle, old: str, new: str) -> list[str]:
    """Move a page or another file of the bundle (an image, a PDF) and rewrite every link to it.

    A moved page's own relative links are rebased. `expected` pages in
    tools/retrieval-eval/questions.yaml follow a moved page. Returns what was
    updated, as lines to print. Nothing changes unless every step succeeds.
    """
    old_rel = bundle.rel(old)
    source = bundle.root / old_rel
    if not old_rel or not source.is_file() or not bundle.includes(source):
        raise SystemExit(f"kb: {old} is not a file of the bundle")
    if source.name in RESERVED:
        raise SystemExit(f"kb: {source.name} cannot be moved (a generated index or the log)")
    new_rel = _destination(bundle, old_rel, new)
    dest = bundle.root / new_rel
    writes: dict[Path, str] = {}
    if old_rel.endswith(".md"):
        page = bundle.by_rel[old_rel]
        target = "/" + encode_path(new_rel)
        text = rewrite_text(page, lambda t: _retarget(t, page.folder, old_rel, target, True))
        if text != page.text:
            writes[dest] = text
    changed = retarget(bundle, old_rel, new_rel)
    writes |= {bundle.root / rel: text for rel, text in changed.items()}
    questions = _questions(bundle, old_rel, new_rel) if old_rel.endswith(".md") else {}
    _commit(bundle, writes | questions, move=(source, dest), what="kb mv")
    bundle.invalidate()
    record_touched(bundle.repo_root, [dest, *(bundle.root / rel for rel in changed)])
    return [f"updated links in {bundle.show(rel)}" for rel in sorted(changed)] + [
        f"updated {path.relative_to(bundle.repo_root).as_posix()}" for path in questions
    ]


# -- kb merge ---------------------------------------------------------------------------


def _union(first: list, second: list) -> list:
    out = list(first)
    for item in second:
        if item not in out:
            out.append(item)
    return out


def _rebased(value: Any, folder: str, key: object = None) -> Any:
    """Parsed frontmatter with relative link values made bundle-absolute (read from `folder`)."""
    if isinstance(value, dict):
        return {k: _rebased(v, folder, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_rebased(v, folder, key) for v in value]
    if isinstance(value, str):
        new = _fm_value(key, value, lambda t: _rebase(t, folder))
        return value if new is None else new
    return value


def _page(bundle: Bundle, arg: str) -> Document:
    rel = bundle.rel(arg)
    path = bundle.root / rel
    if not rel.endswith(".md") or not path.is_file() or not bundle.includes(path):
        raise SystemExit(f"kb: {arg} is not a page in the bundle")
    return bundle.by_rel[rel]


def merge(bundle: Bundle, old_rel: str, into_rel: str, actor: str, dry_run: bool = False) -> list[str]:
    """Fold page `old_rel` into `into_rel`: union metadata, retarget links, delete the old page.

    The agent merges the body text into `into_rel` first; this does the
    bookkeeping. Nothing changes unless every step succeeds.
    """
    from .pages import now_utc

    old_doc, into_doc = _page(bundle, old_rel), _page(bundle, into_rel)
    old_rel, into_rel = str(old_doc.rel), str(into_doc.rel)
    if old_rel == into_rel:
        raise SystemExit("kb: cannot merge a page into itself")
    if old_doc.is_reserved or into_doc.is_reserved:
        raise SystemExit("kb: index.md and log.md cannot be merged")
    if old_doc.frontmatter_error or into_doc.frontmatter_error or not old_doc.type or not into_doc.type:
        raise SystemExit("kb: both pages need valid frontmatter with a type")
    fm = _rebased(dict(into_doc.frontmatter), into_doc.folder)
    extra = _rebased(old_doc.frontmatter, old_doc.folder)
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
                  if isinstance(v, str) and _relation_target(key, v) not in (old_rel, into_rel)]
        if values:
            fm[key] = values
        else:
            fm.pop(key, None)
    fm.pop("verified", None)  # merged content has not been reviewed yet
    fm["generated"] = {"by": actor, "at": now_utc()}
    header = f"---\n{yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=1000)}---\n"
    merged = Document(path=into_doc.path, rel=into_doc.rel, text=header + into_doc.body, has_frontmatter=True,
                      frontmatter=fm, fm_end=len(header))
    changed = retarget(bundle, old_rel, into_rel, overrides={into_rel: merged})
    questions = _questions(bundle, old_rel, into_rel)
    others = sorted(rel for rel in changed if rel != into_rel)
    plan = [f"merge metadata of {bundle.show(old_rel)} into {bundle.show(into_rel)}", f"delete {bundle.show(old_rel)}"]
    shown = [path.relative_to(bundle.repo_root).as_posix() for path in questions]
    if dry_run:
        return (plan + [f"would update links in {bundle.show(rel)}" for rel in others]
                + [f"would update {path}" for path in shown] + ["(dry run: nothing written)"])
    writes = {bundle.root / rel: text for rel, text in changed.items()} | questions
    _commit(bundle, writes, delete=[old_doc.path], what="kb merge")
    bundle.invalidate()
    record_touched(bundle.repo_root, [into_doc.path, *(bundle.root / rel for rel in others)])
    return plan + [f"updated links in {bundle.show(rel)}" for rel in others] + [f"updated {path}" for path in shown]


def _relation_target(key: str, value: str) -> str | None:
    relation = parse_relation(key, value)
    return resolve(relation.path, "") if relation is not None and relation.is_internal else None


# -- applying changes all or nothing ------------------------------------------------------


def _replace(src: Path, dst: Path) -> None:
    """os.replace, one seam for tests that inject a failure."""
    os.replace(src, dst)


def _write(path: Path, text: str, like: bytes | None) -> None:
    """Write through a temporary file in the same folder, keeping the original's BOM, line ends and mode.

    The text has `\n` line ends (as read); if the original has any `\r\n`,
    every line end is written as `\r\n`, so mixed line ends become CRLF.
    """
    newline = "\r\n" if like is not None and b"\r\n" in like else "\n"
    encoding = "utf-8-sig" if like is not None and like.startswith(b"\xef\xbb\xbf") else "utf-8"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as fh:
            fh.write(text)
        if like is not None and path.exists():
            shutil.copymode(path, tmp)
        _replace(Path(tmp), path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _restore(copy: Path, path: Path) -> None:
    tmp = path.with_name(f".{path.name}.restore.tmp")
    shutil.copy2(copy, tmp)
    os.replace(tmp, path)


def _commit(bundle: Bundle, writes: dict[Path, str], move: tuple[Path, Path] | None = None,
            delete: Iterable[Path] = (), what: str = "kb") -> None:
    """Move a file, write texts, delete files: all of it or nothing.

    The originals are copied to `.cache/kb-backup/<time>-…/` first. If a step
    fails, the steps done so far are undone in reverse order and the backup is
    removed; if undoing fails too, the backup stays and the message names it.
    """
    delete = list(delete)
    if not writes and not move and not delete:
        return
    (bundle.repo_root / BACKUPS).mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=time.strftime("%Y%m%dT%H%M%S-"), dir=bundle.repo_root / BACKUPS))
    saved: dict[Path, Path] = {}
    manifest = []
    try:
        for path in [*([move[0]] if move else []), *writes, *delete]:
            if path not in saved and path.is_file():
                saved[path] = backup / str(len(saved))
                shutil.copy2(path, saved[path])
                manifest.append(f"{len(saved) - 1}\t{path}")
        (backup / "MANIFEST").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    except BaseException:  # nothing was changed yet
        shutil.rmtree(backup, ignore_errors=True)
        raise
    undo: list[Callable[[], None]] = []
    try:
        if move:
            source, dest = move
            made = [p for p in reversed(dest.parents) if not p.exists()]
            for folder in made:
                folder.mkdir()
                undo.append(folder.rmdir)
            os.rename(source, dest)
            undo.append(lambda: os.rename(dest, source))
            saved[dest] = saved[source]
        for path, text in writes.items():
            existed = path.exists()
            _write(path, text, saved[path].read_bytes() if path in saved else None)
            undo.append((lambda p=path: _restore(saved[p], p)) if existed else path.unlink)
        for path in delete:
            path.unlink()
            undo.append(lambda p=path: _restore(saved[p], p))
    except BaseException as exc:
        failed = []
        for step in reversed(undo):
            try:
                step()
            except OSError as undo_exc:
                failed.append(str(undo_exc))
        if failed:
            raise SystemExit(f"{what}: failed ({exc}), and could not undo every step ({'; '.join(failed)}); "
                             f"the original files are in {backup} (see its MANIFEST)") from exc
        shutil.rmtree(backup, ignore_errors=True)
        if isinstance(exc, Exception):
            raise SystemExit(f"{what}: failed ({exc}); nothing was changed") from exc
        raise
    shutil.rmtree(backup, ignore_errors=True)
