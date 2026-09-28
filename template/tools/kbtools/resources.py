"""External resources: Zotero, KaraKeep and local file roots.

Binary documents stay in their system of record; pages keep pointers:

* `zotero: {key, citekey}` on Source pages (the 8-character item key never
  changes; the Better BibTeX citation key is the readable id);
* the page's `resource` URL for web articles, resolved in KaraKeep by URL
  (bookmark ids are instance-local, so cloud and self-hosted work alike);
* `locators: ["file:<root>/<path>"]` for files in synced folders, with the
  root mapped to a local path per machine.

Settings come from environment variables, optionally loaded from a gitignored
`.env` file at the repository root (see `.env.example`). Zotero is only read.
KaraKeep gains a bookmark when `kb karakeep save` or `kb fetch <url>` archives
a page that is not bookmarked yet.
"""

from __future__ import annotations

import fnmatch
import hashlib
import http.client
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .bundle import Bundle, load_yaml
from .names import fold, slug

ZOTERO_KEY = re.compile(r"^[A-Z0-9]{8}$")
LOCAL_ZOTERO = "http://localhost:23119/api"  # + /users/0 (the local user) or /groups/<id>
WEB_ZOTERO = "https://api.zotero.org"
TIMEOUT = 20
MARKITDOWN = "markitdown[all]==0.1.8"  # run through uvx when markitdown is not installed; KB_MARKITDOWN overrides
CONVERT_TIMEOUT = 300  # seconds for one markitdown conversion
MAX_PAGES = 1000  # KaraKeep content pages followed for one bookmark
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LIBRARY = re.compile(r"/(users|groups)/\d+/?$")
USER_AGENT = "kb-cli (okf-kb-template)"  # some proxies (e.g. Cloudflare) reject Python's default agent
_CITEKEY_IN_EXTRA = re.compile(r"^\s*Citation Key:\s*(\S+)\s*$", re.M | re.I)


class ResourceError(SystemExit):
    """A resource could not be resolved; the message says what to configure."""


# -- configuration ---------------------------------------------------------------


def _env_value(raw: str) -> str:
    raw = raw.strip()
    quoted = re.match(r"""^(["'])(.*?)\1\s*(#.*)?$""", raw)
    if quoted:
        return quoted.group(2)
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip()  # unquoted: drop an inline comment


LOADED_FROM_DOTENV: set[str] = set()


def load_env(repo_root: Path) -> None:
    """Load KEY=VALUE lines from `<repo>/.env` without overriding the real environment."""
    path = repo_root / ".env"
    if not path.is_file():
        return
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not _ENV_KEY.match(key) or "\0" in value:
            print(f"kb: .env line {number} ignored: expected KEY=value", file=sys.stderr)
            continue
        if key not in os.environ:
            os.environ[key] = _env_value(value)
            LOADED_FROM_DOTENV.add(key)


SECRET_NAMES = {"ZOTERO_API_KEY", "KARAKEEP_API_KEY"}
_SECRET_NAME = re.compile(r"(_API_KEY|_TOKEN|_SECRET|_PASSWORD)$", re.I)


def child_env() -> dict[str, str]:
    """Environment for programs we launch (openers, markitdown, Obsidian).

    Without anything loaded from .env, without launcher state, and without
    secrets from the real environment: the known API keys and every
    `*_API_KEY`, `*_TOKEN`, `*_SECRET` or `*_PASSWORD` name, except uv's own
    settings (`UV_*`), which uvx needs for private package indexes.
    """
    drop = LOADED_FROM_DOTENV | SECRET_NAMES | {"KB_REPO_ROOT", "OKF_KB_LAUNCHER"}
    return {k: v for k, v in os.environ.items()
            if k not in drop and (k.upper().startswith("UV_") or not _SECRET_NAME.search(k))}


_PLATFORM = sys.platform  # a seam for tests


