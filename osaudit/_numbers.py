"""`osaudit numbers`: every number of the paper is a results value, a derivation, or allowed.

Rules:
  numbers/untraced         a printed number matches no results value, derivation or allow entry
  numbers/derive-mismatch  a derivation evaluates to another value than the one it declares
  numbers/derive-unknown   a derivation names a results value that does not exist, or NaN/Infinity
  numbers/chance-match     a printed number matches a results value only directly, but the
                           results are so dense that most numbers printed like it match too
                           (more than CHANCE of its NEIGHBOURS): the match traces nothing, a
                           derivation naming the value does
  numbers/unused           a derivation or allow entry matches no number of the paper
  numbers/exploratory-unlabelled
                           a number traced to exploratory results (provenance mode, see
                           `osaudit study`) whose paragraph (in a PDF, page) does not say
                           "exploratory": a derivation is exploratory when any operand is, a
                           direct match when every matching value is
"""

from __future__ import annotations

import ast
import os
import re
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Iterator
from decimal import Decimal
from itertools import islice

from . import _md, _pdf, _study, _tex
from ._config import Config
from ._findings import Finding
from ._number import NEIGHBOURS, Num, Values, close
from ._results import Results

MAX_CANDIDATES = 3
MAX_EXPRESSIONS = 1000
# Above this many of its NEIGHBOURS matching a value, a direct match of a number is chance.
CHANCE = NEIGHBOURS // 2


def paper_numbers(cfg: Config) -> Iterator[Num]:
    for f in cfg.tex:
        yield from _tex.numbers(cfg.rel(f), f.read_text())
    if cfg.pdf is not None:
        yield from _pdf.numbers(cfg.rel(cfg.pdf), _pdf.text_of(cfg.pdf))
    for f in cfg.md:
        yield from _md.numbers(cfg.rel(f), f.read_text())


def _printed(v: Decimal) -> str:
    return format(v.normalize(), "f") if v == v.to_integral_value() else format(v, ".6g")


def _shown(n: Num, v: Decimal) -> str:
    """`v` rounded as `n` is printed, for messages."""
    x = 100 * v if n.percent else v
    q = x.quantize(Decimal(10) ** -n.decimals)
    return f"{q:,}" + ("%" if n.percent else "")


def _expressions(n: Num, named: list[tuple[str, Decimal]]) -> Iterator[str]:
    """The single-operation expressions over the counts `named` that print as `n`."""
    by_value: dict[Decimal, list[str]] = {}
    for k, v in named:
        by_value.setdefault(v, []).append(k)
    if not n.percent and n.decimals == 0:
        for a, va in named:
            for b in by_value.get(va - n.value, []):
                yield f"{a} - {b}"
            for b in by_value.get(n.value - va, []):
                if a < b:
                    yield f"{a} + {b}"
        return
    # The shares va / vb that `close` can accept lie within half a unit of n, or of n / 100
    # for a percent: look up the va of each vb in that range, not every pair.
    half = Decimal(5) * Decimal(10) ** -(n.decimals + 1)
    targets = [(n.value, half)] + ([(n.value / 100, half / 100)] if n.percent else [])
    distinct = sorted(by_value)
    for vb in distinct:
        if vb == 0:
            continue
        vas: set[Decimal] = set()
        for t, h in targets:
            lo, hi = sorted(((t - h) * vb, (t + h) * vb))
            vas.update(distinct[bisect_left(distinct, lo):bisect_right(distinct, hi)])
        for va in sorted(vas):
            if close(n, va / vb):
                yield from (f"{a} / {b}" for a in by_value[va] for b in by_value[vb] if a != b)


def candidates(n: Num, values: dict[str, Decimal]) -> list[str]:
    """Up to MAX_CANDIDATES single-operation expressions over results values that print as `n`.

    Operands are counts (JSON integers): a sum or difference of counts, or a share of two counts.
    Expressions within one results file come first, then those whose operands are closest in
    the results tree (`survey.by_age.young.complete / survey.total`), then the shortest.
    None when more than MAX_EXPRESSIONS print as `n`: the results are too dense to guess from.
    """
    named = sorted((k, v) for k, v in values.items()
                   if not k.endswith(" (key)") and v.as_tuple().exponent == 0)
    out = list(islice(_expressions(n, named), MAX_EXPRESSIONS + 1))
    if len(out) > MAX_EXPRESSIONS:
        return []

    def rank(e: str) -> tuple[int, int, int, str]:
        a, b = (re.split(r"[.\[]", x) for x in e.split(" ", 2)[::2])
        shared = len(os.path.commonprefix([a, b]))
        return (a[0] != b[0], len(a) + len(b) - 2 * shared, len(e), e)

    return sorted(out, key=rank)[:MAX_CANDIDATES]


