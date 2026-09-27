# Connect KaraKeep

[KaraKeep](https://karakeep.app) archives web pages. With it connected,
`kb fetch <url>` saves the page in KaraKeep and reads the archived text, so
a Source page stays useful after the original page changes or disappears.
The hosted service and a self-hosted instance work the same way.

## 1. Configure

1. In KaraKeep, create an API key (*Settings → API keys*).
2. Add the server address and the key to `.env`:

    ```sh
    KARAKEEP_URL=https://cloud.karakeep.app
    KARAKEEP_API_KEY=…
    ```

    A trailing `/api` or `/api/v1` in the address is accepted too.

## 2. Use it

```sh
uv run kb karakeep save https://example.org/post   # archive it (does nothing if already saved)
uv run kb fetch https://example.org/post           # archived text into .cache/sources/
```

Archiving runs in the background in KaraKeep. If `fetch` finds no content
yet, wait a moment and run it again.

When you ask the agent to ingest a web page, the `kb-ingest` skill runs
`kb fetch <url>` for you. Without KaraKeep, the agent fetches the page
itself.

## How pages point to KaraKeep

They don't, directly. A page stores its canonical URL in `resource`, and
`kb` finds the bookmark by that URL. Bookmark ids differ between KaraKeep
instances, so they are never stored. Moving to another instance only
changes the two lines in `.env`.

See also: [External resources](../explanation/external-resources.md).
