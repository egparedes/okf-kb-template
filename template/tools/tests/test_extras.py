"""Tests for graph analytics, dedup, unlinked mentions, merge and external resources."""

from __future__ import annotations

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from kbtools import dupes, graph, indexgen, linkfix, pages, resources, unlinked
from kbtools.bundle import Bundle
from kbtools.check import Checker

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(FIXTURES / "schema", tmp_path / "schema")
    shutil.copy(REPO / "schema" / "frontmatter.schema.json", tmp_path / "schema")
    (tmp_path / "kb").mkdir()
    for var in ("ZOTERO_API_KEY", "ZOTERO_DATA_DIR", "ZOTERO_USER_ID", "KARAKEEP_URL", "KARAKEEP_API_KEY", "KB_ROOT_NOTES"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def write(repo: Path, rel: str, title: str, body: str = "", extra: str = "", type_: str = "Concept") -> Path:
    path = repo / "kb" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntype: {type_}\ntitle: {title}\ndescription: {title} in one sentence.\ntags: [test]\n"
        f"status: stable\ngenerated: {{ by: test/0, at: 2026-09-25T12:00:00Z }}\n{extra}---\n\n{body}",
        encoding="utf-8",
    )
    return path


def bundle(repo: Path) -> Bundle:
    return Bundle(repo / "kb", repo)


# -- graph -------------------------------------------------------------------------


def test_graph_excludes_generated_hubs_and_separates_citations(repo: Path) -> None:
    write(repo, "systems/a.md", "A", "[B](/systems/b.md) [B again](/systems/b.md) [C](/data/c.md)")
    write(repo, "systems/b.md", "B", "[C](/data/c.md)")
    write(repo, "data/c.md", "C", "Cites.[^s]\n\n[^s]: [S](/sources/s.md)", "sources:\n  - id: s\n    resource: /sources/s.md\n")
    write(repo, "data/lonely.md", "Lonely")
    write(repo, "sources/s.md", "S", "Pages updated: [A](/systems/a.md)", "resource: https://example.org\n", "Source")
    indexgen.write(bundle(repo))
    result = graph.analyze(bundle(repo))
    assert result["pages"] == 4  # sources and index.md files are not nodes
    assert result["links"] == 3  # duplicate links collapse
    assert result["top_pagerank"][0]["page"] == "/data/c.md"
    assert "/data/lonely.md" in result["orphans"] and "/systems/a.md" in result["orphans"]
    assert "/data/c.md" in result["dead_ends"]
    assert graph.build(bundle(repo)).cited_by["sources/s.md"] == 1


def test_colink_gaps_and_weak_tags(repo: Path) -> None:
    for i in range(3):
        write(repo, f"systems/p{i}.md", f"P{i}", "[X](/data/x.md) and [Y](/data/y.md)")
    write(repo, "data/x.md", "X")
    write(repo, "data/y.md", "Y")
    for i in range(10):
        write(repo, f"data/island{i}.md", f"Island {i}")
    result = graph.analyze(bundle(repo))
    assert {"a": "/data/x.md", "b": "/data/y.md", "co_linked_by": 3} in result["colink_gaps"]
    assert result["weak_tags"][0]["tag"] == "test"


# -- dupes ---------------------------------------------------------------------------


def test_dupes_signals_and_suppression(repo: Path) -> None:
    write(repo, "programming/dsl.md", "Domain-specific languages")
    write(repo, "programming/dsls-intro.md", "DSL")
    write(repo, "operations/kubernetes.md", "Kubernetes")
    write(repo, "operations/kubernets.md", "Kubernets")
    write(repo, "systems/raft.md", "Raft consensus", extra='alternative_to: ["[Paxos consensus](/systems/paxos.md)"]\n')
    write(repo, "systems/paxos.md", "Paxos consensus")
    pairs = {(c.a, c.b): c for c in dupes.find(bundle(repo))}
    assert ("programming/dsl.md", "programming/dsls-intro.md") in pairs
    assert "acronym" in pairs[("programming/dsl.md", "programming/dsls-intro.md")].signals
    assert ("operations/kubernetes.md", "operations/kubernets.md") in pairs
    assert ("systems/paxos.md", "systems/raft.md") not in pairs


