"""`osaudit schema`: every structured data file names its schema URL.

The conventions make a `schema` key mandatory in every structured data file, set to the URL of
its JSON Schema in https://github.com/ASSERT-KTH/assert-research-agent (schemas/), so that
whoever finds a file finds its specification.

Rules:
  schema/missing  a structured data file has no `schema` key
  schema/unknown  its `schema` is not the URL of the schema for that kind of file

Files checked: results files (`provenance.schema`; manual ones exempt), audited Markdown
documents (front matter), pre-registrations (`[study] prereg/*.md`) and exploration logs
(`[study] explore/*.md`). A pre-registration or log without front matter is `schema/missing`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import _provenance
from ._config import Config
from ._findings import Finding
from ._frontmatter import front_matter

BASE = "https://github.com/ASSERT-KTH/assert-research-agent/blob/main/schemas/"
PREREG = BASE + "prereg-v1.json"
LOG = BASE + "exploration-log-v1.json"
DOCUMENT = BASE + "document-v1.json"
PROVENANCE = _provenance.SCHEMA


def problem(data: dict[str, Any] | None, expected: str, what: str) -> tuple[str, str] | None:
    """(rule, message) when `data` does not name `expected` as its schema."""
    url = (data or {}).get("schema")
    if url is None:
        return "schema/missing", f'{what} has no schema; add schema = "{expected}"'
    if url != expected:
        return "schema/unknown", f'{what} schema is {url!r}, expected "{expected}"'
    return None


def _markdown(cfg: Config, paths: list[Path], expected: str, what: str) -> list[Finding]:
    out = []
    for f in paths:
        fm, _ = front_matter(f.read_text())
        p = problem(fm, expected, what)
        if p:
            out.append(Finding(cfg.rel(f), 1, *p))
    return out


def check(cfg: Config) -> list[Finding]:
    findings: list[Finding] = []
    manual = {m.file for m in cfg.manual}
    for f in cfg.results:
        name = cfg.rel(f)
        if name in manual:
            continue
        text = f.read_text()
        doc = json.loads(text)
        prov = doc.get(_provenance.KEY) if isinstance(doc, dict) else None
        if not isinstance(prov, dict):
            continue  # reported by `results` as results/no-provenance
        p = problem(prov, PROVENANCE, "the provenance block")
        if p:
            i = text.find(f'"{_provenance.KEY}"')
            findings.append(Finding(name, text.count("\n", 0, i) + 1 if i >= 0 else 1, *p))
    findings += _markdown(cfg, list(cfg.md), DOCUMENT, "the front matter")
    findings += _markdown(cfg, sorted((cfg.root / cfg.study.prereg).glob("*.md")), PREREG,
                          "the pre-registration")
    findings += _markdown(cfg, sorted((cfg.root / cfg.study.explore).glob("*.md")), LOG,
                          "the exploration log")
    return sorted(findings, key=lambda f: (f.file, f.line, f.rule, f.message))
