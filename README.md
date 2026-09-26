# okf-kb-template

A [Copier](https://copier.readthedocs.io) template for LLM-maintained knowledge
bases built on Karpathy's
[LLM wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
pattern. A generated knowledge base keeps its pages in `kb/`, which is:

- a conformant [Open Knowledge Format v0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md)
  bundle at every commit, and
- optionally an Obsidian vault.

Agents (Claude Code, Codex, Gemini CLI…) compile sources into pages through
three skills: ingest, query and maintain. A small Python CLI, `kb`, keeps the
bundle valid and supports two further jobs:

- **Maintenance analytics:** a link graph that excludes generated index
  hubs, near-duplicate candidates, and unlinked mentions. These are
  deterministic candidates that the agent then judges.
- **External material:** Zotero, KaraKeep and synced file roots, resolved on
  demand so that binary files never enter the repository.

## Use

```sh
copier copy --trust gh:egparedes/okf-kb-template my-kb    # or a local path
cd my-kb && just setup && just ci
```

`--trust` is needed because the template runs two post-copy tasks: it writes
the first `log.md` entry and generates the `index.md` files. Generate from a
**clean, tagged** template: `.copier-answers.yml` records the tag, and
`copier update` needs that tag to exist.

The template repository is private: `copier` then needs git credentials for
GitHub (e.g. `gh auth setup-git`, or use `git@github.com:egparedes/okf-kb-template.git`).
Push tags with the commits (`git push origin main --tags`) so that generated
knowledge bases can record and update to release tags. If you render with
`run_setup=false`, `just setup` generates the indexes afterwards.

To pull later template changes into a knowledge base:

```sh
copier update --trust
```

| Question | Purpose |
|---|---|
| `kb_name`, `kb_title`, `kb_description` | Identity: package name, README and AGENTS.md |
| `owner_id` | Your OKF actor, `human:<id>` (Templater templates, trust rules) |
| `agent_actor` | Default `generated.by` for agents (`KB_ACTOR` in Claude Code) |
| `domains` | Knowledge-domain folders: `{slug: {title, description}}`; `a/b` nests (list `a` too). Only used at creation: afterwards the knowledge base edits `schema/taxonomy.yaml` directly. |
| `obsidian`, `claude_code`, `github_ci` | Optional parts: vault config and templates; hooks and CLAUDE.md; CI |
| `run_setup` | Run the post-copy tasks (needs `uv`) |

## What the template manages and what the knowledge base owns

- **Managed:** the tooling (`tools/kbtools`, tests), the agent layer
  (`AGENTS.md`, `CLAUDE.md`, `.agents/skills`, `.claude/settings.json`),
  `justfile`, pre-commit, CI, `schema/frontmatter.schema.json` and the
  Templater templates. `copier update` merges upstream changes into these files.
- **Owned by each knowledge base:**
  - `schema/vocabulary.yaml`: page types, relations and extra `fields`;
  - `schema/taxonomy.yaml`: folders;
  - `schema/resources.yaml`: file roots, deny patterns, Zotero user id;
  - `README.md`;
  - `kb/log.md` and every page;
  - the Obsidian settings and Bases views.

  They are created once and listed in `_skip_if_exists`.
- The core frontmatter schema is extended from `vocabulary.yaml`: each
  relation key becomes a list of markdown links, and `fields` adds keys. A
  knowledge base therefore adapts types, relations and properties without
  forking managed files.

## Design in brief

- **Links:** standard markdown links with bundle-absolute targets
  (`/folder/page.md`). Wikilinks are not part of OKF. `kb fix-links` and
  `kb mv` keep the links in that form.
- **Generated files:** every `index.md` is generated from frontmatter.
  `log.md` is newest-first and written with `kb log`.
- **Provenance:** `sources` with footnote citations, `generated` and
  `verified` actors (trust tiers), and `status` / `stale_after`.
- **Enforcement:** `kb check` checks OKF conformance plus the house profile.
  It runs from Claude Code hooks, pre-commit and CI, and is cross-checked
  with an independent validator (okf-skills).
- **Search:** tiered: `index.md` plus ripgrep, then frontmatter filters
  (`kb find`), then optional local qmd hybrid search.

## Develop

```sh
uv sync
just test      # renders several configurations and runs each result's checks
just render    # renders defaults into /tmp/okf-kb-preview
```

Tag releases (`v0.1.0`, …). Generated knowledge bases record the tag in
`.copier-answers.yml`, and `copier update` moves between tags.

## Credits

- The workflow follows Andrej Karpathy's LLM wiki pattern.
- The file format follows Google's Open Knowledge Format.
- Independent conformance checks use scaccogatto/okf-skills, pinned and
  fetched at run time.
- The maintenance analytics (`kb graph`, `kb dupes`, `kb unlinked`) are
  inspired by Ar9av/obsidian-wiki and reimplemented deterministically.
- `tools/retrieval-eval/questions.yaml` is a hand-maintained set of
  questions for judging whether a heavier search tier is worth enabling. No
  tool reads it yet.
