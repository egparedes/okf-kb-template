"""Tests for `kb import` (Obsidian vaults and Logseq graphs)."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from kbtools import importer
from kbtools.bundle import Bundle, parse_document
from kbtools.check import Checker
from kbtools.cli import main

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

MAPPING = """\
label: old-vault
actor: human:tester
timestamp: updated
exclude: ["People/**"]
description_skip: ["^Applies to:"]
links: { Wanted Thing: /systems/thing.md }
notes:
  - match: "Journal/**/*.md"
    to: "/journal/{yyyy}/{date}.md"
    type: Journal Entry
    title: "{date}"
    alias_stem: false
  - match: "devices/*.md"
    to: "devices/{stem}.md"
    type: Concept
  - match: "**/*.md"
    to: "{dir}/{stem}.md"
    type: { from: kind, map: { note: Concept }, default: Concept }
files:
  - match: "scripts/*"
    to: "scripts/{name}"
    kebab: false
properties:
  updated: drop
  kind: drop
  location: drop
  status: drop
  devices: { relation: related, target: "devices/{value}.md" }
tags:
  drop: ["^\\\\d"]
rewrite:
  - pattern: "```dataview\\n.*?```\\n"
    replace: ""
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURES / "schema", tmp_path / "schema")
    shutil.copy(REPO / "schema" / "frontmatter.schema.json", tmp_path / "schema")
    vocabulary = tmp_path / "schema" / "vocabulary.yaml"
    vocabulary.write_text(
        vocabulary.read_text().replace(
            "relations:",
            '  Journal Entry: { plural: Journal Entries, description: A day., folders: ["journal"] }\nrelations:',
        )
    )
    taxonomy = tmp_path / "schema" / "taxonomy.yaml"
    taxonomy.write_text(
        taxonomy.read_text()
        + "  systems/old: { title: Old, description: Imported. }\n"
        + "  systems/old/devices: { title: Devices, description: Machines. }\n"
        + "  systems/old/concepts: { title: Concepts, description: Ideas. }\n"
        + "  systems/old/scripts: { title: Scripts, description: Scripts. }\n"
        + "  systems/old/assets: { title: Assets, description: Attachments. }\n"
    )
    (tmp_path / "kb").mkdir()
    (tmp_path / "kb" / "log.md").write_text("# Update Log\n")
    return tmp_path


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "Old Vault"
    files = {
        ".obsidian/app.json": "{}",
        "Concepts/Halo Exchange.md": (
            "---\nkind: note\nupdated: 2024-05-01\ntags: [hpc, '2024']\nstatus: done\n---\n"
            "# Halo Exchange\n\nApplies to: [[Big Box]].\n\n"
            "Halo exchange copies boundary cells between neighbours. It is #mpi stuff.\n\n"
            "## Details\n\nSee [[Stencil|stencils]], [[Stencil#Width Rules]] and [[#Details]].\n"
            "Also [[Hannes]] and [[Nowhere]] and [[Stencil#^abc123]].\n"
            "![[diagram.png|300]] and ![[Stencil]] and [script](../scripts/run-me.sh).\n"
            "A block with an id ^blk-1\n\n%% private remark %%\n\n"
            "```bash\n# not a heading [[not a link]]\n```\n\n"
            "```dataview\nTASK FROM #x\n```\n"
        ),
        "Concepts/Stencil.md": "A stencil updates a cell from its neighbours.\n\n## Width Rules\n\nText.\n",
        "devices/Big Box.md": "---\ndevices: []\n---\n# Big Box\n\nThe build server in the basement.\n",
        "Guides/Setup.md": (
            "---\ndevices: [big-box]\n---\n# Setting up\n\nApplies to: [Big Box](../devices/Big%20Box.md).\n\n"
            "Install everything [as described](../Concepts/Halo%20Exchange.md#Details).\n"
            "By name: [stencil](Stencil.md), [paper](../unused.pdf), [[Wanted Thing]].\n"
        ),
        "People/Hannes.md": "# Hannes\n\nA colleague.\n",
        "Journal/2024/10/2024-10-14 (Monday).md": "---\nlocation: home\n---\n- Tried Logseq\n",
        "pages/Logseq Page.md": "title:: Logseq Page\ntags:: tools, notes\nalias:: LP\n\n- A bullet about tools here\n  id:: 64b7f0c2-0000-4000-8000-000000000000\n",
        "Top Note.md": "A note at the top of the vault.\n",
        "scripts/run-me.sh": "#!/bin/sh\necho hi\n",
        "diagram.png": "PNG",
        "unused.pdf": "PDF",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / "scripts/run-me.sh").chmod(0o755)
    return root


