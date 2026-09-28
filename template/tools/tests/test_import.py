"""Tests for `kb import` (Obsidian vaults and Logseq graphs)."""

from __future__ import annotations

import os
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
    if os.name != "nt":  # Windows has no executable bit
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
    (root / "a" / "note!.md").write_text("Two.\n")  # the same slug from another name, on any file system
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
    assert importer.slug("Cartesian GT4Py") == "cartesian-gt4py"
    assert importer.slug("C++ & Écoles") == "cpp-ecoles"
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


# -- v0.7.0: safety and correctness ---------------------------------------------


@pytest.fixture
def case_sensitive_fs(tmp_path: Path) -> bool:
    """True when the file system of tmp_path tells `a` from `A` (Linux; not macOS or Windows by default)."""
    probe = tmp_path / "case-probe"
    probe.write_text("")
    sensitive = not (tmp_path / "CASE-PROBE").exists()
    probe.unlink()
    return sensitive


def symlink(link: Path, target: Path) -> None:
    """Create a symlink, or skip the test where the platform or user cannot (Windows without privileges)."""
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symbolic links unavailable: {exc}")


def test_symlinks_in_the_source_are_never_followed(repo, tmp_path, monkeypatch, capsys) -> None:
    secret = tmp_path / "secret"
    (secret / "dir").mkdir(parents=True)
    (secret / "secret.txt").write_text("TOKEN")
    (secret / "note.md").write_text("Secret note text here.\n")
    (secret / "dir" / "inner.md").write_text("Inner secret note.\n")
    mapping = BASIC + "exclude: ['private/**']\nfiles:\n  - match: '**'\n    to: '{dir}/{name}'\n    kebab: false\n"
    root = tmp_path / "vault2"
    (root / "private").mkdir(parents=True)
    symlink(root / "leak.txt", secret / "secret.txt")
    symlink(root / "linked.md", secret / "note.md")
    symlink(root / "folder", secret / "dir")
    symlink(root / "private" / "hidden.txt", secret / "secret.txt")
    assert import_vault(repo, tmp_path, {"ok.md": "See [[linked]] and [x](leak.txt).\n"}, mapping, monkeypatch) == 0
    out = capsys.readouterr().out
    assert "leak.txt: symbolic link: not followed" in out and "folder: symbolic link: not followed" in out
    assert "private/hidden.txt: excluded by the mapping" in out and "hidden.txt: symbolic" not in out
    written = {p.relative_to(repo / "kb").as_posix() for p in (repo / "kb").rglob("*") if p.is_file() and p.name != "index.md"}
    assert written == {"log.md", "systems/old/ok.md"}
    assert "TOKEN" not in (repo / "kb/systems/old/ok.md").read_text()


def test_a_file_that_becomes_a_symlink_is_not_read(tmp_path) -> None:
    (tmp_path / "secret.txt").write_text("TOKEN")
    symlink(tmp_path / "a.md", tmp_path / "secret.txt")
    plan = importer.Plan(source=tmp_path, into="", mapping=None)  # type: ignore[arg-type]
    with pytest.raises(OSError, match="became a symbolic link"):
        importer._open_source(plan, importer.Item(src="a.md"))


