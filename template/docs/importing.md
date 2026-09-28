# Importing an Obsidian vault or Logseq graph

`kb import` converts an existing vault into pages of this bundle. It is
deterministic: the same source and mapping file always give the same pages,
so you can refine the mapping and re-run the dry run until the plan is right.
The source is only read, never modified. Symbolic links in it are never
followed: they are listed as not imported, so a link to a file outside the
vault cannot bring that file into the repository. A file that turns into a
symbolic link during the run is refused too. Folders that cannot be read
are reported as issues.

```sh
uv run kb import ~/notes/old-vault --into projects/old --map imports/old-vault.yaml --dry-run
uv run kb import ~/notes/old-vault --into projects/old --map imports/old-vault.yaml
uv run poe check
```

The dry run prints the plan and every issue:

- each note, with its new path, type and title;
- each copied file;
- what is not imported, and why;
- the issues, such as links to excluded notes, block references and Dataview
  blocks.

A real run refuses to start while the plan has errors:

- two files with the same destination, or with destinations that differ only
  in case (they would be one file on macOS and Windows);
- a destination that is also the folder of another destination, or whose
  folder is an existing file;
- an existing page, also one that differs only in case;
- a reserved name (`index.md`, `log.md`), or a destination outside the bundle;
- an unavailable placeholder or an invalid template, or a rule without a type;
- a relation value that gives an empty file name.

The real run writes every file to a staging folder in `.cache/import/`
first, and then moves the files into place. If a step fails, the files
already moved are removed again, so the bundle never holds half an import.
Afterwards it:

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
| `[[Note#^block]]`, `^block` ids | a page link and no id (reported); an id is removed only at the end of a paragraph or list item, or on its own line after one, and never inside math |
| `[[#Heading]]` | `[Heading](#heading)` |
| `![[image.png]]`, `![[image.png\|300]]` | `![image](/…/assets/image.png)` |
| `![[Note]]` (transclusion) | `[Note](/…)` (reported) |
| relative, vault-path or bare-name markdown links | bundle-absolute links to the new paths |
| reference-style link definitions (`[x]: path`) | unchanged (reported): rewrite them as inline links |
| a wikilink to an excluded or missing note | its text only (reported); names under `links` point to existing pages when no source file has that name, and `unresolved: wanted` links the rest as wanted pages |
| a linked image without a `files` rule | copied to `<into>/assets/` |
| a linked PDF or office document without a `files` rule | not copied (reported): reference it with a `file:` locator, or add a rule |
| `%% comment %%` outside code | `<!-- comment -->` |
| YAML properties, Logseq `key:: value` page properties | frontmatter, after the `properties` rules; Logseq `[[page]]` values become plain values |
| `[[Note]]` in a YAML property value | `[Note](/…/note.md)`, converted like a link in the text |
| Logseq `id::` and `collapsed::` block properties | removed, also at the top of the file |
| `#tag` in the text (outside code and math) | added to `tags`, kebab-case; the text stays. Colours such as `#ff0000` are not tags |
| `tags: a, b` (a string) | the tags `a` and `b` |
| file and folder names | kebab-case |

For each note, the frontmatter is built as follows:

- **`title`:** the rule's `title` template, or the H1 on the first line,
  or a `title` property, or the file name (Logseq `a___b` becomes `a/b`).
  An H1 on the first line is always removed, since it would repeat the
  title. When no other H1 remains, the remaining headings move up one level,
  so that sections are H1 as in the rest of the bundle.
- **`description`:** a `description` property, or the first sentence of the
  first paragraph. Comments (`%% … %%` and `<!-- … -->`) never count, so
  private remarks do not reach the description or the indexes. Placeholders
  are reported.
- **`aliases`:** existing aliases, plus the old file name when it differs from
  the title.
- **`status`:** `draft` (or the rule's `status`).
- **`generated`:** the mapping's `actor`, and a time taken from the
  `timestamp` property, the file's last git commit, or its modification time.
  A time in the future is clamped to now. The commit times come from one
  `git log` over the source, stopped after 60 seconds.

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

Unknown keys are an error, so that a typo such as `exlude` does not
silently import everything. This holds at the top level, in a rule, in a
rule's `type`, in a `properties` entry (`rename`, `map`, `relation`,
`target`), in `tags` (`inline`, `drop`, `map`) and in a `rewrite` entry
(`pattern`, `replace`). An invalid regular expression in `rewrite`,
`tags.drop` or `description_skip` is an error that names the key.

The `actor` (or `--by`) must match the actor pattern of
`schema/frontmatter.schema.json`: `human:<id>`, `process:<id>` or
`<agent>/<model>`. A context-window suffix on the model is dropped first, as
`kb new` does: `claude-code/claude-opus-5-5[1m]` becomes
`claude-code/claude-opus-5-5`.

Each value must have the right shape: `notes` and `files` are lists of
rules, `properties`, `links`, `tags` and a rule's `type.map` are mappings,
and `timestamp`, `label` and `actor` are strings.

- **Patterns:** `match` and `exclude` are globs on the source path. `**`
  crosses folders, while `*` and `?` do not, and brackets are literal.
  `exclude` ignores case (`private/**` also excludes `Private/`); `match`
  does not. Hidden folders, `.obsidian/`, `.trash/` and Logseq's `logseq/`
  are always skipped.
- **Placeholders** in `to`:
    - `{path}`: the source path without extension;
    - `{dir}`, `{parent}`, `{stem}`, `{name}`, `{ext}`;
    - `{date}`, `{yyyy}`, `{mm}`, `{dd}`: from a `YYYY-MM-DD` or `YYYY_MM_DD`
      date in the name or path.

    `title` supports `{stem}`, `{parent}` and `{date}`.
- **Relations:** each value of a `relation` property becomes a markdown link
  to `target`, with `{value}` in kebab-case. A value that is a wikilink to
  an imported note (`"[[Big Box]]"`) links to that note's new path instead. `target` is relative to
  `--into` unless it starts with `/`. The link text is the target page's
  title when that page is part of the import. Declare the relation key under
  `relations` in `schema/vocabulary.yaml` (the example's `applies_to` is not a
  default relation); `kb check` then requires each target to be linked from
  the body (H031).
- **Rewrite rules** run in order, with Python `re` and the flags
  `MULTILINE` and `DOTALL`. `.` therefore also matches newlines: use
  `[^\n]*` to stay on one line, and non-greedy `.*?` across lines.
- **Types and keys:** the importer does not check types against
  `schema/vocabulary.yaml`, so `kb check` reports unknown ones afterwards
  (H011). Kept properties that the schema does not know are reported as W010:
  declare them under `fields` first, or drop them.

## After the import

1. Register the new folders in `schema/taxonomy.yaml` (otherwise `kb check`
   warns W050), run `uv run poe fix`, then `uv run poe check`, and fix what it reports.
2. Run `uv run kb dupes --scope all` and `uv run kb unlinked --all` for
   overlaps with existing pages.
3. Improve weak descriptions: the first sentence is not always a summary.
4. Log it: `uv run kb log Ingest "Imported <vault> into [<Title>](/<folder>/…)"`.
