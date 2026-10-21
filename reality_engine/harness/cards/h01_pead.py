"""H01 Card B: PIT earnings surprise on normalized snapshot facts.

The database adapter must first DESCRIBE snapshot schemas. This module has
no implicit database or current-company-directory dependency.
"""
import calendar as month_calendar
import math
import re
from datetime import date, datetime, timedelta
from statistics import stdev
from ..data import as_date

TIMINGS = ('bse_next_open', 'both_known_next_open')
VARIANTS = tuple({"entry_timing": timing, "horizon": h, "measure": m, "sign": s}
                 for timing in TIMINGS
                 for h in (20, 60) for m in ("PAT", "revenue")
                 for s in ("positive", "negative"))

MONTHS = {name.lower(): i for i in range(1, 13)
          for name in (month_calendar.month_name[i], month_calendar.month_abbr[i])}
MONTHS["sept"] = 9


def parse_period_end(subject):
    """Accept dates explicitly attached to 'ended/ending', not meeting dates.

    Reject ambiguous subjects containing multiple ended dates. Period dates
    lacking a day or four-digit year are deliberately not inferred.
    """
    text = str(subject or "")
    dates = set()
    pattern = r"\bend(?:ed|ing)\s+(?:on\s+)?(\d{1,2})(?:st|nd|rd|th)?[\s./-]+([A-Za-z]+|\d{1,2})[\s,./-]+(20\d{2})\b"
    for d, m, y in re.findall(pattern, text, flags=re.I):
        month = int(m) if m.isdigit() else MONTHS.get(m.lower())
        try:
            dates.add(date(int(y), month, int(d)))
        except (ValueError, TypeError):
            continue
    return next(iter(dates)) if len(dates) == 1 else None


def pit_trigger(period_end, announcements):
    """Announcement rows for a uniquely mapped trading ISIN.

    Rows are normalized to subcategory, subject, disseminated_at (IST).
    Matches never precede period end; fallback ignores subjects explicitly
    naming a DIFFERENT quarter. Revised filings must be rejected upstream
    unless their values can be proved present in the original PDF.
    """
    q = as_date(period_end)
    exact, fallback = [], []
    for ann in announcements:
        if ann["subcategory"] != "Financial Results":
            continue
        stamp = ann.get("disseminated_at")
        if stamp is None or as_date(stamp) <= q:
            continue
        parsed = parse_period_end(ann.get("subject"))
        if parsed == q:
            exact.append(stamp)
        elif parsed is None and as_date(stamp) <= q + timedelta(days=100):
            fallback.append(stamp)
    if exact:
        return min(exact), "period_parsed"
    if fallback:
        return min(fallback), "within_100_days_unparsed"
    return None, "missing"


def quarter_back(day, n):
    """Calendar-quarter predecessor, only for actual quarter-end records."""
    d = as_date(day)
    if d.month not in (3, 6, 9, 12) or d.day != month_calendar.monthrange(d.year, d.month)[1]:
        return None
    ordinal = d.year * 4 + d.month // 3 - 1 - n
    y, k = divmod(ordinal, 4)
    m = (k + 1) * 3
    return date(y, m, month_calendar.monthrange(y, m)[1])


def select_basis(rows):
    """Choose basis without inspecting values/outcomes. Null consolidated
    values cannot justify falling back to a non-null standalone value.
    Caller supplies only quarter-duration OneD rows for ONE period.
    """
    for basis in ("Consolidated", "Standalone", "Non-Consolidated"):
        same = [r for r in rows if r["basis"] == basis]
        if same:
            return same
    return []


def surprise(current, history, measure="PAT"):
    """Raw YoY delta / sample std of the PRIOR EIGHT quarterly YoY deltas.

    All historical facts must be disseminated strictly before current's
    trigger. No restatement known later can rewrite an earlier quarter.
    Requires a contiguous sequence of twelve prior quarter values. A
    negative surprise is a descriptive avoid cohort, never a short order.
    Revenue facts must have metric RevenueFromOperations or InterestEarned;
    never mix the two across q and its comparators.
    """
    q, trigger = as_date(current["period_end"]), current["trigger"]
    if quarter_back(q, 0) is None:
        return None
    key = "PAT" if measure == "PAT" else "revenue"
    value = current.get(key)
    if value is None or not math.isfinite(value):
        return None
    known = {}
    # Selection is PIT by dissemination, not by snapshot's latest row.
    for row in sorted(history, key=lambda r: r.get("available_at", r["trigger"])):
        p = as_date(row["period_end"])
        if (p >= q or row.get("available_at", row["trigger"]) >= trigger
                or row.get("basis_family", row["basis"]) != current.get("basis_family", current["basis"])):
            continue
        if key == "revenue" and row.get("revenue_metric") != current.get("revenue_metric"):
            continue
        known[p] = row.get(key)
    values = {}
    for n in range(1, 13):
        p = quarter_back(q, n)
        v = known.get(p)
        if v is None or not math.isfinite(v):
            return None
        values[n] = v
    deltas = [values[n] - values[n + 4] for n in range(1, 9)]
    sd = stdev(deltas)
    if not math.isfinite(sd) or sd <= 0:
        return None
    return {"surprise": (value - values[4]) / sd,
            "yoy_change": value - values[4], "prior_yoy_sd": sd,
            "prior_yoy_count": 8, "basis": current["basis"]}


def in_variant(event, params):
    score = event.get(params["measure"] + "_surprise")
    return score is not None and ((score > 0) if params["sign"] == "positive" else (score < 0))


def descriptive_quintiles(events, measure):
    """Ex-post score quintiles, descriptive only; never traded cutoffs.

    Average rank keeps tied scores in the same bin. Bins can be empty; an
    artificial split of identical scores must not create apparent gradients.
    events contain measure+'_surprise' and net_excess for one horizon.
    """
    from statistics import mean, median
    field = measure + "_surprise"
    rows = sorted((e for e in events if e.get(field) is not None
                   and math.isfinite(e[field])), key=lambda e: e[field])
    bins = {q: [] for q in range(1, 6)}
    i = 0
    while i < len(rows):
        j = i + 1
        while j < len(rows) and rows[j][field] == rows[i][field]:
            j += 1
        rank = ((i + 1) + j) / 2
        q = min(5, max(1, math.ceil(5 * rank / len(rows))))
        bins[q].extend(rows[i:j])
        i = j
    return [{"quintile": q, "n_events": len(group),
             "min_surprise": min((e[field] for e in group), default=None),
             "max_surprise": max((e[field] for e in group), default=None),
             "mean_net_excess": mean(e["net_excess"] for e in group) if group else None,
             "median_net_excess": median(e["net_excess"] for e in group) if group else None}
            for q, group in bins.items()]
