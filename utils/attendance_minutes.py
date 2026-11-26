"""Pure minute-based attendance calculations; no database writes."""
import re


def shift_interval(value):
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})\s*", value)
    if not match:
        raise ValueError("Invalid shift interval")
    h1, m1, h2, m2 = map(int, match.groups())
    if h1 > 23 or h2 > 24 or m1 > 59 or m2 > 59 or (h2 == 24 and m2):
        raise ValueError("Invalid shift time")
    start, end = h1 * 60 + m1, h2 * 60 + m2
    if end == start:
        raise ValueError("Ambiguous zero-length shift")
    if end < start:
        end += 1440
    return start, end


def worked_minutes(values):
    intervals = sorted(shift_interval(value) for value in values)
    total = 0
    end = 0
    for start, stop in intervals:
        total += max(0, stop - max(start, end))
        end = max(end, stop)
    return total
