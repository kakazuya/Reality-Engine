"""T-134 period engine: exact period rows and stored derived facts for a v2 company file.

Conventions
-----------
* An Indian fiscal year ends 31 March.  ``fy_end_month`` moves it for a December-year
  company: ``fy_end_month=12`` makes 2026-01-01..2026-03-31 ``Q1FY26`` (its FY26 runs
  2026-01-01..2026-12-31), where the same dates are ``Q4FY26`` for a March company.
* A fiscal label names the fiscal year of the period's END date: ``FY26`` is the year ending
  31 March 2026, ``Q2FY27`` the quarter ending 30 September 2026.
* ``period_row`` classifies a span in this order: POINT (no start), month (M), the fiscal year's
  first quarter / half / nine months / full year, the second half (H2), any other fiscal quarter
  (Q), a rolling twelve months (TTM), fiscal-year-to-date (YTD), otherwise it raises
  ``ValueError`` (``OTHER`` only with ``allow_other=True``).
* ``derive`` writes kind ``derived`` facts with a ``derivation`` row naming the formula and the
  input fact ids.  The answering model reads those rows; it never subtracts or sums.
* Derived rows never restate a reported figure: the engine compares and, when the two differ by
  more than 0.5%, writes ``derived X vs reported Y`` on the reported row's ``check_detail`` only
  (value and status are untouched).
* A growth rate is a different measure from the level, so its fact row carries
  ``definition='<definition>:yoy_pct'`` (or ``:qoq_pct``).  YoY and QoQ compare percent points
  and only use reported/stated facts as inputs.  ``TTM_SUM4Q`` may also sum four derived quarters,
  and records their fact ids in the derivation.
* ``derive`` does not commit; the caller owns the transaction.  ``as_of`` replays the facts a
  date could see (``known_at <= as_of`` and not yet superseded then); run it on a scratch copy,
  not on the live company file.
"""
from __future__ import annotations

import calendar
import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Iterable

__all__ = ["derive", "fiscal_label", "period_row"]

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_DAY = timedelta(days=1)
GROWTH_FORMULAS = ("YOY_PCT", "QOQ_PCT")
REPORTED_TOLERANCE = 0.005        # 0.5%: bigger difference is written on the reported row
_SAME_TOLERANCE = 1e-9            # float noise between two runs of the same arithmetic


# ------------------------------------------------------------------------------------- periods

def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _month_end(day: date) -> date:
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def _fy_start(day: date, fy_end_month: int) -> date:
    """First day of the fiscal year containing ``day``."""
    start_month = fy_end_month % 12 + 1
    start_year = day.year if day.month >= start_month else day.year - 1
    return date(start_year, start_month, 1)


def _fy_end(fy_start: date) -> date:
    return _add_months(fy_start, 12) - _DAY


def _quarter_end(fy_start: date, quarter: int) -> date:
    return _add_months(fy_start, 3 * quarter) - _DAY


def _span_months(start: date, end_exclusive: date) -> int | None:
    """Whole months from ``start`` to ``end_exclusive``, or None when it is not exact."""
    months = (end_exclusive.year - start.year) * 12 + (end_exclusive.month - start.month)
    if end_exclusive.day < start.day:
        months -= 1
    return months if _add_months(start, months) == end_exclusive else None


