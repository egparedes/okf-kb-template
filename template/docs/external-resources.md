# External resources

PDFs, slides, archived web pages and other binary or bulky material stay in
their system of record. The knowledge base keeps pointers, and the `kb` CLI
resolves them on demand into `.cache/sources/` (gitignored):

| Kind | Pointer in frontmatter | Resolved through |
|---|---|---|
| Zotero item | `zotero: { key: ABCD2345, citekey: williams2009roofline }` on Source pages | the Zotero local API, then the web API, then a read-only snapshot of the database plus the `.zotero-ft-cache` files |
| Web article | the page's `resource` URL | KaraKeep, looked up by URL |
| File in a synced or local folder | `locators: ["file:<root>/<path>"]` | the root's local path on this machine |

Settings live in two places:

- **`schema/resources.yaml` (committed):** the file roots, deny patterns, and
  your Zotero user id for the web API.
- **`.env` (gitignored; copy `.env.example`):** secrets, machine paths, and
  deny patterns that would reveal sensitive names (`KB_DENY`).
  - Agents are told never to read it, and Claude Code's Read tool is denied
    it.
  - A shell command could still print it, so keep only what this checkout
    needs.
  - The `kb` tooling reads it itself.

## Zotero

1. In Zotero, open Settings → Advanced and tick **"Allow other
   applications on this computer to communicate with Zotero"**. This is the
   local API. The `kb` tooling only reads; never grant write access if a
   dialog asks for it.
2. Recommended: install **Better BibTeX**, set a citation-key pattern, and
   **pin all keys** so that they never change and sync to zotero.org.
   - The citation key is converted to kebab-case, the **source slug**:
     `hoppeProgressiveMeshes1996` becomes `hoppe-progressive-meshes-1996`.
   - The slug names the Source page (`sources/<slug>.md`) and is the
     `sources[].id` that pages cite as `[^<slug>]`.
   - The exact key stays in `zotero.citekey`.
3. Optional fallback for when Zotero is closed, or on other machines:
   - create a **read-only** API key at zotero.org/settings/keys ("Allow
     library access" only);
   - put it in `.env` as `ZOTERO_API_KEY`;
   - put your numeric user id in `schema/resources.yaml`.

   With Zotero File Storage, the web API also serves full text.
4. Recommended: set `ZOTERO_DATA_DIR` to the Zotero data directory. When
   Zotero is closed and no web key is set, `kb` falls back to a read-only
   snapshot of `zotero.sqlite`, copied to a temporary directory, and reads
   full text from the storage cache.

Commands:

```sh
uv run kb zotero search roofline model           # key, citekey, year, title
uv run kb zotero new-source williams2009roofline # Source page with metadata
uv run kb fetch zotero:williams2009roofline      # full text into .cache/sources/
uv run kb open zotero:ABCD2345                   # select the item in Zotero
```

## KaraKeep

Set `KARAKEEP_URL` (the server address, e.g. `https://cloud.karakeep.app`;
a trailing `/api` or `/api/v1` is accepted too) and `KARAKEEP_API_KEY` in `.env`. The same two settings
work for the hosted service and for a self-hosted instance. Pages never
store bookmark ids, which differ per instance: resolution goes by the page's
`resource` URL. Moving to another instance therefore only changes `.env`.

```sh
uv run kb karakeep save https://example.org/post   # archive it (idempotent)
uv run kb fetch https://example.org/post           # archived text into .cache/sources/
```

## File roots

1. Declare each root once in `schema/resources.yaml`, e.g.
   `talks: My talks - one dated folder per talk.`
2. Map it on each machine in `.env`: `KB_ROOT_TALKS=~/Documents/Talks`.
3. Pages point into it with
   `locators: ["file:talks/[2019.06.12] PASC Minisymposium/slides.pdf"]`.

`kb check` warns about locators whose root is undeclared, and reports an
error for locators that point at denied material.

**Deny patterns:**

- **Scope:** they apply to the *resolved* path, after `..`, `.` and
  symlinks. They also match any parent folder, so `docs/Private` covers
  everything inside it.
- **Syntax:** `*`, `**` and `?` are wildcards. Brackets are literal:
  `bibliography/[Zotero]/**` names the Zotero folder.
- **Case:** matching is case-insensitive on macOS and Windows.
- **Where to put them:** generic patterns go in `schema/resources.yaml`.
  Patterns that would reveal sensitive names go in `KB_DENY` in `.env`,
  separated by `;`.
- Non-text files are converted with `markitdown[all]` (through `uvx` when
  markitdown is not installed).

```sh
uv run kb fetch "file:talks/[2019.06.12] PASC Minisymposium/slides.pdf"   # converted with markitdown
uv run kb open  "file:talks/[2019.06.12] PASC Minisymposium/slides.pdf"
```
