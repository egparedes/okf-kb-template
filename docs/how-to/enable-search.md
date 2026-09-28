# Enable search

Agents find pages in three tiers, each switched on only when the one below
stops being enough:

1. **Navigate:** read the root `index.md` of the knowledge-base folder and
   the folder indexes, then run `rg` over the knowledge-base folder. Always
   available.
2. **Filter:** query frontmatter with `uv run poe find` (type, tag, status,
   folder, trust tier). Always available.
3. **Search:** hybrid search with [qmd](https://github.com/tobi/qmd), which
   combines keyword search, local embeddings and reranking. Optional.

`uv run poe search "<question>"` runs
[`kb search`](../reference/cli.md#kb-search). It uses qmd when the
knowledge base's collection exists, and otherwise falls back to a built-in
text search: it counts the case-insensitive matches of the question's words
of 3 characters or more in each page, skips the `index.md` files, and
prints the 20 best pages as `<folder>/path:count`. The fallback needs
nothing installed. The agent's query skill calls the same task, so enabling
qmd needs no change to the agent.

## Set up qmd

1. Install qmd following its README, and check that `qmd` is on your `PATH`.
2. From the repository root, create the collection, its contexts and the
   embeddings:

    ```sh
    uv run poe search-setup
    ```

    This runs `kb search --setup`, which adds a collection over the
    Markdown files of the knowledge-base folder (`<folder>/**/*.md`, where
    `<folder>` is `bundle` in the
    [`[tool.kb]` table](../reference/repository-layout.md#the-knowledge-base-folder)
    of `pyproject.toml`), one context per folder taken from
    `schema/taxonomy.yaml`, and computes the embeddings with local models.

3. Try it:

    ```sh
    uv run poe search "how do typed relations work"
    ```

4. After adding or changing pages, refresh the index
   (`kb search --reindex`, which runs `qmd update` and `qmd embed`):

    ```sh
    uv run poe search-reindex
    ```

The index lives outside the repository and can be rebuilt from the
knowledge-base folder at any time. The collection records the folder's
path: after you
[rename the knowledge-base folder](rename-the-knowledge-base-folder.md), run
`qmd collection remove <collection> && uv run poe search-setup`, where
`<collection>` is the [collection name](#the-collection-name).

## The collection name

Each knowledge base has its own collection, so several knowledge bases can
share one qmd installation. `kb search` computes the name:

- by default, the knowledge base's `kb_name` (read from `pyproject.toml`,
  whose project name is `<kb_name>-tools`), or `kb` if it cannot be read;
- or the value of the environment variable `KB_QMD_COLLECTION`, when it is
  set in the shell or in `.env`.

## Migrate from the `kb` collection (before v0.4.0)

Before v0.4.0 the collection was always called `kb`. After
[updating](update-from-the-template.md):

```sh
qmd collection remove kb   # the old collection covers the same folder, so remove it first
uv run poe search-setup    # recreates it under the new name, with folder contexts and embeddings
qmd collection list        # check that it is there
```

First check with `qmd collection list` that `kb` points at this knowledge
base's folder (always `kb/` before v0.5.0): if you ran several knowledge
bases before v0.4.0, it may belong to another one. `qmd collection rename kb <kb_name>` is faster than
removing it, because it keeps the embeddings and the folder contexts.

## Is qmd worth it?

Measure before you install anything. `tools/retrieval-eval/questions.yaml`
keeps real questions with the pages that should answer them, and
[`kb eval`](../reference/cli.md#kb-eval) reports which tiers reach those
pages.

1. Add questions with the pages a good answer uses. Two kinds are useful:
    - questions the knowledge base answers routinely: they show that the
      first tiers keep working;
    - questions that were hard to answer (the first searches missed the
      pages): they show whether qmd would help.

    ```yaml
    questions:
      - question: Why do DNS changes take hours to show up?
        expected: [/systems/dns.md, /systems/ttl.md]
      - question: Which Concept pages cover networking?
        expected: [/systems/dns.md]
        filters: {type: Concept, tag: networking}
    ```

    `filters` is optional; it runs the question through `kb find`.

2. Run the evaluation:

    ```sh
    uv run poe eval
    ```

    Each line shows, per tier, how many expected pages are in the top 10
    and the rank of the first one, e.g. `1/2 @3`. The last line gives the
    mean recall@10 of each tier.

3. Decide:
    - index+text reaches the pages of the hard questions too: the first two
      tiers are enough; improve the titles and descriptions of the pages
      that rank low instead of adding a tier.
    - index+text misses pages that are there under other words: install qmd
      as above, then run `uv run poe eval` again. The qmd column now runs
      `qmd query`; keep qmd if it reaches the pages the first tiers miss.

A CI gate such as `uv run poe eval --min-recall 0.8` (in CI or in
`tasks.toml`) exits 1 when index+text recall@10 drops below 0.8. Set the
threshold for the set you keep: hard questions lower the mean on purpose,
so gate on a representative set, or set the threshold just below today's
recall. Pass `--no-qmd` where qmd is not installed consistently.
