# Repository layout

A knowledge base generated with every option enabled and the default
answers (`kb_name` and `bundle_dir` both `my-kb`) looks like this.

```text
my-kb/
├── AGENTS.md                    conventions and workflows for every agent
├── CLAUDE.md                    Claude Code: imports AGENTS.md, adds hook notes      [claude_code]
├── README.md                    the knowledge base's own README
├── .copier-answers.yml          template source, version and answers (written by Copier)
├── .agents/skills/              kb-ingest, kb-query, kb-maintain (SKILL.md each)
├── .claude/
│   ├── settings.json            hooks, KB_ACTOR, Read(.env) denied                   [claude_code]
│   └── skills -> ../.agents/skills                                                   [claude_code]
├── .github/workflows/kb.yml     validation on push, weekly link check                [github_ci]
├── .pre-commit-config.yaml      fix-links, index, check before each commit
├── .env.example                 template for the gitignored .env
├── .gitignore
├── pyproject.toml, uv.lock      the tooling package <kb_name>-tools; [tool.kb] bundle; the tasks
├── tasks.toml                   this knowledge base's own tasks (new in v0.6.0)
├── docs/
│   ├── external-resources.md    Zotero, KaraKeep, file roots
│   ├── importing.md             kb import and its mapping format
│   └── obsidian-setup.md        vault settings and plugins                           [obsidian]
├── schema/
│   ├── frontmatter.schema.json  core frontmatter profile
│   ├── vocabulary.yaml          page types, relations, extra fields
│   ├── taxonomy.yaml            folders, titles, descriptions, groups
│   └── resources.yaml           file roots, deny patterns, Zotero user id
├── tools/
│   ├── kbtools/                 the kb command line (Python)
│   ├── tests/                   its tests
│   ├── obsidian-plugins.json    pinned Obsidian plugins (new in v0.4.0)
│   └── retrieval-eval/questions.yaml   questions for kb eval, which judges the search tiers
├── my-kb/                       the knowledge-base folder: OKF bundle and Obsidian vault
│   ├── index.md                 generated
│   ├── log.md                   newest-first update log
│   ├── <domains>/               your knowledge domains
│   ├── sources/  syntheses/  entities/
│   ├── projects/  journal/
│   ├── _templates/              Templater templates (type: Template)                 [obsidian]
│   ├── _views/                  Bases dashboards (*.base)                            [obsidian]
│   └── .obsidian/               vault settings                                       [obsidian]
├── .cache/                      gitignored scratch: fetched sources, drafts, hook state
└── .venv/                       gitignored Python environment
```

Items marked `[claude_code]`, `[github_ci]` or `[obsidian]` exist only when
that [Copier question](copier-questions.md) was answered *Yes*.

## The knowledge-base folder

