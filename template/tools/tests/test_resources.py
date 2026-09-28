"""Tests for external resources: safety and correctness of Zotero, KaraKeep, file roots and `kb open`."""

from __future__ import annotations

import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unicodedata
from pathlib import Path

import pytest
from test_extras import ITEM, bundle, repo, server, zotero_routes  # noqa: F401 - fixtures

from kbtools import resources

# -- kb open and references ------------------------------------------------------------


@pytest.mark.parametrize(
    "ref",
    [
        "karakeep:-aCalculator",
        "karakeep:file:///etc/passwd",
        "karakeep:smb://host/share",
        "karakeep:javascript:alert(1)",
        "karakeep:https://",
        "https://example.org/\nx",
        "smb://host/share",
        "file://etc/passwd",
        "custom:thing",
    ],
)
def test_open_only_hands_web_urls_to_the_desktop(repo: Path, ref: str) -> None:
    with pytest.raises(SystemExit):
        resources.open_target(bundle(repo), ref)


def test_open_accepts_web_urls_and_zotero_keys(repo: Path) -> None:
    b = bundle(repo)
    assert resources.open_target(b, "https://example.org/a?b=c") == "https://example.org/a?b=c"
    assert resources.open_target(b, "karakeep:http://example.org/x") == "http://example.org/x"
    assert resources.open_target(b, "zotero:ABCD2345") == "zotero://select/library/items/ABCD2345"


@pytest.mark.parametrize(
    ("platform", "opened"),
    [
        ("win32", ["startfile"]),
        ("darwin", ["open"]),
        ("linux", ["xdg-open"]),
    ],
)
def test_open_uses_the_platform_opener(repo: Path, monkeypatch, capsys, platform: str, opened: list[str]) -> None:
    from kbtools.cli import main

    calls = []

    def startfile(target):  # the program it starts inherits kb's environment: the secrets are gone by then
        assert "ZOTERO_API_KEY" not in os.environ and os.environ.get("KEEP_ME") == "yes"
        calls.append(["startfile", target])

    monkeypatch.setattr(os, "environ", dict(os.environ))  # the scrub below must not leak into other tests
    monkeypatch.setattr(resources, "_PLATFORM", platform)
    monkeypatch.setattr(resources.os, "startfile", startfile, raising=False)
    monkeypatch.setenv("ZOTERO_API_KEY", "secret")
    monkeypatch.setenv("KEEP_ME", "yes")
    monkeypatch.setattr(resources.subprocess, "Popen", lambda args, **kw: calls.append(list(args)))
    monkeypatch.setenv("KB_REPO_ROOT", str(repo))
    monkeypatch.chdir(repo)
    assert main(["open", "https://example.org/a?b=c&d=e"]) == 0
    assert calls == [[*opened, "https://example.org/a?b=c&d=e"]]
    assert capsys.readouterr().out.strip() == "https://example.org/a?b=c&d=e"

    def missing(*args, **kwargs):
        raise FileNotFoundError("no opener")

    monkeypatch.setattr(resources.subprocess, "Popen", missing)
    monkeypatch.setattr(resources.os, "startfile", missing, raising=False)
    with pytest.raises(SystemExit, match=r"cannot open https://example\.org"):
        main(["open", "https://example.org/"])


@pytest.mark.parametrize("name", ["setup.exe", "run.BAT", "Shortcut.lnk", "tool.ps1", "Calculator.app", "go.command"])
def test_open_refuses_programs(repo: Path, tmp_path: Path, monkeypatch, name: str) -> None:
    base = tmp_path / "docs"
    (base / "sub").mkdir(parents=True)
    (base / "sub" / name).write_bytes(b"MZ")
    (base / "sub" / "paper.pdf").write_bytes(b"%PDF")
    (repo / "schema" / "resources.yaml").write_text("roots:\n  docs: Docs.\n", encoding="utf-8", newline="\n")
    monkeypatch.setenv("KB_ROOT_DOCS", str(base))
    with pytest.raises(SystemExit, match=r"program or a shortcut.*kb open file:docs/sub"):
        resources.open_target(bundle(repo), f"file:docs/sub/{name}")
    assert resources.open_target(bundle(repo), "file:docs/sub/paper.pdf").endswith("paper.pdf")


