"""`osaudit quotes` on a synthetic paper: each rule on a known-positive, negative and boundary."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from osaudit._cli import main
from osaudit._config import ConfigError, load
from osaudit._quotes import check, contains, normalize, pdf_quotes, same_page, tex_quotes

FIXTURE = Path(__file__).parent / "fixtures" / "quotes"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    return tmp_path


def rules(root: Path) -> list[tuple[str, int, str]]:
    return [(f.file, f.line, f.rule) for f in check(load(root))]


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def test_clean_is_silent(capsys: pytest.CaptureFixture[str]) -> None:  # known-negative
    assert main(["quotes", "--root", str(FIXTURE)]) == 0
    assert capsys.readouterr().out == ""


def quotes(tex: str) -> list[tuple[str, tuple[str, ...], str | None]]:
    return [(q.text, q.keys, q.page) for q in tex_quotes("f.tex", tex)]


def test_pairing_with_citation() -> None:
    assert quotes("X said ``a b'' \\cite{k}.") == [("a b", ("k",), None)]
    assert quotes("As \\citet{k} wrote, ``a b''.") == [("a b", ("k",), None)]
    assert quotes("``a b'' \\cite[p.~7]{k1,k2}.") == [("a b", ("k1", "k2"), "7")]
    assert quotes("``a b'' \\citep[see][pp.~3--5]{k}.") == [("a b", ("k",), "3--5")]
    assert quotes("``a b'' \\cite[ch.~3]{k}.") == [("a b", ("k",), None)]


def test_pairing_stays_in_the_sentence() -> None:  # boundary: the citation of the next sentence
    assert quotes("A ``scare quote'' here. Then \\cite{k} says so.") == []
    assert quotes("See \\cite{k}. A ``scare quote''.") == []
    assert quotes("``a'' e.g. \\cite{k}.") == [("a", ("k",), None)]  # an abbreviation is no end
    assert quotes("``a'' \\cite{k1}, while ``b'' \\cite{k2}.") == [
        ("a", ("k1",), None), ("b", ("k2",), None)]
    assert quotes("``a''\n\n\\cite{k}") == []  # a paragraph ends the sentence
    assert quotes("% ``a'' \\cite{k}\n") == []


def test_pdf_quotes() -> None:
    text = "He wrote “a notebook is read more often” [3, p. 12].\fA “scare” word. Then [4].\n"
    assert [(q.line, q.text, q.page) for q in pdf_quotes("f.pdf", text)] == [
        (1, "a notebook is read more often", "12")]


def test_normalize_and_gaps() -> None:
    assert normalize("a \\emph{Read}~text --- yes") == "a read text — yes"
    assert contains("Every measurement, however simple, carries its instrument.",
                    "every measurement [...] carries its instrument")
    assert contains("A b c d.", "a b \\ldots d")
    assert not contains("A b c d.", "a c b")           # pieces out of order
    assert not contains("A notebook is read.", "a notebook is written")
    assert contains("He said: “yes”.", "He said: ``yes''")


def test_same_page() -> None:
    assert same_page("255", "253-261") and same_page("3--5", "5")
    assert not same_page("12", "13") and same_page("xiii", "xiii")


def test_missing_entry(repo: Path) -> None:  # known-positive: a quote no one checked
    edit(repo / "paper.tex", "\\cite{moe2020}", "\\cite{zoe2021}")
    assert rules(repo) == [("audit.toml", 31, "quotes/unused"),
                           ("paper.tex", 7, "quotes/no-entry")]


def test_quote_not_in_source(repo: Path) -> None:  # a sentence the author never wrote
    edit(repo / "paper.tex", "the second memory of a laboratory", "the only memory of a laboratory")
    found = check(load(repo))
    assert [(f.file, f.line, f.rule) for f in found] == [
        ("audit.toml", 4, "quotes/unused"), ("paper.tex", 2, "quotes/mismatch")]
    assert "closest: audit.toml:4" in found[1].message


def test_wrong_page(repo: Path) -> None:
    edit(repo / "paper.tex", "p.~12", "p.~21")
    assert rules(repo) == [("paper.tex", 2, "quotes/page")]


def test_page_within_range(repo: Path) -> None:  # boundary: pp. 40--41 within 40-45
    assert ("paper.tex", 4, "quotes/page") not in rules(repo)
    edit(repo / "paper.tex", "pp.~40--41", "pp.~46--47")
    assert rules(repo) == [("paper.tex", 4, "quotes/page")]


def test_page_for_abstract(repo: Path) -> None:  # a page invented for an abstract
    edit(repo / "paper.tex", "\\cite{moe2020}", "\\cite[p.~5]{moe2020}")
    assert rules(repo) == [("paper.tex", 7, "quotes/page")]
    edit(repo / "audit.toml", 'version = "abstract"', 'version = "abstract"\npage = "5"')
    assert ("audit.toml", 31, "quotes/page") in rules(repo)


def test_entry_without_page(repo: Path) -> None:  # a transcription without page numbers
    edit(repo / "audit.toml", 'page = "3"\n', "")
    assert rules(repo) == [("audit.toml", 13, "quotes/no-page")]


def test_unverified(repo: Path) -> None:
    edit(repo / "audit.toml", 'status = "verified"', 'status = "unverified"')
    assert rules(repo) == [("audit.toml", 4, "quotes/unverified")]


def test_entry_fields_are_checked(repo: Path) -> None:
    edit(repo / "audit.toml", 'version = "publisher"', 'version = "web search"')
    with pytest.raises(ConfigError, match="version must be one of"):
        load(repo)
    shutil.copy(FIXTURE / "audit.toml", repo / "audit.toml")
    edit(repo / "audit.toml", 'url = "https://doi.org/10.1000/doe2001"\n', "")
    with pytest.raises(ConfigError, match="url mandatory"):
        load(repo)
