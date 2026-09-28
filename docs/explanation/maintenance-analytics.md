# Maintenance analytics

A wiki written by many agent sessions drifts: two sessions create pages for
the same concept under different names; a page mentions a topic that has
its own page without linking it; a central page is never reviewed. Three
read-only commands find candidates for these problems. The agent, and for
merges you, decide what to do with them.

## Which pages

`kb graph`, `kb dupes`, `kb unlinked` and `kb report` look at the same
pages. What is **excluded** matters as much as what is included:

- **Every `index.md` and `log.md`.** Generated indexes link to every page
  in their folder. Counted as pages, they would be the most central nodes of
  the graph, and no page would ever be an orphan. Excluding them
  structurally is what makes the metrics mean something. The committed
  Obsidian graph filter excludes them for the same reason.
- **Templates and folders starting with `_` or `.`**, such as
  `_templates/`: vault tooling, not knowledge. Dot-folders such as
  `.trash/`, and gitignored files, are not part of the bundle at all.
- **Pages whose frontmatter does not parse or has no `type`.** `kb check`
  reports them.
- **Personal areas** (`projects/`, `journal/`), unless `--scope all`
  (`kb unlinked --all`). `kb report` counts personal pages in its type and
  status totals, and leaves them out of the trust and citation sections.

## The link graph: `kb graph`

`kb graph` builds a directed graph of the knowledge pages and their links
(body links and relations), and reports what a reviewer should look at.
Source pages are not nodes: links to and from them are counted as
citations, a separate layer, not as topical links.

From the graph it reports:

| Result | Computed as | Why it is useful |
|---|---|---|
| Most central | PageRank | The pages others depend on most. |
| Review first | Central pages that are unverified or uncited | Errors there spread furthest. |
| Orphans | No inbound links (Synthesis and Comparison pages excepted) | Nobody reaches them by browsing. |
| Dead ends | No outbound links | Readers get stuck. |
| Sink hubs | 3 or more inbound, no outbound | Important pages that give nothing back. |
| Small islands | Connected components of 2 or 3 pages | Clusters cut off from the rest. |
| Weakly linked tags | Tags on 5 or more pages whose pages rarely link each other | A topic that exists only as a label. |
| Co-link gaps | Page pairs often linked from the same pages, with no Synthesis or Comparison about them | A comparison or synthesis worth writing. |

## Near-duplicates: `kb dupes`

`kb dupes` proposes pairs of pages that may describe the same thing. It
compares names (titles, aliases and file names) and, optionally, text:

| Signal | Score |
|---|---|
| same name | 1.0 |
| same `resource` URL | 1.0 |
| one page's name is the other's acronym (`LLM` / `Large language models`) | 0.9 |
| overlapping name words (Jaccard 0.5 or more) | the overlap |
| similar spelling (ratio 0.85 or more) | the ratio |
| shared text, with `--body` (5-word shingles, overlap 0.3 or more) | 0.5 + overlap / 2 |
| similar description, same folder, 2 or more shared tags | small bonuses on top |

To stay fast on thousands of pages, only pages that share a name word, a
4-letter word prefix, an acronym, a whole name or a resource are compared.
A word or prefix shared by more than 200 pages is too common to compare
every pair; pages with the same whole name or the same resource are always
compared.

Some pairs are never proposed:

- a Source page and a non-Source page: a source summary legitimately shares
  its name with the concept it feeds;
- two Journal Entry pages (from v0.4.0): their date titles look alike;
- pages related by `alternative_to`, `supersedes` or `contradicts`, or
  listed in `schema/distinct.yaml`: someone already decided they are
  distinct.

## Unlinked mentions: `kb unlinked`

`kb unlinked` finds places where a page mentions another page's title or
alias without linking to it.

- The longest matching name wins, so "distributed consensus" is not also
  reported as "consensus".
- Matching ignores case and accents, except for all-caps names (acronyms),
  which match case-sensitively, so "API" is not found in "rapid".
- A name matches with spaces, `-` or `_` between its words, and with a
  plural ending (`s`, `es`) on the last word.
- Names shorter than 4 characters are ignored, except acronyms.
- Headings, code, links, URLs, footnote definitions and reference
  definitions are not scanned.
- Targets the page already links, in the body, a reference definition or a
  relation, are
  skipped, so repeated runs converge to nothing.
- A name used by several pages is reported as ambiguous instead of guessed.

## Candidates, not decisions

All three commands are deterministic: the same bundle gives the same
output, so a result can be checked, compared across runs, and tested. None
of them changes a file.

They do not decide, because the decisions need an understanding of the text:

- Two pages called "Caching" in `web/` and `hardware/` share a name and
  describe different things.
- A mention of "consensus" in a sentence about team meetings should not
  link to the distributed-consensus page.
- An orphan may be a page nobody needs, or one that its parent topic
  should mention.

So the maintain skill gives the candidates to the agent, which reads the
pages and acts: it links a mention where a reader would follow it, relates
distinct pages or records them in `distinct.yaml`, and proposes merges.
Merging deletes a page, so it needs your confirmation; `kb merge` then does
the bookkeeping (links, aliases, sources, indexes).

This design was chosen over purely prompt-based deduplication and
cross-linking, where an LLM scans the wiki on its own. That approach is not
reproducible, costs tokens on every run, and is usually built around
wikilinks. Here the cheap, repeatable part is done by code, and the model's
judgement is spent only on the candidates.
