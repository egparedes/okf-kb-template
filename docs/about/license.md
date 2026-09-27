# Licence

The template is licensed under the **MIT No Attribution** licence
(MIT-0, [SPDX: MIT-0](https://spdx.org/licenses/MIT-0.html)). The licence
text is in the [`LICENSE`](https://github.com/egparedes/okf-kb-template/blob/main/LICENSE)
file of the repository.

## What it means for a knowledge base you generate

MIT-0 is the MIT licence without its one condition: you do not have to
keep the copyright notice or the licence text in copies. For a generated
knowledge base this means:

- The tooling, skills, agent instructions, schema and configuration copied
  into your repository carry **no licence obligations**. You need not ship
  a licence file, credit the template, or keep any notice.
- You can license your knowledge base, content and copied tooling alike,
  however you want, or not at all, and keep it private or publish it.
- You can modify, fork and redistribute the template itself freely.

Your pages are your own work. The template claims nothing over them.

## Obsidian plugins are licensed separately

`just obsidian-setup` downloads community plugins from their authors'
GitHub releases onto your machine. The template does not contain,
redistribute or relicense any plugin code:

- the template stores only a list of pins (plugin ID, version, SHA-256
  checksums) in `tools/obsidian-plugins.json`;
- the downloaded files in `kb/.obsidian/plugins/<id>/` are excluded by
  `.gitignore`, so they never enter your repository either.

Each plugin keeps its own licence, recorded with its pin:

| Plugin | Licence |
|---|---|
| Templater | AGPL-3.0 |
| Better Markdown Links | MIT |
| Front Matter Title | GPL-3.0 |
| Folder notes | AGPL-3.0 |
| Breadcrumbs | MIT |
| Linter | MIT |
| Omnisearch | GPL-3.0 |

The GPL and AGPL terms mainly concern redistributing the plugin files
yourself, for example by committing them to a public repository. See each
plugin's repository for the authoritative terms.

## Other third-party software

The tooling installs its Python dependencies (PyYAML, jsonschema, pytest,
pre-commit) from PyPI into the knowledge base's `.venv`, under their own
licences. `just validate-okf` downloads the independent validator from
[scaccogatto/okf-skills](https://github.com/scaccogatto/okf-skills) at run
time; it is not part of the template either.