def run(repo: Path, vault: Path, *extra: str, monkeypatch: pytest.MonkeyPatch) -> int:
    (repo / "imports").mkdir(exist_ok=True)
    (repo / "imports" / "old.yaml").write_text(MAPPING)
    monkeypatch.chdir(repo)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    return main(["import", str(vault), "--into", "systems/old", "--map", "imports/old.yaml", *extra])


def test_dry_run_writes_nothing_and_reports(repo, vault, monkeypatch, capsys) -> None:
    assert run(repo, vault, "--dry-run", monkeypatch=monkeypatch) == 0
    out = capsys.readouterr().out
    assert not (repo / "kb" / "systems").exists()
    assert "Concepts/Halo Exchange.md -> kb/systems/old/concepts/halo-exchange.md  [Concept] Halo Exchange" in out
    assert "People/Hannes.md: excluded by the mapping" in out
    assert "unused.pdf: linked document: add a `files` rule" in out
    assert "`../unused.pdf` points to a file that is not imported" in out
    assert "`[[Hannes]]` points to an excluded note: kept as text" in out
    assert "`[[Nowhere]]` names no file: kept as text" in out
    assert "block reference reduced to a page link" in out
    assert "note embed replaced by a link" in out


def test_import_converts_links_and_frontmatter(repo, vault, monkeypatch) -> None:
    assert run(repo, vault, monkeypatch=monkeypatch) == 0
    kb = repo / "kb"
    halo = parse_document(kb / "systems/old/concepts/halo-exchange.md", kb)
    fm = halo.frontmatter
    assert fm["type"] == "Concept" and fm["title"] == "Halo Exchange" and fm["status"] == "draft"
    assert fm["description"] == "Halo exchange copies boundary cells between neighbours."
    assert fm["tags"] == ["hpc", "mpi"]
    assert fm["status"] == "draft" and "state" not in fm and fm.get("generated")["at"] == "2024-05-01T00:00:00Z"
    body = halo.body
    assert body.lstrip().startswith("Applies to: [Big Box](/systems/old/devices/big-box.md).")
    assert "# Details" in body and "## Details" not in body  # promoted after the title H1 was removed
    assert "[stencils](/systems/old/concepts/stencil.md)" in body
    assert "[Stencil › Width Rules](/systems/old/concepts/stencil.md#width-rules)" in body
    assert "[Details](#details)" in body
    assert "Also Hannes and Nowhere and [Stencil](/systems/old/concepts/stencil.md)." in body
    assert "![diagram](/systems/old/assets/diagram.png)" in body
    assert "[script](/systems/old/scripts/run-me.sh)" in body
    assert "^blk-1" not in body and "<!-- private remark -->" in body
    assert "# not a heading [[not a link]]" in body  # code is untouched
    assert "dataview" not in body
    assert (kb / "systems/old/assets/diagram.png").read_text() == "PNG"
    assert (kb / "systems/old/scripts/run-me.sh").stat().st_mode & 0o111
    assert not (kb / "systems/old/assets/unused.pdf").exists()

    setup = parse_document(kb / "systems/old/guides/setup.md", kb)
    assert setup.frontmatter["title"] == "Setting up"
    assert setup.frontmatter["related"] == ["[Big Box](/systems/old/devices/big-box.md)"]
    assert "[as described](/systems/old/concepts/halo-exchange.md#details)" in setup.body
    assert "[Big Box](/systems/old/devices/big-box.md)" in setup.body
    assert "[stencil](/systems/old/concepts/stencil.md)" in setup.body
    assert "[paper](../unused.pdf)" in setup.body and "[Wanted Thing](/systems/thing.md)" in setup.body

    day = parse_document(kb / "journal/2024/2024-10-14.md", kb)
    assert day.frontmatter["title"] == "2024-10-14" and "location" not in day.frontmatter
    assert "aliases" not in day.frontmatter

    logseq = parse_document(kb / "systems/old/pages/logseq-page.md", kb)
    assert logseq.frontmatter["aliases"] == ["LP"] and logseq.frontmatter["tags"] == ["tools", "notes"]
    assert "id::" not in logseq.body and "title::" not in logseq.text

    assert (kb / "systems/old/top-note.md").is_file()  # an empty {dir} stays under --into

    redirects = (repo / ".cache/import/old-vault-redirects.tsv").read_text()
    assert "Concepts/Halo Exchange.md\t/systems/old/concepts/halo-exchange.md\n" in redirects

    bundle = Bundle(kb, repo)
    errors = [d for d in Checker(bundle).check_all() if d.is_error]
    assert errors == []
    assert not (kb / "systems/old/assets/unused.pdf").exists()


