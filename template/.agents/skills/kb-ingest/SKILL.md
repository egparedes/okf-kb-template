---
name: kb-ingest
description: Ingest a source (URL, paper, doc, talk transcript) into the knowledge base. Writes a Source summary page and folds its knowledge into every page it touches. Use when the human shares something to add, read, summarize into the wiki, or "ingest".
---

# Ingest a source

An ingest **compiles** one source into the wiki. The Source page is the
receipt; the value is in the existing pages the source improves. Expect to
touch 5-15 pages.

## Steps

1. **Dedupe.** Search `kb/sources` for the canonical URL, the Zotero item key
   and the citation key (`rg -l "<url>|<KEY>|<citekey>" kb/sources`). If a
   Source page already exists, treat this as a re-ingest: update that page
   and continue from step 4.

2. **Fetch.** Get the text into `.cache/sources/` (gitignored scratch, never
   part of `kb/`). Pick the branch that matches the source; setup is in
   `docs/external-resources.md`.
   - **Paper, book or report:** it belongs in Zotero. If it is not there
     (`uv run kb zotero search <words>`), ask the human to add it. Then:
     ```sh
     uv run kb zotero new-source <key-or-citekey> --tags …
     uv run kb fetch zotero:<key-or-citekey>
     ```
   - **Web page:** `uv run kb fetch <url>`. This archives the page in
     KaraKeep and extracts its text. Without KaraKeep, fetch the page
     yourself and save it to `.cache/sources/`.
   - **File in a declared root** (talk slides, course material):
     `uv run kb fetch "file:<root>/<path>"`.
   - Record the canonical URL, author and publication date.

3. **Write the Source page.**
   - Zotero sources already have one, created by `kb zotero new-source`.
     It is named `sources/<slug>.md`, where the slug is the citation key in
     kebab-case, and has status `draft`.
   - Otherwise create it:
     ```sh
     uv run kb new Source sources/<slug>.md --title "…" --description "…" --resource <url> --tags …
     ```
     Choose `<slug>` as author-or-org plus a short topic, e.g.
     `kleppmann-ddia-ch5`, `rfc-9110`.
   - Add `author` and `published` (YYYY, YYYY-MM or YYYY-MM-DD) if missing.
   - For files in a root, add `locators: ["file:<root>/<path>"]`.
   - Write a real one-sentence `description`.
   - Fill `# Summary` and `# Key points` in your own words, keeping the
     claims specific enough to cite.
   - Set `status: stable` when the summary is complete.

4. **Map the impact.**
   - Read `kb/index.md`, then the index of each relevant domain folder.
   - Run `just find --tag <tag>` and `rg -il "<term>" kb` for each key term
     in the source.
   - After compiling, run `uv run kb unlinked <pages you touched>` to find
     mentions of existing pages that should become links.
   - Write a list of every concept, technology, tool, pattern, practice,
     person or organization the source covers **substantively**, and mark
     each one *update* (a page exists) or *create*.
   - This step is done when every substantive topic of the source is on the
     list. Passing mentions stay off it.

5. **Compile.** For each page on the list:
   - **Create** pages with `uv run kb new <Type> <path> …`, choosing folders
     per `AGENTS.md`, or **update** existing pages by integrating the new
     knowledge into the right section. Don't append a "From source X" blob.
   - Add the source to the page's `sources` (`id: <slug>` = the Source page's
     file name, `resource: /sources/<slug>.md`) and cite each claim you add
     with `[^<slug>]`.
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
