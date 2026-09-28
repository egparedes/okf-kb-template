# OKF Knowledge Base Template

`okf-kb-template` is a [Copier](https://copier.readthedocs.io) template. It
creates a git repository for a personal knowledge base that LLM agents
maintain, following Andrej Karpathy's
[LLM wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
pattern: you bring sources and questions, and the agent compiles them into
interlinked pages.

The pages live in one folder of the repository, the knowledge-base folder,
which is at the same time:

- an [Open Knowledge Format (OKF) v0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md)
  bundle: plain markdown files with YAML frontmatter that any OKF reader
  can load, valid at every commit;
- an [Obsidian](https://obsidian.md) vault, for reading and writing by hand
  (optional). Obsidian names the vault after the folder, and the folder is
  named after the knowledge base (`my-kb/` below) unless you choose another
  name.

You work with a command-line agent such as
[Claude Code](https://github.com/anthropics/claude-code),
[Codex](https://github.com/openai/codex) or
[Gemini CLI](https://github.com/google-gemini/gemini-cli), from the root of
the repository.

## What you get

- **Three agent workflows** as skills: *ingest* a source, *query* the
  knowledge base with citations, and *maintain* it.
- **A `kb` command line** that validates the bundle, generates the
  `index.md` files, normalizes links, moves and merges pages, and writes the
  log.
- **Enforcement at three points:** agent hooks (Claude Code, and optionally
  Codex and Gemini CLI), a pre-commit hook and
  a GitHub Actions workflow all run `kb check`.
- **Provenance:** every page records who wrote it and when, cites its
  sources in footnotes, and can carry a human review.
- **External material by reference:** Zotero items, KaraKeep bookmarks and
  files in synced folders are resolved on demand and never copied into git.
- **Maintenance analytics:** a link graph, near-duplicate candidates and
  unlinked mentions, which the agent reviews.
- **Imports** from existing Obsidian vaults and Logseq graphs.
- **Obsidian set up by one command:** settings, templates, Bases dashboards
  and pinned community plugins.
- **Updates:** `copier update` brings tooling improvements into an existing
  knowledge base without touching its content.

## Quick start

You need [git](https://git-scm.com) and [uv](https://docs.astral.sh/uv/).
Obsidian 1.13.7 or later is optional.

```sh
uvx copier copy --trust gh:egparedes/okf-kb-template my-kb
cd my-kb
uv run poe setup              # git init, pre-commit hook, indexes; uv installs the tooling
uv run poe obsidian-setup     # then open my-kb/ with Open folder as vault
claude                        # or codex, or gemini
```

Then ask the agent: *"Ingest https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f"*.

The [first tutorial](tutorials/first-knowledge-base.md) walks through these
steps and explains each question and each prompt.

## Where to go next

| If you want to… | Read |
|---|---|
| learn by doing, from an empty directory to a first commit | [Tutorials](tutorials/index.md) |
| do one specific task: connect Zotero, import a vault, update, … | [How-to guides](how-to/index.md) |
| look up a command, a frontmatter key or a check code | [Reference](reference/index.md) |
| understand why it works this way | [Explanation](explanation/index.md) |

The template is licensed [MIT-0](about/license.md). Changes between
releases are in the [changelog](about/changelog.md).
