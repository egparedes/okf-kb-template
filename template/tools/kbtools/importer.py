"""Deterministic import of an Obsidian vault or Logseq graph (`kb import`).

A mapping file (YAML) decides where each note goes, which type it gets and
what happens to each property; the converter does the rest the same way on
every run:

- wikilinks, aliased wikilinks and heading links become bundle-absolute
  markdown links; image embeds become `![](/…)`, note embeds become links;
- relative and vault-path markdown links are rebased onto the new paths;
- file and folder names become kebab-case (attachments keep their name when a
  `files` rule says `kebab: false`);
- the title comes from the first-line H1 (then removed, and the remaining
  headings promoted one level), the description from the first sentence;
- Logseq `key:: value` page properties become YAML frontmatter;
- block ids are removed and block references reduced to page links, both
  reported.

Nothing in the source is modified, and symbolic links in it are not followed.
`--dry-run` prints the plan and every issue without writing; a real run
refuses to start while the plan has errors, writes everything to a staging
folder first and moves it into place only when all of it was written.
The mapping format is documented in docs/importing.md.
"""

from __future__ import annotations

import functools
import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

import yaml

from .bundle import RESERVED, Bundle, load_yaml, record_touched
from .mdlinks import encode_path, find_links, mask_code, reference_definitions
from .names import slug
from .pages import CONTEXT_SUFFIX

ALWAYS_EXCLUDED = (".git/**", ".obsidian/**", ".trash/**", "logseq/**", "**/.DS_Store", ".*")
DEFAULT_MAX_BYTES = 2_000_000
GIT_TIMEOUT = 60  # seconds for the one `git log` pass over the source
# Fallback when the schema has no `$defs.actor.pattern`; keep in step with schema/frontmatter.schema.json.
ACTOR = r"^(human:[a-z0-9._-]+|process:[a-z0-9._-]+|[A-Za-z0-9._-]+/[A-Za-z0-9._:-]+)$"
_WIKILINK = re.compile(r"(?P<bang>!?)\[\[(?P<inner>[^\[\]\n]+?)\]\]")
_BLOCK_ID = re.compile(r"(?:^|[ \t]+)\^(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9-]+[ \t]*$", re.M)  # "r ^2" is not an id
_LIST_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]")
_MATH = re.compile(r"\$\$.+?\$\$|(?<![\\$])\$(?=\S)[^$\n]*?(?<=\S)\$(?!\d)", re.S)
_OBSIDIAN_COMMENT = re.compile(r"%%(?P<text>.*?)%%", re.S)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_INLINE_TAG = re.compile(r"(?<![\w/#&(\[])#(?P<tag>\[\[[^\]\n]+\]\]|[A-Za-z][\w/-]*)")
_HEX_COLOUR = re.compile(r"(?=[a-f]*\d)[0-9a-f]{3}(?:[0-9a-f]{3})?(?:[0-9a-f]{2})?", re.I)  # #ff0000, #0af
_LOGSEQ_PROP = re.compile(r"^(?P<key>[A-Za-z][\w-]*):: ?(?P<value>.*)$")
_LOGSEQ_BLOCK_PROP = re.compile(r"^[ \t]*(?:id|collapsed):: .*\n", re.M)
_FRONTMATTER = re.compile(r"---\n(?P<yaml>.*?\n)??---[ \t]*(?:\n|$)", re.S)
_PAGE_REF = re.compile(r"\[\[([^\[\]]*)\]\]")
WRITTEN_KEYS = ("status", "generated", "verified")  # set by the importer; a source value needs a rule
MAPPING_KEYS = {"label", "actor", "exclude", "notes", "files", "properties", "timestamp", "rewrite", "tags",
                "description_skip", "unresolved", "max_bytes", "links"}
