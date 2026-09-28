# Environment variables

## The `.env` file

Each knowledge base can have a `.env` file at its root for secrets and
machine-specific paths. It is gitignored; start from `.env.example`:

```sh
cp .env.example .env
```

- The `kb` tool loads it itself on each run, after finding the repository
  root. Variables already set in the real environment take precedence.
- Only `kb` reads `.env`. `KB_REPO_ROOT` has no effect there, and the
  launcher needs `KB_DIR` in the shell environment.
- Format: `KEY=value` lines. `export KEY=value`, single or double quotes,
  `#` comment lines and inline ` # comments` after unquoted values are
  accepted. Keys are letters, digits and underscores, not starting with a
  digit. Other lines, such as `=value` or `MY KEY=1`, are skipped with a
  warning that names the line number.
- Programs that `kb` starts (the desktop opener, markitdown, Obsidian) do
  not receive the variables it loaded from `.env`. Nor do they receive
  secrets from the real environment: `ZOTERO_API_KEY`, `KARAKEEP_API_KEY`,
  and every name ending in `_API_KEY`, `_TOKEN`, `_SECRET` or `_PASSWORD`.
  uv's own `UV_*` settings are kept, because `uvx` may need them for a
  private package index.
- `~` in paths is expanded where the value is a path.
- Agents are told never to read it, and with Claude Code the `Read` tool is
  denied `.env` in `.claude/settings.json`. A shell command could still
  print it, so keep only what this checkout needs.

## Variables

### Tooling

| Variable | Read by | Meaning |
|---|---|---|
| `KB_ACTOR` | `kb new`, `kb merge`, `kb zotero new-source` | Default actor for `generated.by` when `--by` is not given, e.g. `claude-code/claude-opus-5-5` or `human:alice`. Claude Code sets it from `.claude/settings.json` (the `agent_actor` answer); it can also be set in `.env`. |
| `KB_REPO_ROOT` | `kb` | Repository root to use instead of searching upwards from the current directory. The launcher sets it for each call. Never export it globally: it pins every `kb` call to one knowledge base. |
| `CLAUDECODE` | `kb` | Set to `1` by Claude Code for the commands its agent runs. When set, commands that change pages record them for the Stop hook. |

No variable names the knowledge-base folder. `kb` and CI read it from
`[tool.kb] bundle` in `pyproject.toml`, and the tasks that need it have it
written in (see
[Repository layout](repository-layout.md#the-knowledge-base-folder)); for a
single call, `kb --bundle PATH` overrides it.

### Launcher (v0.4.0)

| Variable | Meaning |
|---|---|
| `OKF_KB_LAUNCHER` | Set by the launcher for the command it runs, to stop it from calling itself again when a knowledge base has no `kb` of its own. Don't set it yourself. |
| `KB_DIR` | Knowledge base to use when `-C`/`--kb` is not given: a path or a registered name. Takes precedence over the current directory and the configured default. |
| `XDG_CONFIG_HOME` | Base directory of the configuration file: `$XDG_CONFIG_HOME/okf-kb/config.toml`, default `~/.config/okf-kb/config.toml`. |

### Search (v0.4.0)

| Variable | Meaning |
|---|---|
| `KB_QMD_COLLECTION` | Name of the qmd collection used by [`kb search`](cli.md#kb-search), and so by the `search`, `search-setup` and `search-reindex` tasks. Default: the knowledge base's `kb_name`. Since v0.6.0 it can also be set in `.env`. |

### File roots

| Variable | Meaning |
|---|---|
| `KB_ROOT_<ROOT>` | Local path of a file root declared in `schema/resources.yaml`. `<ROOT>` is the root name in upper case with dashes as underscores: root `course-notes` → `KB_ROOT_COURSE_NOTES`. |
| `KB_DENY` | Extra deny patterns, separated by `;`, for patterns that would themselves reveal sensitive names. Added to `deny` in `schema/resources.yaml`. |
| `KB_MARKITDOWN` | Package that `kb fetch` runs through `uvx` to convert non-text files when `markitdown` is not installed. Default `markitdown[all]==0.1.8`. Example: `KB_MARKITDOWN=markitdown[pdf,pptx]==0.1.8`. |

### Zotero

| Variable | Default | Meaning |
|---|---|---|
| `ZOTERO_API_KEY` | none | Read-only web API key ("Allow library access" only). Enables the web API fallback, together with `zotero.user_id` or `group_id` in `schema/resources.yaml`, or `ZOTERO_USER_ID`. |
| `ZOTERO_DATA_DIR` | none | Zotero data directory, e.g. `~/Zotero`. Enables the offline fallback: a read-only snapshot of `zotero.sqlite` and the full-text cache. |
| `ZOTERO_USER_ID` | none | Numeric user id, used when `zotero.user_id` in `schema/resources.yaml` is empty. Prefer the file. |
| `ZOTERO_LOCAL_API` | `http://localhost:23119/api` | Address of Zotero's local API. `kb` adds `/users/0`, or `/groups/<id>` when `zotero.group_id` is set; a trailing `/users/<n>` or `/groups/<n>` in the value is replaced. |
| `ZOTERO_WEB_API` | `https://api.zotero.org` | Address of the Zotero web API. |

Addresses must start with `http://` or `https://`. `kb` warns when an
address that receives an API key uses `http://` to another machine.

### KaraKeep

| Variable | Meaning |
|---|---|
| `KARAKEEP_URL` | Server address, e.g. `https://cloud.karakeep.app` or a self-hosted instance, with its `https://` (or `http://`). A trailing `/api` or `/api/v1` is accepted. |
| `KARAKEEP_API_KEY` | API key. |

## Example

```sh
# .env
ZOTERO_DATA_DIR=~/Zotero
ZOTERO_API_KEY=AbCdEf123456
KARAKEEP_URL=https://karakeep.example.org
KARAKEEP_API_KEY=ak1_…
KB_ROOT_TALKS=~/Documents/Talks
KB_DENY=talks/*/private-notes*
```
