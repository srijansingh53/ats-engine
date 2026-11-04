from __future__ import annotations

import re
from datetime import date

_YM = re.compile(r"^\s*(\d{4})(?:[-/.](\d{1,2}))?")
PRESENT = {"present", "current", "now", "till date", "ongoing", "today"}


def parse_ym(value: str | None, today: date) -> tuple[int, int] | None:
    """'2023-05' -> (2023, 5); 'present' -> today; '2021' -> (2021, 1)."""
    if value is None:
        return None
    v = str(value).strip().lower()
    if not v:
        return None
    if v in PRESENT:
        return today.year, today.month
    m = _YM.match(v)
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2) or 1)
    if not 1 <= month <= 12:
        month = 1
    return year, month


def to_index(ym: tuple[int, int]) -> int:
    """Months since year 0, for arithmetic."""
    return ym[0] * 12 + (ym[1] - 1)


def months_between(start: tuple[int, int], end: tuple[int, int]) -> int:
    """Inclusive month count: Jan->Jan = 1."""
    return to_index(end) - to_index(start) + 1


def union_months(intervals: list[tuple[int, int]]) -> int:
    """Total months covered by inclusive [start_idx, end_idx] intervals, overlaps merged."""
    if not intervals:
        return 0
    merged: list[list[int]] = []
    for s, e in sorted(intervals):
        if e < s:
            continue
        if merged and s <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return sum(e - s + 1 for s, e in merged)
