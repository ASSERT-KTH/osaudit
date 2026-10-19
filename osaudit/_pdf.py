"""Numbers printed in a PDF, with their page (reported as the line).

Text is extracted by `pdftotext` (poppler). Masked, as in LaTeX: quotes, numbered citations
(`[4, p. 317]`), references to parts (`Section 4.3`), list labels (`(4) Codification`), and
lines holding only a number (page and section numbers). The reference list is skipped: from
the last line that reads only "References" to the end.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

from ._number import NUMBER, PART, Num, make

PDF_NUMBER = re.compile(NUMBER + r"(\s*%)?")
QUOTE = re.compile(r"“[^”]*”|``.*?''|\"[^\"\n]*\"", re.DOTALL)
CITATION = re.compile(r"\[\s*\d+(?:\s*[,–-]\s*\d+)*(?:\s*,\s*(?:pp?|ch|sec)\.\s*[\w.–-]+)?\s*\]")
LONE_NUMBER = re.compile(r"^[ \t]*[\d.]+[ \t]*$", re.MULTILINE)
LIST_LABEL = re.compile(r"^[ \t]*\(?\d+[.)][ \t]", re.MULTILINE)
REFERENCES = re.compile(r"^\s*(?:\d+\s+)?references\s*$", re.IGNORECASE | re.MULTILINE)


class PdfError(Exception):
    pass


def text_of(path: Path) -> str:
    exe = shutil.which("pdftotext")
    if exe is None:
        raise PdfError("pdftotext not found; install poppler-utils")
    r = subprocess.run([exe, "-layout", str(path), "-"], capture_output=True, text=True)
    if r.returncode != 0:
        raise PdfError(f"pdftotext failed on {path}: {r.stderr.strip()}")
    return r.stdout


def pages(text: str) -> list[str]:
    """The pages of `text` (form-feed separated), without the reference list."""
    refs = list(REFERENCES.finditer(text))
    if refs:
        text = text[: refs[-1].start()]
    return text.split("\f")


def numbers(file: str, text: str) -> Iterator[Num]:
    for page, body in enumerate(pages(text), 1):
        for pat in (QUOTE, CITATION, PART, LONE_NUMBER, LIST_LABEL):
            body = pat.sub(" ", body)
        for m in PDF_NUMBER.finditer(body):
            pct = m.group(3) is not None
            yield make(file, page, m.group(0).strip(), m.group(1), m.group(2), pct)
