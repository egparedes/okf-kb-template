# Import an Obsidian vault or Logseq graph

`kb import` converts an existing vault into pages of the bundle. It is
deterministic: the same source and mapping file always give the same pages.
You refine a mapping file and re-run a dry run until the plan is right,
then import. The source vault is only read, never modified.

This guide gives the procedure. The full mapping format and the conversion
rules are in the [import mapping reference](../reference/import-mapping.md).

## 1. Prepare the target

- Decide the bundle folder the notes go into, for example `projects/old`.
- Make sure every page type you will use exists in `schema/vocabulary.yaml`.
  Add types there first if needed.
- Declare frontmatter keys you want to keep under `fields` in
  `schema/vocabulary.yaml`, or plan to drop them.
- Start from a clean working tree (`git status`), so the import is one
  reviewable change.

## 2. Write a first mapping

Create `imports/old-vault.yaml` in the repository. Start small: one rule
that maps everything to `Concept`, and exclusions for what must never come
in.

```yaml
label: old-vault
actor: human:alice               # generated.by of every imported page
exclude: ["private/**", "People/**"]
unresolved: text                 # links to missing notes become plain text

notes:
  - match: "**/*.md"
    to: "{path}.md"
    type: Concept
```

Rules are tried in order and the first match wins. Notes that no rule
matches are not imported.

## 3. Run the dry run

```sh
uv run kb import ~/notes/old-vault --into projects/old --map imports/old-vault.yaml --dry-run
```

The dry run prints:

- each note, with its new path, type and title;
- each copied file;
- what is not imported, and why;
- the issues, such as links to excluded notes, block references and
  Dataview blocks.

Nothing is written.

## 4. Refine and repeat

Adjust the mapping and run the dry run again. Typical refinements:

- specific rules before the catch-all, for example journal notes to
  `/journal/{yyyy}/{date}.md` with type `Journal Entry`;
- `skip: true` rules for archives;
- `properties` rules to drop, rename or map keys, and to turn a property
  into a typed relation;
- `tags` rules to drop date tags or rename tags;
- `rewrite` rules to remove Dataview blocks;
- `links` entries for wikilink names that should point to pages already in
  the bundle.

A real run refuses to start while the plan has errors, for example:

- two notes with the same destination, or with destinations that differ
  only in case;
- a destination that is also the folder of another destination;
- an existing page, a reserved name (`index.md`, `log.md`), or a destination
  outside the bundle;
- a placeholder that is not available for a file, or an invalid template,
  in `to` or `title`;
- a rule without a `type`, or a `type: {from: …}` mapping with no match and
  no default;
- a source note with its own `status`, `generated` or `verified` property
  that has no `drop` or `rename` rule.

Mistakes in the mapping file itself stop the command before the plan: an
unknown key at any level, an invalid regular expression, or an `actor` that
is not `human:<id>`, `process:<id>` or `<agent>/<model>`. The message names
the key.

Symbolic links in the vault are listed as not imported. Copy a linked file
into the vault if you want to import it.

Types are not checked against `schema/vocabulary.yaml` during the import;
`kb check` reports unknown ones afterwards (H011).

## 5. Import

```sh
uv run kb import ~/notes/old-vault --into projects/old --map imports/old-vault.yaml
```

The import writes the pages to a staging folder in `.cache/import/` and
moves them into place when all are written. If it fails part-way, for
example on a full disk, it removes what it had moved, and the bundle is as
before. It then regenerates the indexes, and writes a redirect
table (source path → bundle path) to `.cache/import/<vault>-redirects.tsv`,
or to the file given with `--redirects`.

Keep the mapping file in the repository as the record of how the import was
done.

## 6. Finish

1. Register the new folders in `schema/taxonomy.yaml` (otherwise `kb check`
   warns W050), then run `uv run poe fix` and `uv run poe check`, and fix what it
   reports.
2. Look for overlaps with existing pages:

    ```sh
    uv run kb dupes --scope all
    uv run kb unlinked --all
    ```

3. Improve weak descriptions. The first sentence of a note is not always a
   summary.
4. Log it:

    ```sh
    uv run kb log Ingest "Imported old-vault into [Old project](/projects/old/index.md)"
    ```

5. Review the diff and commit.

You can also ask your agent to do the import. `AGENTS.md` points it to a
dry run with a mapping file; ask it to show you the plan before the real
run.
