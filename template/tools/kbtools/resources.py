"""External resources: Zotero, KaraKeep and local file roots.

Binary documents stay in their system of record; pages keep pointers:

* `zotero: {key, citekey}` on Source pages (the 8-character item key never
  changes; the Better BibTeX citation key is the readable id);
* the page's `resource` URL for web articles, resolved in KaraKeep by URL
  (bookmark ids are instance-local, so cloud and self-hosted work alike);
* `locators: ["file:<root>/<path>"]` for files in synced folders, with the
  root mapped to a local path per machine.

Settings come from environment variables, optionally loaded from a gitignored
`.env` file at the repository root (see `.env.example`). Nothing here writes
to Zotero or KaraKeep except `kb karakeep save`, which creates a bookmark.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .bundle import Bundle, load_yaml

ZOTERO_KEY = re.compile(r"^[A-Z0-9]{8}$")
LOCAL_ZOTERO = "http://localhost:23119/api/users/0"
WEB_ZOTERO = "https://api.zotero.org"
TIMEOUT = 20


class ResourceError(SystemExit):
    """A resource could not be resolved; the message says what to configure."""


# -- configuration ---------------------------------------------------------------


def load_env(repo_root: Path) -> None:
    """Load KEY=VALUE lines from `<repo>/.env` without overriding the real environment."""
    path = repo_root / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    roots: dict[str, str]  # root name -> description (committed)
    deny: list[str]  # glob patterns never resolved (committed)
    zotero_user_id: str | None
    zotero_group_id: str | None

    @classmethod
    def load(cls, bundle: Bundle) -> Settings:
        load_env(bundle.repo_root)
        path = bundle.repo_root / "schema" / "resources.yaml"
        data = (load_yaml(path.read_text(encoding="utf-8")) or {}) if path.is_file() else {}
        zotero = data.get("zotero") or {}
        return cls(
            roots={str(k): str(v) for k, v in (data.get("roots") or {}).items()},
            deny=[str(p) for p in data.get("deny") or []],
            zotero_user_id=str(zotero["user_id"]) if zotero.get("user_id") else os.environ.get("ZOTERO_USER_ID"),
            zotero_group_id=str(zotero["group_id"]) if zotero.get("group_id") else None,
        )

    def root_path(self, root: str) -> Path:
        env = f"KB_ROOT_{root.upper().replace('-', '_')}"
        value = os.environ.get(env)
        if root not in self.roots:
            raise ResourceError(f"kb: unknown file root `{root}`; declare it under `roots` in schema/resources.yaml")
        if not value:
            raise ResourceError(f"kb: set {env} (in .env) to the local path of root `{root}`")
        return Path(value).expanduser()

    def denied(self, relative: str) -> bool:
        return any(fnmatch.fnmatch(relative, pattern) for pattern in self.deny)


# -- HTTP ----------------------------------------------------------------------------


def _get(url: str, headers: dict[str, str] | None = None, data: dict | None = None) -> tuple[int, object]:
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, headers={"Accept": "application/json", **(headers or {})})
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    try:
        return status, json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return status, raw


# -- Zotero ----------------------------------------------------------------------------


class ZoteroDB:
    """Offline, read-only metadata from a snapshot of `zotero.sqlite` (+ its WAL).

    Zotero locks its database while running and the schema is internal, so
    this is the last resort: the snapshot is copied to a temp dir and only a
    few long-stable tables are read.
    """

    def __init__(self, data_dir: Path):
        import sqlite3
        import tempfile

        source = data_dir / "zotero.sqlite"
        if not source.is_file():
            raise ResourceError(f"kb: no zotero.sqlite in ZOTERO_DATA_DIR ({data_dir})")
        self._tmp = tempfile.TemporaryDirectory(prefix="kb-zotero-")
        target = Path(self._tmp.name) / "zotero.sqlite"
        shutil.copy2(source, target)
        wal = data_dir / "zotero.sqlite-wal"
        if wal.is_file():
            shutil.copy2(wal, Path(self._tmp.name) / "zotero.sqlite-wal")
        self.db = sqlite3.connect(target)  # a private copy: reading also applies the WAL
        self.db.row_factory = sqlite3.Row

    def _item(self, row) -> dict:
        fields = {r["fieldName"]: r["value"] for r in self.db.execute(
            "SELECT f.fieldName, v.value FROM itemData d JOIN fields f USING (fieldID) "
            "JOIN itemDataValues v USING (valueID) WHERE d.itemID = ?", (row["itemID"],))}
        creators = [
            {"creatorType": r["creatorType"], "lastName": r["lastName"], "firstName": r["firstName"]}
            for r in self.db.execute(
                "SELECT t.creatorType, c.lastName, c.firstName FROM itemCreators ic JOIN creators c USING (creatorID) "
                "JOIN creatorTypes t USING (creatorTypeID) WHERE ic.itemID = ? ORDER BY ic.orderIndex", (row["itemID"],))
        ]
        return {"key": row["key"], "itemType": row["typeName"], "creators": creators, **fields}

    _ITEMS = ("SELECT i.itemID, i.key, t.typeName FROM items i JOIN itemTypes t USING (itemTypeID) "
              "WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems) ")

    def item(self, key: str) -> dict | None:
        row = self.db.execute(self._ITEMS + "AND i.key = ?", (key,)).fetchone()
        return self._item(row) if row else None

    def search(self, query: str, limit: int) -> list[dict]:
        like = f"%{query}%"
        rows = self.db.execute(
            self._ITEMS + "AND t.typeName NOT IN ('attachment', 'note', 'annotation') AND i.itemID IN ("
            "SELECT d.itemID FROM itemData d JOIN fields f USING (fieldID) JOIN itemDataValues v USING (valueID) "
            "WHERE f.fieldName IN ('title', 'citationKey', 'DOI') AND v.value LIKE ? "
            "UNION SELECT ic.itemID FROM itemCreators ic JOIN creators c USING (creatorID) WHERE c.lastName LIKE ?) "
            "LIMIT ?", (like, like, limit)).fetchall()
        return [self._item(r) for r in rows]

    def attachments(self, key: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT i.key FROM itemAttachments a JOIN items i ON i.itemID = a.itemID "
            "JOIN items p ON p.itemID = a.parentItemID WHERE p.key = ?", (key,)).fetchall()
        return [{"key": r["key"], "itemType": "attachment"} for r in rows]


class Zotero:
    """Read-only Zotero access: local API first, then the web API.

    Full text falls back to the `.zotero-ft-cache` files in the data directory
    (`ZOTERO_DATA_DIR`), which also works while Zotero is closed.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.local_base = os.environ.get("ZOTERO_LOCAL_API", LOCAL_ZOTERO)
        self.web_key = os.environ.get("ZOTERO_API_KEY")
        library = (f"groups/{settings.zotero_group_id}" if settings.zotero_group_id
                   else f"users/{settings.zotero_user_id}" if settings.zotero_user_id else None)
        self.web_base = f"{os.environ.get('ZOTERO_WEB_API', WEB_ZOTERO)}/{library}" if library else None
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
                return data
            if status == 404:
                return None
        except (urllib.error.URLError, OSError):
            status = None
        if self.web_base and self.web_key:
            status, data = _get(f"{self.web_base}{path}{query}", {"Zotero-API-Key": self.web_key, "Zotero-API-Version": "3"})
            if status == 200:
                self.used = "web API"
                return data
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
        if not hasattr(self, "_db"):
            self._db = ZoteroDB(self.data_dir)
            self.used = "database snapshot"
        return self._db

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
            items = self._call("/items/top", {"q": query, "qmode": "everything", "limit": limit, "format": "json"}) or []
            return [i.get("data", i) for i in items if isinstance(i, dict)]

        return self._api_or_offline(api, lambda db: db.search(query, limit))

    def item(self, ref: str) -> dict:
        """Item data by item key or citation key."""
        if ZOTERO_KEY.match(ref):
            data = self._api_or_offline(lambda: self._call(f"/items/{ref}", {"format": "json"}), lambda db: db.item(ref))
            if isinstance(data, dict):
                return data.get("data", data)
            raise ResourceError(f"kb: no Zotero item with key `{ref}`")
        for item in self.search(ref, limit=50):
            if item.get("citationKey") == ref:
                return item
        raise ResourceError(f"kb: no Zotero item with citation key `{ref}`")

    def attachments(self, key: str) -> list[dict]:
        children = self._api_or_offline(
            lambda: self._call(f"/items/{key}/children", {"format": "json"}), lambda db: db.attachments(key)) or []
        data = [c.get("data", c) for c in children if isinstance(c, dict)]
        return [c for c in data if c.get("itemType") == "attachment"]

    def fulltext(self, key: str) -> str:
        """Full text of the item's attachments: Zotero's index, else the storage cache files."""
        texts = []
        for attachment in self.attachments(key):
            att = attachment["key"]
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


