"""`osaudit schema`: every structured data file names its schema URL; `run` writes it."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from osaudit._cli import main
from osaudit._config import AUDIT as AUDIT_URL
from osaudit._schema import DOCUMENT, LOG, PREREG, PROVENANCE

INSTRUMENT = "import json; print(json.dumps({'n': 3}))\n"
AUDIT = f"""\
schema = "{AUDIT_URL}"

[paper]
md = ["*.md"]

[results]
files = ["results/*.json"]
instruments = ["inst.py"]

[[results.manual]]
file = "results/manual.json"
by = "A. Author"
date = "2026-10-21"
reason = "checked by hand"
"""


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for d in ("results", "prereg", "explore"):
        (tmp_path / d).mkdir()
    (tmp_path / "audit.toml").write_text(AUDIT)
    (tmp_path / "inst.py").write_text(INSTRUMENT)
    (tmp_path / "data.txt").write_text("x\n")
    (tmp_path / "findings.md").write_text(f'+++\nschema = "{DOCUMENT}"\n+++\nNo numbers.\n')
    (tmp_path / "prereg/a.md").write_text(f'+++\nschema = "{PREREG}"\n+++\n')
    (tmp_path / "explore/b.md").write_text(f'+++\nschema = "{LOG}"\n+++\n')
    (tmp_path / "results/manual.json").write_text('{"n": 1}\n')
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "x")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OSAUDIT_NOW", "2026-10-21T00:00:00+00:00")
    assert main(["run", "--input", "data.txt", "-o", "results/r.json", "--",
                 sys.executable, "inst.py"]) == 0
    return tmp_path


def rules(root: Path) -> list[tuple[str, str]]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["schema", "--root", str(root), "--json"])
    return [(f["file"], f["rule"]) for f in json.loads(buf.getvalue())]


def test_run_writes_the_provenance_schema(repo: Path) -> None:
    assert json.loads((repo / "results/r.json").read_text())["provenance"]["schema"] == PROVENANCE


def test_every_file_with_its_schema_is_clean(repo: Path) -> None:  # known-negative
    assert rules(repo) == []  # the manual results file is exempt


def test_missing_schemas_are_reported(repo: Path) -> None:  # known-positive
    (repo / "findings.md").write_text("+++\ntask = 1\n+++\nNo numbers.\n")
    (repo / "prereg/a.md").write_text("# no front matter\n")
    (repo / "explore/b.md").write_text('+++\nmode = "exploratory"\n+++\n')
    doc = json.loads((repo / "results/r.json").read_text())
    del doc["provenance"]["schema"]
    (repo / "results/r.json").write_text(json.dumps(doc))
    assert rules(repo) == [("explore/b.md", "schema/missing"), ("findings.md", "schema/missing"),
                           ("prereg/a.md", "schema/missing"), ("results/r.json", "schema/missing")]


def test_wrong_kind_of_schema_is_unknown(repo: Path) -> None:  # boundary: a valid URL, wrong file
    (repo / "prereg/a.md").write_text(f'+++\nschema = "{LOG}"\n+++\n')
    assert rules(repo) == [("prereg/a.md", "schema/unknown")]


def test_markdown_without_front_matter_is_not_a_structured_file(repo: Path) -> None:
    (repo / "findings.md").write_text("Plain notes, 0.5.\n")
    assert rules(repo) == []


def test_audit_toml_without_schema_cannot_run(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "audit.toml").write_text(AUDIT.split("\n", 2)[2])  # drop the schema line
    assert main(["schema", "--root", str(repo)]) == 2
    assert "first line must be schema" in capsys.readouterr().err


def test_audit_toml_with_another_schema_cannot_run(repo: Path) -> None:
    (repo / "audit.toml").write_text(AUDIT.replace("audit-v1", "audit-v9"))
    assert main(["schema", "--root", str(repo)]) == 2
