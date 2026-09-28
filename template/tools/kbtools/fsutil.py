"""File-system helpers that behave the same on Windows."""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path


def remove_tree(path: Path | str, ignore_errors: bool = False) -> None:
    """shutil.rmtree that also removes read-only files.

    Windows refuses to delete a read-only file (git objects, a copy of a
    read-only page); POSIX only looks at the folder's permissions. A failed
    removal is retried once after making the file writable.
    """
    def retry(func, name, exc) -> None:
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