def open_with_default_app(target: str) -> None:
    """Hand a URL or file path to the desktop's default handler (`open`, `xdg-open`, or the Windows shell).

    Raises OSError when there is no opener. On Windows os.startfile passes the
    target to the shell directly (no cmd.exe to reinterpret `&` in a URL); it
    takes no environment, so kb's own is first reduced to child_env() (kb
    exits right after, so nothing needs it back).
    """
    if _PLATFORM == "win32":
        keep = child_env()
        for name in [n for n in os.environ if n not in keep]:
            del os.environ[name]
        os.startfile(target)  # noqa: S606 - opening a URI with the default handler
        return
    opener = "open" if _PLATFORM == "darwin" else "xdg-open"
    subprocess.Popen([opener, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=child_env())


def read_config(repo_root: Path) -> tuple[dict, list[str]]:
    """schema/resources.yaml as a dict, plus shape errors (reported by `kb check`)."""
    path = repo_root / "schema" / "resources.yaml"
    if not path.is_file():
        return {}, []
    data = load_yaml(path.read_text(encoding="utf-8")) or {}
    errors = []
    if not isinstance(data, dict):
        return {}, ["schema/resources.yaml must be a mapping"]
    if not isinstance(data.get("roots") or {}, dict):
        errors.append("`roots` must be a mapping of root name to description")
        data["roots"] = {}
    deny = data.get("deny") or []
    if not isinstance(deny, list) or not all(isinstance(p, str) for p in deny):
        errors.append("`deny` must be a list of glob strings")
        data["deny"] = []
    if not isinstance(data.get("zotero") or {}, dict):
        errors.append("`zotero` must be a mapping")
        data["zotero"] = {}
    for key in ("user_id", "group_id"):
        value = (data.get("zotero") or {}).get(key)
        if value not in (None, "") and not re.fullmatch(r"\d+", str(value)):
            errors.append(f"`zotero.{key}` must be a number")
            data["zotero"][key] = None
    return data, errors


def deny_patterns(data: dict) -> list[str]:
    """Committed deny globs plus local ones from KB_DENY (`;`-separated, e.g. in .env).

    Keep patterns that would themselves reveal sensitive names in KB_DENY, not in git.
    """
    local = [p.strip() for p in os.environ.get("KB_DENY", "").split(";") if p.strip()]
    return list(data.get("deny") or []) + local


def _norm(path: str) -> str:
    """NFC (macOS file names are decomposed) and casefolded: a false deny is cheap; a missed one is not."""
    return unicodedata.normalize("NFC", path).casefold()


@dataclass
class Settings:
    roots: dict[str, str]  # root name -> description (committed)
    deny: list[str]  # glob patterns never resolved (committed)
    zotero_user_id: str | None
    zotero_group_id: str | None

    @classmethod
    def load(cls, bundle: Bundle) -> Settings:
        load_env(bundle.repo_root)
        data, errors = read_config(bundle.repo_root)
        if errors:
            raise ResourceError("kb: schema/resources.yaml: " + "; ".join(errors))
        zotero = data.get("zotero") or {}
        return cls(
            roots={str(k): str(v) for k, v in (data.get("roots") or {}).items()},
            deny=deny_patterns(data),
            zotero_user_id=str(zotero["user_id"]) if zotero.get("user_id") else (os.environ.get("ZOTERO_USER_ID") or "").strip() or None,
            zotero_group_id=str(zotero["group_id"]) if zotero.get("group_id") else None,
        )

    def root_path(self, root: str) -> Path:
        env = f"KB_ROOT_{root.upper().replace('-', '_')}"
        if root not in self.roots:
            raise ResourceError(f"kb: unknown file root `{root}`; declare it under `roots` in schema/resources.yaml")
        value = os.environ.get(env)
        if not value:
            raise ResourceError(f"kb: set {env} (in .env) to the local path of root `{root}`")
        return Path(value).expanduser()

    def denied(self, relative: str) -> bool:
        """True if `relative` (root/path, normalized) or any of its parent folders matches a deny pattern.

        Patterns use `*`, `**` and `?`; brackets are literal, so `[Zotero]` names a folder.
        Matching ignores case.
        """
        parts = relative.strip("/").split("/")
        candidates = ["/".join(parts[: i + 1]) for i in range(len(parts))]
        for pattern in self.deny:
            literal = _norm(pattern.strip("/").replace("[", "[[]"))
            base = literal[:-3] if literal.endswith("/**") else literal
            for candidate in map(_norm, candidates):
                if fnmatch.fnmatchcase(candidate, literal) or fnmatch.fnmatchcase(candidate, base):
                    return True
        return False


# -- HTTP ----------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: they would drop POST bodies and leak API keys to other hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def http_base(url: str, variable: str, warn_cleartext: bool = True) -> str:
    """A configured server address, checked: http(s) with a host.

    With `warn_cleartext` (addresses that receive an API key), `http://` to
    another machine prints a warning.
    """
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ResourceError(f"kb: {variable} must be an http:// or https:// address, e.g. https://example.org (got `{url}`)")
    if warn_cleartext and parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        print(f"kb: warning: {variable} uses http://, so the API key crosses the network unencrypted; use https://",
              file=sys.stderr)
    return url.strip().rstrip("/")


def _get(url: str, headers: dict[str, str] | None = None, data: dict | None = None) -> tuple[int, object]:
    """(status, parsed JSON) for a JSON API call; network failures raise ResourceError."""
    body = json.dumps(data).encode() if data is not None else None
    try:
        request = urllib.request.Request(
            url, data=body, headers={"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})}
        )
    except ValueError as exc:
        raise ResourceError(f"kb: invalid address {url}: {exc}") from None
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with _OPENER.open(request, timeout=TIMEOUT) as response:
            raw = response.read().decode("utf-8", "replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise ResourceError(
                f"kb: {url} redirects to {exc.headers.get('Location')}; configure the final address instead"
            ) from None
        try:
            return exc.code, exc.read().decode("utf-8", "replace")
        except (OSError, http.client.HTTPException):
            return exc.code, None
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as exc:
        raise ResourceError(f"kb: cannot reach {urllib.parse.urlsplit(url).netloc}: {exc}") from None
    if not raw:
        return status, None
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        raise ResourceError(f"kb: {url} did not return JSON (is the address right?)") from None


# -- Zotero ----------------------------------------------------------------------------


def _citekey(item: dict) -> str | None:
    """Citation key: Zotero's native field, else a Better BibTeX `Citation Key:` line in Extra."""
    if item.get("citationKey"):
        return item["citationKey"]
    match = _CITEKEY_IN_EXTRA.search(item.get("extra") or "")
    return match.group(1) if match else None


class ZoteroDB:
    """Offline, read-only metadata from a snapshot of `zotero.sqlite` (+ its WAL).

    Zotero locks its database while running and the schema is internal, so
    this is the last resort: the snapshot is copied to a temp dir and only a
    few long-stable tables are read.
    """

    def __init__(self, data_dir: Path, group_id: str | None = None):
        import tempfile

        source = data_dir / "zotero.sqlite"
        if not source.is_file():
            raise ResourceError(f"kb: no zotero.sqlite in ZOTERO_DATA_DIR ({data_dir})")
        # close() removes the snapshot; ignore_cleanup_errors is the fallback when an owner forgets
        # (Windows cannot delete the database file while a connection is open)
        self._tmp = tempfile.TemporaryDirectory(prefix="kb-zotero-", ignore_cleanup_errors=True)
        self.db: sqlite3.Connection | None = None
        target = Path(self._tmp.name) / "zotero.sqlite"
        try:
            shutil.copy2(source, target)
            wal = data_dir / "zotero.sqlite-wal"
            if wal.is_file():
                shutil.copy2(wal, Path(self._tmp.name) / "zotero.sqlite-wal")
            self.db = sqlite3.connect(target)  # a private copy: reading also applies the WAL
            self.db.row_factory = sqlite3.Row
            self.library = self._library(group_id)
        except (OSError, sqlite3.DatabaseError) as exc:
            self.close()
            raise ResourceError(f"kb: cannot read the Zotero database snapshot ({exc}); retry, or close Zotero") from None

    def close(self) -> None:
        """Close the connection, then delete the snapshot (in this order, for Windows)."""
        if self.db is not None:
            self.db.close()
            self.db = None
        self._tmp.cleanup()

    def __enter__(self) -> ZoteroDB:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _library(self, group_id: str | None) -> int | None:
        """libraryID of the configured group, else of the user library (None: a schema without libraries)."""
        columns = {r["name"] for r in self.db.execute("PRAGMA table_info(items)")}
        tables = {r["name"] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "libraryID" not in columns or not {"libraries", "groups"} <= tables:
            return None
        if group_id:
            row = self.db.execute("SELECT libraryID FROM groups WHERE groupID = ?", (int(group_id),)).fetchone()
            if row is None:
                raise ResourceError(f"kb: Zotero group {group_id} is not in the local database (sync it in Zotero first)")
        else:
            row = self.db.execute("SELECT libraryID FROM libraries WHERE type = 'user'").fetchone()
        return row["libraryID"] if row else None

    def _query(self, sql: str, params: tuple) -> list:
        try:
            return self.db.execute(sql, params).fetchall()
        except sqlite3.DatabaseError as exc:
            raise ResourceError(f"kb: cannot read the Zotero database snapshot ({exc}); retry, or close Zotero") from None

    def _in_library(self, alias: str = "i") -> tuple[str, tuple]:
        return (f"AND {alias}.libraryID = ? ", (self.library,)) if self.library is not None else ("", ())

    def _item(self, row) -> dict:
        fields = {r["fieldName"]: r["value"] for r in self._query(
            "SELECT f.fieldName, v.value FROM itemData d JOIN fields f USING (fieldID) "
            "JOIN itemDataValues v USING (valueID) WHERE d.itemID = ?", (row["itemID"],))}
        creators = [
            {"creatorType": r["creatorType"], "lastName": r["lastName"], "firstName": r["firstName"]}
            for r in self._query(
                "SELECT t.creatorType, c.lastName, c.firstName FROM itemCreators ic JOIN creators c USING (creatorID) "
                "JOIN creatorTypes t USING (creatorTypeID) WHERE ic.itemID = ? ORDER BY ic.orderIndex", (row["itemID"],))
        ]
        return {"key": row["key"], "itemType": row["typeName"], "creators": creators, **fields}

    _ITEMS = ("SELECT i.itemID, i.key, t.typeName FROM items i JOIN itemTypes t USING (itemTypeID) "
              "WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems) ")

    def item(self, key: str) -> dict | None:
        where, params = self._in_library()
        rows = self._query(self._ITEMS + where + "AND i.key = ?", (*params, key))
        return self._item(rows[0]) if rows else None

    def search(self, query: str, limit: int) -> list[dict]:
        like = f"%{query}%"
        where, params = self._in_library()
        rows = self._query(
            self._ITEMS + where + "AND t.typeName NOT IN ('attachment', 'note', 'annotation') AND i.itemID IN ("
            "SELECT d.itemID FROM itemData d JOIN fields f USING (fieldID) JOIN itemDataValues v USING (valueID) "
            "WHERE f.fieldName IN ('title', 'citationKey', 'DOI', 'extra') AND v.value LIKE ? "
            "UNION SELECT ic.itemID FROM itemCreators ic JOIN creators c USING (creatorID) WHERE c.lastName LIKE ?) "
            "LIMIT ?", (*params, like, like, limit))
        return [self._item(r) for r in rows]

    def attachments(self, key: str) -> list[dict]:
        where, params = self._in_library("p")
        rows = self._query(
            "SELECT i.key FROM itemAttachments a JOIN items i ON i.itemID = a.itemID "
            "JOIN items p ON p.itemID = a.parentItemID WHERE p.key = ? " + where, (key, *params))
        return [{"key": r["key"], "itemType": "attachment"} for r in rows]


class Zotero:
    """Read-only Zotero access: local API, then the web API, then a database snapshot.

    Full text falls back to the `.zotero-ft-cache` files in the data directory
    (`ZOTERO_DATA_DIR`), which also works while Zotero is closed.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        if not (settings.zotero_user_id or "0").isdigit():
            raise ResourceError("kb: ZOTERO_USER_ID must be the numeric Zotero user id")
        group = settings.zotero_group_id
        local = _LIBRARY.sub("", http_base(os.environ.get("ZOTERO_LOCAL_API") or LOCAL_ZOTERO, "ZOTERO_LOCAL_API",
                                         warn_cleartext=False))  # never sent a key
        self.local_base = f"{local}/groups/{group}" if group else f"{local}/users/0"  # the local API's own user is 0
        self.web_key = os.environ.get("ZOTERO_API_KEY")
        library = (f"groups/{group}" if group
                   else f"users/{settings.zotero_user_id}" if settings.zotero_user_id else None)
        web = os.environ.get("ZOTERO_WEB_API") or WEB_ZOTERO
        self.web_base = f"{http_base(web, 'ZOTERO_WEB_API')}/{library}" if library and self.web_key else None
        self.data_dir = Path(os.environ["ZOTERO_DATA_DIR"]).expanduser() if os.environ.get("ZOTERO_DATA_DIR") else None
        self.used: str | None = None

    def _call(self, path: str, params: dict | None = None) -> object | None:
        """JSON from the local API, else the web API; None when the item does not exist."""
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        status = None
        try:
            status, data = _get(f"{self.local_base}{path}{query}")
            if status == 200:
                self.used = "local API"
                return _unwrap(data)
            if status == 404 and not self.web_base:
                return None
        except ResourceError:
            status = None  # Zotero is not running
        if self.web_base and self.web_key:  # also when the local API does not know the item (not synced yet)
            status, data = _get(f"{self.web_base}{path}{query}", {"Zotero-API-Key": self.web_key, "Zotero-API-Version": "3"})
            if status == 200:
                self.used = "web API"
                return _unwrap(data)
            if status == 404:
                return None
            raise ResourceError(f"kb: Zotero web API returned {status} for {path}")
        hint = "start Zotero, and enable Settings > Advanced > 'Allow other applications on this computer to communicate with Zotero'"
        if status == 403:
            hint = "enable Settings > Advanced > 'Allow other applications on this computer to communicate with Zotero'"
        raise ResourceError(f"kb: Zotero is not reachable ({hint}); no web API fallback configured (ZOTERO_API_KEY + zotero.user_id)")

    def _offline(self) -> ZoteroDB | None:
        if self.data_dir is None:
            return None
        if getattr(self, "_db", None) is None:
            self._db = ZoteroDB(self.data_dir, self.settings.zotero_group_id)
            self.used = "database snapshot"
        return self._db

    def close(self) -> None:
        """Release the database snapshot, if one was opened."""
        db, self._db = getattr(self, "_db", None), None
        if db is not None:
            db.close()

    def __enter__(self) -> Zotero:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _api_or_offline(self, call, offline):
        try:
            return call()
        except ResourceError:
            db = self._offline()
            if db is None:
                raise
            return offline(db)

    def search(self, query: str, limit: int = 20) -> list[dict]:
        def api() -> list[dict]:
            items = self._call("/items/top", {"q": query, "qmode": "everything", "limit": min(limit, 100), "format": "json"})
            if items is not None and not isinstance(items, list):
                raise ResourceError("kb: unexpected Zotero search response")
            return [i for i in items or [] if isinstance(i, dict)]

        return self._api_or_offline(api, lambda db: db.search(query, limit))

    def item(self, ref: str) -> dict:
        """Item data by item key or citation key."""
        if ZOTERO_KEY.match(ref):
            data = self._api_or_offline(lambda: self._call(f"/items/{ref}", {"format": "json"}), lambda db: db.item(ref))
            if isinstance(data, dict):
                return data
            raise ResourceError(f"kb: no Zotero item with key `{ref}`")
        if re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)+", ref):  # a source slug: search by its first word
            for item in self.search(ref.split("-")[0], limit=100):
                if zotero_citekey_slug(item) == ref:
                    return item
        for item in self.search(ref, limit=100):
            if _citekey(item) == ref:
                return item
        raise ResourceError(f"kb: no Zotero item with citation key or slug `{ref}`")

    def attachments(self, key: str) -> list[dict]:
        children = self._api_or_offline(
            lambda: self._call(f"/items/{key}/children", {"format": "json"}), lambda db: db.attachments(key)) or []
        return [c for c in children if isinstance(c, dict) and c.get("itemType") == "attachment"]

    def fulltext(self, key: str) -> str:
        """Full text of the item's attachments: Zotero's index, else the storage cache files."""
        texts = []
        for attachment in self.attachments(key):
            att = str(attachment.get("key") or "")
            if not ZOTERO_KEY.match(att):  # also a path component below: never use it unchecked
                continue
            cache = self.data_dir / "storage" / att / ".zotero-ft-cache" if self.data_dir else None
            data = None
            try:
                if self.used != "database snapshot":
                    data = self._call(f"/items/{att}/fulltext")
            except ResourceError:
                if not (cache and cache.is_file()):
                    raise
            if isinstance(data, dict) and data.get("content"):
                texts.append(data["content"])
            elif cache and cache.is_file():
                texts.append(cache.read_text(encoding="utf-8", errors="replace"))
        if not texts:
            raise ResourceError(f"kb: Zotero item {key} has no indexed full text (let Zotero index the PDF first)")
        return "\n\n".join(texts)


def _unwrap(data: object) -> object:
    """API items as their `data`, keeping the API's `meta.parsedDate` (lists: every item)."""
    if isinstance(data, list):
        return [_unwrap(d) for d in data]
    if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
        return data
    item = dict(data["data"])
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    if meta.get("parsedDate") and "parsedDate" not in item:
        item["parsedDate"] = meta["parsedDate"]
    return item


def citekey_slug(citekey: str) -> str:
    """Kebab-case slug of a citation key: 'hoppeProgressiveMeshes1996' -> 'hoppe-progressive-meshes-1996'."""
    out = []
    for prev, char in zip(" " + citekey, citekey, strict=False):
        if (prev.islower() and char.isupper()) or (prev.isalpha() and char.isdigit()) or (prev.isdigit() and char.isalpha()):
            out.append("-")
        out.append(char)
    return slug("".join(out))


def zotero_citekey_slug(item: dict) -> str:
    """Page slug and `sources[].id`: the citation key in kebab-case, else author-year-word."""
    from_citekey = citekey_slug(_citekey(item) or "")
    if from_citekey and not from_citekey.isdigit():
        return from_citekey
    creators = item.get("creators") or [{}]
    last = creators[0].get("lastName") or creators[0].get("name") or "anon"
    year = re.search(r"\d{4}", item.get("date") or "")
    word = next((w for w in re.findall(r"[a-z]+", fold(item.get("title") or "")) if len(w) > 3), "item")
    if not slug(last):
        return f"zotero-{item['key'].lower()}"
    return slug(f"{last}-{year.group(0) if year else 'nd'}-{word}")


def _published(date: str) -> str | None:
    """YYYY, YYYY-MM or YYYY-MM-DD from a Zotero date ('2009-04-00 April 2009', '2009-04', 'April 2009').

    Parts are read by position and stop at the first unknown (`00`) one, so
    `2009-00-15` gives `2009`, never `2009-15`.
    """
    match = re.search(r"\b(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", date or "")
    if not match or match.group(1) == "0000":
        return None
    parts = [match.group(1)]
    for part in match.groups()[1:]:
        if not part or part == "00":
            break
        parts.append(part)
    return "-".join(parts)


def zotero_source_frontmatter(item: dict, settings: Settings) -> dict:
    """Frontmatter for a Source page describing a Zotero item."""
    creators = [c.get("lastName") or c.get("name") for c in item.get("creators") or [] if c.get("creatorType") in (None, "author", "editor")]
    authors = ", ".join(a for a in creators if a)
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", (item.get("DOI") or "").strip(), flags=re.I)
    library = f"groups/{settings.zotero_group_id}" if settings.zotero_group_id else "library"
    resource = (f"https://doi.org/{doi}" if doi else item.get("url")
                or f"zotero://select/{library}/items/{item['key']}")
    kind = re.sub(r"(?<!^)(?=[A-Z])", " ", item.get("itemType", "item")).lower()
    fm: dict = {"type": "Source", "title": item.get("title") or item["key"],
                "description": f"A {kind} by {authors or 'unknown authors'} (summary pending).",
                "resource": resource}
    if authors:
        fm["author"] = authors
    published = _published(item.get("parsedDate") or item.get("date") or "")
    if published:
        fm["published"] = published
    zotero = {"key": item["key"]}
    if _citekey(item):
        zotero["citekey"] = _citekey(item)
    fm["zotero"] = zotero
    return fm


# -- KaraKeep ------------------------------------------------------------------------


class KaraKeep:
    """KaraKeep by URL; works against the cloud service or a self-hosted instance."""

    def __init__(self):
        base = os.environ.get("KARAKEEP_URL")
        key = os.environ.get("KARAKEEP_API_KEY")
        if not base or not key:
            raise ResourceError("kb: set KARAKEEP_URL (cloud or self-hosted address) and KARAKEEP_API_KEY in .env")
        # Accept the server address with or without /api or /api/v1.
        root = re.sub(r"/api(/v1)?$", "", http_base(base, "KARAKEEP_URL"))
        self.api = f"{root}/api/v1"
        self.headers = {"Authorization": f"Bearer {key}"}

    def find(self, url: str) -> str | None:
        status, data = _get(f"{self.api}/bookmarks/check-url?{urllib.parse.urlencode({'url': url})}", self.headers)
        if status != 200 or not isinstance(data, dict) or "bookmarkId" not in data:
            raise ResourceError(f"kb: KaraKeep check-url failed ({status}); is KARAKEEP_URL right?")
        return data["bookmarkId"]

    def save(self, url: str) -> str:
        status, data = _get(f"{self.api}/bookmarks", self.headers, {"type": "link", "url": url})
        if status not in (200, 201) or not isinstance(data, dict) or not data.get("id"):
            raise ResourceError(f"kb: KaraKeep could not save {url} ({status})")
        return data["id"]

    def text(self, bookmark_id: str) -> str:
        """Readable markdown via /content (paginated); falls back to crawled HTML on older servers."""
        chunks: list[str] = []
        cursor, seen = None, set()
        bookmark = urllib.parse.quote(str(bookmark_id), safe="")
        for _ in range(MAX_PAGES):
            params = {"format": "markdown", **({"cursor": cursor} if cursor else {})}
            status, data = _get(f"{self.api}/bookmarks/{bookmark}/content?{urllib.parse.urlencode(params)}", self.headers)
            if status != 200 or not isinstance(data, dict):
                break
            content = data.get("content")
            chunks.append(content if isinstance(content, str) else "")
            cursor = data.get("nextCursor")
            if not cursor or not isinstance(cursor, str) or cursor in seen:
                break
            seen.add(cursor)
        text = "".join(chunks).strip()
        if text:
            return text  # empty: maybe still archiving; the bookmark tells
        status, data = _get(f"{self.api}/bookmarks/{bookmark}?includeContent=true", self.headers)
        if status != 200 or not isinstance(data, dict):
            raise ResourceError(f"kb: KaraKeep returned {status} for bookmark {bookmark_id}")
        content = data.get("content") if isinstance(data.get("content"), dict) else {}
        if content.get("crawlStatus") == "pending" or (not content.get("htmlContent") and not content.get("crawlStatus")):
            raise ResourceError(f"kb: KaraKeep is still archiving bookmark {bookmark_id}; retry in a minute")
        html = content.get("htmlContent")
        if not html:
            raise ResourceError(f"kb: KaraKeep has no archived content for bookmark {bookmark_id}")
        return _html_to_text(html)


def _html_to_text(html: str) -> str:
    from html.parser import HTMLParser

    class Text(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: list[str] = []
            self.skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self.skip += 1
            elif tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div"):
                self.parts.append("\n")

        def handle_endtag(self, tag):
            if tag in ("script", "style") and self.skip:
                self.skip -= 1

        def handle_data(self, data):
            if not self.skip:
                self.parts.append(data)

    parser = Text()
    parser.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()


# -- references --------------------------------------------------------------------


def web_url(url: str) -> str:
    """`url` if it is an http(s) URL with a host; anything else could make an opener run a program."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc or url != url.strip() or any(c < " " for c in url):
        raise ResourceError(f"kb: `{url}` is not an http:// or https:// URL")
    return url


def split_ref(ref: str) -> tuple[str, str]:
    """`zotero:KEY`, `file:root/path`, `karakeep:URL` or a bare `https://` URL (KaraKeep)."""
    if ref.lower().startswith(("http://", "https://")):
        return "karakeep", web_url(ref)
    scheme, sep, rest = ref.partition(":")
    if not sep or scheme not in ("zotero", "file", "karakeep"):
        raise ResourceError(f"kb: unsupported reference `{ref}` (use zotero:KEY, file:root/path or a URL)")
    return scheme, web_url(rest) if scheme == "karakeep" else rest


def resolve_file(settings: Settings, rest: str) -> Path:
    """Local path of `root/relative`, after resolving `..` and symlinks and applying deny patterns."""
    root, _, relative = rest.partition("/")
    base = settings.root_path(root).resolve()
    path = (base / relative).resolve()
    if base != path and base not in path.parents:
        raise ResourceError("kb: path escapes its root")
    if path == base:
        raise ResourceError("kb: point at a file or folder inside the root, not the root itself")
    inside = path.relative_to(base).as_posix()
    for candidate in (f"{root}/{inside}".rstrip("/."), f"{root}/{relative}"):
        if settings.denied(candidate):
            raise ResourceError(f"kb: `{rest}` matches a deny pattern (schema/resources.yaml or KB_DENY)")
    if not path.exists():
        raise ResourceError(f"kb: {path} does not exist on this machine")
    return path


def _convert(path: Path) -> str:
    """Text of a non-text file via markitdown (with its optional converters).

    It runs without the .env secrets, with a time limit, and through uvx at a
    pinned version (`KB_MARKITDOWN`) unless markitdown is installed.
    """
    if shutil.which("markitdown"):
        command = ["markitdown", str(path)]
    elif shutil.which("uvx"):
        command = ["uvx", "--from", os.environ.get("KB_MARKITDOWN") or MARKITDOWN, "markitdown", str(path)]
    else:
        raise ResourceError("kb: install markitdown (or uv) to convert non-text files")
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                env=child_env(), timeout=CONVERT_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise ResourceError(f"kb: markitdown took more than {CONVERT_TIMEOUT} s for {path.name}") from None
    except OSError as exc:
        raise ResourceError(f"kb: cannot run markitdown: {exc}") from None
    if result.returncode != 0:
        raise ResourceError(f"kb: markitdown could not convert {path.name}: {result.stderr.strip()[-500:]}")
    return result.stdout


def fetch(bundle: Bundle, ref: str, out_dir: Path) -> Path:
    """Write the text of a resource to `out_dir` and return the file."""
    settings = Settings.load(bundle)
    scheme, rest = split_ref(ref)
    if scheme == "zotero":
        with Zotero(settings) as zotero:
            item = zotero.item(rest)
            text, name = zotero.fulltext(item["key"]), zotero_citekey_slug(item)
            header = f"<!-- zotero:{item['key']} via {zotero.used or 'storage cache'} -->\n# {item.get('title', '')}\n\n"
    elif scheme == "karakeep":
        keep = KaraKeep()
        bookmark = keep.find(rest) or keep.save(rest)
        text = keep.text(bookmark)
        parts = urllib.parse.urlparse(rest)
        name = slug(parts.netloc + parts.path)[:70]
        header = f"<!-- {rest} via KaraKeep bookmark {bookmark} -->\n\n"
    else:
        path = resolve_file(settings, rest)
        if not path.is_file():
            raise ResourceError(f"kb: {rest} is not a file")
        name = slug(path.stem)[:70]
        header = f"<!-- file:{rest} -->\n\n"
        text = path.read_text(encoding="utf-8", errors="replace") if path.suffix.lower() in (".md", ".txt") else _convert(path)
    name = f"{name or 'resource'}-{hashlib.sha1(ref.encode()).hexdigest()[:6]}" if scheme != "zotero" else name
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.md"
    target.write_text(header + text, encoding="utf-8")
    return target


# File types the desktop runs instead of showing (Windows PATHEXT and shell types, macOS, Linux desktops).
RUN_ON_OPEN = frozenset({
    ".exe", ".com", ".bat", ".cmd", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".msc", ".msi", ".msp",
    ".scr", ".cpl", ".pif", ".lnk", ".url", ".ps1", ".psm1", ".reg", ".hta", ".jar", ".appref-ms",
    ".app", ".command", ".tool", ".scpt", ".workflow", ".pkg", ".desktop", ".appimage",
})


def _runs_when_opened(path: Path) -> bool:
    pathext = {e.lower() for e in os.environ.get("PATHEXT", "").split(os.pathsep) if e}
    return path.suffix.lower() in RUN_ON_OPEN | pathext


def open_target(bundle: Bundle, ref: str) -> str:
    """What `kb open` hands to the desktop: a zotero:// URL, a file path or a web URL."""
    settings = Settings.load(bundle)
    scheme, rest = split_ref(ref)
    if scheme == "zotero":
        if ZOTERO_KEY.match(rest):
            key = rest
        else:
            with Zotero(settings) as zotero:
                key = str(zotero.item(rest).get("key"))
        if not ZOTERO_KEY.match(key):
            raise ResourceError(f"kb: `{key}` is not a Zotero item key")
        library = f"groups/{settings.zotero_group_id}" if settings.zotero_group_id else "library"
        return f"zotero://select/{library}/items/{key}"
    if scheme == "file":
        path = resolve_file(settings, rest)
        if _runs_when_opened(path):
            folder = rest.rsplit("/", 1)[0] if "/" in rest else rest
            raise ResourceError(f"kb: {path.name} is a program or a shortcut, which the desktop would run rather "
                                f"than show; `kb open file:{folder}` opens its folder")
        return str(path)  # absolute, so never read as an option
    return web_url(rest)
