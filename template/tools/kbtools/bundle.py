"""Bundle model: locating files, parsing frontmatter, loading house config."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

RESERVED = {"index.md", "log.md"}
DEFAULT_BUNDLE_DIR = "kb"
TOUCHED = ".cache/kb-touched.txt"


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


class _Loader(yaml.SafeLoader):
    """SafeLoader that keeps timestamps as strings, so values round-trip verbatim."""


_Loader.yaml_implicit_resolvers = {
    key: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_yaml(text: str) -> Any:
    return yaml.load(text, Loader=_Loader)  # noqa: S506 - SafeLoader subclass


@dataclass
class Document:
    """One markdown file of the bundle."""

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

    @property
    def folder(self) -> str:
        parent = str(self.rel.parent)
        return "" if parent == "." else parent

    @property
    def type(self) -> str | None:
        value = self.frontmatter.get("type")
        return value.strip() if isinstance(value, str) and value.strip() else None

    @property
    def title(self) -> str:
        value = self.frontmatter.get("title")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return self.rel.stem.replace("-", " ").capitalize()

    @property
    def description(self) -> str:
        value = self.frontmatter.get("description")
        return " ".join(value.split()) if isinstance(value, str) else ""


def parse_document(path: Path, root: Path) -> Document:
    text = path.read_text(encoding="utf-8")
    if text.startswith("﻿"):
        text = text[1:]
    doc = Document(path=path, rel=PurePosixPath(path.relative_to(root).as_posix()), text=text)
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return doc
    offset = len(lines[0])
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip("\r\n") == "---":
            doc.has_frontmatter = True
            raw = "".join(lines[1:i])
            doc.fm_end = offset + len(line)
            doc.body_line_offset = i + 1
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
        offset += len(line)
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
    """An OKF bundle rooted at `root` (the bundle folder), with house config from `repo_root`."""

    def __init__(self, root: Path, repo_root: Path):
        self.root = root.resolve()
        self.repo_root = repo_root.resolve()
        self.config = Config.load(self.repo_root)
        # How the bundle folder is named in messages and accepted in path arguments, e.g. `kb`.
        self.prefix = (
            self.root.relative_to(self.repo_root).as_posix() if self.repo_root in self.root.parents else self.root.name
        )

    @classmethod
    def discover(cls, bundle: str | None = None) -> Bundle:
        repo_root = find_repo_root()
        root = Path(bundle).resolve() if bundle else repo_root / bundle_dir(repo_root)
        if not root.is_dir():
            raise SystemExit(f"kb: bundle directory not found: {root}")
        return cls(root, repo_root)

    def markdown_paths(self) -> list[Path]:
        """Every .md file in the tree, including dot-directories (OKF counts them too)."""
        return sorted(p for p in self.root.rglob("*.md") if p.is_file())

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

    def show(self, rel: object) -> str:
        """A bundle-relative path as the user sees it from the repository root, e.g. `kb/log.md`."""
        return f"{self.prefix}/{rel}"

    def rel(self, arg: str) -> str:
        """A bundle path argument without a leading `/` or bundle-folder prefix.

        When the bundle also holds a folder named like the prefix (a domain
        `notes/` inside a bundle `notes/`), the reading inside the bundle wins
        if that path, or its folder, exists.
        """
        arg = arg.lstrip("/")
        if not arg.startswith(self.prefix + "/"):
            return arg
        inside = self.root / arg
        if inside.exists() or inside.parent.is_dir():
            return arg
        return arg[len(self.prefix) + 1 :]

    def path_arg(self, arg: str) -> Path | None:
        """A command-line path: relative to the cwd, the repo, or the bundle (bundle-folder prefix optional)."""
        for candidate in (Path(arg), self.repo_root / arg, self.root / arg.lstrip("/"), self.root / self.rel(arg)):
            candidate = candidate.resolve()
            if candidate.is_file():
                return candidate if self.root in candidate.parents else None
        return None

    def exists(self, rel: str) -> bool:
        target = self.root / rel
        return target.is_file() or target.is_dir()
