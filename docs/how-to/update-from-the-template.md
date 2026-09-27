# Update from the template

A knowledge base records the template version it was generated from in
`.copier-answers.yml` (`_commit`, for example `v0.3.0`). `copier update`
brings the changes of later releases into the files the template manages:
the tooling, the agent layer, the justfile, CI and the core schema. Files
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
    just setup     # uv sync, pre-commit install, indexes
    just ci        # kb check, independent OKF validator, tests, index freshness
    ```

5. Read the [changelog](../about/changelog.md) for steps specific to the
   release, then commit:

    ```sh
    git add -A
    git commit -m "Update from okf-kb-template v0.4.0"
    ```

If you want to change a managed file for good, change it in your own fork of
the template and update from the fork. Local edits to managed files survive
updates only as long as Copier can merge them.

## Updating to v0.4.0

- **Search:** the qmd collection is now named after the knowledge base
  instead of `kb`. Remove the old one, then set it up again:
  `qmd collection remove kb && just search-setup`. See
  [Enable search](enable-search.md).
- **Obsidian:** plugins are now installed by `just obsidian-setup`. Your
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
