"""A number as printed in a paper, and when it matches a value."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

# A number not glued to a word, a path or a command: `123d0d04`, `3.0cm`, `RQ1` and `\\2` are not
# numbers. The lookahead refuses a trailing `.x`/`,x`, so backtracking cannot cut `3.0cm` to `3`.
NUMBER = r"(?<![\w.\\/])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![.,]?\w)"
# A number that names a part of a document, not a quantity: "Section 4.3", "Table~1", "p. 107".
PART = re.compile(
    r"\b(?:sections?|sec\.|tables?|tab\.|figures?|fig\.|definitions?|equations?|eq\.|appendix"
    r"|chapters?|ch\.|pages?|pp?\.)(?:\s|~)*\d+(?:\.\d+)*(?:\s*[-–]\s*\d+)?",
    re.IGNORECASE)
PRINTED = re.compile(r"\s*(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(\\?%)?\s*")


@dataclass(frozen=True)
class Num:
    """A printed number: `text` as in the paper, `value` without separators, d `decimals`."""

    file: str
    line: int
    text: str
    value: Decimal
    decimals: int
    percent: bool

    @property
    def key(self) -> tuple[Decimal, int, bool]:
        """What makes two printed numbers the same number (`1,204` and `1204`)."""
        return (self.value, self.decimals, self.percent)


def make(file: str, line: int, text: str, integer: str, frac: str | None, percent: bool) -> Num:
    digits = integer.replace(",", "") + (frac or "")
    return Num(file, line, text, Decimal(digits), len(frac) - 1 if frac else 0, percent)


def parse(text: str) -> Num | None:
    """Parse a value written in `audit.toml` (`"1,204"`, `"80.3%"`, `"80.3\\%"`)."""
    m = PRINTED.fullmatch(text)
    if not m:
        return None
    return make("", 0, text.strip(), m.group(1), m.group(2), m.group(3) is not None)


def close(num: Num, v: Decimal) -> bool:
    """`num` is `v` printed with its decimals: equal within half a unit of its last digit.

    A plain integer matches only an integral value: `7` is not a rounding of 7.2. A percent
    matches v as a share (100·v), or as a value already in percent when v is not a count (a
    JSON integer): `57.0%` is not the count 57.
    """
    half = Decimal(5) * Decimal(10) ** -(num.decimals + 1)
    if num.percent:
        in_percent = v.as_tuple().exponent != 0 and abs(num.value - v) <= half
        return abs(num.value - 100 * v) <= half or in_percent
    if num.decimals == 0:
        return v == v.to_integral_value() and v == num.value
    return abs(num.value - v) <= half