RULE_KEYS = {"match", "to", "skip", "type", "title", "tags", "status", "alias_stem", "kebab"}
PROPERTY_KEYS = {"rename", "map", "relation", "target"}
TYPE_KEYS = {"from", "map", "default"}
TAG_KEYS = {"inline", "drop", "map"}
REWRITE_KEYS = {"pattern", "replace"}
_DATE = re.compile(r"(?P<y>\d{4})[-_](?P<m>\d{2})[-_](?P<d>\d{2})")
_HEADING = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<text>.*?)[ \t#]*$", re.M)
_SIZE = re.compile(r"^\d+(x\d+)?$")


# -- mapping ------------------------------------------------------------------


@functools.lru_cache(maxsize=None)
def glob_regex(pattern: str, ignore_case: bool = False) -> re.Pattern[str]:
    """`**` crosses folders, `*` and `?` do not; brackets are literal (vault names use them)."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z", re.I if ignore_case else 0)


def _matches(path: str, patterns: list[str] | tuple[str, ...], ignore_case: bool = False) -> bool:
    return any(glob_regex(p, ignore_case).match(path) for p in patterns)


def slugify_heading(text: str) -> str:
    """GitHub-style heading anchor."""
    text = re.sub(r"[`*_~]|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", text)
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def _fail(message: str) -> SystemExit:
    return SystemExit(f"kb import: {message}")


def _regex(pattern: Any, where: str, flags: int = 0) -> re.Pattern[str]:
    try:
        return re.compile(str(pattern), flags)
    except re.error as exc:
        raise _fail(f"invalid regex {str(pattern)!r} in `{where}`: {exc}") from None


def _check_keys(value: Any, allowed: set[str], where: str) -> None:
    if not isinstance(value, dict):
        raise _fail(f"`{where}` must be a mapping")
    unknown = sorted(set(map(str, value)) - allowed)
    if unknown:
        raise _fail(f"unknown key(s) {', '.join(unknown)} in `{where}` (allowed: {', '.join(sorted(allowed))})")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


@dataclass
class Mapping:
    actor: str
    label: str
    exclude: list[str]
    notes: list[dict[str, Any]]
    files: list[dict[str, Any]]
    properties: dict[str, Any]
    timestamp: str | None
    rewrite: list[tuple[re.Pattern[str], str]]
    tags: dict[str, Any]  # inline: collect|ignore, drop: compiled regexes, map: {old: new}
    description_skip: list[re.Pattern[str]]
    unresolved: str
    max_bytes: int
    links: dict[str, str]  # casefolded wikilink name -> bundle path as written in the mapping

    @classmethod
    def load(cls, path: Path, actor: str | None) -> Mapping:
        """Read and validate a mapping file; every mistake is a SystemExit naming the key."""
        data = load_yaml(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise _fail(f"{path} must be a YAML mapping")
        unknown = sorted(set(data) - MAPPING_KEYS)
        if unknown:
            raise _fail(f"unknown mapping key(s) {', '.join(unknown)} in {path}")
        for key, kind, name in (("notes", list, "a list of rules"), ("files", list, "a list of rules"),
                                ("properties", dict, "a mapping"), ("links", dict, "a mapping of name to bundle path"),
                                ("tags", dict, "a mapping"), ("timestamp", str, "a property name"),
                                ("label", str, "a string"), ("actor", str, "a string")):
            if data.get(key) is not None and not isinstance(data[key], kind):
                raise _fail(f"`{key}` must be {name}")
        properties = data.get("properties") or {}
        for key, spec in properties.items():
            if spec in ("keep", "drop"):
                continue
            if not isinstance(spec, dict):
                raise _fail(f"property `{key}` must be keep, drop, or a mapping")
            _check_keys(spec, PROPERTY_KEYS, f"properties.{key}")
            if "relation" in spec and not spec.get("target"):
                raise _fail(f"relation property `{key}` needs a `target`")
            if not isinstance(spec.get("map") or {}, dict):
                raise _fail(f"`properties.{key}.map` must be a mapping")
        actor = actor or data.get("actor")
        if not actor:
            raise _fail("set `actor` in the mapping or pass --by (e.g. human:<id>)")
        for rule in (data.get("notes") or []) + (data.get("files") or []):
            if not isinstance(rule, dict) or "match" not in rule or not (rule.get("skip") or rule.get("to")):
                raise _fail(f"every rule needs `match` and `to` (or `skip: true`): {rule!r}")
            if set(rule) - RULE_KEYS:
                raise _fail(f"unknown rule key(s) {', '.join(sorted(set(rule) - RULE_KEYS))} in {rule!r}")
            if isinstance(rule.get("type"), dict):
                _check_keys(rule["type"], TYPE_KEYS, f"type of rule {rule['match']!r}")
                if not isinstance(rule["type"].get("map") or {}, dict):
                    raise _fail(f"`type.map` of rule {rule['match']!r} must be a mapping")
            elif rule.get("type") is not None and not isinstance(rule["type"], str):
                raise _fail(f"`type` of rule {rule['match']!r} must be a type name or a mapping")
            if not all(isinstance(p, str) for p in _as_list(rule["match"])):
                raise _fail(f"`match` of rule {rule['match']!r} must be a glob or a list of globs")
        unresolved = data.get("unresolved", "text")
        if unresolved not in ("text", "wanted"):
            raise _fail("`unresolved` is `text` or `wanted`")
        tags = data.get("tags") or {}
        _check_keys(tags, TAG_KEYS, "tags")
        if tags.get("inline", "collect") not in ("collect", "ignore"):
            raise _fail("`tags.inline` is `collect` or `ignore`")
        if not isinstance(tags.get("map") or {}, dict):
            raise _fail("`tags.map` must be a mapping")
        rewrite = []
        for i, rule in enumerate(_as_list(data.get("rewrite"))):
            _check_keys(rule, REWRITE_KEYS, f"rewrite[{i}]")
            if "pattern" not in rule:
                raise _fail(f"`rewrite[{i}]` needs a `pattern`")
            rewrite.append((_regex(rule["pattern"], f"rewrite[{i}].pattern", re.M | re.S), str(rule.get("replace") or "")))
        try:
            max_bytes = int(data.get("max_bytes") or DEFAULT_MAX_BYTES)
        except (TypeError, ValueError):
            raise _fail("`max_bytes` must be a number of bytes") from None
        return cls(
            actor=str(actor),
            label=str(data.get("label") or path.stem),
            exclude=[str(p) for p in _as_list(data.get("exclude"))],
            notes=list(data.get("notes") or []),
            files=list(data.get("files") or []),
            properties=dict(properties),
            timestamp=data.get("timestamp"),
            rewrite=rewrite,
            tags={
                "inline": tags.get("inline", "collect"),
                "drop": [_regex(p, f"tags.drop[{i}]") for i, p in enumerate(_as_list(tags.get("drop")))],
                "map": dict(tags.get("map") or {}),
            },
            description_skip=[_regex(p, f"description_skip[{i}]") for i, p in enumerate(_as_list(data.get("description_skip")))],
            unresolved=unresolved,
            max_bytes=max_bytes,
            links={str(k).casefold(): "/" + str(v).strip("/") for k, v in (data.get("links") or {}).items()},
        )


def check_actor(bundle: Bundle, actor: str) -> str:
    """The actor as written to `generated.by`; it must match the schema's `$defs.actor` pattern.

    A context-window suffix on the model is dropped first, as `kb new` does:
    `claude-code/claude-opus-5-5[1m]` -> `claude-code/claude-opus-5-5`.
    """
    if "/" in actor:
        actor = CONTEXT_SUFFIX.sub("", actor)
    pattern = ((bundle.config.schema.get("$defs") or {}).get("actor") or {}).get("pattern") or ACTOR
    if not re.fullmatch(pattern, actor):
        raise _fail(f"actor `{actor}` is not valid: use human:<id>, process:<id> or <agent>/<model> (pattern {pattern})")
    return actor


# -- plan ---------------------------------------------------------------------


@dataclass
class Item:
    src: str  # source-relative posix path
    dest: str | None = None  # bundle-relative path
    rule: dict[str, Any] = field(default_factory=dict)
    note: bool = True
    title: str = ""
    type: str = ""
    reason: str = ""  # why it is skipped


@dataclass
class Note:
    """A source note read once: properties and body after the `rewrite` rules and Logseq block properties."""

    props: dict[str, Any]
    body: str  # without the first-line H1 (headings promoted when it was removed)
    h1: str | None
    problem: str | None  # unparseable frontmatter and the like, reported once


@dataclass
class Plan:
    source: Path
    into: str
    mapping: Mapping
    items: dict[str, Item] = field(default_factory=dict)  # every non-hidden source file
    errors: list[str] = field(default_factory=list)
    issues: list[tuple[str, str]] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)  # dest -> text (notes) or "" (copied files)
    names: dict[str, list[str]] | None = None  # wikilink name index, built on first use
    prefix: str = "kb"  # the bundle folder, for display
    actor: str = ""  # generated.by, after check_actor
    links: dict[str, str] = field(default_factory=dict)  # mapping `links`, as bundle paths
    notes: dict[str, Note] = field(default_factory=dict)  # parsed source notes by src
    by_dest: dict[str, Item] = field(default_factory=dict)  # imported items by dest
    commit_times: dict[str, str] | None = None  # src -> last commit time, from one git log

    @property
    def imported(self) -> list[Item]:
        return [i for i in self.items.values() if i.dest]

    def issue(self, src: str, message: str) -> None:
        self.issues.append((src, message))


def _format(template: str, values: dict[str, str]) -> str:
    try:
        return template.format_map(values)
    except KeyError as exc:
        raise ValueError(f"placeholder {exc} is not available for this file") from None
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"`{template}` is not a valid template ({exc})") from None


def _render(template: str, src: str, into: str, kebab_names: bool = True) -> str:
    path = PurePosixPath(src)
    date = _DATE.search(path.stem) or _DATE.search(src)
    values = {
        "path": str(path.with_suffix("")),
        "dir": "" if str(path.parent) == "." else str(path.parent),
        "parent": "" if str(path.parent) == "." else path.parent.name,
        "stem": path.stem,
        "name": path.name,
        "ext": path.suffix.lstrip("."),
    }
    if date:
        values.update(date=f"{date['y']}-{date['m']}-{date['d']}", yyyy=date["y"], mm=date["m"], dd=date["d"])
    rendered = _format(template, values)
    absolute = template.startswith("/")  # an empty {dir} must not make a path absolute
    parts = [p for p in rendered.split("/") if p]
    if kebab_names and parts:
        *dirs, last = parts
        stem, dot, ext = last.rpartition(".") if "." in last.lstrip(".") else (last, "", "")
        parts = [slug(d) for d in dirs] + [slug(stem) + (dot + ext.lower() if dot else "")]
    if not parts or any(not p for p in parts):
        raise ValueError(f"`{template}` renders an empty name")
    joined = "/".join(parts)
    return posixpath.normpath(joined if absolute or not into else posixpath.join(into, joined))


def _first_rule(rules: list[dict[str, Any]], src: str) -> dict[str, Any] | None:
    for rule in rules:
        if _matches(src, [str(p) for p in _as_list(rule["match"])]):
            return rule
    return None


def _scan(source: Path) -> list[tuple[str, str]]:
    """(source path, reason it cannot be imported or "") for every visible file; symlinks are never followed."""
    found = []

    def unreadable(exc: OSError) -> None:
        name = Path(exc.filename or source)
        rel = name.relative_to(source).as_posix() if name != source and source in name.parents else "."
        found.append((rel, f"folder not readable: {exc.strerror or exc}"))

    for folder, dirs, files in os.walk(source, onerror=unreadable):  # does not descend into symlinked folders
        base = Path(folder)
        rel = base.relative_to(source).as_posix()
        for name in sorted(dirs):
            if name.startswith("."):
                dirs.remove(name)
            elif (base / name).is_symlink():
                found.append((posixpath.join(rel, name).removeprefix("./"), "symbolic link: not followed"))
        for name in files:
            path = base / name
            reason = "symbolic link: not followed" if path.is_symlink() else "" if path.is_file() else "not a regular file"
            found.append((posixpath.join(rel, name).removeprefix("./"), reason))
    return sorted(found)


def build_plan(bundle: Bundle, source: Path, into: str, mapping: Mapping) -> Plan:
    source = source.resolve()
    if not source.is_dir():
        raise _fail(f"{source} is not a directory")
    actor = check_actor(bundle, mapping.actor)
    into = bundle.rel(into).strip("/")
    plan = Plan(source=source, into=into, mapping=mapping, prefix=bundle.prefix, actor=actor)
    plan.links = {name: "/" + bundle.rel(target) for name, target in mapping.links.items()}
    for src, problem in _scan(source):
        if _matches(src, ALWAYS_EXCLUDED, ignore_case=True) or any(p.startswith(".") for p in PurePosixPath(src).parts):
            continue
        item = Item(src=src, note=src.lower().endswith(".md"))
        plan.items[src] = item
        if _matches(src, mapping.exclude, ignore_case=True) or (problem and _matches(src + "/", mapping.exclude, ignore_case=True)):
            item.reason = "excluded by the mapping"
            continue
        if problem:
            item.reason = problem
            if problem.startswith("symbolic"):
                plan.issue(src, "symbolic link: not followed (copy the file into the source to import it)")
            else:
                plan.issue(src, problem)
            continue
        rule = _first_rule(mapping.notes if item.note else mapping.files, src)
        if rule is None:
            item.reason = "no rule matches" if item.note else "attachment (copied only if a note links it)"
            continue
        if rule.get("skip"):
            item.reason = "skipped by a rule"
            continue
        _assign(plan, item, rule)
    _linked_attachments(plan)
    _check_destinations(bundle, plan)
    plan.by_dest = {i.dest: i for i in plan.imported if i.dest}
    return plan


def _check_destinations(bundle: Bundle, plan: Plan) -> None:
    """Collisions (also by case, and file-versus-folder), existing files, reserved names, escapes."""
    seen: dict[str, Item] = {}
    folders: dict[str, Item] = {}  # casefolded folder of some destination -> an item inside it
    listings: dict[Path, dict[str, str]] = {}
    root = bundle.root.resolve()
    for item in plan.imported:
        dest = item.dest or ""
        name = PurePosixPath(dest).name
        if item.note and name in RESERVED:
            plan.errors.append(f"{item.src}: `{name}` is reserved in OKF; map it to another name")
        other = seen.setdefault(dest.casefold(), item)
        if other is not item:
            if other.dest == dest:
                plan.errors.append(f"{item.src} and {other.src} both map to {bundle.show(dest)}")
            else:
                plan.errors.append(f"{item.src} and {other.src} map to {bundle.show(dest)} and "
                                   f"{bundle.show(other.dest)}, which differ only in case (one file on macOS and Windows)")
        for parent in PurePosixPath(dest).parents:
            if str(parent) != ".":
                folders.setdefault(str(parent).casefold(), item)
        if root not in (bundle.root / dest).resolve().parents:
            plan.errors.append(f"{item.src}: {bundle.show(dest)} is outside the bundle")
            continue
        target = bundle.root / dest
        if target.exists():
            plan.errors.append(f"{item.src}: {bundle.show(dest)} already exists")
            continue
        for parent in reversed(PurePosixPath(dest).parents[:-1]):
            if (bundle.root / parent).exists() and not (bundle.root / parent).is_dir():
                plan.errors.append(f"{item.src}: {bundle.show(parent)} is a file, not a folder")
                break
        if target.parent.is_dir():  # a case-only twin on a case-sensitive disk
            if target.parent not in listings:
                listings[target.parent] = {c.name.casefold(): c.name for c in target.parent.iterdir()}
            twin = listings[target.parent].get(name.casefold())
            if twin:
                plan.errors.append(f"{item.src}: {bundle.show(dest)} differs only in case from the existing {twin}")
    for item in plan.imported:
        inside = folders.get((item.dest or "").casefold())
        if inside:
            plan.errors.append(f"{item.src}: {bundle.show(item.dest)} is also the folder of {inside.src}'s destination")


def _assign(plan: Plan, item: Item, rule: dict[str, Any]) -> None:
    template = str(rule["to"])
    if item.note and not template.casefold().endswith((".md", "{name}")):
        template += ".md"  # before kebab-casing, so `v1.2 notes` is not read as an extension
    try:
        item.dest = _render(template, item.src, plan.into, kebab_names=rule.get("kebab", True))
    except ValueError as exc:
        plan.errors.append(f"{item.src}: {exc}")
        return
    item.rule = rule
    size = (plan.source / item.src).stat().st_size
    if not item.note and size > plan.mapping.max_bytes:
        plan.issue(item.src, f"not copied: {size // 1000} kB is above max_bytes; reference it with a file: locator")
        item.dest, item.reason = None, "too large"


def _strings(value: Any) -> list[str]:
    """Every string in a property value (lists and mappings included)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _linked_attachments(plan: Plan) -> None:
    """Attachments without a rule are copied to <into>/assets/ when an imported note links them."""
    wanted: set[str] = set()
    for item in [i for i in plan.imported if i.note]:
        note = parse_note(plan, item)
        texts = [mask_code(note.body)] + _strings(note.props)
        for text in texts:
            for m in _WIKILINK.finditer(text):
                target = _resolve_name(plan, _wikilink_name(m), item.src)
                if target:
                    wanted.add(target)
        for link in find_links(note.body):
            if not link.is_external and link.path:
                target = _resolve_path(plan, link.path, item.src)
                if target:
                    wanted.add(target)
    for src in sorted(wanted):
        item = plan.items[src]
        if item.note or item.dest is not None or not item.reason.startswith("attachment"):
            continue
        if not _is_image(src):  # documents stay in their system of record
            item.reason = "linked document: add a `files` rule to copy it, or reference it with a file: locator"
            continue
        _assign(plan, item, {"match": src, "to": "assets/{name}"})
        if item.dest:
            item.reason = ""


# -- resolution ---------------------------------------------------------------


def _wikilink_name(m: re.Match[str]) -> str:
    return m.group("inner").replace("\\|", "|").split("|")[0].split("#")[0]


def _resolve_path(plan: Plan, link_path: str, from_src: str) -> str | None:
    """Source file a markdown link points to (`link_path` already unquoted).

    Relative to the note, then to the vault root, then, for a bare file name,
    anywhere in the vault (Obsidian's "shortest path" style).
    """
    folder = posixpath.dirname(from_src)
    for candidate in (posixpath.normpath(posixpath.join(folder, link_path)), posixpath.normpath(link_path.lstrip("/"))):
        for variant in (candidate, candidate + ".md"):
            if variant in plan.items:
                return variant
    if "/" not in link_path:
        return _resolve_name(plan, link_path, from_src)
    return None


def _name_index(plan: Plan) -> dict[str, list[str]]:
    """Every name a wikilink may use for a file: its path, each path suffix, with and without `.md`."""
    if plan.names is None:
        plan.names = {}
        for src in plan.items:
            key = src.casefold()
            parts = key.split("/")
            forms = {"/".join(parts[i:]) for i in range(len(parts))}
            forms |= {f.removesuffix(".md") for f in forms if f.endswith(".md")}
            stem = PurePosixPath(key).stem if key.endswith(".md") else None
            if stem and "___" in stem:
                forms.add(stem.replace("___", "/"))  # Logseq namespaces: a___b.md is page a/b
            for form in forms:
                plan.names.setdefault(form, []).append(src)
    return plan.names


def _resolve_name(plan: Plan, name: str, from_src: str) -> str | None:
    """Source file a wikilink names, the way Obsidian and Logseq resolve it."""
    name = name.strip()
    if not name:
        return None
    folder = posixpath.dirname(from_src)
    if name.startswith(("./", "../")):
        relative = posixpath.normpath(posixpath.join(folder, name))
        for variant in (relative, relative + ".md"):
            if variant in plan.items:
                return variant
    hits = _name_index(plan).get(name.casefold().lstrip("/"), [])
    if not hits:
        return None
    return min(hits, key=lambda s: (posixpath.dirname(s) != folder, not s.endswith(".md"), s.count("/"), s))


# -- reading notes ------------------------------------------------------------


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str, str | None]:
    """YAML frontmatter or Logseq page properties, and the rest of the note."""
    m = _FRONTMATTER.match(text)
    if m:
        rest = text[m.end() :]
        try:
            data = load_yaml(m.group("yaml") or "") or {}
        except yaml.YAMLError as exc:
            return {}, rest, f"unparseable frontmatter dropped: {exc}".replace("\n", " ")
        return (data, rest, None) if isinstance(data, dict) else ({}, rest, "non-mapping frontmatter dropped")
    props: dict[str, Any] = {}
    lines = text.splitlines(keepends=True)
    count = 0
    for line in lines:
        m = _LOGSEQ_PROP.match(line.rstrip("\n"))
        if not m:
            break
        count += 1
        value = m.group("value").strip()
        key = m.group("key")
        if key in ("id", "collapsed"):  # block properties of the first block, not page properties
            continue
        if key in ("tags", "alias", "aliases"):
            props[key] = [_PAGE_REF.sub(r"\1", v.strip()).lstrip("#") for v in value.split(",") if v.strip()]
        else:
            props[key] = _PAGE_REF.sub(r"\1", value).lstrip("#")  # `type:: [[guide]]` is the value guide
    return props, "".join(lines[count:]), None


