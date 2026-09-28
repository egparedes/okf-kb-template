"""Tests for `kb fix-links`, `kb mv` and `kb merge`: what they rewrite, what they refuse, all-or-nothing writes."""

from __future__ import annotations

from pathlib import Path

import pytest

from kbtools import check, cli, linkfix, names, rename, retrieval_eval
from test_model import bundle, git, repo, write  # noqa: F401 - fixture

QUESTIONS = """\
# my questions
questions:
  - question: How are names resolved?  # the classic
    expected:
      - /systems/a.md   # keep me
      - /systems/b.md
  - question: Flow style
    expected: [/systems/a.md, /systems/c.md]
"""


def snapshot(repo: Path) -> dict[str, bytes]:
    return {p.relative_to(repo).as_posix(): p.read_bytes() for p in sorted(repo.rglob("*")) if p.is_file()}


# -- what gets rewritten ------------------------------------------------------------------


def test_mv_rewrites_flow_frontmatter_and_reference_definitions(repo: Path) -> None:
    write(repo, "systems/a.md", "A")
    ref = write(
        repo, "data/r.md", "R",
        "See [A][a] and [again][rel].\n\n[a]: /systems/a.md#top\n[rel]: <../systems/a.md> \"title\"\n",
        "sources: [{id: s, resource: /systems/a.md}, {id: t, resource: 'https://x.org'}]  # cited\n"
        "related: [\"[A](../systems/a.md)\"]\n",
    )
    linkfix.move(bundle(repo), "systems/a.md", "systems/net/a.md")
    text = ref.read_text(encoding="utf-8")
    assert "sources: [{id: s, resource: /systems/net/a.md}, {id: t, resource: 'https://x.org'}]  # cited\n" in text
    assert 'related: ["[A](/systems/net/a.md)"]' in text
    assert "[a]: /systems/net/a.md#top\n" in text and '[rel]: </systems/net/a.md> "title"' in text
    assert bundle(repo).by_rel["data/r.md"].frontmatter["sources"][0]["resource"] == "/systems/net/a.md"


def test_fix_links_normalizes_frontmatter_values_and_reference_definitions(repo: Path) -> None:
    write(repo, "systems/a.md", "A")
    write(repo, "sources/x.md", "X")
    ref = write(
        repo, "systems/r.md", "R", "[A][a]\n\n[a]: a.md\n",
        "sources:\n  - id: s  # first\n    resource: ../sources/x.md\n  - id: t\n    resource: https://x.org/a.md\n"
        "flow: {nested: ['[A](a.md)']}\n",
    )
    assert [str(d.rel) for d in linkfix.fix(bundle(repo))] == ["systems/r.md"]
    text = ref.read_text(encoding="utf-8")
    assert "  - id: s  # first\n    resource: /sources/x.md\n" in text
    assert "resource: https://x.org/a.md" in text
    assert "flow: {nested: ['[A](/systems/a.md)']}" in text
    assert "[a]: /systems/a.md\n" in text
    assert linkfix.fix(bundle(repo)) == []


def test_mv_of_an_image_rewrites_links_to_it(repo: Path) -> None:
    (repo / "kb/attachments").mkdir(parents=True)
    (repo / "kb/attachments/net.png").write_bytes(b"\x89PNG")
    ref = write(repo, "systems/a.md", "A", "![n](../attachments/net.png) [png][p]\n\n[p]: /attachments/net.png\n",
                "resource: /attachments/net.png\n")
    assert cli.main(["mv", "kb/attachments/net.png", "attachments/diagrams/network"]) == 0
    assert (repo / "kb/attachments/diagrams/network.png").read_bytes() == b"\x89PNG"
    text = ref.read_text(encoding="utf-8")
    assert text.count("/attachments/diagrams/network.png") == 3 and "net.png" not in text


@pytest.mark.parametrize("new", ["data", "data/", "new/"])
def test_mv_into_a_folder_keeps_the_name(repo: Path, new: str) -> None:
    write(repo, "systems/a.md", "A")
    write(repo, "data/b.md", "B")
    linkfix.move(bundle(repo), "systems/a.md", new)
    assert (repo / "kb" / new.strip("/") / "a.md").is_file()


