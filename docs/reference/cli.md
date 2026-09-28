# kb command line

The `kb` command is the tooling of a knowledge base, installed in its
`.venv` by uv on the first `uv run`. Run it from anywhere inside the
repository:

```sh
uv run kb <command> [options]
```

The [tasks](tasks.md) (`uv run poe …`) are short names for the commands
used most.

With the [global launcher](#the-global-launcher) installed, `kb <command>`
works inside any knowledge base, and elsewhere with `-C`, `$KB_DIR` or a
configured default.

## Finding the knowledge base

`kb` looks for the repository root, the nearest directory at or above the
current one that contains `schema/vocabulary.yaml`. `KB_REPO_ROOT`, when
set, overrides the search.

The bundle is the knowledge-base folder: `<root>/<folder>`, where `<folder>`
is `bundle` in the `[tool.kb]` table of `pyproject.toml`. It is named after
`kb_name` by default, and is `kb` when the table or the key is missing, as in
knowledge bases created before v0.5.0. `--bundle` overrides it. See
[Repository layout](repository-layout.md#the-knowledge-base-folder).

| Global option | Meaning |
|---|---|
| `--bundle PATH` | Bundle root (default: the knowledge-base folder, `<repo>/<folder>`). Goes before the command. |

Paths given to `check` and `fix-links` may be relative to the current
directory, to the repository root, or to the bundle (with or without a
leading `<folder>/` or `/`). `new`, `mv`, `merge`, `unlinked`,
`import --into` and `zotero --path` take bundle paths only (a leading
`<folder>/` or `/` is accepted), and so do `find --folder` and the
`links:` values of an [import mapping](import-mapping.md). With a
knowledge-base folder named `my-kb`, `my-kb/ai/llm.md`, `/ai/llm.md` and
`ai/llm.md` name the same page.

A leading `<folder>/` is stripped only when the path does not also exist
inside the bundle: if the path, or its parent folder, exists inside the
knowledge-base folder, it is read as a bundle path. So when the bundle
holds a folder with the same name as itself, such as a domain `my-kb/` in
the knowledge-base folder `my-kb/`, `my-kb/page.md` means the page in that
domain. Copier and [`kb rename-bundle`](#kb-rename-bundle) refuse such
names, but a domain added later can still create one.

Messages show pages as the repository sees them, `<folder>/<path>`, for
example `my-kb/ai/llm.md:12: W030 …` or `wrote my-kb/index.md`. With
`--bundle` pointing outside the repository, `<folder>` is the name of that
directory.

Exit status: 0 on success, 1 on failure. `kb check` and `kb index --check`
use 1 for "problems found". Usage errors (an unknown option, a missing
command) and the hooks' blocking results use 2 (see [`kb hook`](#kb-hook)).

Every command loads `.env` from the repository root first; variables already
set in the environment take precedence.

## Commands

| Command | Purpose |
|---|---|
| [`check`](#kb-check) | Validate OKF conformance and house rules |
| [`index`](#kb-index) | Regenerate every `index.md` |
| [`fix-links`](#kb-fix-links) | Rewrite internal links as bundle-absolute `/paths` |
| [`mv`](#kb-mv) | Move or rename a page and rewrite inbound links |
| [`merge`](#kb-merge) | Fold a duplicate page into another |
| [`new`](#kb-new) | Create a page skeleton with valid frontmatter |
| [`log`](#kb-log) | Add an entry to the bundle's `log.md` |
| [`find`](#kb-find) | List pages by frontmatter |
| [`folders`](#kb-folders) | Print the indexed folders and their descriptions |
| [`search`](#kb-search) | Search the pages: qmd when set up, otherwise text search |
| [`report`](#kb-report) | Health report |
| [`graph`](#kb-graph) | Link-graph analytics |
| [`dupes`](#kb-dupes) | Near-duplicate candidates |
| [`unlinked`](#kb-unlinked) | Unlinked mentions of other pages |
| [`zotero`](#kb-zotero) | Read-only Zotero access |
| [`karakeep`](#kb-karakeep) | Archive a web page in KaraKeep |
| [`fetch`](#kb-fetch) | Text of an external resource into `.cache/sources/` |
| [`open`](#kb-open) | Open an external resource |
| [`import`](#kb-import) | Convert an Obsidian vault or Logseq graph |
| [`obsidian setup`](#kb-obsidian-setup) | Install the pinned Obsidian plugins and open the vault |
| [`setup`](#kb-setup) | First-time setup of a clone |
| [`rename-bundle`](#kb-rename-bundle) | Rename the knowledge-base folder |
| [`hook`](#kb-hook) | Agent hook entry points (Claude Code, Codex, Gemini CLI) |

### `kb check`

Validate OKF v0.2 conformance and the house rules. Prints one line per
diagnostic, `path:line: CODE message`, then a summary on stderr.

```sh
uv run kb check [PATHS…] [--strict] [--errors-only]
```

| Argument or option | Meaning |
|---|---|
| `PATHS` | Only check these `.md` files. Bundle-level checks (folders in the taxonomy, index freshness, `resources.yaml`) are skipped. |
| `--strict` | Exit 1 on warnings too. |
| `--errors-only` | Print errors only (warnings still count in the summary). |

Exits 1 when there is at least one error. The codes are listed in
[Check codes](check-codes.md).

### `kb index`

Regenerate every `index.md` from frontmatter and `schema/taxonomy.yaml`, and
remove stale ones.

```sh
uv run kb index [--check]
```

| Option | Meaning |
|---|---|
| `--check` | Write nothing; print each out-of-date index and exit 1 if there is any. |

### `kb fix-links`

Rewrite internal links as bundle-absolute `/paths`, in bodies and in
frontmatter relations. A link is resolved relative to the linking file
first, then relative to the bundle root; a link that resolves to nothing is
left as it is. Generated `index.md` files are skipped.

```sh
uv run kb fix-links [PATHS…]
```

| Argument | Meaning |
|---|---|
| `PATHS` | Only fix these files (default: every page). |

### `kb mv`

Move or rename a page, rewrite every link to it, and regenerate the
indexes.

```sh
uv run kb mv OLD NEW
```

| Argument | Meaning |
|---|---|
| `OLD` | Bundle-relative path of the page, e.g. `ai/llm.md`. |
| `NEW` | New bundle-relative path. |

### `kb merge`

Fold a duplicate page into another, after you have merged the body text by
hand. It:

- merges `OLD`'s frontmatter into `INTO`: aliases (plus `OLD`'s title),
  tags, sources and relations;
- drops `INTO`'s `verified` (the merged page needs a new review) and sets
  its `generated` to the actor and the current time;
- deletes `OLD` and points every link to it at `INTO`;
- regenerates the indexes.

It refuses reserved files, merging a page into itself, pages without valid
frontmatter, and two sources with the same id but different resources.

```sh
uv run kb merge OLD INTO [--dry-run] [--by ACTOR]
```

| Argument or option | Meaning |
|---|---|
| `OLD` | Page to remove. |
| `INTO` | Page that absorbs it. |
| `--dry-run` | Print what would change; write nothing. |
| `--by ACTOR` | Actor for `generated.by` (default: `$KB_ACTOR`). |

### `kb new`

Create a page with valid frontmatter and the body sections of its type
(from `schema/vocabulary.yaml`). Prints the path of the new file.

```sh
uv run kb new TYPE PATH --title TITLE --description TEXT [--tags a,b] [--status draft] [--resource URL] [--by ACTOR]
```

| Argument or option | Meaning |
|---|---|
| `TYPE` | A type from `schema/vocabulary.yaml`, e.g. `Concept`. Quote types with spaces: `"Decision Record"`. |
| `PATH` | Bundle-relative path, e.g. `ai/llm-wiki.md`. `.md` is added if missing. |
| `--title` | Required. |
| `--description` | Required. One sentence. |
| `--tags` | Comma-separated kebab-case tags. |
| `--status` | `draft` (default), `stable` or `deprecated`. |
| `--resource` | Canonical URL. `Source` pages need it: `kb new` does not enforce it, but `kb check` reports H013 without it. |
| `--by` | Actor for `generated.by`, e.g. `claude-code/<model>` or `human:<id>` (default: `$KB_ACTOR`; one of the two is required). See below. |

Example:

```sh
uv run kb new Source sources/rfc-9110.md --title "RFC 9110: HTTP Semantics" \
  --description "The IETF standard that defines the semantics of HTTP." \
  --resource https://www.rfc-editor.org/rfc/rfc9110 --tags http,standards
```

The actor must match the `actor` pattern of `schema/frontmatter.schema.json`:
`<tool>/<model>` (letters, digits, `.`, `_`, `-`; the model may also contain
`:`), `human:<id>` or `process:<id>` (`<id>` in `[a-z0-9._-]`). A bracketed
suffix on the model, such as the context-window marker in Claude Code's
`claude-opus-5-5[1m]`, is dropped: `generated.by` becomes
`claude-code/claude-opus-5-5`. Any other actor is refused, with a message
that names `--by` or `KB_ACTOR`, before a file is written. `kb merge` checks
its actor the same way.

### `kb log`

Add `* **Op**: message` to `<folder>/log.md` under today's `## YYYY-MM-DD`
heading (UTC), creating the heading if needed, newest first.

```sh
uv run kb log OP MESSAGE…
```

| Argument | Meaning |
|---|---|
| `OP` | The operation: one word (letters and `-`), capitalized on output. Usual values: `Ingest`, `Query`, `Lint`, `Update`, `Creation`, `Deprecation`, `Refactor`, `Initialization`. |
| `MESSAGE` | Entry text. Link pages as `[Title](/path.md)`. Several words are joined with spaces. |

An entry is one line. Line breaks in the message are replaced by spaces, so
a message cannot start a heading or another entry. An empty message is
refused.

### `kb find`

List pages whose frontmatter matches every given filter, one per line as
`/path<TAB>type<TAB>title`.

```sh
uv run kb find [--type TYPE] [--tag TAG]… [--status STATUS] [--folder FOLDER] [--trust TIER]
```

| Option | Meaning |
|---|---|
| `--type` | Exact type, e.g. `Concept`. |
| `--tag` | Repeatable; the page must have all given tags. |
| `--status` | `draft`, `stable` or `deprecated`. A page without `status` counts as `stable`. |
| `--folder` | Bundle-relative folder prefix, e.g. `ai`. |
| `--trust` | `unverified`, `machine-confirmed` or `human-reviewed`. |

### `kb folders`

Print `folder<TAB>title: description` for every folder that gets an index.
[`kb search --setup`](#kb-search) creates a qmd context for each of them.

```sh
uv run kb folders
```

### `kb search`

*New in v0.6.0.* Search the pages of the knowledge base, and set up or
refresh its [qmd](https://github.com/tobi/qmd) index. See
[Enable search](../how-to/enable-search.md).

```sh
uv run kb search QUERY…
uv run kb search --setup
uv run kb search --reindex
```

| Argument or option | Meaning |
|---|---|
| `QUERY` | Words to search for, joined with spaces. Required unless `--setup` or `--reindex` is given. |
| `--setup` | One-time qmd setup: create the collection over `<folder>/**/*.md`, add a context for the knowledge base and one per indexed folder (the title and description from `schema/taxonomy.yaml`, as [`kb folders`](#kb-folders) prints them), then compute the embeddings (`qmd embed`). |
| `--reindex` | Refresh the qmd index after changes: `qmd update`, then `qmd embed`. |

The qmd collection is named after the knowledge base: `$KB_QMD_COLLECTION`
when set, otherwise `kb_name` (read from the project name `<kb_name>-tools`
in `pyproject.toml`), or `kb` if that cannot be read.

With a query, `kb search`:

- runs `qmd query QUERY -c <collection>` when qmd is on the `PATH` and the
  collection exists, and exits with qmd's status;
- otherwise runs a built-in text search: it keeps the words of the query
  that have 3 characters or more (letters, digits, `_` and `-`), counts
  their case-insensitive matches in each page, skips `index.md` files, and
  prints the 20 pages with the most matches as `<folder>/path:count`. When
  no word is long enough, it searches for the whole query. No output means
  no match; the exit status is 0 either way.

`--setup` and `--reindex` stop with "qmd is not installed" when `qmd` is
not on the `PATH`.

### `kb report`

Print a markdown health report: pages by type, trust tiers of knowledge
pages, status counts, stale pages, uncited knowledge pages, unused sources,
broken links (wanted pages) and drafts.

```sh
uv run kb report
```

### `kb graph`

Link-graph analytics over knowledge pages. Generated indexes, `log.md`,
`_`-prefixed folders and, by default, personal areas are excluded; links to
Source pages count as citations. See
[Maintenance analytics](../explanation/maintenance-analytics.md).

```sh
uv run kb graph [--scope knowledge|all] [--top N] [--json]
```

| Option | Meaning |
|---|---|
| `--scope` | `knowledge` (default) or `all`, which includes personal areas such as `projects/` and `journal/`. |
| `--top` | Length of the ranked lists (default 15). |
| `--json` | Print JSON instead of markdown. |

### `kb dupes`

Print near-duplicate candidate pairs, `score  /a  <->  /b  [signals]`, and
a count on stderr. Read-only.

```sh
uv run kb dupes [--min-score X] [--body] [--scope knowledge|all] [--json]
```

| Option | Meaning |
|---|---|
| `--min-score` | Lowest score to report (default 0.6). |
| `--body` | Also compare page text (slower). |
| `--scope` | `knowledge` (default) or `all`. |
| `--json` | Print JSON. |

### `kb unlinked`

Print mentions of other pages' titles and aliases that are not linked, as
`page:line  "text" -> target` with a snippet, then names shared by several
pages. Read-only.

```sh
uv run kb unlinked [PAGES…] [--min-len N] [--all] [--json]
```

| Argument or option | Meaning |
|---|---|
| `PAGES` | Only scan these pages (bundle paths). |
| `--min-len` | Ignore names shorter than this (default 4); all-caps aliases are exempt. |
| `--all` | Also scan personal areas. |
| `--json` | Print JSON. |

### `kb zotero`

Read-only Zotero access: the local API, then the web API, then a snapshot
of the database. See [Connect Zotero](../how-to/connect-zotero.md).

```sh
uv run kb zotero search WORDS… [--limit N]
uv run kb zotero show KEY
uv run kb zotero new-source KEY [--path PATH] [--tags a,b] [--by ACTOR]
```

| Action or option | Meaning |
|---|---|
| `search WORDS…` | Print `key<TAB>citekey<TAB>year<TAB>title` for matching items. |
| `show KEY` | Print the item as JSON. `KEY` is an item key or a citation key. |
| `new-source KEY` | Create a draft Source page with the item's metadata and a `zotero` pointer. |
| `--limit` | `search`: maximum results (default 20). |
| `--path` | `new-source`: bundle path (default `sources/<slug>.md`, the kebab-case citation key). |
| `--tags` | `new-source`: comma-separated tags. |
| `--by` | `new-source`: actor (default `$KB_ACTOR`). |

### `kb karakeep`

Archive a web page in KaraKeep. Prints `already saved: <id>` or
`saved: <id>`. See [Connect KaraKeep](../how-to/connect-karakeep.md).

```sh
uv run kb karakeep save URL
```

### `kb fetch`

Write the text of an external resource to `.cache/sources/` and print the
file's path.

```sh
uv run kb fetch REF
```

| `REF` form | Resolved through |
|---|---|
| `zotero:<key or citekey>` | Zotero (full text) |
| `file:<root>/<path>` | The root's local path from `KB_ROOT_<ROOT>`; non-text files converted with markitdown |
| `https://…` or `karakeep:<url>` | KaraKeep, archiving the page first if it has no bookmark |

Denied paths are refused.

### `kb open`

Open an external resource with the desktop's default handler (`xdg-open`,
or `open` on macOS), and print what was opened.

```sh
uv run kb open REF [--print]
```

| Argument or option | Meaning |
|---|---|
| `REF` | Same forms as `kb fetch`. Zotero items open as `zotero://select/…`. |
| `--print` | Only print what would be opened. |

### `kb import`

Convert an Obsidian vault or Logseq graph into bundle pages. The source is
never modified. See [Import a vault](../how-to/import-a-vault.md) and the
[import mapping reference](import-mapping.md).

```sh
uv run kb import SOURCE --into FOLDER --map MAPPING [--dry-run] [--by ACTOR] [--redirects FILE]
```

| Argument or option | Meaning |
|---|---|
| `SOURCE` | Vault or graph directory. |
| `--into` | Required. Bundle folder that relative `to` paths start from. |
| `--map` | Required. Mapping file (YAML). |
| `--dry-run` | Print the plan and issues; write nothing. |
| `--by` | Actor for `generated.by` (default: `actor` in the mapping). |
| `--redirects` | Where to write the source → bundle path table (default `.cache/import/<vault>-redirects.tsv`). |

Exits 1 when the plan has errors; a real run then writes nothing.

### `kb obsidian setup`

*New in v0.4.0.* Install the pinned Obsidian community plugins listed in
`<folder>/.obsidian/community-plugins.json` and, optionally, open the vault. See
[Set up Obsidian](../how-to/set-up-obsidian.md).

```sh
uv run kb obsidian setup [--add ID[,ID…]] [--force] [--open]
```

| Option | Meaning |
|---|---|
| `--add` | Also install these plugin IDs and add them to `community-plugins.json`. Each must be pinned in `tools/obsidian-plugins.json`; otherwise the command stops with "no pin for …". The required plugins are always added back to the list. |
| `--force` | Download plugins again even when the pinned version is installed. |
| `--open` | Open the knowledge-base folder in Obsidian through `obsidian://open?path=…` (a vault Obsidian already knows; the first time, use *Open folder as vault*). |

Plugins are downloaded from their GitHub releases, as pinned in
`tools/obsidian-plugins.json`, into `<folder>/.obsidian/plugins/<id>/`, and their
SHA-256 checksums are verified. Listed IDs without a pin are reported. The
command ends by printing the two manual steps, trusting the vault and
turning on Templater's trigger on new file creation, and the folder to open
as the vault.

### `kb setup`

*New in v0.6.0.* First-time setup of a clone, run by `uv run poe setup`.
`uv run` has already created `.venv` and installed the tooling. It:

1. runs `git init` if the repository root is not inside a git repository;
2. installs the pre-commit hook (`pre-commit install`);
3. repairs `.claude/skills` when git checked the symlink out as a small text
   file (Git for Windows without symlink support); see
   [below](#claudeskills-on-windows);
4. regenerates every `index.md`, printing each file it writes.

```sh
uv run kb setup
```

Safe to run again.

#### `.claude/skills` on Windows

`.claude/skills` is a symlink to `../.agents/skills`, so Claude Code and the
other agents read the same skills. Git for Windows without symlink support
(`core.symlinks=false`) checks it out as a text file that holds the target,
and Claude Code then finds no skills. `kb setup` replaces that file with the
first of these that works:

1. a symlink (Windows with Developer Mode, or an elevated shell);
2. a directory junction, which needs no privileges;
3. a copy of `.agents/skills`, marked with a `.kb-copy-of-agents-skills`
   file. Each later `kb setup` refreshes the copy, so run
   `uv run poe setup` again after the skills change.

It then hides the difference from git (`git update-index --skip-worktree`
on `.claude/skills`, and `/.claude/skills/` in `.git/info/exclude`). A
broken link or junction, such as a junction that still points at the old
location after the repository moved, is replaced the same way. It leaves a
working link, an unrelated file and a folder you made alone.

### `kb rename-bundle`

*New in v0.6.0; the `just rename-bundle` recipe of v0.5.0, with the same
behaviour.* Rename the knowledge-base folder from `<folder>` to `NEW`: move
it, re-render the template-managed files that name it, and stage the
result. Close Obsidian first. The task-oriented guide is
[Rename the knowledge-base folder](../how-to/rename-the-knowledge-base-folder.md).

```sh
uv run kb rename-bundle NEW
```

| Argument | Meaning |
|---|---|
| `NEW` | New folder name, lowercase kebab-case. |

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
   files (with a plain move otherwise). `git mv` stages the renames and
   keeps the history. Untracked notes and the installed plugins move along
   but stay untracked, and modified pages stay unstaged;
2. runs `uvx copier recopy --trust --defaults --overwrite --skip-tasks
   --vcs-ref=<_commit> --data bundle_dir=NEW`, which re-renders the
   template-managed files at the template version recorded in
   `.copier-answers.yml` and records the new answer. This needs access to
   the template repository. Copier validates `NEW` as it validates the
   [`bundle_dir` question](copier-questions.md#bundle_dir), so it also
   refuses the slug of a domain in the recorded `domains` answer. If the
   recopy fails, it moves the folder back, restores the managed files and
   `<folder>/_templates/` to `HEAD`, reports that everything was put back
   as it was, and exits 1;
3. compares each re-rendered managed file with `HEAD`, ignoring the folder
   name. Files that differ in more than the name had committed local edits
   that the re-render reverted, for example a hand-edited `KB_ACTOR` in
   `.claude/settings.json`; it lists them in a `WARNING`;
4. stages the changes to tracked files outside the folder and in
   `NEW/_templates/` (`git add -u`). It never stages untracked files;
5. replaces the folder name in `.cache/kb-touched.txt`, the Stop hook's list
   of pages the current agent session changed;
6. regenerates the indexes (the next `uv run` syncs the tooling with the
   re-rendered `pyproject.toml`), and prints what it staged, the `WARNING`
   if any, the next steps (review `git diff --cached`, commit), what to fix
   by hand (mentions of the old folder in `README.md` and in the comments
   of `schema/*.yaml`), and the Obsidian and qmd steps.

If a step after the re-render fails, it stops with a message that asks you
to run `uv run kb index`, then review `git diff --cached`.

It does not commit, and does not touch files owned by the knowledge base,
such as `README.md`.

### `kb hook`

Entry points for the agent hooks in `.claude/settings.json`,
`.codex/hooks.json` and `.gemini/settings.json`. They read the hook payload
(JSON) on stdin. See [Agents and hooks](../explanation/agents-and-hooks.md).

```sh
uv run kb hook EVENT [--agent claude|codex|gemini]
uv run python -m kbtools.hooks EVENT [--agent claude|codex|gemini]
```

The second form is the same command without loading the rest of `kb`; the
hook configurations use it because the shell hooks run on every command.

| Event | When | What it does |
|---|---|---|
| `pre-tool` | Before a shell command (Codex: also before a patch) | Records the digest of `log.md` if this is the session's first event, and a listing of the knowledge base's `.md` files (path, modification time, size, content hash; dot-folders skipped). Always exits 0, even on errors, so it never blocks a command. |
| `post-tool` | After it, also when it failed (Claude Code: `PostToolUseFailure`) | Compares the listing: pages whose content was created, changed or deleted are recorded for the session, and those that exist are checked with `kb check`. |
| `post-edit` | After a file tool wrote `tool_input.file_path` (Claude Code: Write, Edit; Gemini CLI: `write_file`, `replace`) | If it is a `.md` file in the knowledge-base folder: records it and runs `kb check` on it. |
| `stop` | Before the agent finishes (Gemini CLI: `AfterAgent`) | Every page recorded this session passes `kb check`, the indexes above them are fresh, and if knowledge pages changed, `log.md` differs from its digest at the session's start. |

`--agent` selects how problems reach the agent:

| `--agent` | `post-tool`, `post-edit` | `stop` |
|---|---|---|
| `claude` (default) | exit 2, problems on stderr | exit 2, problems on stderr |
| `codex` | exit 0, problems as `hookSpecificOutput.additionalContext` JSON on stdout | exit 2, problems on stderr |
| `gemini` | the same as `codex`; `{}` on stdout when there is nothing to say | exit 2, problems on stderr; `{}` otherwise |

Codex and Gemini CLI replace the output of a tool with the stderr of a
hook that exits 2, so the post-tool problems come as added context there
instead, and the agent still sees what its command printed.

The session state lives in `.cache/kb-hooks/<session id>/`, keyed by the
payload's `session_id` (`default` without one). A clean stop deletes it;
the state of other sessions is removed at the next clean stop of any
session once it is 7 days old. `.cache/kb-hooks/hashes.json` caches the
content hashes of the listings.

## The global launcher

*New in v0.4.0.* The optional `kb` launcher (package `okf-kb`) is installed
once per machine and runs the `kb` of the right knowledge base. See
[Install the kb launcher](../how-to/install-the-cli-launcher.md).

```sh
kb [-C PATH|NAME] COMMAND [ARGS…]
kb [-C PATH|NAME] --which
kb --list
kb --help-launcher
```

| Option | Meaning |
|---|---|
| `-C`, `--kb` (also `--kb=…`) | Use this knowledge base: a directory inside it, or a name from the configuration file. Must come first. |
| `--list` | Print the registered knowledge bases: name and path, `*` before the default, `(missing)` after paths that are not knowledge bases. |
| `--which` | Print the knowledge base root that would be used. |
| `--help-launcher` | Print the launcher's usage. `kb -h` is passed to the knowledge base's tool. |

Without `-C`, the launcher uses `$KB_DIR` (a path or a name), then the nearest parent of the
current directory that contains `schema/vocabulary.yaml`, then the `default`
entry of `$XDG_CONFIG_HOME/okf-kb/config.toml` (default `~/.config/okf-kb/config.toml`). A knowledge-base root is a folder with `schema/vocabulary.yaml` and `pyproject.toml`. Without arguments, the launcher prints its usage and exits 2. It runs
`uv run --project <root> --quiet kb ARGS…` with `KB_REPO_ROOT=<root>`, in
the current directory. The configuration file is read only for a name, the
`default` or `--list`; a broken file does not stop a call that gives a path
or runs inside a knowledge base.
