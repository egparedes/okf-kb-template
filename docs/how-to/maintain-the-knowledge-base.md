# Maintain the knowledge base

As a knowledge base grows, pages go stale, duplicates appear and links go
missing. The simplest way to deal with it is to ask the agent to
*"lint the knowledge base"*: the `kb-maintain` skill runs the steps below
and asks you before merging pages. This guide shows the commands, so you
can run them yourself or check the agent's work.

All analytics commands are read-only. They print candidates; you or the
agent decide what to change.

## 1. Measure

```sh
uv run poe check     # errors and warnings
uv run poe health    # report, link graph, duplicate candidates, unlinked mentions
```

Keep the output: at the end you compare against it.

## 2. Fix check errors

Fix every error first. Also fix warnings that come from real problems:
typos in links (W030), unknown frontmatter keys (W010) and sources that are
never cited (W020). The [check codes reference](../reference/check-codes.md)
gives the fix for each code.

## 3. Work through the report

`uv run poe report` (the first part of `uv run poe health`) lists:

| Section | What to do |
|---|---|
| Trust tiers | Nothing to fix; shows how much is reviewed. |
| Stale pages (`stale_after` in the past) | Re-check the page against its sources, update the facts, refresh `generated`, and move `stale_after` forward. |
| Uncited knowledge pages | Find and ingest a source, or set `status: draft`. |
| Unused sources | Cite the Source page where its knowledge is used, or remove it. |
| Broken links (wanted pages) | Create the page when 2 or more pages link to it; otherwise leave the link. |
| Drafts | Complete them, or merge them into a related page. |

## 4. Review duplicate candidates

```sh
uv run kb dupes                 # names, acronyms, spelling, resources
uv run kb dupes --body          # also compares page text (slower)
uv run kb dupes --scope all     # include projects, journal and other personal areas
```

Each line is a pair with a score and the signals that fired:

```text
0.95  /ai/llm.md  <->  /ai/large-language-models.md  [acronym; same folder]
```

For each pair, read both pages. Then:

- **They are distinct:** relate them with `alternative_to` (with a prose
  link), or record the pair in `schema/distinct.yaml` so it is not reported
  again:

    ```yaml
    distinct:
      - [/ai/llm.md, /ai/llm-evaluation.md]
    ```

- **They are duplicates:** with a clean `git status -- kb`, merge the text
  into the better page by hand, then let `kb merge` do the bookkeeping:

    ```sh
    uv run kb merge ai/llm.md ai/large-language-models.md --dry-run
    uv run kb merge ai/llm.md ai/large-language-models.md
    ```

    `kb merge` removes the old page, rewrites every link to it and its
    entries in `tools/retrieval-eval/questions.yaml`, and regenerates the
    indexes. The merged page loses `verified`: it needs a
    new review.

## 5. Link unlinked mentions

```sh
uv run kb unlinked                          # every knowledge page
uv run kb unlinked ai/llm-wiki.md           # only these pages
uv run kb unlinked --all                    # include personal areas
```

Each result is a page and line where another page's title or alias appears
without a link. Link a mention where a reader would follow it, usually the
first occurrence, and skip incidental uses. For a name reported as
*ambiguous* (several pages share it), give the pages distinguishing titles
or aliases.

## 6. Read the link graph

```sh
uv run kb graph                 # knowledge pages only
uv run kb graph --scope all     # include personal areas
uv run kb graph --json          # for scripts
```

| Section | What to do |
|---|---|
| Most central (PageRank) | The pages most others depend on. |
| Review first | Central pages that are unverified or uncited: check them against their sources first. |
| Orphans | Link them from their parent topic or related pages, in prose, or merge them. |
| Dead ends | Add links to related pages. |
| Sink hubs (3+ inbound, no outbound) | Add outbound links. |
| Small islands | Connect them to the rest. |
| Weakly linked tags | Pages that share a tag but rarely link each other: cross-link them. |
| Co-link gaps | Two pages often linked together with no Synthesis or Comparison: write one. |

## 7. Restructure

- A folder with more than about 20 pages and a clear subtopic gets a
  subfolder. Register it in `schema/taxonomy.yaml`, then move pages with
  `uv run kb mv <old> <new>`, which rewrites every inbound link and the
  page's entries in `tools/retrieval-eval/questions.yaml`. `kb mv` also
  moves images and other files, with the links to them.
- Keep the tree at most 3 levels deep.

## 8. Close

```sh
uv run poe fix
uv run poe check
uv run kb log Lint "Merged the LLM pages into [Large language models](/ai/large-language-models.md); linked 12 mentions."
uv run poe report
```

Compare the report with the one from step 1, then commit.

See [Maintenance analytics](../explanation/maintenance-analytics.md) for
how the graph, duplicates and mentions are computed.
