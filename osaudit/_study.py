"""`osaudit study`: a CONFIRMATORY result is what it claims, proved from git alone.

A results file is confirmatory when its provenance says `"mode": "confirmatory"` and names its
pre-registration in `"study"`; exploratory with `"mode": "exploratory"` and its exploration log.
A file without a mode is unlabelled: never confirmatory, and its inputs count as seen.
Formats: CONVENTIONS.md of https://github.com/ASSERT-KTH/agentic-scientifc-method (Study).

Rules, for every confirmatory results file:
  study/not-preregistered  its pre-registration is absent at the recorded commit, or has no
                           valid front matter (hypothesis, data, alpha, m, ... missing)
  study/prereg-mismatch    the command runs no registered experiment, or an input is outside
                           the registered data
  study/amended            the pre-registration changed between its first commit and the run
                           without an [[amendments]] entry, or was amended after data was seen
  study/data-reused        an input was seen before: same sha256 as an input of a
                           non-confirmatory result, or overlapping a log's data_seen path
"""

from __future__ import annotations

import json
import posixpath
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import _git, _provenance
from ._config import Config, study_context
from ._findings import Finding

FRONT = re.compile(r"\A\+\+\+[ \t]*\n(.*?)\n\+\+\+[ \t]*(?:\n|\Z)", re.DOTALL)
MODES = ("confirmatory", "exploratory")
TEXT_FIELDS = ("hypothesis", "null", "statistic", "go", "stop", "disaster")
LIST_FIELDS = ("experiments", "data")
CORRECTIONS = ("holm", "bonferroni", "hochberg", "benjamini-hochberg", "none")


def front_matter(text: str) -> tuple[dict[str, Any] | None, str]:
    """The TOML front matter (between `+++` lines at the top) of a Markdown file."""
    m = FRONT.match(text)
    if not m:
        return None, "no TOML front matter (+++ ... +++ at the top)"
    try:
        return tomllib.loads(m.group(1)), ""
    except tomllib.TOMLDecodeError as e:
        return None, f"front matter: {e}"


def prereg_problems(fm: dict[str, Any]) -> list[str]:
    """What makes `fm` not a valid pre-registration front matter; [] when valid."""
    out = []
    if fm.get("mode") != "confirmatory":
        out.append('mode must be "confirmatory"')
    out += [f"{k} must be a non-empty string" for k in TEXT_FIELDS
            if not (isinstance(fm.get(k), str) and fm[k].strip())]
    out += [f"{k} must be a non-empty list of paths" for k in LIST_FIELDS
            if not (isinstance(fm.get(k), list) and fm[k]
                    and all(isinstance(p, str) and p for p in fm[k]))]
    alpha = fm.get("alpha")
    if not (isinstance(alpha, float) and 0 < alpha < 1):
        out.append("alpha must be a number in (0, 1)")
    m = fm.get("m")
    if not (isinstance(m, int) and not isinstance(m, bool) and m >= 1):
        out.append("m must be an integer >= 1, the number of tests")
    correction = fm.get("correction")
    if correction not in CORRECTIONS:
        out.append(f"correction must be one of {', '.join(CORRECTIONS)}")
    elif correction == "none" and isinstance(m, int) and m > 1:
        out.append(f'correction "none" with m = {m} tests')
    amendments = fm.get("amendments", [])
    if not isinstance(amendments, list):
        out.append("amendments must be an array of tables ([[amendments]])")
    else:
        for a in amendments:
            if not (isinstance(a, dict) and isinstance(a.get("data_seen"), bool)
                    and all(str(a.get(k, "")).strip() for k in ("date", "what", "why"))):
                out.append("each [[amendments]] needs date, data_seen (true/false), what, why")
                break
    return out


def within(a: str, b: str) -> bool:
    """Path `a` is `b`, or inside it."""
    a, b = posixpath.normpath(a), posixpath.normpath(b)
    return a == b or a.startswith(b + "/")


def overlaps(a: str, b: str) -> bool:
    """One path is the other, or contains it."""
    return within(a, b) or within(b, a)


@dataclass
class Seen:
    """Data already looked at: input hashes and paths, each with who saw it."""

    hashes: dict[str, str] = field(default_factory=dict)
    paths: list[tuple[str, str]] = field(default_factory=list)


def seen(root: Path, results: list[tuple[str, _provenance.Provenance]],
         explore_dir: str) -> Seen:
    out = Seen()
    logs = {p.relative_to(root).as_posix() for p in sorted((root / explore_dir).glob("*.md"))}
    for name, prov in results:
        if prov.mode == "confirmatory":
            continue
        for i in prov.inputs:
            out.hashes.setdefault(i["sha256"], name)
            out.paths.append((i["path"], name))
        if prov.study:
            logs.add(prov.study)
    for log in sorted(logs):
        try:
            fm, _ = front_matter((root / log).read_text())
        except OSError:
            continue
        if fm and fm.get("mode") == "exploratory" and isinstance(fm.get("data_seen"), list):
            out.paths += [(p, log) for p in fm["data_seen"] if isinstance(p, str)]
    return out


