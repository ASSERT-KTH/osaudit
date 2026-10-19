"""`osaudit results`: every results file has a provenance that still holds.

Rules (static, the default, runnable without the inputs):
  results/no-provenance   a results file without a well-formed provenance block
  results/stale           an instrument changed since the commit the results record
  results/wall-clock      an instrument reads the clock (or a file time, the clock when the
                          file was written) instead of the recorded time anchor
  results/unused          an inline clock exemption on a line without a clock call, or a
                          [[results.manual]] or [[results.depends]] entry naming no results file

A results file is stale when one of its instruments changed: those of its [[results.depends]]
entry, or every instrument of [results] instruments.
With --inputs:
  results/input-missing   a recorded input does not exist
  results/input-changed   a recorded input no longer has its recorded sha256
With --rerun:
  results/not-reproduced  the recorded command, run again at the recorded time anchor, does
                          not print the same results

A clock call is exempt with `osaudit: allow results/wall-clock -- <reason>` in a comment on
the same line.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import _git, _provenance
from ._config import Config
from ._findings import Finding

CLOCK = re.compile(
    r"\b(?:datetime|date|Instant|LocalDate|LocalDateTime|Timestamp)\s*\.\s*(?:now|utcnow|today)"
    r"\s*\(|\btime\s*\.\s*(?:time|time_ns|localtime|gmtime|ctime)\s*\(\s*\)|\bDate\.now\s*\("
    r"|\bnew\s+Date\s*\(\s*\)|\bSystem\.currentTimeMillis\s*\("
    # A file time is the clock at the time the file was written: an anchor no one recorded.
    r"|\.st_[amc]time(?:_ns)?\b|\bget[amc]time\s*\(")
EXEMPT = re.compile(r"osaudit:\s*allow\s+results/wall-clock\b(?:\s*--\s*(\S.*))?")
COMMENT_LINE = re.compile(r"^\s*(?:#|//|\*|/\*)")


def wall_clock(cfg: Config) -> list[Finding]:
    out = []
    for f in cfg.instruments:
        try:
            lines = f.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(lines, 1):
            ex = EXEMPT.search(line)
            code = line[: ex.start()] if ex else line
            call = None if COMMENT_LINE.match(code) else CLOCK.search(code)
            if call and ex and ex.group(1):
                continue
            if call:
                why = "; the exemption needs a reason after --" if ex else (
                    f"; read the time anchor from ${_provenance.ENV_NOW} instead")
                out.append(Finding(cfg.rel(f), i, "results/wall-clock",
                                   f"{call.group(0).strip()} reads the clock or a file time{why}"))
            elif ex:
                out.append(Finding(cfg.rel(f), i, "results/unused",
                                   "wall-clock exemption on a line without a clock call"))
    return out


def _line_of_key(text: str, key: str) -> int:
    i = text.find(f'"{key}"')
    return text.count("\n", 0, i) + 1 if i >= 0 else 1


def _first_difference(a: Any, b: Any, path: str = "") -> str | None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}" if path else k
            d = _first_difference(a[k], b[k], f"{path}.{k}" if path else k)
            if d is not None:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path} (length {len(a)} against {len(b)})"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            d = _first_difference(x, y, f"{path}[{i}]")
            if d is not None:
                return d
        return None
    return None if a == b and type(a) is type(b) else (path or "(the whole document)")


def check(cfg: Config, inputs: bool = False, rerun: bool = False,
          timeout: float | None = None) -> list[Finding]:
    findings = wall_clock(cfg)
    manual = {m.file: m for m in cfg.manual}
    files = {cfg.rel(f): f for f in cfg.results}
    for kind, entries in (("manual", cfg.manual), ("depends", cfg.depends)):
        for e in entries:
            if e.file not in files:
                findings.append(Finding(cfg.rel(cfg.path), e.line, "results/unused",
                                        f"{kind} entry {e.file} names no results file"))
    for name, f in files.items():
        instruments = [cfg.rel(p) for p in cfg.instruments_of(name)]
        if name in manual:
            continue
        text = f.read_text()
        doc = json.loads(text)
        prov, why = _provenance.parse(doc)
        if prov is None:
            findings.append(Finding(name, 1, "results/no-provenance", why))
            continue
        line = _line_of_key(text, _provenance.KEY)
        _git.head(cfg.root)  # raises GitError outside a repository: the audit cannot run
        if not _git.has_commit(cfg.root, prov.commit):
            findings.append(Finding(name, line, "results/stale",
                                    f"commit {prov.commit[:12]} is not in the repository"))
        else:
            changed = _git.changed_since(cfg.root, prov.commit, instruments)
            if changed:
                findings.append(Finding(
                    name, line, "results/stale",
                    f"instruments changed since {prov.commit[:12]}: {', '.join(changed)}"))
        if inputs:
            for i in prov.inputs:
                p = prov.resolve(cfg.root, i["path"])
                if not p.exists():
                    findings.append(Finding(name, line, "results/input-missing", i["path"]))
                elif _provenance.sha256(p) != i["sha256"]:
                    findings.append(Finding(name, line, "results/input-changed",
                                            f"{i['path']} no longer has sha256 {i['sha256'][:12]}"))
        if rerun:
            try:
                again = _provenance.execute(prov.command, prov.resolve(cfg.root, prov.cwd),
                                            prov.now, timeout)
            except _provenance.RunError as e:
                findings.append(Finding(name, line, "results/not-reproduced", str(e)))
                continue
            recorded = {k: v for k, v in doc.items() if k != _provenance.KEY}
            again.pop(_provenance.KEY, None)
            d = _first_difference(recorded, again)
            if d is not None:
                findings.append(Finding(name, line, "results/not-reproduced",
                                        f"rerun of {' '.join(prov.command)} differs at {d}"))
    return sorted(findings, key=lambda f: (f.file, f.line, f.rule, f.message))
