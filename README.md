# okf-kb-template

A [Copier](https://copier.readthedocs.io) template for personal knowledge
bases that LLM agents maintain, following Andrej Karpathy's
[LLM wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
pattern. The pages live in one folder of the repository (named after the
knowledge base by default; `kb/` before v0.5.0), which is both a conformant
[Open Knowledge Format v0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md)
bundle and, optionally, an [Obsidian](https://obsidian.md) vault. You work
with a command-line agent (Claude Code, Codex, Gemini CLI) through three
skills: ingest, query and maintain. A small `kb` tool, hooks, pre-commit
and CI keep the bundle valid at every commit.

**Documentation:** <https://egparedes.github.io/okf-kb-template/>
(source in [`docs/`](docs/index.md)).

## Quick start

Requirements: git and [uv](https://docs.astral.sh/uv/); optionally
Obsidian 1.13.7 or later.

```sh
uvx copier copy --trust gh:egparedes/okf-kb-template my-kb
cd my-kb
uv run poe setup              # git init, pre-commit hook, indexes; uv installs the tooling
uv run poe obsidian-setup     # then open my-kb/ with Open folder as vault
claude                        # or codex, or gemini
```

Then ask the agent to ingest a URL. The
[first tutorial](https://egparedes.github.io/okf-kb-template/tutorials/first-knowledge-base/)
explains each step, and `uv run poe` lists the other
[tasks](https://egparedes.github.io/okf-kb-template/reference/tasks/). To
pull later template changes into a knowledge base, run
`uvx copier update --trust` in it.

## Develop

```sh
uv sync
uv run poe test                # renders several configurations and runs each result's checks
uv run poe render [DEST]       # renders the working tree with defaults into DEST (default /tmp/okf-kb-preview)
uv run poe docs-serve          # preview the documentation site on http://localhost:8000
uv run poe docs                # build it into site/ (strict)
```

`uv run poe` lists these tasks; they are defined in `[tool.poe.tasks]` of
`pyproject.toml`.

Tag releases (`v0.1.0`, …) and push the tags with the commits
(`git push origin main --tags`). Generated knowledge bases record the tag
in `.copier-answers.yml`, and `copier update` moves between tags.

## Licence

[MIT-0](LICENSE). Knowledge bases generated from the template carry no
licence obligations for the tooling copied into them. Obsidian plugins are
downloaded from their authors at setup time, not bundled, and keep their
own licences.

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
