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

## Updating to v0.7.0

v0.7.0 changes the tooling throughout, adds hooks for Codex and Gemini CLI,
and lints the tooling in CI. The update itself is the usual one; expect a
few conflicts if you edited files under `tools/`.

- **Two new questions.** Copier asks
  [`codex` and `gemini_cli`](../reference/copier-questions.md), with the
  default *No*. Answer *Yes* for an agent you use: the update then adds
  `.codex/hooks.json` or `.gemini/settings.json`. Both CLIs ask you to
  trust the project's hooks the first time; see
  [Codex and Gemini CLI](../explanation/agents-and-hooks.md#codex-and-gemini-cli).
- **Commit the lockfile.** The tooling has new development dependencies
  (ruff, mypy and their type stubs), and CI now installs with
  `uv sync --locked`, which fails when `uv.lock` does not match
  `pyproject.toml`. After the update, run `uv lock` (or step 4's
  `uv run poe setup`, which writes it too), and commit `uv.lock` with the
  update. See [The lockfile](ci-and-github.md#the-lockfile).
- **`uv run poe ci` lints the tooling.** The new `lint` task runs
  `ruff check` and `ruff format --check` over `tools/` and `mypy` over
  `tools/kbtools/`, and `ci` runs it. Code you added under `tools/` must
  pass too: run `uv run ruff check --fix tools`, then
  `uv run ruff format tools`, and fix what `uv run poe lint` still reports,
  or move your scripts out of `tools/`.
- **Conflicts in `tools/`.** About 30 files of the tooling were reformatted
  with ruff, besides the changes of this release. If you edited
  `tools/kbtools/` or `tools/tests/`, Copier is likely to report conflicts
  there (step 3). Prefer the template's version, then apply your change
  again.
- **`.claude/settings.json` is rewritten.** It registers new hooks around
  Bash commands, runs them as `python -m kbtools.hooks`, and denies shell
  commands that name `.env` and reads of `.env.*` (except `.env.example`).
  If you changed the file, for example `KB_ACTOR`, check that your change
  survived the merge, and apply it again if not. The agent can no longer
  create `.env` for you with `cp .env.example .env`: run that yourself.
  Old hook commands (`kb hook post-edit`, `kb hook stop`) keep working.
- **New files.** `.gitattributes` keeps LF line endings on every platform.
  A repository committed from Windows with `core.autocrlf=false` holds CRLF
  files; normalize it once, as in
  [Line endings](ci-and-github.md#line-endings). Otherwise there is nothing
  to do. With `github_ci`, `.github/dependabot.yml` proposes updates of the
  pinned actions weekly
  ([Pinned actions and Dependabot](ci-and-github.md#pinned-actions-and-dependabot)).
- **Import mappings are checked more strictly.** A mapping with an unknown
  nested key, an invalid regular expression or an invalid actor now stops
  `kb import` with a message that names the key. `exclude` ignores case:
  `private/**` now also excludes `Private/`. See the
  [mapping reference](../reference/import-mapping.md).
- **Zotero settings.** `ZOTERO_LOCAL_API` is now the root of the local API,
  `http://localhost:23119/api`; `kb` adds `/users/0` or `/groups/<id>`
  itself. An old value that ends in `/users/0` still works. In
  `schema/resources.yaml`, `zotero.user_id` and `zotero.group_id` must be
  numbers; `kb check` reports anything else (H061).
- **`kb mv`.** A new name with another extension is refused:
  `kb mv a.md b.txt` used to create `b.txt.md`. A destination that is an
  existing folder moves the page into it (`kb mv a.md ai` gives
  `ai/a.md`, where it used to give `ai.md`). See
  [`kb mv`](../reference/cli.md#kb-mv).
- **What counts as the knowledge base.** Every `kb` command reads the files
  git would commit, and never files below a dot-folder. The pre-commit hooks
  run `kb --tracked`, which reads only what the commit contains. As a
  result:
    - `kb report` totals may drop: Templates and pages in `.trash/` or
      `_` folders are no longer counted;
    - a link into a dot-folder or to a gitignored file is now a broken
      link (W030), and links must match the case of the file name.
- **`tools/retrieval-eval/questions.yaml`** belongs to the knowledge base,
  so the update keeps your file and its old header. `kb eval` reads it; the
  format is the same, with optional `filters`. The template's new header
  explains the format; copy it from the
  [`kb eval` reference](../reference/cli.md#kb-eval) or from a freshly
  generated knowledge base if you want it. `kb mv` and `kb merge` now
  update the entries of the pages they move or merge.
- **`kb open` refuses programs.** It opens web URLs, Zotero items and files
  under a declared root, but no longer programs, shortcuts or executable
  files. See [`kb open`](../reference/cli.md#kb-open).

After the update, run `uv run poe setup` and `uv run poe ci`
(step 4 above), then commit, including `uv.lock`.

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
