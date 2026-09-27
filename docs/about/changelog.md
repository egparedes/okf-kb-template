# Changelog

Releases are git tags. A knowledge base records its tag in
`.copier-answers.yml`; see [Update from the template](../how-to/update-from-the-template.md).

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