def test_second_run_refuses_to_overwrite(repo, vault, monkeypatch, capsys) -> None:
    assert run(repo, vault, monkeypatch=monkeypatch) == 0
    before = (repo / "kb/systems/old/concepts/stencil.md").read_text()
    assert run(repo, vault, monkeypatch=monkeypatch) == 1
    assert "already exists" in capsys.readouterr().out
    assert (repo / "kb/systems/old/concepts/stencil.md").read_text() == before


def test_collisions_and_reserved_names_are_errors(repo, tmp_path, monkeypatch, capsys) -> None:
    root = tmp_path / "v"
    (root / "a").mkdir(parents=True)
    (root / "a" / "Note.md").write_text("One.\n")
    (root / "a" / "note.md").write_text("Two.\n")
    (root / "index.md").write_text("Home.\n")
    assert run(repo, root, "--dry-run", monkeypatch=monkeypatch) == 1
    out = capsys.readouterr().out
    assert "both map to kb/systems/old/a/note.md" in out
    assert "`index.md` is reserved in OKF" in out


def test_glob_and_kebab_helpers() -> None:
    assert importer.glob_regex("topics/**/*.md").match("topics/a/b/c.md")
    assert importer.glob_regex("**/*.md").match("top.md")
    assert not importer.glob_regex("topics/*.md").match("topics/a/b.md")
    assert importer.glob_regex("[Zotero]/*").match("[Zotero]/x")
    assert importer.kebab("Cartesian GT4Py") == "cartesian-gt4py"
    assert importer.kebab("C++ & Écoles") == "cpp-ecoles"
    assert importer.slugify_heading("5.11 Keys `expire`") == "511-keys-expire"


def import_vault(repo: Path, tmp_path: Path, files: dict[str, str], mapping: str, monkeypatch, *extra: str) -> int:
    root = tmp_path / "vault2"
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (repo / "imports").mkdir(exist_ok=True)
    (repo / "imports" / "m.yaml").write_text(mapping)
    monkeypatch.chdir(repo)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    return main(["import", str(root), "--into", "systems/old", "--map", "imports/m.yaml", *extra])


BASIC = "actor: human:tester\nnotes:\n  - match: '**/*.md'\n    to: '{dir}/{stem}.md'\n    type: Concept\n"


def page(repo: Path, rel: str):
    return parse_document(repo / "kb" / rel, repo / "kb")


