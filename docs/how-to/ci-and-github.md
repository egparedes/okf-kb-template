# Use CI on GitHub

When you answer *Yes* to the GitHub Actions question, the knowledge base
contains `.github/workflows/kb.yml` and `.github/dependabot.yml`. The
workflow has two jobs.

| Job | Runs on | What it does |
|---|---|---|
| `validate` | every push and pull request, and manual runs | Installs uv, installs the tooling from `uv.lock` (`uv sync --locked`) and runs `uv run poe ci`: `kb check`, the independent OKF validator, lint and type checks of the tooling (ruff, mypy), the tooling tests, and `kb index --check` |
| `links` | every Monday at 06:00 UTC, and manual runs | Checks the external `http` and `https` URLs in the pages of the knowledge-base folder with [lychee](https://lychee.cli.rs) and fails on dead links |

Both jobs have read-only access to the repository.

## Enable it

1. Create an empty repository on GitHub (private or public).
2. Push the knowledge base:

    ```sh
    git remote add origin git@github.com:you/my-kb.git
    git push -u origin main
    ```

3. Open the repository's *Actions* tab. The `kb` workflow runs on the push.

Nothing else is needed: the workflow uses no secrets. On private
repositories, runs count against your GitHub Actions minutes.

## The lockfile

`uv.lock` pins the versions of the tooling's dependencies (PyYAML,
jsonschema, pytest, pre-commit, poethepoet, ruff, mypy). The first `uv run` writes it;
commit it with the knowledge base. The `validate` job installs exactly
these versions with `uv sync --locked`, and fails when `uv.lock` no longer
matches `pyproject.toml`, for example after a `copier update` that changed
the dependencies. Run `uv lock` (or any `uv run`) and commit the updated
`uv.lock`.

A knowledge base pushed before its first `uv run` has no `uv.lock`. The job
then resolves the dependencies with `uv sync` instead.

To move to newer dependency versions, run `uv lock --upgrade`, then
`uv run poe ci`, and commit `uv.lock`.

## Pinned actions and Dependabot

The workflow uses third-party actions (`actions/checkout`,
`astral-sh/setup-uv`, `lycheeverse/lychee-action`). Each is pinned to the
full commit SHA of a release, with the release in a comment:

```yaml
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
```

A tag such as `v7` can be moved to other code by whoever controls the
action's repository; a commit SHA cannot. `.github/dependabot.yml` asks
[Dependabot](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/keeping-your-actions-up-to-date-with-dependabot)
to check the pins weekly. It opens one pull request that moves all of them
to their latest releases, once a release is a week old. The `validate` job
runs on that pull request; merge it when it passes.

`copier update` also brings the pins of the template release you update
to; the template's own tests keep its `kb.yml` on the versions its
workflows use. When Dependabot and the update changed the same line,
Copier reports a conflict in `kb.yml`: keep the newer version.

Dependabot version updates need no setup on GitHub. To turn them off,
delete `.github/dependabot.yml`.

## Line endings

`.gitattributes` makes Git check out every text file with LF line endings,
on Windows too, where Git would otherwise convert them to CRLF. Pages,
indexes and the log then have the same bytes on every machine, and a
checkout on Windows does not show every file as changed. Windows scripts
(`.bat`, `.cmd`, `.ps1`) keep CRLF, which cmd.exe and PowerShell expect.

The file arrives with `copier update` in knowledge bases created before
v0.7.0. Most repositories need nothing more: Git for Windows normally
converts line endings on commit (`core.autocrlf=true`), so the repository
already holds LF. Only a repository that was committed from Windows with
`core.autocrlf=false` holds CRLF files; normalize it once:

```sh
git add --renormalize .
git commit -m "Normalize line endings"
```

## Run the same checks locally

```sh
uv run poe ci             # what the validate job runs
uv run poe links-online   # what the links job runs; needs lychee installed
```

`uv run poe validate-okf` downloads a pinned copy of the independent validator
([scaccogatto/okf-skills](https://github.com/scaccogatto/okf-skills)), so it
needs network access.

## The weekly link check

Sources rot: articles move, sites close. The `links` job reports external
URLs that no longer answer.

- Responses 200-299, 403 and 429 count as alive. Many sites refuse
  automated clients with 403 or rate-limit them with 429.
- Only `http` and `https` URLs are checked. Links between pages are
  checked by `kb check` instead, where a link to a missing page is allowed
  as a wanted page.
- The `.obsidian/` folder of the vault is excluded.
- The job reads the folder's name from `[tool.kb] bundle` in
  `pyproject.toml` (`kb` when it is missing), so it needs no change after
  [a rename](rename-the-knowledge-base-folder.md).

To run it now instead of waiting for Monday, open *Actions → kb → Run
workflow*. A manual run starts both jobs.

When a source URL is dead, the maintain skill adds an `archived` snapshot
URL to the Source page, or records the loss in the page. Ask the agent to
"fix the dead links from the last link check" and paste the job's output.

## If validate fails

Open the failed run and read the `uv run poe ci` step. The output lists each
diagnostic as `path:line: CODE message`; the
[check codes reference](../reference/check-codes.md) says how to fix each
one. Typical causes are a commit made with `--no-verify`, which skips the
pre-commit hook, and edits made on another machine without the hook
installed (`uv run poe setup` installs it).

When the `lint` part fails, the tooling in `tools/` has a lint, format or
type error. The tooling is managed by the template, so this happens after a
local edit to `tools/`: run `uv run ruff format tools` for formatting, and
fix what `uv run poe lint` reports otherwise. Put your own scripts outside
`tools/`, or keep them to the same rules.

When the *Install the tooling* step fails because the lockfile needs to be
updated, `pyproject.toml` changed without `uv.lock`. Run `uv lock`, commit
`uv.lock`, and push.
