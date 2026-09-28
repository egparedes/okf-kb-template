# Your first agent session

This tutorial continues from [Your first knowledge base](first-knowledge-base.md).
You ingest two more sources, look at how the agent folds them into existing
pages, ask a question whose answer is filed back, run a maintenance pass,
and record your own review of a page. As in that tutorial, the
knowledge-base folder is `my-kb/`; if you named it differently, use your
name in the paths below.

You talk to the agent in plain language. The agent decides which workflow
applies from `AGENTS.md`, and each workflow is a skill in `.agents/skills/`:

| You say | Skill | What it produces |
|---|---|---|
| "Ingest …", "add this", "summarize this into the wiki" | `kb-ingest` | A Source page, plus new and updated knowledge pages that cite it |
| "What does the KB say about …?" | `kb-query` | An answer with links and citations; sometimes a Synthesis page |
| "Lint the knowledge base", "health check", "clean up" | `kb-maintain` | Fixes, merges, new links, and a report of what needs you |

## 1. Ingest a source that overlaps the first one

Start the agent in the repository root and give it a second source on a
related topic, for example the
[OKF specification](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md):

> Ingest https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md

Watch step 4 of the skill, *map the impact*. Before writing, the agent
lists every topic the source covers substantively and marks each one
*update* (a page exists) or *create*. An ingest usually touches 5 to 15
pages. The agent integrates new knowledge into the right section of an
existing page rather than appending a block per source.

When the new source contradicts a page, the agent keeps both claims, cites
both, and adds a short **Conflict:** paragraph. It may also add a
`contradicts` relation between two pages.

When it finishes, open the Source page. Its `# Pages updated` section lists
every page the ingest created or changed.

## 2. Review the diff

The agent never commits unless you ask. Review its work as you would review
a colleague's:

```sh
git status --short
git diff my-kb/
```

Things to look at:

- **Citations:** each non-obvious claim ends with a footnote such as
  `[^okf-spec]`, and the footnote links the Source page.
- **Links:** body links are bundle-absolute, such as `[OKF](/ai/okf.md)`.
- **Relations:** a frontmatter key such as `depends_on` lists markdown
  links, and each target is also linked in the body, in a sentence that
  says why.
- **The log:** `my-kb/log.md` has a new line under today's date.

If something is wrong, tell the agent. It fixes the page, and the hooks
check it again: after every edit and shell command that changes a page, and
before the agent stops. Claude Code runs them as soon as you start it. Codex
and Gemini CLI run them when the knowledge base was generated with the
`codex` or `gemini_cli` answer and you approved the project's hooks; see
[Agents and hooks](../explanation/agents-and-hooks.md#codex-and-gemini-cli).

## 3. Ask a question that spans pages

> Compare how the LLM wiki pattern and OKF each handle links between pages.

The answer draws on several pages, so the `kb-query` skill files it back:
the agent creates `my-kb/syntheses/<slug>.md` with `type: Synthesis`, whose
`sources` are the pages it used. The next person, or agent, who asks a
similar question finds the answer in the index.

If you do not want the answer filed, say so. If the knowledge base cannot
answer, the agent says which sources to ingest.

## 4. Run a maintenance pass

After a few ingests, ask:

> Lint the knowledge base.

The agent follows `kb-maintain`. It first runs `uv run poe check` and
`uv run poe health`, which print:

- the report: pages by type, trust tiers, stale pages, uncited pages,
  unused sources, wanted pages and drafts;
- the link graph: central pages, orphans, dead ends and co-link gaps;
- near-duplicate candidates;
- mentions of page titles that are not linked yet.

These are candidates. The agent reads the pages and decides: it links an
orphan from its parent topic, links a mention where a reader would follow
it, and proposes merges. It asks you before it merges two pages. It ends
with a comparison of the report before and after.

You can run the same commands yourself: see
[Maintain the knowledge base](../how-to/maintain-the-knowledge-base.md).

## 5. Record your review

Pages start *unverified*. When you have read a page and checked it against
its sources, tell the agent:

> I reviewed /ai/llm-wiki.md; mark it verified.

The agent adds your review to the frontmatter:

```yaml
verified: { by: human:alice, at: 2026-09-27T15:00:00Z }
```

The page is now *human-reviewed*. `uv run poe report` counts pages per trust tier,
and in Obsidian the `_views/review-queue.base` dashboard lists what is
left to review. The agent never marks its own work as verified. See
[Provenance and trust](../explanation/provenance-and-trust.md).

## 6. Commit

```sh
uv run poe check
git add -A
git commit -m "Ingest the OKF specification; first lint"
```

## What you learned

- The agent picks a skill from what you say; the skill fixes the steps.
- An ingest updates existing pages and records which ones.
- Reusable answers become Synthesis pages.
- Analytics propose, the agent judges, and you confirm merges.
- Reviews are recorded per page, with your id and the time.

Next, connect your own material: [Zotero](../how-to/connect-zotero.md),
[KaraKeep](../how-to/connect-karakeep.md) or
[local files](../how-to/link-local-files.md).
