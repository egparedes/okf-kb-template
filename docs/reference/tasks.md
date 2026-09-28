# Tasks

*New in v0.6.0; earlier releases had a `justfile` with the same recipes
(see [below](#before-v060-just-recipes)).* The short commands for people
and agents are [poethepoet](https://poethepoet.natn.io) (`poe`) tasks,
defined in `[tool.poe.tasks]` of `pyproject.toml`. Each one is a single
command or a sequence of commands; the logic lives in the
[kb command line](cli.md). `<folder>` below is the knowledge-base folder,
`bundle` in the [`[tool.kb]` table](repository-layout.md#the-knowledge-base-folder)
of `pyproject.toml`.

## Running tasks

```sh
uv run poe <task> [ARGS…]
```

- poethepoet is a development dependency of the tooling, so `uv run`
  installs it into the knowledge base's `.venv` with the rest. There is
  nothing else to install.
- Tasks run from the repository root, whatever directory you call them
  from.
- Arguments after the task name are passed on to the command of a
  single-command task, options included: `uv run poe check my-kb/ai/llm.md`
  runs `kb check my-kb/ai/llm.md`, and `uv run poe find --type Tool` runs
  `kb find --type Tool`. The sequences, `fix`, `health` and `ci`, take no
  arguments and ignore any you give.
- `uv run poe -d <task> [ARGS…]` prints what a task would run without
  running it.

## Listing the tasks

`uv run poe` without a task prints the usage and every task with its help
text, then exits with status 1: that is how poe reports that no task was
given. `uv run poe --help <task>` shows the usage of one task.

## Every task

| Task | Runs | Purpose |
|---|---|---|
| `setup` | [`kb setup`](cli.md#kb-setup): `git init` (if needed), `pre-commit install`, `kb index` | First-time setup of a clone: the git repository, the pre-commit hook and the indexes. `uv run` has already synced the tools. Safe to run again. |
| `check [FILES…]` | `kb check [FILES…]` | Validate OKF conformance and house rules, optionally only the given files; `--strict` and `--errors-only` as in [`kb check`](cli.md#kb-check). |
| `fix` | `kb fix-links`, then `kb index` | Normalize links to the `/…` form, then regenerate every `index.md`. |
| `index` | `kb index` | Regenerate every `index.md`. `--check` as in [`kb index`](cli.md#kb-index). |
| `validate-okf` | the pinned okf-skills validator on `<folder>/`, through `uv run` | Independent second opinion on OKF conformance. Fails on spec violations; tolerates warnings such as wanted pages. Needs network access. |
| `report` | `kb report` | Health report: trust tiers, stale pages, uncited pages, unused sources, wanted pages, drafts. |
| `health` | `kb report`, `kb graph`, `kb dupes`, `kb unlinked` | All maintenance candidates, read-only. |
| `find ARGS…` | `kb find ARGS…` | List pages by frontmatter, e.g. `uv run poe find --type Concept --tag distributed-systems`. |
| `links-online` | `lychee` over `<folder>/**/*.md` | Check external URLs, as the weekly CI job does. Needs [lychee](https://lychee.cli.rs). |
| `search QUERY…` | [`kb search QUERY…`](cli.md#kb-search) | Hybrid search with qmd when the knowledge base's collection exists; otherwise a built-in text search over the words of the query. |
| `search-setup` | `kb search --setup` | One-time qmd setup for this knowledge base: the collection, a context per folder, the embeddings. The collection records the folder's path: after a rename, remove the collection and run this again. |
| `search-reindex` | `kb search --reindex` | Refresh the qmd index after changes (`qmd update`, `qmd embed`). |
| `eval [ARGS…]` | [`kb eval [ARGS…]`](cli.md#kb-eval) | Retrieval evaluation: recall@k of each search tier on `tools/retrieval-eval/questions.yaml`; `--k`, `--json`, `--min-recall`, `--no-qmd` as in `kb eval`. |
| `obsidian-setup [ARGS…]` | `kb obsidian setup [ARGS…]` | Install the pinned Obsidian plugins; `--add`, `--force`, `--open` as in [`kb obsidian setup`](cli.md#kb-obsidian-setup). |
| `rename-bundle NEW` | [`kb rename-bundle NEW`](cli.md#kb-rename-bundle) | Rename the knowledge-base folder to `NEW`, re-render the template-managed files that name it, and stage the result. Close Obsidian first. See [Rename the knowledge-base folder](../how-to/rename-the-knowledge-base-folder.md). |
| `test` | `pytest -q` | Run the tooling's own tests. |
| `ci` | `check`, `validate-okf`, `test`, then `kb index --check` | Everything the CI `validate` job runs. |

The folder name is written into `validate-okf` and `links-online` when
Copier renders `pyproject.toml`; `rename-bundle` renders it again with the
new name. The qmd collection name is computed by `kb`; see
[Enable search](../how-to/enable-search.md#the-collection-name).

## `poe` without `uv run`

Install poethepoet once as a uv tool:

```sh
uv tool install poethepoet
```

Then `poe <task>` works in any knowledge base, and in any other project
with poe tasks: `poe check`, `poe search "typed relations"`. poe finds the
`pyproject.toml` of the directory you are in, or of the nearest parent that
has one.

## Local tasks: `tasks.toml`

`pyproject.toml` is managed by the template: local edits there survive
`copier update` only as long as Copier can merge them. Put the knowledge
base's own tasks in `tasks.toml` at the repository root instead. The
template creates it once, empty apart from an example, and never
overwrites it (it is in `_skip_if_exists`). `pyproject.toml` includes it
through `[tool.poe] include`, so its tasks appear in `uv run poe` next to
the template's:

```toml
[tool.poe.tasks.new-note]
help = "Create a Concept page"
cmd = "kb new Concept"
```

`uv run poe new-note ai/llm.md --title "LLM" --description "…"` then runs
`kb new Concept ai/llm.md …`. The
[poethepoet documentation](https://poethepoet.natn.io/tasks/index.html)
describes the other task types, such as sequences, `args` and `env`.

A task in `tasks.toml` with the same name as a template task is ignored:
the template's task in `pyproject.toml` wins. Give local tasks their own
names.

## Windows

Tasks are plain commands run without a shell, so they work on Windows as
on Linux and macOS. The exception is `links-online`, which needs lychee
installed and on the `PATH`.

## Before v0.6.0: just recipes

Until v0.5.0 the tasks were [just](https://just.systems) recipes in a
`justfile`, run as `just <recipe>`. The tasks keep their names: replace
`just X` with `uv run poe X`. The just variables are gone:

| Variable | Now |
|---|---|
| `kb` | Tasks call `kb` directly. |
| `bundle` | Written into the tasks that need it when Copier renders `pyproject.toml`. Read it in `[tool.kb] bundle`. |
| `okf_validator` | Written into the `validate-okf` task. |
| `qmd_collection` | Computed by `kb search`: `$KB_QMD_COLLECTION`, else `kb_name`. |

See [Updating to v0.6.0](../how-to/update-from-the-template.md#updating-to-v060).
