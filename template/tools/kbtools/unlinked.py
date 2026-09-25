"""Unlinked mentions of other pages (`kb unlinked`).

Deterministic candidates only: the agent decides which mentions deserve a
link and writes it. Names are titles and aliases; the longest name wins, a
name shared by several pages is reported as ambiguous, and targets the page
already links (in the body, a reference definition or a relation) are
skipped, so repeated runs converge. Matching ignores case and accents,
except for all-caps names (acronyms), which match case-sensitively.
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
_REF_DEF = re.compile(r"^ {0,3}\[(?!\^)[^\]]+\]:\s*<?([^\s>]+)>?.*$", re.M)
_URL = re.compile(r"<?https?://[^\s>)]+>?")
SKIP_TYPES = ("Source", "Template")


@dataclass
class Mention:
    page: str
    line: int
    text: str
    target: str
    snippet: str


def _blank(pattern: re.Pattern, text: str) -> str:
    return pattern.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _fold_same_length(text: str) -> str:
    """Casefold and strip accents character by character, keeping offsets intact."""
    if text.isascii():
        return text.lower()
    out = []
    for char in text:
        folded = fold(char)
        out.append(folded[0] if len(folded) >= 1 else char)
    return "".join(out)


def _key(name: str) -> str:
    return " ".join(tokens(name)) or fold(name)


def _name_pattern(name: str) -> str:
    words = [w for w in re.split(r"[\W_]+", name) if w]
    return r"[\s\-_]+".join(re.escape(w) for w in words) + r"(?:e?s)?"


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


def vocabulary(bundle: Bundle, min_len: int = 4) -> tuple[dict[str, tuple[str, str]], dict[str, list[str]]]:
    """normalized name -> (spelling, target page), plus names claimed by several pages."""
    owners: dict[str, set[str]] = defaultdict(set)
    spelled: dict[str, str] = {}
    for rel, doc in _scope(bundle, include_personal=False).items():
        if doc.type in SKIP_TYPES:
            continue
        aliases = [a for a in doc.frontmatter.get("aliases") or [] if isinstance(a, str)]
        for name in [doc.title, *aliases]:
            if len(fold(name).strip()) < min_len and not (name.isupper() and len(name) >= 2):
                continue
            key = ("=" + name) if name.isupper() else _key(name)  # acronyms keyed case-sensitively
            owners[key].add(rel)
            spelled.setdefault(key, name)
    unique = {k: (spelled[k], next(iter(v))) for k, v in owners.items() if len(v) == 1}
    ambiguous = {spelled[k]: sorted(v) for k, v in owners.items() if len(v) > 1}
    return unique, ambiguous


def find(bundle: Bundle, only: list[str] | None = None, min_len: int = 4, include_personal: bool = False) -> list[Mention]:
    names, _ = vocabulary(bundle, min_len)
    pages = _scope(bundle, include_personal)
    wanted = None
    if only:
        wanted = {p.lstrip("/").removeprefix("kb/") for p in only}
        unknown = sorted(wanted - set(pages))
        if unknown:
            raise SystemExit(f"kb: not knowledge pages in scope: {', '.join(unknown)}")
    if not names:
        return []
    acronyms = sorted((s for k, (s, _) in names.items() if k.startswith("=")), key=lambda n: (-len(n), n))
    words = sorted((s for k, (s, _) in names.items() if not k.startswith("=")), key=lambda n: (-len(n), n))
    scans = []  # acronyms match case-sensitively on the text, other names on a folded copy
    if acronyms:
        scans.append((True, re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, acronyms)) + r")(?!\w)")))
    if words:
        scans.append((False, re.compile(r"(?<!\w)(?:" + "|".join(_name_pattern(fold(w)) for w in words) + r")(?!\w)")))

    mentions: list[Mention] = []
    for rel, doc in sorted(pages.items()):
        if wanted is not None and rel not in wanted:
            continue
        linked = {resolve(l.path, doc.folder) for l in find_links(doc.body) if not l.is_external and l.path}
        linked |= {resolve(m.group(1).split("#")[0], doc.folder) for m in _REF_DEF.finditer(doc.body)}
        for key in bundle.config.relations:
            for value in doc.frontmatter.get(key) or []:
                if isinstance(value, str) and "](" in value:
                    linked.add(resolve(value.split("](", 1)[1].rstrip(")").split("#")[0], doc.folder))
        text = mask_code(doc.body)
        text = _LINK.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
        for rx in (_HEADING, _FOOTNOTE_DEF, _REF_DEF, _URL):
            text = _blank(rx, text)
        # Acronyms are matched on the original text, other names on a folded copy.
        folded = _fold_same_length(text)
        seen: set[str] = set()
        for is_acronym, rx in scans:
            for match in rx.finditer(text if is_acronym else folded):
                key = "=" + match.group(0) if is_acronym else _key(match.group(0))
                entry = names.get(key)
                if entry is None and not is_acronym:  # plural forms: 'languages' -> 'language'
                    entry = names.get(_key(re.sub(r"e?s$", "", match.group(0))))
                if not entry:
                    continue
                target = entry[1]
                if target == rel or target in linked or target in seen:
                    continue
                seen.add(target)
                line_no = text.count("\n", 0, match.start()) + 1
                line = doc.body.splitlines()[line_no - 1].strip()
                original = doc.body[match.start():match.end()]
                mentions.append(Mention(f"/{rel}", line_no + doc.body_line_offset, original, f"/{target}", line[:160]))
    return sorted(mentions, key=lambda m: (m.page, m.line))