def test_distinct_file_suppresses_pairs(repo: Path) -> None:
    write(repo, "systems/a.md", "Stencil computation")
    write(repo, "data/b.md", "Stencil computations")
    assert dupes.find(bundle(repo))
    (repo / "schema" / "distinct.yaml").write_text("distinct:\n  - [/systems/a.md, /data/b.md]\n")
    assert dupes.find(bundle(repo)) == []


# -- unlinked --------------------------------------------------------------------------


def test_unlinked_mentions(repo: Path) -> None:
    write(repo, "programming/dsl.md", "Domain-specific language", extra="aliases: [DSL]\n")
    write(repo, "programming/halide.md", "Halide",
          "Halide is a domain specific languages family.\n\n# Domain-specific language\n\n`DSL` in code.\n")
    write(repo, "programming/other.md", "Other", "Uses a DSL, see [DSL](/programming/dsl.md).")
    write(repo, "programming/case.md", "Case", "a dsl in lower case is not the acronym.")
    found = unlinked.find(bundle(repo))
    assert [(m.page, m.target, m.text) for m in found] == [
        ("/programming/halide.md", "/programming/dsl.md", "domain specific languages")
    ]


def test_unlinked_reports_ambiguous_names(repo: Path) -> None:
    write(repo, "systems/a.md", "Scheduler")
    write(repo, "hpc/b.md", "Scheduler")
    _, ambiguous = unlinked.vocabulary(bundle(repo))
    assert ambiguous == {"Scheduler": ["hpc/b.md", "systems/a.md"]}


# -- merge ----------------------------------------------------------------------------


def test_merge_unions_metadata_and_retargets(repo: Path) -> None:
    write(repo, "systems/old.md", "Old name", extra="aliases: [Legacy]\nsources:\n  - id: s1\n    resource: https://a.org\n")
    write(repo, "systems/new.md", "New name", extra="sources:\n  - id: s2\n    resource: https://b.org\n")
    ref = write(repo, "data/ref.md", "Ref", "See [old](/systems/old.md#x).",
                'related: ["[Old](/systems/old.md)"]\n')
    linkfix.merge(bundle(repo), "systems/old.md", "systems/new.md", "test/0")
    assert not (repo / "kb/systems/old.md").exists()
    merged = bundle(repo).by_rel["systems/new.md"].frontmatter
    assert merged["aliases"] == ["Legacy", "Old name"]
    assert [s["id"] for s in merged["sources"]] == ["s2", "s1"]
    text = ref.read_text()
    assert "[old](/systems/new.md#x)" in text and '"[Old](/systems/new.md)"' in text


# -- external resources --------------------------------------------------------------


class _Fake(BaseHTTPRequestHandler):
    routes: dict = {}

    def _reply(self, status: int, body) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        handler = self.routes.get(("GET", url.path))
        self._reply(*(handler(parse_qs(url.query), self.headers) if handler else (404, {})))

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        handler = self.routes.get(("POST", urlparse(self.path).path))
        self._reply(*(handler(body, self.headers) if handler else (404, {})))

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def server():
    routes: dict = {}
    handler = type("Handler", (_Fake,), {"routes": routes})
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", routes
    httpd.shutdown()


ITEM = {"key": "ABCD2345", "itemType": "journalArticle", "title": "Roofline: an insightful model",
        "creators": [{"creatorType": "author", "lastName": "Williams"}], "date": "2009-04",
        "DOI": "10.1145/1498765.1498785", "citationKey": "williams2009roofline"}


def zotero_routes(routes: dict, base: str) -> None:
    routes[("GET", "/api/users/0/items/ABCD2345")] = lambda q, h: (200, {"key": "ABCD2345", "data": ITEM})
    routes[("GET", "/api/users/0/items/top")] = lambda q, h: (200, [{"data": ITEM}])
    routes[("GET", "/api/users/0/items/ABCD2345/children")] = lambda q, h: (
        200, [{"data": {"key": "PDF23456", "itemType": "attachment"}}, {"data": {"key": "NOTE2345", "itemType": "note"}}])
    routes[("GET", "/api/users/0/items/PDF23456/fulltext")] = lambda q, h: (200, {"content": "The roofline model ..."})


