"""`osaudit numbers` on fixtures that reproduce the defects a number audit must catch."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from osaudit._cli import main
from osaudit._config import ConfigError, load
from osaudit._number import parse
from osaudit._numbers import candidates, check
from osaudit._results import Results

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURES / "clean", tmp_path, dirs_exist_ok=True)
    return tmp_path


def rules(root: Path) -> list[tuple[str, int, str]]:
    return [(f.file, f.line, f.rule) for f in check(load(root))]


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def test_clean_is_silent(capsys: pytest.CaptureFixture[str]) -> None:  # known-negative
    assert main(["numbers", "--root", str(FIXTURES / "clean")]) == 0
    assert capsys.readouterr().out == ""


def test_clean_json_is_empty_array(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["numbers", "--root", str(FIXTURES / "clean"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_stale_share_derivation_mismatch(capsys: pytest.CaptureFixture[str]) -> None:
    # known-positive: a share printed from ages computed against now(), recomputed differently
    assert main(["numbers", "--root", str(FIXTURES / "stale-age")]) == 1
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1
    assert out[0].startswith("audit.toml:8: numbers/derive-mismatch: 70.0% declared")
    assert out[0].endswith("printed 62.5%")


def test_derived_number_without_derivation(repo: Path) -> None:
    edit(repo / "audit.toml", 'value = "392"', 'value = "391"')
    findings = check(load(repo))
    assert [(f.file, f.rule) for f in findings] == [
        ("audit.toml", "numbers/derive-mismatch"),
        ("paper/results.tex", "numbers/untraced"),
    ]
    untraced = findings[1]
    assert untraced.line == 6 and untraced.message.startswith("392 ")
    assert untraced.candidates[0] == "panel.overall.total - panel.overall.answers.yes"


def test_cited_count_without_allow(repo: Path) -> None:  # a count published by a source
    toml = repo / "audit.toml"
    text = toml.read_text()
    toml.write_text(text[: text.index("[[numbers.allow]]")])
    assert rules(repo) == [("paper/results.tex", 11, "numbers/untraced")]


def test_unused_entry(repo: Path) -> None:  # an allow entry that outlived its text
    edit(repo / "paper/results.tex", "2,000,000", "two million")
    assert rules(repo) == [("audit.toml", 19, "numbers/unused")]


def test_allow_restricted_to_file(repo: Path) -> None:  # boundary: right value, other file
    toml = repo / "audit.toml"
    toml.write_text(toml.read_text() + 'file = "paper/other.tex"\n')
    assert sorted(rules(repo)) == [("audit.toml", 19, "numbers/unused"),
                                   ("paper/results.tex", 11, "numbers/untraced")]


def test_unknown_value_in_expr(repo: Path) -> None:
    edit(repo / "audit.toml", "panel.overall.total - ", "panel.overall.totl - ")
    findings = check(load(repo))
    assert [(f.line, f.rule) for f in findings] == [(7, "numbers/derive-unknown")]
    assert "panel.overall.totl" in findings[0].message


def test_allow_needs_reason(repo: Path) -> None:
    edit(repo / "audit.toml", 'reason = "population size', 'note = "')
    with pytest.raises(ConfigError, match="reason is mandatory"):
        load(repo)


def test_bad_config_exits_2(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "audit.toml").write_text("[paper]\ntex = ['nothing/*.tex']\n")
    assert main(["numbers", "--root", str(repo)]) == 2
    assert "matches no file" in capsys.readouterr().err


def test_expressions_are_not_evaluated_as_python() -> None:
    r = Results({"a": {"x": 3, "<30d": {"n": 4}}, "b": [10, 20]})
    assert r.evaluate('(a.x + a["<30d"].n) * 2 - b[1] / 4') == 9
    for bad in ("__import__('os')", "a.x ** 2", "a.missing", "a", "1 / 0"):
        with pytest.raises(ValueError):
            r.evaluate(bad)


def test_candidates_use_counts_only() -> None:
    values = Results({"r": {"yes": 812, "total": 1204, "share": 0.5}}).values
    n = parse("67.4%")
    assert n is not None
    assert candidates(n, values) == ["r.yes / r.total"]
    n = parse("3")
    assert n is not None
    assert candidates(n, {"r.share": values["r.share"]}) == []


def test_provenance_is_not_a_result() -> None:
    r = Results.load([FIXTURES / "clean" / "results" / "panel.json"])
    assert not any("provenance" in k for k in r.values)
