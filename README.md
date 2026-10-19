# osaudit

Automated open-science audit: report every claim of a scientific paper that is not traced, mechanically, to the evidence that supports it. A number to a results file, a quote to a page of a verified source, a result to the instrument and the input that produced it. Silent when everything is traced.

What a paper repository must contain to be auditable is in [CONVENTIONS.md](CONVENTIONS.md).

## Install

    uv venv && uv pip install -e '.[dev]'

PDF input needs `pdftotext` (poppler-utils).

## Usage

In the paper repository, write `audit.toml`:

```toml
[paper]
tex = ["paper/sections/*.tex"]      # or: pdf = "paper/main.pdf"

[results]                           # optional: a paper without a study audits its quotes only
files = ["study/results/*.json"]
instruments = ["study/*.py"]        # the code that produces the results

[[results.depends]]                 # optional: what one results file depends on (default: all)
file = "study/results/survey.json"
instruments = ["study/survey.py", "study/_common.py"]

[[results.manual]]                  # a results file made by a person
file = "study/results/labels_check.json"
by = "A. Author"
date = "2026-10-17"
reason = "the author checked 20 labels of the classifier"

[[numbers.derive]]                  # a number computed from results values
value = "392"
expr = "panel.overall.total - panel.overall.answers.yes"

[[numbers.allow]]                   # a number the study does not produce
value = "2,000,000"
reason = "population size published by the cited census"
cite = "census2020"

[[quotes]]                          # a quote as read in its source
key = "doe2001archive"              # BibTeX key
text = "We call the archive the second memory of a laboratory, after the minds of its members."
version = "publisher"               # publisher|author-pdf|preprint|reprint|abstract|secondary
url = "https://doi.org/10.1000/doe2001"
page = "12"                         # omitted for an abstract
date = "2026-10-01"                 # read on
status = "verified"                 # verified|unverified
```

Then:

    osaudit                     # every check (static parts)
    osaudit numbers             # every printed number traced to results, derivation or allow
    osaudit quotes              # every cited quote verbatim in a verified [[quotes]] entry
    osaudit results             # every results file has a provenance that still holds
    osaudit results --inputs    # ... and its inputs still have their recorded sha256
    osaudit results --rerun     # ... and its command, rerun at its time anchor, prints the same
    osaudit CHECK --json        # a JSON array of findings, [] when clean
    osaudit CHECK --root PATH --config FILE

One line per finding, `file:line: rule: message` (for a PDF, the line is the page):

    paper/results.tex:6: numbers/untraced: 392 matches no results value, derivation or allow entry; candidate expr: panel.overall.total - panel.overall.answers.yes | survey.complete - panel.overall.answers.yes
    audit.toml:8: numbers/derive-mismatch: 70.0% declared, but ages.by_age["<30"].holds / ages.by_age["<30"].informative = 0.625, printed 62.5%
    paper.tex:2: quotes/mismatch: ``the only memory of a laboratory'' is not verbatim in the entry of doe2001archive (closest: audit.toml:4)
    study/results/survey.json:1: results/no-provenance: no 'provenance' block
    study/ages.py:12: results/wall-clock: datetime.now( reads the clock or a file time; read the time anchor from $OSAUDIT_NOW instead

Exit status: 0 clean, 1 findings, 2 the audit could not run (configuration, input).

### Producing results

Produce each results file through `osaudit run`, which records its provenance (command, inputs and their sha256, git commit, time anchor) in the file:

    osaudit run --input data/answers.csv -o study/results/survey.json -- python study/survey.py data/answers.csv

The instrument prints its results as a JSON object on stdout, and reads the time anchor from `$OSAUDIT_NOW` instead of the clock. Its instruments must be committed; `run` refuses otherwise. A clock read that is justified carries `# osaudit: allow results/wall-clock -- <reason>` on its line.

### Results values

The `provenance` block is not a result and is never matched. A value is named `<file stem>.<key>...`, with `["key"]` for keys that are not identifiers and `[i]` for list indices: `ages.by_age["<30"].share`. A printed number matches a value within half a unit of its last digit; a percent matches 100·v. Expressions allow `+ - * /`, parentheses and numeric constants, and are never evaluated as Python.

Candidates proposed for an untraced number are single operations over counts (sums, differences, shares), ranked by closeness in the results tree. They are hints: nothing is accepted until written into `audit.toml`.

### What is not audited as a number

LaTeX comments, `tikzpicture` and verbatim environments, verbatim quotes (` ``...'' `, audited as quotes), arguments of `\input \label \cref \cite \url \begin` and similar, parts of a document (`Section 4.3`, `Table~1`, `p.~107`), and numbers glued to a word (`123d0d04`, `3.0cm`, `RQ1`). In a PDF: numbered citations, list labels, lines holding only a number, and everything after the last "References" heading.

### Quotes

A quote is ` ``...'' ` with a citation in the same sentence (the nearest after it, else before it); its page is the `p.~X` of that citation. It must be verbatim, after normalization of LaTeX, typography and case, in the full sentence of an entry for that key; `[...]` marks a cut. In a PDF, citations are numbered, so a quote `“...”` matches any entry by its text.

## Status

`numbers`, `quotes`, `results` and `run` are implemented. References are checked by a separate tool, [check-hallucinations](https://github.com/ASSERT-KTH/check-hallucinations); cross-references and reviews are specified in CONVENTIONS.md and not built.

## License

MIT