def _title_from_h1(body: str) -> tuple[str | None, str]:
    stripped = body.lstrip("\n")
    m = re.match(r"# (?P<title>[^\n]+?)[ \t#]*(?:\n|$)", stripped)
    if not m:
        return None, body
    return m.group("title").strip(), stripped[m.end() :].lstrip("\n")


def _promote_headings(body: str) -> str:
    masked = mask_code(body)
    headings = list(_HEADING.finditer(masked))
    if not headings or any(len(h.group("hashes")) == 1 for h in headings):
        return body
    for h in reversed(headings):
        body = body[: h.start()] + body[h.start() + 1 :]
    return body


def parse_note(plan: Plan, item: Item) -> Note:
    """A source note, read and split once per run (cached on the plan)."""
    note = plan.notes.get(item.src)
    if note is None:
        with _open_source(plan, item) as handle:
            text = handle.read().decode("utf-8", errors="replace").replace("\r\n", "\n")
        props, body, problem = _split_frontmatter(text.removeprefix("﻿"))
        for pattern, replace in plan.mapping.rewrite:
            body = pattern.sub(replace, body)
        for m in reversed(list(_LOGSEQ_BLOCK_PROP.finditer(mask_code(body)))):
            body = body[: m.start()] + body[m.end() :]
        h1, rest = _title_from_h1(body)
        note = plan.notes[item.src] = Note(props, _promote_headings(rest) if h1 is not None else body, h1, problem)
    return note


