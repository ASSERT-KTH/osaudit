"""Markdown documents: audited only with TOML front matter; code, links, labels are not claims."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from osaudit._cli import main
from osaudit._config import ConfigError, load
from osaudit._md import audited, numbers

FINDINGS = """\
+++
task = "exp14"
models = 4
+++
# Aliasing (exp14)

1. **All four models get it wrong.** Accuracy is 0.69 on aliases.
2. See Table 2 and [the code](exp14_aliasing/gen_alias.py#L12), `assert len(a) == 3`.

```python
xs = [1, 2, 3]
```

| kind | 7B |
|---|---|
| alias | 0.69 |

<!-- generated: 2026-10-20 -->
A model said "0.42" once; the threshold was 0.5.
"""


def printed(text: str) -> list[tuple[int, str]]:
    return [(n.line, n.text) for n in numbers("f.md", text)]


def test_without_front_matter_nothing_is_audited() -> None:  # known-negative
    body = FINDINGS.split("+++\n", 2)[2]
    assert not audited(body) and printed(body) == []


def test_prose_and_tables_audited_rest_masked() -> None:  # known-positive
    # Front matter (models = 4), list labels, Table 2, the link target, inline and fenced code,
    # the HTML comment and the quoted "0.42" are not claims.
    assert printed(FINDINGS) == [(7, "0.69"), (16, "0.69"), (19, "0.5")]


def test_number_glued_to_word_is_not_a_number() -> None:  # boundary
    assert printed("+++\nx = 1\n+++\nexp14 on Qwen2.5-Coder-7B, 4 models\n") == [(4, "4")]


def test_dates_masked_and_percent_ranges_shared() -> None:
    text = "+++\nx = 1\n+++\nRun on 2026-10-20: 89–100% stale, 0.35–0.69 right.\n"
    nums = list(numbers("f.md", text))
    assert [(n.text, n.percent) for n in nums] == [
        ("89%", True), ("100%", True), ("0.35", False), ("0.69", False)]


def write(root: Path, audit: str, files: dict[str, str]) -> None:
    (root / "audit.toml").write_text(audit)
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)


def rules(root: Path) -> list[tuple[str, int, str]]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["numbers", "--root", str(root), "--json"])
    return [(f["file"], f["line"], f["rule"]) for f in json.loads(buf.getvalue())]


AUDIT = '[paper]\nmd = ["*.md"]\n\n[results]\nfiles = ["results/*.json"]\n'


def test_md_numbers_traced_to_results(tmp_path: Path) -> None:
    write(tmp_path, AUDIT, {
        "results/beh.json": '{"acc": 0.6883}',
        "findings.md": "+++\ntask = \"exp14\"\n+++\nAccuracy 0.69, and 0.71.\n",
        "notes.md": "Not audited: 0.99.\n",
    })
    assert rules(tmp_path) == [("findings.md", 4, "numbers/untraced")]


def test_md_only_paper_is_a_valid_config(tmp_path: Path) -> None:
    write(tmp_path, '[paper]\nmd = ["*.md"]\n', {"a.md": "+++\nx = 1\n+++\nNo numbers.\n"})
    assert [p.name for p in load(tmp_path).md] == ["a.md"]


def test_broken_front_matter_is_a_config_error(tmp_path: Path) -> None:
    write(tmp_path, '[paper]\nmd = ["*.md"]\n', {"a.md": "+++\nx = \n+++\nbody\n"})
    with pytest.raises(ConfigError, match="front matter"):
        load(tmp_path)
