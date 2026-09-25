"""Unlinked mentions of other pages (`kb unlinked`).

Deterministic candidates only: the agent decides which mentions deserve a
link and writes it. Names are titles and aliases; the longest name wins, a
name shared by several pages is reported as ambiguous, and targets the page
already links (in the body or a relation) are skipped, so repeated runs
converge.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from .bundle import Bundle, Document
from .mdlinks import _LINK, find_links, mask_code, resolve
from .names import fold, tokens

_HEADING = re.compile(r"^#{1,6} .*$", re.M)
_FOOTNOTE_DEF = re.compile(r"^\[\^[^\]]+\]:.*$", re.M)
_URL = re.compile(r"<?https?://[^\s>)]+>?")
SKIP_TYPES = ("Source", "Template")


@dataclass
class Mention:
    page: str
    line: int
    text: str
    target: str
    snippet: str


def _blank_matches(pattern: re.Pattern, text: str) -> str:
    return pattern.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _name_pattern(name: str) -> str:
    words = [w for w in re.split(r"[\W_]+", name) if w]
    body = r"[\s\-_]+".join(re.escape(w) for w in words)
    return body + r"(?:e?s)?"


def _scope(bundle: Bundle, include_personal: bool) -> dict[str, Document]:
    personal = bundle.config.personal_folders
    pages = {}
    for doc in bundle.concepts():
        if doc.frontmatter_error or not doc.type or doc.type == "Template":
            continue
        if any(part.startswith(("_", ".")) for part in doc.rel.parts[:-1]):
            continue
        if not include_personal and len(doc.rel.parts) > 1 and doc.rel.parts[0] in personal:
            continue
        pages[str(doc.rel)] = doc
    return pages


def vocabulary(bundle: Bundle, min_len: int = 4) -> tuple[dict[str, str], dict[str, list[str]]]:
    """name -> target page, plus names claimed by several pages."""
    owners: dict[str, set[str]] = defaultdict(set)
    spelled: dict[str, str] = {}
    for rel, doc in _scope(bundle, include_personal=False).items():
        if doc.type in SKIP_TYPES:
            continue
        aliases = [a for a in doc.frontmatter.get("aliases") or [] if isinstance(a, str)]
        for name in [doc.title, *aliases]:
            key = " ".join(tokens(name)) or fold(name)
            short = len(fold(name).strip()) < min_len
            if short and not (name.isupper() and len(name) >= 2):
                continue
            owners[key].add(rel)
            spelled.setdefault(key, name)
    unique = {spelled[k]: next(iter(v)) for k, v in owners.items() if len(v) == 1}
    ambiguous = {spelled[k]: sorted(v) for k, v in owners.items() if len(v) > 1}
    return unique, ambiguous


def find(bundle: Bundle, only: list[str] | None = None, min_len: int = 4, include_personal: bool = False) -> list[Mention]:
    names, _ = vocabulary(bundle, min_len)
    if not names:
        return []
    ordered = sorted(names, key=lambda n: (-len(n), n))
    case_sensitive = {n for n in ordered if n.isupper()}
    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(
            (f"(?-i:{_name_pattern(n)})" if n in case_sensitive else _name_pattern(n)) for n in ordered
        ) + r")(?!\w)",
        re.IGNORECASE,
    )
    lookup = [(re.compile(r"(?<!\w)" + (_name_pattern(n)) + r"(?!\w)", 0 if n in case_sensitive else re.I), n) for n in ordered]

    pages = _scope(bundle, include_personal)
    wanted = {p.lstrip("/").removeprefix("kb/") for p in only} if only else None
    mentions: list[Mention] = []
    for rel, doc in sorted(pages.items()):
        if wanted is not None and rel not in wanted:
            continue
        linked = {resolve(l.path, doc.folder) for l in find_links(doc.body) if not l.is_external and l.path}
        for key in bundle.config.relations:
            for value in doc.frontmatter.get(key) or []:
                if isinstance(value, str) and "](" in value:
                    linked.add(resolve(value.split("](", 1)[1].rstrip(")").split("#")[0], doc.folder))
        text = mask_code(doc.body)
        text = _LINK.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
        for rx in (_HEADING, _FOOTNOTE_DEF, _URL):
            text = _blank_matches(rx, text)
        seen: set[str] = set()
        for match in pattern.finditer(text):
            name = next((n for rx, n in lookup if rx.fullmatch(match.group(0))), None)
            target = names.get(name) if name else None
            if not target or target == rel or target in linked or target in seen:
                continue
            seen.add(target)
            line_no = text.count("\n", 0, match.start()) + 1
            line = doc.body.splitlines()[line_no - 1].strip()
            mentions.append(Mention(f"/{rel}", line_no + doc.body_line_offset, match.group(0), f"/{target}", line[:160]))
    return mentions
