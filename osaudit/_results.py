"""Results values: every number of the results JSON files, named by its path.

A value is named `<file stem>.<key>...`, with `["key"]` for a key that is not an identifier and
`[i]` for a list index: `survey.responses`, `survey.by_age["<30"].share`. A numeric dict key is
a value too (`survey.share_by_threshold["50"]`), since parameters of a run are often keys.
Expressions over these names (`a - b`, `(a + b) / c`) are parsed by `ast`, never evaluated.
"""

from __future__ import annotations

import ast
import json
from decimal import Decimal, DivisionByZero, InvalidOperation
from pathlib import Path
from typing import Any

IDENT = str.isidentifier


def _name(prefix: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{prefix}[{key}]"
    if IDENT(key):
        return f"{prefix}.{key}" if prefix else key
    return f"{prefix}[{json.dumps(key)}]"


def _numeric_key(k: str) -> Decimal | None:
    try:
        return Decimal(k)
    except InvalidOperation:
        return None


def flatten(name: str, x: Any, out: dict[str, Decimal]) -> None:
    if isinstance(x, dict):
        for k, v in x.items():
            sub = _name(name, k)
            kv = _numeric_key(k)
            if kv is not None and kv.is_finite():
                out[f"{sub} (key)"] = kv
            flatten(sub, v, out)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            flatten(_name(name, i), v, out)
    elif isinstance(x, bool):
        pass
    elif isinstance(x, int | float):
        out[name] = Decimal(str(x))


class Results:
    def __init__(self, docs: dict[str, Any]) -> None:
        self.docs = docs
        self.values: dict[str, Decimal] = {}
        for stem, doc in docs.items():
            flatten(stem, doc, self.values)

    @classmethod
    def load(cls, files: list[Path]) -> Results:
        """The results files, without their provenance block (not a result)."""
        docs = {}
        for f in files:
            doc = json.loads(f.read_text())
            if isinstance(doc, dict):
                doc = {k: v for k, v in doc.items() if k != "provenance"}
            docs[f.stem] = doc
        return cls(docs)

    def evaluate(self, expr: str) -> Decimal:
        """The value of `expr`; ValueError names what is wrong with it."""
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"not an expression: {expr!r}") from e
        try:
            return self._eval(tree.body)
        except (DivisionByZero, InvalidOperation) as e:
            raise ValueError(f"division by zero in {expr!r}") from e

    def _eval(self, node: ast.expr) -> Decimal:
        if isinstance(node, ast.BinOp):
            a, b = self._eval(node.left), self._eval(node.right)
            match node.op:
                case ast.Add():
                    return a + b
                case ast.Sub():
                    return a - b
                case ast.Mult():
                    return a * b
                case ast.Div():
                    return a / b
            raise ValueError(f"operator not allowed: {ast.unparse(node)}")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -self._eval(node.operand)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Decimal(str(node.value))
        return self._lookup(node)

    def _lookup(self, node: ast.expr) -> Decimal:
        path: list[str | int] = []
        n = node
        while True:
            if isinstance(n, ast.Attribute):
                path.append(n.attr)
                n = n.value
            elif isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) \
                    and isinstance(k := n.slice.value, str | int) and not isinstance(k, bool):
                path.append(k)
                n = n.value
            elif isinstance(n, ast.Name):
                path.append(n.id)
                break
            else:
                raise ValueError(f"not a results value: {ast.unparse(node)}")
        x: Any = self.docs
        for k in reversed(path):
            try:
                x = x[k]
            except (KeyError, IndexError, TypeError):
                raise ValueError(f"unknown results value: {ast.unparse(node)}") from None
        if isinstance(x, bool) or not isinstance(x, int | float):
            raise ValueError(f"not a number: {ast.unparse(node)}")
        return Decimal(str(x))
