"""`osaudit run --prereg/--explore` and `osaudit study` on git repositories in temporary dirs.

The study mirrors the ways a confirmatory claim goes wrong: no pre-registration, a run of
another experiment or on other data, a bar moved without an amendment or after the data was
seen, and data already looked at during exploration.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from osaudit._cli import main

EXPERIMENT = """\
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
files = sorted(p.rglob("*.csv")) if p.is_dir() else [p]
rows = [r for f in files for r in f.read_text().splitlines()]
print(json.dumps({"rows": len(rows), "share": 0.625}))
"""

PREREG = """\
+++
mode = "confirmatory"
hypothesis = "the share is above one half"
null = "the share is at most one half"
experiments = ["experiments/count.py"]
data = ["data/test"]
statistic = "one-sided binomial test"
alpha = 0.05
m = 1
correction = "none"
go = "p < 0.05"
stop = "p >= 0.05"
disaster = "rows = 0"
{amendments}+++

# count
"""

LOG = """\
+++
mode = "exploratory"
holdout = ["data/test"]
data_seen = ["data/train.csv"]
+++

# look
"""

AUDIT = """\
[paper]
tex = ["paper.tex"]

[results]
files = ["results/*.json"]
instruments = ["experiments/*.py"]
"""


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t",
                    *args], check=True, capture_output=True)


def commit(root: Path) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "x")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for d in ("experiments", "data/test", "prereg", "explore", "results"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "experiments/count.py").write_text(EXPERIMENT)
    (tmp_path / "experiments/other.py").write_text(EXPERIMENT)
    (tmp_path / "data/train.csv").write_text("a\nb\n")
    (tmp_path / "data/test/part.csv").write_text("c\nd\ne\n")
    (tmp_path / "prereg/count.md").write_text(PREREG.format(amendments=""))
    (tmp_path / "explore/look.md").write_text(LOG)
    (tmp_path / "paper.tex").write_text("No numbers.\n")
    (tmp_path / "audit.toml").write_text(AUDIT)
    git(tmp_path, "init", "-q")
    commit(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OSAUDIT_NOW", "2026-03-02T00:00:00+00:00")
    return tmp_path


def run(*flags: str, data: str = "data/test", script: str = "experiments/count.py",
        out: str = "results/count.json") -> int:
    return main(["run", "--input", data, "-o", out, *flags, "--", sys.executable, script, data])


def audit(root: Path, check: str = "study") -> list[tuple[str, str]]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main([check, "--root", str(root), "--json"])
    found = [(f["rule"], f["message"]) for f in json.loads(buf.getvalue())]
    assert code == (1 if found else 0)
    return found


def rules(root: Path, check: str = "study") -> list[str]:
    return [r for r, _ in audit(root, check)]


def explore_train(repo: Path) -> None:
    assert run("--explore", "explore/look.md", data="data/train.csv",
               out="results/look.json") == 0


def test_confirmatory_run_records_mode_and_is_clean(repo: Path) -> None:  # known-negative
    explore_train(repo)
    assert run("--prereg", "prereg/count.md") == 0
    p = json.loads((repo / "results/count.json").read_text())["provenance"]
    assert (p["mode"], p["study"]) == ("confirmatory", "prereg/count.md")
    commit(repo)
    assert audit(repo) == []


def test_exploratory_run_records_mode(repo: Path) -> None:
    explore_train(repo)
    p = json.loads((repo / "results/look.json").read_text())["provenance"]
    assert (p["mode"], p["study"]) == ("exploratory", "explore/look.md")


def test_explore_without_log_refused(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("--explore", "explore/none.md", data="data/train.csv", out="results/l.json") == 2
    assert "no exploration log" in capsys.readouterr().err


def test_unlabelled_results_stay_silent(repo: Path) -> None:  # backward compatible
    assert run() == 0
    commit(repo)
    assert audit(repo) == []


def refused(capsys: pytest.CaptureFixture[str], rule: str) -> None:
    err = capsys.readouterr().err
    assert "refused" in err and rule in err, err


def test_run_refuses_invalid_prereg(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "prereg/count.md").write_text("# count\nno front matter\n")
    commit(repo)
    assert run("--prereg", "prereg/count.md") == 2
    refused(capsys, "study/not-preregistered")


def test_run_refuses_uncommitted_prereg(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "prereg/new.md").write_text(PREREG.format(amendments=""))
    assert run("--prereg", "prereg/new.md") == 2
    refused(capsys, "not committed")


def test_run_refuses_other_experiment(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("--prereg", "prereg/count.md", script="experiments/other.py") == 2
    refused(capsys, "study/prereg-mismatch")


def test_run_refuses_unregistered_data(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("--prereg", "prereg/count.md", data="data/train.csv") == 2
    refused(capsys, "study/prereg-mismatch")


def test_run_refuses_data_seen_in_log(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "explore/look.md").write_text(LOG.replace('"data/train.csv"', '"data/test/part.csv"'))
    commit(repo)
    assert run("--prereg", "prereg/count.md") == 2
    refused(capsys, "study/data-reused")


def test_run_refuses_data_seen_by_hash(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # The exploration read a copy of the test data under another name: same sha256.
    (repo / "data/copy").mkdir()
    (repo / "data/copy/part.csv").write_text("c\nd\ne\n")
    commit(repo)
    assert run("--explore", "explore/look.md", data="data/copy", out="results/look.json") == 0
    assert run("--prereg", "prereg/count.md") == 2
    refused(capsys, "study/data-reused")


def confirmed(repo: Path) -> None:
    assert run("--prereg", "prereg/count.md") == 0
    commit(repo)


AMENDMENT = """\
[[amendments]]
date = "2026-03-01"
data_seen = {seen}
what = "alpha"
why = "a reviewer asked"
"""


def test_amendment_before_data_is_clean(repo: Path) -> None:
    (repo / "prereg/count.md").write_text(
        PREREG.format(amendments=AMENDMENT.format(seen="false")).replace("0.05", "0.01"))
    commit(repo)
    confirmed(repo)
    assert audit(repo) == []


def fake_confirmatory(repo: Path) -> None:
    """A confirmatory results file written by hand at HEAD, as `run --prereg` would have."""
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()
    prov = {"command": ["python", "experiments/count.py", "data/test"], "cwd": ".",
            "commit": head, "inputs": [{"path": "data/test", "sha256": "1" * 64}],
            "now": "2026-03-02T00:00:00+00:00", "mode": "confirmatory",
            "study": "prereg/count.md"}
    (repo / "results/fake.json").write_text(json.dumps({"n": 1, "provenance": prov}))


def test_change_without_amendment(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "prereg/count.md").write_text(PREREG.format(amendments="").replace("0.05", "0.1"))
    commit(repo)
    assert run("--prereg", "prereg/count.md") == 2
    refused(capsys, "study/amended")
    fake_confirmatory(repo)
    assert rules(repo) == ["study/amended"]


def test_amendment_after_data_seen(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "prereg/count.md").write_text(
        PREREG.format(amendments=AMENDMENT.format(seen="true")))
    commit(repo)
    assert run("--prereg", "prereg/count.md") == 2
    refused(capsys, "after data was seen")
    fake_confirmatory(repo)
    assert rules(repo) == ["study/amended"]


def test_later_prereg_edit_does_not_touch_earlier_result(repo: Path) -> None:
    confirmed(repo)
    (repo / "prereg/count.md").write_text(PREREG.format(amendments="").replace("0.05", "0.1"))
    commit(repo)
    assert audit(repo) == []  # the result is judged by the prereg at its own commit


def test_audit_catches_hand_written_confirmatory(repo: Path) -> None:
    # A results file claiming to be confirmatory, never produced by `run --prereg`.
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()
    prov = {"command": ["python", "experiments/count.py"], "cwd": ".", "commit": head,
            "inputs": [{"path": "data/train.csv", "sha256": "0" * 64}],
            "now": "2026-03-02T00:00:00+00:00", "mode": "confirmatory",
            "study": "prereg/missing.md"}
    (repo / "results/fake.json").write_text(json.dumps({"n": 1, "provenance": prov}))
    assert rules(repo) == ["study/not-preregistered"]
    prov["study"] = "prereg/count.md"
    (repo / "results/fake.json").write_text(json.dumps({"n": 1, "provenance": prov}))
    # data/train.csv is outside the registered data, and the exploration log saw it.
    assert rules(repo) == ["study/data-reused", "study/prereg-mismatch"]


def paper(repo: Path, text: str) -> list[str]:
    (repo / "paper.tex").write_text(text)
    return [r for r in rules(repo, "numbers") if r == "numbers/exploratory-unlabelled"]


def test_exploratory_number_must_say_so(repo: Path) -> None:
    explore_train(repo)
    assert run("--prereg", "prereg/count.md") == 0
    commit(repo)
    assert paper(repo, "The training split has 2 rows.\n") == ["numbers/exploratory-unlabelled"]
    assert paper(repo, "In an exploratory look,\nthe training split has 2 rows.\n") == []
    # Another paragraph saying it does not label this one.
    assert paper(repo, "This is exploratory.\n\nThe split has 2 rows.\n") == [
        "numbers/exploratory-unlabelled"]
    assert paper(repo, "The confirmatory test read 3 rows.\n") == []


def test_derivation_with_exploratory_operand_is_exploratory(repo: Path) -> None:
    explore_train(repo)
    assert run("--prereg", "prereg/count.md") == 0
    commit(repo)
    with (repo / "audit.toml").open("a") as f:
        f.write('\n[[numbers.derive]]\nvalue = "5"\nexpr = "look.rows + count.rows"\n')
    assert paper(repo, "Together 5 rows.\n") == ["numbers/exploratory-unlabelled"]


def test_no_exploratory_results_no_rule(repo: Path) -> None:  # backward compatible
    assert run() == 0
    commit(repo)
    assert paper(repo, "It has 3 rows.\n") == []
