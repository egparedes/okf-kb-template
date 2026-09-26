# Importing an Obsidian vault or Logseq graph

`kb import` converts an existing vault into pages of this bundle. It is
deterministic: the same source and mapping file always give the same pages,
so you can refine the mapping and re-run the dry run until the plan is right.
The source is only read, never modified.

```sh
uv run kb import ~/notes/old-vault --into projects/old --map imports/old-vault.yaml --dry-run
uv run kb import ~/notes/old-vault --into projects/old --map imports/old-vault.yaml
just check
```

The dry run prints the plan and every issue:

- each note, with its new path, type and title;
- each copied file;
- what is not imported, and why;
- the issues, such as links to excluded notes, block references and Dataview
  blocks.

A real run refuses to start while the plan has errors: two notes with the
same destination, an existing page, a reserved name (`index.md`, `log.md`)
or a missing type. Afterwards it:

- regenerates the indexes;
- writes a redirect table (source path → bundle path) to
  `.cache/import/<vault>-redirects.tsv`, or to `--redirects <file>`.

Keep the mapping file (e.g. `imports/<vault>.yaml`) in the repository as the
record of how the import was done.

## What the converter does

| In the source | In the bundle |
|---|---|
| `[[Note]]`, `[[Note\|text]]`, `[[folder/Note]]`, `[[../folder/Note]]` | `[Note](/new/path/note.md)`, `[text](…)` |
| `[[Note#Heading]]`, `[[Note#Section#Heading]]` | `[Note › Heading](/…/note.md#heading)` |
| `[[Note#^block]]`, `^block` ids | a page link and no id (reported) |
| `[[#Heading]]` | `[Heading](#heading)` |
| `![[image.png]]`, `![[image.png\|300]]` | `![image](/…/assets/image.png)` |
| `![[Note]]` (transclusion) | `[Note](/…)` (reported) |
| relative, vault-path or bare-name markdown links | bundle-absolute links to the new paths |
| reference-style link definitions (`[x]: path`) | unchanged (reported): rewrite them as inline links |
| a wikilink to an excluded or missing note | its text only (reported); names listed under `links` point to existing pages, and `unresolved: wanted` links the rest as wanted pages |
| a linked image without a `files` rule | copied to `<into>/assets/` |
| a linked PDF or office document without a `files` rule | not copied (reported): reference it with a `file:` locator, or add a rule |
| `%% comment %%` outside code | `<!-- comment -->` |
| YAML properties, Logseq `key:: value` page properties | frontmatter, after the `properties` rules; Logseq `[[page]]` values become plain values |
| Logseq `id::` and `collapsed::` block properties | removed |
| `#tag` in the text (outside code) | added to `tags`, kebab-case; the text stays |
| file and folder names | kebab-case |

For each note, the frontmatter is built as follows:

- **`title`:** the rule's `title` template, or the H1 on the first line,
  or a `title` property, or the file name (Logseq `a___b` becomes `a/b`).
  An H1 on the first line is always removed, since it would repeat the
  title. When no other H1 remains, the remaining headings move up one level,
  so that sections are H1 as in the rest of the bundle.
- **`description`:** a `description` property, or the first sentence of the
  first paragraph. Placeholders are reported.
- **`aliases`:** existing aliases, plus the old file name when it differs from
  the title.
