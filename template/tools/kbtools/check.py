"""Validation: OKF v0.2 conformance (§11) plus the house profile.

Codes starting with O are OKF conformance errors: a bundle with any of them is
not an OKF bundle. H codes are house rules: errors (H0xx-H2xx) or warnings
(W). OKF itself tolerates broken links and unknown keys, so those are warnings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath

import jsonschema

from . import indexgen
from .bundle import Bundle, Document
from .mdlinks import find_links, footnote_defs, footnote_refs, mask_code, reference_definitions, resolve
from .resources import Settings, deny_patterns, load_env, read_config

KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DATE_HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$")
INDEX_ENTRY = re.compile(r"^[*-] \[(?:[^\]\\]|\\.)+\]\([^)\s]+\)( - .+)?$")
WIKILINK = re.compile(r"!?\[\[[^\]\n]+\]\]")
RELATION_VALUE = re.compile(r"^\[(?P<text>[^\]]+)\]\((?P<target>[^)\s]+)\)$")


@dataclass(frozen=True)
class Diagnostic:
    path: str
    line: int
    code: str
    message: str

    @property
    def is_error(self) -> bool:
        return not self.code.startswith("W")

    def __str__(self) -> str:
        return f"kb/{self.path}:{self.line}: {self.code} {self.message}"


class Checker:
    def __init__(self, bundle: Bundle):
        self.bundle = bundle
        self.config = bundle.config
        self.validator = jsonschema.Draft202012Validator(self.config.schema)
        self.known_keys = set(self.config.schema.get("properties", {}))
        load_env(bundle.repo_root)
        data, self.resource_errors = read_config(bundle.repo_root)
        self.roots = set((data.get("roots") or {}).keys())
        self.deny = Settings(roots={}, deny=deny_patterns(data), zotero_user_id=None, zotero_group_id=None)
        self.diagnostics: list[Diagnostic] = []

    def report(self, doc_or_path: Document | str, line: int, code: str, message: str) -> None:
        path = str(doc_or_path.rel) if isinstance(doc_or_path, Document) else doc_or_path
        self.diagnostics.append(Diagnostic(path, line, code, message))

    # -- entry points -------------------------------------------------------

    def check_all(self) -> list[Diagnostic]:
        for error in self.resource_errors:
            self.report("../schema/resources.yaml", 1, "H061", error)
        for doc in self.bundle.documents:
            self.check_document(doc)
        self.check_folders()
        self.check_indexes()
        return self.sorted()

    def check_files(self, docs: list[Document]) -> list[Diagnostic]:
        for doc in docs:
            self.check_document(doc)
        return self.sorted()

    def sorted(self) -> list[Diagnostic]:
        return sorted(set(self.diagnostics), key=lambda d: (d.path, d.line, d.code))

    # -- per document -------------------------------------------------------

    def check_document(self, doc: Document) -> None:
        if doc.rel.name == "index.md":
            self.check_index(doc)
        elif doc.rel.name == "log.md":
            self.check_log(doc)
        else:
            self.check_concept(doc)

    def check_concept(self, doc: Document) -> None:
        if doc.frontmatter_error:
            self.report(doc, 1, "O001", doc.frontmatter_error)
            return
        if not doc.has_frontmatter:
            self.report(doc, 1, "O001", "missing YAML frontmatter (every non-reserved .md file needs one)")
            return
        if not doc.type:
            self.report(doc, 1, "O002", "frontmatter needs a non-empty `type`")
            return
        self.check_names(doc)
        self.check_schema(doc)
        self.check_type(doc)
        if doc.type == "Template":
            return  # Templater code in the body is not prose; skip link/citation checks
        self.check_citations(doc)
        self.check_links(doc)
        self.check_reference_links(doc)
        self.check_wikilinks(doc)
        self.check_timestamps(doc)
        self.check_relations(doc)
        self.check_locators(doc)
        self.check_staleness(doc)

    def check_names(self, doc: Document) -> None:
        for part in doc.rel.parent.parts:
            if not KEBAB.match(part.lstrip("_").lstrip(".")):
                self.report(doc, 1, "H001", f"folder name `{part}` is not kebab-case")
        if not KEBAB.match(doc.rel.stem):
            self.report(doc, 1, "H001", f"file name `{doc.rel.name}` is not kebab-case")

    def check_schema(self, doc: Document) -> None:
        for error in sorted(self.validator.iter_errors(doc.frontmatter), key=lambda e: list(e.path)):
            where = ".".join(str(p) for p in error.absolute_path) or "frontmatter"
            self.report(doc, 1, "H010", f"{where}: {error.message}")
        for key in doc.frontmatter:
            if key not in self.known_keys:
                self.report(doc, 1, "W010", f"unknown frontmatter key `{key}` (typo? otherwise declare it under `fields` in schema/vocabulary.yaml)")

    def check_type(self, doc: Document) -> None:
        spec = self.config.types.get(doc.type)
        if spec is None:
            self.report(doc, 1, "H011", f"type `{doc.type}` is not in schema/vocabulary.yaml")
            return
        allowed = spec.get("folders", ["*"])
        top = doc.rel.parts[0] if len(doc.rel.parts) > 1 else ""
        ok = any(
            (a == "*" and top in self.config.domain_folders) or top == a or doc.folder.startswith(f"{a}/") or doc.folder == a
            for a in allowed
        )
        if not ok:
            where = ", ".join("a knowledge-domain folder" if a == "*" else f"{a}/" for a in allowed)
            self.report(doc, 1, "H012", f"type `{doc.type}` belongs in {where}")
        for key in spec.get("required", []):
            if key not in doc.frontmatter:
                self.report(doc, 1, "H013", f"type `{doc.type}` requires `{key}`")

    def check_citations(self, doc: Document) -> None:
        sources = doc.frontmatter.get("sources") or []
        ids = {s.get("id") for s in sources if isinstance(s, dict) and s.get("id")}
        defs = footnote_defs(doc.body)
        cited = set()
        for label, line in footnote_refs(doc.body):
            cited.add(label)
            line += doc.body_line_offset
            if label not in ids:
                self.report(doc, line, "H020", f"footnote [^{label}] does not match any `sources[].id`")
            if label not in defs:
                self.report(doc, line, "H021", f"footnote [^{label}] has no definition")
        for source_id in sorted(ids - cited):
            self.report(doc, 1, "W020", f"source `{source_id}` is never cited with [^{source_id}]")
        for source in sources:
            if isinstance(source, dict) and isinstance(source.get("resource"), str):
                res = source["resource"]
                if res.startswith("/") and not self.bundle.exists(res.lstrip("/").split("#")[0]):
                    self.report(doc, 1, "W021", f"source resource `{res}` does not exist in the bundle")

    def check_links(self, doc: Document) -> None:
        for link in find_links(doc.body):
            line = link.line + doc.body_line_offset
            if link.is_external or link.is_anchor_only or not link.path:
                continue
            target = resolve(link.path, doc.folder)
            if target is None:
                self.report(doc, line, "H030", f"link `{link.target}` escapes the bundle")
                continue
            if not self.bundle.exists(target):
                self.report(doc, line, "W030", f"broken link `{link.target}` (not-yet-written page?)")
            if not link.target.startswith("/"):
                self.report(doc, line, "W031", f"link `{link.target}` should be bundle-absolute (`/{target}`); run `just fix`")

    def check_wikilinks(self, doc: Document) -> None:
        masked = mask_code(doc.body)
        for m in WIKILINK.finditer(masked):
            line = masked.count("\n", 0, m.start()) + 1 + doc.body_line_offset
            self.report(doc, line, "H032", f"`{m.group(0)[:60]}` is a wikilink or embed, not an OKF link; use [text](/path.md)")

    def check_timestamps(self, doc: Document) -> None:
        now = datetime.now(timezone.utc)
        events = [("generated.at", (doc.frontmatter.get("generated") or {}).get("at") if isinstance(doc.frontmatter.get("generated"), dict) else None)]
        verified = doc.frontmatter.get("verified")
        for event in verified if isinstance(verified, list) else [verified] if isinstance(verified, dict) else []:
            if isinstance(event, dict):
                events.append(("verified.at", event.get("at")))
        for where, value in events:
            try:
                instant = datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
            except ValueError:
                continue
            if instant and instant.tzinfo and instant > now:
                self.report(doc, 1, "W041", f"{where} {value} is in the future")

    def check_reference_links(self, doc: Document) -> None:
        for line in reference_definitions(doc.body):
            self.report(doc, line + doc.body_line_offset, "W033",
                        "reference-style link definition: kb tooling only follows inline links [text](/path.md)")

    def check_relations(self, doc: Document) -> None:
        body_targets = {
            resolve(link.path, doc.folder)
            for link in find_links(doc.body)
            if not link.is_external and not link.is_anchor_only and link.path
        }
        for key in self.config.relations:
            values = doc.frontmatter.get(key)
            if not isinstance(values, list):
                continue
            for value in values:
                match = RELATION_VALUE.match(value) if isinstance(value, str) else None
                if not match:
                    continue  # shape errors are reported by the schema
                target = resolve(match.group("target").split("#")[0], doc.folder)
                if target and not self.bundle.exists(target):
                    self.report(doc, 1, "W032", f"{key}: target `{match.group('target')}` does not exist")
                if target not in body_targets:
                    self.report(doc, 1, "H031", f"{key}: `{match.group('target')}` is not linked from the body (explain the relation in prose)")

    def check_locators(self, doc: Document) -> None:
        for locator in doc.frontmatter.get("locators") or []:
            if isinstance(locator, str) and locator.startswith("file:"):
                root = locator[5:].split("/", 1)[0]
                if root not in self.roots:
                    self.report(doc, 1, "W060", f"locator root `{root}` is not declared in schema/resources.yaml")
                elif self.deny.denied(locator[5:]):
                    self.report(doc, 1, "H060", f"locator `{locator}` points at denied material; remove it")

    def check_staleness(self, doc: Document) -> None:
        stale_after = doc.frontmatter.get("stale_after")
        if not isinstance(stale_after, str):
            return
        try:
            instant = datetime.fromisoformat(stale_after.replace("Z", "+00:00"))
        except ValueError:
            return
        if instant.tzinfo is None:
            return  # the schema reports the missing UTC offset (H010)
        if datetime.now(timezone.utc) >= instant:
            self.report(doc, 1, "W040", f"stale since {stale_after}: re-check against sources, then update `stale_after`")

    # -- reserved files -----------------------------------------------------

    def check_index(self, doc: Document) -> None:
        if doc.has_frontmatter:
            keys = set(doc.frontmatter) if not doc.frontmatter_error else {"?"}
            if not doc.is_root_index:
                self.report(doc, 1, "O003", "only the bundle-root index.md may have frontmatter")
            elif keys - {"okf_version"}:
                self.report(doc, 1, "O003", "root index.md frontmatter may only contain `okf_version`")
        for n, line in enumerate(doc.body.splitlines(), start=doc.body_line_offset + 1):
            if not line.strip() or line.startswith("#") or INDEX_ENTRY.match(line):
                continue
            self.report(doc, n, "O004", "index.md lines must be headings or `* [Title](url) - description` entries")

    def check_log(self, doc: Document) -> None:
        if doc.has_frontmatter:
            self.report(doc, 1, "O005", "log.md must not have frontmatter")
        previous = None
        for n, line in enumerate(doc.body.splitlines(), start=doc.body_line_offset + 1):
            if not line.startswith("## "):
                continue
            match = DATE_HEADING.match(line)
            if not match:
                self.report(doc, n, "O005", "log.md section headings must be `## YYYY-MM-DD`")
                continue
            if previous is not None and match.group(1) >= previous:
                self.report(doc, n, "O005", "log.md dates must be unique and newest first")
            previous = match.group(1)
        for link in find_links(doc.body):
            if link.is_external or link.is_anchor_only or not link.path:
                continue
            target = resolve(link.path, doc.folder)
            if target is not None and not self.bundle.exists(target):
                self.report(doc, link.line + doc.body_line_offset, "W030", f"broken link `{link.target}`")

    # -- bundle level -------------------------------------------------------

    def check_folders(self) -> None:
        for folder in indexgen.folders_to_index(self.bundle):
            if folder and self.config.folder_spec(folder) is None:
                self.report(f"{folder}/", 1, "W050", "folder has no entry in schema/taxonomy.yaml (title/description for the index)")

    def check_indexes(self) -> None:
        for path in indexgen.stale(self.bundle):
            rel = PurePosixPath(path.relative_to(self.bundle.root).as_posix())
            self.report(str(rel), 1, "H040", "index.md is missing or out of date; run `just index`")


def exit_code(diagnostics: list[Diagnostic], strict: bool) -> int:
    if any(d.is_error for d in diagnostics):
        return 1
    return 1 if strict and diagnostics else 0
