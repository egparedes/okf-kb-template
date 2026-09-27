# just recipes

The `justfile` at the root of a knowledge base holds short commands for
people and agents. Run `just` to list them. Recipes run from the repository
root, whatever directory you call them from; most call
`uv run --quiet kb …` (see the [kb command line](cli.md)). `<folder>` below
is the knowledge-base folder, the value of the [`bundle`](#variables)
variable.

| Recipe | Runs | Purpose |
|---|---|---|
| `just setup` | `git init` (if needed), `uv sync`, `uv run pre-commit install`, `kb index` | Install the Python tooling and the git hook, and generate the indexes. Safe to run again. |
| `just check [FILES…]` | `kb check [FILES…]` | Validate OKF conformance and house rules, optionally only the given files. |
| `just fix` | `kb fix-links`, then `kb index` | Normalize links to the `/…` form, then regenerate every `index.md`. |
| `just index` | `kb index` | Regenerate every `index.md`. |
| `just validate-okf` | the pinned okf-skills validator on `<folder>/` | Independent second opinion on OKF conformance. Fails on spec violations; tolerates warnings such as wanted pages. Needs network access. |
| `just report` | `kb report` | Health report: trust tiers, stale pages, uncited pages, unused sources, wanted pages, drafts. |
| `just health` | `kb report`, `kb graph`, `kb dupes`, `kb unlinked` | All maintenance candidates, read-only. |
| `just find ARGS…` | `kb find ARGS…` | List pages by frontmatter, e.g. `just find --type Concept --tag distributed-systems`. |
| `just search QUERY…` | `qmd query … -c <collection>`, or ripgrep over `<folder>/` | Hybrid search when the qmd collection exists; otherwise ripgrep over the words of the query (3 characters or more), ranked by match count. |
| `just search-setup` | `qmd collection add <folder>`, `qmd context add` per folder, `qmd embed` | One-time qmd setup for this knowledge base. The collection records the folder's path: after a rename, remove the collection and run this again. |
| `just search-reindex` | `qmd update`, `qmd embed` | Refresh the qmd index after changes. |
| `just links-online` | `lychee` over `<folder>/**/*.md` | Check external URLs, as the weekly CI job does. Needs lychee. |
| `just obsidian-setup [ARGS…]` | `kb obsidian setup [ARGS…]` | *New in v0.4.0.* Install the pinned Obsidian plugins; `--add`, `--force`, `--open` as in [`kb obsidian setup`](cli.md#kb-obsidian-setup). |
| `just rename-bundle NEW` | `git mv`, `uvx copier recopy … --data bundle_dir=NEW`, `git add -u`, `uv sync`, `kb index` | *New in v0.5.0.* Rename the knowledge-base folder to `NEW`, re-render the template-managed files that name it, and stage the result. Close Obsidian first. See [below](#rename-bundle). |
| `just test` | `uv run pytest -q` | Run the tooling's own tests. |
| `just ci` | `check`, `validate-okf`, `test`, then `kb index --check` | Everything the CI `validate` job runs. |

## Variables

| Variable | Default | Meaning |
|---|---|---|
| `kb` | `uv run --quiet kb` | How recipes call the tooling. |
| `bundle` | `bundle` in the `[tool.kb]` table of `pyproject.toml`, or `kb` if it is missing | *New in v0.5.0.* The knowledge-base folder, relative to the repository root. Print it with `just --evaluate bundle`. |
| `okf_validator` | URL of `okf_validate.py` in scaccogatto/okf-skills, pinned to a commit | The independent validator. |
| `qmd_collection` | `$KB_QMD_COLLECTION`, or else `kb_name` (read from `pyproject.toml`), or `kb` if that cannot be read | *New in v0.4.0.* The qmd collection of this knowledge base. Before v0.4.0 it was always `kb`. |

Override a variable for one call with `just qmd_collection=other search "…"`.
Do not override `bundle` to rename the folder; use `just rename-bundle`.

## `rename-bundle`

*New in v0.5.0.* `just rename-bundle NEW` renames the knowledge-base folder
from `<folder>` to `NEW`. The task-oriented guide is
[Rename the knowledge-base folder](../how-to/rename-the-knowledge-base-folder.md).

It refuses to run, and changes nothing, when:

- `NEW` is not lowercase kebab-case;
- `NEW` is `schema`, `tools`, `docs`, `imports`, `template`, `launcher` or
  `site` (folders of the repository), or `sources`, `syntheses`,
  `entities`, `projects` or `journal` (standard folders inside the
  knowledge base);
- `<folder>/` does not exist, or `NEW` already exists;
- `<folder>/NEW` exists, for example a domain folder of that name;
- `_commit` in `.copier-answers.yml` is empty, so the template version to
  re-render is unknown;
- tracked files outside `<folder>/`, or in `<folder>/_templates/`, have
  uncommitted changes: the re-render may overwrite them. It lists them.
  Changes to pages and vault settings, and untracked files, are fine: they
  move with the folder.

If `NEW` is already the name, it says so and exits 0. Otherwise it:

1. moves `<folder>/` to `NEW/` with `git mv` when the folder has tracked
   files (with `mv` otherwise). `git mv` stages the renames and keeps the
   history. Untracked notes and the installed plugins move along but stay
   untracked, and modified pages stay unstaged;
2. runs `uvx copier recopy --trust --defaults --overwrite --skip-tasks
   --vcs-ref=<_commit> --data bundle_dir=NEW`, which re-renders the
   template-managed files at the template version recorded in
   `.copier-answers.yml` and records the new answer. This needs access to
   the template repository. Copier validates `NEW` as it validates the
   [`bundle_dir` question](copier-questions.md#bundle_dir), so it also
   refuses the slug of a domain in the recorded `domains` answer. If the
   recopy fails, the recipe moves the folder back, restores the managed
   files and `<folder>/_templates/` to `HEAD`, reports that everything was
   put back as it was, and exits 1;
3. compares each re-rendered managed file with `HEAD`, ignoring the folder
   name. Files that differ in more than the name had committed local edits
   that the re-render reverted, for example a hand-edited `KB_ACTOR` in
   `.claude/settings.json`; it lists them in a `WARNING`;
4. stages the changes to tracked files outside the folder and in
   `NEW/_templates/` (`git add -u`). It never stages untracked files;
5. replaces the folder name in `.cache/kb-touched.txt`, the Stop hook's list
   of pages the current agent session changed;
6. runs `uv sync` and `kb index`, and prints what it staged, the `WARNING`
   if any, the next steps (review `git diff --cached`, commit), what to fix
   by hand (mentions of the old folder in `README.md` and in the comments
   of `schema/*.yaml`), and the Obsidian and qmd steps.

It does not commit, and does not touch files owned by the knowledge base,
such as `README.md`.
