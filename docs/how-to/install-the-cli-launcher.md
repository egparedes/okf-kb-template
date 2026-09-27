# Install the kb launcher

Each knowledge base carries its own copy of the `kb` tool, in its own
`.venv`. Inside a knowledge base, `uv run kb …` and `just …` always work and
need nothing else. The launcher is an optional global `kb` command that
finds the right knowledge base and runs *its* tool, so you can type `kb`
from any directory.

## Install

The launcher needs [uv](https://docs.astral.sh/uv/) on your `PATH`.

```sh
uv tool install "git+https://github.com/egparedes/okf-kb-template#subdirectory=launcher"
```

Upgrade it later with:

```sh
uv tool upgrade okf-kb
```

The launcher does not change which version of the tooling a knowledge base
uses. That version comes from the knowledge base itself; see
[Update from the template](update-from-the-template.md).

## Use it

Every argument after the options goes to the knowledge base's own `kb`:

```sh
cd ~/notes-kb/kb/ai
kb find --type Concept          # the knowledge base that contains this directory
kb -C ~/notes-kb check          # an explicit path
kb -C work report               # a registered name (see below)
```

The launcher picks the knowledge base in this order:

1. `-C PATH|NAME` or `--kb PATH|NAME`;
2. the `KB_DIR` environment variable, also a path or a registered name;
3. the nearest parent of the current directory that contains
   `schema/vocabulary.yaml` and `pyproject.toml` (a knowledge base root);
4. the `default` entry of the configuration file.

A path may be any directory inside a knowledge base; the launcher walks up
to its root.

It then runs `uv run --project <root> --quiet kb <args>` with
`KB_REPO_ROOT=<root>` set. The current directory stays the same, so file
arguments relative to where you are keep working.

## Register knowledge bases by name

Create `~/.config/okf-kb/config.toml` (or `$XDG_CONFIG_HOME/okf-kb/config.toml`):

```toml
default = "work"

[knowledge-bases]
work = "~/work-kb"
notes = "~/notes-kb"   # relative paths are relative to this file
```

Check the configuration:

```sh
kb --list          # registered names and paths; * marks the default
kb --which         # the knowledge base root a command would use from here
kb -C notes --which
```

```text
  notes	/home/alice/notes-kb
* work	/home/alice/work-kb
```

A path that is not a knowledge base is marked `(missing)`.

`kb -h` and `kb <command> -h` show the help of the knowledge base's own
tool; `kb --help-launcher` shows the launcher's.

!!! warning "Do not export `KB_REPO_ROOT`"
    The `kb` tool treats `KB_REPO_ROOT` as the knowledge base root. If you
    export it in your shell profile, every call, including `uv run kb` inside
    another knowledge base, goes to that one. The launcher sets it for each
    call only. To choose a default, use `default` in the configuration file
    or `KB_DIR`.

## Related

- [Run several knowledge bases](multiple-knowledge-bases.md)
- [kb command line reference](../reference/cli.md#the-global-launcher)
