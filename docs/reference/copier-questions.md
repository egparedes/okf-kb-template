# Copier questions

`copier copy` asks these questions, defined in `copier.yml`. The answers are
recorded in `.copier-answers.yml` in the knowledge base, and `copier update`
offers them as defaults.

| Question | Type | Default | Validation | Effect |
|---|---|---|---|---|
| `kb_name` | text | `my-kb` | lowercase kebab-case | Package name of the tooling (`<kb_name>-tools` in `pyproject.toml`), default qmd collection name, and default of `bundle_dir`. |
| `kb_title` | text | `My Knowledge Base` | | Title of `README.md` and `AGENTS.md`. |
| `kb_description` | text | `A personal knowledge base maintained with LLM agents.` | | First paragraph of `README.md` and `AGENTS.md`. |
| `owner_id` | text | `me` | `[a-z0-9._-]` only | Your OKF actor, `human:<owner_id>`: written by the Obsidian templates in `generated.by`, and used in `AGENTS.md` for `verified`. |
| `agent_actor` | text | `claude-code/claude-opus-5-5` | `<tool>/<model>` | Default `generated.by` for agents: `KB_ACTOR` in `.claude/settings.json`. |
| `domains` | YAML mapping | `general` | see below | The knowledge-domain folders in `schema/taxonomy.yaml`. |
| `bundle_dir` | text | `kb_name` for a new knowledge base; `kb` on update of one created before v0.5.0 | lowercase kebab-case; not a folder of the repository, a standard folder or a domain | *New in v0.5.0.* The knowledge-base folder, which holds the bundle and is the Obsidian vault. See [below](#bundle_dir). |
| `obsidian` | yes/no | yes | | Adds `.obsidian/` settings, `_templates/` (Templater) and `_views/` (Bases) to the knowledge-base folder, and `docs/obsidian-setup.md`. |
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

## `bundle_dir`

*New in v0.5.0.* The folder, inside the repository, that holds the
knowledge base itself: the OKF bundle and, with `obsidian`, the Obsidian
vault. Obsidian names a vault after its folder, so this is also the name
the vault shows in Obsidian. Before v0.5.0 the folder was always `kb/`.

The default depends on the operation:

| Operation | Default |
|---|---|
| `copier copy` | the answer to `kb_name`: `copier copy … my-notes` with `kb_name: my-notes` creates `my-notes/my-notes/`. Choose another name, such as `notes`, if you prefer. |
| `copier update` of a knowledge base created before v0.5.0 | `kb`, so nothing moves. Accept it, and rename the folder afterwards with [`just rename-bundle`](../how-to/rename-the-knowledge-base-folder.md) if you want another name. |
| later `copier update`s | the recorded answer, as for every question. |

Copier tells a new knowledge base from an existing one by reading the
previous answers file, `.copier-answers.yml`, before it asks the questions
(`_external_data` in `copier.yml`). On a first `copier copy` that file does
not exist yet, and Copier prints
`MissingFileWarning: File not found; returning empty dict: .copier-answers.yml`.
The warning is expected and harmless.

Copier asks it after `domains`. The answer must be lowercase kebab-case
(`^[a-z0-9]+(-[a-z0-9]+)*$`), and must not be:

- the name of another folder of the repository or the template: `schema`,
  `tools`, `docs`, `imports`, `template`, `launcher` or `site`;
- the name of a standard folder inside the knowledge base: `sources`,
  `syntheses`, `entities`, `projects` or `journal`;
- the slug of a top-level domain in the `domains` answer. Copier then says
  "`X` is also a domain folder; pick another name (e.g. `X-kb`)". A domain
  folder with the same name as the knowledge-base folder would make paths
  such as `X/page.md` ambiguous.

The answer determines:

- the folder itself, with `index.md`, `log.md` and, with `obsidian`,
  `.obsidian/`, `_templates/` and `_views/`;
- `bundle = "<bundle_dir>"` in the `[tool.kb]` table of `pyproject.toml`.
  The `kb` command, the `bundle` just variable and the CI link check read
  the name from there, not from `.copier-answers.yml`; a missing entry means
  `kb`;
- the folder name written into `.gitignore`, `.pre-commit-config.yaml`,
  `AGENTS.md`, `CLAUDE.md`, the three skills, `README.md`,
  `docs/obsidian-setup.md` and the comments of `schema/taxonomy.yaml` (see
  [Repository layout](repository-layout.md#files-rendered-with-the-folder-name)).

Do not change the answer during `copier update`. Copier does not move your
pages: the tooling would point at a new folder that holds only the
template's files, and the pages would stay in the old one. To rename the
folder, run `just rename-bundle NEW` instead
([Rename the knowledge-base folder](../how-to/rename-the-knowledge-base-folder.md)).
The `kb` command and the `kb_name` answer keep their names either way.

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
  --data kb_name=cookbook --data bundle_dir=recipes --data kb_title="Cookbook" --data obsidian=false \
  --data-file domains.yml \
  gh:egparedes/okf-kb-template cookbook
```

`--defaults` accepts the default of every question not given with `--data`
or `--data-file`. Here the knowledge-base folder is `cookbook/recipes/`;
without `--data bundle_dir=…` it would be `cookbook/cookbook/`.