def confirmatory(root: Path, prov: _provenance.Provenance,
                 data_seen: Seen) -> list[tuple[str, str]]:
    """(rule, message) for every way `prov` fails to be a confirmatory result."""
    if not prov.study:
        return [("study/not-preregistered", 'mode "confirmatory" without a "study" file')]
    text = _git.show(root, prov.commit, prov.study)
    if text is None:
        return [("study/not-preregistered",
                 f"{prov.study} is not committed at {prov.commit[:12]}, the commit of the run")]
    fm, why = front_matter(text)
    if fm is None:
        return [("study/not-preregistered", f"{prov.study}: {why}")]
    problems = prereg_problems(fm)
    if problems:
        return [("study/not-preregistered", f"{prov.study}: {'; '.join(problems)}")]
    out = []
    if not any(overlaps(arg, e) for arg in prov.command for e in fm["experiments"]):
        out.append(("study/prereg-mismatch",
                    f"the command runs none of the experiments of {prov.study}: "
                    f"{', '.join(fm['experiments'])}"))
    for i in prov.inputs:
        if not any(within(i["path"], d) for d in fm["data"]):
            out.append(("study/prereg-mismatch",
                        f"input {i['path']} is not in the data of {prov.study}: "
                        f"{', '.join(fm['data'])}"))
    first = _git.first_commit(root, prov.study)
    first_text = _git.show(root, first, prov.study) if first else None
    if first_text is not None and first_text != text:
        first_fm, _ = front_matter(first_text)
        before = len((first_fm or {}).get("amendments", []))
        if len(fm.get("amendments", [])) <= before:
            out.append(("study/amended",
                        f"{prov.study} changed since its first commit {first[:12] if first else ''}"
                        " without an [[amendments]] entry"))
    for a in fm.get("amendments", []):
        if a["data_seen"]:
            out.append(("study/amended",
                        f"{prov.study} was amended on {a['date']} after data was seen: "
                        "the result is exploratory"))
    for i in prov.inputs:
        if i["sha256"] in data_seen.hashes:
            out.append(("study/data-reused",
                        f"input {i['path']} has the sha256 of an input of "
                        f"{data_seen.hashes[i['sha256']]}, which is not confirmatory"))
            continue
        hit = next(((p, who) for p, who in data_seen.paths if overlaps(i["path"], p)), None)
        if hit:
            out.append(("study/data-reused",
                        f"input {i['path']} overlaps {hit[0]}, seen by {hit[1]}"))
    return out


def precheck(root: Path, output: str) -> Callable[[_provenance.Provenance], list[str]]:
    """For `osaudit run`: why a labelled run must not happen, given the provenance it would record.

    Confirmatory: every rule of `confirmatory`, at HEAD, against the other results files, plus a
    clean pre-registration. Exploratory: the log exists.
    """
    root = root.resolve()
    study, files = study_context(root)

    def check(prov: _provenance.Provenance) -> list[str]:
        if prov.mode == "exploratory":
            ok = prov.study and (root / prov.study).is_file()
            return [] if ok else [f"no exploration log {prov.study}"]
        if prov.mode != "confirmatory":
            return []
        if prov.study and prov.study in _git.dirty(root):
            return [f"{prov.study} has uncommitted changes: commit the pre-registration first"]
        results = []
        for f in files:
            name = f.relative_to(root).as_posix()
            try:
                other, _ = _provenance.parse(json.loads(f.read_text()))
            except (OSError, ValueError):
                continue
            if other is not None and name != output:
                results.append((name, other))
        return [f"{rule}: {msg}" for rule, msg in
                confirmatory(root, prov, seen(root, results, study.explore))]

    return check


def load(cfg: Config) -> list[tuple[str, int, _provenance.Provenance]]:
    """Every results file with a valid provenance (others are reported by `results`)."""
    manual = {m.file for m in cfg.manual}
    out = []
    for f in cfg.results:
        name = cfg.rel(f)
        if name in manual:
            continue
        text = f.read_text()
        prov, _ = _provenance.parse(json.loads(text))
        if prov is not None:
            i = text.find(f'"{_provenance.KEY}"')
            out.append((name, text.count("\n", 0, i) + 1 if i >= 0 else 1, prov))
    return out


def modes(cfg: Config) -> dict[str, str | None]:
    """The mode of each results file, by file stem (the name its values are known by)."""
    found = {Path(name).stem: prov.mode for name, _, prov in load(cfg)}
    return {f.stem: found.get(f.stem) for f in cfg.results}


def check(cfg: Config) -> list[Finding]:
    results = load(cfg)
    data_seen = seen(cfg.root, [(n, p) for n, _, p in results], cfg.study.explore)
    findings = [Finding(name, line, rule, msg)
                for name, line, prov in results if prov.mode == "confirmatory"
                for rule, msg in confirmatory(cfg.root, prov, data_seen)]
    return sorted(findings, key=lambda f: (f.file, f.line, f.rule, f.message))
