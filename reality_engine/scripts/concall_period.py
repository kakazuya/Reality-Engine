"""Normalise the quarter / fiscal year a concall discusses (Indian FY: Q1 = Apr-Jun; FY27 = Apr 2026 - Mar 2027).

parse_period('Q2 FY26-27 ...') -> (2, 27). A two-year span (FY26-27, 2026-27) means the FY ending in the second year.
Annual-only labels (FY26, 'full year FY26', 'Q4 & FY26') map to Q4. H1/H2 alone return None (not a quarter).
expected_quarters(date) -> the last two quarters that ended on or before the filing date (both plausible for a call).
"""
import datetime as dt
import re

_Q = re.compile(r"\bQ\s*([1-4])(?!\d)|\b([1-4])\s*Q\b|\b(FIRST|SECOND|THIRD|FOURTH)\s+QUARTER")
_SPAN = re.compile(r"(?:FY\s*'?)?(?:20)?(\d{2})\s*[-/]\s*(?:20)?(\d{2})\b")
_FY = re.compile(r"FY\s*'?\s*(?:20)?(\d{2})\b")
_WORD = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4}


def _fy_from(u):
    span = _SPAN.search(u)
    if span and int(span.group(2)) == (int(span.group(1)) + 1) % 100:
        return int(span.group(2))
    m = _FY.search(u)
    return int(m.group(1)) if m else None


def parse_period(s):
    u = (s or "").upper().replace("–", "-").replace("’", "'")
    q = _Q.search(u)
    if q:
        # the FY that belongs to the quarter: first FY after the 'Qn' (label 'FY25-26 and Q1 FY26-27' -> Q1 FY27),
        # else the nearest one before it
        fy = _fy_from(u[q.end():]) or _fy_from(u[:q.start()])
        if fy is None:
            return None
        return int(q.group(1) or q.group(2) or _WORD[q.group(3)]), fy
    fy = _fy_from(u)
    if fy is None:
        return None
    if re.search(r"\bH[12]\b|HALF|OUTLOOK|BUSINESS UPDATE", u) and not re.search(r"FULL|ANNUAL|YEAR ENDED", u):
        return None
    return 4, fy


def expected_quarters(d):
    ends = []
    for y in (d.year - 1, d.year):
        for m, q, add in ((3, 4, 0), (6, 1, 1), (9, 2, 1), (12, 3, 1)):
            ends.append((dt.date(y, m, 30 if m in (6, 9) else 31), q, (y + add) % 100))
    past = sorted(e for e in ends if e[0] <= d)
    return [(q, fy) for _, q, fy in past[-2:]]
