"""Tests for `kb eval` (retrieval evaluation; no network, qmd faked)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from kbtools import retrieval_eval, search
from kbtools.bundle import Bundle
from kbtools.cli import main

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _page(title: str, description: str, body: str, tags: str = "[]", type_: str = "Concept") -> str:
    return (
        f"---\ntype: {type_}\ntitle: {title}\ndescription: {description}\ntags: {tags}\nstatus: stable\n"
        f"generated: {{ by: test/0, at: 2026-09-25T12:00:00Z }}\n---\n\n{body}\n"
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(FIXTURES / "schema", tmp_path / "schema")
    shutil.copy(REPO / "schema" / "frontmatter.schema.json", tmp_path / "schema")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo-tools"\n\n[tool.kb]\nbundle = "kb"\n')
    kb = tmp_path / "kb"
    (kb / "systems").mkdir(parents=True)
    (kb / "data").mkdir()
    (kb / "systems" / "dns.md").write_text(_page("DNS", "Resolves host names to addresses.", "Recursive resolvers cache.", "[networking]"))
    (kb / "systems" / "dhcp.md").write_text(_page("DHCP", "Leases addresses to hosts.", "Leases expire; see resolvers.", "[networking]"))
    (kb / "data" / "parquet.md").write_text(_page("Parquet", "Columnar file format.", "Row groups and zstd compression."))
    (tmp_path / "tools" / "retrieval-eval").mkdir(parents=True)
    monkeypatch.setenv("KB_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("KB_QMD_COLLECTION", raising=False)
    monkeypatch.setattr(search, "qmd_ready", lambda collection: False)
    return tmp_path


def _questions(repo: Path, text: str) -> Path:
    path = repo / "tools" / "retrieval-eval" / "questions.yaml"
    path.write_text(text)
    return path


QUESTIONS = """\
questions:
  - question: How are host names resolved?
    expected: [/systems/dns.md]
  - question: Which compression does zstd give?
    expected: [/data/parquet.md]
  - question: Which pages are about networking?
    expected: [/systems/dhcp.md, /systems/dns.md]
    filters: {tag: networking, folder: systems}
  - question: Where is the kubernetes scheduler described?
    expected: [/data/parquet.md]