The folder that holds the pages is the OKF bundle and, with `obsidian`, the
Obsidian vault. Its name is the answer to the
[`bundle_dir` question](copier-questions.md#bundle_dir): by default the
knowledge base's `kb_name` (`my-kb/` above), and `kb/` in knowledge bases
created before v0.5.0. Everything inside it is addressed relative to the
folder itself: a link `/ai/llm.md` means `<folder>/ai/llm.md`, whatever the
folder is called. On this site, `<folder>/` stands for its name.

The name is recorded in `pyproject.toml`:

```toml
[tool.kb]
# Folder of the knowledge base (OKF bundle) in this repository; rename it with `uv run poe rename-bundle`.
bundle = "my-kb"
```

| Reader | How it uses `[tool.kb] bundle` |
|---|---|
| the `kb` command | The bundle is `<repo>/<bundle>`, unless `--bundle` is given. The tasks that run `kb`, such as `search-setup` and `rename-bundle`, use it this way. |
| `.github/workflows/kb.yml` | The weekly link check; the `validate` job through `uv run poe ci`. |

When the table or the key is missing, both use `kb`. The `validate-okf` and
`links-online` [tasks](tasks.md) do not read the table: Copier writes the
folder name into them when it renders `pyproject.toml`. `pyproject.toml`
is managed by the template, so edit the name only through
[`uv run poe rename-bundle`](../how-to/rename-the-knowledge-base-folder.md), which
also moves the folder and re-renders the files below.

## Files rendered with the folder name

These files contain the folder name, written when Copier renders them:

| File | Where the name appears | Re-rendered by `copier update` and `uv run poe rename-bundle` |
|---|---|---|
| `pyproject.toml` | `[tool.kb] bundle`, the package description, the `validate-okf` and `links-online` tasks | yes |
| `.gitignore` | the Obsidian and `.trash/` patterns | yes |
| `.pre-commit-config.yaml` | the `files:` patterns of the hooks | yes |
| `AGENTS.md`, `CLAUDE.md` | the map and the rules | yes |
| `.agents/skills/*/SKILL.md` | paths in the three skills | yes |
| `docs/obsidian-setup.md` | the folder to open as the vault | yes |
| `README.md` | the layout and the Obsidian steps | no: owned by the knowledge base |
| `schema/taxonomy.yaml` | comments at the top | no: owned by the knowledge base |

After a rename, update the old name in the owned files by hand.

## Managed by the template

`copier update` merges upstream changes into these files. Change them in the
template, or in your fork of it, rather than locally.

- the tooling: `tools/kbtools/`, `tools/tests/`, `pyproject.toml` with its tasks,
  `tools/obsidian-plugins.json`;
- the agent layer: `AGENTS.md`, `CLAUDE.md`, `.agents/skills/`,
  `.claude/settings.json`;
- `.pre-commit-config.yaml`, `.github/workflows/kb.yml`,
  `.gitignore`, `.env.example`;
- `schema/frontmatter.schema.json`;
- `docs/`;
- the Templater templates in `<folder>/_templates/`.

## Owned by the knowledge base

These files are created once and listed in `_skip_if_exists` in the
template's `copier.yml`, so `copier update` never overwrites them:

| Pattern in `_skip_if_exists` | Files |
|---|---|
| `README.md` | the knowledge base's README |
| `schema/vocabulary.yaml` | page types, relations, `fields` |
| `schema/taxonomy.yaml` | the folder tree |
| `schema/resources.yaml` | file roots, deny patterns, Zotero ids |
| `tools/retrieval-eval/questions.yaml` | retrieval evaluation questions for [`kb eval`](cli.md#kb-eval) |
| `tasks.toml` | the knowledge base's own [tasks](tasks.md#local-tasks-taskstoml) (new in v0.6.0) |
| `{{ bundle_dir }}/log.md` | the update log |
| `{{ bundle_dir }}/.obsidian/*.json` | Obsidian settings, including `community-plugins.json` |
| `{{ bundle_dir }}/.obsidian/plugins/*/data.json` | plugin settings, such as Templater's folder templates |
| `{{ bundle_dir }}/_views/*.base` | Bases dashboards |

`{{ bundle_dir }}` is the name of the knowledge-base folder. Every page in
the folder is owned by the knowledge base too: the template creates
no pages, only the generated indexes and the Templater templates.

Because the vocabulary extends the core schema (relation keys and
`fields`), a knowledge base can add types, relations and properties without
editing a managed file.

## Never committed

`.gitignore` keeps these out of git:

| Path | Why |
|---|---|
| `.env`, `.env.*` (except `.env.example`) | secrets and machine paths |
| `.cache/` | fetched sources, drafts, import redirect tables, the hook's list of touched files |
| `.venv/`, `__pycache__/`, `.pytest_cache/` | Python environment |
| `<folder>/.obsidian/plugins/*/*` except Templater's `data.json` | plugin code (downloaded, never redistributed) and plugin settings that may hold keys |
| `<folder>/.obsidian/workspace*.json`, `<folder>/.obsidian/graph.json.bak`, `<folder>/.obsidian/themes/` | per-device state |
| `<folder>/.trash/` | deleted notes; `.md` files there would break the bundle |
| `<folder>/.smart-env/` | a plugin's local cache |
| `.qmd/`, `.ck/` | local search indexes |
| `.claude/settings.local.json` | personal Claude Code overrides |