def _title(item: Item, note: Note) -> str:
    """Rule `title` template, else the first-line H1, else a `title` property, else the file stem."""
    path = PurePosixPath(item.src)
    if item.rule.get("title"):
        date = _DATE.search(path.stem) or _DATE.search(item.src)
        values = {"stem": path.stem, "parent": path.parent.name}
        if date:
            values["date"] = f"{date['y']}-{date['m']}-{date['d']}"
        return _format(str(item.rule["title"]), values)
    if note.h1:
        return _plain(note.h1)
    title = note.props.get("title")
    return _plain(str(title)) if title else path.stem.replace("___", "/")


def _unlink(text: str) -> str:
    """Wikilinks reduced to their text: `[[Note|shown]]` -> `shown`."""
    return re.sub(r"!?\[\[([^\]|]*\|)?([^\]]*)\]\]", r"\2", text)


def _plain(text: str) -> str:
    text = _HTML_COMMENT.sub("", _OBSIDIAN_COMMENT.sub("", text))
    text = _unlink(text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`|\*\*|__|~~", "", text)
    return " ".join(text.split())


def _without_comments(body: str) -> str:
    """HTML comments (converted `%% %%` included) removed; their line breaks kept."""
    masked = mask_code(body)  # blanks comments and code: a match that is blank there is a comment outside code
    for m in reversed(list(_HTML_COMMENT.finditer(body))):
        if not masked[m.start() : m.end()].strip():
            body = body[: m.start()] + "\n" * body.count("\n", m.start(), m.end()) + body[m.end() :]
    return body


def _description(body: str, skip: list[re.Pattern[str]]) -> str | None:
    """First sentence of the first prose paragraph (hard-wrapped lines joined); comments never count."""
    body = _without_comments(body)
    masked = mask_code(body).split("\n")  # lines end at \n only, in both texts
    paragraph: list[str] = []
    for original, blanked in zip(body.split("\n"), masked, strict=False):
        line = original.strip()
        structural = not blanked.strip() or line.startswith(("#", "|", ">", "<", "---", "![", "```", "~~~"))
        skipped = any(p.search(line) for p in skip)
        if paragraph and (structural or skipped or _LIST_ITEM.match(line)):
            break
        if structural or skipped:
            continue
        paragraph.append(re.sub(r"^(?:[-*+]|\d+[.)])\s+(?:\[.\]\s+)?", "", line))
        if len(" ".join(paragraph)) > 400:
            break
    plain = _plain(" ".join(paragraph))
    if len(plain) < 12:
        return None
    sentence = re.split(r"(?<=[.!?])\s", plain, maxsplit=1)[0]
    if len(sentence) > 200:
        sentence = sentence[:200].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return sentence


def _mask_math(masked: str) -> str:
    """Blank out `$$…$$` and `$…$` math (already code-masked text), preserving offsets."""
    return _MATH.sub(_blank, masked)


def _blank(m: re.Match[str]) -> str:
    return "".join(c if c == "\n" else " " for c in m.group(0))


def _block_ids(masked: str) -> list[tuple[int, int]]:
    """Spans of Obsidian block ids: `^id` ending the last line of a paragraph or list item, or on its own line after one."""
    spans = []
    for m in _BLOCK_ID.finditer(masked):
        line_start = masked.rfind("\n", 0, m.start()) + 1
        next_line = masked[m.end() + 1 :].split("\n", 1)[0] if m.end() < len(masked) else ""
        if masked[line_start : m.start()].strip():
            if not next_line.strip() or _LIST_ITEM.match(next_line):  # the end of the block
                spans.append((m.start(), m.end()))
        else:
            previous = masked[: max(line_start - 1, 0)].rsplit("\n", 1)[-1]
            if line_start and previous.strip():  # `^id` on its own line, after a table or quote
                spans.append((line_start, min(m.end() + 1, len(masked))))
    return spans


# -- conversion ---------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(instant: datetime) -> str:
    return min(instant.astimezone(timezone.utc), _now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _commit_times(plan: Plan) -> dict[str, str]:
    """Last commit time of every file under the source, from one `git log` pass (empty without git)."""
    if plan.commit_times is None:
        plan.commit_times = {}
        try:
            git = subprocess.run(
                ["git", "-c", "core.quotepath=off", "log", "--relative", "--format=%x01%cI", "-z", "--name-only", "--", "."],
                cwd=plan.source, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=GIT_TIMEOUT, check=False,
            )
        except subprocess.TimeoutExpired:
            plan.issue(".", f"`git log` took more than {GIT_TIMEOUT} s: used file modification times")
            return plan.commit_times
        except OSError:
            return plan.commit_times  # no git: use the file times
        if git.returncode == 0:
            current = None
            for token in git.stdout.split("\0"):
                token = token.lstrip("\n")
                if token.startswith("\x01"):
                    current = token[1:]
                elif token and current:
                    plan.commit_times.setdefault(token, current)  # newest first
    return plan.commit_times


def _timestamp(plan: Plan, item: Item, props: dict[str, Any]) -> str:
    key = plan.mapping.timestamp
    value = props.get(key) if key else None
    if value:
        text = str(value).strip()
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                return _iso(datetime.fromisoformat(text + "T00:00:00+00:00"))
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return _iso(parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc))
        except ValueError:
            plan.issue(item.src, f"`{key}: {text}` is not a date; used the file time")
    committed = _commit_times(plan).get(item.src)
    if committed:
        try:
            return _iso(datetime.fromisoformat(committed))
        except ValueError:
            pass
    return _iso(datetime.fromtimestamp((plan.source / item.src).stat().st_mtime, timezone.utc))


def _yaml_flow_scalar(text: str) -> str:
    """`text` as a scalar inside a YAML flow mapping: plain when that reads back unchanged, else quoted."""
    try:
        if load_yaml(f"{{v: {text}}}") == {"v": text}:
            return text
    except yaml.YAMLError:
        pass
    return json.dumps(text)  # a JSON string is a valid double-quoted YAML scalar


def emit(fm: dict[str, Any], actor: str, at: str, body: str) -> str:
    """The page text: frontmatter dumped by yaml, `generated` last in flow style."""
    header = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=1000)
    header += f"generated: {{ by: {_yaml_flow_scalar(actor)}, at: {at} }}\n"
    return f"---\n{header}---\n\n{body.strip()}\n"


