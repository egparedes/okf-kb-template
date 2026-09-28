# Agents and hooks

## How agents learn the conventions

The template targets command-line agents that work inside a repository:
Claude Code, Codex, Gemini CLI and similar. They all read instructions from
files in the repository, so the conventions live in files too.

| File | Read by | Contents |
|---|---|---|
| `AGENTS.md` | Codex and other agents that follow the AGENTS.md convention; Claude Code through `CLAUDE.md`; Gemini CLI through `.gemini/settings.json` | The map of the repository, the three workflows, the OKF hard rules, the page profile, links and relations, placement, and when a change is done. |
| `CLAUDE.md` | Claude Code | Imports `AGENTS.md` (`@AGENTS.md`) and adds Claude Code specifics: skills, `KB_ACTOR`, hooks, `.env`. |
| `.agents/skills/*/SKILL.md` | Codex and Gemini CLI directly; Claude Code through the `.claude/skills` symlink | The step-by-step workflows: `kb-ingest`, `kb-query`, `kb-maintain`. |
| `.gemini/settings.json` | Gemini CLI (with the `gemini_cli` answer) | `context.fileName: ["AGENTS.md", "GEMINI.md"]`, so Gemini CLI reads `AGENTS.md` instead of looking only for `GEMINI.md`; and the hooks. |
| `.codex/hooks.json` | Codex (with the `codex` answer) | The hooks. Codex reads `AGENTS.md` without configuration. |

`AGENTS.md` is short and stable: rules that apply to every edit. The skills
hold the procedures, and are loaded only when a workflow applies, which
keeps the agent's context small. Each skill ends with a definition of done
that can be checked (`uv run poe check` reports 0 errors, a log entry exists) and
with a report to you.

All of them are template-managed. When the workflows improve upstream,
`copier update` brings the improvements to every knowledge base.

