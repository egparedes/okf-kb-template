# Links and relations

## One link syntax: bundle-absolute markdown links

Pages link to each other with standard markdown links whose target is a
path from the bundle root:

```markdown
See the [CAP theorem](/systems/distributed/cap-theorem.md).
```

This one form has to work for three readers.

- **OKF consumers.** OKF uses standard markdown links and recommends
  bundle-root paths. `[[wikilinks]]` are not part of the specification; an
  OKF reader sees them as plain text.
- **Obsidian.** With the knowledge-base folder as the vault root, Obsidian
  resolves `/…` against the same folder. See [the vault is the bundle](design-overview.md#the-vault-is-the-bundle).
- **The `kb` tool and agents.** An absolute path is the same string on every
  page that links to the target, so `rg "/systems/distributed/cap-theorem.md"`
  finds every inbound link, and `kb mv` can rewrite them all.

Relative links (`../cap-theorem.md`) were rejected because they break when
the *linking* page moves, and the same target is written differently from
each folder. Wikilinks with a typed-link plugin were rejected because they
are not OKF links.

## Keeping links in that form

Obsidian cannot write the leading `/` by itself. Its closest setting,
"Path from vault folder", writes `systems/dns.md`, which OKF reads as
relative to the linking file. And when you rename a note, Obsidian rewrites
links in its own format. Three things close the gap:

- the **Better Markdown Links** plugin writes the `/` form;
- **`kb fix-links`** (run by `just fix` and by the pre-commit hook) rewrites
  any internal link to the `/` form. It tries the target relative to the
  linking file first, then relative to the bundle root, and leaves links it
  cannot resolve alone;
- **`kb check`** reports a link that is not bundle-absolute (W031) and any
  wikilink or embed (H032, an error).

Links in generated `index.md` files are the exception: they use `./`
relative paths, so a subtree copied out of the bundle keeps working
indexes.

## Wanted pages

A link to a page that does not exist yet is allowed. It marks a *wanted
page*, as in a classic wiki: the author knows the topic deserves a page and
links it in advance. OKF tolerates broken links; `kb check` warns (W030),
`kb report` lists them, and the maintain workflow creates a wanted page
once two or more pages link to it. In Obsidian, a click on such a link
creates the page, and Templater gives it valid frontmatter.

## Typed relations

Some links carry a meaning worth making explicit: *this page is part of
that one*, *depends on it*, *replaces it*, *contradicts it*. The template
stores these as frontmatter keys whose value is a list of markdown links:

```yaml
part_of: ["[Distributed data stores](/systems/distributed/distributed-data-stores.md)"]
depends_on: ["[Consistency models](/systems/distributed/consistency-models.md)"]
```

The keys are declared in `schema/vocabulary.yaml` under `relations`, so each
knowledge base chooses its own. Each key automatically becomes a validated
frontmatter property.

The values are markdown links, not bare paths or wikilinks, for two
reasons:

- Obsidian indexes markdown links in frontmatter properties as real links:
  they appear in backlinks and the graph, and plugins such as Breadcrumbs
  can navigate them;
- the same `kb fix-links` and `kb mv` machinery keeps them valid.

### Why every relation needs a link in the prose

`kb check` requires each relation target to be linked from the body too
(H031). This looks redundant, but it is not.

- **OKF consumers ignore the keys.** `depends_on` is an extension key; an
  OKF reader that does not know it sees no link at all. A body link makes
  the connection visible to every reader.
- **A relation without an explanation is weak knowledge.** "Depends on
  Consistency models" does not say *which* part depends, or *why*. The
  sentence around the body link does:

    ```markdown
    Choosing between the two requires knowing which
    [consistency model](/systems/distributed/consistency-models.md) the
    application needs.
    ```

- **Agents write better with the rule.** Asking for the prose makes the
  agent justify each relation, which filters out relations added by habit.

The frontmatter relation stays useful as structured data: Breadcrumbs
navigates it, `kb dupes` treats `alternative_to`, `supersedes` and
`contradicts` as proof that two pages are distinct, and `kb graph` counts
relation edges.

## Heading anchors

Links to a section use GitHub-style anchors: `/path/page.md#some-heading`.
OKF readers and GitHub follow them. Obsidian opens the page but does not
scroll to the heading.