def test_mv_keeps_yaml_anchors_and_tags(repo: Path) -> None:
    write(repo, "systems/a.md", "A")
    write(repo, "systems/b.md", "B")
    ref = write(repo, "data/r.md", "R", extra=(
        "sources:\n  - id: s\n    resource: &r ../systems/a.md\n  - id: t\n    resource: *r\n"
        "  - id: u\n    resource: !!str ../systems/b.md\n  - id: v\n    resource: !!str &q '../systems/a.md'\n"
    ))
    linkfix.move(bundle(repo), "systems/a.md", "systems/z.md")
    linkfix.move(bundle(repo), "systems/b.md", "systems/y.md")
    text = ref.read_text(encoding="utf-8")
    assert "resource: &r /systems/z.md\n" in text and "resource: *r\n" in text
    assert "resource: !!str /systems/y.md\n" in text and "resource: !!str &q '/systems/z.md'\n" in text
    sources = bundle(repo).by_rel["data/r.md"].frontmatter["sources"]
    assert [s["resource"] for s in sources] == ["/systems/z.md", "/systems/z.md", "/systems/y.md", "/systems/z.md"]


@pytest.mark.parametrize("style", ["|", ">-"])
def test_mv_rewrites_a_block_scalar_as_a_quoted_one(repo: Path, style: str) -> None:
    write(repo, "systems/a.md", "A")
    ref = write(repo, "data/r.md", "R", extra=f"related:\n  - {style}\n    [A](/systems/a.md)\n\ntags2: [x]\n")
    linkfix.move(bundle(repo), "systems/a.md", "systems/z.md")
    assert 'related:\n  - "[A](/systems/z.md)"\n\ntags2: [x]\n' in ref.read_text(encoding="utf-8")
    assert bundle(repo).by_rel["data/r.md"].frontmatter["related"] == ["[A](/systems/z.md)"]


def test_mv_keeps_a_byte_order_mark(repo: Path) -> None:
    write(repo, "systems/a.md", "A")
    ref = write(repo, "data/r.md", "R", "See [A](/systems/a.md).\n")
    ref.write_bytes(b"\xef\xbb\xbf" + ref.read_bytes())
    linkfix.move(bundle(repo), "systems/a.md", "systems/z.md")
    data = ref.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf---\n") and b"(/systems/z.md)" in data and data.count(b"\xef\xbb\xbf") == 1


def test_mv_keeps_crlf_line_ends(repo: Path) -> None:
    write(repo, "systems/a.md", "A")
    ref = write(repo, "systems/r.md", "R", "See [A](/systems/a.md).\n")
    ref.write_bytes(ref.read_bytes().replace(b"\n", b"\r\n"))
    linkfix.move(bundle(repo), "systems/a.md", "systems/b.md")
    data = ref.read_bytes()
    assert b"(/systems/b.md)" in data and data.count(b"\r\n") == data.count(b"\n")


def test_merge_rebases_the_old_pages_relative_metadata(repo: Path) -> None:
    write(repo, "sources/x.md", "X")
    write(repo, "systems/peer.md", "Peer")
    write(repo, "systems/old.md", "Old", extra="sources: [{id: x, resource: ../sources/x.md}]\n"
                                              "related: ['[Peer](peer.md)', '[Into](../data/into.md)']\n")
    write(repo, "data/into.md", "Into", "Self [link](../systems/old.md).\n")
    linkfix.merge(bundle(repo), "systems/old.md", "data/into.md", "test/0")
    doc = bundle(repo).by_rel["data/into.md"]
    assert doc.frontmatter["sources"] == [{"id": "x", "resource": "/sources/x.md"}]
    assert doc.frontmatter["related"] == ["[Peer](/systems/peer.md)"]
    assert "Self [link](/data/into.md)." in doc.body


# -- questions.yaml -------------------------------------------------------------------------


def test_mv_renames_expected_pages_and_keeps_comments(repo: Path, capsys: pytest.CaptureFixture) -> None:
    for name in "abc":
        write(repo, f"systems/{name}.md", name.upper())
    questions = repo / retrieval_eval.QUESTIONS
    questions.parent.mkdir(parents=True)
    questions.write_text(QUESTIONS, encoding="utf-8")
    assert cli.main(["mv", "systems/a.md", "systems/z.md"]) == 0
    assert questions.read_text(encoding="utf-8") == QUESTIONS.replace("/systems/a.md", "/systems/z.md")
    assert "updated tools/retrieval-eval/questions.yaml" in capsys.readouterr().out
    assert len(retrieval_eval.load_questions(bundle(repo), questions)) == 2


def test_merge_drops_an_expected_page_the_question_already_has(repo: Path) -> None:
    for name in "abc":
        write(repo, f"systems/{name}.md", name.upper())
    questions = repo / retrieval_eval.QUESTIONS
    questions.parent.mkdir(parents=True)
    questions.write_text(QUESTIONS, encoding="utf-8")
    assert "would update tools/retrieval-eval/questions.yaml" in linkfix.merge(
        bundle(repo), "systems/a.md", "systems/b.md", "test/0", dry_run=True)
    assert questions.read_text(encoding="utf-8") == QUESTIONS
    linkfix.merge(bundle(repo), "systems/a.md", "systems/b.md", "test/0")
    text = questions.read_text(encoding="utf-8")
    assert "keep me" not in text and "# the classic" in text and "      - /systems/b.md\n" in text
    assert "expected: [/systems/b.md, /systems/c.md]" in text
    assert [q.expected for q in retrieval_eval.load_questions(bundle(repo), questions)] == [
        ["/systems/b.md"], ["/systems/b.md", "/systems/c.md"]]