On Windows, git checks the `.claude/skills` symlink out as a small text file
unless symlinks are enabled. `uv run poe setup` replaces it with a symlink,
a directory junction or a copy; see
[`kb setup`](../reference/cli.md#claudeskills-on-windows).

## Why instructions are not enough

Agents follow written rules most of the time, not all of the time. Over
hundreds of sessions, a rule followed 98% of the time still breaks the
bundle regularly: a wikilink slips in, an index goes stale, a footnote has
no source. OKF conformance is binary, so the template checks every change
mechanically, at three points:

| Where | When | What runs | Who it covers |
|---|---|---|---|
| Agent hooks | during the session | `kb check` on each page the agent changes; a final check before the agent stops | Claude Code; Codex and Gemini CLI when their configuration is added |
| pre-commit | on `git commit` | `kb fix-links`, `kb index`, `kb check`, on what the commit contains (`kb --tracked`) | everyone who commits from a machine where `uv run poe setup` ran |
| CI | on push | `uv run poe ci`, including an independent OKF validator | everything that reaches GitHub |

Agents without hooks are covered by the pre-commit hook and CI. The earlier
a problem is caught, the cheaper it is to fix, which is why the hooks exist
even though CI would eventually catch the same errors.

## The hooks

`.claude/settings.json` registers the hooks below. All of them run
`python -m kbtools.hooks`, the hook part of the knowledge base's own `kb`
(the same as `kb hook`, without loading the rest of the tool), and all of
them report problems with exit status 2: Claude Code then shows the hook's
message to the agent, which fixes the problem and continues. The hook
before a Bash command is the exception: it never fails (it ends in
`|| true` and catches its own errors), because a failing `PreToolUse` hook
would block every command, including the `uv sync` that could repair it.

**After each Write, Edit or MultiEdit** (`post-edit`): if the file is a `.md`
file inside the knowledge-base folder, the hook records its path and runs `kb check` on that
file. Errors go straight back to the agent, while it still has the page in
mind. Warnings, such as wanted pages, do not block.

**Before and after each Bash command** (`pre-tool`, `post-tool`): an agent
can change pages without a file tool, with `sed -i`, `cat >`, `git mv`, `rm`
or a script. Before the command, the hook lists the knowledge base's `.md`
files with their modification time, size and a hash of their content;
after it, it lists them again. Pages whose content was created, changed or
deleted are recorded as touched, and those that exist are checked like an
edit. A page rewritten with the same text, or changed and changed back, does
not count. The after-hook runs for failed commands too
(`PostToolUseFailure`), since `sed -i … && false` still changed the page.

The listing skips dot-folders such as `.obsidian/` and `.trash/`, and no
hook checks or records a gitignored file: like every `kb` command, the
hooks treat only the files git would commit as pages. The
hashes are cached in `.cache/kb-hooks/hashes.json` by path, modification
time and size, so a listing reads only the files changed since the last
one: with thousands of pages, it takes a few tens of milliseconds, and the
first listing of a session somewhat more.

**When the agent is about to stop** (`stop`): the hook checks the
pages *this session* changed.

- Each of them must pass `kb check`.
- The `index.md` of each changed page's folder, and every index above it up
  to the root, must be current.
- If any changed page is a knowledge page (not in a personal area, not an
  index or the log), the bundle's `log.md` must differ from what it was
  when the session started, meaning the session logged its work.

If a check fails, the agent is sent back with the list of problems, fixes
them, and tries again. To avoid an endless loop, the hook does not block a
second time in a row (Claude Code marks that case with `stop_hook_active`).
The session's list is then kept, so a resumed session is checked again, and
the pre-commit hook still stands between those pages and a commit. Other
sessions do not see it.

### Codex and Gemini CLI

With the `codex` and `gemini_cli` answers, `.codex/hooks.json` and
`.gemini/settings.json` register the same checks. Both CLIs send a JSON
payload with a `session_id`, like Claude Code, so the same code serves all
three; `--agent` adapts the output.

| Check | Claude Code | Codex | Gemini CLI |
|---|---|---|---|
| file tools | `post-edit` after `Write`, `Edit`, `MultiEdit` | `pre-tool`/`post-tool` around `apply_patch` (its payload holds the patch, not a path) | `post-edit` after `write_file`, `replace` |
| shell commands | `pre-tool`/`post-tool` around `Bash` (`PostToolUse` and `PostToolUseFailure`) | around `Bash` | around `run_shell_command` |
| before stopping | `Stop` | `Stop` | `AfterAgent` |

Gemini CLI runs the hooks in the project directory, so its commands have no
`cd`, and they work in PowerShell on Windows. As with the pre-tool hook
everywhere, the Gemini hooks around tools end in `; exit 0` and the Codex
post-tool hook in `|| true`: their problems come back as JSON with exit 0,
so a failing `uv` must not turn into a blocked tool. The Python side of
these hooks exits 0 whatever goes wrong in it. Codex does not document the
shell it runs hooks with on Windows, so there it runs each hook's
`commandWindows`, the same command without `|| true`. The one gap left: if
`uv` itself cannot start on Windows, it exits 2 and Codex blocks the
command until `uv sync` repairs the environment. The stop hooks keep
exit 2, which is how they send the agent back. Its payload has no tool-call
id, so commands that overlap share one "before" listing: the one taken
before the first of them is kept until a later hook uses it.

On Windows, Gemini CLI runs hooks with `powershell -Command` (PowerShell 7
when installed). PowerShell alone reports any failed program as exit 1, but
Gemini CLI appends `; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }` to
every hook command (`packages/core/src/hooks/hookRunner.ts`). The stop hook's
exit 2 therefore reaches Gemini CLI unchanged, and the stop command needs no
suffix of its own.

Both CLIs ask you to review project hooks before they run: in Codex, trust
the project and approve the hooks with `/hooks`; in Gemini CLI, trust the
folder and accept the hooks when it warns about them. Until then, the
pre-commit hook and CI are the safety net.

## Which pages count as "this session's"

The stop hook deliberately does not check the whole bundle. You may be
editing a note in Obsidian while an agent works; a half-written note of
yours must not block the agent, and the agent must not "fix" it.

So the hooks keep the session's state in `.cache/kb-hooks/<session id>/`,
keyed by the `session_id` of the hook payload:

- the post-edit hook adds each file the agent writes or edits;
- the post-tool hook adds each page a shell command created, changed or
  deleted;
- `kb` commands that change pages (`new`, `mv`, `merge`, `fix-links`,
  `import`) add the files they change to `.cache/kb-touched.txt`, but only
  when the environment variable `CLAUDECODE` is set. Claude Code sets it
  for the commands its agent runs; your own terminal does not, so your
  commands never add to the list. The next hook of the session moves these
  entries into the session's state.

Paths are stored relative to the knowledge-base folder, and paths that no
longer lie inside it (for example after the repository moved) are dropped.

When the stop checks pass, the session's state is deleted, and the next
session starts empty. State of sessions that never stopped cleanly is
removed at the next clean stop of any session once it is 7 days old.

The log-entry rule uses the same list: it applies only when the session
changed knowledge pages. Pages in the personal areas (`projects/`,
`journal/` and `_templates/` by default) are yours, so editing them on your
behalf does not require a log entry.

The log check compares `log.md` with the digest the hooks took at the
session's first event, before its first change. It does not ask git, so it
works in a repository nested in another one, without git, and after the
agent commits in the middle of a session. An uncommitted log entry you
wrote before the session does not count as the agent's.

## What the hooks do not cover

The hooks are a guardrail against mistakes, not a security boundary.

- **Changes outside the tool calls.** A background process started by a
  command, a change made while no command runs, and a tool other than
  those in the table above (an MCP server that writes files, for example)
  are not recorded.
- **Everything a command changes counts as the agent's.** A page you edit
  in Obsidian while an agent's command runs, and pages that a `git checkout`,
  `git stash` or `git pull` run by the agent rewrites with other content,
  are recorded as touched, and may then need a log entry. With Gemini CLI,
  overlapping commands can also pick up each other's changes.
- **Files outside the knowledge-base folder.** Only its `.md` files are
  listed; a command that edits `schema/` is caught by the pre-commit hook
  and CI.
- **Other agents' hooks.** Agents without hook support, or with hooks you
  have not approved, rely on the pre-commit hook and CI.

## Other settings

- **`KB_ACTOR`** is set in `.claude/settings.json` from the `agent_actor`
  answer, so pages the agent creates are signed with the model's name.
  Update it there when you change models. Codex and Gemini CLI pass
  `--by <tool>/<model>` instead, as `AGENTS.md` shows.
- **`.env` is denied** to the file tools (`Read(.env)`, `Read(.env.*)`,
  except `.env.example`) and to shell commands that name it
  (`Bash(* .env)`, `Bash(* .env *)` and the same with `./.env`), so the
  agent cannot read secrets with `cat .env` or `source .env`. The same rules
  stop the agent from creating or editing `.env`, for example with
  `cp .env.example .env`: that is yours to do. The `kb` tool
  loads `.env` itself when it needs a key. A command that reaches the file
  another way, such as `python -c "open('.env')"` or a path built in a
  variable, is not matched: Claude Code's permission rules match the text
  of a command. Use Claude Code's sandbox for a hard boundary.
- **The agent never commits** unless you ask, and never marks its own work
  as verified. Both rules are in `AGENTS.md`.
