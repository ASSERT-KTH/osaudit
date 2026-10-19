"""Numbers extracted from LaTeX and from PDF text: claims kept, layout and references masked."""

from __future__ import annotations

from osaudit import _pdf, _tex


def tex(text: str) -> list[str]:
    return [n.text for n in _tex.numbers("f.tex", text)]


def pdf(text: str) -> list[str]:
    return [n.text for n in _pdf.numbers("f.pdf", text)]


def test_tex_claims_kept() -> None:  # known-positive
    assert tex("Of the 1,500 responses, 1,204 (80.3\\%) are complete.") == [
        "1,500", "1,204", "80.3\\%"]
    assert tex("\\textbf{1,204} & 296 \\\\") == ["1,204", "296"]
    assert tex("ends a sentence with 1,204.") == ["1,204"]


def test_tex_layout_masked() -> None:  # known-negative
    assert tex("% 999 in a comment") == []
    assert tex("\\input{sections/05-method}\\label{sec:x2}\\cref{tab:t4}") == []
    assert tex("\\cite[p.~107]{doe2001} and \\citep[ch.~3]{x}") == []
    assert tex("\\begin{tabular}{@{}lrr@{}}\\multicolumn{2}{@{}l}{Total}") == []
    assert tex("\\begin{tikzpicture}\\node at (90:2.9) {x};\\end{tikzpicture}") == []
    assert tex("Answer \\texttt{123d0d04}, RQ1, 3.0cm, \\\\[-2pt]") == []
    assert tex("``as of July 2023, over 16 billion forms were filed''") == []
    assert tex("\\href{https://x.org/v2/1234}{the site}") == []
    assert tex("see Table~1 and Section 4.3") == []


def test_tex_boundary() -> None:
    assert tex("100\\% not a comment") == ["100\\%"]
    assert tex("\\href{https://x.org/1234}{version 5678}") == ["5678"]
    assert tex("5.1.1") == []
    lines = [n.line for n in _tex.numbers("f.tex", "a\n``quote\n12''\n\n34\n")]
    assert lines == [5]


def test_pdf_pages_and_masks() -> None:
    text = (
        "9\n"                                            # page number
        "5.1\n"                                          # section number
        "Tool A2 (1,792), Tool B4 (573) [40, 42].\n"
        "(4) Analysis. As said in [4, p. 317] and [16, p. xiii].\n"
        "\f"
        "Of these, 67.4% are complete, “16 billion” quoted, see Section 4.3.\n"
        "References\n"
        "[1] A. Author. 2023. Title. 12(3):45-67.\n"
    )
    nums = list(_pdf.numbers("f.pdf", text))
    assert [(n.line, n.text) for n in nums] == [(1, "1,792"), (1, "573"), (2, "67.4%")]
    assert nums[2].percent