def _stem(name: str) -> str:
    return re.split(r"[.\[ ]", name, maxsplit=1)[0]


def _expr_stems(expr: str) -> set[str]:
    """The results files an expression reads: the root name of each operand."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return set()
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def _contexts(cfg: Config) -> dict[str, list[str]]:
    """For each paper file, the text around each line: its paragraph (LaTeX, Markdown) or page
    (PDF)."""
    out: dict[str, list[str]] = {}
    for f in (*cfg.tex, *cfg.md):
        lines = f.read_text().splitlines()
        paragraphs, start = [], 0
        for i, line in enumerate([*lines, ""]):
            if not line.strip():
                paragraphs += ["\n".join(lines[start:i])] * (i - start + 1)
                start = i + 1
        out[cfg.rel(f)] = ["", *paragraphs]
    if cfg.pdf is not None:
        out[cfg.rel(cfg.pdf)] = ["", *_pdf.pages(_pdf.text_of(cfg.pdf))]
    return out


def exploratory_unlabelled(cfg: Config, results: Results) -> list[Finding]:
    modes = _study.modes(cfg)
    exploratory = {s for s, m in modes.items() if m == "exploratory"}
    if not exploratory:
        return []
    contexts = _contexts(cfg)
    out = []
    for n in paper_numbers(cfg):
        entries = [e for e in cfg.entries if e.covers(n)]
        if entries:
            stems = {s for e in entries if e.expr for s in _expr_stems(e.expr)}
            tainted = bool(stems & exploratory)
        else:
            stems = {_stem(k) for k, v in results.values.items() if close(n, v)}
            tainted = bool(stems) and stems <= exploratory
        if not tainted:
            continue
        lines = contexts.get(n.file, [])
        context = lines[n.line] if n.line < len(lines) else ""
        if "exploratory" not in context.lower():
            out.append(Finding(n.file, n.line, "numbers/exploratory-unlabelled",
                               f"{n.text} comes from exploratory results "
                               f"({', '.join(sorted(stems & exploratory))}); say so where it is "
                               "printed: its p-values and intervals are not calibrated"))
    return out


def check(cfg: Config) -> list[Finding]:
    results = Results.load(list(cfg.results))
    values = Values(results.values)
    toml = cfg.rel(cfg.path)
    findings: list[Finding] = []

    broken: set[int] = set()
    for i, e in enumerate(cfg.entries):
        if e.kind != "derive":
            continue
        assert e.expr is not None
        try:
            v = results.evaluate(e.expr)
        except ValueError as err:
            findings.append(Finding(toml, e.line, "numbers/derive-unknown", str(err)))
            broken.add(i)
            continue
        if not close(e.num, v):
            findings.append(Finding(
                toml, e.line, "numbers/derive-mismatch",
                f"{e.num.text} declared, but {e.expr} = {_printed(v)}, printed {_shown(e.num, v)}"))
            broken.add(i)

    # A broken entry still covers its number: the defect is reported once, on the entry.
    used: set[int] = set()
    for n in paper_numbers(cfg):
        hits = [i for i, e in enumerate(cfg.entries) if e.covers(n)]
        used.update(hits)
        if hits:
            continue
        if values.matches(n):
            if (chance := values.neighbours_matched(n)) > CHANCE:
                names = [k for k in values.names(n) if not k.endswith(" (key)")]
                names = names[:MAX_CANDIDATES]
                findings.append(Finding(
                    n.file, n.line, "numbers/chance-match",
                    f"{n.text} matches a results value, but so do {chance} of the {NEIGHBOURS} "
                    "numbers printed like it nearest to it: name its value in a "
                    "[[numbers.derive]]" + (", expr: " + " | ".join(names) if names else ""),
                    tuple(names)))
            continue
        cands = candidates(n, results.values)
        msg = f"{n.text} matches no results value, derivation or allow entry"
        if cands:
            msg += "; candidate expr: " + " | ".join(cands)
        findings.append(Finding(n.file, n.line, "numbers/untraced", msg, tuple(cands)))

    for i, e in enumerate(cfg.entries):
        if i not in used and i not in broken:
            where = f" in {e.file}" if e.file else ""
            findings.append(Finding(toml, e.line, "numbers/unused",
                                    f"{e.kind} {e.num.text} matches no number of the paper{where}"))
    findings += exploratory_unlabelled(cfg, results)
    return sorted(findings, key=lambda f: (f.file, f.line, f.rule, f.message))


def render(findings: Iterable[Finding]) -> str:
    return "".join(f"{f}\n" for f in findings)
