from __future__ import annotations

from datetime import date, timedelta


def is_banking_day(day: date, holidays: frozenset[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def banking_days_between(start: date, end: date, holidays: frozenset[date]) -> int:
    """Inclusive count of banking days strictly after start, up to and including end.
    Negative if end is before start."""
    if end == start:
        return 0
    step = 1 if end > start else -1
    cur = start
    n = 0
    while cur != end:
        cur = cur + timedelta(days=step)
        if is_banking_day(cur, holidays):
            n += step
    return n