"""


def test_eval_table_and_summary(repo: Path, capsys) -> None:
    _questions(repo, QUESTIONS)
    assert main(["eval"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[1].split()[:4] == ["1", "1/1", "@1", "-"]  # index entry "host names" -> rank 1
    assert lines[2].split()[:3] == ["2", "1/1", "@1"]  # body-only word: found by the text search
    assert lines[3].split()[1:5] == ["2/2", "@1", "2/2", "@1"]  # filters tier ran
    assert lines[4].split()[1:3] == ["0/1", "@-"]  # nothing reaches it
    assert "skipped" in lines[1]
    assert "index+text 0.75 (3/4 hit)" in out and "filters 1.00 (1/1 hit)" in out
    assert "qmd skipped (qmd is not set up: no collection `demo`)" in out


def test_eval_json(repo: Path, capsys) -> None:
    _questions(repo, QUESTIONS)
    assert main(["eval", "--json", "--k", "1"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["k"] == 1
    third = result["questions"][2]["tiers"]
    assert third["index+text"]["recall"] == 0.5 and len(third["index+text"]["top"]) == 1
    assert third["filters"]["top"] == ["/systems/dhcp.md"]  # kb find order: by path
    assert result["questions"][0]["tiers"]["filters"] == {"status": "skipped", "reason": "no filters"}
    assert result["summary"]["qmd"]["recall"] is None


@pytest.mark.parametrize(("min_recall", "code"), [("0.7", 0), ("0.75", 0), ("0.8", 1)])
def test_eval_min_recall(repo: Path, capsys, min_recall: str, code: int) -> None:
    _questions(repo, QUESTIONS)
    assert main(["eval", "--min-recall", min_recall]) == code
    assert ("below --min-recall" in capsys.readouterr().err) == bool(code)


def test_eval_index_navigation_ranks_index_matches_first(repo: Path) -> None:
    bundle = Bundle(repo / "kb", repo)
    # "resolvers" is only in bodies; "addresses" is in two index entries, "hosts" in one
    ranking = retrieval_eval.tier1_ranking(bundle, "addresses hosts resolvers")
    assert ranking == ["/systems/dhcp.md", "/systems/dns.md"]
    assert retrieval_eval.index_ranking(bundle, "resolvers") == []


def test_eval_common_words_do_not_bury_text_hits(repo: Path, capsys) -> None:
    """Regression: substring matches and stop words let every index entry outrank the text search."""
    for n in range(12):
        (repo / "kb" / "data" / f"thing-{n:02}.md").write_text(_page(f"Thing {n}", f"Overview of the thing number {n}.", "Nothing."))
    (repo / "kb" / "data" / "zbackups.md").write_text(
        _page("Snapshot schedule", "When snapshots run.", "The retention policy for backups keeps 30 days.")
    )
    _questions(repo, "questions:\n  - question: What is the retention policy for backups?\n    expected: [/data/zbackups.md]\n")
    assert main(["eval", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["questions"][0]["tiers"]["index+text"]["rank"] == 1


def test_eval_index_needs_two_words_of_a_long_question(repo: Path) -> None:
    bundle = Bundle(repo / "kb", repo)
    assert retrieval_eval.index_ranking(bundle, "columnar storage layout") == []  # one word of three
    assert retrieval_eval.index_ranking(bundle, "columnar format layout") == ["/data/parquet.md"]
    assert retrieval_eval.index_ranking(bundle, "columnar") == ["/data/parquet.md"]
    assert retrieval_eval.index_ranking(bundle, "what are the columns") == []  # stop words, whole words only


@pytest.mark.parametrize(
    ("args", "lines"),
    [
        (["--tag", "networking"], ["/systems/dhcp.md\tConcept\tDHCP", "/systems/dns.md\tConcept\tDNS"]),
        (["--folder", "data"], ["/data/parquet.md\tConcept\tParquet"]),
        (["--folder", "systems", "--tag", "networking", "--status", "stable"],
         ["/systems/dhcp.md\tConcept\tDHCP", "/systems/dns.md\tConcept\tDNS"]),
        (["--status", "draft"], []),
        (["--type", "Source"], []),
    ],
)
def test_find_output_unchanged(repo: Path, capsys, args: list[str], lines: list[str]) -> None:
    assert main(["find", *args]) == 0
    assert capsys.readouterr().out.splitlines() == lines


def test_eval_qmd_tier(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _questions(repo, "questions:\n  - question: host names\n    expected: [/systems/dns.md]\n")
    monkeypatch.setattr(search, "qmd_ready", lambda collection: True)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        rows = [{"file": "qmd://demo/systems/dhcp.md"}, {"file": "qmd://demo/systems/dns.md?index=index"}]
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(rows), stderr="")

    monkeypatch.setattr(retrieval_eval.subprocess, "run", fake_run)
    assert main(["eval", "--json"]) == 0
    captured = capsys.readouterr()
    qmd = json.loads(captured.out)["questions"][0]["tiers"]["qmd"]
    assert qmd["rank"] == 2 and qmd["recall"] == 1.0
    assert calls == [["qmd", "query", "-c", "demo", "--json", "-n", "20", "--", "host names"]]
    assert "may download qmd's models" in captured.err
    assert main(["eval", "--no-qmd"]) == 0 and len(calls) == 1
    captured = capsys.readouterr()
    assert "disabled with --no-qmd" in captured.out and "qmd query" not in captured.err


def test_eval_qmd_timeout_is_an_error_cell(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _questions(repo, "questions:\n  - question: host names\n    expected: [/systems/dns.md]\n")
    monkeypatch.setattr(search, "qmd_ready", lambda collection: True)

    def slow(cmd, **kwargs):
        assert kwargs["timeout"] == retrieval_eval.QMD_TIMEOUT
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(retrieval_eval.subprocess, "run", slow)
    assert main(["eval"]) == 0
    out = capsys.readouterr().out
    assert "error" in out.splitlines()[1] and "timed out after" in out


def test_eval_qmd_failure_is_reported(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _questions(repo, "questions:\n  - question: host names\n    expected: [/systems/dns.md]\n")
    monkeypatch.setattr(search, "qmd_ready", lambda collection: True)
    monkeypatch.setattr(
        retrieval_eval.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, stdout="", stderr="no models"),
    )
    assert main(["eval"]) == 0
    out = capsys.readouterr().out
    assert "error" in out.splitlines()[1] and "qmd: `qmd query` failed (exit 2): no models" in out


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("- a\n", "expected a mapping with one key, `questions`"),
        ("questions: {a: 1}\n", "`questions` must be a list"),
        ("questions: [x]\n", "question 1: expected a mapping"),
        ("questions:\n  - expected: [/systems/dns.md]\n", "question 1: `question` must be a non-empty string"),
        ("questions:\n  - question: q\n", "question 1: `expected` must be a non-empty list"),
        ("questions:\n  - {question: q, expected: [systems/dns.md]}\n", "'systems/dns.md' is not a bundle-absolute path"),
        ("questions:\n  - {question: q, expected: [/systems/nope.md]}\n", "/systems/nope.md does not exist in the bundle"),
        ("questions:\n  - {question: q, expected: [/Systems/DNS.md]}\n", "/Systems/DNS.md does not exist in the bundle"),
        ("questions:\n  - {question: q, expected: [/systems/index.md]}\n", "/systems/index.md is a generated index"),
        ("questions:\n  - {question: q, expected: [/systems/dns.md], note: x}\n", "unknown key `note`"),
        ("questions:\n  - {question: q, expected: [/systems/dns.md], filters: [x]}\n", "`filters` must be a mapping"),
        ("questions:\n  - {question: q, expected: [/systems/dns.md], filters: {kind: x}}\n", "unknown filter `kind`"),
        ("questions:\n  - {question: q, expected: [/systems/dns.md], filters: {tag: [1]}}\n", "filter `tag` must be a string or a list"),
        ("questions:\n  - {question: q, expected: [/systems/dns.md], filters: {status: old}}\n", "filter `status` must be one of"),
        ("questions: [\n", "unparseable YAML"),
        ("questions:\n  - {question: q, expected: [/systems/dns.md, /systems/dns.md]}\n", "/systems/dns.md is listed more than once"),
        ("questions:\n  - {question: q, expected: [/systems/dns.md], filters: {type: Idea}}\n", "'Idea' is not a type"),
        ("questions:\n  - {question: q, expected: [/systems/dns.md], filters: {folder: nope}}\n", "'nope' is not a folder"),
        ("questions:\n  - {question: q, expected: [/systems/dns.md], filters: {tag: []}}\n", "must name at least one tag"),
    ],
)
def test_eval_rejects_invalid_questions(repo: Path, text: str, message: str) -> None:
    _questions(repo, text)
    with pytest.raises(SystemExit) as exc:
        main(["eval"])
    assert message in str(exc.value)


def test_eval_reports_every_problem_at_once(repo: Path) -> None:
    _questions(repo, "questions:\n  - {question: q, expected: [/a.md]}\n  - {question: r, expected: [/b.md]}\n")
    with pytest.raises(SystemExit) as exc:
        main(["eval"])
    assert "question 1: expected page /a.md" in str(exc.value) and "question 2: expected page /b.md" in str(exc.value)


def test_eval_missing_file_and_bad_options(repo: Path) -> None:
    with pytest.raises(SystemExit, match="cannot read"):
        main(["eval"])
    _questions(repo, "questions: []\n")
    with pytest.raises(SystemExit, match="--k must be at least 1"):
        main(["eval", "--k", "0"])
    with pytest.raises(SystemExit, match="between 0 and 1"):
        main(["eval", "--min-recall", "2"])


def test_eval_empty_set_passes(repo: Path, capsys) -> None:
    _questions(repo, "# only comments\nquestions: []\n")
    assert main(["eval", "--min-recall", "1"]) == 0
    assert "kb eval: no questions in" in capsys.readouterr().out
    assert main(["eval", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["questions"] == []


def test_eval_shipped_question_file_is_valid(repo: Path) -> None:
    shipped = REPO / "tools" / "retrieval-eval" / "questions.yaml"
    assert retrieval_eval.load_questions(Bundle(repo / "kb", repo), shipped) == []