def test_code_is_never_changed(repo, tmp_path, monkeypatch) -> None:
    note = (
        "Text %% hidden %% here and 100 percent.\n\n"
        "```bash\nbase=${file%%.*}\ndir=${path%%/*}\n  id:: 64b7f0c2-0000-4000-8000-000000000000\n```\n\n"
        "Inline `a %% b` stays, and so does `[[Link]]`. Growth is r ^2\n"
    )
    assert import_vault(repo, tmp_path, {"n.md": note}, BASIC, monkeypatch) == 0
    body = page(repo, "systems/old/n.md").body
    assert "Text <!-- hidden --> here" in body
    assert "base=${file%%.*}\ndir=${path%%/*}\n  id:: 64b7f0c2" in body
    assert "`a %% b`" in body and "`[[Link]]`" in body and "r ^2" in body


def test_empty_frontmatter_keeps_title_and_body(repo, tmp_path, monkeypatch) -> None:
    note = "---\n---\n# Empty FM\n\nThe first paragraph is here.\n\n---\n\nAfter the rule.\n"
    assert import_vault(repo, tmp_path, {"e.md": note}, BASIC, monkeypatch) == 0
    doc = page(repo, "systems/old/e.md")
    assert doc.frontmatter["title"] == "Empty FM"
    assert doc.frontmatter["description"] == "The first paragraph is here."
    assert "After the rule." in doc.body


def test_written_keys_need_a_rule(repo, tmp_path, monkeypatch, capsys) -> None:
    files = {"s.md": "---\nstatus: done\n---\nText of the note.\n"}
    assert import_vault(repo, tmp_path, files, BASIC, monkeypatch, "--dry-run") == 1
    assert "property `status` would clash" in capsys.readouterr().out
    mapping = BASIC + "properties:\n  status: { rename: state, map: { done: closed } }\n"
    assert import_vault(repo, tmp_path, files, mapping, monkeypatch) == 0
    fm = page(repo, "systems/old/s.md").frontmatter
    assert fm["status"] == "draft" and fm["state"] == "closed"
    for bad in ("generated: keep", "status: keep", "status: { rename: verified }"):
        files = {"g.md": f"---\n{bad.split(':')[0]}: true\n---\nText of the note.\n"}
        assert import_vault(repo, tmp_path, files, BASIC + f"properties:\n  {bad}\n", monkeypatch, "--dry-run") == 1


def test_mapping_mistakes_are_errors_not_tracebacks(repo, tmp_path, monkeypatch, capsys) -> None:
    mapping = "actor: human:t\nnotes:\n  - match: '*.md'\n    to: '{stem}.md'\n    type: Concept\n    title: '{date}'\n"
    assert import_vault(repo, tmp_path, {"README.md": "Text.\n"}, mapping, monkeypatch, "--dry-run") == 1
    assert "placeholder 'date' is not available" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="unknown mapping key"):
        import_vault(repo, tmp_path, {"a.md": "x"}, BASIC + "exlude: []\n", monkeypatch)
    with pytest.raises(SystemExit, match="unknown rule key"):
        import_vault(repo, tmp_path, {"a.md": "x"}, BASIC + "    typ: Concept\n", monkeypatch)
    with pytest.raises(SystemExit, match="needs a `target`"):
        import_vault(repo, tmp_path, {"a.md": "x"}, BASIC + "properties:\n  d: { relation: related }\n", monkeypatch)