# -- what gets refused -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("../outside.md", "systems/o.md", "outside the bundle"),
        ("log.md", "systems/log-2.md", "cannot be moved"),
        ("systems/index.md", "systems/i.md", "cannot be moved"),
        (".obsidian/app.md", "systems/app.md", "not a file of the bundle"),
        ("systems/missing.md", "systems/m.md", "not a file of the bundle"),
        ("systems/a.md", "systems/index.md", "reserved"),
        ("systems/a.md", "log", "reserved"),
        ("systems/a.md", ".trash/a.md", "hidden folder"),
        ("systems/a.md", "../a.md", "outside the bundle"),
        ("systems/a.md", "systems/b.md", "already exists"),
        ("systems/a.md", "systems", "already exists"),
        ("systems/a.md", "systems/a.md", "already exists"),
        ("systems/a.md", "systems/a.txt", "keep the file extension"),
        ("systems/a.md", "releases/v1.2", "end the path with `/`"),
        ("systems/a.md", "", "give a new path"),
        ("systems/a.md", "/", "give a new path"),
        ("systems/a.md", ".", "give a new path"),
        ("systems/a.md", "systems/b.md/c.md", "is a file"),
        ("attachments/x.png", "attachments/x.md", "keep the file extension"),
    ],
)
def test_mv_refuses(repo: Path, old: str, new: str, message: str) -> None:
    write(repo, "systems/a.md", "A")
    write(repo, "systems/b.md", "B")
    (repo / "kb/systems/index.md").write_text("# Systems\n")
    (repo / "kb/log.md").write_text("# Log\n")
    (repo / "kb/.obsidian").mkdir()
    (repo / "kb/.obsidian/app.md").write_text("x")
    (repo / "kb/attachments").mkdir()
    (repo / "kb/attachments/x.png").write_bytes(b"png")
    (repo / "outside.md").write_text("---\ntype: Concept\n---\n")
    before = snapshot(repo)
    with pytest.raises(SystemExit, match=message):
        linkfix.move(bundle(repo), old, new)
    assert snapshot(repo) == before


def test_mv_refuses_a_destination_git_ignores(repo: Path) -> None:
    write(repo, "systems/a.md", "A")
    (repo / ".gitignore").write_text("kb/private/\n")
    git(repo, "init", "-q")
    with pytest.raises(SystemExit, match="git ignores"):
        linkfix.move(bundle(repo), "systems/a.md", "private/a.md")
    linkfix.move(bundle(repo), "systems/a.md", "public/a.md")
    assert (repo / "kb/public/a.md").is_file()


@pytest.mark.parametrize("args", [("attachments/x.png", "systems/b.md"), ("systems/a.md", ".trash/b.md")])
def test_merge_refuses_files_that_are_not_pages_of_the_bundle(repo: Path, args: tuple[str, str]) -> None:
    write(repo, "systems/a.md", "A")
    write(repo, "systems/b.md", "B")
    write(repo, ".trash/b.md", "B")
    (repo / "kb/attachments").mkdir()
    (repo / "kb/attachments/x.png").write_bytes(b"png")
    with pytest.raises(SystemExit, match="not a page in the bundle"):
        linkfix.merge(bundle(repo), *args, "test/0")


# -- all or nothing -----------------------------------------------------------------------------


def _bundle_with_links(repo: Path) -> None:
    write(repo, "systems/a.md", "A", "Peer [B](b.md).\n")
    write(repo, "systems/b.md", "B")
    for name in ("c", "d", "e"):
        write(repo, f"data/{name}.md", name.upper(), "See [A](/systems/a.md).\n", 'related: ["[A](/systems/a.md)"]\n')
    questions = repo / retrieval_eval.QUESTIONS
    questions.parent.mkdir(parents=True)
    questions.write_text(QUESTIONS, encoding="utf-8")


def _fail_on(monkeypatch: pytest.MonkeyPatch, call: int) -> None:
    real, calls = linkfix._replace, []

    def flaky(src: Path, dst: Path) -> None:
        calls.append(dst)
        if len(calls) == call:
            raise OSError(28, "No space left on device")
        real(src, dst)

    monkeypatch.setattr(linkfix, "_replace", flaky)


