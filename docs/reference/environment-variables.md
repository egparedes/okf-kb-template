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
  launcher (`KB_DIR`) and `just` (`KB_QMD_COLLECTION`) need these variables
  in the shell environment.
- Format: `KEY=value` lines. `export KEY=value`, single or double quotes,
  `#` comment lines and inline ` # comments` after unquoted values are
  accepted.
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

### Launcher (v0.4.0)

| Variable | Meaning |
|---|---|
| `OKF_KB_LAUNCHER` | Set by the launcher for the command it runs, to stop it from calling itself again when a knowledge base has no `kb` of its own. Don't set it yourself. |
| `KB_DIR` | Knowledge base to use when `-C`/`--kb` is not given: a path or a registered name. Takes precedence over the current directory and the configured default. |
| `XDG_CONFIG_HOME` | Base directory of the configuration file: `$XDG_CONFIG_HOME/okf-kb/config.toml`, default `~/.config/okf-kb/config.toml`. |

### Search (v0.4.0)

| Variable | Meaning |
|---|---|
| `KB_QMD_COLLECTION` | Name of the qmd collection used by `just search`, `just search-setup` and `just search-reindex`. Default: the knowledge base's `kb_name`. Read by `just` from the environment it runs in. |

### File roots

| Variable | Meaning |
|---|---|
| `KB_ROOT_<ROOT>` | Local path of a file root declared in `schema/resources.yaml`. `<ROOT>` is the root name in upper case with dashes as underscores: root `course-notes` → `KB_ROOT_COURSE_NOTES`. |
| `KB_DENY` | Extra deny patterns, separated by `;`, for patterns that would themselves reveal sensitive names. Added to `deny` in `schema/resources.yaml`. |

### Zotero

| Variable | Default | Meaning |
|---|---|---|
| `ZOTERO_API_KEY` | none | Read-only web API key ("Allow library access" only). Enables the web API fallback, together with `zotero.user_id` or `group_id` in `schema/resources.yaml`, or `ZOTERO_USER_ID`. |
| `ZOTERO_DATA_DIR` | none | Zotero data directory, e.g. `~/Zotero`. Enables the offline fallback: a read-only snapshot of `zotero.sqlite` and the full-text cache. |
| `ZOTERO_USER_ID` | none | Numeric user id, used when `zotero.user_id` in `schema/resources.yaml` is empty. Prefer the file. |
| `ZOTERO_LOCAL_API` | `http://localhost:23119/api/users/0` | Address of Zotero's local API. |
| `ZOTERO_WEB_API` | `https://api.zotero.org` | Address of the Zotero web API. |

### KaraKeep

| Variable | Meaning |
|---|---|
| `KARAKEEP_URL` | Server address, e.g. `https://cloud.karakeep.app` or a self-hosted instance. A trailing `/api` or `/api/v1` is accepted. |
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