- **`status`:** `draft` (or the rule's `status`).
- **`generated`:** the mapping's `actor`, and a time taken from the
  `timestamp` property, the file's last git commit, or its modification time.
  A time in the future is clamped to now.

A source note that has its own `status`, `generated` or `verified` property
is a plan error until the mapping gives that property a `drop` rule, or a
`rename` to another key, because the importer writes these keys itself.

Code blocks and inline code are never changed, apart from `rewrite` rules
(which see the raw text). Indented code blocks are not recognised as code.
Dataview blocks stay as code and are reported: rewrite them as Bases, or
drop them with a `rewrite` rule.

Heading links use GitHub-style anchors (`#some-heading`), which OKF readers
and GitHub follow. Obsidian opens the page but does not scroll to the
heading.

## The mapping file

```yaml
label: old-vault                 # used in placeholder descriptions
actor: human:alice               # generated.by for every page (or --by)
timestamp: updated               # optional: property holding the note's date
exclude: ["private/**", "People/**"]
unresolved: text                 # or `wanted`
max_bytes: 2000000               # larger attachments are not copied (reported)
description_skip: ["^Applies to:"]   # regexes for lines that never become the description
links:                           # wikilink names that no note resolves -> existing pages
  DaCe: /programming/dace.md

notes:                           # first matching rule wins; unmatched notes are not imported
  - match: README.md
    to: old.md                   # relative to --into; a leading / makes it bundle-absolute
    type: Project
    title: Old project
  - match: "Journal/**/*.md"
    to: "/journal/{yyyy}/{date}.md"
    type: Journal Entry
    title: "{date}"
    alias_stem: false
  - match: "topics/*/*.md"
    to: "{parent}/{stem}.md"
    type: { from: type, map: { guide: Guide, record: Record }, default: Concept }
    tags: [imported]             # added to every page of the rule
  - match: "Archive/**"
    skip: true

files:                           # non-markdown files; unmatched images are copied to
  - match: "topics/*/*"          #   <into>/assets/ only when an imported note links them
    to: "{parent}/{name}"
    kebab: false                 # keep installed names (scripts, units)

properties:                      # unlisted properties are kept (status, generated, verified need a rule)
  updated: drop
  status: { rename: state, map: { wip: active } }
  devices: { relation: applies_to, target: "devices/{value}.md" }

tags:
  inline: collect                # or `ignore`
  drop: ["^\\d", "^Y\\d{4}$"]    # regexes for tags to leave out (dates, …)
  map: { gt4py-meeting: gt4py }

rewrite:                         # regex substitutions on the text after the frontmatter
  - pattern: "```dataview\\n.*?```\\n"
    replace: ""
```

Unknown keys, at the top level or in a rule, are an error, so that a typo
such as `exlude` does not silently import everything.

- **Patterns:** `match` and `exclude` are globs on the source path. `**`
  crosses folders, while `*` and `?` do not, and brackets are literal.
  Hidden folders, `.obsidian/`, `.trash/` and Logseq's `logseq/` are always
  skipped.
- **Placeholders** in `to`:
  - `{path}`: the source path without extension;
  - `{dir}`, `{parent}`, `{stem}`, `{name}`, `{ext}`;
  - `{date}`, `{yyyy}`, `{mm}`, `{dd}`: from a `YYYY-MM-DD` or `YYYY_MM_DD`
    date in the name or path.

  `title` supports `{stem}`, `{parent}` and `{date}`.
- **Relations:** each value of a `relation` property becomes a markdown link
  to `target`, with `{value}` in kebab-case. It uses the target page's title
  when that page is part of the import. `kb check` then requires each
  target to be linked from the body (H031).
- **Rewrite rules** run in order, with Python `re` and the flags
  `MULTILINE` and `DOTALL`. `.` therefore also matches newlines: use
  `[^\n]*` to stay on one line, and non-greedy `.*?` across lines.
- **Types and keys:** every type must exist in `schema/vocabulary.yaml`, and
  kept properties that the schema does not know are reported by `kb check`
  (W010). Declare them under `fields` first, or drop them.

## After the import

1. Register the new folders in `schema/taxonomy.yaml` (otherwise `kb check`
   warns W050), run `just fix`, then `just check`, and fix what it reports.
2. Run `uv run kb dupes --scope all` and `uv run kb unlinked --all` for
   overlaps with existing pages.
3. Improve weak descriptions: the first sentence is not always a summary.
4. Log it: `uv run kb log Ingest "Imported <vault> into [<Title>](/<folder>/…)"`.
