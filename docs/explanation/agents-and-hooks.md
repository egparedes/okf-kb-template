# Agents and hooks

## How agents learn the conventions

The template targets command-line agents that work inside a repository:
Claude Code, Codex, Gemini CLI and similar. They all read instructions from
files in the repository, so the conventions live in files too.

| File | Read by | Contents |
|---|---|---|
| `AGENTS.md` | Codex and other agents that follow the AGENTS.md convention; Claude Code through `CLAUDE.md` | The map of the repository, the three workflows, the OKF hard rules, the page profile, links and relations, placement, and when a change is done. |
| `CLAUDE.md` | Claude Code | Imports `AGENTS.md` (`@AGENTS.md`) and adds Claude Code specifics: skills, `KB_ACTOR`, hooks. |
| `.agents/skills/*/SKILL.md` | Agents with skill support; Claude Code through the `.claude/skills` symlink | The step-by-step workflows: `kb-ingest`, `kb-query`, `kb-maintain`. |

Agents that read another file name by default, such as Gemini CLI, can be
configured to read `AGENTS.md`; see their documentation on context files.

`AGENTS.md` is short and stable: rules that apply to every edit. The skills
hold the procedures, and are loaded only when a workflow applies, which
keeps the agent's context small. Each skill ends with a definition of done
that can be checked (`just check` reports 0 errors, a log entry exists) and
with a report to you.

Both are template-managed. When the workflows improve upstream,
`copier update` brings the improvements to every knowledge base.

## Why instructions are not enough

Agents follow written rules most of the time, not all of the time. Over
hundreds of sessions, a rule followed 98% of the time still breaks the
bundle regularly: a wikilink slips in, an index goes stale, a footnote has
no source. OKF conformance is binary, so the template checks every change
mechanically, at three points:

| Where | When | What runs | Who it covers |
|---|---|---|---|
| Claude Code hooks | during the session | `kb check` on each edited file; a final check before the agent stops | Claude Code sessions |
| pre-commit | on `git commit` | `kb fix-links`, `kb index`, `kb check` | everyone who commits from a machine where `just setup` ran |
| CI | on push | `just ci`, including an independent OKF validator | everything that reaches GitHub |

Agents without hooks are covered by the pre-commit hook and CI. The earlier
a problem is caught, the cheaper it is to fix, which is why the hooks exist
even though CI would eventually catch the same errors.

## The Claude Code hooks

`.claude/settings.json` registers two hooks. Both call the knowledge base's
own `kb`, and both exit with status 2 when something must be fixed: Claude
Code then shows the hook's message to the agent, which fixes the problem and
continues.

**After each Write or Edit** (`kb hook post-edit`): if the file is a `.md`
file inside the knowledge-base folder, the hook records its path and runs `kb check` on that
file. Errors go straight back to the agent, while it still has the page in
mind. Warnings, such as wanted pages, do not block.

**When the agent is about to stop** (`kb hook stop`): the hook checks the
pages *this session* changed.

- Each of them must pass `kb check`.
- The `index.md` of each changed page's folder, and every index above it up
  to the root, must be current.
- If any changed page is a knowledge page (not in a personal area, not an
  index or the log), the bundle's `log.md` must have uncommitted changes, meaning the
  session logged its work.

If a check fails, the agent is sent back with the list of problems, fixes
them, and tries again. To avoid an endless loop, the hook does not block a
second time in a row (Claude Code marks that case with `stop_hook_active`).
The list of touched files is then kept, so the next session's stop check
still covers those pages, and the pre-commit hook still stands between them
and a commit.

## Which pages count as "this session's"

The stop hook deliberately does not check the whole bundle. You may be
editing a note in Obsidian while an agent works; a half-written note of
yours must not block the agent, and the agent must not "fix" it.

So the hooks keep a list of touched files in `.cache/kb-touched.txt`:

- the post-edit hook adds each file the agent writes or edits;
- `kb` commands that change pages (`new`, `mv`, `merge`, `fix-links`,
  `import`) add the files they change, but only when the environment
  variable `CLAUDECODE` is set. Claude Code sets it for the commands its
  agent runs; your own terminal does not, so your commands never add to the
  list.

When the stop checks pass, the list is deleted, and the next session starts
empty.

The log-entry rule uses the same list: it applies only when the session
changed knowledge pages. Pages in the personal areas (`projects/`,
`journal/` and `_templates/` by default) are yours, so editing them on your
behalf does not require a log entry.

## Other settings

- **`KB_ACTOR`** is set in `.claude/settings.json` from the `agent_actor`
  answer, so pages the agent creates are signed with the model's name.
  Update it there when you change models.
- **`Read(./.env)` is denied**, so the agent cannot read secrets with its
  file tool. The `kb` tool loads `.env` itself when it needs a key.
- **The agent never commits** unless you ask, and never marks its own work
  as verified. Both rules are in `AGENTS.md`.
