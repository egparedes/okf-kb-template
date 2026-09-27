# Copier questions

`copier copy` asks these questions, defined in `copier.yml`. The answers are
recorded in `.copier-answers.yml` in the knowledge base, and `copier update`
offers them as defaults.

| Question | Type | Default | Validation | Effect |
|---|---|---|---|---|
| `kb_name` | text | `my-kb` | lowercase kebab-case | Package name of the tooling (`<kb_name>-tools` in `pyproject.toml`) and default qmd collection name. |
| `kb_title` | text | `My Knowledge Base` | | Title of `README.md` and `AGENTS.md`. |
| `kb_description` | text | `A personal knowledge base maintained with LLM agents.` | | First paragraph of `README.md` and `AGENTS.md`. |
| `owner_id` | text | `me` | `[a-z0-9._-]` only | Your OKF actor, `human:<owner_id>`: written by the Obsidian templates in `generated.by`, and used in `AGENTS.md` for `verified`. |
| `agent_actor` | text | `claude-code/claude-opus-5-5` | `<tool>/<model>` | Default `generated.by` for agents: `KB_ACTOR` in `.claude/settings.json`. |
| `domains` | YAML mapping | `general` | see below | The knowledge-domain folders in `schema/taxonomy.yaml`. |
| `obsidian` | yes/no | yes | | Adds `kb/.obsidian/` settings, `kb/_templates/` (Templater), `kb/_views/` (Bases) and `docs/obsidian-setup.md`. |
| `claude_code` | yes/no | yes | | Adds `CLAUDE.md` and `.claude/` (settings, hooks, the `skills` symlink). |
| `github_ci` | yes/no | yes | | Adds `.github/workflows/kb.yml`. |
| `run_setup` | yes/no | yes | | Runs the post-copy tasks (below). Needs uv. |

## `domains`

A mapping from folder slug to a title and a description:

```yaml
distributed-systems:
  title: Distributed systems
  description: Consistency, consensus, replication and failure.
science:
  title: Science
  description: Natural sciences.
science/physics:
  title: Physics
  description: Classical and quantum physics.
```

- Slugs are kebab-case segments separated by `/`, at most 3 levels deep.
- A nested slug such as `science/physics` needs its parent (`science`) in
  the mapping too.
- Every domain needs a `title` and a `description`; they become the entries
  of the generated `index.md` files.
- Top-level domains are placed in the "Knowledge domains" group of the root
  index.

The answer is only used when the knowledge base is created. Afterwards,
edit `schema/taxonomy.yaml` directly.

At the prompt, type the mapping on one line in YAML flow style:
`{general: {title: General, description: Anything else.}}`. For longer
answers, write a YAML file with a top-level `domains:` key and pass it with
`--data-file domains.yml`.

## Post-copy tasks

With `run_setup`, Copier runs, in the new repository:

| Task | When |
|---|---|
| `uv run --quiet kb log Initialization "Created the knowledge base from okf-kb-template."` | on `copy` only |
| `uv run --quiet kb index` | on `copy` and `update` |

They need `--trust` on the command line. Without them the bundle has no
`index.md` files; `just setup` generates them later.

## Non-interactive use

```sh
uvx copier copy --trust --defaults \
  --data kb_name=cookbook --data kb_title="Cookbook" --data obsidian=false \
  --data-file domains.yml \
  gh:egparedes/okf-kb-template cookbook
```

`--defaults` accepts the default of every question not given with `--data`
or `--data-file`.
