"""Bundle model: locating files, parsing frontmatter, loading house config."""

from __future__ import annotations

import json
import os
import posixpath
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import yaml

from . import mdlinks
from .mdlinks import Link, RefDef, Relation

RESERVED = {"index.md", "log.md"}
# Bound at import: tests that stub subprocess.run for other tools must not see the bundle listing.
_run_git = subprocess.run
DEFAULT_BUNDLE_DIR = "kb"
TOUCHED = ".cache/kb-touched.txt"
SCOPES = ("knowledge", "all")


def record_touched(repo_root: Path, paths) -> None:
    """Remember pages changed in an agent session, for the Stop hook.

    Claude Code sets CLAUDECODE=1 for the commands its agent runs; a human's
    terminal does not, so human edits never block an agent session.
    """
    if not os.environ.get("CLAUDECODE"):
        return
    target = repo_root / TOUCHED
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        for path in paths:
            fh.write(f"{Path(path).resolve()}\n")


# libyaml's parser when PyYAML was built with it (several times faster), else the pure-Python one.
# libyaml is slightly more lenient: it accepts a few inputs the pure-Python parser rejects,
# e.g. a tab after the colon (`a:\t1`), so such frontmatter parses on one machine and not another.
_SafeLoader: Any = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class _Loader(_SafeLoader):
    """SafeLoader that keeps timestamps as strings, so values round-trip verbatim."""


_Loader.yaml_implicit_resolvers = {
    key: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_yaml(text: str) -> Any:
    return yaml.load(text, Loader=_Loader)  # noqa: S506 - SafeLoader subclass


def in_tooling_folder(rel: PurePosixPath) -> bool:
    """True below a `.` folder (hidden) or a `_` folder (vault tooling such as `_templates`)."""
    return any(part.startswith(("_", ".")) for part in rel.parts[:-1])


@dataclass
class Document:
    """One markdown file of the bundle.

    The parsed views of the body (masked text, links, footnotes, reference
    definitions) and the frontmatter links are computed once, on first use.
    Their offsets and line numbers are relative to the body: add
    `body_line_offset` for a line of the file.
    """

    path: Path  # absolute path
    rel: PurePosixPath  # bundle-relative path, e.g. systems/dns.md
    text: str
    has_frontmatter: bool = False
    frontmatter: dict[str, Any] = field(default_factory=dict)
    frontmatter_error: str | None = None
    fm_end: int = 0  # offset where the body starts
    body_line_offset: int = 0  # number of lines before the body

    @property
    def is_reserved(self) -> bool:
        return self.rel.name in RESERVED

    @property
    def is_root_index(self) -> bool:
        return str(self.rel) == "index.md"

    @property
    def body(self) -> str:
        return self.text[self.fm_end :]

    @property
    def concept_id(self) -> str:
        return str(self.rel.with_suffix(""))

    @cached_property
    def folder(self) -> str:
        parent = str(self.rel.parent)
        return "" if parent == "." else parent

    @property
    def in_tooling_folder(self) -> bool:
        return in_tooling_folder(self.rel)

    @property
    def type(self) -> str | None:
        value = self.frontmatter.get("type")
        return value.strip() if isinstance(value, str) and value.strip() else None

    @property
    def title(self) -> str:
        value = self.frontmatter.get("title")
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
        return self.rel.stem.replace("-", " ").capitalize()

    @property
    def description(self) -> str:
        value = self.frontmatter.get("description")
        return " ".join(value.split()) if isinstance(value, str) else ""

    # -- parsed views, cached -----------------------------------------------

    @cached_property
    def masked_body(self) -> str:
        """The body with code, HTML comments and backslash escapes blanked out (same offsets)."""
        return mdlinks.mask(self.body)

    @cached_property
    def links(self) -> list[Link]:
        """Inline links and images of the body, outside code."""
        return mdlinks.find_links(self.body, self.masked_body)

    @cached_property
    def link_targets(self) -> set[str]:
        """Bundle paths the body's internal links point to."""
        return {t for t in map(self.resolve, self.links) if t is not None}

    @cached_property
    def footnote_refs(self) -> list[tuple[str, int]]:
        """(label, body line) of every footnote reference `[^label]`."""
        return mdlinks.footnote_refs(self.body, self.masked_body)

    @cached_property
    def footnote_defs(self) -> set[str]:
        return mdlinks.footnote_defs(self.body, self.masked_body)

    @cached_property
    def ref_defs(self) -> list[RefDef]:
        """Reference-style link definitions `[label]: target` of the body."""
        return mdlinks.ref_defs(self.body, self.masked_body)

    @cached_property
    def frontmatter_links(self) -> list[Relation]:
        """Every top-level frontmatter value, or list item, of the form `[text](target)`."""
        out = []
        for key, value in self.frontmatter.items():
            for item in value if isinstance(value, list) else [value]:
                relation = mdlinks.parse_relation(str(key), item)
                if relation is not None:
                    out.append(relation)
        return out

    def relations(self, keys: Iterable[str]) -> list[Relation]:
        """Frontmatter links under the given keys (the vocabulary's relation keys)."""
        wanted = set(keys)
        return [r for r in self.frontmatter_links if r.key in wanted]

    def resolve(self, link: Link | Relation) -> str | None:
        """Bundle path an internal link points to; None if external, anchor-only or escaping the bundle."""
        return mdlinks.resolve(link.path, self.folder) if link.is_internal else None


def parse_document(path: Path, root: Path) -> Document:
    text = path.read_text(encoding="utf-8")
    if text.startswith("﻿"):
        text = text[1:]
    doc = Document(path=path, rel=PurePosixPath(path.relative_to(root).as_posix()), text=text)
    first, sep, _ = text.partition("\n")
    if first.rstrip("\r") != "---":
        return doc
    # Lines end at \n only: str.splitlines also splits on U+2028, \f and friends.
    offset, line_no = len(first) + len(sep), 1
    while sep and offset <= len(text):
        end = text.find("\n", offset)
        line = text[offset:] if end < 0 else text[offset:end]
        line_no += 1
        if line.rstrip("\r") == "---":
            doc.has_frontmatter = True
            raw = text[len(first) + 1 : offset]
            doc.fm_end = len(text) if end < 0 else end + 1
            doc.body_line_offset = line_no
            try:
                data = load_yaml(raw)
            except yaml.YAMLError as exc:
                doc.frontmatter_error = f"unparseable YAML frontmatter: {exc}".replace("\n", " ")
                return doc
            if data is None:
                data = {}
            if not isinstance(data, dict):
                doc.frontmatter_error = "frontmatter is not a YAML mapping"
                return doc
            doc.frontmatter = data
            return doc
        if end < 0:
            break
        offset = end + 1
    doc.frontmatter_error = "frontmatter block is not closed with '---'"
    return doc


def find_repo_root(start: Path | None = None) -> Path:
    env = os.environ.get("KB_REPO_ROOT")
    if env:
        return Path(env).resolve()
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "schema" / "vocabulary.yaml").is_file():
            return candidate
    raise SystemExit("kb: cannot find repo root (a directory containing schema/vocabulary.yaml)")


