"""Tests for external resources: safety and correctness of Zotero, KaraKeep, file roots and `kb open`."""

from __future__ import annotations

import os
import socket
import sqlite3
import subprocess
import threading
import unicodedata
from pathlib import Path

import pytest

from kbtools import resources
from test_extras import ITEM, bundle, repo, server, zotero_routes  # noqa: F401 - fixtures

# -- kb open and references ------------------------------------------------------------


@pytest.mark.parametrize("ref", [
    "karakeep:-aCalculator", "karakeep:file:///etc/passwd", "karakeep:smb://host/share", "karakeep:javascript:alert(1)",
    "karakeep:https://", "https://example.org/\nx", "smb://host/share", "file://etc/passwd", "custom:thing",
])
def test_open_only_hands_web_urls_to_the_desktop(repo: Path, ref: str) -> None:
    with pytest.raises(SystemExit):
        resources.open_target(bundle(repo), ref)


def test_open_accepts_web_urls_and_zotero_keys(repo: Path) -> None:
    b = bundle(repo)
    assert resources.open_target(b, "https://example.org/a?b=c") == "https://example.org/a?b=c"
    assert resources.open_target(b, "karakeep:http://example.org/x") == "http://example.org/x"
    assert resources.open_target(b, "zotero:ABCD2345") == "zotero://select/library/items/ABCD2345"


# -- markitdown ----------------------------------------------------------------------


