"""Numbers printed by LaTeX sources, with their line.

What is not printed text, or not the paper's own claim, is masked before numbers are searched:
comments, pictures, verbatim quotes (audited as quotes), and the arguments of commands that
name files, labels, keys, URLs or layout.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ._number import NUMBER, PART, Num, make

# Number of brace arguments masked after the command; None masks every adjacent argument.
MASKED_ARGS: dict[str, int | None] = {
    **{c: None for c in (
        "input", "include", "label", "ref", "cref", "Cref", "autoref", "eqref", "pageref",
        "nameref", "url", "begin", "end", "usepackage", "documentclass", "bibliography",
        "bibliographystyle", "includegraphics", "hspace", "vspace", "setlength", "addtolength",
        "newcommand", "renewcommand", "newenvironment", "newtcolorbox", "usetikzlibrary",
        "rule", "resizebox", "scalebox", "color", "textcolor",
    )},
    "href": 1,
    "multicolumn": 2,
}
CITE = re.compile(r"\\[A-Za-z]*cite[A-Za-z]*\*?")
COMMAND = re.compile(r"\\([A-Za-z]+)\*?")
MASKED_ENVS = ("tikzpicture", "verbatim", "lstlisting", "minted")
COMMENT = re.compile(r"(?<!\\)%.*")
QUOTE = re.compile(r"``.*?''", re.DOTALL)
TEX_NUMBER = re.compile(NUMBER + r"(\s*\\%)?")


def _blank(s: str) -> str:
    return re.sub(r"[^\n]", " ", s)


def _group_end(text: str, i: int, open_: str, close_: str) -> int:
    """Index after the group opened at text[i], or -1 when unbalanced."""
    depth = 0
    j = i
    while j < len(text):
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == open_:
            depth += 1
        elif text[j] == close_:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return -1


def _args_end(text: str, i: int, n: int | None) -> int:
    """Index after the optional `[...]` and the first n (all when None) `{...}` arguments."""
    count = 0
    while i < len(text) and (n is None or count < n):
        j = i
        while j < len(text) and text[j] in " \t":
            j += 1
        if j < len(text) and text[j] == "[":
            end = _group_end(text, j, "[", "]")
        elif j < len(text) and text[j] == "{":
            end = _group_end(text, j, "{", "}")
            count += 1
        else:
            break
        if end < 0:
            break
        i = end
    return i


def mask(text: str) -> str:
    """The text with every non-claim region replaced by spaces, newlines kept."""
    text = COMMENT.sub(lambda m: _blank(m.group(0)), text)
    for env in MASKED_ENVS:
        pat = re.compile(rf"\\begin\{{{env}\*?\}}.*?\\end\{{{env}\*?\}}", re.DOTALL)
        text = pat.sub(lambda m: _blank(m.group(0)), text)
    text = QUOTE.sub(lambda m: _blank(m.group(0)), text)
    text = PART.sub(lambda m: _blank(m.group(0)), text)
    out = list(text)
    for m in COMMAND.finditer(text):
        name = m.group(1)
        if CITE.fullmatch(m.group(0)):
            n: int | None = None
        elif name in MASKED_ARGS:
            n = MASKED_ARGS[name]
        else:
            continue
        end = _args_end(text, m.end(), n)
        for k in range(m.end(), end):
            if out[k] != "\n":
                out[k] = " "
    return "".join(out)


def numbers(file: str, text: str) -> Iterator[Num]:
    masked = mask(text)
    for m in TEX_NUMBER.finditer(masked):
        line = masked.count("\n", 0, m.start()) + 1
        yield make(file, line, m.group(0).strip(), m.group(1), m.group(2), m.group(3) is not None)
