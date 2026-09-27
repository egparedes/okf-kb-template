# External resources

## Pointers, not copies

Much of what a knowledge base draws on is bulky or binary: papers and books
as PDFs, slide decks, archived web pages. The template never copies them
into the repository. Each stays in its *system of record*, and pages keep
a pointer that the `kb` tool resolves on demand:

| Material | System of record | Pointer on the page |
|---|---|---|
| Papers, books, reports | Zotero | `zotero: { key, citekey }` |
| Web articles | KaraKeep | the page's `resource` URL |
| Slides, course material, other files | a synced or local folder | `locators: ["file:<root>/<path>"]` |

`kb fetch` extracts the text into `.cache/sources/`, which is gitignored,
so an agent can read it during an ingest; `kb open` opens the original.

Copying the files into the repository, or into Git LFS, was rejected. It
would duplicate libraries that are already organized and synced, and every
PDF would stay in git history forever. The pages themselves are what the
knowledge base contributes; the sources remain one command away.

## Why pointers are stable

Each pointer is chosen so that it survives changes on the other side.

- **Zotero:** the 8-character item key never changes. The Better BibTeX
  citation key is the readable id: pinned, it names the Source page and is
  its citation label. `kb` reads through the local API first, then a
  read-only web API key, then a temporary snapshot of the database with the
  full-text cache, so it works with Zotero closed or on another machine. It
  never writes to Zotero.
- **KaraKeep:** bookmark ids differ between instances, so pages store only
  the URL, and `kb` looks the bookmark up by URL. Moving from the hosted
  service to a self-hosted instance changes two lines of `.env` and no page.
- **Files:** a locator names a *root* and a path inside it. The root is
  declared once in `schema/resources.yaml`, and each machine maps it to its
  own local folder in `.env`. The same page works on a laptop and a
  workstation with different directory layouts.

An MCP server for Zotero is a reasonable way to explore a library
interactively. Ingestion uses the `kb` commands instead, because they are
deterministic and scriptable.

## What is committed and what is local

| Committed (`schema/resources.yaml`) | Local (`.env`) |
|---|---|
| root names and descriptions | the local path of each root |
| generic deny patterns | deny patterns that would reveal sensitive names (`KB_DENY`) |
| the numeric Zotero user id (not a secret) | API keys, the Zotero data directory, the KaraKeep address |

Agents are told never to read `.env`, and Claude Code's `Read` tool is
denied it. The `kb` tool reads it itself.

## Deny rules

A file root often points into a folder that also holds material that must
never reach the knowledge base: personal documents, reviews, credentials.
Deny patterns mark it.

- `kb fetch` and `kb open` refuse denied paths.
- `kb check` reports a locator that points at denied material as an error
  (H060), so such a pointer cannot be committed silently.

The matching rules are chosen so that a mistake errs on the side of
refusing:

- patterns apply to the **resolved** path, after `..`, `.` and symlinks, so
  a path cannot walk around a rule;
- a pattern also matches every **parent** folder, so denying a folder
  denies everything in it;
- matching **ignores case** on every platform;
- brackets are **literal**, so a folder named `[Zotero]` can be denied by
  name.

Some patterns would themselves leak information if committed, because they
name what they protect. Those go in `KB_DENY` in `.env`, which only the
local machine sees. The two lists are combined.

Deny rules are a guard against accidents, not an access-control system. The
stronger measure is to map each root to exactly the folder its description
names, never to a broader parent.