def _shift_year(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:                      # 29 February -> 28 February
        return day.replace(year=day.year + years, day=28)


def _day_label(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def _fy_number(day: date, fy_end_month: int) -> str:
    return f"{_fy_end(_fy_start(day, fy_end_month)).year % 100:02d}"


def _quarter_number(day: date, fy_end_month: int) -> int:
    start = _fy_start(day, fy_end_month)
    months = (day.year - start.year) * 12 + (day.month - start.month)
    return min(4, months // 3 + 1)


def _quarter_label(day: date, fy_end_month: int) -> str:
    return f"Q{_quarter_number(day, fy_end_month)}FY{_fy_number(day, fy_end_month)}"


def _ttm_label(end: date, fy_end_month: int) -> str:
    start = _fy_start(end, fy_end_month)
    for quarter in (1, 2, 3, 4):
        if end == _quarter_end(start, quarter):
            return f"TTM to Q{quarter}FY{_fy_number(end, fy_end_month)}"
    return f"TTM to {_day_label(end)}"


def _classify(start: date | None, end: date, fy_end_month: int,
              allow_other: bool) -> tuple[str, str]:
    if not 1 <= fy_end_month <= 12:
        raise ValueError(f"fy_end_month must be 1..12, got {fy_end_month}")
    if start is None:
        return "POINT", _day_label(end)
    if end < start:
        raise ValueError(f"period end {end} is before start {start}")
    if end == start:
        if allow_other:
            return "OTHER", _day_label(start)
        raise ValueError(f"{start}..{end} is a single day, not a period")
    if start.day == 1 and end == _month_end(start):
        return "M", f"{MONTHS[start.month - 1]} {start.year}"
    fy_start = _fy_start(end, fy_end_month)
    fy_end = _fy_end(fy_start)
    if start == fy_start:
        if end == _quarter_end(fy_start, 1):
            return "Q", _quarter_label(end, fy_end_month)
        if end == _quarter_end(fy_start, 2):
            return "H1", f"H1FY{_fy_number(fy_start, fy_end_month)}"
        if end == _quarter_end(fy_start, 3):
            return "9M", f"9MFY{_fy_number(fy_start, fy_end_month)}"
        if end == fy_end:
            return "FY", f"FY{_fy_number(fy_start, fy_end_month)}"
    if start == _add_months(fy_start, 6) and end == fy_end:
        return "H2", f"H2FY{_fy_number(fy_start, fy_end_month)}"
    months = _span_months(start, end + _DAY)
    if months == 3:
        offset = _span_months(fy_start, start)
        if offset is not None and offset in (0, 3, 6, 9):
            quarter = offset // 3 + 1
            if end == _quarter_end(fy_start, quarter):
                return "Q", _quarter_label(end, fy_end_month)
    if months == 12:
        return "TTM", _ttm_label(end, fy_end_month)
    if start == fy_start and end <= fy_end:
        return "YTD", f"YTD to {_day_label(end)}"
    if allow_other:
        return "OTHER", f"{_day_label(start)} to {_day_label(end)}"
    raise ValueError(f"{start}..{end} is none of Q, H1, H2, 9M, FY, TTM, M, YTD or POINT")


def fiscal_label(start: Any, end: Any, fy_end_month: int = 3) -> str:
    """'Q2FY27', 'H1FY27', '9MFY27', 'FY26', 'H2FY26', 'TTM to Q2FY27', '30 Sep 2026' (POINT).

    ``start=None`` is a point in time and the label is the day.  ``fy_end_month=12`` labels a
    December year-end company (2026-01-01..2026-03-31 -> 'Q1FY26').
    """
    return _classify(None if start is None else _as_date(start), _as_date(end),
                     fy_end_month, False)[1]


def _period_of(start: date | None, end: date, fy_end_month: int = 3,
               allow_other: bool = False) -> dict[str, Any]:
    kind, label = _classify(start, end, fy_end_month, allow_other)
    period_id = f"/{end.isoformat()}" if start is None else f"{start.isoformat()}/{end.isoformat()}"
    return {"period_id": period_id, "start": start, "end": end, "kind": kind, "fiscal_label": label}


def period_row(start: Any, end: Any, fy_end_month: int = 3,
               allow_other: bool = False) -> dict[str, Any]:
    """The ``period`` table row for a span: period_id, start_date, end_date, kind, fiscal_label.

    Raises ``ValueError`` when end < start or the span is not one of the fiscal shapes; a caller
    that really wants to store another span passes ``allow_other=True`` for kind ``OTHER``.
    """
    row = _period_of(None if start is None else _as_date(start), _as_date(end),
                     fy_end_month, allow_other)
    return {
        "period_id": row["period_id"],
        "start_date": row["start"].isoformat() if row["start"] is not None else None,
        "end_date": row["end"].isoformat(),
        "kind": row["kind"],
        "fiscal_label": row["fiscal_label"],
    }


# ----------------------------------------------------------------------------------- derivation

def _load_periods(conn: sqlite3.Connection, period_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    ids = sorted(set(period_ids))
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT period_id, start_date, end_date, kind, fiscal_label FROM period "
        f"WHERE period_id IN ({marks})", ids).fetchall()
    return {
        r[0]: {"period_id": r[0], "start": _as_date(r[1]) if r[1] is not None else None,
               "end": _as_date(r[2]), "kind": r[3], "fiscal_label": r[4]}
        for r in rows
    }


def _as_of_ts(as_of: Any) -> str | None:
    if as_of is None:
        return None
    text = as_of.isoformat() if isinstance(as_of, (date, datetime)) else str(as_of)
    return text if "T" in text else f"{text}T23:59:59"


def _load_facts(conn: sqlite3.Connection, entity_id: int, metric: str, dimension: str,
                basis: str, definition: str, as_of: str | None) -> list[dict[str, Any]]:
    sql = ("SELECT fact_id, period_id, value, unit, kind, known_at, superseded_at, check_detail "
           "FROM fact WHERE entity_id=? AND metric=? AND dimension=? AND basis=? AND definition=? ")
    params: list[Any] = [entity_id, metric, dimension, basis, definition]
    if as_of is None:
        sql += "AND superseded_at IS NULL"
    else:
        sql += "AND known_at <= ? AND (superseded_at IS NULL OR superseded_at > ?)"
        params += [as_of, as_of]
    return [
        {"fact_id": r[0], "period_id": r[1], "value": float(r[2]), "unit": r[3], "kind": r[4],
         "known_at": r[5], "superseded_at": r[6], "check_detail": r[7], "_dead": False}
        for r in conn.execute(sql + " ORDER BY fact_id", params).fetchall()
    ]


def _load_derivations(conn: sqlite3.Connection, entity_id: int, metric: str, dimension: str,
                      basis: str, definition: str) -> dict[int, tuple[str, list[int]]]:
    rows = conn.execute(
        "SELECT f.fact_id, d.formula_id, d.input_ids FROM fact f "
        "JOIN derivation d ON d.fact_id = f.fact_id "
        "WHERE f.entity_id=? AND f.metric=? AND f.dimension=? AND f.basis=? AND f.definition=?",
        (entity_id, metric, dimension, basis, definition)).fetchall()
    out: dict[int, tuple[str, list[int]]] = {}
    for fact_id, formula_id, input_ids in rows:
        try:
            ids = [int(x) for x in json.loads(input_ids or "[]")]
        except (TypeError, ValueError):
            ids = []
        out[fact_id] = (formula_id, ids)
    return out


def _group(facts: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        grouped.setdefault(fact["period_id"], []).append(fact)
    return grouped


def _pick(facts: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """The current fact a period contributes: latest known_at, then lowest fact_id."""
    live = [f for f in facts if not f.get("_dead")]
    if not live:
        return None
    return max(live, key=lambda f: (f["known_at"], -f["fact_id"]))


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= _SAME_TOLERANCE * max(1.0, abs(a), abs(b))


def _rel_diff(a: float, b: float) -> float:
    if b == 0:
        return 0.0 if a == 0 else float("inf")
    return abs(a - b) / abs(b)


def _values_conflict(values: list[float]) -> bool:
    return max(values) - min(values) > _SAME_TOLERANCE * max(1.0, *(abs(v) for v in values))


def _num_text(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _conflicts(ctx: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    found: list[dict[str, Any]] = []
    conflicted: set[str] = set()
    for period_id in sorted(ctx["by_period"]):
        rows = ctx["by_period"][period_id]
        values = sorted(f["value"] for f in rows)
        if not _values_conflict(values):
            continue
        conflicted.add(period_id)
        period = ctx["periods"].get(period_id, {})
        found.append({
            "period_id": period_id,
            "fiscal_label": period.get("fiscal_label", period_id),
            "metric": ctx["metric"], "dimension": ctx["dimension"],
            "values": values, "fact_ids": [f["fact_id"] for f in rows],
        })
    return found, conflicted


def _input_fact(ctx: dict[str, Any], period_id: str) -> dict[str, Any] | None:
    if period_id in ctx["conflicted"]:
        return None
    return _pick(ctx["by_period"].get(period_id, []))


def _input_pid(start: date, end: date) -> str:
    return f"{start.isoformat()}/{end.isoformat()}"


def _skip(ctx: dict[str, Any], formula_id: str, period: dict[str, Any],
          reason: str, **detail: Any) -> None:
    entry = {"formula_id": formula_id, "period": period.get("fiscal_label", period["period_id"]),
             "reason": reason}
    entry.update(detail)
    ctx["skipped"].append(entry)


def _insert_period(conn: sqlite3.Connection, period: dict[str, Any]) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO period (period_id, start_date, end_date, kind, fiscal_label) "
        "VALUES (?,?,?,?,?)",
        (period["period_id"], period["start"].isoformat() if period["start"] else None,
         period["end"].isoformat(), period["kind"], period["fiscal_label"]))


def _apply(ctx: dict[str, Any], formula_id: str, period: dict[str, Any],
           inputs: list[dict[str, Any]], value: float | None, unit: str,
           definition: str, by_period: dict[str, list[dict[str, Any]]],
           derivations: dict[int, tuple[str, list[int]]]) -> None:
    """Compare with what is already stored, then either write the derived fact or skip it."""
    units = sorted({f["unit"] for f in inputs})
    if len(units) != 1:
        _skip(ctx, formula_id, period, "unit_mismatch", units=units)
        return
    if value is None:
        _skip(ctx, formula_id, period, "base_not_positive",
              values=[f["value"] for f in inputs])
        return
    period_id = period["period_id"]
    if period_id in ctx["conflicted"]:
        _skip(ctx, formula_id, period, "target_conflict")
        return
    rows = by_period.get(period_id, [])
    reported = [f for f in rows if f["kind"] != "derived" and not f.get("_dead")]
    if reported:
        reference = _pick(reported)
        assert reference is not None
        if _rel_diff(value, reference["value"]) <= REPORTED_TOLERANCE:
            _skip(ctx, formula_id, period, "matches_reported", fact_id=reference["fact_id"])
            return
        detail = (f"derived {_num_text(value)} vs reported "
                  f"{_num_text(reference['value'])}")
        if reference.get("check_detail") != detail:
            ctx["conn"].execute("UPDATE fact SET check_detail=? WHERE fact_id=?",
                                (detail, reference["fact_id"]))
            reference["check_detail"] = detail
        _skip(ctx, formula_id, period, "reported_differs", fact_id=reference["fact_id"],
              detail=detail)
        return

    input_ids = [f["fact_id"] for f in inputs]
    same_formula = [f for f in rows
                    if f["kind"] == "derived" and not f.get("_dead")
                    and derivations.get(f["fact_id"], ("", []))[0] == formula_id]
    for fact in same_formula:
        _, existing_inputs = derivations.get(fact["fact_id"], ("", []))
        if existing_inputs == input_ids and fact["unit"] == unit and _same(fact["value"], value):
            _skip(ctx, formula_id, period, "exists", fact_id=fact["fact_id"])
            return
    others = [f for f in rows
              if f["kind"] == "derived" and not f.get("_dead") and f not in same_formula]
    if others and all(f["unit"] == unit and _same(f["value"], value) for f in others):
        _skip(ctx, formula_id, period, "agrees_with_derivation",
              fact_ids=[f["fact_id"] for f in others],
              formulas=[derivations.get(f["fact_id"], ("", []))[0] for f in others])
        return
    if others:
        _skip(ctx, formula_id, period, "derives_disagree",
              fact_ids=[f["fact_id"] for f in others], derived=value,
              stored=[f["value"] for f in others])
        return

    if period_id not in ctx["periods"]:
        _insert_period(ctx["conn"], period)
        ctx["periods"][period_id] = period
    known_at = max(f["known_at"] for f in inputs)
    cursor = ctx["conn"].execute(
        "INSERT INTO fact (entity_id, metric, dimension, period_id, basis, definition, kind, "
        "value, unit, known_at, check_status) VALUES (?,?,?,?,?,?,'derived',?,?,?,'unverified')",
        (ctx["entity_id"], ctx["metric"], ctx["dimension"], period_id, ctx["basis"], definition,
         value, unit, known_at))
    fact_id = int(cursor.lastrowid or 0)
    ctx["conn"].execute(
        "INSERT INTO derivation (fact_id, formula_id, input_ids) VALUES (?,?,?)",
        (fact_id, formula_id, json.dumps(input_ids)))
    new_row = {"fact_id": fact_id, "period_id": period_id, "value": value, "unit": unit,
               "kind": "derived", "known_at": known_at, "superseded_at": None,
               "check_detail": None, "_dead": False}
    by_period.setdefault(period_id, []).append(new_row)
    derivations[fact_id] = (formula_id, input_ids)
    for old in same_formula:                  # a restated input re-derives a new row
        ctx["conn"].execute("UPDATE fact SET superseded_at=? WHERE fact_id=?",
                            (known_at, old["fact_id"]))
        old["superseded_at"] = known_at
        old["_dead"] = True
    ctx["written"] += 1


# ------------------------------------------------------------------------------- sum candidates

def _cand_q2(ctx: dict[str, Any]):
    for period in list(ctx["periods"].values()):
        if period["kind"] != "H1" or period["start"] is None:
            continue
        q1_end = _add_months(period["start"], 3) - _DAY
        h1 = _input_fact(ctx, period["period_id"])
        q1 = _input_fact(ctx, _input_pid(period["start"], q1_end))
        if h1 is None or q1 is None or h1["kind"] == "derived" or q1["kind"] == "derived":
            continue
        target = _period_of(_add_months(period["start"], 3), period["end"])
        yield "Q_FROM_H1_LESS_Q1", target, [h1, q1]


def _cand_q3(ctx: dict[str, Any]):
    for period in list(ctx["periods"].values()):
        if period["kind"] != "9M" or period["start"] is None:
            continue
        h1_end = _add_months(period["start"], 6) - _DAY
        nine = _input_fact(ctx, period["period_id"])
        h1 = _input_fact(ctx, _input_pid(period["start"], h1_end))
        if nine is None or h1 is None or nine["kind"] == "derived" or h1["kind"] == "derived":
            continue
        target = _period_of(_add_months(period["start"], 6), period["end"])
        yield "Q_FROM_9M_LESS_H1", target, [nine, h1]


def _cand_q4(ctx: dict[str, Any]):
    for period in list(ctx["periods"].values()):
        if period["kind"] != "FY" or period["start"] is None:
            continue
        nine_end = _add_months(period["start"], 9) - _DAY
        fy = _input_fact(ctx, period["period_id"])
        nine = _input_fact(ctx, _input_pid(period["start"], nine_end))
        if fy is None or nine is None or fy["kind"] == "derived" or nine["kind"] == "derived":
            continue
        target = _period_of(_add_months(period["start"], 9), period["end"])
        yield "Q_FROM_FY_LESS_9M", target, [fy, nine]


def _cand_h2(ctx: dict[str, Any]):
    for period in list(ctx["periods"].values()):
        if period["kind"] != "FY" or period["start"] is None:
            continue
        h1_end = _add_months(period["start"], 6) - _DAY
        fy = _input_fact(ctx, period["period_id"])
        h1 = _input_fact(ctx, _input_pid(period["start"], h1_end))
        if fy is None or h1 is None or fy["kind"] == "derived" or h1["kind"] == "derived":
            continue
        target = _period_of(_add_months(period["start"], 6), period["end"])
        yield "H2_FROM_FY_LESS_H1", target, [fy, h1]


def _is_fy_span(start: date, end: date, fy_end_month: int = 3) -> bool:
    fy_start = _fy_start(end, fy_end_month)
    return start == fy_start and end == _fy_end(fy_start)


def _cand_ttm_sum4q(ctx: dict[str, Any]):
    quarters = [p for p in ctx["periods"].values()
                if p["kind"] == "Q" and p["start"] is not None]
    quarters.sort(key=lambda p: p["start"])  # type: ignore[arg-type]
    run: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for period in quarters:
        fact = _input_fact(ctx, period["period_id"])
        if fact is None:
            run = []
            continue
        if run and period["start"] == run[-1][0]["end"] + _DAY:  # type: ignore[operator]
            run.append((period, fact))
        else:
            run = [(period, fact)]
        if len(run) >= 4:
            window = run[-4:]
            start = window[0][0]["start"]
            end = window[-1][0]["end"]
            if start is not None and not _is_fy_span(start, end):
                target = _period_of(start, end)
                yield "TTM_SUM4Q", target, [f for _, f in window]


def _cand_ttm_fy_plus_ytd(ctx: dict[str, Any]):
    fy_ends = {(p["end"]): p for p in ctx["periods"].values() if p["kind"] == "FY"}
    for period in sorted(ctx["periods"].values(), key=lambda p: p["period_id"]):
        if period["start"] is None or period["kind"] in ("FY", "TTM", "POINT", "H2"):
            continue
        previous_fy = fy_ends.get(period["start"] - _DAY)
        if previous_fy is None:
            continue
        prior_pid = _input_pid(_shift_year(period["start"], -1), _shift_year(period["end"], -1))
        prior_period = ctx["periods"].get(prior_pid)
        if prior_period is None or prior_period["kind"] != period["kind"]:
            continue
        fy_fact = _input_fact(ctx, previous_fy["period_id"])
        now_fact = _input_fact(ctx, period["period_id"])
        prior_fact = _input_fact(ctx, prior_pid)
        if fy_fact is None or now_fact is None or prior_fact is None:
            continue
        if any(f["kind"] == "derived" for f in (fy_fact, now_fact, prior_fact)):
            continue                       # only TTM_SUM4Q may use a derived input
        target_start = _shift_year(period["end"], -1) + _DAY
        if _span_months(target_start, period["end"] + _DAY) != 12:
            continue
        target = _period_of(target_start, period["end"])
        if target["kind"] != "TTM":
            continue
        yield "TTM_FY_PLUS_YTD_LESS_PRIOR_YTD", target, [fy_fact, now_fact, prior_fact]


def _sum_value(formula_id: str, inputs: list[dict[str, Any]]) -> float:
    values = [f["value"] for f in inputs]
    if formula_id == "TTM_SUM4Q":
        return float(sum(values))
    if formula_id == "TTM_FY_PLUS_YTD_LESS_PRIOR_YTD":
        return float(values[0] + values[1] - values[2])
    return float(values[0] - values[1])


# ------------------------------------------------------------------------------------ growth

def _growth_definition(definition: str, formula_id: str) -> str:
    return f"{definition}:{formula_id.lower()}"


def _growth_value(now: float, before: float) -> float | None:
    if before <= 0:
        return None
    return (now / before - 1.0) * 100.0


def _cand_yoy(ctx: dict[str, Any]):
    for period in sorted(ctx["periods"].values(), key=lambda p: p["period_id"]):
        if period["start"] is None:
            continue
        now = _input_fact(ctx, period["period_id"])
        if now is None or now["kind"] == "derived":
            continue
        prior_pid = _input_pid(_shift_year(period["start"], -1), _shift_year(period["end"], -1))
        prior_period = ctx["periods"].get(prior_pid)
        if prior_period is None or prior_period["kind"] != period["kind"]:
            continue
        before = _input_fact(ctx, prior_pid)
        if before is None or before["kind"] == "derived":
            continue
        yield "YOY_PCT", period, [before, now], _growth_value(now["value"], before["value"])


def _cand_qoq(ctx: dict[str, Any]):
    quarter_ends = {(p["end"]): p for p in ctx["periods"].values() if p["kind"] == "Q"}
    for period in sorted(ctx["periods"].values(), key=lambda p: p["period_id"]):
        if period["kind"] != "Q" or period["start"] is None:
            continue
        now = _input_fact(ctx, period["period_id"])
        if now is None or now["kind"] == "derived":
            continue
        prior_period = quarter_ends.get(period["start"] - _DAY)
        if prior_period is None:
            continue
        before = _input_fact(ctx, prior_period["period_id"])
        if before is None or before["kind"] == "derived":
            continue
        yield "QOQ_PCT", period, [before, now], _growth_value(now["value"], before["value"])


# ------------------------------------------------------------------------------------- public

_SUM_CANDIDATES = (
    ("Q_FROM_H1_LESS_Q1", _cand_q2),
    ("Q_FROM_9M_LESS_H1", _cand_q3),
    ("Q_FROM_FY_LESS_9M", _cand_q4),
    ("H2_FROM_FY_LESS_H1", _cand_h2),
    ("TTM_SUM4Q", _cand_ttm_sum4q),
    ("TTM_FY_PLUS_YTD_LESS_PRIOR_YTD", _cand_ttm_fy_plus_ytd),
)
_GROWTH_CANDIDATES = (("YOY_PCT", _cand_yoy), ("QOQ_PCT", _cand_qoq))


def derive(conn: sqlite3.Connection, entity_id: int, metric: str, dimension: str = "",
           basis: str = "na", definition: str = "reported", additive: bool = True,
           as_of: Any = None) -> dict[str, Any]:
    """Derive and store v2 facts for one key; returns ``{"written", "conflicts", "skipped"}``.

    Keys are ``entity x metric x dimension x basis x definition``.  ``additive=True`` (a flow)
    writes quarters, H2, TTM and growth; ``additive=False`` (a ratio or a level that must not be
    summed) writes only YoY and QoQ.  A conflict -- two current facts for one key and period with
    different values -- blocks every formula that needs that period and is returned in
    ``conflicts``.  Re-running writes nothing new.  The caller commits.
    """
    as_of_ts = _as_of_ts(as_of)
    facts = _load_facts(conn, entity_id, metric, dimension, basis, definition, as_of_ts)
    by_period = _group(facts)
    periods = _load_periods(conn, [f["period_id"] for f in facts])
    ctx: dict[str, Any] = {
        "conn": conn, "entity_id": entity_id, "metric": metric, "dimension": dimension,
        "basis": basis, "periods": periods, "by_period": by_period,
        "skipped": [], "written": 0, "conflicted": set(),
    }
    conflicts, ctx["conflicted"] = _conflicts(ctx)
    derivations = _load_derivations(conn, entity_id, metric, dimension, basis, definition)

    if additive:
        for formula_id, generate in _SUM_CANDIDATES:
            for candidate_formula, target, inputs in generate(ctx):
                value = _sum_value(candidate_formula, inputs)
                _apply(ctx, candidate_formula, target, inputs, value, inputs[0]["unit"],
                       definition, by_period, derivations)

    for formula_id, generate in _GROWTH_CANDIDATES:
        growth_definition = _growth_definition(definition, formula_id)
        growth_facts = _load_facts(conn, entity_id, metric, dimension, basis,
                                   growth_definition, as_of_ts)
        growth_by_period = _group(growth_facts)
        growth_derivations = _load_derivations(conn, entity_id, metric, dimension, basis,
                                               growth_definition)
        for candidate_formula, target, inputs, value in generate(ctx):
            _apply(ctx, candidate_formula, target, inputs, value, "pct", growth_definition,
                   growth_by_period, growth_derivations)

    return {"written": ctx["written"], "conflicts": conflicts, "skipped": ctx["skipped"]}
