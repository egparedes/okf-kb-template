# Rename the knowledge-base folder

The knowledge-base folder is the folder of the repository that holds the
pages: the OKF bundle and, with Obsidian, the vault. It is named after
`kb_name` by default, and is `kb/` in knowledge bases created before v0.5.0.
`just rename-bundle NEW` gives it another name. This guide renames `kb/` to
`my-notes/`; use your own names.

## When to rename

- **The vault name.** Obsidian names a vault after its folder, so a
  knowledge base created before v0.5.0 appears as "kb" in the vault
  switcher. After a rename it appears under the new name.
- **Several knowledge bases.** When every folder is called `kb/`, vaults,
  editor tabs and paths in the agent's output look the same in every
  knowledge base. Distinct names tell them apart; see
  [Run several knowledge bases](multiple-knowledge-bases.md).

A rename changes no page. Links such as `/ai/llm-wiki.md` are relative to
the bundle root, whatever the folder is called, and the bundle stays
conformant. The `kb` command, the `kb_name` answer and the qmd collection
name keep their names. The repository directory itself is not renamed.

## Before you start

- The knowledge base is at template v0.5.0 or later (`_commit` in
  `.copier-answers.yml`, which must not be empty). If it is older,
  [update it](update-from-the-template.md) and commit the update first.
- Changes to tracked files outside the knowledge-base folder, and in its
  `_templates/`, are committed or stashed: the recipe re-renders those files.
  Changes to pages and vault settings, and untracked files such as notes you
  have not committed yet, are fine: they move with the folder.
- Obsidian is closed, so that it does not write into the folder while it
  moves.
