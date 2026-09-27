# Your first knowledge base

In this tutorial you create a knowledge base, open it in Obsidian, let an
agent ingest one web page, ask it a question, and make the first commit.
At the end you have a git repository `my-kb/` with a knowledge-base folder
inside it, also called `my-kb/`, that is a valid Open Knowledge Format
bundle with a few real pages in it.

## 1. Install the prerequisites

| Tool | What it does here | Install |
|---|---|---|
| [git](https://git-scm.com) | Version history of the knowledge base | Your system's package manager |
| [uv](https://docs.astral.sh/uv/) | Runs the Python tooling and Copier; manages the `.venv` | [Installer](https://docs.astral.sh/uv/getting-started/installation/) (see below) |
| [just](https://just.systems) | Runs the short commands (`just setup`, `just check`) | `uv tool install rust-just`, or your package manager |
| [Copier](https://copier.readthedocs.io) | Generates the repository from the template | Nothing to install: `uvx copier` runs it |
| [Obsidian](https://obsidian.md) 1.13.7 or later | Reading and writing by hand (optional) | From obsidian.md |
| A command-line agent | Writes the pages | [Claude Code](https://github.com/anthropics/claude-code), [Codex](https://github.com/openai/codex) or [Gemini CLI](https://github.com/google-gemini/gemini-cli) |

On Linux and macOS, uv installs with:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Check the tools:

```sh
git --version
uv --version
just --version
uvx copier --version
```

git also needs your name and e-mail for commits
(`git config --global user.name …` and `user.email …`), if you have not set
them yet.

## 2. Generate the repository

Run Copier with the template and a destination folder:

```sh
uvx copier copy --trust gh:egparedes/okf-kb-template my-kb
```

`--trust` allows the template to run two commands after copying: one writes
the first entry of the log, `log.md`, the other generates the `index.md`
files.
Without them the new bundle would not be valid.

Copier may first print
`MissingFileWarning: File not found; returning empty dict: .copier-answers.yml`.
It is expected on a first copy (Copier looks for the answers of an earlier
copy, and there is none yet); ignore it.

Copier asks these questions. Press Enter to accept the default shown.

| Question | Example answer |
|---|---|
| Short slug for this knowledge base | `my-kb` |
| Human title | `My Knowledge Base` |
| What this knowledge base covers | `Notes on AI tooling, maintained with LLM agents.` |
| Your id for OKF actors | `alice` (your pages will be signed `human:alice`) |
| Default actor for agent-written pages | `claude-code/claude-opus-5-5` |
| Knowledge-domain folders | see below |
| Folder that holds the knowledge base itself | `my-kb` (the default: the slug) |
| Configure the knowledge-base folder as an Obsidian vault? | `Yes` |
| Add Claude Code settings, hooks and CLAUDE.md? | `Yes` if you use Claude Code |
| Add a GitHub Actions workflow? | `Yes` |
| Run the post-copy tasks? | `Yes` |

The domains are the top-level topic folders of the knowledge-base folder.
The answer is YAML; type it on one line:

```yaml
{ai: {title: AI and machine learning, description: Models, training, evaluation and LLM tooling.}, general: {title: General, description: Knowledge that does not fit a more specific domain yet.}}
```

You can change them later in `schema/taxonomy.yaml`.

The next question names the **knowledge-base folder**: the folder inside
the repository that holds the pages. It is the OKF bundle and the Obsidian
vault, and Obsidian names the vault after it. This tutorial keeps the
default, so the repository `my-kb/` contains a folder `my-kb/`, and every
path below that starts with `my-kb/` is relative to the repository root. If
you choose another name, such as `notes`, read `notes/` wherever the
tutorial says `my-kb/`. The name cannot be one of your domains, such as
`ai`. You can rename the folder later with
[`just rename-bundle`](../how-to/rename-the-knowledge-base-folder.md).

The [Copier questions reference](../reference/copier-questions.md)
describes every question.

Copier lists the files it creates and ends with the two tasks:

```text
 > Running task 1 of 2: uv run --quiet kb log Initialization "Created the knowledge base from okf-kb-template."
logged in my-kb/log.md
 > Running task 2 of 2: uv run --quiet kb index
wrote my-kb/index.md
wrote my-kb/ai/index.md
wrote my-kb/entities/index.md
…
```

## 3. Set up the tooling

```sh
cd my-kb
just setup
```

`just setup` initializes git, installs the Python tooling into `.venv`,
installs the pre-commit hook and regenerates the indexes:

```text
git rev-parse --git-dir >/dev/null 2>&1 || git init -q
uv sync
uv run pre-commit install
pre-commit installed at .git/hooks/pre-commit
uv run --quiet kb index
```

Check the empty bundle:

```sh
just check
```

```text
kb check: 0 error(s), 0 warning(s) in 12 file(s)
```

Look at `my-kb/index.md`. It lists your domains, then the Library folders
(`sources`, `syntheses`, `entities`) and the Personal folders (`projects`,
`journal`). It is generated: you never edit it by hand.

## 4. Open the vault in Obsidian

Skip this step if you answered *No* to the Obsidian question.

```sh
just obsidian-setup
```

The command downloads the two required community plugins, Templater and
Better Markdown Links, into `my-kb/.obsidian/plugins/`, and checks their SHA-256
checksums:

```text
templater-obsidian: installed 2.25.1 (Templater, AGPL-3.0)
better-markdown-links: installed 5.1.0 (Better Markdown Links, MIT)

Two steps are left in Obsidian (they are not stored in the vault):
  1. On first open, choose "Trust author and enable plugins".
  2. Settings → Templater → turn on "Trigger Templater on new file creation".
Open my-kb/ as the vault (Open folder as vault), not the repository root.
```

In Obsidian, choose *Open folder as vault* and select the knowledge-base
folder, `my-kb/my-kb/` (the `my-kb/` folder inside the repository). The
vault appears as "my-kb" in Obsidian's vault switcher.
Later, `just obsidian-setup --open` reopens the vault from the terminal.
Then do the two steps:

1. Obsidian asks **"Do you trust the author of this vault?"**. Choose
   **Trust author and enable plugins**. This is Obsidian's restricted-mode
   safety check; the template does not bypass it.
2. Open *Settings → Templater* and turn on **Trigger Templater on new file
   creation**. Obsidian keeps this switch per device, so no script can set
   it. With it on, every new note gets valid frontmatter.

The vault is the knowledge-base folder, not the repository root. That matters for links: see
[Links and relations](../explanation/links-and-relations.md).

## 5. Ingest a first source

Start your agent from the repository root:

```sh
claude    # or: codex, gemini
```

Ask it to add a web page. Karpathy's description of the pattern this
template follows is a good first source:

> Ingest https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

The agent follows the `kb-ingest` skill. Expect it to:

1. search `my-kb/sources/` for an existing page about the URL;
2. fetch the text into `.cache/sources/` (without KaraKeep configured, it
   fetches the page itself);
3. create a Source page such as `my-kb/sources/karpathy-llm-wiki.md` with a
   summary and key points;
4. create or update the pages the source covers, for example a Concept page
   in `my-kb/ai/`, citing the source with footnotes such as `[^karpathy-llm-wiki]`;
5. run `just fix` and `just check`, and add a line to `my-kb/log.md` with
   `uv run kb log Ingest …`;
6. report the key takeaways and the pages it created or updated.

With Claude Code, hooks check each file as it is written, and the session
cannot end while a page it changed fails `kb check` or the log entry is
missing. See [Agents and hooks](../explanation/agents-and-hooks.md).

Look at the result: in Obsidian, or with `git status` and your editor.
Each new page starts with frontmatter like this:

```yaml
---
type: Concept
title: LLM wiki
description: A knowledge base that an LLM agent compiles from sources into interlinked markdown pages.
tags: [llm, knowledge-management]
status: stable
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-27T12:00:00Z }
sources:
  - id: karpathy-llm-wiki
    resource: /sources/karpathy-llm-wiki.md
    title: LLM Wiki
---
```

## 6. Ask a question

In the same session, ask:

> What does the knowledge base say about how an LLM wiki differs from
> retrieval-augmented generation?

The agent follows the `kb-query` skill: it reads `my-kb/index.md` and the
folder indexes, narrows with `just find` and `rg`, reads the pages, and
answers with links to them and to their sources. It marks anything it adds
from its own knowledge. If the answer draws on three or more pages, it files
it back as a Synthesis page in `my-kb/syntheses/`.

## 7. Check the bundle

Leave the agent and run the full check:

```sh
just check
```

```text
my-kb/ai/llm-wiki.md:21: W030 broken link `/ai/retrieval-augmented-generation.md` (not-yet-written page?)
…
kb check: 0 error(s), 2 warning(s) in 16 file(s)
```

Errors must be fixed. Warnings such as `W030` are allowed: a link to a page
that does not exist yet marks a *wanted page*. The
[check codes reference](../reference/check-codes.md) explains every code.

## 8. Commit

```sh
git add -A
git commit -m "Start the knowledge base"
```

The pre-commit hook runs `kb fix-links`, `kb index` and `kb check` before
the commit is recorded:

```text
kb fix-links (bundle-absolute links).....................................Passed
kb index (regenerate index.md files).....................................Passed
kb check (OKF v0.2 + house rules)........................................Passed
…
```

If a hook changes a file (for example, it regenerates an index), the commit
stops. Run `git add -A` and commit again.

## What you have now

- a git repository whose knowledge-base folder, `my-kb/`, is an OKF v0.2
  bundle and an Obsidian vault;
- a Source page, the pages it fed, and a log entry;
- checks that run on every agent edit, every commit and, once you push to
  GitHub, every push.

Next: [Your first agent session](first-agent-session.md) goes further with
the three skills. To push the repository to GitHub and enable CI, see
[Use CI on GitHub](../how-to/ci-and-github.md).