def test_markitdown_runs_pinned_without_secrets_and_with_a_timeout(repo: Path, monkeypatch, tmp_path: Path) -> None:
    (repo / ".env").write_text("ZOTERO_API_KEY=secret-key\n")
    monkeypatch.delenv("KB_MARKITDOWN", raising=False)
    resources.load_env(repo)
    monkeypatch.setattr(resources.shutil, "which", lambda name: "/usr/bin/uvx" if name == "uvx" else None)
    seen = {}

    def run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0, "converted text", "")

    real_run = subprocess.run

    def only_uvx(fake):  # other commands (a bundle's git listing) really run
        return lambda command, **kwargs: fake(command, **kwargs) if command[0] == "uvx" else real_run(command, **kwargs)

    monkeypatch.setattr(resources.subprocess, "run", only_uvx(run))
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"%PDF")
    assert resources._convert(doc) == "converted text"
    assert seen["command"][:3] == ["uvx", "--from", resources.MARKITDOWN] and "==" in resources.MARKITDOWN
    assert "ZOTERO_API_KEY" not in seen["env"] and seen["timeout"] == resources.CONVERT_TIMEOUT
    monkeypatch.setenv("KB_MARKITDOWN", "markitdown[pdf]==0.1.7")
    resources._convert(doc)
    assert seen["command"][2] == "markitdown[pdf]==0.1.7"

    def slow(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(resources.subprocess, "run", only_uvx(slow))
    with pytest.raises(SystemExit, match="took more than"):
        resources._convert(doc)
    os.environ.pop("ZOTERO_API_KEY", None)
    resources.LOADED_FROM_DOTENV.discard("ZOTERO_API_KEY")


# -- configuration --------------------------------------------------------------------


def test_malformed_env_lines_are_skipped(repo: Path, monkeypatch, capsys) -> None:
    for var in ("GOOD_ONE", "GOOD_TWO"):
        monkeypatch.delenv(var, raising=False)
    (repo / ".env").write_text("=value\nbad key=1\nA-B=2\nno equals sign\nGOOD_ONE=1\nexport GOOD_TWO=2\n")
    resources.load_env(repo)
    assert (os.environ["GOOD_ONE"], os.environ["GOOD_TWO"]) == ("1", "2")
    assert capsys.readouterr().err.count("ignored") == 4


@pytest.mark.parametrize("address", ["localhost:3000", "karakeep.example.org", "ftp://x.org", "https://"])
def test_server_address_without_scheme_is_a_message(repo: Path, monkeypatch, address: str) -> None:
    monkeypatch.setenv("KARAKEEP_URL", address)
    monkeypatch.setenv("KARAKEEP_API_KEY", "k")
    with pytest.raises(SystemExit, match="must be an http:// or https:// address"):
        resources.KaraKeep()


def test_cleartext_api_keys_are_warned_about(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("KARAKEEP_API_KEY", "k")
    for address, warned in (("http://karakeep.lan:3000", True), ("http://localhost:3000", False),
                            ("http://127.0.0.1:3000", False), ("https://karakeep.example.org", False)):
        monkeypatch.setenv("KARAKEEP_URL", address)
        resources.KaraKeep()
        assert ("unencrypted" in capsys.readouterr().err) is warned
    monkeypatch.setenv("ZOTERO_LOCAL_API", "http://zotero-box.lan:23119/api")  # carries no key: no warning
    resources.Zotero(resources.Settings.load(bundle(repo)))
    assert "unencrypted" not in capsys.readouterr().err


def test_deny_matches_either_unicode_normalization(repo: Path, monkeypatch, tmp_path: Path) -> None:
    base = tmp_path / "docs"
    folder = base / unicodedata.normalize("NFD", "Café")  # as macOS stores it
    folder.mkdir(parents=True)
    (folder / "x.md").write_text("secret")
    (repo / "schema" / "resources.yaml").write_text("roots:\n  docs: Docs.\ndeny: ['docs/café']\n")
    monkeypatch.setenv("KB_ROOT_DOCS", str(base))
    with pytest.raises(SystemExit, match="deny"):
        resources.fetch(bundle(repo), "file:docs/" + unicodedata.normalize("NFD", "Café") + "/x.md", repo / ".cache")


def test_zotero_ids_must_be_numbers(repo: Path) -> None:
    from kbtools.check import Checker

    (repo / "schema" / "resources.yaml").write_text("zotero: { group_id: ../x }\n")
    with pytest.raises(SystemExit, match="group_id` must be a number"):
        resources.Settings.load(bundle(repo))
    (repo / "schema" / "resources.yaml").write_text("zotero: { user_id: me, group_id: '12' }\n")
    found = [str(d) for d in Checker(bundle(repo)).check_all() if d.code == "H061"]
    assert len(found) == 1 and "zotero.user_id" in found[0]


def test_child_programs_never_see_secrets(repo: Path, monkeypatch) -> None:
    (repo / ".env").write_text("FROM_DOTENV_X=1\n")
    monkeypatch.delenv("FROM_DOTENV_X", raising=False)
    resources.load_env(repo)
    for name in ("ZOTERO_API_KEY", "KARAKEEP_API_KEY", "GITHUB_TOKEN", "my_secret", "DB_PASSWORD", "OTHER_API_KEY"):
        monkeypatch.setenv(name, "s")  # exported in the shell, not from .env
    monkeypatch.setenv("UV_INDEX_PRIVATE_PASSWORD", "uv needs it")
    monkeypatch.setenv("HOME_TOKENISH", "kept")
    env = resources.child_env()
    assert not {"FROM_DOTENV_X", "ZOTERO_API_KEY", "KARAKEEP_API_KEY", "GITHUB_TOKEN", "my_secret", "DB_PASSWORD",
                "OTHER_API_KEY"} & set(env)
    assert env["UV_INDEX_PRIVATE_PASSWORD"] == "uv needs it" and env["HOME_TOKENISH"] == "kept" and "PATH" in env
    os.environ.pop("FROM_DOTENV_X", None)
    resources.LOADED_FROM_DOTENV.discard("FROM_DOTENV_X")


# -- HTTP and KaraKeep -------------------------------------------------------------------


def test_truncated_responses_are_messages(repo: Path, monkeypatch) -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()

    def serve() -> None:
        conn, _ = listener.accept()
        conn.recv(65536)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{\"bookm")
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    monkeypatch.setenv("KARAKEEP_URL", f"http://127.0.0.1:{listener.getsockname()[1]}")
    monkeypatch.setenv("KARAKEEP_API_KEY", "k")
    with pytest.raises(SystemExit, match="cannot reach"):
        resources.KaraKeep().find("https://example.org")
    listener.close()


def _keep(server, monkeypatch) -> tuple[resources.KaraKeep, dict]:
    base, routes = server
    monkeypatch.setenv("KARAKEEP_URL", base)
    monkeypatch.setenv("KARAKEEP_API_KEY", "k")
    return resources.KaraKeep(), routes


def test_karakeep_null_content_and_failed_fallback(repo: Path, server, monkeypatch) -> None:
    keep, routes = _keep(server, monkeypatch)
    routes[("GET", "/api/v1/bookmarks/bm1/content")] = lambda q, h: (200, {"content": None, "nextCursor": None})
    routes[("GET", "/api/v1/bookmarks/bm1")] = lambda q, h: (200, {"id": "bm1", "content": None})
    with pytest.raises(SystemExit, match="still archiving"):
        keep.text("bm1")
    routes[("GET", "/api/v1/bookmarks/bm1")] = lambda q, h: (500, {"error": "boom"})
    with pytest.raises(SystemExit, match="returned 500"):
        keep.text("bm1")


def test_karakeep_content_pages_are_bounded(repo: Path, server, monkeypatch) -> None:
    keep, routes = _keep(server, monkeypatch)
    counter = iter(range(10_000))
    routes[("GET", "/api/v1/bookmarks/bm1/content")] = lambda q, h: (200, {"content": "x", "nextCursor": f"c{next(counter)}"})
    monkeypatch.setattr(resources, "MAX_PAGES", 5)
    assert keep.text("bm1") == "xxxxx"


# -- Zotero -------------------------------------------------------------------------------


def test_zotero_group_library_uses_the_local_group_api(repo: Path, server, monkeypatch) -> None:
    base, routes = server
    item = {**ITEM, "key": "GRP23456"}
    routes[("GET", "/api/groups/4242/items/GRP23456")] = lambda q, h: (200, {"data": item, "meta": {"parsedDate": "2009-04"}})
    (repo / "schema" / "resources.yaml").write_text("zotero: { group_id: 4242 }\n")
    monkeypatch.setenv("ZOTERO_LOCAL_API", f"{base}/api/users/0")  # the library part is replaced
    zotero = resources.Zotero(resources.Settings.load(bundle(repo)))
    assert zotero.local_base == f"{base}/api/groups/4242"
    found = zotero.item("GRP23456")
    assert found["key"] == "GRP23456" and found["parsedDate"] == "2009-04"
    assert resources.open_target(bundle(repo), "zotero:GRP23456") == "zotero://select/groups/4242/items/GRP23456"


def test_zotero_local_404_falls_back_to_the_web_api(repo: Path, server, monkeypatch) -> None:
    base, routes = server
    routes[("GET", "/web/users/77/items/ABCD2345")] = lambda q, h: (200, {"data": ITEM})
    (repo / "schema" / "resources.yaml").write_text("zotero: { user_id: 77 }\n")
    monkeypatch.setenv("ZOTERO_LOCAL_API", f"{base}/api")
    monkeypatch.setenv("ZOTERO_WEB_API", f"{base}/web")
    monkeypatch.setenv("ZOTERO_API_KEY", "key")
    zotero = resources.Zotero(resources.Settings.load(bundle(repo)))
    assert zotero.item("ABCD2345")["title"] == ITEM["title"] and zotero.used == "web API"


@pytest.mark.parametrize(("date", "published"), [
    ("2009-04-00 April 2009", "2009-04"), ("1996-00-00 1996", "1996"), ("2009-00-15 2009", "2009"),
    ("2009-04-15", "2009-04-15"), ("April 2009", "2009"), ("", None), ("0000-00-00 ", None),
])
def test_published_dates_are_read_by_position(date: str, published: str | None) -> None:
    assert resources._published(date) == published


def test_published_prefers_the_parsed_date(repo: Path) -> None:
    item = {**ITEM, "date": "April 2009", "parsedDate": "2009-04"}
    assert resources.zotero_source_frontmatter(item, resources.Settings.load(bundle(repo)))["published"] == "2009-04"


def test_unsafe_attachment_keys_are_ignored(repo: Path, server, monkeypatch, tmp_path: Path) -> None:
    base, routes = server
    zotero_routes(routes, base)
    routes[("GET", "/api/users/0/items/ABCD2345/children")] = lambda q, h: (
        200, [{"data": {"key": "../../../etc", "itemType": "attachment"}}])
    monkeypatch.setenv("ZOTERO_LOCAL_API", f"{base}/api/users/0")
    monkeypatch.setenv("ZOTERO_DATA_DIR", str(tmp_path / "zotero"))
    with pytest.raises(SystemExit, match="no indexed full text"):
        resources.fetch(bundle(repo), "zotero:ABCD2345", repo / ".cache")


def _library_db(path: Path) -> None:
    path.mkdir(parents=True)
    db = sqlite3.connect(path / "zotero.sqlite")
    db.executescript("""
        CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT);
        CREATE TABLE groups (groupID INT, libraryID INT);
        CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
        CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INT, libraryID INT, key TEXT);
        CREATE TABLE deletedItems (itemID INT);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT);
        CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);
        CREATE TABLE creatorTypes (creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT);
        CREATE TABLE itemCreators (itemID INT, creatorID INT, creatorTypeID INT, orderIndex INT);
        CREATE TABLE itemAttachments (itemID INT, parentItemID INT);
        INSERT INTO libraries VALUES (1, 'user'), (2, 'group');
        INSERT INTO groups VALUES (4242, 2);
        INSERT INTO itemTypes VALUES (1, 'journalArticle');
        INSERT INTO items VALUES (1, 1, 1, 'USER2345'), (2, 1, 2, 'GRP23456');
        INSERT INTO fields VALUES (1, 'title');
        INSERT INTO itemDataValues VALUES (1, 'Roofline model');
        INSERT INTO itemData VALUES (1, 1, 1), (2, 1, 1);
    """)
    db.commit()
    db.close()


@pytest.mark.parametrize(("config", "key"), [("", "USER2345"), ("zotero: { group_id: 4242 }\n", "GRP23456")])
def test_zotero_snapshot_reads_only_the_configured_library(repo: Path, monkeypatch, tmp_path: Path, config: str, key: str) -> None:
    _library_db(tmp_path / "zotero")
    (repo / "schema" / "resources.yaml").write_text(config)
    monkeypatch.setenv("ZOTERO_LOCAL_API", "http://127.0.0.1:9/api")  # Zotero closed
    monkeypatch.setenv("ZOTERO_DATA_DIR", str(tmp_path / "zotero"))
    zotero = resources.Zotero(resources.Settings.load(bundle(repo)))
    assert [i["key"] for i in zotero.search("Roofline")] == [key]


def test_torn_database_snapshot_is_a_message(repo: Path, monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "zotero").mkdir()
    (tmp_path / "zotero" / "zotero.sqlite").write_bytes(b"SQLite format 3\x00" + b"\xff" * 200)
    monkeypatch.setenv("ZOTERO_LOCAL_API", "http://127.0.0.1:9/api")
    monkeypatch.setenv("ZOTERO_DATA_DIR", str(tmp_path / "zotero"))
    zotero = resources.Zotero(resources.Settings.load(bundle(repo)))
    with pytest.raises(SystemExit, match="cannot read the Zotero database snapshot"):
        zotero.search("x")