def zotero_citekey_slug(item: dict) -> str:
    key = item.get("citationKey") or ""
    slug = re.sub(r"[^a-z0-9]+", "-", key.casefold()).strip("-")
    if slug:
        return slug
    creators = item.get("creators") or [{}]
    last = creators[0].get("lastName") or creators[0].get("name") or "anon"
    year = re.search(r"\d{4}", item.get("date") or "")
    word = next((w for w in re.findall(r"[a-z]+", (item.get("title") or "").casefold()) if len(w) > 3), "item")
    return re.sub(r"[^a-z0-9]+", "-", f"{last}-{year.group(0) if year else 'nd'}-{word}".casefold()).strip("-")


def zotero_source_frontmatter(item: dict, settings: Settings) -> dict:
    """Frontmatter for a Source page describing a Zotero item."""
    creators = [c.get("lastName") or c.get("name") for c in item.get("creators") or [] if c.get("creatorType") in (None, "author", "editor")]
    authors = ", ".join(a for a in creators if a)
    doi = item.get("DOI")
    library = f"groups/{settings.zotero_group_id}" if settings.zotero_group_id else "library"
    resource = (f"https://doi.org/{doi}" if doi else item.get("url")
                or f"zotero://select/{library}/items/{item['key']}")
    fm: dict = {"type": "Source", "title": item.get("title") or item["key"],
                "description": f"{item.get('itemType', 'item')} by {authors or 'unknown authors'}.",
                "resource": resource}
    if authors:
        fm["author"] = authors
    year = re.search(r"\d{4}(-\d{2}(-\d{2})?)?", item.get("date") or "")
    if year:
        fm["published"] = year.group(0)
    zotero = {"key": item["key"]}
    if item.get("citationKey"):
        zotero["citekey"] = item["citationKey"]
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
        self.api = base.rstrip("/") + ("" if base.rstrip("/").endswith("/api/v1") else "/api/v1")
        self.headers = {"Authorization": f"Bearer {key}"}

    def find(self, url: str) -> str | None:
        status, data = _get(f"{self.api}/bookmarks/check-url?{urllib.parse.urlencode({'url': url})}", self.headers)
        if status != 200:
            raise ResourceError(f"kb: KaraKeep check-url returned {status}")
        return (data or {}).get("bookmarkId") if isinstance(data, dict) else None

    def save(self, url: str) -> dict:
        status, data = _get(f"{self.api}/bookmarks", self.headers, {"type": "link", "url": url})
        if status not in (200, 201) or not isinstance(data, dict):
            raise ResourceError(f"kb: KaraKeep could not save {url} ({status})")
        return data

    def text(self, bookmark_id: str) -> str:
        """Readable markdown via /content (paginated); falls back to crawled HTML on older servers."""
        chunks, cursor = [], None
        while True:
            params = {"format": "markdown", **({"cursor": cursor} if cursor else {})}
            status, data = _get(f"{self.api}/bookmarks/{bookmark_id}/content?{urllib.parse.urlencode(params)}", self.headers)
            if status != 200 or not isinstance(data, dict):
                break
            chunks.append(data.get("content") or "")
            cursor = data.get("nextCursor")
            if not cursor:
                return "".join(chunks)
        status, data = _get(f"{self.api}/bookmarks/{bookmark_id}?includeContent=true", self.headers)
        content = (data or {}).get("content", {}) if isinstance(data, dict) else {}
        if content.get("crawlStatus") == "pending":
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


