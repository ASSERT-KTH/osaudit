"""The version is declared twice: CD releases pyproject.toml's, the CLI prints __version__."""

from __future__ import annotations

import tomllib
from pathlib import Path

from osaudit import __version__


def test_versions_agree() -> None:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    assert tomllib.loads(pyproject.read_text())["project"]["version"] == __version__