@pytest.mark.parametrize(
    ("name", "content", "refused"),
    [
        ("notes", b"plain words, but no extension\n", True),  # macOS `open` runs it in Terminal
        ("run.txt", b"#!/bin/sh\necho pwned\n", True),
        ("tool.dat", b"\x7fELF\x02\x01", True),
        ("tool.bin2", b"\xcf\xfa\xed\xfe\x07", True),  # Mach-O 64-bit
        ("setup.data", b"MZ\x90\x00", True),
        ("paper.pdf", b"%PDF-1.7\n", False),  # SMB, WSL /mnt/c, FAT: every file has the executable bit
        ("notes.txt", b"plain text\n", False),
    ],
)
def test_open_refuses_executable_bit_files_that_could_run(
    repo: Path, tmp_path: Path, monkeypatch, name: str, content: bytes, refused: bool
) -> None:
    base = tmp_path / "docs"
    (base / "sub").mkdir(parents=True)
    (base / "sub" / name).write_bytes(content)
    (base / "sub" / "plain").write_bytes(b"no extension, not executable\n")
    (repo / "schema" / "resources.yaml").write_text("roots:\n  docs: Docs.\n", encoding="utf-8", newline="\n")
    monkeypatch.setenv("KB_ROOT_DOCS", str(base))
    # The executable bit, as on an SMB or FAT mount (patched: Windows files have no mode bits).
    monkeypatch.setattr(resources.os, "access", lambda path, mode: Path(path).name != "plain")
    for platform in ("darwin", "linux"):
        monkeypatch.setattr(resources, "_PLATFORM", platform)
        if refused:
            with pytest.raises(
                SystemExit, match=rf"{re.escape(name)} is a program or a shortcut.*kb open file:docs/sub"
            ):
                resources.open_target(bundle(repo), f"file:docs/sub/{name}")
        else:
            assert resources.open_target(bundle(repo), f"file:docs/sub/{name}").endswith(name)
        assert resources.open_target(bundle(repo), "file:docs/sub/plain").endswith("plain")
        assert resources.open_target(bundle(repo), "file:docs/sub").endswith("sub")  # the folder still opens
    monkeypatch.setattr(resources, "_PLATFORM", "win32")  # Windows has no executable bit: extensions only
    assert resources.open_target(bundle(repo), f"file:docs/sub/{name}").endswith(name)


# -- programs from PATH ----------------------------------------------------------------


def _program(folder: Path, name: str, text: str = "planted") -> Path:
    """A runnable stand-in `name` in `folder` (a .bat file on Windows, found through PATHEXT)."""
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path = folder / f"{name}.bat"
        path.write_text(f"@echo {text}\r\n", encoding="utf-8", newline="")
    else:
        path = folder / name
        path.write_text(f"#!/bin/sh\necho {text}\n", encoding="utf-8", newline="\n")
        path.chmod(0o755)
    return path