class _Converter:
    """Turns one parsed source note into a bundle page: body links, then frontmatter."""

    def __init__(self, plan: Plan):
        self.plan = plan
        self.by_src = plan.items

    # links

    def link_target(self, src: str, fragment: str, from_item: Item, raw: str, fallback: str = "kept as text") -> str | None:
        item = self.by_src[src]
        if not item.dest:
            why = "an excluded note" if item.reason == "excluded by the mapping" else f"a file that is not imported ({item.reason})"
            self.plan.issue(from_item.src, f"`{raw}` points to {why}: {fallback}")
            return None
        if fragment.startswith("^"):
            self.plan.issue(from_item.src, f"`{raw}`: block reference reduced to a page link")
            fragment = ""
        elif fragment:
            fragment = slugify_heading(unquote(fragment).split("#")[-1])  # [[Note#A#B]] targets heading B
        target = "/" + encode_path(item.dest)
        return f"{target}#{fragment}" if fragment else target

    def wikilink(self, m: re.Match[str], item: Item) -> str:
        raw = m.group(0)
        inner = m.group("inner").replace("\\|", "|")
        target, _, alias = inner.partition("|")
        name, _, fragment = target.partition("#")
        embed = bool(m.group("bang"))
        text = alias.strip() if alias and not (embed and _SIZE.match(alias.strip())) else ""
        if not name.strip():  # [[#Heading]] inside the same note
            heading = fragment.split("#")[-1]
            anchor = "" if fragment.startswith("^") else slugify_heading(heading)
            return f"[{text or heading}](#{anchor})" if anchor else (text or fragment.lstrip("^"))
        heading = fragment.split("#")[-1]
        shown = name.strip().rsplit("/", 1)[-1] if name.strip().startswith(("./", "../")) else name.strip()
        display = text or (f"{shown} › {heading}" if fragment and not fragment.startswith("^") else shown)
        src = _resolve_name(self.plan, name, item.src)
        href = self.link_target(src, fragment, item, raw) if src else None
        if src is None and name.strip().casefold() in self.plan.links:
            return f"[{display}]({encode_path(self.plan.links[name.strip().casefold()])})"
        if href is None:
            if src is None:
                if self.plan.mapping.unresolved == "wanted" and not embed and slug(name):
                    wanted = "/" + encode_path(posixpath.join(self.plan.into, slug(name) + ".md"))
                    self.plan.issue(item.src, f"`{raw}` names no file: linked as wanted page {wanted}")
                    return f"[{display}]({wanted})"
                self.plan.issue(item.src, f"`{raw}` names no file: kept as text")
            return display
        if embed:
            if src.endswith(".md"):
                self.plan.issue(item.src, f"`{raw}`: note embed replaced by a link")
                return f"[{display}]({href})"
            alt = text or PurePosixPath(src).stem
            return f"![{alt}]({href})" if _is_image(src) else f"[{display}]({href})"
        return f"[{display}]({href})"

    def links_in(self, value: Any, item: Item) -> Any:
        """Wikilinks inside a property value, converted like those in the body."""
        if isinstance(value, str) and "[[" in value:
            return _WIKILINK.sub(lambda m: self.wikilink(m, item), value)
        if isinstance(value, list):
            return [self.links_in(v, item) for v in value]
        if isinstance(value, dict):
            return {k: self.links_in(v, item) for k, v in value.items()}
        return value

    # the note

    def convert(self, item: Item) -> str:
        note = parse_note(self.plan, item)
        if note.problem:
            self.plan.issue(item.src, note.problem)
        tags = self.tags(note.props, note.body, item)
        body = self.convert_body(note.body, item)
        if not body.strip():
            self.plan.issue(item.src, "empty note: imported as a stub")
        fm = self.frontmatter(item, note.props, body, tags)
        item.type = fm["type"]
        return emit(fm, self.plan.actor, _timestamp(self.plan, item, note.props), body)

    def frontmatter(self, item: Item, props: dict[str, Any], body: str, tags: list[str]) -> dict[str, Any]:
        fm: dict[str, Any] = {"type": self.type_of(item, props), "title": item.title}
        fm["description"] = self.description(item, props, body)
        aliases = self.aliases(item, props)
        if aliases:
            fm["aliases"] = aliases
        fm["tags"] = tags
        fm["status"] = item.rule.get("status", "draft")
        self.properties(fm, item, props)
        return {k: v for k, v in fm.items() if k == "tags" or v not in (None, [], "")}

    def description(self, item: Item, props: dict[str, Any], body: str) -> str:
        given = props.get("description")
        description = _plain(given) if isinstance(given, str) else None
        description = description or _description(body, self.plan.mapping.description_skip)
        if not description:
            self.plan.issue(item.src, "no prose for a description: wrote a placeholder")
            description = f"{item.title}, imported from {self.plan.mapping.label}."
        return description

    def aliases(self, item: Item, props: dict[str, Any]) -> list[str]:
        aliases = [str(a) for key in ("aliases", "alias") for a in _as_list(props.get(key))]
        stem = PurePosixPath(item.src).stem
        generic = {"readme", "index", "untitled", PurePosixPath(item.dest or "").stem, item.title.casefold()}
        if item.rule.get("alias_stem", True) and stem.casefold() not in generic:
            aliases.append(stem)
        return list(dict.fromkeys(a for a in aliases if a))

    def properties(self, fm: dict[str, Any], item: Item, props: dict[str, Any]) -> None:
        specs = self.plan.mapping.properties
        for key, value in props.items():
            if key in ("type", "title", "description", "tags", "tag", "aliases", "alias") and key not in specs:
                continue
            spec = specs.get(key)
            if key in WRITTEN_KEYS and not (
                spec == "drop" or (isinstance(spec, dict) and spec.get("rename", key) not in WRITTEN_KEYS)
            ):
                self.plan.errors.append(f"{item.src}: property `{key}` would clash with the `{key}` the importer writes; add a `drop` or `rename` rule")
                continue
            self.property(fm, key, value, item)

    def type_of(self, item: Item, props: dict[str, Any]) -> str:
        spec = item.rule.get("type")
        if isinstance(spec, dict):
            value = props.get(spec.get("from", "type"))
            mapped = (spec.get("map") or {}).get(str(value)) if value is not None else None
            if mapped:
                return str(mapped)
            if not spec.get("default"):
                self.plan.errors.append(f"{item.src}: no type for `{spec.get('from', 'type')}: {value}` and no default")
                return "?"
            return str(spec["default"])
        if not spec:
            self.plan.errors.append(f"{item.src}: rule `{item.rule['match']}` has no `type`")
            return "?"
        return str(spec)

    def property(self, fm: dict[str, Any], key: str, value: Any, item: Item) -> None:
        spec = self.plan.mapping.properties.get(key, "keep")
        if spec == "drop":
            return
        if spec == "keep":
            fm.setdefault(key, self.links_in(value, item))
            return
        if "relation" in spec:
            links = [link for entry in _as_list(value) if (link := self.relation_link(key, spec, entry, item))]
            if links:
                fm[spec["relation"]] = fm.get(spec["relation"], []) + links
            return
        values = spec.get("map") or {}
        value = values.get(value, value) if isinstance(value, str) else value
        fm[spec.get("rename", key)] = self.links_in(value, item)

    def relation_link(self, key: str, spec: dict[str, Any], entry: Any, item: Item) -> str | None:
        """`[Title](/target.md)` for one relation value: a wikilink to an imported note, else the `target` template."""
        text = str(entry).strip()
        dest = None
        m = _WIKILINK.fullmatch(text)
        if m:
            text = _wikilink_name(m).strip()
            src = _resolve_name(self.plan, text, item.src)
            target = self.by_src.get(src) if src else None
            if target and target.note and target.dest:
                dest = target.dest
        if dest is None:
            value = slug(text)
            if not value:
                self.plan.errors.append(f"{item.src}: relation `{key}`: value `{entry}` gives an empty name")
                return None
            try:
                dest = _render(str(spec["target"]).replace("{value}", value), item.src, self.plan.into)
            except ValueError as exc:
                self.plan.errors.append(f"{item.src}: relation `{key}`: {exc}")
                return None
        known = self.plan.by_dest.get(dest)
        return f"[{(known.title if known and known.title else None) or text}](/{encode_path(dest)})"

    def tags(self, props: dict[str, Any], body: str, item: Item) -> list[str]:
        options = self.plan.mapping.tags
        found = []
        for key in ("tags", "tag"):
            value = props.get(key)
            values = re.split(r"[,\s]+", value) if isinstance(value, str) else _as_list(value)  # `tags: a, b`
            found += [str(v).lstrip("#") for v in values if str(v).strip("#")]
        if options["inline"] == "collect":
            for m in _INLINE_TAG.finditer(_mask_math(mask_code(body))):
                if not _HEX_COLOUR.fullmatch(m.group("tag")):
                    found.append(m.group("tag").strip("[]"))
        out = []
        for tag in found:
            tag = str(options["map"].get(tag, tag))
            if not tag or any(p.search(tag) for p in options["drop"]):
                continue
            value = slug(tag.replace("/", "-"))
            if value and value not in out:
                out.append(value)
        return out + [t for t in _as_list(item.rule.get("tags")) if t not in out]

    def convert_body(self, body: str, item: Item) -> str:
        masked = mask_code(body)
        edits: list[tuple[int, int, str]] = []
        for m in _OBSIDIAN_COMMENT.finditer(masked):  # %% in code (e.g. ${x%%.*}) is masked out
            edits += [(m.start(), m.start() + 2, "<!--"), (m.end() - 2, m.end(), "-->")]
        for m in _WIKILINK.finditer(masked):
            edits.append((m.start(), m.end(), self.wikilink(m, item)))
        taken = [(s, e) for s, e, _ in edits]
        for link in find_links(masked):
            if link.is_external or link.is_anchor_only or not link.path:
                continue
            if any(s <= link.start < e for s, e in taken):
                continue
            src = _resolve_path(self.plan, link.path, item.src)
            if src is None:
                self.plan.issue(item.src, f"link `{link.target}` points to no file in the source: left as is")
                continue
            href = self.link_target(src, link.fragment, item, link.target, fallback="left as is")
            if href:
                edits.append((link.start, link.end, href))
        for start, end in _block_ids(_mask_math(_OBSIDIAN_COMMENT.sub(_blank, masked))):
            edits.append((start, end, ""))
            self.plan.issue(item.src, f"block id `{body[start:end].strip()}` removed")
        for start, end, new in sorted(edits, reverse=True):
            body = body[:start] + new + body[end:]
        masked = mask_code(body)
        for fence in re.finditer(r"^[ \t]*(```|~~~)[ \t]*(dataview|dataviewjs)\b", body, re.M):
            self.plan.issue(item.src, f"{fence.group(2)} block kept as code: rewrite it as a Base or drop it")
        if reference_definitions(body):
            self.plan.issue(item.src, "reference-style link definitions are not rebased: rewrite them as inline links")
        if "((" in masked and re.search(r"\(\([0-9a-f-]{36}\)\)", masked):
            self.plan.issue(item.src, "Logseq block references `((uuid))` kept as text")
        return body


