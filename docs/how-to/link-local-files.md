# Link local files

Slides, PDFs and course material in a synced or local folder stay where
they are. A page points to them with a *locator*, `file:<root>/<path>`, and
`kb` resolves the root to a local path on each machine.

## 1. Declare the root

In `schema/resources.yaml` (committed), add a root name and a description
of exactly what it holds:

```yaml
roots:
  talks: My talks - slides and sources, one dated folder per talk.
```

Root names use lowercase letters, digits and dashes.

## 2. Map it on each machine

In `.env`, set `KB_ROOT_<ROOT>` to the local folder. The name is the root in
upper case, with dashes as underscores:

```sh
KB_ROOT_TALKS=~/Documents/Talks
```

Map each root to exactly the folder its description names, never to a
broader parent folder.

## 3. Point a page at a file

Add a `locators` list to the page's frontmatter, usually on a Source page:

```yaml
locators: ["file:talks/2024-05-conference-talk/slides.pdf"]
```

## 4. Read or open the file

```sh
uv run kb fetch "file:talks/2024-05-conference-talk/slides.pdf"   # text into .cache/sources/
uv run kb open  "file:talks/2024-05-conference-talk/slides.pdf"   # open with the default application
```

`kb fetch` converts non-text files with
[markitdown](https://github.com/microsoft/markitdown). It uses the installed
`markitdown` if there is one, and otherwise runs a pinned version through
`uvx` (`markitdown[all]==0.1.8`; set `KB_MARKITDOWN` in `.env` to choose
another, for example `KB_MARKITDOWN=markitdown[all]==0.1.7`). The converter
runs without the variables that `kb` loaded from `.env` and without API
keys, tokens or passwords from your shell environment, and it is stopped
after 5 minutes.

## Keep private material out: deny patterns

Deny patterns stop `kb fetch` and `kb open` from resolving a path, and make
`kb check` report an error (H060) for a locator that points at denied
material.

- **Generic patterns** go in `schema/resources.yaml`:

    ```yaml
    deny:
      - "documents/Personal/**"
      - "bibliography/[Zotero]/**"
    ```

- **Patterns that would reveal sensitive names** go in `.env`, separated by
  `;`, so they never reach git:

    ```sh
    KB_DENY=talks/*/private-notes*;papers/reviews/**
    ```

How patterns match:

| Rule | Detail |
|---|---|
| What is matched | `kb fetch` and `kb open` check the path both as written and resolved (symlinks included). `kb check` (H060) normalizes `..` and `.` but does not follow symlinks. |
| Parent folders | A pattern also matches every parent folder, so `docs/Private` covers everything inside it. |
| Wildcards | `*` and `**` both match any characters, including `/` (shell-style `fnmatch`); `?` matches one character. Brackets are literal: `bibliography/[Zotero]/**` names a folder called `[Zotero]`. |
| Case | Ignored on every platform. |
| Accents | Compared in the same Unicode form (NFC), so `Café` matches whether the disk stores the `é` as one character or two, as macOS does. |

## What `kb check` reports

| Code | When |
|---|---|
| W060 | A locator uses a root that is not declared in `schema/resources.yaml`. |
| H060 | A locator points at denied material. Remove it. |
| H061 | `schema/resources.yaml` has the wrong shape. |

See also: [External resources](../explanation/external-resources.md),
[environment variables](../reference/environment-variables.md).
