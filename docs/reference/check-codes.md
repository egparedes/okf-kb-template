# Check codes

`kb check` prints one line per problem:

```text
kb/ai/llm-wiki.md:18: H032 `[[Other]]` is a wikilink or embed, not an OKF link; use [text](/path.md)
```

The code's letter gives its kind:

| Prefix | Kind | Effect |
|---|---|---|
| `O` | OKF conformance error. A bundle with any of these is not an OKF v0.2 bundle. | Error: `kb check` exits 1. |
| `H` | House-rule error: the profile this template adds on top of OKF. | Error: `kb check` exits 1. |
| `W` | Warning. OKF tolerates these (broken links, unknown keys), but they usually point at a real problem. | Exit 0, unless `--strict`. |

The Claude Code hooks block on errors only. When `kb check` is given file
paths, it runs only the per-file checks: W050, H040 and H061 need a full
run.

## OKF conformance

| Code | Meaning | Fix |
|---|---|---|
| O001 | The page has no YAML frontmatter, the block is not closed with `---`, the YAML does not parse, or it is not a mapping. | Add or repair the frontmatter. Files that are not pages belong outside `kb/` or in `.cache/`. |
| O002 | The frontmatter has no non-empty `type`. | Add a `type` from `schema/vocabulary.yaml`. |
| O003 | An `index.md` other than the root one has frontmatter, or the root `index.md` has keys other than `okf_version`. | Run `just index`; never edit indexes by hand. |
| O004 | An `index.md` line is neither a heading nor a `* [Title](url) - description` entry. | Run `just index`. |
| O005 | `log.md` has frontmatter, a section heading that is not `## YYYY-MM-DD`, or dates that are not unique and newest first. | Repair the headings; add entries only with `uv run kb log`. |

## House-rule errors

| Code | Meaning | Fix |
|---|---|---|
| H001 | A file or folder name is not kebab-case (a leading `_` or `.` is allowed in folder names only). | Rename with `uv run kb mv`. |
| H010 | The frontmatter does not match the schema, e.g. a missing `title`, `description`, `tags`, `status` or `generated`; a description over 300 characters; a timestamp without a UTC offset; a malformed relation value. The message names the key. | Correct the value. See [page frontmatter](page-frontmatter.md). |
| H011 | The `type` is not in `schema/vocabulary.yaml`. | Use an existing type, or add the type to the vocabulary. |
| H012 | The type is not allowed in this folder. | Move the page with `uv run kb mv`, or change the type's `folders`. |
| H013 | The type requires a key that is missing, e.g. `resource` on a Source page. | Add the key. |
| H020 | A footnote `[^id]` does not match any `sources[].id`. | Add the source to `sources`, or fix the label. |
| H021 | A footnote `[^id]` has no definition. | Add `[^id]: [Title](/sources/<id>.md)` at the end of the page. |
| H030 | A link escapes the bundle (e.g. `../../README.md`). | Link inside `kb/`, or use an external URL. |
| H031 | A relation target is not linked from the body. | Link it in a sentence that explains the relation. |
| H032 | A wikilink or embed (`[[…]]`, `![[…]]`) outside code. | Write `[text](/path.md)`, or `![alt](/path.png)` for images. |
| H040 | An `index.md` is missing or out of date. | Run `just index` (or `just fix`). |
| H060 | A locator points at material that a deny pattern covers. | Remove the locator. |
| H061 | `schema/resources.yaml` has the wrong shape: `roots` not a mapping, `deny` not a list of strings, or `zotero` not a mapping. | Correct the file. |

## Warnings

| Code | Meaning | Fix |
|---|---|---|
| W010 | An unknown frontmatter key. | Fix the typo, or declare the key under `fields` in `schema/vocabulary.yaml`. |
| W020 | A source in `sources` is never cited in the body. | Cite it with `[^id]` where it supports a claim, or remove it. |
| W021 | A source's bundle `resource` (e.g. `/sources/x.md`) does not exist. | Create the Source page, or fix the path. |
| W030 | A link to a page that does not exist. | Nothing, if it marks a wanted page. Fix it if it is a typo. |
| W031 | An internal link is not bundle-absolute. | Run `just fix`. It rewrites links whose target exists; fix the others by hand. |
| W032 | A relation target does not exist. | Create the page, or fix the target. |
| W033 | A reference-style link definition (`[x]: path`). The tooling only follows inline links. | Rewrite it as an inline link `[text](/path.md)`. |
| W040 | The page is past its `stale_after` date. | Re-check it against its sources, update it, refresh `generated`, and move `stale_after` forward. |
| W041 | A `generated.at` or `verified.at` is in the future. | Correct the timestamp (UTC). |
| W050 | A folder has no entry in `schema/taxonomy.yaml`. | Add the folder with a title and description, then run `just index`. |
| W060 | A locator uses a root not declared in `schema/resources.yaml`. | Declare the root under `roots`, or fix the locator. |

## Exit status

| Situation | `kb check` | `kb check --strict` |
|---|---|---|
| No diagnostics | 0 | 0 |
| Warnings only | 0 | 1 |
| Any error | 1 | 1 |

Pages with `type: Template` (Templater templates in `_templates/`) are only
checked for names, the frontmatter schema and the type's placement. Their
bodies hold template code, so links, citations, wikilinks, timestamps,
relations, locators and staleness are not checked.
