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

Nothing in the source is modified. `--dry-run` prints the plan and every
issue without writing; a real run refuses to start while the plan has errors.
The mapping format is documented in docs/importing.md.
"""

from __future__ import annotations

import posixpath
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

import yaml

from .bundle import RESERVED, Bundle, load_yaml, record_touched
from .mdlinks import encode_path, find_links, mask_code, reference_definitions
from .names import fold

ALWAYS_EXCLUDED = (".git/**", ".obsidian/**", ".trash/**", "logseq/**", "**/.DS_Store", ".*")
DEFAULT_MAX_BYTES = 2_000_000
_WIKILINK = re.compile(r"(?P<bang>!?)\[\[(?P<inner>[^\[\]\n]+?)\]\]")
_BLOCK_ID = re.compile(r"[ \t]+\^(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9-]+[ \t]*$", re.M)  # "r ^2" is not an id
_OBSIDIAN_COMMENT = re.compile(r"%%(?P<text>.*?)%%", re.S)
_INLINE_TAG = re.compile(r"(?<![\w/#&(\[])#(?P<tag>\[\[[^\]\n]+\]\]|[A-Za-z][\w/-]*)")
_LOGSEQ_PROP = re.compile(r"^(?P<key>[A-Za-z][\w-]*):: ?(?P<value>.*)$")
_LOGSEQ_BLOCK_PROP = re.compile(r"^[ \t]*(?:id|collapsed):: .*\n", re.M)
_FRONTMATTER = re.compile(r"---\n(?P<yaml>.*?\n)??---[ \t]*(?:\n|$)", re.S)
_PAGE_REF = re.compile(r"\[\[([^\[\]]*)\]\]")
WRITTEN_KEYS = ("status", "generated", "verified")  # set by the importer; a source value needs a rule
MAPPING_KEYS = {"label", "actor", "exclude", "notes", "files", "properties", "timestamp", "rewrite", "tags",
                "description_skip", "unresolved", "max_bytes", "links"}
RULE_KEYS = {"match", "to", "skip", "type", "title", "tags", "status", "alias_stem", "kebab"}
_DATE = re.compile(r"(?P<y>\d{4})[-_](?P<m>\d{2})[-_](?P<d>\d{2})")
_HEADING = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<text>.*?)[ \t#]*$", re.M)
_SIZE = re.compile(r"^\d+(x\d+)?$")


# -- mapping ------------------------------------------------------------------


def glob_regex(pattern: str) -> re.Pattern[str]:
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
    return re.compile("".join(out) + r"\Z")


def _matches(path: str, patterns: list[str]) -> bool:
    return any(glob_regex(p).match(path) for p in patterns)


def kebab(name: str) -> str:
    name = re.sub(r"(\w)\+\+", r"\1pp", name)
    name = re.sub(r"(\w)#", r"\1sharp", name)
    return re.sub(r"[^a-z0-9]+", "-", fold(name)).strip("-")


def slugify_heading(text: str) -> str:
    """GitHub-style heading anchor."""
    text = re.sub(r"[`*_~]|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", text)
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


@dataclass
class Mapping:
    actor: str
    label: str
    exclude: list[str]
    notes: list[dict[str, Any]]
    files: list[dict[str, Any]]
    properties: dict[str, Any]
    timestamp: str | None
    rewrite: list[dict[str, str]]
    tags: dict[str, Any]
    description_skip: list[str]
    unresolved: str
    max_bytes: int
    links: dict[str, str]

    @classmethod
    def load(cls, path: Path, actor: str | None) -> Mapping:
        data = load_yaml(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise SystemExit(f"kb import: {path} must be a YAML mapping")
        unknown = sorted(set(data) - MAPPING_KEYS)
        if unknown:
            raise SystemExit(f"kb import: unknown mapping key(s) {', '.join(unknown)} in {path}")
        for key, spec in (data.get("properties") or {}).items():
            if isinstance(spec, dict) and "relation" in spec and not spec.get("target"):
                raise SystemExit(f"kb import: relation property `{key}` needs a `target`")
        actor = actor or data.get("actor")
        if not actor:
            raise SystemExit("kb import: set `actor` in the mapping or pass --by (e.g. human:<id>)")
        for rule in (data.get("notes") or []) + (data.get("files") or []):
            if not isinstance(rule, dict) or "match" not in rule or not (rule.get("skip") or rule.get("to")):
                raise SystemExit(f"kb import: every rule needs `match` and `to` (or `skip: true`): {rule!r}")
            if set(rule) - RULE_KEYS:
                raise SystemExit(f"kb import: unknown rule key(s) {', '.join(sorted(set(rule) - RULE_KEYS))} in {rule!r}")
        unresolved = data.get("unresolved", "text")
        if unresolved not in ("text", "wanted"):
            raise SystemExit("kb import: `unresolved` is `text` or `wanted`")
        return cls(
            actor=str(actor),
            label=str(data.get("label") or path.stem),
            exclude=list(data.get("exclude") or []),
            notes=list(data.get("notes") or []),
            files=list(data.get("files") or []),
            properties=dict(data.get("properties") or {}),
            timestamp=data.get("timestamp"),
            rewrite=list(data.get("rewrite") or []),
            tags=dict(data.get("tags") or {}),
            description_skip=list(data.get("description_skip") or []),
            unresolved=unresolved,
            max_bytes=int(data.get("max_bytes") or DEFAULT_MAX_BYTES),
            links={str(k).casefold(): "/" + str(v).strip("/").removeprefix("kb/") for k, v in (data.get("links") or {}).items()},
        )


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
class Plan:
    source: Path
    into: str
    mapping: Mapping
    items: dict[str, Item] = field(default_factory=dict)  # every non-hidden source file
    errors: list[str] = field(default_factory=list)
    issues: list[tuple[str, str]] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)  # dest -> text (notes) or "" (copied files)
    names: dict[str, list[str]] | None = None  # wikilink name index, built on first use

    @property
    def imported(self) -> list[Item]:
        return [i for i in self.items.values() if i.dest]

    def issue(self, src: str, message: str) -> None:
        self.issues.append((src, message))


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
    try:
        rendered = template.format_map(values)
    except KeyError as exc:
        raise ValueError(f"placeholder {exc} is not available for this file") from None
    absolute = template.startswith("/")  # an empty {dir} must not make a path absolute
    parts = [p for p in rendered.split("/") if p]
    if kebab_names:
        *dirs, last = parts
        stem, dot, ext = last.rpartition(".") if "." in last.lstrip(".") else (last, "", "")
        parts = [kebab(d) for d in dirs] + [kebab(stem) + (dot + ext.lower() if dot else "")]
    if not parts or any(not p for p in parts):
        raise ValueError(f"`{template}` renders an empty name")
    joined = "/".join(parts)
    return posixpath.normpath(joined if absolute or not into else posixpath.join(into, joined))


def _first_rule(rules: list[dict[str, Any]], src: str) -> dict[str, Any] | None:
    for rule in rules:
        patterns = rule["match"] if isinstance(rule["match"], list) else [rule["match"]]
        if _matches(src, patterns):
            return rule
    return None


def build_plan(bundle: Bundle, source: Path, into: str, mapping: Mapping) -> Plan:
    source = source.resolve()
    if not source.is_dir():
        raise SystemExit(f"kb import: {source} is not a directory")
    into = into.strip("/").removeprefix("kb/")
    plan = Plan(source=source, into=into, mapping=mapping)
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        src = path.relative_to(source).as_posix()
        if _matches(src, list(ALWAYS_EXCLUDED)) or any(part.startswith(".") for part in PurePosixPath(src).parts):
            continue
        item = Item(src=src, note=path.suffix.lower() == ".md")
        plan.items[src] = item
        if _matches(src, mapping.exclude):
            item.reason = "excluded by the mapping"
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
    seen: dict[str, str] = {}
    for item in plan.imported:
        name = PurePosixPath(item.dest).name
        if item.note and name in RESERVED:
            plan.errors.append(f"{item.src}: `{name}` is reserved in OKF; map it to another name")
        if item.dest in seen:
            plan.errors.append(f"{item.src} and {seen[item.dest]} both map to kb/{item.dest}")
        seen[item.dest] = item.src
        if (bundle.root / item.dest).exists():
            plan.errors.append(f"{item.src}: kb/{item.dest} already exists")
        if bundle.root.resolve() not in (bundle.root / item.dest).resolve().parents:
            plan.errors.append(f"{item.src}: kb/{item.dest} is outside the bundle")
    return plan


def _assign(plan: Plan, item: Item, rule: dict[str, Any]) -> None:
    template = rule["to"]
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


def _linked_attachments(plan: Plan) -> None:
    """Attachments without a rule are copied to <into>/assets/ when an imported note links them."""
    wanted: set[str] = set()
    for item in [i for i in plan.imported if i.note]:
        text = read_note(plan, item)[1]
        masked = mask_code(text)
        for m in _WIKILINK.finditer(masked):
            target = _resolve_name(plan, m.group("inner").replace("\\|", "|").split("|")[0].split("#")[0], item.src)
            if target:
                wanted.add(target)
        for link in find_links(text):
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


# -- conversion ---------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(instant: datetime) -> str:
    return min(instant.astimezone(timezone.utc), _now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    try:
        git = subprocess.run(
            ["git", "--literal-pathspecs", "log", "-1", "--format=%cI", "--", item.src],
            cwd=plan.source, capture_output=True, text=True, check=False,
        )
        if git.returncode == 0 and git.stdout.strip():
            return _iso(datetime.fromisoformat(git.stdout.strip()))
    except OSError:
        pass  # no git: use the file time
    return _iso(datetime.fromtimestamp((plan.source / item.src).stat().st_mtime, timezone.utc))


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
        value = m.group("value").strip()
        key = m.group("key")
        if key in ("tags", "alias", "aliases"):
            props[key] = [_PAGE_REF.sub(r"\1", v.strip()).lstrip("#") for v in value.split(",") if v.strip()]
        else:
            props[key] = _PAGE_REF.sub(r"\1", value).lstrip("#")  # `type:: [[guide]]` is the value guide
        count += 1
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


def _plain(text: str) -> str:
    text = re.sub(r"!?\[\[([^\]|]*\|)?([^\]]*)\]\]", r"\2", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`|\*\*|__|~~", "", text)
    return " ".join(text.split())


def _description(body: str, skip: list[str]) -> str | None:
    """First sentence of the first prose paragraph (hard-wrapped lines joined)."""
    masked = mask_code(body).splitlines()
    paragraph: list[str] = []
    for original, blanked in zip(body.splitlines(), masked, strict=False):
        line = original.strip()
        structural = not blanked.strip() or line.startswith(("#", "|", ">", "<", "---", "![", "```", "~~~"))
        skipped = any(re.search(p, line) for p in skip)
        if paragraph and (structural or skipped or re.match(r"^(?:[-*+]|\d+[.)])\s", line)):
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


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


class _Converter:
    def __init__(self, plan: Plan):
        self.plan = plan
        self.by_src = plan.items

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
        if src is None and name.strip().casefold() in self.plan.mapping.links:
            return f"[{display}]({encode_path(self.plan.mapping.links[name.strip().casefold()])})"
        if href is None:
            if src is None:
                if self.plan.mapping.unresolved == "wanted" and not embed:
                    wanted = "/" + encode_path(posixpath.join(self.plan.into, kebab(name) + ".md"))
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

    def convert(self, item: Item) -> str:
        mapping = self.plan.mapping
        props, body, problem = read_note(self.plan, item)
        if problem:
            self.plan.issue(item.src, problem)
        for m in reversed(list(_LOGSEQ_BLOCK_PROP.finditer(mask_code(body)))):
            body = body[: m.start()] + body[m.end() :]

        h1, rest = _title_from_h1(body)
        if h1 is not None:
            body = _promote_headings(rest)
        stem = PurePosixPath(item.src).stem
        try:
            title = item.title = _title(item, props, h1)
        except (KeyError, ValueError) as exc:
            self.plan.errors.append(f"{item.src}: title template: placeholder {exc} is not available for this file")
            title = item.title = stem

        tags = self.tags(props, body, item)
        body = self.convert_body(body, item)
        if not body.strip():
            self.plan.issue(item.src, "empty note: imported as a stub")
        fm: dict[str, Any] = {"type": self.type_of(item, props), "title": title}
        description = props.get("description") if isinstance(props.get("description"), str) else None
        description = description or _description(body, mapping.description_skip)
        if not description:
            description = f"{title}, imported from {mapping.label}."
            self.plan.issue(item.src, "no prose for a description: wrote a placeholder")
        fm["description"] = description
        aliases = [str(a) for key in ("aliases", "alias") for a in _as_list(props.get(key))]
        generic = {"readme", "index", "untitled", PurePosixPath(item.dest).stem}
        if item.rule.get("alias_stem", True) and stem.casefold() not in generic | {title.casefold()}:
            aliases.append(stem)
        if aliases:
            fm["aliases"] = list(dict.fromkeys(aliases))
        fm["tags"] = tags
        fm["status"] = item.rule.get("status", "draft")
        at = _timestamp(self.plan, item, props)
        for key, value in props.items():
            if key in ("type", "title", "description", "tags", "tag", "aliases", "alias") and key not in mapping.properties:
                continue
            spec = mapping.properties.get(key)
            if key in WRITTEN_KEYS and not (
                spec == "drop" or (isinstance(spec, dict) and spec.get("rename", key) not in WRITTEN_KEYS)
            ):
                self.plan.errors.append(f"{item.src}: property `{key}` would clash with the `{key}` the importer writes; add a `drop` or `rename` rule")
                continue
            self.property(fm, key, value, item)
        fm = {k: v for k, v in fm.items() if k == "tags" or v not in (None, [], "")}
        item.type = fm["type"]
        header = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=1000)
        header += f"generated: {{ by: {mapping.actor}, at: {at} }}\n"
        return f"---\n{header}---\n\n{body.strip()}\n"

    def type_of(self, item: Item, props: dict[str, Any]) -> str:
        spec = item.rule.get("type")
        if isinstance(spec, dict):
            value = props.get(spec.get("from", "type"))
            mapped = (spec.get("map") or {}).get(str(value)) if value is not None else None
            if mapped:
                return mapped
            if not spec.get("default"):
                self.plan.errors.append(f"{item.src}: no type for `{spec.get('from', 'type')}: {value}` and no default")
                return "?"
            return spec["default"]
        if not spec:
            self.plan.errors.append(f"{item.src}: rule `{item.rule['match']}` has no `type`")
            return "?"
        return str(spec)

    def property(self, fm: dict[str, Any], key: str, value: Any, item: Item) -> None:
        spec = self.plan.mapping.properties.get(key, "keep")
        if spec == "drop":
            return
        if spec == "keep":
            fm.setdefault(key, value)
            return
        if not isinstance(spec, dict):
            self.plan.errors.append(f"mapping: property `{key}` must be keep, drop, or a mapping")
            return
        if "relation" in spec:
            links = []
            for entry in _as_list(value):
                try:
                    dest = _render(spec["target"].replace("{value}", kebab(str(entry))), item.src, self.plan.into)
                except ValueError as exc:
                    self.plan.errors.append(f"{item.src}: relation `{key}`: {exc}")
                    continue
                title = next((i.title for i in self.plan.imported if i.dest == dest and i.title), None)
                links.append(f"[{title or entry}](/{encode_path(dest)})")
            if links:
                fm[spec["relation"]] = fm.get(spec["relation"], []) + links
            return
        values = spec.get("map") or {}
        fm[spec.get("rename", key)] = values.get(value, value) if isinstance(value, str) else value

    def tags(self, props: dict[str, Any], body: str, item: Item) -> list[str]:
        options = self.plan.mapping.tags
        found = [str(t).lstrip("#") for key in ("tags", "tag") for t in _as_list(props.get(key))]
        if options.get("inline", "collect") == "collect":
            for m in _INLINE_TAG.finditer(mask_code(body)):
                found.append(m.group("tag").strip("[]"))
        drop = [re.compile(p) for p in options.get("drop") or []]
        rename = options.get("map") or {}
        out = []
        for tag in found:
            tag = rename.get(tag, tag)
            if not tag or any(p.search(tag) for p in drop):
                continue
            slug = kebab(tag.replace("/", "-"))
            if slug and slug not in out:
                out.append(slug)
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
        for m in _BLOCK_ID.finditer(masked):
            edits.append((m.start(), m.end(), ""))
            self.plan.issue(item.src, f"block id `{m.group(0).strip()}` removed")
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


def _title(item: Item, props: dict[str, Any], h1: str | None) -> str:
    """Rule `title` template, else the first-line H1, else a `title` property, else the file stem."""
    path = PurePosixPath(item.src)
    if item.rule.get("title"):
        date = _DATE.search(path.stem) or _DATE.search(item.src)
        values = {"stem": path.stem, "parent": path.parent.name}
        if date:
            values["date"] = f"{date['y']}-{date['m']}-{date['d']}"
        return str(item.rule["title"]).format_map(values)
    if h1:
        return _plain(h1)
    return str(props["title"]) if props.get("title") else path.stem.replace("___", "/")


def read_note(plan: Plan, item: Item) -> tuple[dict[str, Any], str, str | None]:
    """Properties and body of a source note, after the mapping's `rewrite` rules."""
    text = (plan.source / item.src).read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    props, body, problem = _split_frontmatter(text.removeprefix("\ufeff"))
    for rule in plan.mapping.rewrite:
        body = re.sub(rule["pattern"], rule.get("replace", ""), body, flags=re.M | re.S)
    return props, body, problem