@pytest.mark.parametrize("call", [1, 3, 5])
def test_mv_failing_midway_changes_nothing(repo: Path, monkeypatch: pytest.MonkeyPatch, call: int) -> None:
    _bundle_with_links(repo)
    before = snapshot(repo)
    _fail_on(monkeypatch, call)
    with pytest.raises(SystemExit, match="No space left on device.*nothing was changed"):
        linkfix.move(bundle(repo), "systems/a.md", "net/deep/a.md")
    assert snapshot(repo) == before
    assert not (repo / "kb/net").exists() and not any((repo / linkfix.BACKUPS).iterdir())


@pytest.mark.parametrize("call", [1, 2, 4])
def test_merge_failing_midway_changes_nothing(repo: Path, monkeypatch: pytest.MonkeyPatch, call: int) -> None:
    _bundle_with_links(repo)
    before = snapshot(repo)
    _fail_on(monkeypatch, call)
    with pytest.raises(SystemExit, match="nothing was changed"):
        linkfix.merge(bundle(repo), "systems/a.md", "systems/b.md", "test/0")
    assert snapshot(repo) == before


def test_mv_keeps_the_backup_when_undoing_fails(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _bundle_with_links(repo)
    original = (repo / "kb/data/c.md").read_bytes()
    _fail_on(monkeypatch, 3)

    def broken(copy: Path, path: Path) -> None:
        raise OSError(5, "I/O error")

    monkeypatch.setattr(linkfix, "_restore", broken)
    with pytest.raises(SystemExit, match="could not undo every step") as raised:
        linkfix.move(bundle(repo), "systems/a.md", "systems/z.md")
    backup = next((repo / linkfix.BACKUPS).iterdir())
    assert str(backup) in str(raised.value)
    manifest = (backup / "MANIFEST").read_text(encoding="utf-8")
    kept = next(line.split("\t")[0] for line in manifest.splitlines() if line.endswith("data/c.md"))
    assert (backup / kept).read_bytes() == original


def test_successful_mv_and_merge_leave_no_backup_or_temporary_files(repo: Path, capsys: pytest.CaptureFixture) -> None:
    _bundle_with_links(repo)
    assert cli.main(["mv", "systems/a.md", "systems/z.md"]) == 0
    assert cli.main(["merge", "systems/z.md", "systems/b.md", "--by", "test/0"]) == 0
    out = capsys.readouterr().out
    assert "wrote kb/systems/index.md" in out and "updated links in kb/data/c.md" in out
    assert not any((repo / linkfix.BACKUPS).iterdir())
    assert not [p for p in (repo / "kb").rglob("*") if p.name.endswith(".tmp")]
    assert "(/systems/b.md)" in (repo / "kb/data/e.md").read_text(encoding="utf-8")


def test_an_interrupted_backup_leaves_nothing_behind(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _bundle_with_links(repo)
    before = snapshot(repo)
    real, calls = linkfix.shutil.copy2, []

    def interrupted(src, dst):
        calls.append(src)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return real(src, dst)

    monkeypatch.setattr(linkfix.shutil, "copy2", interrupted)
    with pytest.raises(KeyboardInterrupt):
        linkfix.move(bundle(repo), "systems/a.md", "systems/z.md")
    monkeypatch.undo()
    assert not any((repo / linkfix.BACKUPS).iterdir())
    assert {k: v for k, v in snapshot(repo).items() if not k.startswith(linkfix.BACKUPS)} == before


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("questions:\n  - question: q\n    expected:\n      - /a.md\n      - /a.md  # again\n      - /c.md\n",
         "questions:\n  - question: q\n    expected:\n      - /z.md\n      - /c.md\n"),
        ("questions:\n  - question: q\n    expected:\n      - /a.md\n      - /z.md\n      - /a.md\n",
         "questions:\n  - question: q\n    expected:\n      - /z.md\n"),
        ("questions:\n  - {question: q, expected: [/a.md, /c.md, /a.md]}\n",
         "questions:\n  - {question: q, expected: [/z.md, /c.md]}\n"),
        ("questions:\n  - {question: q, expected: [/c.md, '/a.md']}\n",
         "questions:\n  - {question: q, expected: [/c.md, '/z.md']}\n"),
    ],
)
def test_every_expected_entry_of_a_page_is_renamed(tmp_path: Path, text: str, expected: str) -> None:
    path = tmp_path / "questions.yaml"
    path.write_text(text, encoding="utf-8")
    assert linkfix._question_edits(path, "/a.md", "/z.md") == expected


def test_kebab_has_one_definition() -> None:
    assert check.KEBAB is names.KEBAB is rename.KEBAB
