"""Link-graph analytics for the maintain workflow (`kb graph`).

Nodes are knowledge pages identified by bundle path. Reserved and generated
files (every index.md and log.md), `_`-prefixed vault folders and, by
default, the human's personal areas are excluded structurally, so generated
index hubs never distort the metrics. Source pages form a separate citation
layer: links to and from them are counted as citations, not as topical links.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations

from .bundle import Bundle, Document
from .report import trust_tier

SYNTHESIS_TYPES = ("Synthesis", "Comparison")


@dataclass
class Graph:
    pages: dict[str, Document]  # knowledge pages (graph nodes)
    out: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    inc: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    relations: Counter = field(default_factory=Counter)  # relation key -> edge count
    cited_by: Counter = field(default_factory=Counter)  # source page -> citing pages

    def add(self, src: str, dst: str) -> None:
        if src != dst:
            self.out[src].add(dst)
            self.inc[dst].add(src)


def build(bundle: Bundle, scope: str = "knowledge") -> Graph:
    candidates = bundle.pages(scope)
    sources = {rel for rel, d in candidates.items() if d.type == "Source"}
    graph = Graph(pages={rel: d for rel, d in candidates.items() if rel not in sources})
    for rel, doc in candidates.items():
        targets = {t for t in doc.link_targets if t}
        for relation in doc.relations(bundle.config.relations):
            target = doc.resolve(relation)
            if target:
                targets.add(target)
                if rel in graph.pages and target in graph.pages:
                    graph.relations[relation.key] += 1
        for target in targets:
            if rel in sources or target in sources:
                if target in sources and rel not in sources:
                    graph.cited_by[target] += 1
                continue
            if rel in graph.pages and target in graph.pages:
                graph.add(rel, target)
    return graph


def pagerank(graph: Graph, damping: float = 0.85, iterations: int = 60) -> dict[str, float]:
    nodes = list(graph.pages)
    n = len(nodes)
    if n == 0:
        return {}
    rank = {v: 1.0 / n for v in nodes}
    for _ in range(iterations):
        dangling = sum(rank[v] for v in nodes if not graph.out.get(v))
        new = {v: (1 - damping) / n + damping * dangling / n for v in nodes}
        for v in nodes:
            targets = graph.out.get(v)
            if targets:
                share = damping * rank[v] / len(targets)
                for t in targets:
                    new[t] += share
        rank = new
    return rank


def components(graph: Graph) -> list[list[str]]:
    parent = {v: v for v in graph.pages}

    def find(v: str) -> str:
        while parent[v] != v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v

    for src, targets in graph.out.items():
        for dst in targets:
            parent[find(src)] = find(dst)
    groups: dict[str, list[str]] = defaultdict(list)
    for v in graph.pages:
        groups[find(v)].append(v)
    return sorted((sorted(g) for g in groups.values()), key=lambda g: (-len(g), g))


def tag_cohesion(graph: Graph, min_pages: int = 5, threshold: float = 0.15) -> list[tuple[str, int, float]]:
    by_tag: dict[str, list[str]] = defaultdict(list)
    for rel, doc in graph.pages.items():
        for tag in doc.frontmatter.get("tags") or []:
            by_tag[str(tag)].append(rel)
    weak = []
    for tag, members in sorted(by_tag.items()):
        n = len(members)
        if n < min_pages:
            continue
        linked = sum(1 for a, b in combinations(members, 2) if b in graph.out.get(a, ()) or a in graph.out.get(b, ()))
        density = linked / (n * (n - 1) / 2)
        if density < threshold:
            weak.append((tag, n, round(density, 3)))
    return weak


def colink_gaps(graph: Graph, min_count: int = 3, max_out: int = 60) -> list[tuple[str, str, int]]:
    """Pairs of pages linked together from several pages but never discussed side by side."""
    counts: Counter = Counter()
    for targets in graph.out.values():
        if len(targets) <= max_out:
            counts.update(combinations(sorted(targets), 2))
    covered: set[tuple[str, str]] = set()
    for rel, doc in graph.pages.items():
        if doc.type in SYNTHESIS_TYPES:
            covered.update(combinations(sorted(graph.out.get(rel, ())), 2))
    gaps = [
        (a, b, n)
        for (a, b), n in counts.items()
        if n >= min_count
        and (a, b) not in covered
        and graph.pages[a].type not in SYNTHESIS_TYPES
        and graph.pages[b].type not in SYNTHESIS_TYPES
    ]
    return sorted(gaps, key=lambda g: (-g[2], g[0], g[1]))


def analyze(bundle: Bundle, scope: str = "knowledge", top: int = 15) -> dict:
    graph = build(bundle, scope)
    rank = pagerank(graph)
    ordered = sorted(rank, key=lambda v: (-rank[v], v))
    comps = components(graph)
    pages = graph.pages
    indeg = {v: len(graph.inc.get(v, ())) for v in pages}
    outdeg = {v: len(graph.out.get(v, ())) for v in pages}
    return {
        "scope": scope,
        "pages": len(pages),
        "links": sum(outdeg.values()),
        "relation_edges": dict(graph.relations),
        "components": {
            "count": len(comps),
            "largest": len(comps[0]) if comps else 0,
            "small": [c for c in comps if 1 < len(c) <= 3],
        },
        "top_pagerank": [
            {"page": f"/{v}", "score": round(rank[v], 4), "in": indeg[v], "out": outdeg[v]} for v in ordered[:top]
        ],
        "orphans": [f"/{v}" for v in sorted(pages) if indeg[v] == 0 and pages[v].type not in SYNTHESIS_TYPES],
        "dead_ends": [f"/{v}" for v in sorted(pages) if outdeg[v] == 0],
        "sink_hubs": [f"/{v}" for v in sorted(pages) if indeg[v] >= 3 and outdeg[v] == 0],
        "weak_tags": [{"tag": t, "pages": n, "density": d} for t, n, d in tag_cohesion(graph)],
        "colink_gaps": [{"a": f"/{a}", "b": f"/{b}", "co_linked_by": n} for a, b, n in colink_gaps(graph)[:top]],
        "review_first": [
            {
                "page": f"/{v}",
                "score": round(rank[v], 4),
                "trust": trust_tier(pages[v]),
                "cited": bool(pages[v].frontmatter.get("sources")),
            }
            for v in ordered
            if trust_tier(pages[v]) == "unverified" or not pages[v].frontmatter.get("sources")
        ][:top],
    }


def to_markdown(result: dict) -> str:
    lines = [
        f"# Link graph ({result['scope']} scope)",
        "",
        f"{result['pages']} pages, {result['links']} links, "
        f"{result['components']['count']} components (largest {result['components']['largest']}).",
        "",
    ]

    def section(title: str, items: list[str]) -> None:
        if not items:
            return
        lines.extend([f"## {title} ({len(items)})", ""])
        lines.extend(f"* {item}" for item in items)
        lines.append("")

    section(
        "Most central (PageRank)",
        [f"{e['page']} - {e['score']} (in {e['in']}, out {e['out']})" for e in result["top_pagerank"]],
    )
    section(
        "Review first: central but unverified or uncited",
        [f"{e['page']} - {e['trust']}{'' if e['cited'] else ', no sources'}" for e in result["review_first"]],
    )
    section("Orphans (nothing links here)", result["orphans"])
    section("Dead ends (link nowhere)", result["dead_ends"])
    section("Sink hubs (3+ inbound, no outbound)", result["sink_hubs"])
    section(
        "Small islands (components of 2-3 pages)",
        [", ".join(f"/{p}" for p in c) for c in result["components"]["small"]],
    )
    section(
        "Weakly linked tags (5+ pages, density < 0.15)",
        [f"{t['tag']} - {t['pages']} pages, density {t['density']}" for t in result["weak_tags"]],
    )
    section(
        "Co-link gaps (linked together often, no synthesis or comparison)",
        [f"{g['a']} + {g['b']} - co-linked by {g['co_linked_by']} pages" for g in result["colink_gaps"]],
    )
    return "\n".join(lines).rstrip() + "\n"
