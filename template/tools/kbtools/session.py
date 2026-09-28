"""Agent-session state for the hooks: which pages a session changed, and log.md before it started.

State lives in `.cache/kb-hooks/<session id>/`, so concurrent or later
sessions never see each other's lists:

- `log`: a digest of the bundle's `log.md`, taken at the session's first hook
  event (before its first change), so the Stop hook can tell whether the
  session logged its work without asking git;
- `touched`: bundle-relative paths the session changed, one per line;
- `pre-<tool call>.json`: the bundle's (path, mtime, size, content hash)
  listing taken before a shell command, compared after it to find the files
  it changed. `.cache/kb-hooks/hashes.json` caches the hashes, so only files
  changed since the last listing are read.

`kb` commands run by Claude Code append to `.cache/kb-touched.txt`
(`bundle.record_touched`); each hook event moves those entries into the
session that is running.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import time
from collections.abc import Iterable
from pathlib import Path

from .bundle import TOUCHED
from .fsutil import remove_tree

STATE = ".cache/kb-hooks"
HASHES = "hashes.json"  # content hashes of the bundle's pages, shared by all sessions
KEEP_DAYS = 7  # state of sessions that never stopped cleanly is removed after this
SNAPSHOT_MAX_AGE = 3600  # seconds a shared snapshot (no tool-call id) is kept for overlapping commands
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def scan(root: Path) -> dict[str, list[int]]:
    """Every .md file below `root` outside dot-folders: bundle-relative path -> [mtime_ns, size]."""
    found: dict[str, list[int]] = {}
    stack = [(root, "")]
    while stack:
        folder, prefix = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append((Path(entry.path), f"{prefix}{entry.name}/"))
                elif entry.name.endswith(".md") and entry.is_file():
                    stat = entry.stat()
                    found[prefix + entry.name] = [stat.st_mtime_ns, stat.st_size]
            except OSError:
                continue
    return found


def listing(root: Path, cache: Path) -> dict[str, list]:
    """`scan` plus a content hash per file: path -> [mtime_ns, size, hash].

    Hashes are cached in `cache` by (path, mtime, size), shared by all
    sessions, so only files changed since the last listing are read.
    """
    try:
        known = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        known = {}
    if not isinstance(known, dict):
        known = {}
    found, fresh = {}, False
    for rel, (mtime, size) in scan(root).items():
        old = known.get(rel)
        if isinstance(old, list) and len(old) == 3 and old[0] == mtime and old[1] == size:
            found[rel] = old
            continue
        try:
            digest = hashlib.blake2b((root / rel).read_bytes(), digest_size=16).hexdigest()
        except OSError:
            continue
        found[rel], fresh = [mtime, size, digest], True
    if fresh or found.keys() != known.keys():
        with contextlib.suppress(
            OSError
        ):  # the cache is optional: on Windows, replacing it fails while another hook reads it
            _write_json(cache, found)
    return found


def _write_json(target: Path, data: object) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8", newline="\n")
    try:
        os.replace(tmp, target)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "absent"


class Session:
    """The hook state of one agent session (`session_id` from the hook payload; `default` without one)."""

    def __init__(self, root: Path, repo_root: Path, session_id: object = None):
        self.root = root.resolve()
        self.repo_root = repo_root.resolve()
        key = _UNSAFE.sub("_", str(session_id or ""))[:120].strip(".") or "default"
        self.dir = self.repo_root / STATE / key

    # -- log baseline ----------------------------------------------------------

    def start(self, log_already_changed: bool = False) -> None:
        """Record log.md's digest unless this session already has one (first touch wins)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.dir / "log", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            return
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("changed" if log_already_changed else _digest(self.root / "log.md"))

    def log_changed(self) -> bool | None:
        """Whether log.md differs from the session's baseline; None without a baseline."""
        try:
            baseline = (self.dir / "log").read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return baseline == "changed" or baseline != _digest(self.root / "log.md")

    # -- touched pages -----------------------------------------------------------

    def rel(self, path: Path | str) -> str | None:
        """The bundle-relative path of `path`, or None when it is outside the bundle."""
        path = Path(path)
        if not path.is_absolute():
            path = self.root / path
        try:
            return Path(os.path.normpath(path)).relative_to(self.root).as_posix()
        except ValueError:
            try:
                return path.resolve().relative_to(self.root).as_posix()
            except (ValueError, OSError):
                return None

    def record(self, paths: Iterable[str | Path]) -> None:
        rels = [r for r in (self.rel(p) for p in paths) if r]
        if not rels:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / "touched").open("a", encoding="utf-8", newline="\n") as fh:
            fh.write("".join(f"{r}\n" for r in rels))

    def claim_commands(self) -> None:
        """Move the entries `kb` commands appended to `.cache/kb-touched.txt` into this session."""
        legacy = self.repo_root / TOUCHED
        if not legacy.is_file():
            return
        claimed = legacy.with_name(f"{legacy.name}.{os.getpid()}")
        try:
            os.replace(legacy, claimed)  # atomic: a concurrent hook finds nothing left to claim
            lines = claimed.read_text(encoding="utf-8").splitlines()
            claimed.unlink()
        except OSError:
            return
        self.record(line.strip() for line in lines if line.strip())

    def touched(self) -> list[str]:
        """Bundle-relative paths this session changed (existing or deleted); stale entries dropped."""
        self.claim_commands()
        try:
            lines = (self.dir / "touched").read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        return sorted({r for r in (self.rel(line.strip()) for line in lines if line.strip()) if r})

    # -- shell commands --------------------------------------------------------

    def _snapshot_file(self, tool_use_id: object) -> Path:
        key = _UNSAFE.sub("_", str(tool_use_id or ""))[:120] or "last"
        return self.dir / f"pre-{key}.json"

    def _listing(self) -> dict[str, list]:
        return listing(self.root, self.repo_root / STATE / HASHES)

    def snapshot(self, tool_use_id: object = None) -> None:
        """The bundle's listing before a shell command.

        Without a tool-call id (Gemini CLI), calls share one snapshot: an
        existing recent one is kept, so overlapping commands are compared with
        the state before the first of them.
        """
        target = self._snapshot_file(tool_use_id)
        if not tool_use_id:
            try:
                if time.time() - target.stat().st_mtime < SNAPSHOT_MAX_AGE:
                    return
            except OSError:
                pass
        _write_json(target, self._listing())

    def changes(self, tool_use_id: object = None) -> list[str]:
        """Pages created, modified or deleted since `snapshot`; they are recorded as touched.

        A file whose content is unchanged (rewritten with the same text, or
        changed and changed back) does not count.
        """
        source = self._snapshot_file(tool_use_id)
        try:
            before = json.loads(source.read_text(encoding="utf-8"))
            source.unlink()
        except (OSError, ValueError):
            return []
        after = self._listing()

        def content(listing: dict, rel: str) -> object:
            entry = listing.get(rel)
            return entry[2] if isinstance(entry, list) and len(entry) == 3 else entry

        changed = sorted(rel for rel in before.keys() | after.keys() if content(before, rel) != content(after, rel))
        self.record(changed)
        return changed

    # -- lifecycle ---------------------------------------------------------------

    def clear(self) -> None:
        remove_tree(self.dir, ignore_errors=True)
        cutoff = time.time() - KEEP_DAYS * 86400
        try:
            others = list((self.repo_root / STATE).iterdir())
        except OSError:
            return
        tmp_cutoff = time.time() - 3600
        for other in others:
            try:
                if other.is_dir() and other.stat().st_mtime < cutoff:
                    remove_tree(other, ignore_errors=True)
                elif other.name.endswith(".tmp") and other.is_file() and other.stat().st_mtime < tmp_cutoff:
                    other.unlink()  # left by a hook that was killed while writing the hash cache
            except OSError:
                continue
