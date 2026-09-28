# Run several knowledge bases on one machine

You can generate as many knowledge bases as you like, for example one for
work and one for a hobby. They do not interfere, because almost everything
is per repository.

## What each knowledge base has of its own

| Item | Where |
|---|---|
| Tooling version and Python environment | `.venv/`, created by uv on the first `uv run` |
| Secrets and machine paths | `.env` |
| Scratch space (fetched sources, drafts) | `.cache/` |
| git hooks | `.git/hooks/pre-commit` |
| Claude Code settings, hooks and `KB_ACTOR` | `.claude/settings.json` |
| Codex and Gemini CLI hooks, if added | `.codex/hooks.json`, `.gemini/settings.json` |
| The hooks' session state | `.cache/kb-hooks/` |
| Obsidian vault and its plugins | the knowledge-base folder and its `.obsidian/` |
| Search collection | a qmd collection named after the knowledge base |

## What they share

Zotero, KaraKeep and the folders behind file roots are services on your
machine. Every knowledge base uses them read-only (KaraKeep also gains
bookmarks when you archive a page), so several knowledge bases can point at
the same library or the same folder. Each one declares its own file roots
and deny patterns, and maps them in its own `.env`.

## Steps

1. Generate each knowledge base in its own directory, with its own
   `kb_name`. Keep the default knowledge-base folder, which is named after
   `kb_name`, or choose another name that is unique among your vaults:

    ```sh
    uvx copier copy --trust gh:egparedes/okf-kb-template ~/work-kb
    uvx copier copy --trust gh:egparedes/okf-kb-template ~/cooking-kb
    ```

2. Run `uv run poe setup` in each, and fill in each `.env` from its
   `.env.example`.

3. If you use qmd, run `uv run poe search-setup` in each. The collection is named
   after `kb_name` (`work-kb`, `cooking-kb`), so the indexes stay separate.
   See [Enable search](enable-search.md).

4. If you use Obsidian, run `uv run poe obsidian-setup` in each and open each
   knowledge-base folder (`~/work-kb/work-kb/`, `~/cooking-kb/cooking-kb/`)
   with *Open folder as vault*. Obsidian names a vault after its folder, and
   since v0.5.0 the folder is named after `kb_name` by default, so the
   vaults appear as `work-kb` and `cooking-kb` in the vault switcher.
   Knowledge bases created before v0.5.0 keep the folder `kb/`, so they all
   appear as `kb`; give each a distinct name with
   [`uv run poe rename-bundle`](rename-the-knowledge-base-folder.md).

5. Optional: install the [launcher](install-the-cli-launcher.md) and register
   the knowledge bases by name, so that `kb -C work report` works from
   anywhere.

Start your agent from the root of the knowledge base you want it to work
on. The agent reads that repository's `AGENTS.md` and skills, and the hooks
check that repository's bundle.

## Things to avoid

- Exporting `KB_REPO_ROOT` in your shell profile: it sends every `kb`
  call to one knowledge base.
- Using one qmd collection name for two knowledge bases: set
  `KB_QMD_COLLECTION` only when you need a name other than `kb_name`, and
  keep it unique.
- Pointing two knowledge bases' file roots at a broader folder than each
  needs. Map each root to exactly the folder its description names.