def _is_image(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".avif"}


# -- entry point --------------------------------------------------------------


def _open_source(plan: Plan, item: Item):
    """A source file opened for reading without following a symlink (one that appeared after the scan)."""
    path = plan.source / item.src
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow and path.is_symlink():  # Windows: no O_NOFOLLOW, so check just before opening
        raise OSError(f"{item.src} became a symbolic link during the import")
    try:
        fd = os.open(path, os.O_RDONLY | nofollow | getattr(os, "O_BINARY", 0))
    except OSError as exc:
        if path.is_symlink():
            raise OSError(f"{item.src} became a symbolic link during the import") from None
        raise exc
    return os.fdopen(fd, "rb")


def _move(staged: Path, dest: Path) -> None:
    """Move without ever replacing an existing file: a hard link, else an exclusive-create copy."""
    try:
        os.link(staged, dest)  # fails with FileExistsError when dest exists
    except FileExistsError:
        raise
    except OSError:  # no hard links here, or another file system
        with staged.open("rb") as source, dest.open("xb") as out:  # "x" also refuses an existing file
            try:
                shutil.copyfileobj(source, out)
                shutil.copymode(staged, dest)
            except BaseException:
                out.close()
                dest.unlink(missing_ok=True)  # ours: created just above
                raise
    staged.unlink()


