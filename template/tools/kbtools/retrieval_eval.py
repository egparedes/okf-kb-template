"""`kb eval`: do the retrieval tiers reach the pages a question needs?

Reads tools/retrieval-eval/questions.yaml and, for each question, ranks the
pages with each tier and reports recall@k of the expected pages:

- index+text: index navigation (pages whose index entry, title and
  description, contains words of the question), then `kb search`'s text
  search for the rest;
- filters: the question's optional `filters`, through the code of `kb find`;
- qmd: `qmd query`, only when the knowledge base's collection exists.

Deterministic apart from qmd's own models; no network, no LLM calls.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import finder, search
from .bundle import Bundle, load_yaml

QUESTIONS = "tools/retrieval-eval/questions.yaml"
TIERS = ("index+text", "filters", "qmd")
FILTER_KEYS = {"type": str, "tag": (str, list), "status": str, "folder": str, "trust": str}
# Question words that say nothing about the topic; they are left out of index matching.
STOPWORDS = frozenset(
    "about all and any are can could did does for from had has have how into its not our should than that the "
    "their them then there these they this those use was were what when where which who whom why will with would "
    "you your".split()
)
QMD_TIMEOUT = 600  # seconds per question; the first run of qmd downloads its models
FILTER_CHOICES = {
    "status": ("draft", "stable", "deprecated"),
    "trust": ("unverified", "machine-confirmed", "human-reviewed"),
}


@dataclass
class Question:
    question: str
    expected: list[str]  # bundle-absolute paths, e.g. /systems/dns.md
    filters: dict[str, Any] = field(default_factory=dict)


def load_questions(bundle: Bundle, path: Path) -> list[Question]:
    """Parse and validate the question file; SystemExit lists every problem found."""
    try:
        data = load_yaml(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"kb eval: cannot read {path}: {exc.strerror or exc}") from None
    except yaml.YAMLError as exc:
        raise SystemExit(f"kb eval: {path}: unparseable YAML: {exc}") from None
    if data is None:
        return []
    if not isinstance(data, dict) or set(data) - {"questions"}:
        raise SystemExit(f"kb eval: {path}: expected a mapping with one key, `questions`")
    items = data.get("questions") or []
    if not isinstance(items, list):
        raise SystemExit(f"kb eval: {path}: `questions` must be a list")
    errors: list[str] = []
    out: list[Question] = []
    for i, item in enumerate(items, start=1):
        where = f"question {i}"
        if not isinstance(item, dict):
            errors.append(f"{where}: expected a mapping with `question` and `expected`")
            continue
        for key in sorted(set(item) - {"question", "expected", "filters"}, key=str):
            errors.append(f"{where}: unknown key `{key}` (allowed: question, expected, filters)")
        text = item.get("question")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{where}: `question` must be a non-empty string")
            text = ""
        expected = item.get("expected")
        if not isinstance(expected, list) or not expected:
            errors.append(f"{where}: `expected` must be a non-empty list of /paths")
            expected = []
        for value in {e for e in expected if isinstance(e, str) and expected.count(e) > 1}:
            errors.append(f"{where}: expected page {value} is listed more than once")
        for value in expected:
            if not isinstance(value, str) or not value.startswith("/") or not value.endswith(".md"):
                errors.append(f"{where}: expected page {value!r} is not a bundle-absolute path such as /folder/page.md")
            elif value.rsplit("/", 1)[-1] == "index.md":
                errors.append(f"{where}: expected page {value} is a generated index; name the pages it lists")
            elif value[1:] not in bundle.by_rel:
                errors.append(f"{where}: expected page {value} does not exist in the bundle")
        filters = item.get("filters") or {}
        if not isinstance(filters, dict):
            errors.append(f"{where}: `filters` must be a mapping, e.g. {{type: Concept, tag: [dns]}}")
            filters = {}
        for key, value in filters.items():
            kinds = FILTER_KEYS.get(key)
            if kinds is None:
                errors.append(f"{where}: unknown filter `{key}` (allowed: {', '.join(FILTER_KEYS)})")
            elif not isinstance(value, kinds) or (isinstance(value, list) and not all(isinstance(v, str) for v in value)):
                errors.append(f"{where}: filter `{key}` must be a string" + (" or a list of strings" if key == "tag" else ""))
            elif key in FILTER_CHOICES and value not in FILTER_CHOICES[key]:
                errors.append(f"{where}: filter `{key}` must be one of {', '.join(FILTER_CHOICES[key])}")
            elif key == "type" and value not in bundle.config.types:
                errors.append(f"{where}: filter `type` {value!r} is not a type in schema/vocabulary.yaml")
            elif key == "folder" and not (bundle.root / bundle.rel(value).strip("/")).is_dir():
                errors.append(f"{where}: filter `folder` {value!r} is not a folder of the bundle")
            elif key == "tag" and value in ("", []):
                errors.append(f"{where}: filter `tag` must name at least one tag")
        out.append(Question(text.strip(), [e for e in expected if isinstance(e, str)], filters))
    if errors:
        raise SystemExit("\n".join(f"kb eval: {path}: {e}" for e in errors))
    return out


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\w-]+", text.casefold()))


def index_ranking(bundle: Bundle, query: str) -> list[str]:
    """Pages whose index entry (title and description) contains words of the query, most distinct words first.

    Whole words only, without stop words and words under 3 characters. With 3
    or more such words in the question, an entry must match at least 2 of
    them: one common word alone says little about a page.
    """
    terms = {w for w in _words(query) if len(w) >= 3 and w not in STOPWORDS}
    least = 2 if len(terms) >= 3 else 1
    scored = []
    for doc in bundle.concepts():
        if any(part.startswith((".", "_")) for part in doc.rel.parts):
            continue  # folders that get no index
        score = len(terms & _words(f"{doc.title} {doc.description}"))
        if score >= least:
            scored.append((-score, f"/{doc.rel}"))
    return [path for _, path in sorted(scored)]


def tier1_ranking(bundle: Bundle, query: str) -> list[str]:
    """Index navigation first, then the text search of `kb search` for pages the index did not surface."""
    ranking = index_ranking(bundle, query)
    seen = set(ranking)
    prefix = bundle.show("")
    for shown, _count in search.text_search(bundle, query, limit=len(bundle.documents)):
        path = "/" + shown.removeprefix(prefix)
        if path not in seen:
            seen.add(path)
            ranking.append(path)
    return ranking


def filters_ranking(bundle: Bundle, filters: dict[str, Any]) -> list[str]:
    tags = filters.get("tag")
    docs = finder.find_pages(bundle, filters.get("type"), [tags] if isinstance(tags, str) else tags,
                      filters.get("status"), filters.get("folder"), filters.get("trust"))
    return [f"/{doc.rel}" for doc in docs]


def qmd_ranking(collection: str, query: str, limit: int) -> list[str]:
    """`qmd query --json` results as bundle-absolute paths."""
    try:
        result = subprocess.run(
            ["qmd", "query", "-c", collection, "--json", "-n", str(limit), "--", query],
            capture_output=True, text=True, check=False, timeout=QMD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"`qmd query` timed out after {QMD_TIMEOUT} s") from None
    if result.returncode != 0:
        raise RuntimeError(f"`qmd query` failed (exit {result.returncode}): {result.stderr.strip()[:200]}")
    try:
        rows = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"`qmd query --json` printed no JSON: {exc}") from None
    uri = f"qmd://{collection}/"
    out = []
    for row in rows if isinstance(rows, list) else []:
        file = row.get("file", "") if isinstance(row, dict) else ""
        file = file.split("?", 1)[0] if isinstance(file, str) else ""  # qmd may append ?index=<name>
        if file.startswith(uri):
            path = "/" + file[len(uri):]
            if path not in out:
                out.append(path)
    return out


def score(ranking: list[str], expected: list[str], k: int) -> dict[str, Any]:
    """Rank of the first expected page (1-based, anywhere in the ranking) and recall@k.

    Pages are compared case-insensitively. qmd reports paths with their case
    as on disk, so this is only a safeguard; bundle paths are kebab-case.
    """
    folded = [p.casefold() for p in ranking]
    wanted = [e.casefold() for e in expected]
    ranks = [folded.index(e) + 1 for e in wanted if e in folded]
    found = [e for e, w in zip(expected, wanted, strict=True) if w in folded[:k]]
    return {
        "status": "ok",
        "rank": min(ranks) if ranks else None,
        "found": found,
        "recall": len(found) / len(expected),
        "hit": bool(found),
        "top": ranking[:k],
    }


def evaluate(bundle: Bundle, questions: list[Question], k: int, use_qmd: bool = True) -> dict[str, Any]:
    collection = search.qmd_collection(bundle)
    qmd_skip = "disabled with --no-qmd" if not use_qmd else None
    if qmd_skip is None and not search.qmd_ready(collection):
        qmd_skip = f"qmd is not set up: no collection `{collection}`"
    if qmd_skip is None and questions:
        print(f"kb eval: running `qmd query` for {len(questions)} question(s); the first run may download qmd's models",
              file=sys.stderr, flush=True)
    results = []
    for q in questions:
        tiers: dict[str, Any] = {"index+text": score(tier1_ranking(bundle, q.question), q.expected, k)}
        tiers["filters"] = (
            score(filters_ranking(bundle, q.filters), q.expected, k) if q.filters
            else {"status": "skipped", "reason": "no filters"}
        )
        if qmd_skip:
            tiers["qmd"] = {"status": "skipped", "reason": qmd_skip}
        else:
            try:
                tiers["qmd"] = score(qmd_ranking(collection, q.question, max(k, 20)), q.expected, k)
            except RuntimeError as exc:
                tiers["qmd"] = {"status": "error", "reason": str(exc)}
        results.append({"question": q.question, "expected": q.expected, "filters": q.filters, "tiers": tiers})
    summary = {}
    for tier in TIERS:
        ran = [r["tiers"][tier] for r in results if r["tiers"][tier]["status"] == "ok"]
        summary[tier] = {
            "questions": len(ran),
            "hits": sum(t["hit"] for t in ran),
            "recall": sum(t["recall"] for t in ran) / len(ran) if ran else None,
        }
    if qmd_skip:
        summary["qmd"]["skipped"] = qmd_skip
    return {"k": k, "questions": results, "summary": summary}


def _cell(tier: dict[str, Any], expected: int) -> str:
    if tier["status"] == "skipped":
        return "-" if tier["reason"] == "no filters" else "skipped"
    if tier["status"] == "error":
        return "error"
    return f"{len(tier['found'])}/{expected} @{tier['rank'] or '-'}"


def to_text(result: dict[str, Any]) -> str:
    k = result["k"]
    lines = [f"{'#':>3}  {'index+text':<11} {'filters':<11} {'qmd':<11} question"]
    for i, r in enumerate(result["questions"], start=1):
        cells = [_cell(r["tiers"][t], len(r["expected"])) for t in TIERS]
        lines.append(f"{i:>3}  {cells[0]:<11} {cells[1]:<11} {cells[2]:<11} {r['question']}")
        for tier in TIERS:
            if r["tiers"][tier]["status"] == "error":
                lines.append(f"     {tier}: {r['tiers'][tier]['reason']}")
    parts = []
    for tier in TIERS:
        s = result["summary"][tier]
        if s.get("skipped"):
            parts.append(f"{tier} skipped ({s['skipped']})")
        elif s["recall"] is None:
            parts.append(f"{tier} not run")
        else:
            parts.append(f"{tier} {s['recall']:.2f} ({s['hits']}/{s['questions']} hit)")
    lines.append("")
    lines.append(f"cells: expected pages in the top {k} / expected pages, @rank of the first expected page")
    lines.append(f"kb eval: {len(result['questions'])} question(s), recall@{k}: " + "; ".join(parts))
    return "\n".join(lines) + "\n"


def run(bundle: Bundle, questions_path: str | None, k: int = 10, as_json: bool = False,
        min_recall: float | None = None, use_qmd: bool = True) -> int:
    if k < 1:
        raise SystemExit("kb eval: --k must be at least 1")
    if min_recall is not None and not 0 <= min_recall <= 1:
        raise SystemExit("kb eval: --min-recall must be between 0 and 1")
    path = Path(questions_path) if questions_path else bundle.repo_root / QUESTIONS
    questions = load_questions(bundle, path)
    if not questions and not as_json:
        print(f"kb eval: no questions in {path}; its header comment explains the format")
        return 0
    result = evaluate(bundle, questions, k, use_qmd)
    sys.stdout.write(json.dumps(result, indent=2) + "\n" if as_json else to_text(result))
    recall = result["summary"]["index+text"]["recall"]
    if min_recall is not None and recall is not None and recall < min_recall:
        print(f"kb eval: index+text recall@{k} {recall:.2f} is below --min-recall {min_recall}", file=sys.stderr)
        return 1
    return 0
