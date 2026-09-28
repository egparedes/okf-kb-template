# Update from the template

A knowledge base records the template version it was generated from in
`.copier-answers.yml` (`_commit`, for example `v0.3.0`). `copier update`
brings the changes of later releases into the files the template manages:
the tooling and its tasks, the agent layer, CI and the core schema. Files
the knowledge base owns, such as `schema/vocabulary.yaml` and every page,
are never touched. The [repository layout](../reference/repository-layout.md)
lists which is which.

## Steps

1. Start from a clean working tree. Copier refuses to update a repository
   with uncommitted changes.

    ```sh
    git status --short     # must print nothing
    ```

2. Run the update from the repository root:

    ```sh
    uvx copier update --trust
    ```

    Copier asks the questions again, with your recorded answers as defaults.
    Add `--skip-answered` to keep every recorded answer without being asked. To move to a
    specific release instead of the latest tag, add `--vcs-ref v0.4.0`.

    `--trust` is needed because the template runs `kb index` after the
    update.

3. Resolve conflicts. Where both you and the template changed the same
   lines of a managed file, Copier writes git-style conflict markers into
   the file:

    ```sh
    git diff
    rg -n '^(<<<<<<<|>>>>>>>)' .
    ```

    Edit each file to keep the right lines, and remove the markers. The
    pre-commit hook `check-merge-conflict` refuses a commit that still has
    them. If you prefer the rejected hunks in separate `.rej` files, run the
    update with `--conflict rej`.

4. Refresh the environment and check everything:

    ```sh
    uv run poe setup     # uv syncs the tooling; pre-commit hook, indexes
    uv run poe ci        # kb check, independent OKF validator, lint, tests, index freshness
    ```

    Updating to a release before v0.6.0, run `just setup` and `just ci`
    instead.

5. Read the [changelog](../about/changelog.md) for steps specific to the
   release, then commit:

    ```sh
    git add -A
    git commit -m "Update from okf-kb-template v0.4.0"
    ```

If you want to change a managed file for good, change it in your own fork of
the template and update from the fork. Local edits to managed files survive
updates only as long as Copier can merge them.

## Updating to v0.6.0

v0.6.0 replaces the `justfile` with [poethepoet tasks](../reference/tasks.md)
in `pyproject.toml`. The tasks keep the names of the recipes.

- **The justfile goes away.** `copier update` deletes `justfile`, even if
  you edited it, without asking. If you had your own recipes, recover them
  from git before you commit the update, with `git show HEAD:justfile`, and
  move them into `tasks.toml` (see *Custom recipes* below).
- **`tasks.toml` appears** at the repository root. It holds this knowledge
  base's own tasks, and `copier update` never overwrites it.
- **Run tasks with `uv run poe`.** Replace `just X` with `uv run poe X` in
  your habits, shell aliases and scripts: `uv run poe setup`,
  `uv run poe check path.md`, `uv run poe find --type Tool`. `uv run poe`
  alone lists the tasks. just is no longer needed; poethepoet is installed
  into `.venv` by `uv run`. Optionally, `uv tool install poethepoet` once
  lets you type `poe X` in any knowledge base.
- **README.md** belongs to the knowledge base, so the update leaves it
  alone: replace the `just …` commands in it by hand.
- **Custom recipes** that you added to the old `justfile` go into
  `tasks.toml`, as poe tasks
  ([example](../reference/tasks.md#local-tasks-taskstoml)). Never add them
  to `pyproject.toml`: the template manages it. A recipe longer than a line
  or two becomes a `sequence` of commands, or a script that the task runs.
- **The just variables are gone.** The folder name is written into the
  tasks that need it, and `kb search` computes the qmd collection name,
  still `$KB_QMD_COLLECTION` or `kb_name`. So
  `just qmd_collection=other search …` becomes
  `KB_QMD_COLLECTION=other uv run poe search …`.
- **New `kb` commands** do the work of the longer recipes:
  [`kb setup`](../reference/cli.md#kb-setup),
  [`kb search`](../reference/cli.md#kb-search) (with `--setup` and
  `--reindex`) and
  [`kb rename-bundle`](../reference/cli.md#kb-rename-bundle). The search
  fallback no longer needs ripgrep.
- **CI** runs `uv run poe ci`; the step that installed just is gone. Nothing
  to do if you did not edit the workflow.

After the update, run `uv run poe setup` and `uv run poe ci`
(step 4 above), then commit.

## Updating to v0.5.0

- **Knowledge-base folder:** Copier asks the new question `bundle_dir`, the
  name of the knowledge-base folder, with the default `kb`. Accept it: your
  knowledge base keeps its `kb/` folder, and `pyproject.toml` records the
  name in `[tool.kb] bundle = "kb"`. Answering another name here does not
  move your pages.
- **Optional rename:** to give the folder, and so the Obsidian vault,
  another name, commit the update first, then run
  `uv run poe rename-bundle <name>`. See
  [Rename the knowledge-base folder](rename-the-knowledge-base-folder.md).

## Updating to v0.4.0

- **Search:** the qmd collection is now named after the knowledge base
  instead of `kb`. Remove the old one, then set it up again:
  `qmd collection remove kb && uv run poe search-setup`. See
  [Enable search](enable-search.md).
- **Obsidian:** plugins are now installed by `uv run poe obsidian-setup`. Your
  `kb/.obsidian/community-plugins.json` belongs to the knowledge base, so it
  keeps its previous list. The command installs every listed plugin that has
  a pin; remove the IDs you don't want from the list first. See
  [Set up Obsidian](set-up-obsidian.md).

## When the template repository is private

`copier update` fetches the template from `_src_path` in
`.copier-answers.yml`. For a private repository, such as your own fork, git
needs credentials for it. Either:

- let the GitHub CLI act as git's credential helper:

    ```sh
    gh auth setup-git
    ```

- or make git use SSH for GitHub URLs:

    ```sh
    git config --global url."git@github.com:".insteadOf "https://github.com/"
    ```

You can also generate the knowledge base from the SSH address in the first
place (`uvx copier copy --trust git@github.com:you/okf-kb-template.git my-kb`);
`_src_path` then records it.

Updates need release tags in the template repository: `_commit` names a tag,
and Copier compares it with the new one. If you maintain a fork, push tags
with your commits (`git push origin main --tags`).
