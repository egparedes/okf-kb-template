"""Global `kb` launcher: find a knowledge base and run its own `kb` tool.

The knowledge base is chosen, in order, by `-C/--kb PATH|NAME`, `$KB_DIR`,
the nearest parent of the current directory that holds
`schema/vocabulary.yaml`, and the `default` entry of the config file
(`$XDG_CONFIG_HOME/okf-kb/config.toml`):

    default = "work"
    [knowledge-bases]
    work = "~/work-kb"

The command runs `uv run --project <root> --quiet kb <args>` with
`KB_REPO_ROOT=<root>`, in the current directory.
"""

from __future__ import annotations

import os
import shutil
import sys
import tomllib
from pathlib import Path

GUARD = "OKF_KB_LAUNCHER"
USAGE = """usage: kb [-C PATH|NAME] <command> [args...]
       kb --list | --which | --help-launcher

Runs the `kb` tool of a knowledge base generated from okf-kb-template.
Without -C: $KB_DIR, then the knowledge base around the current directory,
then `default` in {config}.
`kb -h` and `kb <command> -h` show the knowledge base's own help."""


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "okf-kb" / "config.toml"


def load_config(strict: bool = True) -> dict:
    """The config file; with strict=False a broken file is ignored (an explicit -C does not need it)."""
    path = config_path()
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        if strict:
            raise SystemExit(f"kb: cannot read {path}: {exc}") from None
        return {}
    table = data.get("knowledge-bases", {})
    problem = None
    if not isinstance(table, dict) or not all(isinstance(v, str) for v in table.values()):
        problem = "[knowledge-bases] must map names to path strings"
    elif "default" in data and not isinstance(data["default"], str):
        problem = "`default` must be a name from [knowledge-bases]"
    if problem:
        if strict:
            raise SystemExit(f"kb: {path}: {problem}")
        return {}
    return data


def registered(config: dict) -> dict[str, Path]:
    """Registered names; relative paths are relative to the config file."""
    base = config_path().parent
    return {
        str(name): (base / Path(os.path.expanduser(path))).resolve()
        for name, path in (config.get("knowledge-bases") or {}).items()
    }


def is_kb_root(path: Path) -> bool:
    return (path / "schema" / "vocabulary.yaml").is_file() and (path / "pyproject.toml").is_file()


def find_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if is_kb_root(candidate):
            return candidate
    return None


def resolve(selector: str | None, config: dict) -> Path:
    names = registered(config)
    for label, value in (("-C", selector), ("$KB_DIR", os.environ.get("KB_DIR"))):
        if value is None or (label == "$KB_DIR" and not value):
            continue
        if not value:
            raise SystemExit(f"kb: {label} needs a path or a registered name")
        path = names.get(value) or Path(os.path.expanduser(value))
        root = find_root(path.resolve()) if path.exists() else None
        if root is None:
            known = f" (registered: {', '.join(sorted(names))})" if names else ""
            raise SystemExit(f"kb: {label} {value!r} is neither a knowledge base nor a registered name{known}")
        return root
    root = find_root(Path.cwd().resolve())
    if root:
        return root
    default = config.get("default")
    if default:
        target = names.get(default)
        if target is None or not is_kb_root(target):
            raise SystemExit(f"kb: default {default!r} -> {target or 'not registered'} is not a knowledge base ({config_path()})")
        return target
    raise SystemExit(
        "kb: not inside a knowledge base. Use -C PATH|NAME, set $KB_DIR, "
        f"or register one with a default in {config_path()}"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if os.environ.get(GUARD):
        raise SystemExit(
            "kb: the knowledge base's environment has no `kb` command, so the global launcher was found "
            "instead; run `just setup` (or `uv sync`) in the knowledge base"
        )
    if args[:1] in (["--help-launcher"], []):
        print(USAGE.format(config=config_path()))
        return 0 if args else 2
    selector = None
    if args[0] in ("-C", "--kb"):
        if len(args) < 2:
            raise SystemExit("kb: -C needs a path or a registered name")
        selector, args = args[1], args[2:]
    elif args[0].startswith("--kb="):
        selector, args = args[0].split("=", 1)[1], args[1:]
    config = load_config(strict=selector is None or args[:1] == ["--list"])
    if args[:1] == ["--list"]:
        for name, path in sorted(registered(config).items()):
            mark = "*" if name == config.get("default") else " "
            state = "" if is_kb_root(path) else "  (missing)"
            print(f"{mark} {name}\t{path}{state}")
        return 0
    root = resolve(selector, config)
    if args[:1] == ["--which"]:
        print(root)
        return 0
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("kb: `uv` is not on PATH (https://docs.astral.sh/uv/)")
    env = dict(os.environ, KB_REPO_ROOT=str(root), **{GUARD: "1"})
    command = [uv, "run", "--project", str(root), "--quiet", "kb", *args]
    if os.name == "nt":  # no exec on Windows: wait and forward the exit code
        import subprocess

        try:
            return subprocess.call(command, env=env)
        except KeyboardInterrupt:
            return 130
    os.execve(uv, command, env)
    return 0  # not reached


if __name__ == "__main__":
    raise SystemExit(main())
