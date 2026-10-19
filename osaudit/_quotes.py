"""`osaudit quotes`: every cited verbatim quote is in a verified `[[quotes]]` entry.

Rules:
  quotes/no-entry    a quote whose citation key has no entry (PDF: no entry holds its text)
  quotes/mismatch    entries for the key exist, none holds the quote's text verbatim
  quotes/page        the cited page is not the entry's page, or a page is given for an abstract
  quotes/no-page     an entry read in a paged version records no page
  quotes/unverified  an entry whose status is not verified
  quotes/unused      an entry that matches no quote of the paper

A quote is ``...'' (LaTeX) or “...” (PDF) with a citation in the same sentence: the nearest
after it, else the nearest before (`As \\citet{k} wrote, ``...''`). Its page is the `p.~X`
argument of that citation. A PDF citation is numbered, so a PDF quote matches any entry by
text. Text is compared after normalization (LaTeX unwrapped, dashes, quotes, spaces, case);
`[...]` or an ellipsis in the paper's quote matches any gap, the pieces in order. A quote may
be a part of the entry's sentence, which is why the entry holds the full sentence.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterator
from dataclasses import dataclass

from . import _pdf
from ._config import Config, Quote
from ._findings import Finding

TEX_COMMENT = re.compile(r"(?<!\\)%.*")
TEX_QUOTE = re.compile(r"``(.*?)''", re.DOTALL)
PDF_QUOTE = re.compile(r"“([^”]*)”|``(.*?)''", re.DOTALL)
TEX_CITE = re.compile(
    r"\\[A-Za-z]*cite[A-Za-z]*\*?\s*(?:\[([^\]]*)\])?\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}")
PDF_CITE = re.compile(r"\[\s*\d+(?:\s*[,–-]\s*\d+)*(?:\s*,\s*([^\]]*))?\]")
PARAGRAPH = re.compile(r"\n[ \t]*\n")
ABBREVIATIONS = frozenset({"e.g", "i.e", "al", "p", "pp", "fig", "sec", "cf", "vs", "etc", "ch",
                           "vol", "no", "eq", "ed", "eds"})
SENTENCE_END = re.compile(r"(\S*?)[.!?](?=\s)")
PAGE = re.compile(r"\b(?:pp?|pages?)\.?(?:\s|~)*([\w]+(?:\s*[-–]+\s*[\w]+)?)", re.IGNORECASE)
TYPOGRAPHY: dict[int, str | None] = {
    ord(c): r for c, r in {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                           "`": "'", "\u00a0": " ", "{": None, "}": None}.items()}
GAP = re.compile(r"\[\s*(?:\.\s*){3}\]|\[\s*…\s*\]|\\l?dots(?:\{\})?|…|(?:\.\s*){3}")


@dataclass(frozen=True)
class PaperQuote:
    file: str
    line: int
    text: str
    keys: tuple[str, ...]  # empty for a PDF: numbered citations name no key
    page: str | None


def _ends_sentence(segment: str) -> bool:
    return any(m.group(1).lstrip("([{~").lower() not in ABBREVIATIONS
               for m in SENTENCE_END.finditer(segment))


def _page(optargs: list[str | None]) -> str | None:
    for arg in reversed([a for a in optargs if a]):
        m = PAGE.search(arg)
        if m:
            return m.group(1)
    return None


def _blank(m: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def tex_quotes(file: str, text: str) -> Iterator[PaperQuote]:
    text = TEX_COMMENT.sub(_blank, text)
    for para in _paragraphs(text):
        start, body = para
        quotes = list(TEX_QUOTE.finditer(body))
        cites = list(TEX_CITE.finditer(body))
        for q in quotes:
            cite = None
            after = [c for c in cites if c.start() >= q.end()]
            if after and not _ends_sentence(_strip_quotes(body[q.end():after[0].start()])):
                cite = after[0]
            else:
                before = [c for c in cites if c.end() <= q.start()]
                if before and not _ends_sentence(_strip_quotes(body[before[-1].end():q.start()])):
                    cite = before[-1]
            if cite is None:
                continue
            keys = tuple(k.strip() for k in cite.group(3).split(",") if k.strip())
            line = text.count("\n", 0, start + q.start()) + 1
            yield PaperQuote(file, line, q.group(1), keys, _page([cite.group(1), cite.group(2)]))


def _strip_quotes(s: str) -> str:
    return TEX_QUOTE.sub(" ", s)


def _paragraphs(text: str) -> Iterator[tuple[int, str]]:
    pos = 0
    for m in PARAGRAPH.finditer(text):
        yield pos, text[pos:m.start()]
        pos = m.end()
    yield pos, text[pos:]


def pdf_quotes(file: str, text: str) -> Iterator[PaperQuote]:
    for page, body in enumerate(_pdf.pages(text), 1):
        body = re.sub(r"-\n\s*", "", body)
        for q in PDF_QUOTE.finditer(body):
            rest = body[q.end():]
            c = PDF_CITE.search(rest)
            if c is None or _ends_sentence(rest[:c.start()]):
                continue
            quoted = q.group(1) if q.group(1) is not None else q.group(2)
            yield PaperQuote(file, page, quoted, (), _page([c.group(1)]))


def paper_quotes(cfg: Config) -> Iterator[PaperQuote]:
    for f in cfg.tex:
        yield from tex_quotes(cfg.rel(f), f.read_text())
    if cfg.pdf is not None:
        yield from pdf_quotes(cfg.rel(cfg.pdf), _pdf.text_of(cfg.pdf))


def normalize(s: str) -> str:
    """Text as compared: LaTeX unwrapped, typography and spacing unified, case folded."""
    prev = None
    while prev != s:
        prev, s = s, re.sub(r"\\[A-Za-z]+\*?\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\([%&$#_])", r"\1", s)
    s = re.sub(r"\\[A-Za-z]+\*?", " ", s)
    s = s.replace("---", "—").replace("--", "–").replace("~", " ")
    s = s.translate(TYPOGRAPHY)
    s = s.replace("''", '"')
    return re.sub(r"\s+", " ", s).strip().casefold()


def _pieces(quote: str) -> list[str]:
    return [p for p in (normalize(x).strip(" .,;:") for x in GAP.split(quote)) if p]


def contains(entry_text: str, quote: str) -> bool:
    """The quote's pieces appear in the entry's text, in order."""
    text = normalize(entry_text)
    pos = 0
    for piece in _pieces(quote):
        i = text.find(piece, pos)
        if i < 0:
            return False
        pos = i + len(piece)
    return True


def _range(page: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"\s*(\d+)\s*(?:[-–]+\s*(\d+))?\s*", page)
    if not m:
        return None
    lo = int(m.group(1))
    return lo, int(m.group(2) or lo)


def same_page(cited: str, recorded: str) -> bool:
    """Equal pages, or overlapping numeric ranges (`p. 255` within `253-261`)."""
    a, b = _range(cited), _range(recorded)
    if a and b:
        return a[0] <= b[1] and b[0] <= a[1]
    return normalize(cited) == normalize(recorded)


def _closest(quote: str, entries: list[Quote]) -> Quote:
    q = normalize(quote)
    return max(entries, key=lambda e: difflib.SequenceMatcher(None, q, normalize(e.text)).ratio())


def check(cfg: Config) -> list[Finding]:
    toml = cfg.rel(cfg.path)
    findings: list[Finding] = []
    used: set[int] = set()
    for q in paper_quotes(cfg):
        short = " ".join(q.text.split())
        short = short if len(short) <= 60 else short[:57] + "..."
        if q.keys:
            pool = [e for e in cfg.quotes if e.key in q.keys]
            if not pool:
                findings.append(Finding(q.file, q.line, "quotes/no-entry",
                                        f"``{short}'' cites {', '.join(q.keys)}, "
                                        "which has no [[quotes]] entry"))
                continue
        else:
            pool = list(cfg.quotes)
        hits = [e for e in pool if contains(e.text, q.text)]
        if not hits:
            if not q.keys:
                findings.append(Finding(q.file, q.line, "quotes/no-entry",
                                        f"“{short}” is in no [[quotes]] entry"))
            else:
                c = _closest(q.text, pool)
                findings.append(Finding(q.file, q.line, "quotes/mismatch",
                                        f"``{short}'' is not verbatim in the entry of {c.key} "
                                        f"(closest: {toml}:{c.line})"))
            continue
        e = hits[0]
        used.update(id(h) for h in hits)
        if q.page is None:
            continue
        if e.version == "abstract":
            findings.append(Finding(q.file, q.line, "quotes/page",
                                    f"p. {q.page} cited, but {e.key} was read in its abstract "
                                    f"only ({toml}:{e.line})"))
        elif e.page is not None and not same_page(q.page, e.page):
            findings.append(Finding(q.file, q.line, "quotes/page",
                                    f"p. {q.page} cited, the entry of {e.key} records p. "
                                    f"{e.page} ({toml}:{e.line})"))
    for e in cfg.quotes:
        if e.status != "verified":
            findings.append(Finding(toml, e.line, "quotes/unverified",
                                    f"{e.key}: {e.status}, do not quote before it is verified"))
        if e.page is None and e.version != "abstract":
            findings.append(Finding(toml, e.line, "quotes/no-page",
                                    f"{e.key}: read in its {e.version} version, but no page"))
        if e.page is not None and e.version == "abstract":
            findings.append(Finding(toml, e.line, "quotes/page",
                                    f"{e.key}: an abstract has no page, {e.page} recorded"))
        if id(e) not in used:
            findings.append(Finding(toml, e.line, "quotes/unused",
                                    f"{e.key}: the entry matches no quote of the paper"))
    return sorted(findings, key=lambda f: (f.file, f.line, f.rule, f.message))