@pytest.mark.parametrize("name", ["qmd", "node", "uvx", "markitdown", "git"])
def test_programs_are_never_taken_from_the_current_directory(tmp_path: Path, monkeypatch, name: str) -> None:
    """Windows looks in the current directory before PATH: a program committed to the knowledge base must not run."""
    from kbtools import fsutil, search

    root = tmp_path / "kb-root"
    _program(root, name)
    monkeypatch.chdir(root)
    monkeypatch.setenv("PATH", os.pathsep.join(["", ".", os.curdir + os.sep, "../kb-root"]))
    assert fsutil.which_on_path(name) is None
    with pytest.raises(FileNotFoundError, match=f"`{name}` is not installed"):  # never the bare name (cwd on Windows)
        fsutil.program(name)
    if name == "qmd":
        with pytest.raises(FileNotFoundError):
            search.qmd_argv("status")
        with pytest.raises(SystemExit, match="kb search: `qmd` is not installed"):
            search._qmd("status")
        assert search.qmd_ready("demo") is False
        from kbtools import retrieval_eval

        with pytest.raises(RuntimeError, match="`qmd` is not installed"):
            retrieval_eval.qmd_ranking("demo", "query", 5)
    installed = _program(tmp_path / "bin", name, "installed")
    monkeypatch.setenv("PATH", os.pathsep.join(["", ".", str(tmp_path / "bin")]))
    assert fsutil.which_on_path(name) == str(installed)
    if name == "qmd":
        assert search.qmd_argv("status") == [str(installed), "status"]


def test_commands_say_so_when_git_is_missing(repo: Path, tmp_path: Path, monkeypatch) -> None:
    from kbtools import rename
    from kbtools.cli import main

    monkeypatch.setenv("PATH", str(tmp_path / "no-programs-here"))
    (repo / "kb" / "a.md").write_text("# A\n", encoding="utf-8", newline="\n")
    assert "a.md" in bundle(repo).files  # no git: the file-system walk
    with pytest.raises(SystemExit, match="kb rename-bundle: `git` is not installed"):
        rename._git(repo, "status")
    monkeypatch.setenv("KB_REPO_ROOT", str(repo))
    with pytest.raises(SystemExit, match="kb setup: `git` is not installed"):
        main(["setup"])


def test_markitdown_is_not_run_from_the_current_directory(tmp_path: Path, monkeypatch) -> None:
    _program(tmp_path, "markitdown")
    _program(tmp_path, "uvx")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join(["", "."]))
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"%PDF")
    with pytest.raises(SystemExit, match="install markitdown"):
        resources._convert(doc)


# -- markitdown ----------------------------------------------------------------------


def test_markitdown_runs_pinned_without_secrets_and_with_a_timeout(repo: Path, monkeypatch, tmp_path: Path) -> None:
    (repo / ".env").write_text("ZOTERO_API_KEY=secret-key\n", newline="\n")
    monkeypatch.delenv("KB_MARKITDOWN", raising=False)
    resources.load_env(repo)
    monkeypatch.setattr(resources, "which_on_path", lambda name: "/usr/bin/uvx" if name == "uvx" else None)
    seen = {}

    def run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0, "converted text", "")

    real_run = subprocess.run

    def only_uvx(fake):  # other commands (a bundle's git listing) really run
        return lambda command, **kwargs: (
            fake(command, **kwargs) if command[0] == "/usr/bin/uvx" else real_run(command, **kwargs)
        )

    monkeypatch.setattr(resources.subprocess, "run", only_uvx(run))
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"%PDF")
    assert resources._convert(doc) == "converted text"
    assert seen["command"][:3] == ["/usr/bin/uvx", "--from", resources.MARKITDOWN] and "==" in resources.MARKITDOWN
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
    (repo / ".env").write_text(
        "=value\nbad key=1\nA-B=2\nno equals sign\nGOOD_ONE=1\nexport GOOD_TWO=2\n", newline="\n"
    )
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
    for address, warned in (
        ("http://karakeep.lan:3000", True),
        ("http://localhost:3000", False),
        ("http://127.0.0.1:3000", False),
        ("https://karakeep.example.org", False),
    ):
        monkeypatch.setenv("KARAKEEP_URL", address)
        resources.KaraKeep()
        assert ("unencrypted" in capsys.readouterr().err) is warned
    monkeypatch.setenv("ZOTERO_LOCAL_API", "http://zotero-box.lan:23119/api")  # carries no key: no warning
    resources.Zotero(resources.Settings.load(bundle(repo)))
    assert "unencrypted" not in capsys.readouterr().err


