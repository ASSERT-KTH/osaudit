"""A finding: one line `file:line: rule: message`, or one JSON object."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    rule: str
    message: str
    candidates: tuple[str, ...] = field(default=())

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.rule}: {self.message}"

    def as_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["candidates"] = list(self.candidates)
        return d
