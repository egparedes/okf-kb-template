# Connect Zotero

Papers, books and reports belong in [Zotero](https://www.zotero.org). The
knowledge base keeps a Source page per item, with a pointer to it, and the
`kb` tool reads the item's metadata and full text on demand. It never writes
to Zotero.

## 1. Enable the local API

In Zotero, open *Settings → Advanced* and tick **Allow other applications
on this computer to communicate with Zotero**. `kb` reads through this
local API while Zotero is running. If a dialog ever asks for write access,
do not grant it.

## 2. Pin citation keys (recommended)

Install [Better BibTeX](https://retorque.re/zotero-better-bibtex/), set a
citation-key pattern, and **pin all keys**, so that they never change and
sync to zotero.org.

The citation key names the Source page. It is converted to kebab-case, the
*source slug*:

| Citation key | Source slug | Source page | Citation in pages |
|---|---|---|---|
| `hoppeProgressiveMeshes1996` | `hoppe-progressive-meshes-1996` | `kb/sources/hoppe-progressive-meshes-1996.md` | `[^hoppe-progressive-meshes-1996]` |

The exact key stays in the page's `zotero.citekey`.

## 3. Set the data directory (recommended)

Add the Zotero data directory to `.env`:

```sh
ZOTERO_DATA_DIR=~/Zotero
```

When Zotero is closed and no web API key is set, `kb` reads a read-only
snapshot of `zotero.sqlite`, copied to a temporary directory, and takes full
text from the storage cache (`.zotero-ft-cache` files).

## 4. Add a web API key (optional)

The web API is a fallback for when Zotero is closed, or on a machine without
Zotero.

1. At [zotero.org/settings/keys](https://www.zotero.org/settings/keys),
   create a key with **Allow library access** only (read-only).
2. Put it in `.env`:

    ```sh
    ZOTERO_API_KEY=…
    ```

3. Put your numeric user id, shown on the same page, in
   `schema/resources.yaml`. It is not a secret:

    ```yaml
    zotero:
      user_id: 1234567
      # group_id: 7654321   # to read a group library instead
    ```

With Zotero File Storage, the web API also serves full text.

`kb` tries the local API first, then the web API, then the database
snapshot.

## 5. Use it

```sh
uv run kb zotero search roofline model           # key, citekey, year, title
uv run kb zotero show williams2009roofline       # the item as JSON
uv run kb zotero new-source williams2009roofline # Source page with metadata, status draft
uv run kb fetch zotero:williams2009roofline      # full text into .cache/sources/
uv run kb open zotero:ABCD2345                   # select the item in Zotero
```

Items are addressed by their 8-character Zotero key (`ABCD2345`) or by
citation key. In practice you ask the agent to "ingest" a paper: the
`kb-ingest` skill runs `kb zotero search`, asks you to add the item to
Zotero if it is missing, then runs `new-source` and `fetch`.

The Source page created by `new-source` carries the pointer:

```yaml
zotero: { key: ABCD2345, citekey: williams2009roofline }
```

## Troubleshooting

- **No results while Zotero is closed:** set `ZOTERO_DATA_DIR`, or a web
  API key and `user_id`.
- **`kb check` reports H010 on `zotero.key`:** the key must be the
  8-character item key, in capitals.

See also: [External resources](../explanation/external-resources.md),
[environment variables](../reference/environment-variables.md).