def _write(bundle: Bundle, plan: Plan) -> list[Path]:
    """Write every output to a staging folder, then move it into place; on any error nothing stays behind."""
    cache = bundle.repo_root / ".cache" / "import"
    cache.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="staging-", dir=cache))
    moved: list[Path] = []
    created: list[Path] = []
    try:
        for item in plan.imported:
            staged = staging / (item.dest or "")
            staged.parent.mkdir(parents=True, exist_ok=True)
            if item.note:
                staged.write_text(plan.outputs[item.dest or ""], encoding="utf-8", newline="\n")
            else:
                with _open_source(plan, item) as handle, staged.open("wb") as out:
                    shutil.copyfileobj(handle, out)
                    staged.chmod(os.fstat(handle.fileno()).st_mode & 0o777)
        for item in plan.imported:
            dest = bundle.root / (item.dest or "")
            for parent in reversed(PurePosixPath(item.dest or "").parents[:-1]):
                folder = bundle.root / parent
                if not folder.exists():
                    folder.mkdir()
                    created.append(folder)
            try:
                _move(staging / (item.dest or ""), dest)
            except FileExistsError:
                raise FileExistsError(f"{bundle.show(item.dest)} appeared during the import") from None
            moved.append(dest)
    except BaseException as exc:
        for path in reversed(moved):
            path.unlink(missing_ok=True)
        for folder in reversed(created):
            try:
                folder.rmdir()
            except OSError:
                pass
        if isinstance(exc, Exception):
            raise _fail(f"{exc}; nothing was written") from None
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return moved