def test_unreadable_folders_are_reported(repo, tmp_path, monkeypatch, capsys) -> None:
    real_walk = importer.os.walk

    def walk(top, onerror=None):  # an unreadable folder, the same way on every platform and user
        for folder, dirs, files in real_walk(top):
            if "locked" in dirs:
                dirs.remove("locked")
                onerror(PermissionError(13, "Permission denied", str(Path(folder) / "locked")))
            yield folder, dirs, files

    monkeypatch.setattr(importer.os, "walk", walk)
    files = {"ok.md": "Text here.\n", "locked/x.md": "Hidden.\n"}
    assert import_vault(repo, tmp_path, files, BASIC, monkeypatch, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "locked: folder not readable: Permission denied" in out and "locked/x.md" not in out


def test_comments_never_reach_the_description(repo, tmp_path, monkeypatch) -> None:
    files = {
        "a.md": "Public text %%my private remark%% continues here. More.\n",
        "b.md": "<!-- hidden -->\nVisible <!-- secret --> sentence goes here.\n",
        "c.md": "---\ntitle: T %%secret%% <!-- also -->\n---\n%%\nmulti-line private\n%%\nThe real first sentence.\n",
    }
    assert import_vault(repo, tmp_path, files, BASIC, monkeypatch) == 0
    assert page(repo, "systems/old/a.md").frontmatter["description"] == "Public text continues here."
    assert page(repo, "systems/old/b.md").frontmatter["description"] == "Visible sentence goes here."
    assert page(repo, "systems/old/c.md").frontmatter["description"] == "The real first sentence."
    assert page(repo, "systems/old/c.md").frontmatter["title"] == "T"
    index = (repo / "kb/systems/old/index.md").read_text()
    assert "secret" not in index and "private" not in index and "also" not in index


def test_exclude_ignores_case(repo, tmp_path, monkeypatch, capsys) -> None:
    mapping = BASIC + "exclude: ['private/**']\n"
    files = {"Private/x.md": "Secret text here.\n", "pub.md": "Public text.\n"}
    assert import_vault(repo, tmp_path, files, mapping, monkeypatch, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "Private/x.md: excluded by the mapping" in out and "pub.md -> " in out


FILES_AS_IS = BASIC + "files:\n  - match: '**'\n    to: '{dir}/{name}'\n    kebab: false\n"


def files_to(template: str) -> str:
    return BASIC + f"files:\n  - match: '**'\n    to: '{template}'\n    kebab: false\n"


@pytest.mark.parametrize(("files", "mapping", "message"), [
    ({"a.txt": "file", "a/y.png": "PNG"}, files_to("{path}"), "is also the folder of a/y.png's destination"),
    ({"one/Data.txt": "1", "two/data.txt": "2"}, files_to("out/{stem}"), "differ only in case"),  # distinct sources
    ({"one/Data.txt": "1", "two/data.txt": "2"}, files_to("out/{parent}-{stem}"), None),
    ({"Note.md": "One.\n", "sub/N.md": "Two.\n"}, FILES_AS_IS, None),
])
def test_destination_collisions_by_case_and_folder(repo, tmp_path, monkeypatch, capsys, files, mapping, message) -> None:
    code = import_vault(repo, tmp_path, files, mapping, monkeypatch, "--dry-run")
    out = capsys.readouterr().out
    if message is None:
        assert code == 0
    else:
        assert code == 1 and message in out


def test_existing_files_block_folders_and_case_twins(repo, tmp_path, monkeypatch, capsys, case_sensitive_fs) -> None:
    (repo / "kb/systems/old").mkdir(parents=True)
    (repo / "kb/systems/old/x").write_text("a file")
    (repo / "kb/systems/old/Twin.md").write_text("existing")
    files = {"x/y.md": "Text here.\n", "twin.md": "Text here.\n"}
    assert import_vault(repo, tmp_path, files, BASIC, monkeypatch, "--dry-run") == 1
    out = capsys.readouterr().out
    assert "kb/systems/old/x is a file, not a folder" in out
    if case_sensitive_fs:
        assert "differs only in case from the existing Twin.md" in out
    else:  # macOS, Windows: the disk itself finds the twin
        assert "kb/systems/old/twin.md already exists" in out


def test_a_failed_write_leaves_nothing_behind(repo, tmp_path, monkeypatch) -> None:
    calls = []
    real_move = importer._move

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) == 3:
            raise OSError("disk full")
        return real_move(src, dst)

    monkeypatch.setattr(importer, "_move", flaky)
    files = {"a/one.md": "One text.\n", "b/two.md": "Two text.\n", "c/three.md": "Three text.\n", "d/pic.png": "PNG"}
    with pytest.raises(SystemExit, match="disk full; nothing was written"):
        import_vault(repo, tmp_path, files, FILES_AS_IS, monkeypatch)
    assert sorted(p.name for p in (repo / "kb").iterdir()) == ["log.md"]
    assert list((repo / ".cache" / "import").iterdir()) == []  # the staging folder is gone too


def test_the_final_move_never_replaces_a_file(tmp_path, monkeypatch) -> None:
    staged, dest = tmp_path / "staged", tmp_path / "dest"
    staged.write_text("new")
    dest.write_text("old")
    with pytest.raises(FileExistsError):
        importer._move(staged, dest)
    monkeypatch.setattr(importer.os, "link", lambda *a: (_ for _ in ()).throw(OSError("no hard links")))
    with pytest.raises(FileExistsError):
        importer._move(staged, dest)
    assert dest.read_text() == "old" and staged.read_text() == "new"
    dest.unlink()
    importer._move(staged, dest)
    assert dest.read_text() == "new" and not staged.exists()


def test_actor_is_validated_and_emitted_safely(repo, tmp_path, monkeypatch) -> None:
    from kbtools.bundle import load_yaml

    for bad in ("a, b: c", "human:Has Space", "nobody", "human:tester\n", "claude-code/[1m]"):
        with pytest.raises(SystemExit, match="is not valid"):
            import_vault(repo, tmp_path, {"a.md": "Text here.\n"}, BASIC, monkeypatch, "--dry-run", "--by", bad)
    assert import_vault(repo, tmp_path, {"a.md": "Text here.\n"}, BASIC, monkeypatch, "--by", "claude-code/claude-opus-5-5[1m]") == 0
    assert page(repo, "systems/old/a.md").frontmatter["generated"]["by"] == "claude-code/claude-opus-5-5"
    text = importer.emit({"type": "Concept"}, "claude-code/opus[1m]", "2024-01-01T00:00:00Z", "Body.")
    fm = load_yaml(text.split("---\n")[1])
    assert fm["generated"] == {"by": "claude-code/opus[1m]", "at": "2024-01-01T00:00:00Z"}
    plain = importer.emit({}, "human:tester", "2024-01-01T00:00:00Z", "")
    assert "generated: { by: human:tester, at: 2024-01-01T00:00:00Z }" in plain


@pytest.mark.parametrize(("extra", "message"), [
    ("properties:\n  d: { relation: related, targt: 'x/{value}.md' }\n", "unknown key(s) targt in `properties.d`"),
    ("properties:\n  d: kept\n", "property `d` must be keep, drop"),
    ("tags: { inlin: ignore }\n", "unknown key(s) inlin in `tags`"),
    ("tags: { inline: nope }\n", "`tags.inline` is `collect` or `ignore`"),
    ("rewrite:\n  - pattern: '(unclosed'\n", "in `rewrite[0].pattern`"),
    ("rewrite:\n  - patern: 'x'\n", "unknown key(s) patern in `rewrite[0]`"),
    ("tags: { drop: ['[z-a]'] }\n", "in `tags.drop[0]`"),
    ("description_skip: ['*x']\n", "in `description_skip[0]`"),
    ("max_bytes: lots\n", "`max_bytes` must be a number"),
    ("links: [a]\n", "`links` must be a mapping"),
    ("timestamp: [x]\n", "`timestamp` must be a property name"),
    ("files: { a: b }\n", "`files` must be a list of rules"),
    ("label: [x]\n", "`label` must be a string"),
    ("  - match: 'x/*.md'\n    to: 'x/{stem}.md'\n    type: { from: kind, map: [a] }\n", "`type.map` of rule 'x/*.md' must be a mapping"),
    ("  - match: 'y/*.md'\n    to: 'y/{stem}.md'\n    type: [Concept]\n", "`type` of rule 'y/*.md' must be a type name"),
    ("  - match: [1]\n    to: 'z.md'\n    type: Concept\n", "`match` of rule [1] must be a glob"),
])
def test_nested_mapping_mistakes_name_the_key(repo, tmp_path, monkeypatch, extra, message) -> None:
    with pytest.raises(SystemExit) as exc:
        import_vault(repo, tmp_path, {"a.md": "Text here.\n"}, BASIC + extra, monkeypatch, "--dry-run")
    assert message in str(exc.value)


def test_type_spec_keys_are_checked(repo, tmp_path, monkeypatch) -> None:
    mapping = BASIC.replace("type: Concept", "type: { form: kind, default: Concept }")
    with pytest.raises(SystemExit, match="unknown key"):
        import_vault(repo, tmp_path, {"a.md": "Text here.\n"}, mapping, monkeypatch, "--dry-run")


def test_tags_block_ids_and_math(repo, tmp_path, monkeypatch) -> None:
    note = (
        "---\ntags: alpha, beta gamma\n---\n"
        "Colour #ff0000 and #0af are no tags, #real is. Math $a #b$ is not.\n\n"
        "$$\nE = x ^n\n$$\n\n"
        "See figure ^fig1\nwhich continues the paragraph.\n\n"
        "Last line of a paragraph ^para-1\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n^table-1\n\n"
        "- item one ^item-1\n- item two\n"
    )
    assert import_vault(repo, tmp_path, {"n.md": note}, BASIC, monkeypatch) == 0
    doc = page(repo, "systems/old/n.md")
    assert doc.frontmatter["tags"] == ["alpha", "beta", "gamma", "real"]
    assert "E = x ^n" in doc.body and "See figure ^fig1\nwhich" in doc.body
    assert "^para-1" not in doc.body and "^table-1" not in doc.body and "^item-1" not in doc.body
    assert "| 1 | 2 |\n\n- item one\n- item two" in doc.body


def test_logseq_block_properties_at_the_top_and_property_wikilinks(repo, tmp_path, monkeypatch) -> None:
    mapping = BASIC + "properties:\n  parts: { relation: related, target: 'devices/{value}.md' }\n"
    files = {
        "logseq.md": "collapsed:: true\nid:: 64b7f0c2-0000-4000-8000-000000000000\n- A block of text here\n",
        "other.md": "# Other page\n\nThe other page.\n",
        "props.md": "---\nsee: '[[Other]]'\nparts: ['[[Other]]', 'Big Box']\n---\nText with links in properties.\n",
    }
    assert import_vault(repo, tmp_path, files, mapping, monkeypatch) == 0
    fm = page(repo, "systems/old/logseq.md").frontmatter
    assert "collapsed" not in fm and "id" not in fm
    fm = page(repo, "systems/old/props.md").frontmatter
    assert fm["see"] == "[Other](/systems/old/other.md)"
    assert fm["related"] == ["[Other page](/systems/old/other.md)", "[Big Box](/systems/old/devices/big-box.md)"]


@pytest.mark.parametrize(("mapping", "message"), [
    (BASIC + "properties:\n  d: { relation: related, target: 'devices/{value}.md' }\n", "value `!!!` gives an empty name"),
    (BASIC.replace("'{dir}/{stem}.md'", "'{stem.nope}.md'"), "is not a valid template"),
    (BASIC.replace("'{dir}/{stem}.md'", "'{0}.md'"), "is not a valid template"),
    (BASIC + "    title: '{stem[99]}'\n", "title template"),
])
def test_bad_values_and_templates_are_plan_errors(repo, tmp_path, monkeypatch, capsys, mapping, message) -> None:
    files = {"a.md": "---\nd: '!!!'\n---\nText here.\n"}
    assert import_vault(repo, tmp_path, files, mapping, monkeypatch, "--dry-run") == 1
    assert message in capsys.readouterr().out


def test_each_note_is_read_once_and_history_is_read_once(repo, tmp_path, monkeypatch) -> None:
    import os
    import subprocess

    root = tmp_path / "vault2"
    files = {f"n{i}.md": f"# Note {i}\n\nText {i} links [[n{(i + 1) % 5}]] and ![[p.png]].\n" for i in range(5)}
    files["p.png"] = "PNG"
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    when = "2020-01-02T03:04:05Z"
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x", "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "x"]):
        subprocess.run(["git", *args], cwd=root, env=env, check=True)
    reads, runs = [], []
    real_split, real_run = importer._split_frontmatter, importer.subprocess.run
    monkeypatch.setattr(importer, "_split_frontmatter", lambda text: reads.append(1) or real_split(text))
    monkeypatch.setattr(importer.subprocess, "run", lambda *a, **k: runs.append(k.get("timeout")) or real_run(*a, **k))
    (repo / "imports").mkdir(exist_ok=True)
    (repo / "imports" / "m.yaml").write_text(BASIC)
    monkeypatch.chdir(repo)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    mapping = importer.Mapping.load(repo / "imports" / "m.yaml", None)
    links = dict(mapping.links)
    plan, _ = importer.run(Bundle(repo / "kb", repo), root, "systems/old", mapping, False, None)
    assert plan.errors == [] and len(reads) == 5 and runs == [importer.GIT_TIMEOUT]
    assert mapping.links == links  # the plan resolves links without changing the mapping
    fm = page(repo, "systems/old/n0.md").frontmatter
    assert fm["generated"]["at"] == when and fm["title"] == "Note 0"


def test_slug_is_shared() -> None:
    from kbtools import names, resources

    assert names.slug("C++ & Écoles") == importer.slug("C++ & Écoles") == "cpp-ecoles"
    assert names.slug("C#") == "csharp" and names.slug("!!!") == ""
    assert resources.citekey_slug("smithC++") == "smith-cpp"
