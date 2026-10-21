"""TOML front matter: the structured data at the top of a Markdown file, between `+++` lines.

Pre-registrations, exploration logs and audited Markdown documents carry it (conventions:
https://github.com/ASSERT-KTH/assert-research-agent/blob/main/CONVENTIONS.md).
"""

from __future__ import annotations

import re
import tomllib
from typing import Any

FRONT = re.compile(r"\A\+\+\+[ \t]*\n(.*?)\n\+\+\+[ \t]*(?:\n|\Z)", re.DOTALL)


def front_matter(text: str) -> tuple[dict[str, Any] | None, str]:
    """The TOML front matter of a Markdown file, or None and what is wrong."""
    m = FRONT.match(text)
    if not m:
        return None, "no TOML front matter (+++ ... +++ at the top)"
    try:
        return tomllib.loads(m.group(1)), ""
    except tomllib.TOMLDecodeError as e:
        return None, f"front matter: {e}"


def span(text: str) -> int:
    """The length of the front matter block at the top of `text`, 0 when there is none."""
    m = FRONT.match(text)
    return m.end() if m else 0
