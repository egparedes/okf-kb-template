"""Deterministic near-duplicate candidates (`kb dupes`).

The command only proposes pairs, with the signals that fired; deciding and
merging is the agent's job in the maintain workflow (then `kb merge`).
Pairs are suppressed when the pages are already related as distinct
(`alternative_to`, `supersedes`, `contradicts`) or listed in
`schema/distinct.yaml`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from itertools import combinations

from .bundle import Bundle, Document, load_yaml
from .names import acronym, page_names, tokens

DISTINCT_RELATIONS = ("alternative_to", "supersedes", "contradicts")
_WORD = re.compile(r"\w+")
MAX_BLOCK = 200  # pages sharing one name token or prefix; bigger blocks are too common to compare


@dataclass
class Candidate:
    a: str
    b: str
    score: float
    signals: list[str] = field(default_factory=list)


def _jaccard(x: set, y: set) -> float:
    return len(x & y) / len(x | y) if x and y else 0.0


def _shingles(doc: Document, size: int = 5) -> set[tuple[str, ...]]:
    words = _WORD.findall(doc.masked_body.casefold())
    return {tuple(words[i : i + size]) for i in range(len(words) - size + 1)}


def _distinct_pairs(bundle: Bundle, docs: dict[str, Document]) -> set[frozenset]:
    pairs: set[frozenset] = set()
    for rel, doc in docs.items():
        for relation in doc.relations(DISTINCT_RELATIONS):
            target = doc.resolve(relation)
            if target:
                pairs.add(frozenset((rel, target)))
    path = bundle.repo_root / "schema" / "distinct.yaml"
    if path.is_file():
        for pair in (load_yaml(path.read_text(encoding="utf-8")) or {}).get("distinct") or []:
            if isinstance(pair, list) and len(pair) == 2:
                pairs.add(frozenset(str(p).lstrip("/") for p in pair))
    return pairs


def find(bundle: Bundle, min_score: float = 0.6, body: bool = False, scope: str = "knowledge") -> list[Candidate]:
    docs = bundle.pages(scope)
    names = {rel: [tokens(n) for n in page_names(doc)] for rel, doc in docs.items()}
    acronyms = {rel: {acronym(n) for n in page_names(doc) if len(tokens(n)) >= 2} for rel, doc in docs.items()}
    distinct = _distinct_pairs(bundle, docs)

    # Blocking: only compare pages that share a name token, a 4-letter token
    # prefix (catches typos), an acronym, a whole name or a resource. Blocks of
    # a common token are too big to compare pairwise and are skipped; whole
    # names (`n:`) and resources (`r:`) are exact matches and always compared.
    blocks: dict[str, set[str]] = defaultdict(set)
    for rel, doc in docs.items():
        for name in names[rel]:
            blocks["n:" + " ".join(name)].add(rel)
            for token in name:
                blocks[f"t:{token}"].add(rel)
                blocks[f"p:{token[:4]}"].add(rel)
            if len(name) == 1:
                blocks[f"a:{name[0]}"].add(rel)
        for acr in acronyms[rel]:
            blocks[f"a:{acr}"].add(rel)
        resource = doc.frontmatter.get("resource")
        if isinstance(resource, str) and resource:
            blocks[f"r:{resource.rstrip('/')}"].add(rel)
    pairs: set[tuple[str, str]] = set()
    for key, members in blocks.items():
        if len(members) <= MAX_BLOCK or key.startswith(("n:", "r:")):
            pairs.update(combinations(sorted(members), 2))

    shingles = {rel: _shingles(doc) for rel, doc in docs.items()} if body else {}
    found = []
    for a, b in sorted(pairs):
        if frozenset((a, b)) in distinct:
            continue
        da, db = docs[a], docs[b]
        if (da.type == "Source") != (db.type == "Source"):
            continue  # a Source summary legitimately shares names with the concept it feeds
        if da.type == db.type == "Journal Entry":
            continue  # dated titles look alike; journal entries are never merged
        signals: list[str] = []
        score = 0.0
        if set(names[a]) & set(names[b]):
            score, signals = 1.0, ["same name"]
        ra, rb = da.frontmatter.get("resource"), db.frontmatter.get("resource")
        if isinstance(ra, str) and ra and ra.rstrip("/") == str(rb or "").rstrip("/"):
            score = 1.0
            signals.append("same resource")
        singles_a = {n[0] for n in names[a] if len(n) == 1}
        singles_b = {n[0] for n in names[b] if len(n) == 1}
        if (acronyms[a] & singles_b) or (acronyms[b] & singles_a):
            score = max(score, 0.9)
            signals.append("acronym")
        best_j = max((_jaccard(set(x), set(y)) for x in names[a] for y in names[b]), default=0.0)
        if best_j >= 0.5:
            score = max(score, best_j)
            signals.append(f"name overlap {best_j:.2f}")
        best_r = 0.0
        for x in names[a]:
            for y in names[b]:
                sm = SequenceMatcher(None, " ".join(x), " ".join(y))
                if sm.quick_ratio() >= 0.85:
                    best_r = max(best_r, sm.ratio())
        if best_r >= 0.85:
            score = max(score, best_r)
            signals.append(f"similar spelling {best_r:.2f}")
        if body:
            overlap = _jaccard(shingles[a], shingles[b])
            if overlap >= 0.3:
                score = max(score, 0.5 + overlap / 2)
                signals.append(f"shared text {overlap:.2f}")
        if not signals:
            continue
        desc = _jaccard(set(tokens(da.description)), set(tokens(db.description)))
        if desc >= 0.5:
            score += 0.1
            signals.append(f"similar description {desc:.2f}")
        if da.folder == db.folder:
            score += 0.05
            signals.append("same folder")
        if len(set(da.frontmatter.get("tags") or []) & set(db.frontmatter.get("tags") or [])) >= 2:
            score += 0.05
            signals.append("shared tags")
        score = min(round(score, 2), 1.0)
        if score >= min_score:
            found.append(Candidate(a, b, score, signals))
    return sorted(found, key=lambda c: (-c.score, c.a, c.b))
