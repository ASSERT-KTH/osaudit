"""Numbers printed by a Markdown document, with their line.

A Markdown document is audited only when it starts with TOML front matter (`+++ ... +++`): the
structured data marks it as a document whose claims are meant to be traced, as a findings file
or a report. A Markdown file without front matter is not audited.

What is not a claim of the document's prose is masked before numbers are searched, newlines
kept: the front matter itself (data, not prose), fenced and inline code, link and image targets,
HTML comments and tags, quotes in double quotes, dates (`2026-10-20`), references to parts
(`Section 4.3`, `Table 1`), list labels (`1. `) and table separator rows. In a range with one
percent sign (`89–100%`), both ends are percents.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ._frontmatter import span
from ._number import NUMBER, PART, Num, make

MD_NUMBER = re.compile(NUMBER + r"(\s*%)?")
FENCE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.DOTALL | re.MULTILINE)
INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1", re.DOTALL)
LINK_TARGET = re.compile(r"\]\([^)\n]*\)|<https?://[^>\n]*>|\bhttps?://\S+")
HTML = re.compile(r"<!--.*?-->|<[A-Za-z/][^>\n]*>", re.DOTALL)
QUOTE = re.compile(r"“[^”]*”|\"[^\"\n]*\"")
LIST_LABEL = re.compile(r"^[ \t]*\d+[.)][ \t]", re.MULTILINE)
TABLE_RULE = re.compile(r"^[ \t]*\|?[ \t:|-]+\|[ \t:|-]*$", re.MULTILINE)
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b")
# "89–100%": the percent sign applies to both ends of the range.
PERCENT_RANGE = re.compile(r"(\d+(?:\.\d+)?)(\s*[–-]\s*\d+(?:\.\d+)?\s*%)")


def _blank(m: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def audited(text: str) -> bool:
    """Whether a Markdown document is audited: it starts with TOML front matter."""
    return span(text) > 0


def mask(text: str) -> str:
    """The text with every non-claim region replaced by spaces, newlines kept."""
    n = span(text)
    text = re.sub(r"[^\n]", " ", text[:n]) + text[n:]
    for pat in (FENCE, HTML, INLINE_CODE, LINK_TARGET, QUOTE, DATE, PART, LIST_LABEL, TABLE_RULE):
        text = pat.sub(_blank, text)
    return PERCENT_RANGE.sub(lambda m: f"{m.group(1)}%{m.group(2)}", text)


def numbers(file: str, text: str) -> Iterator[Num]:
    if not audited(text):
        return
    masked = mask(text)
    for m in MD_NUMBER.finditer(masked):
        line = masked.count("\n", 0, m.start()) + 1
        yield make(file, line, m.group(0).strip(), m.group(1), m.group(2), m.group(3) is not None)
