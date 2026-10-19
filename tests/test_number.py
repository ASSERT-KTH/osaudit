"""Matching a printed number to a value: rounding tolerance, percents, integers."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from osaudit._number import Num, close, parse


def num(text: str) -> Num:
    n = parse(text)
    assert n is not None
    return n


@pytest.mark.parametrize("text,value", [
    ("1,204", "1204"),                 # known-negative: printed as stored
    ("67.5%", "0.6745"),               # boundary: half a unit, rounded up
    ("67.4%", "0.6745"),               # boundary: half a unit, rounded half-even
    ("80.3\\%", "0.8027"),
    ("42.1%", "42.1"),                 # a value already in percent
    ("4.2", "4.23"),
    ("99%", "0.99"),
])
def test_close(text: str, value: str) -> None:
    assert close(num(text), D(value))


@pytest.mark.parametrize("text,value", [
    ("70.0%", "0.625"),                # known-positive: a share that drifted
    ("67.6%", "0.6745"),               # boundary: just beyond half a unit
    ("7", "7.2"),                      # an integer is not the rounding of a decimal
    ("1,205", "1204"),
    ("4.2", "0.042"),                  # a plain decimal is not a percent
    ("57.0%", "57"),                   # a count is not a percent
])
def test_not_close(text: str, value: str) -> None:
    assert not close(num(text), D(value))


def test_parse() -> None:
    assert num("1,204").key == num("1204").key
    assert num("80.3\\%").key == num("80.3%").key
    assert num("80.3%").decimals == 1 and num("80.3%").percent
    assert parse("about 3") is None
