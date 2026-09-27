# Use CI on GitHub

When you answer *Yes* to the GitHub Actions question, the knowledge base
contains `.github/workflows/kb.yml`. It has two jobs.

| Job | Runs on | What it does |
|---|---|---|
| `validate` | every push and pull request, and manual runs | Installs uv and just, runs `uv sync` and `just ci`: `kb check`, the independent OKF validator, the tooling tests, and `kb index --check` |
| `links` | every Monday at 06:00 UTC, and manual runs | Checks the external `http` and `https` URLs in `kb/**/*.md` with [lychee](https://lychee.cli.rs) and fails on dead links |

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

## Run the same checks locally

```sh
just ci             # what the validate job runs
just links-online   # what the links job runs; needs lychee installed
```

`just validate-okf` downloads a pinned copy of the independent validator
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
- `kb/.obsidian/` is excluded.

To run it now instead of waiting for Monday, open *Actions → kb → Run
workflow*. A manual run starts both jobs.

When a source URL is dead, the maintain skill adds an `archived` snapshot
URL to the Source page, or records the loss in the page. Ask the agent to
"fix the dead links from the last link check" and paste the job's output.

## If validate fails

Open the failed run and read the `just ci` step. The output lists each
diagnostic as `path:line: CODE message`; the
[check codes reference](../reference/check-codes.md) says how to fix each
one. Typical causes are a commit made with `--no-verify`, which skips the
pre-commit hook, and edits made on another machine without the hook
installed (`just setup` installs it).
