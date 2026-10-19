"""`osaudit numbers`: every number of the paper is a results value, a derivation, or allowed.

Rules:
  numbers/untraced         a printed number matches no results value, derivation or allow entry
  numbers/derive-mismatch  a derivation evaluates to another value than the one it declares
  numbers/derive-unknown   a derivation names a results value that does not exist
  numbers/unused           a derivation or allow entry matches no number of the paper
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator
from decimal import Decimal

from . import _pdf, _tex
from ._config import Config
from ._findings import Finding
from ._number import Num, close
from ._results import Results

MAX_CANDIDATES = 3


def paper_numbers(cfg: Config) -> Iterator[Num]:
    for f in cfg.tex:
        yield from _tex.numbers(cfg.rel(f), f.read_text())
    if cfg.pdf is not None:
        yield from _pdf.numbers(cfg.rel(cfg.pdf), _pdf.text_of(cfg.pdf))


def _printed(v: Decimal) -> str:
    return format(v.normalize(), "f") if v == v.to_integral_value() else format(v, ".6g")


def _shown(n: Num, v: Decimal) -> str:
    """`v` rounded as `n` is printed, for messages."""
    x = 100 * v if n.percent else v
    q = x.quantize(Decimal(10) ** -n.decimals)
    return f"{q:,}" + ("%" if n.percent else "")


def candidates(n: Num, values: dict[str, Decimal]) -> list[str]:
    """Up to MAX_CANDIDATES single-operation expressions over results values that print as `n`.

    Operands are counts (JSON integers): a sum or difference of counts, or a share of two counts.
    Expressions within one results file come first, then those whose operands are closest in
    the results tree (`survey.by_age.young.complete / survey.total`), then the shortest.
    """
    named = sorted((k, v) for k, v in values.items()
                   if not k.endswith(" (key)") and v.as_tuple().exponent == 0)
    by_value: dict[Decimal, list[str]] = {}
    for k, v in named:
        by_value.setdefault(v, []).append(k)
    out: list[str] = []
    if not n.percent and n.decimals == 0:
        for a, va in named:
            for b in by_value.get(va - n.value, []):
                out.append(f"{a} - {b}")
            for b in by_value.get(n.value - va, []):
                if a < b:
                    out.append(f"{a} + {b}")
    else:
        for a, va in named:
            for b, vb in named:
                if a != b and vb != 0 and close(n, va / vb):
                    out.append(f"{a} / {b}")
    def rank(e: str) -> tuple[int, int, int, str]:
        a, b = (re.split(r"[.\[]", x) for x in e.split(" ", 2)[::2])
        shared = len(os.path.commonprefix([a, b]))
        return (a[0] != b[0], len(a) + len(b) - 2 * shared, len(e), e)

    return sorted(out, key=rank)[:MAX_CANDIDATES]


def check(cfg: Config) -> list[Finding]:
    results = Results.load(list(cfg.results))
    values = list(results.values.values())
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
        if hits or any(close(n, v) for v in values):
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
    return sorted(findings, key=lambda f: (f.file, f.line, f.rule, f.message))


def render(findings: Iterable[Finding]) -> str:
    return "".join(f"{f}\n" for f in findings)
