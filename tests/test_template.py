"""Render the template in a few configurations and run each result's own checks."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from copier import run_copy

TEMPLATE = Path(__file__).resolve().parents[1]

VARIANTS = {
    "defaults": {},
    "custom-folder": {"kb_name": "team-notes", "bundle_dir": "notes-vault", "codex": True, "gemini_cli": True},
    "minimal": {
        "kb_name": "cookbook",
        "obsidian": False,
        "claude_code": False,
        "github_ci": False,
        "domains": {
            "baking": {"title": "Baking", "description": "Bread and pastry."},
            "baking/sourdough": {"title": "Sourdough", "description": "Wild-yeast breads."},
        },
    },
}


def render(tmp_path: Path, answers: dict) -> Path:
    dst = tmp_path / "kb-instance"
    run_copy(str(TEMPLATE), dst, data=answers, defaults=True, unsafe=True, quiet=True, vcs_ref="HEAD")
    return dst


def run(cmd: list[str], cwd: Path) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert result.returncode == 0, f"{' '.join(cmd)} failed:\n{result.stdout}\n{result.stderr}"
    return result.stdout + result.stderr


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")  # LF on Windows too, like a checkout


def venv_command(project: Path, name: str) -> str:
    """A console script of the project's virtual environment (bin/ on POSIX, Scripts/*.exe on Windows)."""
    if os.name == "nt":
        return str(project / ".venv" / "Scripts" / f"{name}.exe")
    return str(project / ".venv" / "bin" / name)


