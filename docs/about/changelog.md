# Changelog

Releases are git tags. A knowledge base records its tag in
`.copier-answers.yml`; see [Update from the template](../how-to/update-from-the-template.md).
Entries before v0.6.0 name tasks as just recipes (`just X`); today, run
them as `uv run poe X`.

## v0.7.0

- **Faster and more correct checking.** Pages are parsed once and shared by
  every command: `kb check` is about twice as fast, `kb check FILE` reads
  only the given files, so the agent hooks take a fraction of a second even
  with thousands of pages, and `kb unlinked` takes seconds instead of
  minutes. The bundle is the set of files git would commit, without
  dot-folders such as `.trash/`
  ([which files are checked](../reference/check-codes.md#which-files-are-checked));
  the new global option `kb --tracked`, used by the pre-commit hooks, reads
  only what a commit contains. Link targets must match the case of the
  file on every platform, and link parsing follows CommonMark more closely
  (wrapped link text, indented fences and code blocks, code spans).
  `kb graph`, `kb dupes`, `kb unlinked` and `kb report` look at the
  [same pages](../explanation/maintenance-analytics.md#which-pages);
  orphaned `index.md` files are reported.
- **Agent guardrails: hooks, Codex, Gemini CLI.** The
  [hooks](../explanation/agents-and-hooks.md#the-hooks) also check pages
  that shell commands change, keep their state per session in
  `.cache/kb-hooks/`, and check the log against `log.md` at the start of
  the session instead of asking git. New Copier questions
  [`codex` and `gemini_cli`](../reference/copier-questions.md) add the same
  hooks for [Codex and Gemini CLI](../explanation/agents-and-hooks.md#codex-and-gemini-cli);
  Gemini CLI then reads `AGENTS.md`. Claude Code is denied shell commands
  that name `.env`. `kb new` checks the actor and always writes valid
  frontmatter; `kb log` keeps entries on one line. `kb setup` repairs
  [`.claude/skills` on Windows](../reference/cli.md#claudeskills-on-windows),
  and the launcher tolerates a broken configuration file when a knowledge
  base is named.
- **Safer import and external resources.**
  [`kb import`](../reference/cli.md#kb-import) never follows symlinks,
  rolls back on failure, and refuses destinations that clash by case or
  with a folder; `exclude` ignores case, the
  [mapping](../reference/import-mapping.md) is validated as a whole, and
  many conversions are fixed. [`kb open`](../reference/cli.md#kb-open)
  opens only web URLs, Zotero items and files under a declared root, never
  programs. `kb fetch` runs markitdown (when it is not installed, a pinned
  version through uvx, overridable with `KB_MARKITDOWN`) and stops it after
  5 minutes; neither it nor the desktop opener gets your API keys
  ([details](../explanation/external-resources.md#what-the-tool-hands-to-other-programs)).
  Zotero [group libraries](../how-to/connect-zotero.md#group-libraries)
  work with the local API, and bad settings or responses give clear errors
  instead of tracebacks.
- **`kb mv`, `kb merge` and `kb fix-links`.** [`kb mv`](../reference/cli.md#kb-mv)
  and [`kb merge`](../reference/cli.md#kb-merge) change files all or
  nothing, with backups in `.cache/kb-backup/`. `kb mv` refuses reserved
  files, hidden or ignored places and a change of extension; it moves
  images and other files, and moves into existing folders. All three
  rewrite reference definitions and frontmatter in block or flow style,
  keeping comments and quoting; `kb mv` and `kb merge` also update
  `tools/retrieval-eval/questions.yaml`.
- **`kb eval`.** [`kb eval`](../reference/cli.md#kb-eval) (`uv run poe eval`)
  reports, for the questions in `tools/retrieval-eval/questions.yaml`,
  whether each search tier (index and text search, `kb find` filters, qmd)
  reaches the expected pages (recall@k). It is deterministic, and
  `--min-recall` makes it a CI gate. See
  [Is qmd worth it?](../how-to/enable-search.md#is-qmd-worth-it)
- **Cross-platform and CI.** The template's CI runs on Linux, macOS and
  Windows. Knowledge-base CI installs from
  [`uv.lock`](../how-to/ci-and-github.md#the-lockfile) with
  `uv sync --locked`; actions are pinned to commit SHAs and kept current by
  [Dependabot](../how-to/ci-and-github.md#pinned-actions-and-dependabot);
  [`.gitattributes`](../how-to/ci-and-github.md#line-endings) keeps LF
  line endings. `kb` runs git, qmd and other programs only from absolute
  `PATH` entries, never from the current directory.
- **Lint and types.** `uv run poe lint` runs ruff over `tools/` and mypy
  over `tools/kbtools/`, and [`uv run poe ci`](../reference/tasks.md) runs
  it. The tooling is formatted with ruff.

**Upgrading.** `copier update` asks the two new questions (`codex`,
`gemini_cli`, default *No*), rewrites `.claude/settings.json`, adds
`.gitattributes` and, with GitHub CI, `.github/dependabot.yml`, and
reformats about 30 tooling files. Then run `uv lock` and commit `uv.lock`:
CI now fails when it is stale. Some behaviour changed: import mappings are
stricter, `kb mv` no longer adds `.md` to a name with another extension,
and links into dot-folders or ignored files are now wanted pages (W030).
See [Updating to v0.7.0](../how-to/update-from-the-template.md#updating-to-v070).

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
