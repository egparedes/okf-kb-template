# just recipes

The `justfile` at the root of a knowledge base holds short commands for
people and agents. Run `just` to list them. Recipes run from the repository
root, whatever directory you call them from; most call
`uv run --quiet kb …` (see the [kb command line](cli.md)).

| Recipe | Runs | Purpose |
|---|---|---|
| `just setup` | `git init` (if needed), `uv sync`, `uv run pre-commit install`, `kb index` | Install the Python tooling and the git hook, and generate the indexes. Safe to run again. |
| `just check [FILES…]` | `kb check [FILES…]` | Validate OKF conformance and house rules, optionally only the given files. |
| `just fix` | `kb fix-links`, then `kb index` | Normalize links to the `/…` form, then regenerate every `index.md`. |
| `just index` | `kb index` | Regenerate every `index.md`. |
| `just validate-okf` | the pinned okf-skills validator on `kb/` | Independent second opinion on OKF conformance. Fails on spec violations; tolerates warnings such as wanted pages. Needs network access. |
| `just report` | `kb report` | Health report: trust tiers, stale pages, uncited pages, unused sources, wanted pages, drafts. |
| `just health` | `kb report`, `kb graph`, `kb dupes`, `kb unlinked` | All maintenance candidates, read-only. |
| `just find ARGS…` | `kb find ARGS…` | List pages by frontmatter, e.g. `just find --type Concept --tag distributed-systems`. |
| `just search QUERY…` | `qmd query … -c <collection>`, or ripgrep | Hybrid search when the qmd collection exists; otherwise ripgrep over the words of the query (3 characters or more), ranked by match count. |
| `just search-setup` | `qmd collection add`, `qmd context add` per folder, `qmd embed` | One-time qmd setup for this knowledge base. |
| `just search-reindex` | `qmd update`, `qmd embed` | Refresh the qmd index after changes. |
| `just links-online` | `lychee` over `kb/**/*.md` | Check external URLs, as the weekly CI job does. Needs lychee. |
| `just obsidian-setup [ARGS…]` | `kb obsidian setup [ARGS…]` | *New in v0.4.0.* Install the pinned Obsidian plugins; `--add`, `--force`, `--open` as in [`kb obsidian setup`](cli.md#kb-obsidian-setup). |
| `just test` | `uv run pytest -q` | Run the tooling's own tests. |
| `just ci` | `check`, `validate-okf`, `test`, then `kb index --check` | Everything the CI `validate` job runs. |

## Variables

| Variable | Default | Meaning |
|---|---|---|
| `kb` | `uv run --quiet kb` | How recipes call the tooling. |
| `okf_validator` | URL of `okf_validate.py` in scaccogatto/okf-skills, pinned to a commit | The independent validator. |
| `qmd_collection` | `$KB_QMD_COLLECTION`, or else `kb_name` (read from `pyproject.toml`), or `kb` if that cannot be read | *New in v0.4.0.* The qmd collection of this knowledge base. Before v0.4.0 it was always `kb`. |

Override a variable for one call with `just qmd_collection=other search "…"`.
