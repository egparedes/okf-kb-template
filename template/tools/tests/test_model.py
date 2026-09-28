"""Tests for the shared page model: markdown scanning, file listing, paths, scope."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from kbtools import bundle as bundle_module
from kbtools import cli, dupes, graph, indexgen, report, unlinked
from kbtools.bundle import Bundle, load_yaml
from kbtools.check import Checker
from kbtools.mdlinks import find_links, footnote_refs, mask_code, ref_defs

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(FIXTURES / "schema", tmp_path / "schema")
    shutil.copy(REPO / "schema" / "frontmatter.schema.json", tmp_path / "schema")
    (tmp_path / "kb").mkdir()
    monkeypatch.setenv("KB_REPO_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write(repo: Path, rel: str, title: str, body: str = "", extra: str = "", type_: str = "Concept") -> Path:
    path = repo / "kb" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntype: {type_}\ntitle: {title}\ndescription: {title} in one sentence.\ntags: [test]\n"
        f"status: stable\ngenerated: {{ by: test/0, at: 2026-09-25T12:00:00Z }}\n{extra}---\n\n{body}",
        encoding="utf-8",
        newline="\n",
    )
    return path


def bundle(repo: Path, tracked_only: bool = False) -> Bundle:
    return Bundle(repo / "kb", repo, tracked_only)


def codes(repo: Path) -> list[str]:
    return [d.code for d in Checker(bundle(repo)).check_all()]


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.org", "-c", "user.name=t", *args], cwd=repo, check=True, capture_output=True
    )


# -- markdown scanning ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "targets"),
    [
        ("See the [alpha\npage](/a.md).", ["/a.md"]),  # a soft line break in the link text
        ("See the [alpha\n\npage](/a.md).", []),  # a blank line ends the paragraph
        ("[![logo](/img.png)](/a.md)", ["/img.png", "/a.md"]),  # an image inside a link
        (r"Not a link: \[x](/a.md).", []),  # escaped bracket
        (r"A link after an escaped backslash: \\[x](/a.md).", ["/a.md"]),
        (r"\![x](/a.md) is a link, not an image.", ["/a.md"]),
        ("`code [x](/a.md)` and [y](/b.md)", ["/b.md"]),
    ],
)
def test_find_links(text: str, targets: list[str]) -> None:
    assert [link.target for link in find_links(text)] == targets


def test_escaped_bang_makes_a_link_not_an_image() -> None:
    assert [link.image for link in find_links(r"\![x](/a.md) ![y](/b.png)")] == [False, True]


@pytest.mark.parametrize(
    ("text", "visible"),
    [
        # a stray backtick stays literal and does not mask the paragraphs after it
        ("Use ` here.\n\nSee [a](/a.md) and `x`.\n", ["[a](/a.md)"]),
        # code spans need a closing run of the same length, in the same paragraph
        ("``a ` b`` then [a](/a.md)", ["[a](/a.md)"]),
        ("`a\nb` [a](/a.md)", ["[a](/a.md)"]),
        # fences inside list items are indented; the closing fence must match
        ("* item\n\n    ~~~\n    [[x]]\n    ~~~\n\n[a](/a.md)\n", ["[a](/a.md)"]),
        ("```\n[[x]]\n~~~\n[[y]]\n```\n[a](/a.md)\n", ["[a](/a.md)"]),
        # an indented code block after a blank line, outside a list
        ("Text.\n\n    [[x]] [b](/b.md)\n\n[a](/a.md)\n", ["[a](/a.md)"]),
        # a fence closes only with a fence indented less than 4 columns deeper than the opening one
        ("```md\n- item\n\n    ```\n    [[x]]\n    ```\n```\n[a](/a.md)\n", ["[a](/a.md)"]),
        # a fence in a list item ends with the item
        ("- a\n\n      ```\n      [[x]]\n- [a](/a.md)\n", ["[a](/a.md)"]),
        # the continuation of a footnote definition is text, a fence there is code
        ("[^1]: First.\n\n    More [a](/a.md).\n\n    ```\n    [[x]]\n    ```\n", ["[a](/a.md)"]),
    ],
)
def test_mask_code(text: str, visible: list[str]) -> None:
    masked = mask_code(text)
    assert [s for s in visible if s in masked] == visible
    assert "[[x]]" not in masked and "[b](/b.md)" not in masked and "[[y]]" not in masked


def test_indented_list_continuation_is_not_code() -> None:
    text = "* item\n\n    continued with [a](/a.md)\n"
    assert [link.target for link in find_links(text)] == ["/a.md"]
    text = "Paragraph\n    still the paragraph [a](/a.md)\n"  # no blank line: not a code block
    assert [link.target for link in find_links(text)] == ["/a.md"]
    text = "Text.[^1]\n\n[^1]: First.\n\n    Continued with [Delta](/general/delta.md).\n"
    assert [link.target for link in find_links(text)] == ["/general/delta.md"]


def test_line_numbers_count_newlines_only() -> None:
    text = "a\u2028b\fc\n[x](/x.md) [^n]\n\n[r]: /r.md\n"
    assert [link.line for link in find_links(text)] == [2]
    assert footnote_refs(text) == [("n", 2)]
    assert [(d.label, d.target, d.line) for d in ref_defs(text)] == [("r", "/r.md", 4)]


# -- documents -------------------------------------------------------------------------


def test_timestamps_stay_strings_with_the_c_loader() -> None:
    assert load_yaml("at: 2026-09-25T12:00:00Z\nd: 2026-01-01\n") == {"at": "2026-09-25T12:00:00Z", "d": "2026-01-01"}


def test_document_model_is_parsed_once(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(repo, "systems/a b.md", "A")
    write(
        repo,
        "systems/c.md",
        "C",
        "See [A](</systems/a b.md>) and [A again](/systems/a%20b.md).",
        extra='related: ["[A](/systems/a%20b.md)", "[A](</systems/a b.md>)", "plain text"]\n',
    )
    b = bundle(repo)
    doc = b.by_rel["systems/c.md"]
    assert doc.masked_body == doc.body  # nothing to mask; computed now, once

    def fail(text: str) -> str:
        raise AssertionError("masked twice")

    monkeypatch.setattr(bundle_module.mdlinks, "mask", fail)
    assert doc.link_targets == {"systems/a b.md"}
    assert [doc.resolve(r) for r in doc.relations(["related"])] == ["systems/a b.md", "systems/a b.md"]
    assert doc.links is doc.links and doc.footnote_refs == [] and doc.ref_defs == []
    found = [d.code for d in Checker(b).check_files([doc])]
    assert "H031" not in found and "W032" not in found


def test_relation_targets_are_percent_decoded(repo: Path) -> None:
    write(repo, "systems/a b.md", "A")
    write(
        repo,
        "systems/c.md",
        "C",
        "See [A](/systems/a%20b.md) because C needs it.",
        extra='depends_on: ["[A](/systems/a%20b.md)"]\n',
    )
    assert graph.analyze(bundle(repo))["relation_edges"] == {"depends_on": 1}
    assert [c for c in codes(repo) if c.startswith(("H03", "W03"))] == []


def test_soft_line_break_link_satisfies_the_relation_rule(repo: Path) -> None:
    write(repo, "systems/a.md", "A")
    write(
        repo,
        "systems/b.md",
        "B",
        "B builds on the [alpha\npage](/systems/a.md).\n",
        extra='depends_on: ["[A](/systems/a.md)"]\n',
    )
    assert "H031" not in codes(repo)


def test_wikilink_in_an_indented_fence_is_not_flagged(repo: Path) -> None:
    write(repo, "systems/a.md", "A", "1. Step:\n   - detail:\n\n     ~~~\n     [[not a link]]\n     ~~~\n")
    assert "H032" not in codes(repo)


def test_frontmatter_with_line_separator_keeps_line_numbers(repo: Path) -> None:
    path = write(repo, "systems/a.md", "A", "Text\n\n[[b]]\n", extra='note: "x\u2028y"\n')
    diagnostics = [d for d in Checker(bundle(repo)).check_all() if d.code == "H032"]
    assert [d.line for d in diagnostics] == [path.read_text(encoding="utf-8").split("\n").index("[[b]]") + 1]


# -- files of the bundle -----------------------------------------------------------------


def test_dot_folders_are_not_part_of_the_bundle(repo: Path) -> None:
    write(repo, "systems/a.md", "A")
    write(repo, ".trash/old.md", "Old", type_="Nope")
    (repo / "kb" / ".obsidian").mkdir()
    (repo / "kb" / ".obsidian" / "x.md").write_text("no frontmatter\n", newline="\n")
    b = bundle(repo)
    assert [str(d.rel) for d in b.documents] == ["systems/a.md"]
    assert not {"H011", "H012", "O001"} & set(codes(repo))


def test_git_listing_skips_ignored_files(repo: Path) -> None:
    git(repo, "init", "-q")
    (repo / ".gitignore").write_text("kb/private/\n", newline="\n")
    write(repo, "systems/a.md", "A", "See [P](/private/p.md) and [N](/systems/new.md).")
    write(repo, "private/p.md", "P", type_="Nope")
    write(repo, "systems/new.md", "N")
    git(repo, "add", ".gitignore", "kb/systems/a.md")
    assert sorted(bundle(repo).files) == ["systems/a.md", "systems/new.md"]
    assert sorted(bundle(repo, tracked_only=True).files) == ["systems/a.md"]
    found = codes(repo)
    assert "H011" not in found and found.count("W030") == 1  # the ignored page does not exist for links
    (repo / "kb" / "systems" / "a.md").unlink()  # tracked, deleted from disk
    assert sorted(bundle(repo).files) == ["systems/new.md"]


def test_bundle_ignored_by_an_enclosing_repository_is_read_from_disk(repo: Path) -> None:
    git(repo, "init", "-q")
    (repo / ".gitignore").write_text("*\n", newline="\n")
    write(repo, "systems/a.md", "A", "See [B](/systems/b.md).")
    assert sorted(bundle(repo).files) == ["systems/a.md"]
    assert codes(repo).count("W030") == 1  # checked, not passed vacuously


def test_tracked_outside_git_warns(repo: Path, capsys: pytest.CaptureFixture) -> None:
    write(repo, "systems/a.md", "A")
    assert sorted(bundle(repo, tracked_only=True).files) == ["systems/a.md"]
    assert "--tracked" in capsys.readouterr().err


def test_tracked_option_checks_and_indexes_what_a_commit_contains(repo: Path, capsys: pytest.CaptureFixture) -> None:
    git(repo, "init", "-q")
    write(repo, "systems/a.md", "A")
    (repo / "kb" / "systems" / "draft.md").write_text("an untracked note without frontmatter\n", newline="\n")
    git(repo, "add", "kb/systems/a.md")
    assert cli.main(["check"]) == 1  # the working tree: the draft is an O001
    assert cli.main(["--tracked", "index"]) == 0
    assert "draft" not in (repo / "kb/systems/index.md").read_text(encoding="utf-8")
    git(repo, "add", "kb")
    capsys.readouterr()
    assert cli.main(["--tracked", "check"]) == 1  # staged now: part of the commit
    assert "O001" in capsys.readouterr().out
    git(repo, "rm", "-q", "--cached", "kb/systems/draft.md")
    assert cli.main(["--tracked", "check"]) == 0


def test_git_listing_of_a_bundle_named_like_a_pathspec(repo: Path) -> None:
    git(repo, "init", "-q")
    (repo / "kb").rename(repo / "[kb]")
    b = Bundle(repo / "[kb]", repo)
    (b.root / "systems").mkdir()
    (b.root / "systems" / "a.md").write_text("x", newline="\n")
    (repo / "k.md").write_text("x", newline="\n")
    assert b.files == {"systems/a.md"}


def test_existence_is_case_exact(repo: Path) -> None:
    write(repo, "systems/Foo.md", "Foo")
    write(repo, "systems/b.md", "B", "See [f](/systems/foo.md) and [F](/systems/Foo.md) and [s](/systems/).")
    b = bundle(repo)
    assert b.exists("systems/Foo.md") and b.exists("systems") and b.exists("") and not b.exists("systems/foo.md")
    assert codes(repo).count("W030") == 1


@pytest.mark.parametrize(
    ("arg", "rel"),
    [
        ("./systems/a.md", "systems/a.md"),
        ("systems//a.md", "systems/a.md"),
        ("systems\\a.md", "systems/a.md"),
        ("/kb/systems/./a.md", "systems/a.md"),
        ("systems/x/../a.md", "systems/a.md"),
        ("kb\\systems\\a.md", "systems/a.md"),
    ],
)
def test_path_arguments_are_normalized(repo: Path, arg: str, rel: str) -> None:
    write(repo, "systems/a.md", "A")
    assert bundle(repo).rel(arg) == rel


@pytest.mark.parametrize("arg", ["../x.md", "systems/../../x.md", "..", "kb/../../x.md"])
def test_path_arguments_cannot_leave_the_bundle(repo: Path, arg: str) -> None:
    with pytest.raises(SystemExit, match="outside the bundle"):
        bundle(repo).rel(arg)


def test_mv_with_unnormalized_paths_rewrites_links(repo: Path, capsys: pytest.CaptureFixture) -> None:
    write(repo, "systems/a.md", "A")
    write(repo, "systems/b.md", "B", "See [A](/systems/a.md).")
    assert cli.main(["mv", "./systems//a.md", "systems\\c.md"]) == 0
    assert "(/systems/c.md)" in (repo / "kb/systems/b.md").read_text(encoding="utf-8")
    assert "updated links in kb/systems/b.md" in capsys.readouterr().out


# -- kb check FILE -------------------------------------------------------------------------


def test_check_of_one_file_reads_only_that_file(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    for i in range(5):
        write(repo, f"systems/p{i}.md", f"P{i}", f"See [next](/systems/p{i + 1}.md).")
    parsed = []
    real = bundle_module.parse_document
    monkeypatch.setattr(bundle_module, "parse_document", lambda path, root: parsed.append(path) or real(path, root))
    assert cli.main(["check", "kb/systems/p0.md"]) == 0
    assert len(parsed) == 1
    assert "in 1 file(s)" in capsys.readouterr().err
    cli.main(["check", "kb/systems/p4.md"])
    assert "W030 broken link `/systems/p5.md`" in capsys.readouterr().out


# -- indexes --------------------------------------------------------------------------------


def test_orphaned_index_is_reported_and_deleted(repo: Path, capsys: pytest.CaptureFixture) -> None:
    write(repo, "systems/old/a.md", "A")
    indexgen.write(bundle(repo))
    (repo / "kb/systems/old/a.md").rename(repo / "kb/systems/a.md")
    indexgen.write(bundle(repo))  # the parent indexes change too
    (repo / "kb/systems/old/index.md").write_text("# Pages\n", newline="\n")  # left behind, e.g. by a checkout
    assert indexgen.stale(bundle(repo)) == [repo / "kb/systems/old/index.md"]
    diagnostics = [d for d in Checker(bundle(repo)).check_all() if d.code == "H040"]
    assert [(d.path, "without pages" in d.message) for d in diagnostics] == [("systems/old/index.md", True)]
    assert cli.main(["index", "--check"]) == 1
    assert "orphaned: kb/systems/old/index.md" in capsys.readouterr().out
    assert cli.main(["index"]) == 0
    assert capsys.readouterr().out.splitlines() == ["deleted kb/systems/old/index.md"]
    assert cli.main(["index", "--check"]) == 0


def test_multiline_titles_are_one_line_in_indexes(repo: Path) -> None:
    write(repo, "systems/a.md", "|\n  First line\n  second line")
    taxonomy = repo / "schema" / "taxonomy.yaml"
    taxonomy.write_text(
        taxonomy.read_text(encoding="utf-8").replace(
            "systems: { group: Knowledge domains, title: Systems,",
            'systems: { group: Knowledge domains, title: "Sys\\ntems",',
        ),
        newline="\n",
    )
    indexgen.write(bundle(repo))
    assert "* [First line second line](./a.md)" in (repo / "kb/systems/index.md").read_text(encoding="utf-8")
    assert "* [Sys tems](./systems/index.md)" in (repo / "kb/index.md").read_text(encoding="utf-8")
    assert "O004" not in codes(repo) and "H040" not in codes(repo)


# -- scope and analytics ------------------------------------------------------------------------


def test_one_scope_for_every_analytics_command(repo: Path) -> None:
    write(repo, "systems/a.md", "Alpha widget", "Text.")
    write(repo, "_templates/t.md", "Alpha widget", "Mentions Alpha widget.", type_="Template")
    write(repo, "journal/2026/2026-01-01.md", "Alpha widget", "Mentions alpha widget.", type_="Journal Entry")
    b = bundle(repo)
    assert set(b.pages()) == {"systems/a.md"}
    assert set(b.pages("all")) == {"systems/a.md", "journal/2026/2026-01-01.md"}
    assert graph.analyze(b)["pages"] == 1 and graph.analyze(b, scope="all")["pages"] == 2
    assert "Template" not in report.build(b)
    assert unlinked.find(b) == []  # the template's mention is not scanned
    assert [m.page for m in unlinked.find(b, include_personal=True)] == ["/journal/2026/2026-01-01.md"]
    assert dupes.find(b) == []  # the template is not a duplicate candidate


def test_exact_duplicates_are_found_in_large_blocks(repo: Path) -> None:
    for i in range(dupes.MAX_BLOCK + 5):
        write(repo, f"data/w{i}.md", f"Widget number {i}")
    write(repo, "systems/widget-cache.md", "Widget cache")
    write(repo, "hpc/widget-cache.md", "Widget cache")
    found = [(c.a, c.b) for c in dupes.find(bundle(repo)) if "same name" in c.signals]
    assert found == [("hpc/widget-cache.md", "systems/widget-cache.md")]


def test_unlinked_line_numbers_and_punctuated_acronyms(repo: Path) -> None:
    write(repo, "programming/dotnet.md", "Dotnet platform", extra="aliases: [.NET]\n")
    write(repo, "programming/user.md", "User", "One\u2028line.\n\nBuilt on .NET today.\n")
    path = repo / "kb/programming/user.md"
    found = unlinked.find(bundle(repo))
    assert [(m.text, m.snippet) for m in found] == [(".NET", "Built on .NET today.")]
    assert found[0].line == path.read_text(encoding="utf-8").split("\n").index("Built on .NET today.") + 1


def test_unlinked_plural_and_separator_forms(repo: Path) -> None:
    write(repo, "programming/dsl.md", "Domain-specific language")
    write(repo, "programming/a.md", "A", "Two domain_specific languages.\n")
    write(repo, "programming/b.md", "B", "A domain, specific language.\n")  # punctuation between: no match
    found = unlinked.find(bundle(repo))
    assert [(m.page, m.text) for m in found] == [("/programming/a.md", "domain_specific languages")]


def test_remove_tree_deletes_read_only_files(tmp_path: Path, monkeypatch) -> None:
    """Windows refuses to delete read-only files (git objects, copies of read-only pages)."""
    import os
    import stat

    from kbtools import fsutil

    tree = tmp_path / "backup"
    (tree / "objects").mkdir(parents=True)
    for path in (tree / "objects" / "ab12", tree / "0"):
        path.write_text("x", encoding="utf-8", newline="\n")
        path.chmod(stat.S_IREAD)
    real_unlink = os.unlink

    def windows_unlink(path, *, dir_fd=None):
        if not os.stat(path, dir_fd=dir_fd).st_mode & stat.S_IWRITE:
            raise PermissionError(f"read-only: {path}")
        real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", windows_unlink)
    fsutil.remove_tree(tree)
    assert not tree.exists()
    with pytest.raises(FileNotFoundError):
        fsutil.remove_tree(tree)
    fsutil.remove_tree(tree, ignore_errors=True)
