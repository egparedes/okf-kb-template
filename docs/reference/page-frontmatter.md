# Page frontmatter and schema files

Every `.md` file in the knowledge-base folder (named after `kb_name` by
default; `kb/` in knowledge bases created before v0.5.0), except `index.md`
and `log.md`, is a page. It
starts with a YAML frontmatter block. OKF itself only requires a non-empty
`type`; the template adds a *house profile* that `kb check` enforces.

```yaml
---
type: Concept                      # from schema/vocabulary.yaml
title: CAP theorem
description: One sentence that stands alone; it becomes the index entry.
aliases: [Brewer's theorem]        # optional, helps search and kb unlinked
tags: [distributed-systems]        # kebab-case, cross-cutting only
status: stable                     # draft | stable | deprecated
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-25T12:00:00Z }
verified: { by: human:alice, at: 2026-09-26T08:00:00Z }   # only after a human review
stale_after: 2027-09-01T00:00:00Z  # optional, for facts that expire
sources:
  - id: brewer-2012                # cited in the body as [^brewer-2012]
    resource: /sources/brewer-2012.md
    title: CAP twelve years later
depends_on: ["[Consistency models](/systems/distributed/consistency-models.md)"]
---
```

The shapes are defined in `schema/frontmatter.schema.json` (JSON Schema
2020-12), which the template manages, and extended by
`schema/vocabulary.yaml`, which the knowledge base owns.

## Core keys

| Key | Required | Shape | Meaning |
|---|---|---|---|
| `type` | yes | non-empty string, a type from `vocabulary.yaml` | What the page is. |
| `title` | yes | non-empty string | Display title; used in indexes. |
| `description` | yes | string, 1 to 300 characters | One standalone sentence; becomes the index entry. |
| `tags` | yes (except `Template`) | list of unique kebab-case strings; `/` allowed for nesting | Cross-cutting topics. Folders already give the main topic. |
| `status` | yes (except `Template`) | `draft`, `stable` or `deprecated` | `draft` while incomplete; `deprecated` when superseded. |
| `generated` | yes (except `Template`) | `{ by: <actor>, at: <datetime> }` | Who last wrote the page meaningfully, and when (UTC). |
| `verified` | no | an event `{ by, at }`, or a non-empty list of events | Reviews. A `human:` actor makes the page *human-reviewed*. |
| `aliases` | no | list of non-empty strings | Other names; used by search, `kb dupes` and `kb unlinked`. |
| `resource` | `Source` pages | non-empty string | The canonical URL of the external source. |
| `sources` | no | list of `{ id, resource, title?, author?, usage_count?, last_modified?, usage_window? }` | What the page cites. `id` is kebab-case; `resource` is usually `/sources/<id>.md`. |
| `stale_after` | no | datetime | After this instant, `kb check` warns (W040) and `kb report` lists the page. |
| `usage_window` | no | `{ from, to }` datetimes | OKF usage metadata. |

### Keys for Source pages

| Key | Shape | Meaning |
|---|---|---|
| `author` | string | Author(s) of the external source. |
| `published` | `YYYY`, `YYYY-MM` or `YYYY-MM-DD` | Publication date. |
| `archived` | `http(s)://…` URL | An archived snapshot, e.g. on the Wayback Machine. |
| `zotero` | `{ key, citekey?, library? }` | Zotero pointer. `key` is the 8-character item key (`[A-Z0-9]{8}`); `citekey` the Better BibTeX key; `library` is `user` or `group:<id>`. No other keys. |
| `locators` | non-empty list of unique strings, each `file:<root>/<path>` or `zotero:<KEY>` | Access routes to material outside the bundle. Roots are declared in `schema/resources.yaml`. |

### Value formats

| Format | Pattern | Examples |
|---|---|---|
| datetime | ISO 8601 with an explicit UTC offset | `2026-09-25T12:00:00Z`, `2026-09-25T14:00+02:00` |
| actor | `human:<id>`, `process:<id>` or `<tool>/<model>` | `human:alice`, `process:nightly-lint`, `claude-code/claude-opus-5-5` |
| relation value | a markdown link to a bundle-absolute `.md` path, optionally with an anchor | `"[Consensus](/systems/consensus.md)"` |

Keys not defined anywhere are allowed by OKF, but `kb check` warns about
them (W010), to catch typos.

## `schema/vocabulary.yaml`

Owned by the knowledge base. It has three sections.

### `types`

Each type has:

| Key | Meaning |
|---|---|
| `plural` | Section heading in the generated indexes. |
| `description` | When to use the type. |
| `folders` | Folder prefixes where the type may live. `"*"` means any knowledge-domain folder. Default `["*"]`. |
| `required` | Frontmatter keys required on top of the core profile. |
| `sections` | Body headings of a new page (`kb new`). |

The template ships these types. Keep them; the skills and tools rely on
them. Add your own below them.

