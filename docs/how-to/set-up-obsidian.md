# Set up Obsidian

This guide applies when you answered *Yes* to the Obsidian question: the
template then configures the knowledge-base folder as a vault. That folder
is named after `kb_name` by default (`kb/` in knowledge bases created before
v0.5.0); below it is `<folder>/`, and `bundle` in the `[tool.kb]` table
of `pyproject.toml` holds its name. You need Obsidian 1.13.7 or later, the
minimum version of the pinned plugins.

!!! important "Open the knowledge-base folder, not the repository root"
    Pages link to each other with bundle-absolute paths such as
    `/ai/llm-wiki.md`. Obsidian resolves a leading `/` against the vault
    root, so the links only work when the vault root is the knowledge-base
    folder.

Obsidian names the vault after the folder. To give the vault another name,
[rename the knowledge-base folder](rename-the-knowledge-base-folder.md)
before you open it in Obsidian: after a rename, Obsidian sees a new vault.

## Run the setup command

```sh
uv run poe obsidian-setup
```

Then, in Obsidian, choose *Open folder as vault* and select `<folder>/`. Later,
`uv run poe obsidian-setup --open` reopens it from the terminal.

`uv run poe obsidian-setup` runs `kb obsidian setup`. It:

1. reads the plugin list in `<folder>/.obsidian/community-plugins.json`;
2. downloads each listed plugin that has a pin in
   `tools/obsidian-plugins.json` from its GitHub release into
   `<folder>/.obsidian/plugins/<id>/` (`main.js`, `manifest.json`, and
   `styles.css` when the plugin has one);
3. verifies the SHA-256 checksum of each file against the pin;
4. reports listed plugins without a pin, which you install from Obsidian;
5. with `--open`, opens the vault through
   `obsidian://open?path=<absolute path of the folder>`. This only works
   for a vault that Obsidian already knows. The first time, use *Open folder
   as vault* and choose `<folder>/`;
6. prints the manual steps below.

The command is idempotent:

- a plugin installed at the pinned version is skipped;
- a newer version, for example one Obsidian updated itself, is kept;
- `--force` installs the pinned version again.

`community-plugins.json` changes only after every download has verified.

Plugin code is never committed. `.gitignore` excludes it, so run the command
again after cloning the repository on another machine.

The default list holds the two required plugins. If one of them is missing
from the list, the command adds it back.

