# Repository layout

A knowledge base generated with every option enabled looks like this.

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
├── justfile                     task runner (see just recipes)
├── pyproject.toml, uv.lock      the tooling package <kb_name>-tools
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
│   └── retrieval-eval/questions.yaml   questions for judging search tiers
├── kb/                          the OKF bundle and Obsidian vault
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

## Managed by the template

`copier update` merges upstream changes into these files. Change them in the
template, or in your fork of it, rather than locally.

- the tooling: `tools/kbtools/`, `tools/tests/`, `pyproject.toml`,
  `tools/obsidian-plugins.json`;
- the agent layer: `AGENTS.md`, `CLAUDE.md`, `.agents/skills/`,
  `.claude/settings.json`;
- `justfile`, `.pre-commit-config.yaml`, `.github/workflows/kb.yml`,
  `.gitignore`, `.env.example`;
- `schema/frontmatter.schema.json`;
- `docs/`;
- the Templater templates in `kb/_templates/`.

## Owned by the knowledge base

These files are created once and listed in `_skip_if_exists` in the
template's `copier.yml`, so `copier update` never overwrites them:

| Pattern in `_skip_if_exists` | Files |
|---|---|
| `README.md` | the knowledge base's README |
| `schema/vocabulary.yaml` | page types, relations, `fields` |
| `schema/taxonomy.yaml` | the folder tree |
| `schema/resources.yaml` | file roots, deny patterns, Zotero ids |
| `tools/retrieval-eval/questions.yaml` | retrieval evaluation questions |
| `kb/log.md` | the update log |
| `kb/.obsidian/*.json` | Obsidian settings, including `community-plugins.json` |
| `kb/.obsidian/plugins/*/data.json` | plugin settings, such as Templater's folder templates |
| `kb/_views/*.base` | Bases dashboards |

Every page in `kb/` is owned by the knowledge base too: the template creates
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
| `kb/.obsidian/plugins/*/*` except Templater's `data.json` | plugin code (downloaded, never redistributed) and plugin settings that may hold keys |
| `kb/.obsidian/workspace*.json`, `kb/.obsidian/themes/` | per-device state |
| `kb/.trash/` | deleted notes; `.md` files there would break the bundle |
| `kb/.smart-env/` | a plugin's local cache |
| `.qmd/`, `.ck/` | local search indexes |
| `.claude/settings.local.json` | personal Claude Code overrides |
