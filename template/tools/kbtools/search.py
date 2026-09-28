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


# What cmd.exe reinterprets in the arguments of a .cmd/.bat file, quoted or not; Python cannot escape it.
_BATCH_UNSAFE = re.compile(r'["%!^&|<>\r\n]')
# npm's cmd-shim: `"%_prog%"  "%dp0%\node_modules\...\qmd.js" %*` (older shims: `%~dp0\`).
_NPM_SHIM_SCRIPT = re.compile(r'"%~?dp0%?\\([^"%]+\.[cm]?js)"')


def qmd_argv(*args: str) -> list[str]:
    """The command line that runs qmd with `args`.

    On Windows, npm installs qmd as a `qmd.cmd` shim, which only a PATH lookup
    with PATHEXT finds and which runs through cmd.exe: a query such as
    `a&calc` would start another program. The shim's script is then run with
    node directly; if that fails, arguments cmd.exe would reinterpret are
    refused (ValueError).
    """
    exe = shutil.which("qmd") or "qmd"
    if os.path.splitext(exe)[1].lower() not in (".cmd", ".bat"):
        return [exe, *args]
    node = shutil.which("node")
    try:
        with open(exe, encoding="utf-8", errors="replace") as fh:
            found = _NPM_SHIM_SCRIPT.search(fh.read())
    except OSError:
        found = None
    script = os.path.join(os.path.dirname(exe), found.group(1).replace("\\", os.sep)) if found else None
    if node and script and os.path.isfile(script) and os.path.splitext(node)[1].lower() not in (".cmd", ".bat"):
        return [node, script, *args]
    unsafe = next((a for a in args if _BATCH_UNSAFE.search(a)), None)
    if unsafe is not None:
        raise ValueError(f"qmd is the batch file {exe}, and cmd.exe would reinterpret a character of {unsafe!r} "
                         '(one of " % ! ^ & | < > or a line break); leave it out, or install qmd so that '
                         "`node` can run its script directly")
    return [exe, *args]


def _qmd(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        argv = qmd_argv(*args)
    except ValueError as exc:
        raise SystemExit(f"kb search: {exc}") from None
    result = subprocess.run(argv, check=False)
    if check and result.returncode != 0:
        raise SystemExit(f"kb search: `qmd {' '.join(args)}` failed (exit {result.returncode})")
    return result


def qmd_ready(collection: str) -> bool:
    if shutil.which("qmd") is None:
        return False
    listing = subprocess.run(qmd_argv("collection", "list"), capture_output=True, text=True, encoding="utf-8",
                             errors="replace", check=False).stdout
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