| Plugin | ID | Configure | Role |
|---|---|---|---|
| [Templater](https://github.com/SilentVoid13/Templater) | `templater-obsidian` | Preconfigured, apart from the trigger (below). | Gives new notes valid OKF frontmatter, through the templates in `<folder>/_templates/`. |
| [Better Markdown Links](https://github.com/mnaoumov/obsidian-better-markdown-links) | `better-markdown-links` | Keep "Use leading slash for absolute paths" on (the default). | Writes links in the bundle-absolute `/…` form. |

The output names each plugin, what happened, and its licence. Here the
repository is `~/my-kb` and its knowledge-base folder is `my-kb/`:

```text
templater-obsidian: installed 2.25.1 (Templater, AGPL-3.0)
better-markdown-links: installed 5.1.0 (Better Markdown Links, MIT)

Two steps are left in Obsidian (they are not stored in the vault):
  1. On first open, choose "Trust author and enable plugins".
  2. Settings → Templater → turn on "Trigger Templater on new file creation".
Open my-kb/ as the vault (Open folder as vault), not the repository root.
opening obsidian://open?path=%2Fhome%2Falice%2Fmy-kb%2Fmy-kb (works once Obsidian knows the vault; otherwise use Open folder as vault)
```

## Do the two manual steps

1. **Trust the vault.** On first open, Obsidian asks "Do you trust the
   author of this vault?". Choose **Trust author and enable plugins**. This
   is Obsidian's restricted-mode safety check, and the template deliberately
   does not bypass it.
2. **Turn on the Templater trigger.** Open *Settings → Templater* and turn
   on **Trigger Templater on new file creation**. Templater keeps this
   switch in Obsidian's local storage on each device, not in a vault file,
   so no script can set it. Do it once per device.

The folder templates are already configured in the committed
`<folder>/.obsidian/plugins/templater-obsidian/data.json`: journal notes use
`_templates/journal-entry.md` and every other new note uses
`_templates/knowledge-page.md`. With the trigger on, a blank new note, or a
click on a link to a page that does not exist yet, gets a valid OKF
frontmatter.

## Add optional plugins

Five more plugins are pinned. Add any of them to the list and install them
in one step:

```sh
uv run poe obsidian-setup --add obsidian-front-matter-title-plugin,folder-notes
```

Then configure them by hand in Obsidian:

| Plugin | ID | Settings | Role |
|---|---|---|---|
| [Front Matter Title](https://github.com/snezhig/obsidian-front-matter-title) | `obsidian-front-matter-title-plugin` | Enable it for the file explorer, tabs, graph and search, with the title key `title`. | Shows page titles instead of file names. Many files are called `index.md`. |
| [Folder notes](https://github.com/lostpaul/obsidian-folder-notes) | `folder-notes` | Folder note name: `index`. Do not let it create folder notes automatically: `index.md` files are generated. | Clicking a folder opens its index. |
| [Breadcrumbs](https://github.com/michaelpporter/breadcrumbs) | `breadcrumbs` | Add one edge field per relation key in `schema/vocabulary.yaml`, with `part_of` as "up". | Navigates the typed relations. |
| [Linter](https://github.com/platers/obsidian-linter) | `obsidian-linter` | YAML key sort, priority order: `type, title, description, aliases, resource, author, published, archived, tags, status, generated, verified, stale_after, sources, zotero, locators`, then the relation keys. Leave "lint on save" off for `_templates/`. | Keeps frontmatter tidy. It does not validate; `kb check` does. |
| [Omnisearch](https://github.com/scambier/obsidian-omnisearch) | `omnisearch` | Defaults. | Full-text search in the app. |

`--add` accepts only pinned IDs; for any other ID it stops and lists the
optional plugins. Other plugins you list in `community-plugins.json` by hand
are reported as having no pin: install them from *Settings → Community
plugins → Browse*. Two that work with the bundle are OKF Enforcer
(validation on save, still young) and Tasks.

## What is already configured

The template commits these settings in `<folder>/.obsidian/`. They belong to the
knowledge base: template updates never overwrite them.

| Setting | Value | Why |
|---|---|---|
| Use `[[Wikilinks]]` | off | OKF links are standard markdown links. Typing `[[` still autocompletes, but inserts a markdown link. |
| New link format | Path from vault folder | Better Markdown Links adds the leading `/`. `uv run poe fix` repairs any link written without it. |
| Automatically update internal links | on | Renames inside Obsidian keep links working. `uv run poe fix` restores the `/` form afterwards. |
| Deleted files | Move to system trash | `kb` skips a `.trash/` folder inside the vault, but other OKF readers of the folder would count its files as pages. |
| Properties in document | Source | The Properties editor rewrites the whole YAML block, reordering keys and dropping quotes. Edit frontmatter as text. |
| Default location for new notes | Same folder as current file | |
| Attachment folder | `assets` | |
| Daily notes | `journal/YYYY/YYYY-MM-DD`, template `_templates/journal-entry` | |
| Graph filter | `-file:index.md -file:log.md -path:_templates` | Generated indexes would otherwise be hubs that distort the graph. |
| Core plugins | Bases, Daily notes, Backlinks, Outgoing links, Outline, Page preview, Properties, Bookmarks, Footnotes view, … | Core Templates is off; Templater replaces it. |

`<folder>/_views/` holds three Bases dashboards. Bases files are YAML, not
markdown, so they are outside the bundle:

- `knowledge.base`: every knowledge page by type, plus recent changes;
- `review-queue.base`: unverified pages, drafts and stale pages;
- `sources.base`: ingested sources.

## Write by hand

- **Journal:** open today's daily note. It lands in `journal/YYYY/`.
- **Other pages:** run *Templater: Create new note from template* and pick
  `knowledge-page` or `decision-record`. The template asks for the type,
  title and description, and renames the file to kebab-case.
- **Links:** type `[[` and pick a page (Obsidian writes a markdown link), or
  write `[Title](/folder/page.md)` directly.
- Before committing, run `uv run poe fix` and `uv run poe check`. The
  pre-commit hook runs them too.

Pages you write are signed `human:<your id>` in `generated.by`. The id is
set in the templates from the `owner_id` question.

## Clip web pages with Web Clipper

[Obsidian Web Clipper](https://obsidian.md/clipper) can create Source pages.
In its template:

- note name: `{{title|kebab}}`; location: `sources/`;
- text properties: `type: Source`, `title`, `description`,
  `resource: {{url}}` and `status: draft`.

Leave out `tags` and `generated`. The Clipper writes text properties as
quoted strings, which `kb check` rejects for those two keys. Then ask your
agent to finish the page with the ingest skill, which adds them. The page
validates only after that, so do not commit it before.

## Plugins that create files without OKF frontmatter

- **Excalidraw:** set its file format to plain `.excalidraw`, not
  `.excalidraw.md`. Files without the `.md` extension are outside the
  bundle. Embed drawings in pages with a markdown image link.
- **Note composer** (extract to a new note): add the frontmatter by hand,
  or run the `knowledge-page` template on the new note.

## Plugins to avoid

- **Wikilink Types**, **Dataview** link fields, **ExcaliBrain**, **Juggl**
  and **Graph Link Types**: they only understand `[[wikilinks]]`, which are
  not part of OKF.
- **Periodic Notes**: unmaintained.
- **Obsidian Git**: commit from the command line or through the agent, so
  that the pre-commit checks run.

## Caveat: Templater runs code

With the trigger on, Templater also runs the `<% … %>` commands in any
*new, non-empty* `.md` file of up to 100 KB that appears in the vault, for
example after a `git pull`. Keep Templater syntax out of pages outside
`_templates/`. `kb check` does not look for it.

## Settings files written on first launch

Obsidian writes more settings files the first time it opens the vault, such
as `appearance.json`, `types.json` and the `data.json` of plugins you
configure. Commit the ones you want on every machine. `.gitignore` keeps
per-device workspace state out, and tracks only the Templater plugin
settings among plugin files. Allow others explicitly in `.gitignore` after
checking that they hold no API keys.
