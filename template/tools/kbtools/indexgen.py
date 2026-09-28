"""Deterministic generation of OKF index.md files (OKF §8) from frontmatter."""

from __future__ import annotations

import posixpath
from pathlib import Path, PurePosixPath

from .bundle import RESERVED, Bundle, Document, in_tooling_folder
from .mdlinks import encode_path

OKF_VERSION = "0.2"
FOLDERS_HEADING = "Folders"
EMPTY_HEADING = "Pages"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _entry(title: str, href: str, description: str) -> str:
    line = f"* [{_escape(title)}]({encode_path(href)})"
    return f"{line} - {description}" if description else line


def folders_to_index(bundle: Bundle) -> list[str]:
    """Bundle-relative folders that get an index.md ('' is the root).

    A folder is indexed when it contains a .md file anywhere below it or has a
    taxonomy entry. Dot-folders and `_` folders (vault tooling such as
    `_templates`, not knowledge) are skipped.
    """
    folders = {""}
    for rel in bundle.files:
        if not rel.endswith(".md") or posixpath.basename(rel) in RESERVED:
            continue
        parent = posixpath.dirname(rel)
        if parent in folders or in_tooling_folder(PurePosixPath(rel)):
            continue
        while parent and parent not in folders:
            folders.add(parent)
            parent = posixpath.dirname(parent)
    for name in bundle.config.folders:
        if in_tooling_folder(PurePosixPath(name, "x")):
            continue
        folders.add(name)
        ancestor = PurePosixPath(name).parent
        while str(ancestor) != ".":
            folders.add(str(ancestor))
            ancestor = ancestor.parent
    return sorted(folders)


def _parent(folder: str) -> str:
    parent = str(PurePosixPath(folder).parent)
    return "" if parent == "." else parent


def _child_folders(folder: str, all_folders: list[str]) -> list[str]:
    return [f for f in all_folders if f and _parent(f) == folder]


def _folder_meta(bundle: Bundle, folder: str) -> tuple[str, str]:
    spec = bundle.config.folder_spec(folder) or {}
    title = " ".join(str(spec.get("title") or "").split())  # a block-scalar title may hold line breaks
    title = title or PurePosixPath(folder).name.replace("-", " ").capitalize()
    return title, " ".join(str(spec.get("description", "")).split())


def _sorted_docs(bundle: Bundle, folder: str, docs: list[Document]) -> list[Document]:
    if bundle.config.folder_sort(folder) == "date-desc":
        return sorted(docs, key=lambda d: d.rel.name, reverse=True)
    return sorted(docs, key=lambda d: (d.title.casefold(), d.rel.name))


def render_index(
    bundle: Bundle, folder: str, all_folders: list[str], by_folder: dict[str, list[Document]] | None = None
) -> str:
    config = bundle.config
    sections: list[tuple[str, list[str]]] = []

    children = _child_folders(folder, all_folders)
    if folder == "":
        groups: dict[str, list[str]] = {g: [] for g in config.taxonomy.get("root_groups", [])}
        for child in children:
            spec = config.folder_spec(child) or {}
            groups.setdefault(spec.get("group") or FOLDERS_HEADING, []).append(child)
        order = {name: i for i, name in enumerate(config.folders)}
        for group, members in groups.items():
            members.sort(key=lambda c: (order.get(c, len(order)), c))
            sections.append((group, [_entry(*_child_entry(bundle, c)) for c in members]))
    else:
        if config.folder_sort(folder) == "date-desc":
            children = sorted(children, reverse=True)
        else:
            children = sorted(children, key=lambda c: _folder_meta(bundle, c)[0].casefold())
        sections.append((FOLDERS_HEADING, [_entry(*_child_entry(bundle, c)) for c in children]))

    docs = (by_folder or _by_folder(bundle)).get(folder, [])
    by_type: dict[str, list[Document]] = {}
    for doc in docs:
        by_type.setdefault(doc.type or "Untyped", []).append(doc)
    type_order = list(config.types)
    for type_name in sorted(by_type, key=lambda t: (type_order.index(t) if t in type_order else len(type_order), t)):
        heading = config.types.get(type_name, {}).get("plural", type_name)
        entries = [
            _entry(d.title, f"./{d.rel.name}", d.description) for d in _sorted_docs(bundle, folder, by_type[type_name])
        ]
        sections.append((heading, entries))

    sections = [(h, e) for h, e in sections if e] or [(EMPTY_HEADING, [])]
    body = "\n".join(f"# {h}\n" + ("\n" + "".join(f"{line}\n" for line in e) if e else "") for h, e in sections)
    if folder == "":
        return f'---\nokf_version: "{OKF_VERSION}"\n---\n\n{body}'
    return body


def _child_entry(bundle: Bundle, child: str) -> tuple[str, str, str]:
    title, description = _folder_meta(bundle, child)
    return title, f"./{PurePosixPath(child).name}/index.md", description


def generate(bundle: Bundle) -> dict[Path, str]:
    """Map of index.md path -> expected content for every indexed folder."""
    all_folders = folders_to_index(bundle)
    by_folder = _by_folder(bundle)
    return {
        (bundle.root / folder / "index.md") if folder else bundle.root / "index.md": render_index(
            bundle, folder, all_folders, by_folder
        )
        for folder in all_folders
    }


def _by_folder(bundle: Bundle) -> dict[str, list[Document]]:
    """The pages an index lists, by folder: every non-reserved file with parseable frontmatter."""
    out: dict[str, list[Document]] = {}
    for doc in bundle.documents:
        if not doc.is_reserved and not doc.frontmatter_error:
            out.setdefault(doc.folder, []).append(doc)
    return out


def orphans(bundle: Bundle, expected: dict[Path, str] | None = None) -> list[Path]:
    """index.md files left behind in folders that no longer hold pages (`write` deletes them)."""
    expected = generate(bundle) if expected is None else expected
    holding = set()  # folders with a page anywhere below them
    for rel in bundle.files:
        if rel.endswith(".md") and posixpath.basename(rel) not in RESERVED:
            folder = posixpath.dirname(rel)
            while folder and folder not in holding:
                holding.add(folder)
                folder = posixpath.dirname(folder)
    return [
        bundle.root / rel
        for rel in sorted(bundle.files)
        if posixpath.basename(rel) == "index.md"
        and bundle.root / rel not in expected
        and posixpath.dirname(rel) not in holding
    ]


def write(bundle: Bundle) -> list[Path]:
    """Regenerate every index.md and delete orphaned ones; returns the paths written or deleted.

    A returned path that no longer exists was deleted.
    """
    changed = []
    expected = generate(bundle)
    for path in orphans(bundle, expected):
        path.unlink()
        changed.append(path)
    for path, content in expected.items():
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")  # LF on every platform
            changed.append(path)
    return changed


def stale(bundle: Bundle, expected: dict[Path, str] | None = None) -> list[Path]:
    """index.md files that `write` would change: missing, out of date, or orphaned."""
    expected = generate(bundle) if expected is None else expected
    outdated = [
        path for path, content in expected.items() if not path.exists() or path.read_text(encoding="utf-8") != content
    ]
    return sorted(outdated + orphans(bundle, expected))
