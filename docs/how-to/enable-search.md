# Enable search

Agents find pages in three tiers, each switched on only when the one below
stops being enough:

1. **Navigate:** read the root `index.md` of the knowledge-base folder and
   the folder indexes, then run `rg` over the knowledge-base folder. Always
   available.
2. **Filter:** query frontmatter with `just find` (type, tag, status,
   folder, trust tier). Always available.
3. **Search:** hybrid search with [qmd](https://github.com/tobi/qmd), which
   combines keyword search, local embeddings and reranking. Optional.

`just search "<question>"` uses qmd when the knowledge base's collection
exists, and otherwise falls back to ripgrep over the words of the question.
The agent's query skill calls it, so enabling qmd needs no change to the
agent.

## Set up qmd

1. Install qmd following its README, and check that `qmd` is on your `PATH`.
2. From the repository root, create the collection, its contexts and the
   embeddings:

    ```sh
    just search-setup
    ```

    This adds a collection over the Markdown files of the knowledge-base
    folder (`<folder>/**/*.md`, where `<folder>` is the
    [`bundle` variable](../reference/just-recipes.md#variables)), one context per folder taken
    from `schema/taxonomy.yaml`, and computes the embeddings with local
    models.

3. Try it:

    ```sh
    just search "how do typed relations work"
    ```

4. After adding or changing pages, refresh the index:

    ```sh
    just search-reindex
    ```

The index lives outside the repository and can be rebuilt from the
knowledge-base folder at any time. The collection records the folder's
path: after you
[rename the knowledge-base folder](rename-the-knowledge-base-folder.md), run
`qmd collection remove <collection> && just search-setup`, where
`<collection>` is the [collection name](#the-collection-name).

## The collection name

Each knowledge base has its own collection, so several knowledge bases can
share one qmd installation. The name is the just variable `qmd_collection`:

- by default, the knowledge base's `kb_name` (read from `pyproject.toml`,
  whose project name is `<kb_name>-tools`);
- or the value of the environment variable `KB_QMD_COLLECTION`, when it
  is set in the shell that runs `just`.

## Migrate from the `kb` collection (before v0.4.0)

Before v0.4.0 the collection was always called `kb`. After
[updating](update-from-the-template.md):

```sh
qmd collection remove kb          # the old collection covers the same folder, so remove it first
just search-setup                 # recreates it under the new name, with folder contexts and embeddings
qmd collection list               # check that it is there
```

First check with `qmd collection list` that `kb` points at this knowledge
base's folder (always `kb/` before v0.5.0): if you ran several knowledge
bases before v0.4.0, it may belong to another one. `qmd collection rename kb <kb_name>` is faster than
removing it, because it keeps the embeddings and the folder contexts.

## Is qmd worth it?

`tools/retrieval-eval/questions.yaml` is a place to keep questions with the
pages that should answer them. Use it to judge by hand whether the first two
tiers miss answers before you enable a heavier tier. No tool reads it yet.