| Type | Folders | Sections of a new page |
|---|---|---|
| `Concept` | knowledge domains | Definition, Details, Examples, Related |
| `Practice` | knowledge domains | Goal, Steps, Pitfalls, Related |
| `Comparison` | knowledge domains, `syntheses/` | Summary, Comparison, Recommendation, Related |
| `Synthesis` | `syntheses/` | Question, Answer, Evidence, Open questions |
| `Source` (requires `resource`) | `sources/` | Summary, Key points, Pages updated |
| `Person` | `entities/` | Overview, Contributions, Related |
| `Organization` | `entities/` | Overview, Contributions, Related |
| `Project` | `projects/` | Goal, Status, Decisions, Links |
| `Decision Record` | `projects/` | Context, Decision, Alternatives, Consequences |
| `Journal Entry` | `journal/` | Notes, Open questions |
| `Template` | `_templates/` | none |

`Template` pages are Obsidian Templater templates. They need only `type`,
`title` and `description`, and `kb check` skips their links and citations.

### `relations`

Typed relations: each key maps to a sentence saying what it means. Every key
becomes a frontmatter property whose value is a list of markdown links.

| Relation | Meaning |
|---|---|
| `part_of` | The page is a component or subtopic of the target. |
| `depends_on` | Understanding or using the page requires the target first. |
| `example_of` | The page is an instance or illustration of the target. |
| `alternative_to` | The page and the target solve the same problem differently. |
| `supersedes` | The page replaces the target, which is outdated. |
| `contradicts` | The page makes claims in conflict with the target. |
| `related` | Any other notable relationship, explained in the body. |

Each target must also be linked from the body, in prose (H031). See
[Links and relations](../explanation/links-and-relations.md).

### `fields`

Extra frontmatter keys for this knowledge base, as JSON Schema snippets.
They are added to the core schema, so `kb check` validates them and stops
warning W010.

```yaml
fields:
  isbn: { type: string, pattern: "^[0-9X-]+$" }
  state: { enum: [active, done, closed, superseded] }
```

## `schema/taxonomy.yaml`

Owned by the knowledge base. It describes the subfolders of the
knowledge-base folder; the index generator takes titles and descriptions
from it.

```yaml
root_groups: [Knowledge domains, Library, Personal, Vault]

folders:
  ai:
    group: Knowledge domains
    title: AI and machine learning
    description: Models, training, evaluation and LLM tooling.
  ai/evaluation:
    title: Evaluation
    description: Benchmarks and evaluation methods.
  journal:
    group: Personal
    title: Journal
    description: Dated personal notes (one folder per year).
    sort: date-desc
    auto_children: true
```

| Key | Where | Meaning |
|---|---|---|
| `root_groups` | top level | Order of the groups in the root `index.md`. |
| `folders.<path>` | top level | One entry per folder, by bundle-relative path. Every folder needs one (W050 otherwise). |
| `group` | top-level folders | Heading under which the root index lists the folder. |
| `title`, `description` | every folder | The folder's entry in its parent index. |
| `sort: date-desc` | any folder | List pages and subfolders newest first by name; inherited by subfolders. |
| `auto_children: true` | any folder | Subfolders need no entry; their title is the folder name. |

The groups have fixed meanings:

| Group | Folders | Owner |
|---|---|---|
| Knowledge domains | your domains | Agents and you. Types with `folders: ["*"]` live here. |
| Library | `sources`, `syntheses`, `entities` | Agents and you. |
| Personal | `projects`, `journal` | You. Agents edit them only when asked; analytics skip them by default; knowledge-edit log entries are not required for them. |
| Vault | `_templates` | You (Obsidian tooling). |

Folders starting with `_` or `.` get no index.

## `schema/resources.yaml`

Owned by the knowledge base. Settings for external material that can be
committed; secrets and machine paths go in `.env`.

```yaml
zotero:
  user_id: 1234567       # numeric Zotero user id, for the web API fallback
  # group_id: 7654321    # read a group library instead
roots:
  talks: My talks - slides and sources, one dated folder per talk.
deny:
  - "documents/Personal/**"
```

| Key | Shape | Meaning |
|---|---|---|
| `zotero.user_id` | number or null | Zotero user id for the web API. |
| `zotero.group_id` | number | Use this group library instead of the user library. |
| `roots` | mapping name → description | File roots that locators point into; each is mapped per machine with `KB_ROOT_<NAME>`. |
| `deny` | list of glob strings | `root/path` patterns that `kb fetch` and `kb open` refuse, and that make locators an error (H060). |

A wrong shape is reported as H061.

## `schema/distinct.yaml`

Optional; create it when needed. Pairs of pages that `kb dupes` must not
report again:

```yaml
distinct:
  - [/ai/llm.md, /ai/llm-evaluation.md]
```

Pages related by `alternative_to`, `supersedes` or `contradicts` are never
reported as duplicates either.

## Body conventions

- Top-level sections are H1 headings (`# Definition`); the title is in the
  frontmatter.
- Links to other pages are markdown links with bundle-absolute targets:
  `[CAP theorem](/systems/distributed/cap-theorem.md)`. Wikilinks and
  embeds are errors (H032).
- Citations are footnotes whose label is a `sources[].id`, with a
  definition that links the Source page:

    ```markdown
    Partition tolerance cannot be given up in practice.[^brewer-2012]

    [^brewer-2012]: [CAP twelve years later](/sources/brewer-2012.md)
    ```

- File and folder names are kebab-case (H001).
