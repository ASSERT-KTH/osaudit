"""`osaudit run` and `osaudit results` on git repositories built in a temporary directory.

The instruments mirror the defects a results audit must catch: results without provenance, an
age computed against the clock at analysis time, inputs that change after the run.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from osaudit._cli import main
from osaudit._provenance import sha256

INSTRUMENT = """\
import json, os, sys
from datetime import datetime
lines = open(sys.argv[1]).read().splitlines()
now = datetime.fromisoformat(os.environ["OSAUDIT_NOW"])
start = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
print(json.dumps({"lines": len(lines), "age_days": (now - start).days}))
"""

CLOCK_INSTRUMENT = """\
import json, time
now = time.time_ns()  # osaudit: allow results/wall-clock -- exempt, to test the rerun
print(json.dumps({"age_ns": now}))
"""

AUDIT = """\
[paper]
tex = ["paper.tex"]

[results]
files = ["results/*.json"]
instruments = ["*.py"]
"""


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t",
                    *args], check=True, capture_output=True)


def commit(root: Path) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "x")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "inst.py").write_text(INSTRUMENT)
    (tmp_path / "data.txt").write_text("a\nb\nc\n")
    (tmp_path / "paper.tex").write_text("No numbers.\n")
    (tmp_path / "audit.toml").write_text(AUDIT)
    (tmp_path / "results").mkdir()
    git(tmp_path, "init", "-q")
    commit(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OSAUDIT_NOW", "2026-03-02T00:00:00+00:00")
    assert run(tmp_path, "inst.py", "data.txt", "results/r.json") == 0
    commit(tmp_path)
    return tmp_path


def run(root: Path, script: str, data: str, out: str) -> int:
    return main(["run", "--root", str(root), "--input", data, "-o", out, "--",
                 sys.executable, script, data])


def audit(root: Path, *flags: str) -> list[tuple[str, int, str]]:
    """(file, line, rule) of every finding, from the --json output."""
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(["results", "--root", str(root), "--json", *flags])
    found = [(f["file"], f["line"], f["rule"]) for f in json.loads(buf.getvalue())]
    assert code == (1 if found else 0)
    return found


def test_run_writes_provenance(repo: Path) -> None:
    doc = json.loads((repo / "results/r.json").read_text())
    p = doc["provenance"]
    assert doc["lines"] == 3 and doc["age_days"] == 60
    assert p["inputs"] == [{"path": "data.txt", "sha256": sha256(repo / "data.txt")}]
    assert p["now"] == "2026-03-02T00:00:00+00:00" and p["cwd"] == "."
    assert p["command"][1:] == ["inst.py", "data.txt"] and len(p["commit"]) == 40


def test_clean_is_silent(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:  # negative
    assert main(["results", "--root", str(repo), "--inputs", "--rerun"]) == 0
    assert capsys.readouterr().out == ""


def test_run_refuses_dirty_tree(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "inst.py").write_text(INSTRUMENT + "# changed\n")
    assert run(repo, "inst.py", "data.txt", "results/r.json") == 2
    assert "not clean: inst.py" in capsys.readouterr().err


def test_run_refuses_failing_command(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(repo, "missing.py", "data.txt", "results/m.json") == 2
    assert "exited" in capsys.readouterr().err
    assert not (repo / "results/m.json").exists()


def test_no_provenance(repo: Path) -> None:  # results that record no command
    (repo / "results/bare.json").write_text('{"responses": 1500}\n')
    assert audit(repo) == [("results/bare.json", 1, "results/no-provenance")]


def test_malformed_provenance(repo: Path) -> None:
    doc = json.loads((repo / "results/r.json").read_text())
    doc["provenance"]["now"] = "2026-03-02T00:00:00"  # boundary: no time zone
    (repo / "results/r.json").write_text(json.dumps(doc))
    assert audit(repo) == [("results/r.json", 1, "results/no-provenance")]


def test_stale_after_commit(repo: Path) -> None:  # known-positive
    (repo / "inst.py").write_text(INSTRUMENT + "# changed\n")
    commit(repo)
    [(file, _, rule)] = audit(repo)
    assert (file, rule) == ("results/r.json", "results/stale")


def test_stale_uncommitted(repo: Path) -> None:  # boundary: the change is not committed yet
    (repo / "inst.py").write_text(INSTRUMENT + "# changed\n")
    assert [r for _, _, r in audit(repo)] == ["results/stale"]


def test_other_files_do_not_make_stale(repo: Path) -> None:
    (repo / "README").write_text("notes\n")
    commit(repo)
    assert audit(repo) == []


DEPENDS = '\n[[results.depends]]\nfile = "results/r.json"\ninstruments = ["inst.py"]\n'


def test_depends_scopes_staleness(repo: Path) -> None:
    (repo / "other.py").write_text("print('{}')\n")
    commit(repo)
    assert [r for _, _, r in audit(repo)] == ["results/stale"]  # every instrument by default
    (repo / "audit.toml").write_text(AUDIT + DEPENDS)
    assert audit(repo) == []                                    # known-negative: not its own
    (repo / "inst.py").write_text(INSTRUMENT + "# changed\n")
    assert [r for _, _, r in audit(repo)] == ["results/stale"]  # known-positive: its own


def test_depends_scopes_run(repo: Path) -> None:
    (repo / "audit.toml").write_text(AUDIT + DEPENDS)
    (repo / "other.py").write_text("print('{}')\n")
    commit(repo)
    (repo / "other.py").write_text("print('{\"x\": 1}')\n")  # dirty, but not an instrument of r
    assert run(repo, "inst.py", "data.txt", "results/r.json") == 0


def test_depends_unused(repo: Path) -> None:  # boundary: an entry for a file that is gone
    (repo / "audit.toml").write_text(AUDIT + DEPENDS.replace("r.json", "gone.json"))
    assert audit(repo) == [("audit.toml", 8, "results/unused")]


def test_input_changed_and_missing(repo: Path) -> None:
    (repo / "data.txt").write_text("a\nb\nc\nd\n")
    assert [r for _, _, r in audit(repo)] == []  # static by default
    assert [r for _, _, r in audit(repo, "--inputs")] == ["results/input-changed"]
    (repo / "data.txt").unlink()
    assert [r for _, _, r in audit(repo, "--inputs")] == ["results/input-missing"]


def test_rerun_detects_clock(repo: Path) -> None:  # an age against the time of analysis
    (repo / "clock.py").write_text(CLOCK_INSTRUMENT)
    commit(repo)
    assert [r for _, _, r in audit(repo)] == ["results/stale"]  # a new instrument: rerun all
    assert run(repo, "inst.py", "data.txt", "results/r.json") == 0
    assert run(repo, "clock.py", "data.txt", "results/c.json") == 0
    commit(repo)
    assert audit(repo) == []
    assert audit(repo, "--rerun") == [("results/c.json", 3, "results/not-reproduced")]


def test_rerun_detects_changed_output(repo: Path) -> None:
    doc = json.loads((repo / "results/r.json").read_text())
    doc["lines"] = 4  # a number edited by hand
    (repo / "results/r.json").write_text(json.dumps(doc, indent=1))
    found = audit(repo, "--rerun")
    assert [r for _, _, r in found] == ["results/not-reproduced"]


@pytest.mark.parametrize("line,rules", [
    ("now = datetime.now(UTC)", ["results/wall-clock"]),               # known-positive
    ("t = time.time()", ["results/wall-clock"]),
    ("d = date.today()", ["results/wall-clock"]),
    ("now = datetime.fromtimestamp(Path(p).stat().st_mtime)", ["results/wall-clock"]),  # file time
    ("m = os.path.getmtime(p)", ["results/wall-clock"]),
    ("now = datetime.fromisoformat(os.environ['OSAUDIT_NOW'])", []),   # known-negative
    ("# datetime.now() would be wrong here", []),
    ("t = time.localtime(stamp)", []),                                  # boundary: not the clock
    ("now = datetime.now(UTC)  # osaudit: allow results/wall-clock -- replay time, recorded",
     []),
    ("now = datetime.now(UTC)  # osaudit: allow results/wall-clock", ["results/wall-clock"]),
    ("x = 1  # osaudit: allow results/wall-clock -- stale", ["results/unused"]),
])
def test_wall_clock(repo: Path, line: str, rules: list[str]) -> None:
    (repo / "probe.py").write_text(f"import time\n{line}\n")
    found = [(f, n, r) for f, n, r in audit(repo) if f == "probe.py"]
    assert found == [("probe.py", 2, r) for r in rules]


def test_manual_results(repo: Path) -> None:
    (repo / "results/review.json").write_text('{"verdicts_checked": 20, "owner_agrees": 20}\n')
    toml = repo / "audit.toml"
    toml.write_text(AUDIT + '\n[[results.manual]]\nfile = "results/review.json"\nby = "M"\n'
                    'date = "2026-10-17"\nreason = "the author checked 20 labels"\n')
    assert audit(repo) == []
    toml.write_text(toml.read_text().replace("results/review.json", "results/gone.json"))
    assert sorted(r for _, _, r in audit(repo)) == ["results/no-provenance", "results/unused"]


def test_manual_needs_reason(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "audit.toml").write_text(AUDIT + '\n[[results.manual]]\nfile = "results/r.json"\n')
    assert main(["results", "--root", str(repo)]) == 2
    assert "by, date, reason mandatory" in capsys.readouterr().err


def test_directory_hash(tmp_path: Path) -> None:
    d = tmp_path / "store"
    (d / "a").mkdir(parents=True)
    (d / "a" / "s1.jsonl").write_text("x\n")
    before = sha256(d)
    assert sha256(d) == before                      # deterministic
    (d / "a" / "s2.jsonl").write_text("y\n")        # a live store gains a session
    assert sha256(d) != before


def test_not_a_repository(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "paper.tex").write_text("x\n")
    (tmp_path / "audit.toml").write_text(AUDIT)
    (tmp_path / "results").mkdir()
    (tmp_path / "inst.py").write_text("")
    (tmp_path / "results/r.json").write_text(json.dumps({"provenance": {
        "command": ["x"], "inputs": [{"path": "d", "sha256": "0" * 64}],
        "commit": "0" * 40, "now": "2026-01-01T00:00:00+00:00"}}))
    assert main(["results", "--root", str(tmp_path)]) == 2
    assert "git" in capsys.readouterr().err
