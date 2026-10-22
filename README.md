# osaudit

Automated open-science audit: report every claim of a scientific paper that is not traced, mechanically, to the evidence that supports it. A number to a results file, a quote to a page of a verified source, a result to the instrument and the input that produced it. Silent when everything is traced.

What a repository must contain to be auditable is specified in the [conventions](https://github.com/ASSERT-KTH/assert-research-agent/blob/main/CONVENTIONS.md), shared with the [research agent](https://github.com/ASSERT-KTH/assert-research-agent), which enforces them while the work is done; `osaudit` checks them afterwards, from the repository alone.

## Install

    uv venv && uv pip install -e '.[dev]'

PDF input needs `pdftotext` (poppler-utils).

## Usage

In the paper repository, write `audit.toml`:

```toml
schema = "https://github.com/ASSERT-KTH/assert-research-agent/blob/main/schemas/audit-v1.json"   # mandatory, the first line

[paper]
tex = ["paper/sections/*.tex"]      # or: pdf = "paper/main.pdf"
md = ["findings-*.md"]              # Markdown documents with TOML front matter (others skipped)

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

[study]                             # optional: where the study keeps its files (defaults shown)
prereg = "prereg"
explore = "explore"
experiments = "experiments"
results = "results"
```

Then:

    osaudit                     # every check (static parts)
    osaudit numbers             # every printed number traced to results, derivation or allow
    osaudit quotes              # every cited quote verbatim in a verified [[quotes]] entry
    osaudit results             # every results file has a provenance that still holds
    osaudit results --inputs    # ... and its inputs still have their recorded sha256
    osaudit results --rerun     # ... and its command, rerun at its time anchor, prints the same
    osaudit study               # every confirmatory result pre-registered, unamended, on unseen data
    osaudit schema              # every structured data file names its schema URL
    osaudit CHECK --json        # a JSON array of findings, [] when clean
    osaudit CHECK --root PATH --config FILE

One line per finding, `file:line: rule: message` (for a PDF, the line is the page):

    paper/results.tex:6: numbers/untraced: 392 matches no results value, derivation or allow entry; candidate expr: panel.overall.total - panel.overall.answers.yes | survey.complete - panel.overall.answers.yes
    audit.toml:8: numbers/derive-mismatch: 70.0% declared, but ages.by_age["<30"].holds / ages.by_age["<30"].informative = 0.625, printed 62.5%
    paper.tex:2: quotes/mismatch: ``the only memory of a laboratory'' is not verbatim in the entry of doe2001archive (closest: audit.toml:4)
    study/results/survey.json:1: results/no-provenance: no 'provenance' block
    study/ages.py:12: results/wall-clock: datetime.now( reads the clock or a file time; read the time anchor from $OSAUDIT_NOW instead
    results/passrate.json:9: study/data-reused: input data/test/part.csv has the sha256 of an input of results/look.json, which is not confirmatory

Exit status: 0 clean, 1 findings, 2 the audit could not run (configuration, input).

### Producing results

Produce each results file through `osaudit run`, which records its provenance (command, inputs and their sha256, git commit, time anchor) in the file:

    osaudit run --input data/answers.csv -o study/results/survey.json -- python study/survey.py data/answers.csv

The instrument prints its results as a JSON object on stdout, and reads the time anchor from `$OSAUDIT_NOW` instead of the clock. Its instruments must be committed; `run` refuses otherwise. A clock read that is justified carries `# osaudit: allow results/wall-clock -- <reason>` on its line.

### Confirmatory and exploratory results

A run says which kind of result it produces, and the provenance records it (`mode`, `study`):

    osaudit run --prereg prereg/2026-10-21-passrate.md --input data/test -o results/passrate.json -- python experiments/passrate.py data/test
    osaudit run --explore explore/2026-10-20-look.md --input data/train.csv -o results/look.json -- python explore/look.py data/train.csv

A pre-registration and an exploration log are Markdown files with TOML front matter, in the formats of the conventions. `run --prereg` refuses, before the command sees any data, a run that `osaudit study` would reject. `osaudit study` then proves, for every confirmatory results file, from git alone:

- `study/not-preregistered`: its pre-registration is committed at the run's commit, with valid front matter (hypothesis, data, alpha, m, correction, ...);
- `study/prereg-mismatch`: the command runs a registered experiment, and every input is inside the registered data;
- `study/amended`: the registration did not change between its first commit and the run without an `[[amendments]]` entry, and no amendment was made after data was seen;
- `study/data-reused`: no input was seen before, as an input of an exploratory or unlabelled result (same sha256, under any name) or in an exploration log's `data_seen`.

A results file without a mode is unlabelled: never confirmatory, silent for these rules. When some results are exploratory, a printed number traced only to them (or a derivation with an exploratory operand) must say "exploratory" in its paragraph (in a PDF, its page): `numbers/exploratory-unlabelled`.

### Results values

The `provenance` block is not a result and is never matched. A value is named `<file stem>.<key>...`, with `["key"]` for keys that are not identifiers and `[i]` for list indices: `ages.by_age["<30"].share`. A printed number matches a value within half a unit of its last digit; a percent matches 100·v. `NaN` and `Infinity` are not values: nothing matches them, and an expression naming one is `numbers/derive-unknown`.

A match traces a number only if few numbers printed like it match too. Results that hold raw outputs (per-layer curves, per-example scores) hold so many values that any 2- or 3-decimal number in [0, 1] is within half a unit of one. When more than 50 of the 100 nearest numbers with the same decimals (and percent sign) also match a value, the direct match is `numbers/chance-match`: declare the number in `[[numbers.derive]]` with the name of its value (`expr = "raw.scores[420]"`; the closest values are proposed). Better, write results that hold the cited quantities, not the raw outputs. Expressions allow `+ - * /`, parentheses and numeric constants, and are never evaluated as Python.

Candidates proposed for an untraced number are single operations over counts (sums, differences, shares), ranked by closeness in the results tree. They are hints: nothing is accepted until written into `audit.toml`.

### What is not audited as a number

LaTeX comments, `tikzpicture` and verbatim environments, verbatim quotes (` ``...'' `, audited as quotes), arguments of `\input \label \cref \cite \url \begin` and similar, parts of a document (`Section 4.3`, `Table~1`, `p.~107`), and numbers glued to a word (`123d0d04`, `3.0cm`, `RQ1`). In a PDF: numbered citations, list labels, lines holding only a number, and everything after the last "References" heading.

### Markdown documents

A Markdown document (`[paper] md`, alone or with LaTeX or a PDF) is audited only when it starts with TOML front matter (`+++ ... +++`): the structured data marks it as a document whose numbers are meant to be traced, such as a findings file or a report. Without front matter it is skipped; front matter that does not parse stops the audit. Its numbers are audited as a paper's; not audited are the front matter itself (data, not prose), fenced and inline code, link and image targets, HTML comments, double-quoted text, dates (`2026-10-20`), parts of a document, list labels and table separator rows. In a range with one percent sign (`89–100%`), both ends are percents. The context of `numbers/exploratory-unlabelled` is the paragraph. Quotes are audited in LaTeX and PDF only.

### Quotes

A quote is ` ``...'' ` with a citation in the same sentence (the nearest after it, else before it); its page is the `p.~X` of that citation. It must be verbatim, after normalization of LaTeX, typography and case, in the full sentence of an entry for that key; `[...]` marks a cut. In a PDF, citations are numbered, so a quote `“...”` matches any entry by its text.

### Schema URLs

Every structured data file names its schema in a mandatory `schema` key, the URL of a JSON Schema in [assert-research-agent/schemas](https://github.com/ASSERT-KTH/assert-research-agent/tree/main/schemas): `audit.toml` itself (`audit-v1`; without it the audit cannot run, exit 2), the results `provenance` block (`osaudit run` writes it), the front matter of audited Markdown documents, pre-registrations (`[study] prereg/*.md`) and exploration logs (`[study] explore/*.md`). `osaudit schema` reports `schema/missing` and `schema/unknown` (a URL that is not the schema for that kind of file); `run --prereg` refuses a pre-registration without it.

## Release

Bump `version` in `pyproject.toml` and `osaudit/__init__.py` (a test checks they agree) and push to `main`. The publish workflow tests that commit, publishes it to PyPI, then tags it `v<version>` with a GitHub release. A push whose version is already tagged publishes nothing.

## Status

`numbers` (LaTeX, PDF, Markdown), `quotes` (LaTeX, PDF), `results`, `study`, `schema` and `run` are implemented. References are checked by a separate tool, [check-hallucinations](https://github.com/ASSERT-KTH/check-hallucinations); cross-references and reviews are specified in the [conventions](https://github.com/ASSERT-KTH/assert-research-agent/blob/main/CONVENTIONS.md) and not built.

## License

MIT