def run(bundle: Bundle, source: Path, into: str, mapping: Mapping, dry_run: bool, redirects: Path | None) -> tuple[Plan, list[str]]:
    plan = build_plan(bundle, source, into, mapping)
    converter = _Converter(plan)
    notes = [i for i in plan.imported if i.note]
    for item in notes:  # titles first, so relation links can use them
        try:
            item.title = _title(item, parse_note(plan, item))
        except ValueError as exc:
            plan.errors.append(f"{item.src}: title template: {exc}")
            item.title = PurePosixPath(item.src).stem
    for item in notes:
        plan.outputs[item.dest or ""] = converter.convert(item)
    for item in plan.imported:
        if not item.note:
            plan.outputs.setdefault(item.dest or "", "")
    lines = report(plan)
    if dry_run or plan.errors:
        return plan, lines
    written = _write(bundle, plan)
    record_touched(bundle.repo_root, [p for p in written if p.suffix == ".md"])
    target = redirects or bundle.repo_root / ".cache" / "import" / f"{slug(plan.source.name) or 'import'}-redirects.tsv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "source\tbundle_path\n" + "".join(f"{i.src}\t/{i.dest}\n" for i in sorted(plan.imported, key=lambda i: i.src)),
        encoding="utf-8",
    )
    lines.append(f"wrote {len(written)} file(s); redirect table: {target}")
    return plan, lines


def report(plan: Plan) -> list[str]:
    notes = sorted((i for i in plan.imported if i.note), key=lambda i: i.dest or "")
    files = sorted((i for i in plan.imported if not i.note), key=lambda i: i.dest or "")
    skipped = sorted((i for i in plan.items.values() if not i.dest), key=lambda i: i.src)
    lines = [f"kb import: {plan.source} -> {plan.prefix}/{plan.into or ''}"]
    lines.append(f"\nnotes ({len(notes)}):")
    lines += [f"  {i.src} -> {plan.prefix}/{i.dest}  [{i.type or '?'}] {i.title}" for i in notes]
    if files:
        lines.append(f"\nfiles ({len(files)}):")
        lines += [f"  {i.src} -> {plan.prefix}/{i.dest}" for i in files]
    if skipped:
        lines.append(f"\nnot imported ({len(skipped)}):")
        lines += [f"  {i.src}: {i.reason}" for i in skipped]
    if plan.issues:
        lines.append(f"\nissues ({len(plan.issues)}):")
        lines += [f"  {src}: {message}" for src, message in sorted(set(plan.issues))]
    if plan.errors:
        lines.append(f"\nerrors ({len(plan.errors)}), nothing written:")
        lines += [f"  {e}" for e in plan.errors]
    return lines