def test_zotero_local_api_fetch_and_new_source(repo: Path, server, monkeypatch) -> None:
    base, routes = server
    zotero_routes(routes, base)
    monkeypatch.setenv("ZOTERO_LOCAL_API", f"{base}/api/users/0")
    b = bundle(repo)
    out = resources.fetch(b, "zotero:williams2009roofline", repo / ".cache" / "sources")
    assert out.name == "williams-2009-roofline.md" and "roofline model" in out.read_text()
    fm = resources.zotero_source_frontmatter(ITEM, resources.Settings.load(b))
    path = pages.new_page(b, "Source", "sources/williams2009roofline.md", fm.pop("title"), fm.pop("description"),
                          [], "test/0", status="draft", resource=fm.pop("resource"), extra=fm)
    text = path.read_text()
    assert "resource: https://doi.org/10.1145/1498765.1498785" in text and "citekey: williams2009roofline" in text
    indexgen.write(bundle(repo))
    assert [str(d) for d in Checker(bundle(repo)).check_all()] == []


def test_zotero_falls_back_to_storage_cache(repo: Path, server, monkeypatch, tmp_path: Path) -> None:
    base, routes = server
    zotero_routes(routes, base)
    del routes[("GET", "/api/users/0/items/PDF23456/fulltext")]
    cache = tmp_path / "zotero" / "storage" / "PDF23456" / ".zotero-ft-cache"
    cache.parent.mkdir(parents=True)
    cache.write_text("text from the storage cache")
    monkeypatch.setenv("ZOTERO_LOCAL_API", f"{base}/api/users/0")
    monkeypatch.setenv("ZOTERO_DATA_DIR", str(tmp_path / "zotero"))
    out = resources.fetch(bundle(repo), "zotero:ABCD2345", repo / ".cache")
    assert "storage cache" in out.read_text()