def fake_command(tmp_path: Path, name: str, body: str) -> dict[str, str]:
    """An environment whose PATH starts with a stand-in `name` that runs the Python `body`:
    a shell script on POSIX, a .bat wrapper on Windows (found through PATHEXT)."""
    bin_dir, scripts = tmp_path / "fake-bin", tmp_path / "fake-scripts"
    bin_dir.mkdir(exist_ok=True)
    scripts.mkdir(exist_ok=True)
    script = scripts / f"{name}.py"
    write(script, body)
    if os.name == "nt":
        (bin_dir / f"{name}.bat").write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8", newline="")
    else:
        write(bin_dir / name, f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        (bin_dir / name).chmod(0o755)
    return dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def posix_shell() -> list[str] | None:
    """The shell that runs a hook command: /bin/sh on POSIX, Git Bash on Windows (Claude Code
    runs its hooks with Git Bash there); None when Git Bash is not found."""
    if os.name != "nt":
        return ["/bin/sh", "-c"]
    git = shutil.which("git")
    candidates = [Path(git).resolve().parents[i] / "bin" / "bash.exe" for i in (1, 2)] if git else []
    bash = next((str(c) for c in candidates if c.is_file()), None)
    return [bash, "-c"] if bash else None


def hook_shell(agent: str) -> list[str] | None:
    """The shell each agent runs hook commands with. Gemini CLI uses PowerShell on Windows
    (Windows PowerShell 5.1 is the strictest about `;` and `||`) and bash elsewhere; Claude Code
    uses Git Bash on Windows; Codex's Windows shell is not documented (hence commandWindows)."""
    if os.name == "nt" and agent == "gemini":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        return [powershell, "-NoProfile", "-NonInteractive", "-Command"] if powershell else None
    return posix_shell()


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required to run the rendered tooling")
@pytest.mark.parametrize("variant", VARIANTS)
def test_rendered_knowledge_base_is_conformant(tmp_path: Path, variant: str) -> None:
    answers = VARIANTS[variant]
    bundle = answers.get("bundle_dir", answers.get("kb_name", "my-kb"))  # new knowledge bases: named after kb_name
    dst = render(tmp_path, answers)
    assert (dst / ".copier-answers.yml").is_file()
    assert not (dst / "kb").exists()
    assert "okf_version" in read(dst / bundle / "index.md")
    assert f'bundle = "{bundle}"' in read(dst / "pyproject.toml")
    assert f"{bundle}/.obsidian/plugins/*/*" in read(dst / ".gitignore")
    assert f"^{bundle}/" in read(dst / ".pre-commit-config.yaml")
    assert f"`{bundle}/`" in read(dst / "AGENTS.md")
    assert "* text=auto eol=lf" in read(dst / ".gitattributes")
    skills = dst / ".claude" / "skills"
    if answers.get("claude_code", True):  # a symlink, or the placeholder of a checkout without symlinks (kb setup repairs it)
        assert (skills / "kb-ingest" / "SKILL.md").is_file() or read(skills).strip() == "../.agents/skills"
    assert b"\r\n" not in (dst / "AGENTS.md").read_bytes()  # a CRLF checkout of the template would show here
    assert "0 error(s), 0 warning(s)" in run(["uv", "run", "--quiet", "kb", "check"], dst)
    run(["uv", "run", "--quiet", "kb", "index", "--check"], dst)
    run(["uv", "run", "--quiet", "pytest", "-q"], dst)
    leftovers = [p for p in dst.rglob("*") if "{%" in p.name or "{{" in p.name or p.suffix == ".jinja"]
    assert leftovers == []
    name = VARIANTS[variant].get("kb_name", "my-kb")
    probe = "from kbtools.bundle import Bundle; from kbtools import search; b = Bundle.discover(); print(b.prefix, search.qmd_collection(b))"
    assert run(["uv", "run", "--quiet", "python", "-c", probe], dst).split() == [bundle, name]
    listing = subprocess.run(["uv", "run", "--quiet", "poe"], cwd=dst, capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout  # lists, exits 1
    assert all(task in listing for task in ("setup", "check", "ci", "rename-bundle", "obsidian-setup", "search"))
    env = fake_command(tmp_path, "uv", 'import sys\nprint("uv", *sys.argv[1:])\n')  # prints its arguments (no network)
    out = subprocess.run([venv_command(dst, "poe"), "validate-okf"], cwd=dst, env=env, capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    assert out.rstrip().endswith(f"okf_validate.py {bundle}"), out
    assert not (dst / "justfile").exists() and (dst / "tasks.toml").is_file()
    _check_agent_hooks(dst, answers)


def _check_agent_hooks(dst: Path, answers: dict) -> None:
    """Each agent's hook configuration parses, and every hook command it names runs."""
    import json

    configs = {
        "claude": (dst / ".claude" / "settings.json", answers.get("claude_code", True)),
        "codex": (dst / ".codex" / "hooks.json", answers.get("codex", False)),
        "gemini": (dst / ".gemini" / "settings.json", answers.get("gemini_cli", False)),
    }
    for agent, (path, wanted) in configs.items():
        assert path.is_file() == wanted, path
        if not wanted:
            continue
        config = json.loads(read(path))
        commands = [h["command"] for groups in config["hooks"].values() for group in groups for h in group["hooks"]]
        assert commands and all("python -m kbtools.hooks" in c for c in commands)
        # Hooks that must never block the tool end in a shell-neutral "succeed anyway";
        # the stop hook must be able to exit 2. Gemini runs bash -c on POSIX, PowerShell on Windows.
        never_block = {"claude": ("pre-tool",), "codex": ("pre-tool", "post-tool"),
                       "gemini": ("pre-tool", "post-tool", "post-edit")}[agent]
        suffix = "; exit 0" if agent == "gemini" else "|| true"
        for command in commands:
            event = command.split("kbtools.hooks ", 1)[1].split()[0]
            assert command.endswith(suffix) == (event in never_block), (agent, command)
        assert any(" pre-tool" in c for c in commands)
        if agent == "claude":  # failed Bash commands fire PostToolUseFailure, not PostToolUse
            assert [g["matcher"] for g in config["hooks"]["PostToolUseFailure"]] == ["Bash"]
        if agent == "gemini":  # Gemini runs hooks in the project dir and quotes $GEMINI_PROJECT_DIR itself
            assert not any("$GEMINI_PROJECT_DIR" in c or "&&" in c or "||" in c for c in commands)
        if agent == "codex":  # the shell Codex uses on Windows is not documented: no shell syntax there
            hooks = [h for groups in config["hooks"].values() for group in groups for h in group["hooks"]]
            for h in hooks:
                windows = h.get("commandWindows", h["command"])
                assert not re.search(r"\|\||&&|;|\$", windows) and windows in h["command"], h
            if os.name == "nt":
                commands = [h.get("commandWindows", h["command"]) for h in hooks]
        env, shell = dict(os.environ, CLAUDE_PROJECT_DIR=str(dst)), hook_shell(agent)
        for command in commands if shell else ():  # Windows without Git Bash or PowerShell: not run
            payload = '{"session_id": "template-test", "tool_input": {}}'
            result = subprocess.run([*shell, command], cwd=dst, env=env, input=payload, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace")
            assert result.returncode == 0, (agent, command, result.stderr)
            assert result.stdout.strip() == ("{}" if agent == "gemini" else ""), (agent, command, result.stdout)
    if answers.get("gemini_cli"):
        assert json.loads(read(configs["gemini"][0]))["context"]["fileName"][0] == "AGENTS.md"
    shutil.rmtree(dst / ".cache" / "kb-hooks", ignore_errors=True)


@pytest.mark.parametrize("domains", [
    {"My Domain": {"title": "x", "description": "y"}},
    {"physics/quantum": {"title": "Q", "description": "Quantum."}},
    {"ok": {"title": "Only a title"}},
])
def test_invalid_domains_are_rejected(tmp_path: Path, domains: dict) -> None:
    with pytest.raises(ValueError, match="Validation error for question 'domains'"):
        render(tmp_path, {"domains": domains, "run_setup": False})


@pytest.mark.skipif(shutil.which("uv") is None or shutil.which("git") is None, reason="needs uv and git")
def test_update_keeps_owned_files_and_updates_managed_ones(tmp_path: Path) -> None:
    from copier import run_update

    src = tmp_path / "template-repo"
    shutil.copytree(TEMPLATE, src, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache"))
    git = lambda *a, cwd=src: run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd)  # noqa: E731
    git("init", "-q"), git("add", "-A"), git("commit", "-qm", "v1"), git("tag", "v0.0.1")
    dst = tmp_path / "instance"
    run_copy(str(src), dst, defaults=True, unsafe=True, quiet=True, vcs_ref="v0.0.1")
    git("init", "-q", cwd=dst), git("add", "-A", cwd=dst), git("commit", "-qm", "init", cwd=dst)
    owned = dst / "schema" / "vocabulary.yaml"
    write(owned, read(owned) + "# local edit\n")
    git("commit", "-qam", "local", cwd=dst)
    managed = src / "template" / "AGENTS.md.jinja"
    write(managed, read(managed) + "\n<!-- upstream change -->\n")
    write(src / "template" / "schema" / "vocabulary.yaml", "# upstream would clobber\n")
    git("commit", "-qam", "v2"), git("tag", "v0.0.2")
    run_update(dst, defaults=True, unsafe=True, quiet=True, overwrite=True, vcs_ref="v0.0.2")
    assert "# local edit" in read(owned)
    assert "<!-- upstream change -->" in read(dst / "AGENTS.md")
    assert "_commit: v0.0.2" in read(dst / ".copier-answers.yml")


def test_optional_parts_are_omitted(tmp_path: Path) -> None:
    dst = render(tmp_path, {**VARIANTS["minimal"], "run_setup": False})
    for path in (".claude", "CLAUDE.md", ".codex", ".gemini", ".github", "cookbook/.obsidian", "cookbook/_templates",
                 "docs/obsidian-setup.md"):
        assert not (dst / path).exists(), path
    assert "Obsidian vault" not in read(dst / "AGENTS.md")


def _template_repo(tmp_path: Path):
    src = tmp_path / "template-repo"
    shutil.copytree(TEMPLATE, src, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache", "site"))
    git = lambda *a, cwd=src: run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd)  # noqa: E731
    git("init", "-q"), git("add", "-A"), git("commit", "-qm", "v1"), git("tag", "v0.0.1")
    return src, git


def _as_pre_v05(src: Path) -> None:
    """Turn a template checkout into the v0.4 layout: no bundle_dir question, the folder is always kb/."""
    copier_yml = src / "copier.yml"
    text = read(copier_yml)
    text = re.sub(r"\nbundle_dir:\n(?:  .*\n|    .*\n)+", "\n", text)
    write(copier_yml, text.replace("{{ bundle_dir }}", "kb"))
    (src / "template" / "{{ bundle_dir }}").rename(src / "template" / "kb")
    for path in (src / "template").rglob("*.jinja"):
        write(path, read(path).replace("{{ bundle_dir }}", "kb").replace("(bundle_dir ~ '/')", "'kb/'"))
    write(src / "template" / "justfile", "# the v0.4 task runner\ncheck:\n    uv run kb check\n")


@pytest.mark.skipif(shutil.which("uv") is None or shutil.which("git") is None, reason="needs uv and git")
def test_update_of_a_pre_v05_knowledge_base_keeps_kb(tmp_path: Path) -> None:
    from copier import run_update

    src = tmp_path / "template-repo"
    shutil.copytree(TEMPLATE, src, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache", "site"))
    git = lambda *a, cwd=src: run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd)  # noqa: E731
    current = tmp_path / "current"
    shutil.copytree(src, current)
    _as_pre_v05(src)
    git("init", "-q"), git("add", "-A"), git("commit", "-qm", "v0.4-like"), git("tag", "v0.0.1")
    dst = tmp_path / "old-instance"
    run_copy(str(src), dst, data={"kb_name": "legacy", "run_setup": False}, defaults=True, unsafe=True, quiet=True, vcs_ref="v0.0.1")
    assert (dst / "kb" / "log.md").is_file() and "bundle_dir" not in read(dst / ".copier-answers.yml")
    git("init", "-q", cwd=dst), git("add", "-A", cwd=dst), git("commit", "-qm", "init", cwd=dst)
    write(dst / "justfile", read(dst / "justfile") + "mine:\n    echo local\n")
    git("commit", "-qam", "a local recipe", cwd=dst)
    for item in src.iterdir():  # v0.0.2 = the current template
        if item.name != ".git":
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    shutil.copytree(current, src, dirs_exist_ok=True)
    git("add", "-A"), git("commit", "-qm", "v0.5-like"), git("tag", "v0.0.2")
    run_update(dst, defaults=True, unsafe=True, quiet=True, overwrite=True, vcs_ref="v0.0.2")
    assert (dst / "kb" / "log.md").is_file() and not (dst / "legacy").exists()
    assert 'bundle = "kb"' in read(dst / "pyproject.toml")
    assert "kb/.obsidian/plugins/*/*" in read(dst / ".gitignore")
    assert not (dst / "justfile").exists()  # removed upstream in v0.6: deleted even though edited
    assert "mine:" in run(["git", "show", "HEAD:justfile"], dst)  # recoverable from git, as the docs say
    assert (dst / "tasks.toml").is_file()


@pytest.mark.skipif(not all(shutil.which(t) for t in ("uv", "git")), reason="needs uv and git")
def test_rename_bundle_moves_everything_and_rerenders(tmp_path: Path) -> None:
    src, git = _template_repo(tmp_path)
    dst = tmp_path / "instance"
    run_copy(str(src), dst, data={"kb_name": "demo"}, defaults=True, unsafe=True, quiet=True, vcs_ref="v0.0.1")
    git("init", "-q", cwd=dst), git("add", "-A", cwd=dst), git("commit", "-qm", "init", cwd=dst)
    (dst / "demo" / "general" / "draft-note.md").parent.mkdir(parents=True, exist_ok=True)
    write(dst / "demo" / "general" / "draft-note.md", "untracked, not committed")
    template_page = dst / "demo" / "_templates" / "knowledge-page.md"
    write(template_page, read(template_page) + "\n<!-- local edit -->\n")
    refused = subprocess.run(["uv", "run", "--quiet", "poe", "rename-bundle", "field-notes"], cwd=dst, capture_output=True,
                             text=True, encoding="utf-8", errors="replace")
    assert refused.returncode != 0 and "_templates/knowledge-page.md" in refused.stderr and (dst / "demo").is_dir()
    git("checkout", "--", "demo/_templates", cwd=dst)
    agents = dst / "AGENTS.md"
    write(agents, read(agents) + "\nA committed local note.\n")
    git("commit", "-qam", "local edit to a managed file", cwd=dst)
    (dst / "demo" / "field-notes").mkdir()
    blocked = subprocess.run(["uv", "run", "--quiet", "poe", "rename-bundle", "field-notes"], cwd=dst, capture_output=True,
                             text=True, encoding="utf-8", errors="replace")
    assert blocked.returncode != 0 and "already has a folder named field-notes" in blocked.stderr
    (dst / "demo" / "field-notes").rmdir()
    out = run(["uv", "run", "--quiet", "poe", "rename-bundle", "field-notes"], dst)
    assert "reverted" in out and "AGENTS.md" in out  # the committed local edit is reported
    staged = run(["git", "diff", "--cached", "--name-status"], dst)
    assert "R100\tdemo/log.md\tfield-notes/log.md" in staged and "M\tpyproject.toml" in staged
    assert "draft-note.md" in run(["git", "status", "--porcelain"], dst).split("??", 1)[-1]  # still untracked
    assert not (dst / "demo").exists()
    assert read(dst / "field-notes" / "general" / "draft-note.md") == "untracked, not committed"
    assert (dst / "field-notes" / "log.md").is_file()
    assert 'bundle = "field-notes"' in read(dst / "pyproject.toml")
    assert "bundle_dir: field-notes" in read(dst / ".copier-answers.yml")
    assert "field-notes/.obsidian/plugins/*/*" in read(dst / ".gitignore")
    assert "`field-notes/`" in read(dst / "AGENTS.md")
    (dst / "field-notes" / "general" / "draft-note.md").unlink()
    run(["uv", "run", "--quiet", "kb", "index"], dst)
    assert "0 error(s)" in run(["uv", "run", "--quiet", "kb", "check"], dst)
    bad = subprocess.run(["uv", "run", "--quiet", "poe", "rename-bundle", "schema"], cwd=dst, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    assert bad.returncode != 0 and "already a folder" in bad.stderr


@pytest.mark.parametrize("name", ["general", "schema", "Not_Kebab"])
def test_invalid_bundle_dir_is_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="Validation error for question 'bundle_dir'"):
        render(tmp_path, {"bundle_dir": name, "run_setup": False})


@pytest.mark.skipif(not all(shutil.which(t) for t in ("uv", "git")), reason="needs uv and git")
def test_rename_bundle_rolls_back_when_the_template_is_unreachable(tmp_path: Path) -> None:
    src, git = _template_repo(tmp_path)
    dst = tmp_path / "instance"
    run_copy(str(src), dst, data={"kb_name": "demo"}, defaults=True, unsafe=True, quiet=True, vcs_ref="v0.0.1")
    answers = dst / ".copier-answers.yml"
    text, found = re.subn(r"(?m)^_src_path: .*$", "_src_path: /nonexistent/template", read(answers))
    assert found == 1
    write(answers, text)
    git("init", "-q", cwd=dst), git("add", "-A", cwd=dst), git("commit", "-qm", "init", cwd=dst)
    failed = subprocess.run(["uv", "run", "--quiet", "poe", "rename-bundle", "field-notes"], cwd=dst, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    assert failed.returncode != 0 and "put back" in failed.stderr
    assert (dst / "demo" / "log.md").is_file() and not (dst / "field-notes").exists()
    assert run(["git", "status", "--porcelain"], dst).strip() == ""


def test_custom_folder_leaves_no_stray_kb_paths(tmp_path: Path) -> None:
    dst = render(tmp_path, {"kb_name": "team-notes", "bundle_dir": "notes-vault", "run_setup": False})
    stray = []
    for path in dst.rglob("*"):
        if path.is_dir() or "tests" in path.parts or path.suffix in (".py", ".json", ".base"):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if re.search(r"(?<![\w./-])kb/", line) and "before v0.5" not in line:
                stray.append(f"{path.relative_to(dst)}:{n}: {line.strip()}")
    assert stray == []


@pytest.mark.skipif(not all(shutil.which(t) for t in ("uv", "git")), reason="needs uv and git")
def test_rename_bundle_warns_only_about_real_edits(tmp_path: Path) -> None:
    src, git = _template_repo(tmp_path)
    dst = tmp_path / "instance"
    answers = {"kb_name": "demo", "bundle_dir": "kb", "obsidian": False, "claude_code": False}
    run_copy(str(src), dst, data=answers, defaults=True, unsafe=True, quiet=True, vcs_ref="v0.0.1")
    git("init", "-q", cwd=dst), git("add", "-A", cwd=dst), git("commit", "-qm", "init", cwd=dst)
    # to the knowledge base's own name (kb_name appears in the answers), then to a word used in
    # the text ("notes"), then back to `kb` (the `kb` command appears everywhere): all pure renames
    for old, new in (("kb", "demo"), ("demo", "notes"), ("notes", "kb")):
        out = run(["uv", "run", "--quiet", "poe", "rename-bundle", new], dst)
        assert "WARNING" not in out, (new, out)
        assert (dst / new / "log.md").is_file() and not (dst / old).exists()
        git("commit", "-qm", f"rename to {new}", cwd=dst)
    assert "0 error(s)" in run(["uv", "run", "--quiet", "kb", "check"], dst)


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")
def test_local_tasks_and_paths_with_spaces(tmp_path: Path) -> None:
    dst = render(tmp_path / "with space", {"kb_name": "demo", "run_setup": False})
    write(dst / "tasks.toml", read(dst / "tasks.toml") + 'hello = { cmd = "echo local task", help = "A local task" }\n')
    listing = subprocess.run(["uv", "run", "--quiet", "poe"], cwd=dst, capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
    assert "hello" in listing and "A local task" in listing
    env = fake_command(tmp_path, "lychee", 'import sys\nfor a in sys.argv[1:]:\n    print(f"ARG[{a}]")\n')
    out = subprocess.run([venv_command(dst, "poe"), "links-online"], cwd=dst, env=env, capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    root_dir = next((a for a in re.findall(r"ARG\[(.*)\]", out) if a.endswith("/demo")), "")
    assert Path(root_dir.removesuffix("/demo")).resolve() == dst.resolve() and "ARG[demo/**/*.md]" in out, out
