"""The provenance block of a results file, and `osaudit run`, which writes it.

    "provenance": {
      "command": ["python", "study/survey.py", "data/answers.csv"],
      "cwd": ".",
      "inputs": [{"path": "data/answers.csv", "sha256": "e3b0..."}],
      "commit": "<40 hex: git HEAD, tree clean, when the command ran>",
      "now": "2026-10-19T10:00:00+00:00",
      "mode": "confirmatory",               # optional: confirmatory|exploratory
      "study": "prereg/2026-10-19-x.md",    # with mode: the pre-registration, or the log
      "osaudit": "0.2.0"
    }

`now` is the time anchor: the command runs with it in `OSAUDIT_NOW`, and an instrument reads it
instead of the clock, so a rerun computes the same ages. A directory input hashes as the sha256
of its manifest, one `relpath<TAB>sha256` line per file, sorted: a directory that changes
(a live log store) never matches its recorded hash.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__, _git

KEY = "provenance"
ENV_NOW = "OSAUDIT_NOW"
HEX64 = re.compile(r"[0-9a-f]{64}")
HEX40 = re.compile(r"[0-9a-f]{40}")
MODES = ("confirmatory", "exploratory")


class RunError(Exception):
    pass


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256(path: Path) -> str:
    """The sha256 of a file, or of the manifest of a directory."""
    if not path.is_dir():
        return _file_sha256(path)
    lines = sorted(f"{p.relative_to(path).as_posix()}\t{_file_sha256(p)}\n"
                   for p in path.rglob("*") if p.is_file())
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def _shown(path: Path, root: Path) -> str:
    """`path` relative to the repository when inside it, absolute otherwise."""
    path = path.resolve()
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


@dataclass(frozen=True)
class Provenance:
    command: list[str]
    cwd: str
    inputs: list[dict[str, str]]
    commit: str
    now: str
    mode: str | None = None
    study: str | None = None

    def resolve(self, root: Path, path: str) -> Path:
        p = Path(path)
        return p if p.is_absolute() else root / p


def parse(doc: Any) -> tuple[Provenance | None, str]:
    """The provenance of a results document, or None and what is wrong with it."""
    if not isinstance(doc, dict) or KEY not in doc:
        return None, f"no {KEY!r} block"
    p = doc[KEY]
    if not isinstance(p, dict):
        return None, f"{KEY!r} is not an object"
    cmd = p.get("command")
    if not (isinstance(cmd, list) and cmd and all(isinstance(c, str) for c in cmd)):
        return None, "command must be a non-empty list of strings"
    inputs = p.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        return None, "inputs must list every input, with its sha256"
    for i in inputs:
        if not (isinstance(i, dict) and isinstance(i.get("path"), str)
                and isinstance(i.get("sha256"), str) and HEX64.fullmatch(i["sha256"])):
            return None, f"input {i!r} must have a path and a 64-hex sha256"
    if not (isinstance(p.get("commit"), str) and HEX40.fullmatch(p["commit"])):
        return None, "commit must be the 40-hex git commit of the instruments"
    try:
        now = datetime.fromisoformat(p.get("now", ""))
    except (TypeError, ValueError):
        return None, "now must be an ISO 8601 time"
    if now.tzinfo is None:
        return None, "now must carry a time zone"
    mode, study = p.get("mode"), p.get("study")
    if mode is not None and mode not in MODES:
        return None, f"mode must be one of {', '.join(MODES)}"
    if study is not None and not (isinstance(study, str) and study):
        return None, "study must be the path of the pre-registration or exploration log"
    if mode is None and study is not None:
        return None, "study without a mode"
    return Provenance(cmd, str(p.get("cwd", ".")), inputs, p["commit"], p["now"],
                      mode, study), ""


def execute(cmd: list[str], cwd: Path, now: str, timeout: float | None = None) -> Any:
    """Run `cmd` with the time anchor and return its stdout parsed as a JSON object."""
    env = {**os.environ, ENV_NOW: now}
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, text=True,
                           timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RunError(f"{cmd[0]}: {e}") from e
    if r.returncode != 0:
        raise RunError(f"{' '.join(cmd)} exited {r.returncode}")
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise RunError(f"{' '.join(cmd)} printed no JSON object on stdout: {e}") from e
    if not isinstance(out, dict):
        raise RunError(f"{' '.join(cmd)} printed JSON that is not an object")
    return out


def run(root: Path, cmd: list[str], inputs: list[Path], output: Path,
        instruments: list[str] | None = None, mode: str | None = None, study: str | None = None,
        precheck: Callable[[Provenance], list[str]] | None = None) -> None:
    """Run an instrument and write its results with their provenance to `output`.

    The recorded commit holds only if the instruments are committed: those must be clean
    (every tracked file but `output` when no instruments are declared), while results files
    regenerated in the same session may be. `mode` and `study` label the run; `precheck`,
    given the provenance to be recorded, lists why the run must not happen (a confirmatory
    run that `osaudit study` would reject is refused before it sees the data).
    """
    root = root.resolve()
    if not inputs:
        raise RunError("declare every input with --input")
    for i in inputs:
        if not i.exists():
            raise RunError(f"input {i} does not exist")
    out_rel = _shown(output, root)
    dirty = [p for p in _git.dirty(root)
             if p != out_rel and (instruments is None or p in instruments)]
    if dirty:
        raise RunError(f"commit first, the tree is not clean: {', '.join(dirty[:5])}")
    now = os.environ.get(ENV_NOW) or datetime.now(UTC).isoformat(timespec="seconds")
    commit = _git.head(root)
    hashed = [{"path": _shown(i, root), "sha256": sha256(i)} for i in inputs]
    cwd = _shown(Path.cwd(), root)
    if precheck is not None:
        problems = precheck(Provenance(cmd, cwd, hashed, commit, now, mode, study))
        if problems:
            raise RunError("refused: " + "; ".join(problems))
    out = execute(cmd, Path.cwd(), now)
    labels = {"mode": mode, "study": study} if mode else {}
    out[KEY] = {"command": cmd, "cwd": cwd, "inputs": hashed, "commit": commit, "now": now,
                **labels, "osaudit": __version__}
    output.write_text(json.dumps(out, indent=1) + "\n")