def test_deny_matches_either_unicode_normalization(repo: Path, monkeypatch, tmp_path: Path) -> None:
    try:
        "\u0301".encode(sys.getfilesystemencoding())
    except UnicodeEncodeError:
        pytest.skip("the file system encoding cannot name non-ASCII files (C locale without UTF-8 mode)")
    base = tmp_path / "docs"
    folder = base / unicodedata.normalize("NFD", "Café")  # as macOS stores it
    folder.mkdir(parents=True)
    (folder / "x.md").write_text("secret", encoding="utf-8", newline="\n")
    (repo / "schema" / "resources.yaml").write_text(
        "roots:\n  docs: Docs.\ndeny: ['docs/café']\n", encoding="utf-8", newline="\n"
    )
    monkeypatch.setenv("KB_ROOT_DOCS", str(base))
    with pytest.raises(SystemExit, match="deny"):
        resources.fetch(bundle(repo), "file:docs/" + unicodedata.normalize("NFD", "Café") + "/x.md", repo / ".cache")


def test_zotero_ids_must_be_numbers(repo: Path) -> None:
    from kbtools.check import Checker

    (repo / "schema" / "resources.yaml").write_text("zotero: { group_id: ../x }\n", newline="\n")
    with pytest.raises(SystemExit, match="group_id` must be a number"):
        resources.Settings.load(bundle(repo))
    (repo / "schema" / "resources.yaml").write_text("zotero: { user_id: me, group_id: '12' }\n", newline="\n")
    found = [str(d) for d in Checker(bundle(repo)).check_all() if d.code == "H061"]
    assert len(found) == 1 and "zotero.user_id" in found[0]


