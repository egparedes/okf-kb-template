# Provenance and trust

When most of a knowledge base is written by agents, a reader needs to know,
for each page: who wrote it, what it rests on, whether a person checked it,
and whether it is still current. The template records each of these in the
page's frontmatter, using OKF's provenance fields.

## Who wrote it: `generated`

```yaml
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-27T12:00:00Z }
```

`generated` names the *actor* of the last meaningful edit and when it
happened, in UTC. Actors have three forms:

| Form | Example | Who |
|---|---|---|
| `<tool>/<model>` | `claude-code/claude-opus-5-5` | an agent, naming the model |
| `human:<id>` | `human:alice` | a person |
| `process:<id>` | `process:nightly-lint` | an automated process |

Agents take their actor from `KB_ACTOR` (set by Claude Code from the
`agent_actor` answer) or `--by`. Pages you write in Obsidian get
`human:<owner_id>` from the templates. When the agent writes on your behalf,
the actor is still the agent: `generated` records who wrote the text, not
who asked for it.

Naming the model matters. When a model is found to make a certain kind of
mistake, `kb find` and `rg` can list every page it wrote.

## What it rests on: sources and citations

```yaml
sources:
  - id: brewer-2012
    resource: /sources/brewer-2012.md
    title: CAP twelve years later
```

```markdown
Partition tolerance cannot be given up in practice.[^brewer-2012]

[^brewer-2012]: [CAP twelve years later](/sources/brewer-2012.md)
```

Every non-obvious claim carries a footnote whose label is a `sources[].id`.
The chain from claim to origin has three links:

1. the footnote in the text points to a source id;
2. the source's `resource` is a Source page in `kb/sources/`, which
   summarizes the source and lists the pages it fed;
3. the Source page's own `resource` is the canonical URL, and possibly a
   `zotero` pointer, `locators` to a file, or an `archived` snapshot.

`kb check` enforces the first link: a footnote without a matching source is
an error (H020), and a source never cited is a warning (W020).

What the agent adds from its own knowledge carries no footnote, and the
skills require the prose to make that clear. A reader can therefore tell
*sourced* from *model-supplied* statements.

A Synthesis page, filed back from a query, cites knowledge-base pages rather
than external sources: its `sources` point at the pages it combined.

## Whether a person checked it: `verified` and trust tiers

```yaml
verified: { by: human:alice, at: 2026-09-28T09:00:00Z }
```

`verified` records reviews: one event, or a list. From it, OKF derives a
page's *trust tier*:

| Tier | Condition |
|---|---|
| unverified | no `verified` |
| machine-confirmed | `verified` only by processes or agents |
| human-reviewed | at least one `verified` event by a `human:` actor |

Two rules keep the tiers meaningful:

- **The agent never verifies its own work.** It adds `verified` with your id
  only when you say you reviewed that page.
- **Merging resets the review.** `kb merge` drops `verified`, because the
  merged text has not been reviewed.

`kb report` counts knowledge pages per tier, `kb find --trust unverified`
lists them, and `kb graph` puts central but unverified pages at the top of
its "review first" list. In Obsidian, `_views/review-queue.base` shows the
same queue. The query skill flags answers that depend on unverified pages.

## Whether it is finished: `status`

`status` is `draft` while a page is incomplete, `stable` when it is
complete, and `deprecated` when another page has replaced it (usually with
a `supersedes` relation from the new page). `kb new` creates drafts; the
agent sets `stable` when the page is done.

## Whether it is still current: `stale_after`

```yaml
stale_after: 2027-03-01T00:00:00Z
```

Some facts expire: version numbers, prices, roadmaps, "the current
maintainer". Pages that contain such facts carry a `stale_after` date.
After it, `kb check` warns (W040), and `kb report` lists the page. The
maintain workflow then re-checks the page against its sources, updates it,
and moves the date forward.

Staleness is a date rather than a judgement made at read time because a
date can be set when the fact is written, by the writer who knows how
volatile it is.
