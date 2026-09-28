"""`kb rename-bundle NEW`: rename the knowledge-base folder (and so the Obsidian vault).

1. Checks the name, and that template-managed files are committed (they are re-rendered).
2. Moves the folder with `git mv`, so untracked notes and installed plugins move with it.
3. Re-renders the template-managed files with `copier recopy` and the new name.
4. Reports managed files whose committed local edits the re-render reverted.
5. Stages tracked changes only, rewrites the Stop hook's touched list, regenerates indexes
   (no `uv sync` here: the next `uv run` syncs, and a running tool can't replace itself on Windows).

If the re-render fails, everything is put back as it was.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml

from . import indexgen, search
from .bundle import TOUCHED, Bundle
from .names import KEBAB

REPOSITORY_FOLDERS = {"schema", "tools", "docs", "imports", "template", "launcher", "site"}
STANDARD_FOLDERS = {"sources", "syntheses", "entities", "projects", "journal"}
ANSWERS = ".copier-answers.yml"
_WORD = re.compile(r"([\w-]+)")


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check, encoding="utf-8",
                          errors="replace")  # `git show` prints the UTF-8 files as stored, whatever the locale


def _fail(message: str) -> SystemExit:
    return SystemExit(f"kb rename-bundle: {message}")


def check_name(repo: Path, old: str, new: str) -> None:
    if not KEBAB.match(new):
        raise _fail("use lowercase kebab-case")
    if new in REPOSITORY_FOLDERS:
        raise _fail(f"{new} is already a folder of the repository")
    if new in STANDARD_FOLDERS:
        raise _fail(f"{new} is a standard folder inside the knowledge base; pick another name")
    if not (repo / old).is_dir():
        raise _fail(f"{old}/ not found")
    if (repo / new).exists():
        raise _fail(f"{new} already exists")
    if (repo / old / new).exists():
        raise _fail(f"{old}/ already has a folder named {new} (a domain?); pick another name, e.g. {new}-kb")


def template_ref(repo: Path) -> str:
    try:
        ref = (yaml.safe_load((repo / ANSWERS).read_text(encoding="utf-8")) or {}).get("_commit")
    except (OSError, yaml.YAMLError):
        ref = None
    if not ref:
        raise _fail(f"no _commit in {ANSWERS}: cannot tell which template version to re-render")
    return str(ref)


def dirty_managed_files(repo: Path, old: str) -> str:
    """Uncommitted changes that copier recopy could overwrite: outside the folder, and its _templates/."""
    outside = _git(repo, "status", "--porcelain", "--untracked-files=no", "--", ".", f":(exclude){old}").stdout
    templates = _git(repo, "status", "--porcelain", "--untracked-files=no", "--", f"{old}/_templates").stdout
    return (outside + templates).strip()  # two calls: an :(exclude) pathspec would also hide {old}/_templates


def reverted_files(repo: Path, old: str, new: str) -> list[str]:
    """Re-rendered files that differ from HEAD by more than the folder name (one word for one word)."""
    changed = _git(repo, "diff", "--name-only", "-z", "--", ".", f":(exclude){new}", f":(exclude){ANSWERS}").stdout
    reverted = []
    for path in filter(None, changed.split("\0")):
        head = _git(repo, "show", f"HEAD:{path}", check=False)
        try:
            current = (repo / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            current = ""
        a, b = _WORD.split(head.stdout), _WORD.split(current)
        if head.returncode != 0 or len(a) != len(b) or any(x != y and (x, y) != (old, new) for x, y in zip(a, b)):
            reverted.append(path)
    return reverted


def _rewrite_touched(repo: Path, old: str, new: str) -> None:
    touched = repo / TOUCHED
    if not touched.is_file():
        return
    root = repo.resolve()
    before, after = str(root / old) + os.sep, str(root / new) + os.sep  # record_touched writes resolved OS paths
    lines = touched.read_text(encoding="utf-8").splitlines()
    text = "".join((after + l[len(before):] if l.startswith(before) else l) + "\n" for l in lines)
    touched.write_text(text, encoding="utf-8", newline="\n")


def rename(bundle: Bundle, new: str, recopy_command: list[str] | None = None) -> int:
    repo, old = bundle.repo_root, bundle.prefix
    if new == old:
        print(f"kb rename-bundle: already named {new}")
        return 0
    check_name(repo, old, new)
    ref = template_ref(repo)
    dirty = dirty_managed_files(repo, old)
    if dirty:
        raise _fail("commit or stash these changes first:\n" + dirty)
    tracked = bool(_git(repo, "ls-files", "--", old).stdout.strip())

    def move(src: str, dst: str) -> None:
        if tracked:
            _git(repo, "mv", "--", src, dst)
        else:
            shutil.move(repo / src, repo / dst)

    move(old, new)  # git mv stages the renames; untracked notes and installed plugins move with the folder
    command = recopy_command or [
        "uvx", "--quiet", "copier", "recopy", "--quiet", "--trust", "--defaults", "--overwrite", "--skip-tasks",
        f"--vcs-ref={ref}", "--data", f"bundle_dir={new}", ".",
    ]
    if subprocess.run(command, cwd=repo, check=False).returncode != 0:
        try:
            move(new, old)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise _fail(f"copier recopy failed, and moving {new}/ back to {old}/ failed too ({exc}); do it by hand") from None
        _git(repo, "restore", "--source=HEAD", "--staged", "--worktree", "--", ".", f":(exclude){old}", check=False)
        _git(repo, "restore", "--source=HEAD", "--staged", "--worktree", "--", f"{old}/_templates", check=False)
        raise _fail("copier recopy failed (see above); everything was put back as it was")
    try:
        reverted = reverted_files(repo, old, new)
        # tracked files only: untracked work stays unstaged
        staging = [_git(repo, "add", "-u", "--", ".", f":(exclude){new}", check=False)]
        if (repo / new / "_templates").is_dir():
            staging.append(_git(repo, "add", "-u", "--", f"{new}/_templates", check=False))
        for result in staging:  # "did not match any files" (nothing tracked yet) is fine; anything else is shown
            if result.returncode != 0 and "did not match any files" not in result.stderr:
                print(f"WARNING: git add failed, stage the changes yourself: {result.stderr.strip()}")
        _rewrite_touched(repo, old, new)
        indexgen.write(Bundle(repo / new, repo))  # the next `uv run` syncs the re-rendered pyproject
    except (OSError, subprocess.CalledProcessError) as exc:
        raise _fail(f"stopped after moving {old}/ to {new}/ and re-rendering ({exc}); "
                    "run uv run kb index, then review git diff --cached") from None
    print(f"Renamed {old}/ to {new}/ and staged the move and the re-rendered template files.")
    if reverted:
        print("WARNING: these template-managed files had local edits that the re-render reverted (see git diff --cached):")
        print("".join(f"  {path}\n" for path in reverted), end="")
    print("Next: review git diff --cached, then commit. Your unstaged edits and untracked notes are untouched;")
    print("the pre-commit hook checks only what the commit contains (tracked and staged files).")
    print(f"By hand: mentions of {old}/ in README.md and in schema/*.yaml comments (not re-rendered).")
    if (repo / new / ".obsidian").is_dir():
        print(f"Obsidian: open {new}/ with Open folder as vault.")
    if shutil.which("qmd"):
        print(f"qmd: qmd collection remove {search.qmd_collection(bundle)} && uv run poe search-setup (the folder path changed)")
    return 0