def test_child_programs_never_see_secrets(repo: Path, monkeypatch) -> None:
    (repo / ".env").write_text("FROM_DOTENV_X=1\n", newline="\n")
    monkeypatch.delenv("FROM_DOTENV_X", raising=False)
    resources.load_env(repo)
    for name in ("ZOTERO_API_KEY", "KARAKEEP_API_KEY", "GITHUB_TOKEN", "my_secret", "DB_PASSWORD", "OTHER_API_KEY"):
        monkeypatch.setenv(name, "s")  # exported in the shell, not from .env
    monkeypatch.setenv("UV_INDEX_PRIVATE_PASSWORD", "uv needs it")
    monkeypatch.setenv("HOME_TOKENISH", "kept")
    env = resources.child_env()
    assert not {
        "FROM_DOTENV_X",
        "ZOTERO_API_KEY",
        "KARAKEEP_API_KEY",
        "GITHUB_TOKEN",
        "my_secret",
        "DB_PASSWORD",
        "OTHER_API_KEY",
    } & set(env)
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
        conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{"bookm')
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
    routes[("GET", "/api/v1/bookmarks/bm1/content")] = lambda q, h: (
        200,
        {"content": "x", "nextCursor": f"c{next(counter)}"},
    )
    monkeypatch.setattr(resources, "MAX_PAGES", 5)
    assert keep.text("bm1") == "xxxxx"


# -- Zotero -------------------------------------------------------------------------------


def test_zotero_group_library_uses_the_local_group_api(repo: Path, server, monkeypatch) -> None:
    base, routes = server
    item = {**ITEM, "key": "GRP23456"}
    routes[("GET", "/api/groups/4242/items/GRP23456")] = lambda q, h: (
        200,
        {"data": item, "meta": {"parsedDate": "2009-04"}},
    )
    (repo / "schema" / "resources.yaml").write_text("zotero: { group_id: 4242 }\n", newline="\n")
    monkeypatch.setenv("ZOTERO_LOCAL_API", f"{base}/api/users/0")  # the library part is replaced
    zotero = resources.Zotero(resources.Settings.load(bundle(repo)))
    assert zotero.local_base == f"{base}/api/groups/4242"
    found = zotero.item("GRP23456")
    assert found["key"] == "GRP23456" and found["parsedDate"] == "2009-04"
    assert resources.open_target(bundle(repo), "zotero:GRP23456") == "zotero://select/groups/4242/items/GRP23456"


def test_zotero_local_404_falls_back_to_the_web_api(repo: Path, server, monkeypatch) -> None:
    base, routes = server
    routes[("GET", "/web/users/77/items/ABCD2345")] = lambda q, h: (200, {"data": ITEM})
    (repo / "schema" / "resources.yaml").write_text("zotero: { user_id: 77 }\n", newline="\n")
    monkeypatch.setenv("ZOTERO_LOCAL_API", f"{base}/api")
    monkeypatch.setenv("ZOTERO_WEB_API", f"{base}/web")
    monkeypatch.setenv("ZOTERO_API_KEY", "key")
    zotero = resources.Zotero(resources.Settings.load(bundle(repo)))
    assert zotero.item("ABCD2345")["title"] == ITEM["title"] and zotero.used == "web API"


@pytest.mark.parametrize(
    ("date", "published"),
    [
        ("2009-04-00 April 2009", "2009-04"),
        ("1996-00-00 1996", "1996"),
        ("2009-00-15 2009", "2009"),
        ("2009-04-15", "2009-04-15"),
        ("April 2009", "2009"),
        ("", None),
        ("0000-00-00 ", None),
    ],
)
def test_published_dates_are_read_by_position(date: str, published: str | None) -> None:
    assert resources._published(date) == published


def test_published_prefers_the_parsed_date(repo: Path) -> None:
    item = {**ITEM, "date": "April 2009", "parsedDate": "2009-04"}
    assert resources.zotero_source_frontmatter(item, resources.Settings.load(bundle(repo)))["published"] == "2009-04"


def test_unsafe_attachment_keys_are_ignored(repo: Path, server, monkeypatch, tmp_path: Path) -> None:
    base, routes = server
    zotero_routes(routes, base)
    routes[("GET", "/api/users/0/items/ABCD2345/children")] = lambda q, h: (
        200,
        [{"data": {"key": "../../../etc", "itemType": "attachment"}}],
    )
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
def test_zotero_snapshot_reads_only_the_configured_library(
    repo: Path, monkeypatch, tmp_path: Path, config: str, key: str
) -> None:
    _library_db(tmp_path / "zotero")
    (repo / "schema" / "resources.yaml").write_text(config, newline="\n")
    monkeypatch.setenv("ZOTERO_LOCAL_API", "http://127.0.0.1:9/api")  # Zotero closed
    monkeypatch.setenv("ZOTERO_DATA_DIR", str(tmp_path / "zotero"))
    with resources.Zotero(resources.Settings.load(bundle(repo))) as zotero:
        assert [i["key"] for i in zotero.search("Roofline")] == [key]
        snapshot = Path(zotero._db._tmp.name)
        assert (snapshot / "zotero.sqlite").is_file()
    assert not snapshot.exists()  # closed first, then deleted (Windows cannot delete an open database)


def test_torn_database_snapshot_is_a_message(repo: Path, monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "zotero").mkdir()
    (tmp_path / "zotero" / "zotero.sqlite").write_bytes(b"SQLite format 3\x00" + b"\xff" * 200)
    monkeypatch.setenv("ZOTERO_LOCAL_API", "http://127.0.0.1:9/api")
    monkeypatch.setenv("ZOTERO_DATA_DIR", str(tmp_path / "zotero"))
    zotero = resources.Zotero(resources.Settings.load(bundle(repo)))
    made = set(Path(tempfile.gettempdir()).glob("kb-zotero-*"))
    with pytest.raises(SystemExit, match="cannot read the Zotero database snapshot"):
        zotero.search("x")
    assert set(Path(tempfile.gettempdir()).glob("kb-zotero-*")) <= made  # the failed snapshot is removed
