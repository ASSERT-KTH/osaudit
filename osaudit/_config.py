"""`audit.toml`: where the paper, the results and the instruments are, and how they are audited.

    [paper]
    tex = ["paper/sections/*.tex"]     # LaTeX sources, audited when present
    pdf = "paper/main.pdf"             # audited when no tex is declared
    md = ["findings-*.md"]             # Markdown documents, audited when they have TOML front
                                       # matter (+++ ... +++); others are skipped

    [results]
    files = ["study/results/*.json"]
    instruments = ["study/*.py"]       # the code that produces the results (staleness, clock)

    [[results.depends]]                # optional: the instruments one results file depends on
    file = "study/results/survey.json" # (default: every instrument)
    instruments = ["study/survey.py", "study/_common.py"]

    [[results.manual]]                 # a results file made by a person, not an instrument
    file = "study/results/labels_check.json"
    by = "A. Author"
    date = "2026-10-17"
    reason = "the author checked 20 labels of the classifier"

    [[numbers.derive]]
    value = "1,204"
    expr = "survey.responses - survey.partial"
    file = "paper/results.tex"         # optional: only there

    [[numbers.allow]]
    value = "2,000,000"
    reason = "population size published by the cited census"
    cite = "census2020"                # optional
    file = "paper/method.tex"          # optional

    [[quotes]]                         # a quote as read in its source
    key = "doe2001theory"              # BibTeX key
    text = "The full sentence, verbatim, of which the paper may quote a part."
    version = "publisher"              # publisher|author-pdf|preprint|reprint|abstract|secondary
    url = "https://doi.org/10.1000/xyz"
    page = "107"                       # omitted for an abstract
    date = "2026-10-17"                # read on
    status = "verified"                # verified|unverified
    claim = "what the citation supports"   # optional

    [study]                            # optional: the study directories (defaults shown)
    prereg = "prereg"
    explore = "explore"                # exploration logs: their data_seen counts as seen
    experiments = "experiments"
    results = "results"                # results files for `run`, when [results] files is absent
    report = ["REPORT.md", "NOTES.md", "README.md"]

`[results]` is optional: a paper without a study audits its quotes and references only.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._frontmatter import front_matter, span
from ._number import Num, parse


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    """A `[[numbers.derive]]` or `[[numbers.allow]]` entry; `line` is its header in audit.toml."""

    kind: str
    num: Num
    line: int
    file: str | None
    expr: str | None = None
    reason: str | None = None
    cite: str | None = None

    def covers(self, n: Num) -> bool:
        return n.key == self.num.key and (self.file is None or self.file == n.file)


@dataclass(frozen=True)
class Manual:
    """A `[[results.manual]]` entry: a results file made by a person."""

    file: str
    by: str
    date: str
    reason: str
    line: int


@dataclass(frozen=True)
class Depends:
    """A `[[results.depends]]` entry: the instruments one results file depends on."""

    file: str
    instruments: tuple[Path, ...]
    line: int


VERSIONS = ("publisher", "author-pdf", "preprint", "reprint", "abstract", "secondary")
STATUSES = ("verified", "unverified")


@dataclass(frozen=True)
class Quote:
    """A `[[quotes]]` entry: a quote as read in a source."""

    key: str
    text: str
    version: str
    url: str
    page: str | None
    date: str
    status: str
    claim: str | None
    line: int


@dataclass(frozen=True)
class Study:
    """`[study]`: where a study keeps its pre-registrations, logs, experiments, results, report.

    Shared with the research-agent hooks; every key is optional.
    """

    prereg: str = "prereg"
    explore: str = "explore"
    experiments: str = "experiments"
    results: str = "results"
    report: tuple[str, ...] = ("REPORT.md", "NOTES.md", "README.md")


def _study(raw: Any) -> Study:
    if not isinstance(raw, dict):
        raise ConfigError("study must be a table ([study])")
    for k, v in raw.items():
        if k not in Study.__dataclass_fields__:
            raise ConfigError(f"study.{k}: unknown key")
        if k == "report":
            if not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
                raise ConfigError("study.report must be a list of paths")
        elif not (isinstance(v, str) and v):
            raise ConfigError(f"study.{k} must be a directory path")
    report = tuple(raw.pop("report")) if "report" in raw else Study.report
    return Study(**raw, report=report)


@dataclass(frozen=True)
class Config:
    root: Path
    path: Path
    tex: tuple[Path, ...]
    pdf: Path | None
    results: tuple[Path, ...]
    entries: tuple[Entry, ...]
    instruments: tuple[Path, ...] = ()
    manual: tuple[Manual, ...] = ()
    depends: tuple[Depends, ...] = ()
    quotes: tuple[Quote, ...] = ()
    study: Study = Study()
    md: tuple[Path, ...] = ()

    def rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self.root))
        except ValueError:
            return str(p)

    def instruments_of(self, results_file: str) -> tuple[Path, ...]:
        """The instruments `results_file` depends on: its `[[results.depends]]`, or all."""
        for d in self.depends:
            if d.file == results_file:
                return d.instruments
        return self.instruments


def _glob(root: Path, patterns: Any, what: str) -> tuple[Path, ...]:
    if isinstance(patterns, str):
        patterns = [patterns]
    if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
        raise ConfigError(f"{what} must be a string or a list of strings")
    out: list[Path] = []
    for p in patterns:
        hits = sorted(root.glob(p))
        if not hits:
            raise ConfigError(f"{what}: {p!r} matches no file")
        out += hits
    return tuple(out)


def _header_lines(text: str, table: str) -> list[int]:
    pat = re.compile(rf"^[ \t]*\[\[[ \t]*{re.escape(table)}[ \t]*\]\]", re.MULTILINE)
    return [text.count("\n", 0, m.start()) + 1 for m in pat.finditer(text)]


def _entries(text: str, numbers: dict[str, Any], kind: str) -> list[Entry]:
    raw = numbers.get(kind, [])
    if not isinstance(raw, list):
        raise ConfigError(f"numbers.{kind} must be an array of tables ([[numbers.{kind}]])")
    lines = _header_lines(text, f"numbers.{kind}")
    out = []
    for i, e in enumerate(raw):
        line = lines[i] if i < len(lines) else 0
        where = f"audit.toml:{line}: numbers.{kind}"
        value = e.get("value")
        num = parse(value) if isinstance(value, str) else None
        if num is None:
            raise ConfigError(f"{where}: value must be a string, the number as printed")
        if kind == "derive" and not isinstance(e.get("expr"), str):
            raise ConfigError(f"{where}: expr is mandatory")
        if kind == "allow" and not str(e.get("reason", "")).strip():
            raise ConfigError(f"{where}: reason is mandatory")
        out.append(Entry(kind, num, line, e.get("file"), e.get("expr"), e.get("reason"),
                         e.get("cite")))
    return out


def load(root: Path, path: Path | None = None) -> Config:
    path = path or root / "audit.toml"
    if not path.is_file():
        raise ConfigError(f"{path}: no audit.toml (see https://github.com/ASSERT-KTH/assert-research-agent/blob/main/CONVENTIONS.md)")
    text = path.read_text()
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    paper = data.get("paper", {})
    tex = _glob(root, paper["tex"], "paper.tex") if "tex" in paper else ()
    md = _markdown(_glob(root, paper["md"], "paper.md")) if "md" in paper else ()
    pdf = None
    if not tex and ("pdf" in paper or "md" not in paper):
        if "pdf" not in paper:
            raise ConfigError(f"{path}: [paper] declares neither tex, pdf nor md")
        pdf = root / paper["pdf"]
        if not pdf.is_file():
            raise ConfigError(f"paper.pdf: {paper['pdf']!r} is not a file")
    res = data.get("results", {})
    results = _glob(root, res["files"], "results.files") if "files" in res else ()
    numbers = data.get("numbers", {})
    entries = _entries(text, numbers, "derive") + _entries(text, numbers, "allow")
    instruments = res.get("instruments", [])
    return Config(root, path, tex, pdf, results, tuple(entries),
                  _glob(root, instruments, "results.instruments") if instruments else (),
                  tuple(_manual(text, res.get("manual", []))),
                  tuple(_depends(root, text, res.get("depends", []))),
                  tuple(_quotes(text, data.get("quotes", []))),
                  _study(data.get("study", {})), md)


def _markdown(files: tuple[Path, ...]) -> tuple[Path, ...]:
    """The Markdown documents that are audited: those with TOML front matter, which must parse."""
    out = []
    for f in files:
        text = f.read_text()
        if not span(text):
            continue
        fm, why = front_matter(text)
        if fm is None:
            raise ConfigError(f"{f}: {why}")
        out.append(f)
    return tuple(out)


def study_context(root: Path) -> tuple[Study, list[Path]]:
    """`[study]` and the results files, for `osaudit run`, which may run before a paper exists.

    The results files are `[results] files` when declared, else every JSON file under
    `[study] results`.
    """
    path = root / "audit.toml"
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: {e}") from e
    study = _study(data.get("study", {}))
    files = data.get("results", {}).get("files")
    if files:
        return study, [p for pat in ([files] if isinstance(files, str) else files)
                       for p in sorted(root.glob(pat))]
    return study, sorted((root / study.results).rglob("*.json"))


def _quotes(text: str, raw: Any) -> list[Quote]:
    if not isinstance(raw, list):
        raise ConfigError("quotes must be an array of tables ([[quotes]])")
    lines = _header_lines(text, "quotes")
    out = []
    for i, e in enumerate(raw):
        line = lines[i] if i < len(lines) else 0
        where = f"audit.toml:{line}: quotes"
        missing = [k for k in ("key", "text", "version", "url", "date", "status")
                   if not str(e.get(k, "")).strip()]
        if missing:
            raise ConfigError(f"{where}: {', '.join(missing)} mandatory")
        if e["version"] not in VERSIONS:
            raise ConfigError(f"{where}: version must be one of {', '.join(VERSIONS)}")
        if e["status"] not in STATUSES:
            raise ConfigError(f"{where}: status must be one of {', '.join(STATUSES)}")
        page = e.get("page")
        out.append(Quote(e["key"], e["text"], e["version"], e["url"],
                         None if page is None else str(page), str(e["date"]), e["status"],
                         e.get("claim"), line))
    return out


def instruments(root: Path, output: str) -> list[str] | None:
    """The instruments `output` depends on, per `<root>/audit.toml`, relative to root; None if
    undeclared.

    For `osaudit run`, which may create the first results file, so `load` would refuse.
    """
    path = root / "audit.toml"
    if not path.is_file():
        return None
    text = path.read_text()
    try:
        results = tomllib.loads(text).get("results", {})
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    for d in _depends(root, text, results.get("depends", [])):
        if d.file == output:
            return [str(p.relative_to(root)) for p in d.instruments]
    if not results.get("instruments"):
        return None
    return [str(p.relative_to(root))
            for p in _glob(root, results["instruments"], "results.instruments")]


def _depends(root: Path, text: str, raw: Any) -> list[Depends]:
    if not isinstance(raw, list):
        raise ConfigError("results.depends must be an array of tables ([[results.depends]])")
    lines = _header_lines(text, "results.depends")
    out = []
    for i, e in enumerate(raw):
        line = lines[i] if i < len(lines) else 0
        if not isinstance(e.get("file"), str) or "instruments" not in e:
            raise ConfigError(f"audit.toml:{line}: results.depends: file, instruments mandatory")
        out.append(Depends(e["file"], _glob(root, e["instruments"], "results.depends"), line))
    return out


def _manual(text: str, raw: Any) -> list[Manual]:
    if not isinstance(raw, list):
        raise ConfigError("results.manual must be an array of tables ([[results.manual]])")
    lines = _header_lines(text, "results.manual")
    out = []
    for i, e in enumerate(raw):
        line = lines[i] if i < len(lines) else 0
        missing = [k for k in ("file", "by", "date", "reason") if not str(e.get(k, "")).strip()]
        if missing:
            raise ConfigError(f"audit.toml:{line}: results.manual: {', '.join(missing)} mandatory")
        out.append(Manual(e["file"], e["by"], str(e["date"]), e["reason"], line))
    return out
