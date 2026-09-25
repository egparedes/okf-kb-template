"""Deterministic generation of OKF index.md files (OKF §8) from frontmatter."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from .bundle import Bundle, Document
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
    for doc in bundle.documents:
        if doc.is_reserved or any(part.startswith((".", "_")) for part in doc.rel.parts[:-1]):
            continue
        parent = doc.rel.parent
        while str(parent) != ".":
            folders.add(str(parent))
            parent = parent.parent
    for name in bundle.config.folders:
        if any(part.startswith((".", "_")) for part in PurePosixPath(name).parts):
            continue
        folders.add(name)
        parent = PurePosixPath(name).parent
        while str(parent) != ".":
            folders.add(str(parent))
            parent = parent.parent
    return sorted(folders)


def _parent(folder: str) -> str:
    parent = str(PurePosixPath(folder).parent)
    return "" if parent == "." else parent


def _child_folders(folder: str, all_folders: list[str]) -> list[str]:
    return [f for f in all_folders if f and _parent(f) == folder]


def _folder_meta(bundle: Bundle, folder: str) -> tuple[str, str]:
    spec = bundle.config.folder_spec(folder) or {}
    title = spec.get("title") or PurePosixPath(folder).name.replace("-", " ").capitalize()
    return title, " ".join(str(spec.get("description", "")).split())


def _sorted_docs(bundle: Bundle, folder: str, docs: list[Document]) -> list[Document]:
    if bundle.config.folder_sort(folder) == "date-desc":
        return sorted(docs, key=lambda d: d.rel.name, reverse=True)
    return sorted(docs, key=lambda d: (d.title.casefold(), d.rel.name))


def render_index(bundle: Bundle, folder: str, all_folders: list[str]) -> str:
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

    docs = [
        d
        for d in bundle.documents
        if not d.is_reserved and d.folder == folder and not d.frontmatter_error
    ]
    by_type: dict[str, list[Document]] = {}
    for doc in docs:
        by_type.setdefault(doc.type or "Untyped", []).append(doc)
    type_order = list(config.types)
    for type_name in sorted(by_type, key=lambda t: (type_order.index(t) if t in type_order else len(type_order), t)):
        heading = config.types.get(type_name, {}).get("plural", type_name)
        entries = [
            _entry(d.title, f"./{d.rel.name}", d.description)
            for d in _sorted_docs(bundle, folder, by_type[type_name])
        ]
        sections.append((heading, entries))

    sections = [(h, e) for h, e in sections if e] or [(EMPTY_HEADING, [])]
    body = "\n".join(
        f"# {h}\n" + ("\n" + "".join(f"{line}\n" for line in e) if e else "") for h, e in sections
    )
    if folder == "":
        return f'---\nokf_version: "{OKF_VERSION}"\n---\n\n{body}'
    return body


def _child_entry(bundle: Bundle, child: str) -> tuple[str, str, str]:
    title, description = _folder_meta(bundle, child)
    return title, f"./{PurePosixPath(child).name}/index.md", description


def generate(bundle: Bundle) -> dict[Path, str]:
    """Map of index.md path -> expected content for every indexed folder."""
    all_folders = folders_to_index(bundle)
    return {
        (bundle.root / folder / "index.md") if folder else bundle.root / "index.md": render_index(
            bundle, folder, all_folders
        )
        for folder in all_folders
    }


def _stale_index_files(bundle: Bundle, expected: dict[Path, str]) -> list[Path]:
    """Generated index.md files left behind in folders that no longer hold pages."""
    stale = []
    for path in bundle.root.rglob("index.md"):
        rel = path.relative_to(bundle.root)
        if path in expected or any(part.startswith(".") for part in rel.parts):
            continue
        siblings = [p for p in path.parent.rglob("*.md") if p.name not in ("index.md", "log.md")]
        if not siblings:
            stale.append(path)
    return stale


def write(bundle: Bundle) -> list[Path]:
    changed = []
    expected = generate(bundle)
    for path in _stale_index_files(bundle, expected):
        path.unlink()
        changed.append(path)
    for path, content in expected.items():
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            changed.append(path)
    return changed


def stale(bundle: Bundle) -> list[Path]:
    return [
        path
        for path, content in generate(bundle).items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    ]
