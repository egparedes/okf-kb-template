"""Name normalization shared by `kb dupes` and `kb unlinked`."""

from __future__ import annotations

import re
import unicodedata

from .bundle import Document

STOPWORDS = frozenset(
    "a an and at by for from in into of on or the to vs with without".split()
)
_NON_WORD = re.compile(r"[^\w]+")


def fold(text: str) -> str:
    """Casefold and strip diacritics: 'Écoles' -> 'ecoles'."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def tokens(name: str) -> tuple[str, ...]:
    """Normalized content words; a naive plural strip keeps 'stencils' == 'stencil'.

    `C++` and `C#` stay distinct from `C` (-> 'cpp', 'csharp').
    """
    name = re.sub(r"(\w)\+\+", r"\1pp", name)
    name = re.sub(r"(\w)#", r"\1sharp", name)
    words = [w for w in _NON_WORD.split(fold(name).replace("_", " ")) if w]
    out = []
    for word in words:
        if word in STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.append(word)
    return tuple(out)


def acronym(name: str) -> str:
    """Initials of the content words: 'Domain Specific Language' -> 'dsl'."""
    return "".join(t[0] for t in tokens(name))


def page_names(doc: Document) -> list[str]:
    """Title, aliases and file stem of a page, deduplicated in that order."""
    names = [doc.title]
    aliases = doc.frontmatter.get("aliases") or []
    names += [a for a in aliases if isinstance(a, str)]
    names.append(doc.rel.stem.replace("-", " "))
    seen: set[tuple[str, ...]] = set()
    unique = []
    for name in names:
        key = tokens(name)
        if key and key not in seen:
            seen.add(key)
            unique.append(name)
    return unique
