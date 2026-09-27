# kb command line

The `kb` command is the tooling of a knowledge base, installed in its
`.venv` by `just setup`. Run it from anywhere inside the repository:

```sh
uv run kb <command> [options]
```

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
domain. Copier and `just rename-bundle` refuse such names, but a domain
added later can still create one.

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
| [`hook`](#kb-hook) | Claude Code hook entry points |

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
| `--by` | Actor for `generated.by`, e.g. `claude-code/<model>` or `human:<id>` (default: `$KB_ACTOR`; one of the two is required). |

Example:

```sh
uv run kb new Source sources/rfc-9110.md --title "RFC 9110: HTTP Semantics" \
  --description "The IETF standard that defines the semantics of HTTP." \
  --resource https://www.rfc-editor.org/rfc/rfc9110 --tags http,standards
```

### `kb log`

Add `* **Op**: message` to `<folder>/log.md` under today's `## YYYY-MM-DD`
heading (UTC), creating the heading if needed, newest first.

```sh
uv run kb log OP MESSAGE…
```

| Argument | Meaning |
|---|---|
| `OP` | The operation, capitalized on output. Usual values: `Ingest`, `Query`, `Lint`, `Update`, `Creation`, `Deprecation`, `Refactor`, `Initialization`. |
| `MESSAGE` | Entry text. Link pages as `[Title](/path.md)`. Several words are joined with spaces. |

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
`just search-setup` uses it to create qmd contexts.

```sh
uv run kb folders
```

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

### `kb hook`

Entry points for the Claude Code hooks in `.claude/settings.json`. They read
the hook payload on stdin and exit 2 with instructions on stderr when the
agent must fix something. See
[Agents and hooks](../explanation/agents-and-hooks.md).

```sh
uv run kb hook post-edit
uv run kb hook stop
```

| Event | Checks |
|---|---|
| `post-edit` | After a Write or Edit of a `.md` file in the knowledge-base folder: records the file and runs `kb check` on it. |
| `stop` | Before the agent finishes: every page recorded this session passes `kb check`, the indexes above them are fresh, and knowledge edits have a `log.md` entry. |

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
the current directory.