def bundle_dir(repo_root: Path) -> str:
    """The bundle's folder inside the repository: `[tool.kb] bundle` in pyproject.toml (default `kb`)."""
    try:
        data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return DEFAULT_BUNDLE_DIR
    name = ((data.get("tool") or {}).get("kb") or {}).get("bundle")
    return name.strip("/") if isinstance(name, str) and name.strip("/") else DEFAULT_BUNDLE_DIR


@dataclass
class Config:
    vocabulary: dict[str, Any]
    taxonomy: dict[str, Any]
    schema: dict[str, Any]

    @classmethod
    def load(cls, repo_root: Path) -> Config:
        schema_dir = repo_root / "schema"
        vocabulary = load_yaml((schema_dir / "vocabulary.yaml").read_text(encoding="utf-8")) or {}
        schema = json.loads((schema_dir / "frontmatter.schema.json").read_text(encoding="utf-8"))
        # The vocabulary extends the core frontmatter schema: every relation key
        # holds a list of markdown links, and `fields` adds instance-specific keys.
        properties = schema.setdefault("properties", {})
        for key in vocabulary.get("relations") or {}:
            properties.setdefault(key, {"$ref": "#/$defs/relation"})
        for key, spec in (vocabulary.get("fields") or {}).items():
            properties.setdefault(key, spec)
        return cls(
            vocabulary=vocabulary,
            taxonomy=load_yaml((schema_dir / "taxonomy.yaml").read_text(encoding="utf-8")) or {},
            schema=schema,
        )

    @property
    def types(self) -> dict[str, dict[str, Any]]:
        return self.vocabulary.get("types", {})

    @property
    def relations(self) -> dict[str, str]:
        return self.vocabulary.get("relations", {})

    @property
    def folders(self) -> dict[str, dict[str, Any]]:
        return self.taxonomy.get("folders", {}) or {}

    @property
    def domain_folders(self) -> set[str]:
        return {
            name
            for name, spec in self.folders.items()
            if "/" not in name and spec.get("group") == "Knowledge domains"
        }

    @property
    def personal_folders(self) -> set[str]:
        """Top-level folders owned by the human (groups "Personal" and "Vault")."""
        return {
            name
            for name, spec in self.folders.items()
            if "/" not in name and spec.get("group") in ("Personal", "Vault")
        }

    def folder_spec(self, folder: str) -> dict[str, Any] | None:
        """Taxonomy entry for a folder, synthesized for children of `auto_children` folders."""
        if folder in self.folders:
            return self.folders[folder]
        parent = str(PurePosixPath(folder).parent)
        parent_spec = self.folders.get(parent)
        if parent_spec and parent_spec.get("auto_children"):
            return {"title": PurePosixPath(folder).name, "description": "", "auto": True}
        return None

    def folder_sort(self, folder: str) -> str | None:
        path = PurePosixPath(folder)
        for candidate in (path, *path.parents):
            spec = self.folders.get(str(candidate))
            if spec and spec.get("sort"):
                return spec["sort"]
        return None


