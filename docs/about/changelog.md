# Changelog

Releases are git tags. A knowledge base records its tag in
`.copier-answers.yml`; see [Update from the template](../how-to/update-from-the-template.md).
Entries before v0.6.0 name tasks as just recipes (`just X`); today, run
them as `uv run poe X`.

## v0.6.0

- **poethepoet tasks instead of just.** The `justfile` is gone, from
  generated knowledge bases and from the template repository. The short
  commands are [poethepoet tasks](../reference/tasks.md), one-liners and
  sequences in `[tool.poe.tasks]` of `pyproject.toml`, with the same names
  as the old recipes. Run them with `uv run poe <task> [ARGS…]`; extra
  arguments are passed on, and `uv run poe` alone lists the tasks (and
  exits with status 1). poethepoet is a development dependency, so there is
  nothing to install besides uv; `uv tool install poethepoet` once makes
  `poe <task>` work anywhere. Tasks run without a shell, so they work on
  Windows, except `links-online`, which needs lychee.
- **The logic of the longer recipes moved into `kb`**:
  [`kb setup`](../reference/cli.md#kb-setup) (git repository, pre-commit
  hook, indexes), [`kb search`](../reference/cli.md#kb-search) (qmd when set
  up, otherwise a built-in text search that no longer needs ripgrep;
  `--setup` and `--reindex` for qmd) and
  [`kb rename-bundle`](../reference/cli.md#kb-rename-bundle) (the former
  recipe, same behaviour).
- **Local tasks** go in `tasks.toml`, which each knowledge base owns: the
  template creates it once and `pyproject.toml` includes it.
- The just variables are gone. The folder name is written into the tasks
  that need it; `kb search` computes the qmd collection name, and
  `KB_QMD_COLLECTION` can now also be set in `.env`.
- CI runs `uv run poe ci`; the step that installed just is gone.
- Template repository: `uv run poe test | render [DEST] | docs | docs-serve`.

**Upgrading.** `copier update` deletes the `justfile`, even an edited one
(recover your own recipes with `git show HEAD:justfile`), and adds
`tasks.toml`. Replace `just X` with `uv run poe X`, also in your
`README.md`, and move your own recipes into `tasks.toml`. See
[Updating to v0.6.0](../how-to/update-from-the-template.md#updating-to-v060).

## v0.5.0

- **Configurable knowledge-base folder.** The folder that holds the bundle
  and is the Obsidian vault is no longer always `kb/`. The new Copier
  question [`bundle_dir`](../reference/copier-questions.md#bundle_dir),
  asked after `domains`, names it, after `kb_name` by default, so each vault
  gets its own name in Obsidian. It cannot be the name of a domain or of a
  standard folder such as `sources`. The name is recorded in
  `[tool.kb] bundle` in `pyproject.toml`, and the `kb` command, the new
  `bundle` just variable and CI read it from there. The `kb` command keeps its name. See
  [Repository layout](../reference/repository-layout.md#the-knowledge-base-folder).
- **`just rename-bundle NEW`** renames the folder of an existing knowledge
  base: it moves the folder with `git mv`, re-renders the template-managed
  files that name it, stages the result for review, warns about local edits
  the re-render reverted, and regenerates the indexes. If the re-render
  fails, it puts everything back.
  [How-to](../how-to/rename-the-knowledge-base-folder.md).
- `kb` messages show paths as `<folder>/…`, and path arguments accept a
  leading `<folder>/` as well as `/` (unless the path also exists inside the
  bundle; see [the kb command line](../reference/cli.md#finding-the-knowledge-base)).
- `.gitignore`, `.pre-commit-config.yaml`, `AGENTS.md`, `CLAUDE.md`, the
  skills, `README.md` and `docs/obsidian-setup.md` are rendered with the
  folder name.
- On a first `copier copy`, Copier prints a harmless `MissingFileWarning`
  about `.copier-answers.yml`: the template reads the previous answers, if
  any, to choose the default of `bundle_dir`.

**Upgrading.** `copier update` asks `bundle_dir` with the default `kb`:
accept it, and nothing moves. Existing knowledge bases keep `kb/`. To give
the folder, and so the Obsidian vault, another name, commit the update and
then run `just rename-bundle <name>`. See
[Updating to v0.5.0](../how-to/update-from-the-template.md#updating-to-v050).

## v0.4.0

- **Global launcher.** An optional `kb` command (package `okf-kb`, in
  `launcher/`) runs the right knowledge base's own tool from any directory:
  `-C PATH|NAME`, `KB_DIR`, the enclosing knowledge base, or a default from
  `~/.config/okf-kb/config.toml`; `kb --list`, `kb --which`.
  [Install it](../how-to/install-the-cli-launcher.md).
- **Several knowledge bases per machine.** The qmd collection is named after
  `kb_name` (override: `KB_QMD_COLLECTION`) instead of `kb`.
  *Action:* `qmd collection remove kb && just search-setup`.
- **Obsidian setup automation.** `just obsidian-setup` (`kb obsidian setup`)
  downloads the pinned community plugins, verifies their checksums, and
  with `--open` opens the vault if Obsidian already knows it. The default plugin list is now Templater
  and Better Markdown Links; five more are pinned and added with `--add`.
  Plugin code is never committed. Requires Obsidian 1.13.7 or later. A newer version that Obsidian installed is kept.
  *Action:* run `just obsidian-setup`. Existing knowledge bases keep their
  own `community-plugins.json`.
- `kb dupes` no longer pairs two Journal Entry pages.
- The template is licensed [MIT-0](license.md).
- Public documentation site.

## v0.3.0 (2026-09-26)

- `kb import`: deterministic conversion of an Obsidian vault or Logseq graph
  into bundle pages, driven by a mapping file, with a dry run and a redirect
  table. [How-to](../how-to/import-a-vault.md),
  [reference](../reference/import-mapping.md).

## v0.2.2 (2026-09-26)

- CI: current action versions, read-only permissions, manual runs; the
  weekly link check covers only `http(s)` URLs and tolerates 403 and 429.
- `just setup` also generates the indexes; `just links-online` matches CI.
- `.gitignore`: `.env.*` ignored (except the example); only the Templater
  plugin settings are tracked.
- Documentation: Web Clipper recipe, Templater caveat, first-launch
  settings files, private-template credentials.

## v0.2.1 (2026-09-26)

- KaraKeep: `KARAKEEP_URL` may end in `/api` or `/api/v1`; requests send a
  User-Agent, which the hosted service requires.

## v0.2.0 (2026-09-25)

- **External resources:** Zotero (local API, web API, database snapshot),
  KaraKeep by URL, and file roots with deny patterns: `kb zotero`,
  `kb karakeep`, `kb fetch`, `kb open`, the `zotero` and `locators` keys,
  `schema/resources.yaml`, `.env.example`.
- **Maintenance analytics:** `kb graph` (generated indexes excluded),
  `kb dupes`, `kb unlinked`, `kb merge`, and `just health`.
- `kb check`: wikilinks and embeds are errors (H032); future timestamps
  (W041); malformed `resources.yaml` (H061). `kb new` creates drafts.
- The Stop hook checks only the pages the session changed.

## v0.1.0 (2026-09-25)

- First release: the `kb` tool (`check`, `index`, `fix-links`, `mv`, `new`,
  `log`, `find`, `report`, hooks), the agent layer (`AGENTS.md`,
  `CLAUDE.md`, the ingest, query and maintain skills, Claude Code hooks),
  Obsidian configuration, pre-commit, CI, and template tests that render
  several configurations and exercise `copier update`.
