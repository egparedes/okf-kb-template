---
name: kb-ingest
description: Ingest a source (URL, paper, doc, talk transcript) into the knowledge base. Writes a Source summary page and folds its knowledge into every page it touches. Use when the human shares something to add, read, summarize into the wiki, or "ingest".
---

# Ingest a source

An ingest **compiles** one source into the wiki. The Source page is the
receipt; the value is in the existing pages the source improves. Expect to
touch 5-15 pages.

## Steps

1. **Dedupe.** Run `rg -l "<canonical-url>" kb/sources`. If a Source page
   already exists, treat this as a re-ingest: update that page and continue
   from step 4.

2. **Fetch.** Save a readable copy in `.cache/sources/<slug>.md`, which is
   gitignored scratch and never part of `kb/`.
   - Web pages: fetch the content.
   - PDFs and office docs: `uvx markitdown <url-or-file> > .cache/sources/<slug>.md`.
   - Record the canonical URL, author and publication date.

3. **Write the Source page.**
   ```sh
   uv run kb new Source sources/<slug>.md --title "…" --description "…" --resource <url> --tags …
   ```
   - Add `author`, `published` (YYYY, YYYY-MM or YYYY-MM-DD) and, when it
     exists, `archived` (a Wayback Machine URL).
   - Fill `# Summary` and `# Key points` in your own words, keeping the
     claims specific enough to cite.
   - Choose `<slug>` as author-or-org plus a short topic, e.g.
     `kleppmann-ddia-ch5`, `rfc-9110`.

4. **Map the impact.**
   - Read `kb/index.md`, then the index of each relevant domain folder.
   - Run `just find --tag <tag>` and `rg -il "<term>" kb` for each key term
     in the source.
   - Write a list of every concept, technology, tool, pattern, practice,
     person or organization the source covers **substantively**, and mark
     each one *update* (a page exists) or *create*.
   - This step is done when every substantive topic of the source is on the
     list. Passing mentions stay off it.

5. **Compile.** For each page on the list:
   - **Create** pages with `uv run kb new <Type> <path> …`, choosing folders
     per `AGENTS.md`, or **update** existing pages by integrating the new
     knowledge into the right section. Don't append a "From source X" blob.
   - Add the source to the page's `sources` (id = the source slug, resource =
     `/sources/<slug>.md`) and cite each claim you add with `[^<slug>]`.
   - **Conflict:** when the source contradicts the page, keep both claims,
     cite both, and add a short `**Conflict:**` paragraph saying which is
     newer or better supported. Add the `contradicts` relation if one page
     contradicts another.
   - Add typed relations where they hold, each with a body link in prose.
   - Refresh `generated` (you, now in UTC). Set `stale_after` if facts in the
     page will expire.

6. **Close the loop.**
   - Under the Source page's `# Pages updated`, list every page you created
     or updated, as links.
   - Run `just fix`, then run `just check` until it reports 0 errors.
   - Log it: `uv run kb log Ingest "[<Source title>](/sources/<slug>.md). Created …; updated …."`

7. **Report** to the human:
   - the source's 3-5 key takeaways;
   - the pages created and updated;
   - any conflicts found;
   - wanted pages (links you left for later).