- The template repository is reachable. The recipe fetches the template at
  the version recorded in `.copier-answers.yml`, as `copier update` does; for
  a private fork, see
  [When the template repository is private](update-from-the-template.md#when-the-template-repository-is-private).
- The new name is lowercase kebab-case, is not an existing file or folder,
  and is not `schema`, `tools`, `docs`, `imports`, `template`, `launcher` or
  `site` (folders of the repository), nor `sources`, `syntheses`,
  `entities`, `projects` or `journal` (standard folders inside the
  knowledge base). It must not be the name of a folder inside the knowledge-base
  folder, or of a domain in the `domains` answer: a domain `notes/` inside a
  knowledge-base folder `notes/` would make paths ambiguous. Choose, for
  example, `notes-kb` instead.

## Rename the folder

From the repository root:

```sh
just rename-bundle my-notes
```

If a check fails, the recipe says why and changes nothing; for uncommitted
changes, it lists the files to commit or stash.

Copier lists the files it renders, and the recipe ends with a summary:

```text
…
Renamed kb/ to my-notes/ and staged the move and the re-rendered template files.
WARNING: these template-managed files had local edits that the re-render reverted (see git diff --cached):
  .claude/settings.json
Next: review git diff --cached, then commit. Your unstaged edits and untracked notes are untouched;
the pre-commit hook checks the whole working tree, including them.
By hand: mentions of kb/ in README.md and in schema/*.yaml comments (not re-rendered).
Obsidian: open my-notes/ with Open folder as vault. qmd: qmd collection remove my-kb && just search-setup
```

The `WARNING` lines appear only when there is something to restore (see
below).

The recipe:

1. checks the name, the recorded template version and the working tree,
   and stops without changing anything if a check fails;
2. moves the folder to `my-notes/` with `git mv`, which stages the renames
   and keeps the pages' history. Untracked notes, `.obsidian/` settings and
   the installed Obsidian plugins move along; untracked files stay
   untracked, and pages you had modified stay unstaged;
3. re-renders the template-managed files with the new name, by running
   `uvx copier recopy --trust --defaults --overwrite --skip-tasks
   --vcs-ref=<_commit> --data bundle_dir=my-notes`. This rewrites
   `[tool.kb] bundle` in `pyproject.toml`, `.gitignore`,
   `.pre-commit-config.yaml`, `AGENTS.md`, `CLAUDE.md`, the skills and
   `docs/obsidian-setup.md`, and records the new answer in
   `.copier-answers.yml`. It uses the template version you already have,
   so nothing else is upgraded. Copier validates the name as it does on
   `copier copy`. Files the knowledge base owns, such as `README.md`, are
   left alone;
4. warns about managed files whose change is more than the folder name:
   committed local edits that the re-render reverted;
5. stages the re-rendered files (`git add -u` on tracked files outside the
   folder and in `my-notes/_templates/`). It never stages untracked files;
6. updates the folder name in `.cache/kb-touched.txt`, so that the Claude
   Code Stop hook of a running agent session still finds the pages it
   changed;
7. runs `uv sync` and `kb index`, and prints the summary.

It does not commit.

If the recopy fails, for example because the template repository cannot be
reached or Copier rejects the name, the recipe moves the folder back,
restores the managed files and `kb/_templates/` to the last commit, says
that everything was put back as it was, and exits with an error.

## Review and commit

1. Review what the recipe staged:

    ```sh
    git diff --cached --stat
    git diff --cached
    just check
    ```

    The pages show as renamed, and the managed files as modified.

2. If the recipe printed a `WARNING`, the listed files had committed local
   edits, such as a hand-edited `KB_ACTOR` in `.claude/settings.json`,
   that the re-render replaced with the template's version. The removed
   lines are in `git diff --cached`: put back the ones you want to keep,
   keeping the new folder name, and `git add` the file.

3. Update the old name in the files the knowledge base owns. Copier does not
   re-render them:

    ```sh
    rg -nF 'kb/' README.md schema/
    ```

    `git add` the files you change.

4. Commit what is staged:

    ```sh
    git commit -m "Rename the knowledge-base folder to my-notes"
    ```

    Your unstaged edits and untracked notes are not part of this commit.
    The pre-commit hook, however, checks the whole knowledge-base folder in
    the working tree, not only the staged files: an untracked page without
    valid frontmatter blocks the commit until you fix it.

## Afterwards

- **Obsidian.** Choose *Open folder as vault* and select `my-notes/`. To
  Obsidian this is a new vault; its settings and plugins moved with the
  folder. If Obsidian asks again whether you trust the author, or the
  Templater trigger is off, repeat the two manual steps of
  [Set up Obsidian](set-up-obsidian.md#do-the-two-manual-steps). Remove the
  old vault from Obsidian's vault list. From then on,
  `just obsidian-setup --open` opens the vault.
- **qmd.** The collection keeps its name but still points at the old
  folder. Recreate it:

    ```sh
    qmd collection remove "$(just --evaluate qmd_collection)" && just search-setup
    ```

- **Launcher and scripts.** The [launcher](install-the-cli-launcher.md)
  registers repository roots, so its configuration keeps working. Update
  anything that uses a path inside the old folder: a `KB_DIR` or launcher
  entry that points into it, shell aliases, editor workspaces, scripts.
- **CI.** Nothing to change: the workflow reads the folder name from
  `pyproject.toml`.
- **Other clones.** After `git pull` on another machine, git moves the
  tracked files, but the files git ignores or does not track stay in the old
  folder there: the Obsidian plugins, per-device settings and uncommitted
  notes. Move the notes you want to keep, delete the old folder, run
  `just setup` and `just obsidian-setup`, and open the new folder as a vault.

## Rename it back

After the commit, rename it again the same way, for example
`just rename-bundle kb`.

To undo a rename you have not committed, move the folder back, restore the
re-rendered files, and refresh the environment and the indexes:

```sh
git mv my-notes kb        # or mv, if the folder had no tracked files
git restore --source=HEAD --staged --worktree -- . ':(exclude)kb'   # files outside the folder
git restore --source=HEAD --staged --worktree -- kb/_templates       # the Templater templates
uv sync
just index
```

## Why not rename it by hand

A plain `mv` or `git mv` moves the pages, but `pyproject.toml`,
`.gitignore`, the pre-commit hooks and the agent instructions keep the old
name, so `kb` and the hooks no longer find the bundle. Those files are
managed by the template, and the next `copier update` would render them
again from the name recorded in `.copier-answers.yml`. `just rename-bundle`
changes the folder, the managed files and the recorded answer together.