def test_paths_names_and_limits(repo, tmp_path, monkeypatch, capsys) -> None:
    mapping = BASIC.replace("'{dir}/{stem}.md'", "'{dir}/{stem}'") + (
        "  - match: 'x'\n    to: 'x'\n    type: Concept\n"
        "files:\n  - match: 'bin/*'\n    to: 'bin/{name}'\n    kebab: false\n  - match: 'big/*'\n    to: 'big/{name}'\n"
        "max_bytes: 10\nunresolved: wanted\ntags: { inline: ignore }\n"
    )
    files = {
        "notes/v1.2 notes.md": "See [[../notes/Other]], [[Other#A#B]], [[Missing Page]] and [s](../bin/My_Script.PY). #tag\n",
        "notes/Other.md": "# Other\n\n# A\n\n## B\n",
        "bin/My_Script.PY": "print()\n",
        "big/blob.png": "x" * 20,
    }
    before = {p: (tmp_path / "vault2" / p) for p in files}
    redirects = tmp_path / "r.tsv"
    assert import_vault(repo, tmp_path, files, mapping, monkeypatch, "--redirects", str(redirects)) == 0
    out = capsys.readouterr().out
    doc = page(repo, "systems/old/notes/v1-2-notes.md")
    assert "[Other](/systems/old/notes/other.md)" in doc.body
    assert "[Other › B](/systems/old/notes/other.md#b)" in doc.body
    assert "[Missing Page](/systems/old/missing-page.md)" in doc.body
    assert "[s](/systems/old/bin/My_Script.PY)" in doc.body
    assert doc.frontmatter["tags"] == []
    assert (repo / "kb/systems/old/bin/My_Script.PY").is_file()
    assert "above max_bytes" in out and not (repo / "kb/systems/old/big").exists()
    assert "notes/Other.md\t/systems/old/notes/other.md" in redirects.read_text()
    assert all(path.read_text() == files[rel] for rel, path in before.items())  # the source is untouched


def test_outside_bundle_and_future_dates(repo, tmp_path, monkeypatch, capsys) -> None:
    bad = BASIC.replace("'{dir}/{stem}.md'", "'/../../{stem}.md'") + "    kebab: false\n"
    assert import_vault(repo, tmp_path, {"a.md": "Text here.\n"}, bad, monkeypatch, "--dry-run") == 1
    assert "outside the bundle" in capsys.readouterr().out
    mapping = BASIC + "timestamp: updated\n"
    files = {"f.md": "---\nupdated: 2999-01-01\n---\nA note from the future.\n"}
    assert import_vault(repo, tmp_path, files, mapping, monkeypatch) == 0
    at = page(repo, "systems/old/f.md").frontmatter["generated"]["at"]
    assert at < "2999" and at.endswith("Z")


def test_logseq_graph(repo, tmp_path, monkeypatch) -> None:
    mapping = (
        "actor: human:t\nnotes:\n"
        "  - match: 'journals/*.md'\n    to: '/journal/{yyyy}/{date}.md'\n    type: Journal Entry\n    title: '{date}'\n"
        "  - match: 'pages/*.md'\n    to: '{stem}.md'\n    type: { from: type, map: { concept: Concept } }\n"
    )
    files = {
        "journals/2023_08_23.md": "- Read about [[aa/bb]] today\n",
        "pages/aa___bb.md": "type:: [[concept]]\nsource:: [[Some Book]]\n\n- A namespaced page body\n",
        "logseq/config.edn": "{}",
    }
    assert import_vault(repo, tmp_path, files, mapping, monkeypatch) == 0
    day = page(repo, "journal/2023/2023-08-23.md")
    assert "[aa/bb](/systems/old/aa-bb.md)" in day.body
    ns = page(repo, "systems/old/aa-bb.md").frontmatter
    assert ns["type"] == "Concept" and ns["title"] == "aa/bb" and ns["source"] == "Some Book"


def test_name_resolution_scales(repo, tmp_path, monkeypatch) -> None:
    files = {f"n/note {i}.md": " ".join(f"[[note {j}]]" for j in range(i, i + 20)) + "\n" for i in range(600)}
    start = time.monotonic()
    assert import_vault(repo, tmp_path, files, BASIC, monkeypatch, "--dry-run") == 0
    assert time.monotonic() - start < 60  # a full scan per link took minutes


def test_name_placeholder_in_a_note_rule(repo, tmp_path, monkeypatch) -> None:
    mapping = BASIC.replace("'{dir}/{stem}.md'", "'{dir}/{name}'")
    assert import_vault(repo, tmp_path, {"a/My Note.md": "Some text here.\n"}, mapping, monkeypatch) == 0
    assert (repo / "kb/systems/old/a/my-note.md").is_file()
