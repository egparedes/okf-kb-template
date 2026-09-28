"""Unlinked mentions of other pages (`kb unlinked`).

Deterministic candidates only: the agent decides which mentions deserve a
link and writes it. Names are titles and aliases; the longest name wins, a
name shared by several pages is reported as ambiguous, and targets the page
already links (in the body, a reference definition or a relation) are
skipped, so repeated runs converge. Matching ignores case and accents,
except for all-caps names (acronyms), which match case-sensitively.

Names are looked up word by word in a dictionary (not with one big regular
expression), so the cost grows with the text, not with the number of names.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import unquote

from .bundle import Bundle, Document
from .mdlinks import _FOOTNOTE_DEF, _LINK, _REF_DEF, line_at, resolve
from .names import fold, tokens

_HEADING = re.compile(r"^#{1,6} .*$", re.M)
_URL = re.compile(r"<?https?://[^\s>)]+>?")
_WORDS = re.compile(r"[^\W_]+")  # the words of a name or a text: runs of letters and digits
_SEPARATOR = re.compile(r"[\s\-_]+")  # what may stand between the words of a name in the text
_ACRONYM_START = re.compile(r"(?<!\w)\w+")  # a whole word
_WORD_RUN = re.compile(r"\w+")
SKIP_TYPES = ("Source", "Template")


@dataclass
class Mention:
    page: str
    line: int
    text: str
    target: str
    snippet: str


def _spaces(text: str) -> str:
    """The text with every character but line breaks replaced by a space."""
    return " " * len(text) if "\n" not in text else re.sub(r"[^\n]", " ", text)


def _blank(pattern: re.Pattern, text: str) -> str:
    return pattern.sub(lambda m: _spaces(m.group(0)), text)


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


def vocabulary(bundle: Bundle, min_len: int = 4) -> tuple[dict[str, tuple[str, str]], dict[str, list[str]]]:
    """normalized name -> (spelling, target page), plus names claimed by several pages."""
    owners: dict[str, set[str]] = defaultdict(set)
    spelled: dict[str, str] = {}
    for rel, doc in bundle.pages("knowledge").items():
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


class _Matcher:
    """Finds names in a text, leftmost first and longest first, without overlaps."""

    def __init__(self, names: dict[str, tuple[str, str]]):
        # Acronyms, by their first word: matched case-sensitively on the text itself.
        # Each entry is (spelling, offset of that first word in the spelling), longest first.
        self.acronyms: dict[str, list[tuple[str, int]]] = defaultdict(list)
        # Other names, as tuples of folded words (and with a plural ending): matched on a folded copy.
        self.forms: set[tuple[str, ...]] = set()
        self.first_words: set[str] = set()  # what a text word must be to start a name
        self.longest = 0
        self._entries: dict[str, tuple[str, str] | None] = {}
        for key, (spelling, _) in names.items():
            if key.startswith("="):
                first = _WORD_RUN.search(spelling)
                if first:
                    self.acronyms[first.group(0)].append((spelling, first.start()))
                continue
            words = tuple(_WORDS.findall(fold(spelling)))
            if words:
                for plural in ("", "s", "es"):  # the text may add a plural ending to the last word
                    form = (*words[:-1], words[-1] + plural)
                    self.forms.add(form)
                    self.first_words.add(form[0])
                self.longest = max(self.longest, len(words))
        for spellings in self.acronyms.values():
            spellings.sort(key=lambda s: (-len(s[0]), s[0]))

    def acronym_matches(self, text: str):
        if not self.acronyms:
            return
        pos = 0
        for m in _ACRONYM_START.finditer(text):
            for spelling, lead in self.acronyms.get(m.group(0), ()):
                begin, end = m.start() - lead, m.start() - lead + len(spelling)
                if begin < pos or not text.startswith(spelling, begin):
                    continue
                if (begin and _is_word(text[begin - 1])) or (end < len(text) and _is_word(text[end])):
                    continue
                yield begin, end
                pos = end
                break

    def entry(self, matched: str, names: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
        """The (spelling, page) a matched folded text names, if any (memoized: texts repeat)."""
        if matched not in self._entries:
            entry = names.get(_key(matched))
            if entry is None:  # plural forms: 'languages' -> 'language'
                entry = names.get(_key(re.sub(r"e?s$", "", matched)))
            self._entries[matched] = entry
        return self._entries[matched]

    def phrase_matches(self, folded: str):
        """Spans of names in the folded text; a plural `s`/`es` on the last word is allowed."""
        if not self.forms:
            return
        matches = list(_WORDS.finditer(folded))
        words = [m.group(0) for m in matches]
        count, size, i = len(words), len(folded), 0
        while i < count:
            start = matches[i].start()
            # Words are whole runs of letters and digits: only a `_` can glue them to more word characters.
            if words[i] not in self.first_words or (start and folded[start - 1] == "_"):
                i += 1
                continue
            longest = 1  # how many words follow each other with only spaces, `-` or `_` between
            while (longest < self.longest and i + longest < count
                   and _SEPARATOR.fullmatch(folded, matches[i + longest - 1].end(), matches[i + longest].start())):
                longest += 1
            found = 0
            for n in range(longest, 0, -1):
                end = matches[i + n - 1].end()
                if (end == size or folded[end] != "_") and tuple(words[i : i + n]) in self.forms:
                    found = n
                    break
            if found:
                yield start, matches[i + found - 1].end()
                i += found
            else:
                i += 1


def _is_word(char: str) -> bool:
    return char.isalnum() or char == "_"


def find(bundle: Bundle, only: list[str] | None = None, min_len: int = 4, include_personal: bool = False) -> list[Mention]:
    names, _ = vocabulary(bundle, min_len)
    pages = bundle.pages("all" if include_personal else "knowledge")
    wanted = None
    if only:
        wanted = {bundle.rel(p) for p in only}
        unknown = sorted(wanted - set(pages))
        if unknown:
            raise SystemExit(f"kb: not knowledge pages in scope: {', '.join(unknown)}")
    if not names:
        return []
    matcher = _Matcher(names)

    mentions: list[Mention] = []
    for rel, doc in sorted(pages.items()):
        if wanted is not None and rel not in wanted:
            continue
        mentions += _page_mentions(bundle, rel, doc, names, matcher)
    return sorted(mentions, key=lambda m: (m.page, m.line))


def _page_mentions(bundle: Bundle, rel: str, doc: Document, names: dict, matcher: _Matcher) -> list[Mention]:
    linked = {resolve(link.path, doc.folder) for link in doc.links if not link.is_external and link.path}
    linked |= {resolve(unquote(d.target.split("#")[0]), doc.folder) for d in doc.ref_defs}
    linked |= {doc.resolve(r) for r in doc.relations(bundle.config.relations)}
    text = doc.masked_body
    for rx in (_LINK, _HEADING, _FOOTNOTE_DEF, _REF_DEF, _URL):
        text = _blank(rx, text)
    folded = _fold_same_length(text)
    body = doc.body
    seen: set[str] = set()
    out = []
    # Acronyms are matched on the original text, other names on a folded copy.
    for is_acronym, spans in ((True, matcher.acronym_matches(text)), (False, matcher.phrase_matches(folded))):
        for start, end in spans:
            entry = names.get("=" + text[start:end]) if is_acronym else matcher.entry(folded[start:end], names)
            if not entry:
                continue
            target = entry[1]
            if target == rel or target in linked or target in seen:
                continue
            seen.add(target)
            line_start = body.rfind("\n", 0, start) + 1
            line_end = body.find("\n", start)
            snippet = body[line_start : len(body) if line_end < 0 else line_end].strip()
            out.append(Mention(f"/{rel}", line_at(body, start) + doc.body_line_offset, body[start:end], f"/{target}", snippet[:160]))
    return out