def split_ref(ref: str) -> tuple[str, str]:
    """`zotero:KEY`, `file:root/path`, `karakeep:URL` or a bare `https://` URL (KaraKeep)."""
    if ref.startswith(("http://", "https://")):
        return "karakeep", ref
    scheme, sep, rest = ref.partition(":")
    if not sep or scheme not in ("zotero", "file", "karakeep"):
        raise ResourceError(f"kb: unsupported reference `{ref}` (use zotero:KEY, file:root/path or a URL)")
    return scheme, rest


def resolve_file(settings: Settings, rest: str) -> Path:
    root, _, relative = rest.partition("/")
    if settings.denied(f"{root}/{relative}"):
        raise ResourceError(f"kb: `{root}/{relative}` matches a deny pattern in schema/resources.yaml")
    base = settings.root_path(root).resolve()
    path = (base / relative).resolve()
    if base not in path.parents and path != base:
        raise ResourceError("kb: path escapes its root")
    if not path.exists():
        raise ResourceError(f"kb: {path} does not exist on this machine")
    return path


def fetch(bundle: Bundle, ref: str, out_dir: Path) -> Path:
    """Write the text of a resource to `out_dir` and return the file."""
    settings = Settings.load(bundle)
    scheme, rest = split_ref(ref)
    if scheme == "zotero":
        zotero = Zotero(settings)
        item = zotero.item(rest)
        text, name = zotero.fulltext(item["key"]), zotero_citekey_slug(item)
        header = f"<!-- zotero:{item['key']} via {zotero.used or 'storage cache'} -->\n# {item.get('title', '')}\n\n"
    elif scheme == "karakeep":
        keep = KaraKeep()
        bookmark = keep.find(rest) or keep.save(rest).get("id")
        text = keep.text(bookmark)
        name = re.sub(r"[^a-z0-9]+", "-", urllib.parse.urlparse(rest).netloc + urllib.parse.urlparse(rest).path).strip("-")[:80]
        header = f"<!-- {rest} via KaraKeep bookmark {bookmark} -->\n\n"
    else:
        path = resolve_file(settings, rest)
        name = re.sub(r"[^a-z0-9]+", "-", path.stem.casefold()).strip("-")
        header = f"<!-- file:{rest} -->\n\n"
        if path.suffix.lower() in (".md", ".txt"):
            text = path.read_text(encoding="utf-8", errors="replace")
        else:
            converter = shutil.which("markitdown")
            command = [converter, str(path)] if converter else (["uvx", "markitdown", str(path)] if shutil.which("uvx") else None)
            if not command:
                raise ResourceError("kb: install markitdown (or uv) to convert non-text files")
            text = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name or 'resource'}.md"
    target.write_text(header + text, encoding="utf-8")
    return target


def open_target(bundle: Bundle, ref: str) -> str:
    """What `kb open` hands to the desktop: a zotero:// URL, a file path or a web URL."""
    settings = Settings.load(bundle)
    scheme, rest = split_ref(ref)
    if scheme == "zotero":
        key = rest if ZOTERO_KEY.match(rest) else Zotero(settings).item(rest)["key"]
        library = f"groups/{settings.zotero_group_id}" if settings.zotero_group_id else "library"
        return f"zotero://select/{library}/items/{key}"
    if scheme == "file":
        return str(resolve_file(settings, rest))
    return rest
