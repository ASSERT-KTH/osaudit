"""`osaudit numbers` on fixtures that reproduce the defects a number audit must catch."""

from __future__ import annotations

import json
import random
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from osaudit._cli import main
from osaudit._config import AUDIT, ConfigError, load
from osaudit._number import Values, close, parse
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
    assert out[0].startswith("audit.toml:10: numbers/derive-mismatch: 70.0% declared")
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
    assert rules(repo) == [("audit.toml", 21, "numbers/unused")]


def test_allow_restricted_to_file(repo: Path) -> None:  # boundary: right value, other file
    toml = repo / "audit.toml"
    toml.write_text(toml.read_text() + 'file = "paper/other.tex"\n')
    assert sorted(rules(repo)) == [("audit.toml", 21, "numbers/unused"),
                                   ("paper/results.tex", 11, "numbers/untraced")]


def test_unknown_value_in_expr(repo: Path) -> None:
    edit(repo / "audit.toml", "panel.overall.total - ", "panel.overall.totl - ")
    findings = check(load(repo))
    assert [(f.line, f.rule) for f in findings] == [(9, "numbers/derive-unknown")]
    assert "panel.overall.totl" in findings[0].message


def test_allow_needs_reason(repo: Path) -> None:
    edit(repo / "audit.toml", 'reason = "population size', 'note = "')
    with pytest.raises(ConfigError, match="reason is mandatory"):
        load(repo)


def test_bad_config_exits_2(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "audit.toml").write_text(f"schema = '{AUDIT}'\n[paper]\ntex = ['nothing/*.tex']\n")
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


def test_non_finite_results_value_is_skipped(repo: Path) -> None:  # issue #1
    (repo / "results" / "nan.json").write_text('{"acc": NaN, "inf": Infinity, "x": 0.42}')
    r = Results.load([repo / "results" / "nan.json"])
    assert r.values == {"nan.x": Decimal("0.42")}
    for expr in ("nan.acc", "nan.inf + 1"):
        with pytest.raises(ValueError, match="not a finite number"):
            r.evaluate(expr)
    assert rules(repo) == []


def test_values_index_agrees_with_close() -> None:  # the index against its reference
    rng = random.Random(0)
    vs = [Decimal(str(round(rng.uniform(0, 3), rng.randint(0, 4)))) for _ in range(300)]
    vs += [Decimal(rng.randint(0, 300)) for _ in range(100)]
    index = Values({str(i): v for i, v in enumerate(vs)})
    for d in range(4):
        for pct in (False, True):
            for i in range(0, 400 if d == 0 else 3 * 10 ** d, 1 if d < 2 else 7):
                text = f"{i / 10 ** d:.{d}f}" + ("%" if pct else "")
                n = parse(text)
                assert n is not None
                assert index.matches(n) == any(close(n, v) for v in vs), text
                assert set(index.names(n)) == {str(i) for i, v in enumerate(vs) if close(n, v)}


def dense(root: Path, paper: str, derive: str = "") -> Path:
    """A paper over raw outputs: a per-example score for every 3-decimal value in [0, 1]."""
    (root / "results").mkdir()
    (root / "results" / "raw.json").write_text(json.dumps(
        {"scores": [i / 1000 for i in range(1001)], "n": 7}))
    (root / "paper.tex").write_text(paper)
    (root / "audit.toml").write_text(f"schema = '{AUDIT}'\n[paper]\ntex = ['paper.tex']\n"
                                     f"[results]\nfiles = ['results/*.json']\n{derive}")
    return root


def test_dense_results_match_by_chance(tmp_path: Path) -> None:  # issue #2, known-positive
    root = dense(tmp_path, "The mean is 0.42, then 0.01 or 4.2\\%, of 7 runs.\n")
    found = {f.message.split(" ")[0]: f for f in check(load(root))}
    assert sorted(found) == ["0.01", "0.42", "4.2\\%"]  # 7 is one of 2 integer values: traced
    assert {f.rule for f in found.values()} == {"numbers/chance-match"}
    assert found["0.42"].candidates[0] == "raw.scores[420]"  # the closest value first
    assert "100 of the 100" in found["0.42"].message


def test_derivation_traces_a_number_in_dense_results(tmp_path: Path) -> None:  # boundary
    root = dense(tmp_path, "The mean is 0.42.\n",
                 '[[numbers.derive]]\nvalue = "0.42"\nexpr = "raw.scores[420]"\n')
    assert rules(root) == []


def test_sparse_results_are_not_chance() -> None:  # known-negative
    index = Values({"a": Decimal("0.42"), "b": Decimal("0.5"), "c": Decimal("7")})
    for text in ("0.42", "42.0%", "7"):
        n = parse(text)
        assert n is not None and index.matches(n)
        assert index.neighbours_matched(n) <= 1


def test_share_candidates_agree_with_all_pairs() -> None:  # the range lookup against all pairs
    rng = random.Random(1)
    values = {f"r.c{i}": Decimal(rng.randint(-40, 400)) for i in range(60)} | {"r.z": Decimal(0)}
    named = sorted(values.items())
    for text in ("0.5", "1.25", "0.0%", "33.3%", "12.50%", "2.0", "0.07"):
        n = parse(text)
        assert n is not None
        every = sorted(f"{a} / {b}" for a, va in named for b, vb in named
                       if a != b and vb != 0 and close(n, va / vb))
        with pytest.MonkeyPatch.context() as m:
            m.setattr("osaudit._numbers.MAX_CANDIDATES", len(named) ** 2)
            m.setattr("osaudit._numbers.MAX_EXPRESSIONS", len(named) ** 2)
            assert sorted(candidates(n, values)) == every, text


def test_no_candidates_from_dense_counts() -> None:  # too many expressions print as the number
    n = parse("5")
    assert n is not None
    counts = {f"r.c{i}": Decimal(i) for i in range(2000)}
    assert candidates(n, counts) == []
    assert candidates(n, {k: counts[k] for k in ("r.c2", "r.c3", "r.c9")}) == ["r.c2 + r.c3"]
