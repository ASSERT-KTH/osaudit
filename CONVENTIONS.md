# Conventions of an automated open-science audit

A paper is auditable when every claim in it can be traced, mechanically, to the evidence that supports it.
This document states what a paper repository must contain, and in which format, so that `osaudit` can audit it.
Each rule is normative (MUST) and names the failure it prevents. Rule ids (`numbers/…`) are those printed by `osaudit`.

## Repository

- The repository root holds `audit.toml`, which declares where the paper, the results and the ledgers are. *Prevents: an audit that silently checks nothing because it looked in the wrong place.*
- The paper is LaTeX sources or a PDF. When both exist, the LaTeX sources are audited. *Prevents: auditing a stale PDF that no longer matches the sources.*
- Every machine-readable file of the audit (configuration, derivations, ledgers) is TOML. *Prevents: two parsers, two sets of quoting rules, two ways to be wrong.*
- An entry of `audit.toml` that matches nothing in the paper is a defect, and is reported. *Prevents: allow-lists and derivations that outlive the text they justified.*

## Numbers

- Every number printed in the paper is a results value, a declared derivation of results values, or an allow-list entry with a reason (`numbers/untraced`). *Prevents: an untraced number, such as a breakdown found in no results file, and different when recomputed.*
- Results are JSON files produced by a committed instrument; a value is named `<file stem>.<key>.<key>…`. *Prevents: numbers copied by hand from a terminal.*
- A printed number with d decimals matches a value v when it equals v, or 100·v for a percent, within half a unit of its last digit. *Prevents: false alarms on correct rounding (0.6745 printed 67.5%, or 67.4% when rounding half to even).*
- A number that is a sum, difference, product or share of results values is declared in `[[numbers.derive]]` with its expression (`value = "296"`, `expr = "survey.responses - survey.complete"`). *Prevents: derived numbers that no one can recompute, and a matcher that guesses derivations.*
- A declared derivation that evaluates to another value than the printed one is a defect (`numbers/derive-mismatch`). *Prevents: a number that drifted after the results were regenerated.*
- An expression that names a value absent from the results is a defect (`numbers/derive-unknown`). *Prevents: derivations over results that were renamed or removed.*
- A number that is not produced by the study (a year, a count published by a cited source, a parameter of the method) is allow-listed with `reason`, and with `cite` when it comes from a source (`[[numbers.allow]]`). *Prevents: an unexplained exemption.*
- A number taken from a cited source agrees with that source, verbatim. "Equals" is said only of equal numbers. *Prevents: a count claimed to equal a published count that differs from it in the fourth digit.*
- A number inside a verbatim quote is audited as part of the quote, not as a number. *Prevents: reporting a source's numbers as the study's.*
- Counts of parts add up to the whole that the text states, and each part is named ("8 runs: 6 pass, of which 1 with all tests skipped, 2 cannot start"). *Prevents: arithmetic that does not close.*
- The same quantity has the same value in every section; a different population is named and its difference explained ("1,204 of the 1,500 responses are complete, the 296 others are partial"). *Prevents: counts that silently differ across sections.*

## Results

- Every results file is a JSON object with a `provenance` block: `command` (argv), `cwd`, `inputs` (each `path` with its `sha256`), `commit` (git commit of the instruments), `now` (time anchor, ISO 8601 with time zone). `osaudit run` writes it (`results/no-provenance`). *Prevents: results that cannot be tied to the command and the data they claim to describe.*
- Results are produced from committed instruments: the instruments (`[results] instruments` in `audit.toml`) are unchanged since the recorded commit (`results/stale`). A results file that depends on only some of them declares them in `[[results.depends]]` (`file`, `instruments`). *Prevents: results of a version of the code that no longer exists, without rerunning every instrument for every change.*
- An input is a frozen snapshot: a directory input hashes as the manifest of its files, so a live directory (a log store that grows every day) never matches its record (`results/input-changed`, `results/input-missing`, with `--inputs`). *Prevents: results that no one can recompute, even with the same code.*
- Re-running the recorded command at the recorded time anchor prints the same results (`results/not-reproduced`, with `--rerun`). *Prevents: results that no instrument can produce any more, and numbers edited by hand.*
- An instrument never reads the clock or a file time: a time-dependent value (an age, a duration until now) is computed against the anchor in `$OSAUDIT_NOW`, recorded as `provenance.now` (`results/wall-clock`). A justified exception carries `osaudit: allow results/wall-clock -- <reason>` in a comment on the same line. *Prevents: values that shift between runs, such as ages computed against `now()` at analysis time, or against the modification time of a file.*
- A results file made by a person (a manual check of an automated classifier) is declared in `[[results.manual]]` with `file`, `by`, `date`, `reason`, and is exempt from provenance. *Prevents: a human judgment passed off as an instrument output, or rejected for not being one.*
- An exemption or a dependency entry that applies to nothing, inline or in `audit.toml`, is a defect (`results/unused`). *Prevents: exemptions that outlive the code they justified.*
- Every instrument is tested on a known-positive, a known-negative and a boundary case. *Prevents: trusting the numbers of an unvalidated instrument.*

## Quotes

- Every verbatim quote with a citation in the same sentence has an entry in the quote ledger, the `[[quotes]]` entries of `audit.toml` (`quotes/no-entry`). *Prevents: a quote no one checked.*
- A ledger entry records the citation `key`, the full sentence `text` verbatim, the `version` read (`publisher`, `author-pdf`, `preprint`, `reprint`, `abstract`, `secondary`), its `url`, the `page`, the `date` read and the `status` (`verified` or `unverified`), optionally the `claim` it supports. *Prevents: losing which text was actually read.*
- The quote of the paper is verbatim in the entry's text; `[...]` marks a cut (`quotes/mismatch`). *Prevents: a quote reworded, or attributed to a text that does not contain it.*
- The page cited is the page recorded (`quotes/page`), and an entry read in a paged version records its page (`quotes/no-page`). *Prevents: a page no one read.*
- Only a `verified` entry is quoted (`quotes/unverified`); an entry that matches no quote is removed (`quotes/unused`). *Prevents: quoting before checking, and a ledger that drifts from the paper.*
- A quote is `verified` only when its wording was matched against the version read; a summary by a search engine or a model is never a version read. *Prevents: a sentence that summaries attribute to an author, but that is not in the text.*
- The version read is the version cited; when they differ, the numbers and pages are those of the version cited, or the citation changes. *Prevents: citing a published version with the numbers of its preprint, which differ.*
- A quote from an abstract has no page and the ledger says `abstract`; a page read from a reprint is not the page of the original. *Prevents: invented page numbers.*
- A shortened quote keeps the scope of the full sentence; the ledger holds the full sentence. *Prevents: a truncated quote that widens the author's claim, such as a quote that drops "some of".*

## References

- A source is cited for a position it holds, not for one it refutes or does not address; the ledger entry records the claim the citation supports. *Prevents: citing a paper for the position it refutes, or a study of one measure for another measure.*
- Every cited BibTeX entry has a verification record (date, what was checked, against which source) and a DOI or a URL. *Prevents: references with invented fields.*
- Every cross-reference resolves, and the text names what it points to. *Prevents: text pointing to an example removed in an earlier revision.*

## Reviews

- Every finding of an automated reviewer is a claim, verified by a tool before it is acted on. *Prevents: changing the author's prose for a style defect that the reviewer reported and the prose checker does not confirm.*
- A verified finding is reported with the tool output that confirms it; an unconfirmed finding is reported as unconfirmed, never acted on. *Prevents: reviewer hallucinations entering the paper as corrections.*