class Bundle:
    """An OKF bundle rooted at `root` (the bundle folder), with house config from `repo_root`.

    The bundle's files are the ones git would commit: in a git repository,
    tracked and untracked files that are not ignored (`tracked_only`: tracked
    and staged files only, what a commit contains); elsewhere, every file.
    Files below dot-folders (`.obsidian/`, `.trash/`) are never part of it.
    """

    def __init__(self, root: Path, repo_root: Path, tracked_only: bool = False):
        self.root = root.resolve()
        self.repo_root = repo_root.resolve()
        self.tracked_only = tracked_only
        self.config = Config.load(self.repo_root)
        # How the bundle folder is named in messages and accepted in path arguments, e.g. `kb`.
        self.prefix = (
            self.root.relative_to(self.repo_root).as_posix() if self.repo_root in self.root.parents else self.root.name
        )

    @classmethod
    def discover(cls, bundle: str | None = None, tracked_only: bool = False) -> Bundle:
        repo_root = find_repo_root()
        root = Path(bundle).resolve() if bundle else repo_root / bundle_dir(repo_root)
        if not root.is_dir():
            raise SystemExit(f"kb: bundle directory not found: {root}")
        return cls(root, repo_root, tracked_only)

    # -- files ---------------------------------------------------------------

    @cached_property
    def files(self) -> frozenset[str]:
        """Bundle-relative paths of every file of the bundle (not only .md), exact case."""
        listed = self._git_files()
        if listed is None and self.tracked_only:
            print("kb: warning: not a git work tree, so --tracked reads every file", file=sys.stderr)
        if not listed:
            # Not a git work tree, or git lists nothing: e.g. a knowledge base not yet
            # `git init`-ed inside another repository that ignores it. Read the disk then.
            walked = self._walk_files()
            if listed is None or (not self.tracked_only and any(rel.endswith(".md") for rel in walked)):
                listed = walked
        return frozenset(rel for rel in listed if not any(part.startswith(".") for part in rel.split("/")[:-1]))

    @cached_property
    def dirs(self) -> frozenset[str]:
        """Bundle-relative folders that hold a file of the bundle ('' is the root)."""
        out = {""}
        for rel in self.files:
            parent = posixpath.dirname(rel)
            while parent and parent not in out:
                out.add(parent)
                parent = posixpath.dirname(parent)
        return frozenset(out)

    def _git_files(self) -> list[str] | None:
        """`git ls-files` of the bundle folder, or None outside a git work tree."""
        inside = self.repo_root in self.root.parents
        cwd = self.repo_root if inside else self.root  # hooks may set a GIT_DIR relative to the top level
        prefix = f"{self.prefix}/" if inside else ""
        args = ["git", "ls-files", "-z", "--cached"]
        if not self.tracked_only:
            args += ["--others", "--exclude-standard"]
        try:
            result = _run_git(
                [*args, "--", f":(literal){prefix or '.'}"], cwd=cwd, capture_output=True, check=False, timeout=60
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        out = []
        for entry in result.stdout.decode("utf-8", "surrogateescape").split("\0"):
            if not entry or entry.endswith("/") or not entry.startswith(prefix):
                continue
            rel = entry[len(prefix) :]
            if os.path.isfile(self.root / rel):  # --cached also lists tracked files deleted from disk
                out.append(rel)
        return out

    def _walk_files(self) -> list[str]:
        out = []
        for folder, dirs, names in os.walk(self.root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            base = Path(folder).relative_to(self.root).as_posix()
            out += [name if base == "." else f"{base}/{name}" for name in names]
        return out

    def markdown_paths(self) -> list[Path]:
        """Every .md file of the bundle (see the class docstring for which files count)."""
        return sorted(self.root / rel for rel in self.files if rel.endswith(".md"))

    def invalidate(self) -> None:
        """Forget the file listing and parsed documents, after files were moved or deleted."""
        for name in ("files", "dirs", "documents", "by_rel"):
            self.__dict__.pop(name, None)

    def includes(self, path: Path) -> bool:
        """True if an absolute path is a file of the bundle (not ignored, not in a dot-folder)."""
        path = path.resolve()
        return self.root in path.parents and path.relative_to(self.root).as_posix() in self.files

    def exists(self, rel: str) -> bool:
        """True if a bundle-relative path is a file or folder of the bundle, with exactly this case."""
        return rel.strip("/") in self.files or rel.strip("/") in self.dirs

    # -- documents -----------------------------------------------------------

    @cached_property
    def documents(self) -> list[Document]:
        return [parse_document(p, self.root) for p in self.markdown_paths()]

    @cached_property
    def by_rel(self) -> dict[str, Document]:
        return {str(d.rel): d for d in self.documents}

    def concepts(self) -> list[Document]:
        return [d for d in self.documents if not d.is_reserved]

    def document(self, path: Path) -> Document:
        return parse_document(path.resolve(), self.root)

    def in_scope(self, doc: Document, scope: str = "knowledge") -> bool:
        """Is `doc` a page the analytics commands look at (graph, dupes, unlinked, report)?

        A page has valid frontmatter with a type, is not index.md/log.md or a
        Template, and is not below a `_` or `.` folder. The `knowledge` scope
        also leaves out the human's personal areas (taxonomy groups Personal
        and Vault); `all` keeps them.
        """
        if doc.is_reserved or doc.frontmatter_error or not doc.type or doc.type == "Template":
            return False
        if doc.in_tooling_folder:
            return False
        return scope == "all" or not (len(doc.rel.parts) > 1 and doc.rel.parts[0] in self.config.personal_folders)

    def pages(self, scope: str = "knowledge") -> dict[str, Document]:
        """Pages in scope (see `in_scope`), by bundle path."""
        return {str(d.rel): d for d in self.documents if self.in_scope(d, scope)}

    # -- paths ---------------------------------------------------------------

    def show(self, rel: object) -> str:
        """A bundle-relative path as the user sees it from the repository root, e.g. `kb/log.md`."""
        return f"{self.prefix}/{rel}"

    def rel(self, arg: str) -> str:
        """A bundle path argument, normalized: no leading `/` or bundle-folder prefix, `/` separators.

        `./a.md`, `a//b.md` and `a\\b.md` (Windows) all mean what they say; a
        path that leaves the bundle (`../x.md`) is refused. When the bundle
        also holds a folder named like the prefix (a domain `notes/` inside a
        bundle `notes/`), the reading inside the bundle wins if that path, or
        its folder, exists.
        """
        given = arg
        if "\\" in arg:
            arg = PureWindowsPath(arg).as_posix()
        arg = posixpath.normpath(arg.lstrip("/")) if arg.strip("/") else ""
        if arg == ".":
            arg = ""
        if arg == ".." or arg.startswith("../"):
            raise SystemExit(f"kb: {given} is outside the bundle")
        if not arg.startswith(self.prefix + "/"):
            return arg
        inside = self.root / arg
        if inside.exists() or inside.parent.is_dir():
            return arg
        return arg[len(self.prefix) + 1 :]

    def path_arg(self, arg: str) -> Path | None:
        """A command-line path: relative to the cwd, the repo, or the bundle (bundle-folder prefix optional).

        None unless it is a file of the bundle (ignored files and dot-folders are not).
        """
        candidates = [Path(arg), self.repo_root / arg, self.root / arg.lstrip("/")]
        try:
            candidates.append(self.root / self.rel(arg))
        except SystemExit:
            pass
        for candidate in candidates:
            candidate = candidate.resolve()
            if candidate.is_file():
                return candidate if self.includes(candidate) else None
        return None