def _is_image(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".avif"}


# -- entry point --------------------------------------------------------------


def run(bundle: Bundle, source: Path, into: str, mapping: Mapping, dry_run: bool, redirects: Path | None) -> tuple[Plan, list[str]]:
    plan = build_plan(bundle, source, into, mapping)
    converter = _Converter(plan)
    notes = [i for i in plan.imported if i.note]
    for item in notes:  # titles first, so relation links can use them
        props, body, _ = read_note(plan, item)
        try:
            item.title = _title(item, props, _title_from_h1(body)[0])
        except (KeyError, ValueError):
            item.title = PurePosixPath(item.src).stem  # reported as an error by the conversion
    for item in notes:
        plan.outputs[item.dest] = converter.convert(item)
    for item in plan.imported:
        if not item.note:
            plan.outputs.setdefault(item.dest, "")
    lines = report(plan)
    if dry_run or plan.errors:
        return plan, lines
    written = []
    for item in plan.imported:
        dest = bundle.root / item.dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        if item.note:
            dest.write_text(plan.outputs[item.dest], encoding="utf-8")
        else:
            dest.write_bytes((plan.source / item.src).read_bytes())
            dest.chmod((plan.source / item.src).stat().st_mode & 0o777)
        written.append(dest)
    record_touched(bundle.repo_root, [p for p in written if p.suffix == ".md"])
    target = redirects or bundle.repo_root / ".cache" / "import" / f"{kebab(plan.source.name)}-redirects.tsv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "source\tbundle_path\n" + "".join(f"{i.src}\t/{i.dest}\n" for i in sorted(plan.imported, key=lambda i: i.src)),
        encoding="utf-8",
    )
    lines.append(f"wrote {len(written)} file(s); redirect table: {target}")
    return plan, lines


def report(plan: Plan) -> list[str]:
    notes = sorted((i for i in plan.imported if i.note), key=lambda i: i.dest)
    files = sorted((i for i in plan.imported if not i.note), key=lambda i: i.dest)
    skipped = sorted((i for i in plan.items.values() if not i.dest), key=lambda i: i.src)
    lines = [f"kb import: {plan.source} -> kb/{plan.into or ''}"]
    lines.append(f"\nnotes ({len(notes)}):")
    lines += [f"  {i.src} -> kb/{i.dest}  [{i.type or '?'}] {i.title}" for i in notes]
    if files:
        lines.append(f"\nfiles ({len(files)}):")
        lines += [f"  {i.src} -> kb/{i.dest}" for i in files]
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