def test_zotero_unreachable_explains_setup(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZOTERO_LOCAL_API", "http://127.0.0.1:9/api/users/0")
    with pytest.raises(SystemExit, match="Allow other applications"):
        resources.fetch(bundle(repo), "zotero:ABCD2345", repo / ".cache")


def test_karakeep_by_url_on_any_instance(repo: Path, server, monkeypatch) -> None:
    base, routes = server
    saved: dict = {}

    def check(q, h):
        assert h["Authorization"] == "Bearer secret"
        return 200, {"bookmarkId": saved.get(q["url"][0])}

    def create(body, h):
        saved[body["url"]] = "bm1"
        return 201, {"id": "bm1"}

    routes[("GET", "/api/v1/bookmarks/check-url")] = check
    routes[("POST", "/api/v1/bookmarks")] = create
    routes[("GET", "/api/v1/bookmarks/bm1/content")] = lambda q, h: (
        (200, {"content": "part two", "nextCursor": None}) if q.get("cursor")
        else (200, {"content": "part one, ", "nextCursor": "c2"}))
    (repo / ".env").write_text(f"KARAKEEP_URL={base}\nKARAKEEP_API_KEY=secret\n")
    out = resources.fetch(bundle(repo), "https://example.org/post", repo / ".cache")
    assert out.read_text().endswith("part one, part two") and saved == {"https://example.org/post": "bm1"}


def test_file_roots_and_deny(repo: Path, monkeypatch, tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    (notes / "private").mkdir(parents=True)
    (notes / "talk.md").write_text("slides text")
    (notes / "private" / "x.md").write_text("secret")
    (repo / "schema" / "resources.yaml").write_text("roots:\n  notes: Notes.\ndeny: ['notes/private/**']\n")
    monkeypatch.setenv("KB_ROOT_NOTES", str(notes))
    assert "slides text" in resources.fetch(bundle(repo), "file:notes/talk.md", repo / ".cache").read_text()
    with pytest.raises(SystemExit, match="deny"):
        resources.fetch(bundle(repo), "file:notes/private/x.md", repo / ".cache")
    with pytest.raises(SystemExit, match="escapes"):
        resources.fetch(bundle(repo), "file:notes/../notes2/y.md", repo / ".cache")
    write(repo, "systems/t.md", "T", extra='locators: ["file:talks/x.pdf"]\n')
    assert "W060" in [d.code for d in Checker(bundle(repo)).check_all()]


def test_zotero_offline_database_snapshot(repo: Path, monkeypatch, tmp_path: Path) -> None:
    import sqlite3

    data = tmp_path / "zotero"
    (data / "storage" / "PDF23456").mkdir(parents=True)
    (data / "storage" / "PDF23456" / ".zotero-ft-cache").write_text("offline full text")
    db = sqlite3.connect(data / "zotero.sqlite")
    db.executescript("""
        CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
        CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INT, key TEXT);
        CREATE TABLE deletedItems (itemID INT);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT);
        CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);
        CREATE TABLE creatorTypes (creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT);
        CREATE TABLE itemCreators (itemID INT, creatorID INT, creatorTypeID INT, orderIndex INT);
        CREATE TABLE itemAttachments (itemID INT, parentItemID INT);
        INSERT INTO itemTypes VALUES (1, 'journalArticle'), (2, 'attachment');
        INSERT INTO items VALUES (1, 1, 'ABCD2345'), (2, 2, 'PDF23456');
        INSERT INTO fields VALUES (1, 'title'), (2, 'citationKey'), (3, 'date');
        INSERT INTO itemDataValues VALUES (1, 'Roofline model'), (2, 'williams2009roofline'), (3, '2009-04-01');
        INSERT INTO itemData VALUES (1, 1, 1), (1, 2, 2), (1, 3, 3);
        INSERT INTO creators VALUES (1, 'Samuel', 'Williams');
        INSERT INTO creatorTypes VALUES (1, 'author');
        INSERT INTO itemCreators VALUES (1, 1, 1, 0);
        INSERT INTO itemAttachments VALUES (2, 1);
    """)
    db.commit()
    db.close()
    monkeypatch.setenv("ZOTERO_LOCAL_API", "http://127.0.0.1:9/api/users/0")  # Zotero closed
    monkeypatch.setenv("ZOTERO_DATA_DIR", str(data))
    zotero = resources.Zotero(resources.Settings.load(bundle(repo)))
    assert [i["key"] for i in zotero.search("Williams")] == ["ABCD2345"]
    assert zotero.item("williams2009roofline")["title"] == "Roofline model"
    out = resources.fetch(bundle(repo), "zotero:williams2009roofline", repo / ".cache")
    assert "offline full text" in out.read_text() and "database snapshot" in out.read_text()


# -- round-2 review regressions ----------------------------------------------------


def _roots(repo: Path, tmp_path: Path, monkeypatch, deny: str) -> Path:
    base = tmp_path / "docs"
    (base / "Personal").mkdir(parents=True)
    (base / "pub").mkdir()
    (base / "[Zotero]").mkdir()
    (base / "Personal" / "secret.md").write_text("secret")
    (base / "pub" / "ok.md").write_text("public")
    (base / "[Zotero]" / "z.md").write_text("zotero")
    (base / "pub" / "link").symlink_to(base / "Personal")
    (repo / "schema" / "resources.yaml").write_text(f"roots:\n  docs: Docs.\ndeny: {deny}\n")
    monkeypatch.setenv("KB_ROOT_DOCS", str(base))
    return base


@pytest.mark.parametrize("ref", [
    "file:docs/Personal/secret.md", "file:docs/pub/../Personal/secret.md", "file:docs/./Personal/secret.md",
    "file:docs/pub/link/secret.md", "file:docs/[Zotero]/z.md",
])
def test_deny_cannot_be_bypassed(repo: Path, tmp_path: Path, monkeypatch, ref: str) -> None:
    _roots(repo, tmp_path, monkeypatch, "['docs/Personal', 'docs/[Zotero]/**']")
    with pytest.raises(SystemExit, match="deny"):
        resources.fetch(bundle(repo), ref, repo / ".cache")
    assert "public" in resources.fetch(bundle(repo), "file:docs/pub/ok.md", repo / ".cache").read_text()


def test_local_deny_patterns_and_denied_locators(repo: Path, tmp_path: Path, monkeypatch) -> None:
    _roots(repo, tmp_path, monkeypatch, "[]")
    (repo / ".env").write_text("KB_DENY=docs/pub/ok.md ; docs/Personal\n")
    monkeypatch.delenv("KB_DENY", raising=False)
    with pytest.raises(SystemExit, match="deny"):
        resources.fetch(bundle(repo), "file:docs/pub/ok.md", repo / ".cache")
    write(repo, "systems/t.md", "T", extra='locators: ["file:docs/Personal/secret.md"]\n')
    assert "H060" in [d.code for d in Checker(bundle(repo)).check_all()]


def test_env_parsing(repo: Path, monkeypatch) -> None:
    for var in ("A_ONE", "A_TWO", "A_THREE", "A_FOUR"):
        monkeypatch.delenv(var, raising=False)
    (repo / ".env").write_text("A_ONE=/x/y   # comment\nexport A_TWO=two\nA_THREE=\"quoted # kept\"\nA_FOUR='x\n")
    resources.load_env(repo)
    import os
    assert (os.environ["A_ONE"], os.environ["A_TWO"], os.environ["A_THREE"], os.environ["A_FOUR"]) == ("/x/y", "two", "quoted # kept", "'x")


def test_malformed_resources_config_is_a_diagnostic(repo: Path) -> None:
    (repo / "schema" / "resources.yaml").write_text("roots: [a, b]\ndeny: nope\n")
    assert [d.code for d in Checker(bundle(repo)).check_all()].count("H061") == 2


@pytest.mark.parametrize("args", [("systems/a.md", "systems/a.md"), ("log.md", "systems/a.md"), ("../outside.md", "systems/a.md")])
def test_merge_refuses_unsafe_targets(repo: Path, args) -> None:
    write(repo, "systems/a.md", "A")
    (repo / "kb" / "log.md").write_text("# Log\n")
    (repo / "outside.md").write_text("---\ntype: Concept\n---\n")
    with pytest.raises(SystemExit):
        linkfix.merge(bundle(repo), *args, "test/0")
    assert (repo / "kb/systems/a.md").exists() and (repo / "kb/log.md").exists() and (repo / "outside.md").exists()


def test_merge_drops_verified_and_cleans_empty_folders(repo: Path) -> None:
    write(repo, "data/old/x.md", "X")
    write(repo, "systems/y.md", "Y", extra="verified: { by: human:me, at: 2026-01-01T00:00:00Z }\n")
    indexgen.write(bundle(repo))
    assert (repo / "kb/data/old/index.md").exists()
    plan = linkfix.merge(bundle(repo), "data/old/x.md", "systems/y.md", "test/0", dry_run=True)
    assert plan[-1].startswith("(dry run")
    linkfix.merge(bundle(repo), "data/old/x.md", "systems/y.md", "test/0")
    indexgen.write(bundle(repo))
    assert "verified" not in bundle(repo).by_rel["systems/y.md"].frontmatter
    assert not (repo / "kb/data/old/index.md").exists()


def test_names_keep_c_family_distinct(repo: Path) -> None:
    write(repo, "programming/c.md", "C")
    write(repo, "programming/cpp.md", "C++")
    write(repo, "programming/csharp.md", "C#")
    assert dupes.find(bundle(repo)) == []


def test_unlinked_folds_accents_and_scales(repo: Path) -> None:
    import time

    write(repo, "systems/ecoles.md", "Écoles normales")
    write(repo, "systems/ref.md", "Ref", "About ecoles normales here. See [x][r].\n\n[r]: /systems/other.md\n")
    write(repo, "systems/other.md", "Other thing")
    found = unlinked.find(bundle(repo))
    assert [(m.page, m.target) for m in found] == [("/systems/ref.md", "/systems/ecoles.md")]
    for i in range(400):
        write(repo, f"data/p{i}.md", f"Topic number {i} alpha", f"Mentions topic number {i + 1} alpha and more text. " * 3)
    start = time.perf_counter()
    unlinked.find(bundle(repo))
    assert time.perf_counter() - start < 5
    with pytest.raises(SystemExit, match="not knowledge pages"):
        unlinked.find(bundle(repo), only=["/nope.md"])


def test_wikilinks_and_future_timestamps_are_flagged(repo: Path) -> None:
    write(repo, "systems/a.md", "A", "See [[B]] and ![[img.png]] but not `[[code]]`.",
          extra="verified: { by: human:me, at: 2999-01-01T00:00:00Z }\n")
    diagnostics = [d.code for d in Checker(bundle(repo)).check_all()]
    assert diagnostics.count("H032") == 2 and "W041" in diagnostics


def test_zotero_helpers() -> None:
    assert resources.citekey_slug("hoppeProgressiveMeshes1996") == "hoppe-progressive-meshes-1996"
    assert resources.citekey_slug("müllerÜber2019") == "muller-uber-2019"
    assert resources._citekey({"extra": "tex.x: 1\nCitation Key: smith2020\n"}) == "smith2020"
    assert resources._published("2009-04-00 April 2009") == "2009-04"
    assert resources._published("1996-00-00 1996") == "1996"


def test_http_errors_become_messages(repo: Path, server, monkeypatch) -> None:
    base, routes = server

    class Redirect(_Fake):
        def do_GET(self):  # noqa: N802
            self.send_response(301)
            self.send_header("Location", "https://elsewhere.example/api")
            self.end_headers()

    monkeypatch.setenv("KARAKEEP_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("KARAKEEP_API_KEY", "k")
    with pytest.raises(SystemExit, match="cannot reach"):
        resources.fetch(bundle(repo), "https://example.org/x", repo / ".cache")
    httpd = HTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv("KARAKEEP_URL", f"http://127.0.0.1:{httpd.server_port}")
    with pytest.raises(SystemExit, match="redirects"):
        resources.fetch(bundle(repo), "https://example.org/x", repo / ".cache")
    httpd.shutdown()


def test_post_approval_fixes(repo: Path, tmp_path: Path, monkeypatch) -> None:
    import os

    _roots(repo, tmp_path, monkeypatch, "['docs/personal']")
    with pytest.raises(SystemExit, match="deny"):
        resources.fetch(bundle(repo), "file:docs/Personal/secret.md", repo / ".cache")  # case-insensitive
    with pytest.raises(SystemExit, match="root itself"):
        resources.open_target(bundle(repo), "file:docs")
    monkeypatch.delenv("Q_ONE", raising=False)
    (repo / ".env").write_text('Q_ONE="a b" # comment\n')
    resources.load_env(repo)
    assert os.environ["Q_ONE"] == "a b"
    assert resources.zotero_citekey_slug({"key": "ABCD2345", "creators": [{"lastName": "李"}], "date": "2020"}) == "zotero-abcd2345"


def test_zotero_lookup_by_slug(repo: Path, server, monkeypatch) -> None:
    base, routes = server
    zotero_routes(routes, base)
    monkeypatch.setenv("ZOTERO_LOCAL_API", f"{base}/api/users/0")
    zotero = resources.Zotero(resources.Settings.load(bundle(repo)))
    assert zotero.item("williams-2009-roofline")["key"] == "ABCD2345"


@pytest.mark.parametrize("suffix", ["", "/", "/api", "/api/", "/api/v1"])
def test_karakeep_address_forms_and_user_agent(repo: Path, server, monkeypatch, suffix: str) -> None:
    base, routes = server
    seen = {}

    def check(q, h):
        seen["ua"] = h.get("User-Agent")
        return 200, {"bookmarkId": "bm1"}

    routes[("GET", "/api/v1/bookmarks/check-url")] = check
    monkeypatch.setenv("KARAKEEP_URL", base + suffix)
    monkeypatch.setenv("KARAKEEP_API_KEY", "k")
    assert resources.KaraKeep().find("https://example.org") == "bm1"
    assert seen["ua"] == resources.USER_AGENT
