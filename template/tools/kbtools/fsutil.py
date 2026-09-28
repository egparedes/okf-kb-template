"""File-system helpers that behave the same on Windows."""

from __future__ import annotations

import os
import shutil
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


def remove_tree(path: Path | str, ignore_errors: bool = False) -> None:
    """shutil.rmtree that also removes read-only files.

    Windows refuses to delete a read-only file (git objects, a copy of a
    read-only page); POSIX only looks at the folder's permissions. A failed
    removal is retried once after making the file writable.
    """

    def retry(func: Callable[..., object], name: str, exc: BaseException | tuple[Any, BaseException, Any]) -> None:
        exc = exc[1] if isinstance(exc, tuple) else exc  # onerror passes sys.exc_info()
        try:
            if func not in (os.unlink, os.remove, os.rmdir) or not isinstance(exc, PermissionError):
                raise exc
            os.chmod(name, stat.S_IWRITE)
            func(name)
        except OSError:
            if not ignore_errors:
                raise

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


def which_on_path(name: str) -> str | None:
    """The program `name` from an absolute PATH entry, like shutil.which without the current directory.

    On Windows, shutil.which (and CreateProcess for a bare name) looks in the
    current directory first, so a `qmd.cmd` or `git.exe` committed to the
    knowledge base would run instead of the installed one. Only absolute PATH
    entries are searched here (not "", "." or relative ones), with PATHEXT on
    Windows; the result is an absolute path to hand to subprocess.
    """
    if not name or os.path.basename(name) != name or name in (os.curdir, os.pardir):
        return None
    if sys.platform == "win32":
        exts = [e for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").lower().split(os.pathsep) if e]
        candidates = [name] if os.path.splitext(name)[1].lower() in exts else [name + e for e in exts]
    else:
        candidates = [name]
    for entry in os.environ.get("PATH", os.defpath).split(os.pathsep):
        entry = entry.strip('"')  # Windows allows quoted entries
        if not entry or not os.path.isabs(entry):
            continue
        for candidate in candidates:
            path = os.path.join(entry, candidate)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
    return None


def program(name: str) -> str:
    """The absolute path of the program `name` on PATH, never from the current directory.

    Raises FileNotFoundError when it is not on PATH: handing the bare name to
    subprocess would let Windows (CreateProcess) look in the current directory.
    """
    found = which_on_path(name)
    if found is None:
        raise FileNotFoundError(f"`{name}` is not installed (not found on PATH)")
    return found
