"""`kb search`: qmd hybrid search when it is set up, otherwise a plain text search.

qmd keeps one index per user, so each knowledge base gets its own
collection, named after `kb_name` (`$KB_QMD_COLLECTION` overrides it).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib

from .bundle import Bundle


def qmd_collection(bundle: Bundle) -> str:
    """This knowledge base's qmd collection: $KB_QMD_COLLECTION, else kb_name (project `<kb_name>-tools`), else `kb`."""
    if os.environ.get("KB_QMD_COLLECTION"):
        return os.environ["KB_QMD_COLLECTION"]
    try:
        name = tomllib.loads((bundle.repo_root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["name"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "kb"
    return name.removesuffix("-tools") if isinstance(name, str) and name.endswith("-tools") else "kb"


def _qmd(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["qmd", *args], text=True, check=False)
    if check and result.returncode != 0:
        raise SystemExit(f"kb search: `qmd {' '.join(args)}` failed (exit {result.returncode})")
    return result


def qmd_ready(collection: str) -> bool:
    if shutil.which("qmd") is None:
        return False
    listing = subprocess.run(["qmd", "collection", "list"], capture_output=True, text=True, check=False).stdout
    return f"(qmd://{collection}/)" in listing


def text_search(bundle: Bundle, query: str, limit: int = 20) -> list[tuple[str, int]]:
    """Pages ranked by case-insensitive matches of the query's words (3+ characters), index.md excluded."""
    if not query.strip():
        return []
    terms = [t for t in (re.sub(r"[^\w-]", "", w) for w in query.split()) if len(t) >= 3]
    pattern = re.compile("|".join(re.escape(t) for t in terms) if terms else re.escape(query), re.IGNORECASE)
    hits = []
    for doc in bundle.documents:
        if doc.rel.name == "index.md" or any(part.startswith(".") for part in doc.rel.parts):
            continue
        count = len(pattern.findall(doc.text))
        if count:
            hits.append((bundle.show(doc.rel), count))
    return sorted(hits, key=lambda h: (-h[1], h[0]))[:limit]


def search(bundle: Bundle, query: str) -> int:
    if not query.strip():
        raise SystemExit("kb search: give a query")
    collection = qmd_collection(bundle)
    if qmd_ready(collection):
        return _qmd("query", query, "-c", collection, check=False).returncode
    for path, count in text_search(bundle, query):
        print(f"{path}:{count}")
    return 0


def setup(bundle: Bundle, folders: list[tuple[str, str]]) -> int:
    """One-time qmd setup: the collection, a context per indexed folder, embeddings."""
    if shutil.which("qmd") is None:
        raise SystemExit("kb: qmd is not installed (https://github.com/tobi/qmd)")
    collection = qmd_collection(bundle)
    _qmd("collection", "add", str(bundle.root), "--name", collection, "--mask", "**/*.md")
    _qmd("context", "add", f"qmd://{collection}", "Knowledge base (OKF v0.2 bundle). Start from the index.md files.")
    for folder, description in folders:
        _qmd("context", "add", f"qmd://{collection}/{folder}", description)
    _qmd("embed")
    return 0


def reindex() -> int:
    if shutil.which("qmd") is None:
        raise SystemExit("kb: qmd is not installed (https://github.com/tobi/qmd)")
    _qmd("update")
    _qmd("embed")
    return 0
