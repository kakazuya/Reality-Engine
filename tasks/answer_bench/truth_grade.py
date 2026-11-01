"""Truth grade beside the contract count: shape, a store read, and a stratified panel.

The strict grader (``grade_v2.py``) certifies the *contract*: every part of the
decomposer's own Ask carries §D.4 fields.  That is the system marking its own
homework — a decomposer that emits fewer parts scores higher.  This module adds the
pieces the contract cannot see, and no check here loosens a contract check.  Since
2026-10-31 the RIGHT branch also **re-reads the store**:

* the answer's entity, measure, period and value must equal a separate read of the
  pilot fact store within :data:`VALUE_TOLERANCE_REL` (0.5%);
* a value the store cannot settle is ``PARTIAL`` (``TRUTH_VALUE_UNVERIFIED``), never
  RIGHT;
* a premise the stores contradict, or a question that names another company, is
  ``ILL_POSED`` — its own column, always in the denominator, never RIGHT;
* the lexical rubric is retired as a verdict input.  ``rubric_score`` stays only as
  the diagnostic ``--rubric40`` cheap test; a prose ``ground_truth`` is ignored, and a
  numeric one must appear in the answer.

The shape checks still read the question text alone:

1. **Answer shape** (:func:`question_shapes`, :func:`shape_failures`).  The shape is
   read from the *question text alone* — never from the Ask and never from what the
   executor returned.  Eight deterministic failures, each with a stable name:
   a set/list/ranking ask answered from one entity; a comparison missing a side; a
   judgement ask with no rule output; a period-named change run first-to-last over
   the whole window; two parts returning one value under different labels; a
   ``list_distinct`` dump past its limit with no aggregation; a forecast answered
   with a spot price; and a returned period that is not the one asked.

2. **Rubric** (:func:`rubric_score`).  **Retired as a verdict input** on 2026-10-31:
   it agreed with the 40 hand verdicts on 8/40 and fired on 30 answered panel rows,
   none of them RIGHT.  It stays only as the ``--rubric40`` diagnostic and is not
   called by :func:`truth_verdict`.  A ``ground_truth`` is used only when it carries a
   number and the answer carries that number.

3. **Truth** (:func:`truth_verdict`).  RIGHT / PARTIAL / WRONG / ILL_POSED for one
   graded row.  ILL_POSED comes first (premise audit + entity mismatch); then the
   shape checks, a measure/part coverage test, and the independent store read.  A
   RIGHT requires every part to be answered and every numeric value to be reproduced
   from the store.  The panel (:func:`build_panel`) is the authority; the numbers it
   produces are printed with a Wilson interval, and ILL_POSED is reported in its own
   column, never as RIGHT, never out of the denominator.

It reads graded rows (``GATE_RESULTS_v4_strict.jsonl``), the bank, the instances, the
premise audit and the read-only pilot store (``fact_v4_pilot.db`` / ``v4.db``).  The
store is opened ``mode=ro&immutable=1`` and by entity/measure/period, never from the
answer's own ``source_ref``.
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[2]
BENCH = REPO / "tasks" / "answer_bench"
BANK = REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl"
INSTANCES = REPO / "tasks" / "pilot60" / "INSTANCES.jsonl"
SAMPLE40_MD = REPO / "tasks" / "arch_v4" / "GATE_V4_SAMPLE40.md"
PANEL = REPO / "tasks" / "arch_v4" / "TRUTH_PANEL_2026-10-31.jsonl"
PREMISE_AUDIT = REPO / "tasks" / "pilot60" / "PREMISE_AUDIT_2026-10-31.jsonl"
READ_PANEL = REPO / "tasks" / "arch_v4" / "TRUTH_PANEL_READ_2026-10-31.jsonl"
DATA = Path(os.environ.get("REALITY_DATA_ROOT") or (REPO / "reality_engine" / "data"))
V4_ROOT = Path(os.environ.get("REALITY_V4_PILOT") or (DATA / "pilot" / "v4"))

#: a value matches the store when ``|answer - store| <= max(ABS, REL * |store|)``.
#: 0.5% is stated here so every tolerance in the report has one source.
VALUE_TOLERANCE_ABS = 0.005
VALUE_TOLERANCE_REL = 0.005


#: committed seed: the fixed 150-row panel is the same rows on every run.
SEED_PANEL = 20261031
PANEL_N = 150
FRESH_N = 40
#: the panel oversamples answered rows (a bank-proportional draw would carry ~12 of
#: them) and the truth estimate reweights by the measured contract answered share.
PANEL_ANSWERED_SHARE = 0.67
#: a ``list_distinct`` dump with no stated limit is still not an answer past this many
#: rows; the reason text says which cap fired.
ROW_CAP = 25
ABSURD_DUMP = 200

# ---------------------------------------------------------------------------
# small parsing helpers
# ---------------------------------------------------------------------------
_MONTHS = ("january|february|march|april|may|june|july|august|september|october|"
           "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")
_MONTH_NO = {name: index for index, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), 1)}
_MONTH_NO.update({"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
                  "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12})
_QUARTER_RE = re.compile(r"\bq\s*([1-4])\s*(?:fy|fy\.)?\s*'?(?:20)?(\d{2})\b", re.I)
_FY_RE = re.compile(r"\bfy\s*'?(?:20)?(\d{2})\b", re.I)
_MONTH_YEAR_RE = re.compile(rf"\b({_MONTHS})\.?,?\s+(20\d{{2}})\b", re.I)
_DAY_MONTH_RE = re.compile(rf"\b(\d{{1,2}})\s+({_MONTHS})\.?,?\s+(20\d{{2}})\b", re.I)
_MONTH_DAY_RE = re.compile(rf"\b({_MONTHS})\.?\s+(\d{{1,2}}),?\s+(20\d{{2}})\b", re.I)
_ISO_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")

_SET_RE = re.compile(
    r"\b(which (companies|stocks|scrips|firms|sectors|industries|banks|peers|listed)"
    r"|top \d+|rank(ed|ing)?\b|all listed|constituents\b|each company|per company"
    r"|how many (companies|stocks|names|sessions)|across the (universe|market|sector|industry)"
    r"|companies with|name the (companies|stocks)|highest (turnover|volume|return)"
    r"|top (losers|gainers|companies|stocks|names)|leaders? in)\b", re.I)
_COMPARE_RE = re.compile(
    r"\b(versus|vs\.?|compare[sd]?|compared (with|to)|the two companies|both companies"
    r"|either company|which (one|is) (is )?more)\b", re.I)
_COMPARE_OFF_RE = re.compile(
    r"\bvs\.?\s+(the\s+)?(stored|computed|reported|derived|last|previous)\b"
    r"|\b(stored|computed|reported|derived)\b[^?.]{0,25}\bvs\.?\b", re.I)
#: "stored vs computed" is a comparison of two measures on one entity, not a
#: two-company ask.  Kept apart so `SHAPE_COMPARE_ONE_SIDE` can skip it while the
#: answer is still required to show both sides (`measure_shortfall`).
_MEASURE_VS_RE = re.compile(
    r"\b(stored|computed|reported|derived|market|book)\b[^?.]{0,30}\bvs\.?\b"
    r"|\bvs\.?\s+(the\s+)?(stored|computed|reported|derived|market|book)\b", re.I)
_JUDGEMENT_RE = re.compile(
    r"(\b(is|are|was|were)\b[^?.]{0,90}\b(cheap|expensive|good|bad|safe|risky|fair"
    r"|justified|sustainable|credible|consistent|valid|warning|noise|distribution"
    r"|absorption|overvalued|undervalued|premium|thesis|driven|accumulation|intraday)\b"
    r"|\b(is|are|was|were)\b[^?.]{0,80}\b(being|getting)\b[^?.]{0,40}\b(driven|sold|bought)\b"
    r"|\b(did|does|do|has|have|had)\b[^?.]{0,90}\b(hold|held|break|broken|reverse|sustain"
    r"|confirm|follow through|retest)\b"
    r"|\bcheap or\b|\bsasta\b|\bwarning or noise\b"
    r"|\bwhat would (break|it take|happen)\b|\bwhat would .{0,70}\b(change|mean|imply|matter)\b"
    r"|\bneeds? to show\b|\bis (that|this) (a|the)?\s?(warning|noise|bottom|top)\b"
    r"|\bdeserves?\b|\bworth (it|buying)\b|\bdo(es)? .* flatter\b"
    r"|\bwho (gains|wins|is more)\b|\bkaun (jeetta|peeche)\b)", re.I)
#: an N-day average the question names; the answer must name the same window.
_DAY_AVG_RE = re.compile(r"\b(\d{1,3})[- ]day\b", re.I)
_RULE_RE = re.compile(
    r"\bwhat is the correct\b|\bwhat('s| is) the right\b|\bhow should\b"
    r"|\bwhat price should\b|\bwhich rule\b|\bwhat rule\b"
    r"|\bhow (does|do) (a|the) .{0,40}treat\b", re.I)
_FORECAST_RE = re.compile(
    r"\bwhat (will|would)\b[^?]{0,80}\b(be|reach|trade|go to|settle)\b"
    r"|\b(where|how much) will\b|\bforecast\b|\bprice target\b"
    r"|\b(diwali|new year)\s+20\d\d\b|\bnext year\b|\bby 20\d\d\b", re.I)
_CHANGE_RE = re.compile(
    r"\b(change[sd]?|rose|rise|fell|fall|jump(ed)?|drop(ped)?|gain(ed)?|lost|moved?"
    r"|growth|grew|decline[sd]?|increase[sd]?|decrease[sd]?|swing|surge[sd]?|slipped"
    r"|expanded|contracted)\b", re.I)
_MULTI_RE = re.compile(
    r"(\band\b[^?]{0,90}\b(what|how|which|who|when|did|does|is|was|were|has|have|do)\b"
    r"|\baur\b|\bya\b)", re.I)
_FORWARD_RE = re.compile(
    r"\bnext (\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(sessions|days|weeks|months)"
    r"|\bwhat followed\b|\bhow many sessions did it take\b|\bsubsequent\b", re.I)
_LIMIT_RE = re.compile(r"\btop (\d+)\b|\bfirst (\d+)\b|\blast (\d+)\b"
                       r"|\b(\d+) (sessions|days|names|companies|stocks|rows|items)\b", re.I)
#: measure words the question names that an answer must actually contain.  Kept small
#: and precise on purpose: every term here is a computation, not a restatement.
_MEASURE_TERMS = (
    ("per square foot", ("per square foot", "per sq ft", "per sq. ft", "sq ft", "square foot")),
    ("inventory turns", ("inventory turn", "inventory turnover", "turns")),
    ("price to book", ("p/b", "price to book", "price-to-book", "book value")),
    ("realisation", ("realisation", "realization", "realisation per", "per unit")),
    ("us revenue", ("us revenue", "revenue from the us", "us share", "americas")),
    ("forward return", ("forward return", "what followed", "next-day", "next day")),
    ("session count", ("how many sessions", "sessions this year", "count of sessions")),
)
_STOP = set(
    "the a an of and or to in on for with from by as at is are was were be been being this "
    "that these those it its how what which who when where why do does did has have had not "
    "no must should can could would will shall if then than all any each per more most less "
    "least into over under after before between within without using use used about".split())


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _day(value: Any) -> str:
    """The YYYY-MM-DD part of a period/known_at value, or ""."""
    text = str(value or "")
    match = _ISO_RE.search(text)
    return match.group(0) if match else ""


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _words(text: Any) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9:.%/]+", _norm(text))
            if len(word) > 2 and word not in _STOP]


# ---------------------------------------------------------------------------
# 1. the ask's shape, read from the question text alone
# ---------------------------------------------------------------------------
def _fy_start_year(two_digit: str | int) -> int:
    year = int(two_digit)
    return 2000 + year


def _quarter_window(fy: int, quarter: int) -> tuple[str, str]:
    """Indian FY quarter window: Q1 FY27 = 2026-04-01..2026-06-30."""
    start_year = fy - 1
    starts = {1: (start_year, 4, 1), 2: (start_year, 7, 1),
              3: (start_year, 10, 1), 4: (fy, 1, 1)}
    ends = {1: (start_year, 6, 30), 2: (start_year, 9, 30),
            3: (start_year, 12, 31), 4: (fy, 3, 31)}
    return ("%04d-%02d-%02d" % starts[quarter], "%04d-%02d-%02d" % ends[quarter])


def _fy_window(fy: int) -> tuple[str, str]:
    return (f"{fy - 1}-04-01", f"{fy}-03-31")


def _month_window(year: int, month: int) -> tuple[str, str]:
    last = (31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[month - 1]
    return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last:02d}"


def asked_periods(question: str) -> list[dict[str, Any]]:
    """Every dated period the question names, as ``kind/label/start/end``.

    Only absolute periods are read: a quarter label, a FY, a month-year, a full date.
    Relative wording ("a month", "last week") is left unparsed on purpose — its window
    depends on a reference date the question does not always state, so a grader that
    guessed it would fail right answers.
    """
    text = str(question or "")
    out: list[dict[str, Any]] = []
    for match in _QUARTER_RE.finditer(text):
        quarter, fy = int(match.group(1)), _fy_start_year(match.group(2))
        start, end = _quarter_window(fy, quarter)
        out.append({"kind": "quarter", "label": f"Q{quarter}FY{fy % 100:02d}",
                    "start": start, "end": end})
    for match in _FY_RE.finditer(text):
        if re.match(r"q", text[max(0, match.start() - 3):match.start()], re.I):
            continue
        fy = _fy_start_year(match.group(1))
        start, end = _fy_window(fy)
        out.append({"kind": "annual", "label": f"FY{fy % 100:02d}", "start": start, "end": end})
    for match in _DAY_MONTH_RE.finditer(text):
        day, month, year = int(match.group(1)), _MONTH_NO[match.group(2).lower()], int(match.group(3))
        out.append({"kind": "date", "label": match.group(0),
                    "start": f"{year}-{month:02d}-{day:02d}",
                    "end": f"{year}-{month:02d}-{day:02d}"})
        # "1 January-30 September 2026": the leading date carries no year of its own.
        head = text[max(0, match.start() - 18):match.start()]
        opening = re.search(rf"(\d{{1,2}})\s+({_MONTHS})\.?\s*[-\u2013\u2014]\s*$", head, re.I)
        if opening:
            start_month = _MONTH_NO[opening.group(2).lower()]
            start_day = int(opening.group(1))
            out.append({"kind": "date", "label": f"{start_day} {start_month} {year}",
                        "start": f"{year}-{start_month:02d}-{start_day:02d}",
                        "end": f"{year}-{start_month:02d}-{start_day:02d}"})
    for match in _MONTH_DAY_RE.finditer(text):
        month, day, year = _MONTH_NO[match.group(1).lower()], int(match.group(2)), int(match.group(3))
        out.append({"kind": "date", "label": match.group(0),
                    "start": f"{year}-{month:02d}-{day:02d}",
                    "end": f"{year}-{month:02d}-{day:02d}"})
    for match in _MONTH_YEAR_RE.finditer(text):
        month, year = _MONTH_NO[match.group(1).lower()], int(match.group(2))
        if any(p["label"].lower() == match.group(0).lower() for p in out):
            continue
        start, end = _month_window(year, month)
        out.append({"kind": "month", "label": match.group(0), "start": start, "end": end})
    for match in _ISO_RE.finditer(text):
        day = match.group(0)
        out.append({"kind": "date", "label": day, "start": day, "end": day})
    seen: set[tuple[str, str]] = set()
    unique = []
    for period in out:
        key = (period["label"].lower(), period["start"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(period)
    return unique


def stated_limit(question: str) -> int | None:
    match = _LIMIT_RE.search(str(question or ""))
    if not match:
        return None
    for group in match.groups():
        if group and group.isdigit():
            return int(group)
    return None


def question_shapes(question: str) -> dict[str, Any]:
    """The shape flags the question text implies (no Ask, no executor output)."""
    text = str(question or "")
    periods = asked_periods(text)
    measure_vs = bool(_MEASURE_VS_RE.search(text))
    compare = (bool(_COMPARE_RE.search(text))
               and not _COMPARE_OFF_RE.search(text) and not measure_vs)
    return {
        "set": bool(_SET_RE.search(text)),
        "compare": compare,
        "measure_vs": measure_vs,
        "judgement": bool(_JUDGEMENT_RE.search(text)),
        "rule": bool(_RULE_RE.search(text)),
        "forecast": bool(_FORECAST_RE.search(text)),
        "change": bool(_CHANGE_RE.search(text)),
        "forward": bool(_FORWARD_RE.search(text)),
        "multi": bool(_MULTI_RE.search(text)),
        "periods": periods,
        "limit": stated_limit(text),
    }


def shape_label(shapes: Mapping[str, Any]) -> str:
    """One label for the panel's stratification: the strictest shape present."""
    for name in ("set", "compare", "judgement", "forecast", "forward", "change", "rule"):
        if shapes.get(name):
            return name
    return "plain"


# ---------------------------------------------------------------------------
# 2. the eight shape failures
# ---------------------------------------------------------------------------
def _results(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [r for r in (row.get("results") or []) if isinstance(r, Mapping)]


def _covered_results(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [r for r in _results(row)
            if str(r.get("answer_type") or "") in ("measured", "estimate")]


def _entity_ids(row: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for result in _results(row):
        if result.get("isin"):
            out.add(str(result["isin"]))
        for value in result.get("values") or []:
            if isinstance(value, Mapping):
                for key in ("entity_id", "isin"):
                    if value.get(key):
                        out.add(str(value[key]))
        for entity in result.get("entities") or []:
            if isinstance(entity, Mapping) and entity.get("entity_id"):
                out.add(str(entity["entity_id"]))
    return out


def _fail(reason: str, detail: str) -> dict[str, str]:
    return {"reason": reason, "detail": detail}


def _change_endpoints(result: Mapping[str, Any]) -> tuple[str, str]:
    numbers = result.get("numbers") or {}
    start, end = _day(numbers.get("from")), _day(numbers.get("to"))
    if start and end:
        return start, end
    dated = sorted(_day(value.get("period")) for value in result.get("values") or []
                   if isinstance(value, Mapping) and _day(value.get("period")))
    if len(dated) >= 2:
        return dated[0], dated[-1]
    return "", ""


def _inside(day: str, start: str, end: str) -> bool:
    """A period is inside a window, with one day of slack at each edge."""
    def _shift(value: str, delta: int) -> str:
        from datetime import date, timedelta
        try:
            return (date.fromisoformat(value) + timedelta(days=delta)).isoformat()
        except ValueError:
            return value
    return _shift(start, -1) <= day <= _shift(end, 1)


def _span_days(start: str, end: str) -> int:
    from datetime import date
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return 0


def _set_one_entity(row: Mapping[str, Any], shapes: Mapping[str, Any]) -> dict | None:
    if not shapes.get("set"):
        return None
    results = _results(row)
    if not results:
        return None
    if any(str(r.get("operator") or "") in ("count", "aggregate") for r in results):
        return None
    if len(_entity_ids(row)) >= 2:
        return None
    return _fail("SHAPE_SET_ONE_ENTITY",
                 "the ask is a set/list/ranking; the answer carries one entity "
                 f"({len(_entity_ids(row))}) and no count or ranked set")


def _compare_one_side(row: Mapping[str, Any], shapes: Mapping[str, Any]) -> dict | None:
    if not shapes.get("compare"):
        return None
    # A "stored vs computed" ask on one entity is two measures, not two companies.
    # It still has to show both sides, but that is `measure_shortfall`, not this check.
    if shapes.get("measure_vs"):
        return None
    results = _results(row)
    if not results:
        return None
    if any(str(r.get("operator") or "") in ("compare", "join_entity_set") for r in results):
        return None
    if len(_entity_ids(row)) >= 2:
        return None
    return _fail("SHAPE_COMPARE_ONE_SIDE",
                 "the ask compares sides; the answer carries one entity and no compare operator")


def _judgement_no_rule(row: Mapping[str, Any], shapes: Mapping[str, Any]) -> dict | None:
    if not (shapes.get("judgement") or shapes.get("rule")):
        return None
    results = _results(row)
    if not results:
        return None
    if any(bool(r.get("rule_used")) or str(r.get("shape") or "") == "verdict"
           for r in results):
        return None
    return _fail("SHAPE_JUDGEMENT_NO_RULE",
                 "the ask is a judgement/rule ask; no part carries a rule_used or verdict block")


def _change_over_window(row: Mapping[str, Any], shapes: Mapping[str, Any]) -> dict | None:
    if not shapes.get("change"):
        return None
    periods = shapes.get("periods") or []
    forward = bool(shapes.get("forward"))
    if not periods and not forward:
        return None
    covered = _covered_results(row)
    changes = [result for result in covered
               if str(result.get("operator") or "") in ("change", "pct_change", "growth")]
    if not changes:
        return None
    if forward and len(changes) == len(covered):
        start, end = _change_endpoints(changes[0])
        if start and end:
            return _fail(
                "SHAPE_CHANGE_OVER_WINDOW",
                f"the ask names the window after the event; every part is a change "
                f"running {start}..{end} first-to-last over the past window")
    if not periods:
        return None
    window_start = min(p["start"] for p in periods)
    window_end = max(p["end"] for p in periods)
    label = ", ".join(p["label"] for p in periods)
    for result in changes:
        start, end = _change_endpoints(result)
        if not start or not end:
            continue
        if not (_inside(start, window_start, window_end)
                and _inside(end, window_start, window_end)):
            return _fail(
                "SHAPE_CHANGE_OVER_WINDOW",
                f"the ask names {label}; the change runs {start}..{end} first-to-last "
                "over the whole window")
    return None


def _duplicate_value(row: Mapping[str, Any], shapes: Mapping[str, Any]) -> dict | None:
    if not shapes.get("multi"):
        return None
    seen: dict[tuple[float, str], dict[str, Any]] = {}
    for result in _covered_results(row):
        value = _num(result.get("value"))
        if value is None or isinstance(result.get("values"), list) and len(result["values"]) > 1:
            continue
        key = (round(value, 6), _day(result.get("period")))
        label = (str(result.get("atom") or result.get("formula") or ""),
                 str(result.get("operator") or ""), json.dumps(result.get("dims") or {}, sort_keys=True))
        if key in seen and seen[key]["label"] != label:
            return _fail(
                "SHAPE_DUPLICATE_VALUE",
                f"parts {seen[key]['part']} and {result.get('part_index')} return the same "
                f"value {value:,.6g} for the same period under different labels")
        seen[key] = {"label": label, "part": result.get("part_index")}
    return None


def _list_dump(row: Mapping[str, Any], shapes: Mapping[str, Any]) -> dict | None:
    stated = shapes.get("limit")
    for result in _results(row):
        if str(result.get("operator") or "") != "list_distinct":
            continue
        rows = len(result.get("values") or [])
        if stated and rows > stated:
            return _fail("SHAPE_LIST_DUMP",
                         f"the ask states {stated} rows; list_distinct dumps {rows} with no aggregation")
        if not stated and rows > ABSURD_DUMP:
            return _fail("SHAPE_LIST_DUMP",
                         f"no limit is stated and list_distinct dumps {rows} rows with no "
                         f"aggregation (grader cap {ABSURD_DUMP})")
    return None


def _forecast_spot(row: Mapping[str, Any], shapes: Mapping[str, Any]) -> dict | None:
    if not shapes.get("forecast"):
        return None
    results = _results(row)
    if not results:
        return None
    if any(str(r.get("answer_type") or "") == "estimate"
           or str(r.get("rule_used") or "") or str(r.get("shape") or "") == "verdict"
           for r in results):
        return None
    market = [r for r in results
              if str(r.get("atom") or "").startswith(("price.", "market."))
              and r.get("value") is not None]
    if market:
        return _fail("SHAPE_FORECAST_SPOT",
                     "the ask is a forecast; the answer is a spot market reading "
                     f"({market[0].get('atom')} at {_day(market[0].get('period')) or 'no date'})")
    return None


_POINT_OPERATORS = {
    "series", "rank", "screen", "count", "aggregate", "list_distinct", "walk",
    "join_entity_set", "exists", "correlate", "describe_series", "span_days",
    "first_visible", "last_visible", "lag_between", "event_window_return",
}
#: selector dims a stored row names in its own record; a mismatch means the part read a
#: different slice than it asked for, whatever the contract says.
_ROW_DIMS = ("topic", "holder_class", "doctype")


def _period_mismatch(row: Mapping[str, Any], shapes: Mapping[str, Any]) -> dict | None:
    periods = shapes.get("periods") or []
    if not periods:
        return None
    quarters = [p for p in periods if p["kind"] == "quarter"]
    if shapes.get("change") and len(quarters) >= 2:
        covered = _covered_results(row)
        changes = [r for r in covered
                   if str(r.get("operator") or "") in ("change", "pct_change", "growth")]
        distinct = {_day(r.get("period")) for r in covered if _day(r.get("period"))}
        if not changes and len(distinct) < 2:
            return _fail(
                "SHAPE_PERIOD_MISMATCH",
                f"the ask names {', '.join(p['label'] for p in quarters)}; one reading "
                f"({', '.join(sorted(distinct)) or 'no period'}) answers neither")
    single = len(periods) == 1
    window_start = min(p["start"] for p in periods)
    window_end = max(p["end"] for p in periods)
    label = ", ".join(p["label"] for p in periods)
    if _span_days(window_start, window_end) >= 30:
        for result in _covered_results(row):
            if str(result.get("operator") or "") not in ("max_with_date", "min_with_date"):
                continue
            if (result.get("numbers") or {}).get("n") == 1:
                return _fail(
                    "SHAPE_PERIOD_MISMATCH",
                    f"the ask names {label}; the extreme was taken over 1 row "
                    f"({_day(result.get('period'))})")
    for result in _covered_results(row):
        if str(result.get("operator") or "") in _POINT_OPERATORS:
            continue
        day = _day(result.get("period"))
        if not day:
            continue
        kind = str((result.get("dims") or {}).get("period_kind") or "").lower()
        if single:
            period = periods[0]
            if period["kind"] == "quarter" and kind in ("fy", "annual", "year"):
                return _fail("SHAPE_PERIOD_MISMATCH",
                             f"the ask names {period['label']}; the answer is an annual reading "
                             f"(period {day})")
            if not _inside(day, period["start"], period["end"]):
                return _fail("SHAPE_PERIOD_MISMATCH",
                             f"the ask names {period['label']}; the returned period is {day}")
            continue
        if any(_inside(day, p["start"], p["end"]) for p in periods):
            if quarters and kind in ("fy", "annual", "year"):
                return _fail("SHAPE_PERIOD_MISMATCH",
                             f"the ask names {', '.join(p['label'] for p in periods)}; the "
                             f"answer is an annual reading (period {day})")
            continue
        if _inside(day, window_start, window_end):
            continue
        return _fail("SHAPE_PERIOD_MISMATCH",
                     f"the ask names {', '.join(p['label'] for p in periods)}; the returned "
                     f"period is {day}")
    return None


def shape_failures(row: Mapping[str, Any],
                   shapes: Mapping[str, Any] | None = None) -> list[dict[str, str]]:
    """Every named shape failure for one graded row (empty when the shape holds)."""
    shapes = shapes or question_shapes(row.get("question") or "")
    out = []
    for check in (_set_one_entity, _compare_one_side, _judgement_no_rule,
                  _change_over_window, _duplicate_value, _list_dump,
                  _forecast_spot, _period_mismatch):
        failure = check(row, shapes)
        if failure:
            out.append(failure)
    return out


def shape_reasons(row: Mapping[str, Any],
                  shapes: Mapping[str, Any] | None = None) -> list[str]:
    return [failure["reason"] for failure in shape_failures(row, shapes)]


# ---------------------------------------------------------------------------
# 3. rubric scoring (the cheap test)
# ---------------------------------------------------------------------------
def _answer_text(row: Mapping[str, Any]) -> str:
    """The answer plus every quote/value it carries: what a judge would read."""
    parts = [str(row.get("answer_full") or row.get("answer") or "")]
    for result in _results(row):
        if result.get("rule_used"):
            parts.append(str(result["rule_used"]))
        if result.get("verdict"):
            parts.append(str(result["verdict"]))
        for value in result.get("values") or []:
            if isinstance(value, Mapping):
                parts.append(str(value.get("quote") or ""))
                parts.append(str(value.get("metric") or ""))
    return " ".join(parts)


def _coverage(clause: str, words: set[str]) -> float:
    wanted = _words(clause)
    if not wanted:
        return 1.0
    return sum(1 for word in wanted if word in words) / len(wanted)


def _steps_of(value: Any) -> list[str]:
    if not value:
        return []
    text = value if isinstance(value, str) else "; ".join(map(str, value))
    steps = [step.strip() for step in re.split(r"\s*->\s*", text) if step.strip()]
    if len(steps) <= 1:
        steps = [step.strip() for step in text.split(";") if step.strip()]
    return steps


def _forbidden_hit(value: Any, words: set[str]) -> bool:
    for clause in _steps_of(value):
        wanted = set(_words(clause))
        if wanted and len(wanted & words) / len(wanted) >= 0.7:
            return True
    return False


def _gold_present(value: Any, words: set[str], text: str) -> bool:
    if not value:
        return True
    gold = value if isinstance(value, str) else "; ".join(map(str, value))
    numbers = [number for number in re.findall(r"\b\d[\d,.]{2,}\b", gold)
               if not re.fullmatch(r"20\d\d", number)]
    if numbers:
        return any(number.replace(",", "") in text.replace(",", "") for number in numbers)
    wanted = set(_words(gold))
    return bool(wanted) and len(wanted & words) / len(wanted) >= 0.5


def rubric_score(row: Mapping[str, Any], rubric: Mapping[str, Any]) -> dict[str, Any]:
    """Score one answer against the bank's own rubric, lexically and conservatively.

    ``required_steps`` is prose: this can only check that each step's words appear in
    the answer, never that the arithmetic was done.  ``verdict`` is ``None`` when the
    rubric has no steps and no gold — the rubric cannot judge that row at all.
    """
    rubric = rubric or {}
    text = _answer_text(row)
    words = set(_words(text))
    steps = _steps_of(rubric.get("required_steps"))
    covered = [_coverage(step, words) >= 0.34 for step in steps]
    forbidden = _forbidden_hit(rubric.get("forbidden"), words)
    gold = _gold_present(rubric.get("ground_truth"), words, text)
    out: dict[str, Any] = {
        "steps": len(steps), "steps_covered": sum(covered), "forbidden": forbidden,
        "gold": gold, "verdict": None, "reason": "",
    }
    if not steps and not rubric.get("ground_truth"):
        out["reason"] = "the rubric has no required_steps and no ground_truth"
        return out
    if forbidden:
        out.update(verdict="WRONG", reason="the answer walks into a forbidden step")
        return out
    if steps and not any(covered):
        out.update(verdict="WRONG", reason=f"none of the {len(steps)} required steps is covered")
        return out
    if steps and not all(covered):
        out.update(verdict="PARTIAL",
                   reason=f"{sum(covered)}/{len(steps)} required steps covered")
        return out
    if not gold:
        out.update(verdict="WRONG", reason="the gold reading is not in the answer")
        return out
    out.update(verdict="RIGHT", reason="every required step appears and the gold matches")
    return out


def _hand_verdicts(path: Path = SAMPLE40_MD) -> dict[str, str]:
    """mid -> the hand verdict's first word, parsed from the sample-40 table."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        mid = cells[1].strip("`* ")
        if not re.fullmatch(r"MB\d{4}(#[A-Z]+)?", mid):
            continue
        verdict = re.match(r"\**\s*(RIGHT|PARTIAL|WRONG)", cells[-1], re.I)
        if verdict:
            out[mid] = verdict.group(1).upper()
    return out


def rubric40(graded_path: Path, bank: Mapping[str, Mapping[str, Any]],
             sample_md: Path = SAMPLE40_MD) -> dict[str, Any]:
    """The brief's cheap test: does the rubric agree with the 40 hand verdicts?"""
    hand = _hand_verdicts(sample_md)
    rows = {}
    with Path(graded_path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(row.get("mid")) in hand:
                rows[str(row["mid"])] = row
    agree = exact = 0
    undecidable = 0
    right_certified = right_total = wrong_failed = wrong_total = 0
    scored_verdicts: Counter = Counter()
    misses = []
    for mid, verdict in hand.items():
        right_total += int(verdict == "RIGHT")
        wrong_total += int(verdict == "WRONG")
        row = rows.get(mid)
        if row is None:
            continue
        parent = bank.get(mid.split("#")[0]) or {}
        scored = rubric_score(row, parent.get("rubric") or {})
        scored_verdicts[str(scored["verdict"])] += 1
        if scored["verdict"] is None:
            undecidable += 1
            misses.append((mid, verdict, "no rubric"))
            continue
        exact += int(scored["verdict"] == verdict)
        agree += int((scored["verdict"] == "RIGHT") == (verdict == "RIGHT"))
        right_certified += int(verdict == "RIGHT" and scored["verdict"] == "RIGHT")
        wrong_failed += int(verdict == "WRONG" and scored["verdict"] != "RIGHT")
        if scored["verdict"] != verdict:
            misses.append((mid, verdict, scored["verdict"]))
    return {
        "rows": len(hand), "scored": len(rows), "judged": len(rows) - undecidable,
        "agreement_exact": exact, "agreement_right_only": agree,
        "agreement_needed": len(hand) if len(hand) <= 30 else 30,
        "undecidable": undecidable,
        "right_certified": right_certified, "right_rows": right_total,
        "wrong_failed": wrong_failed, "wrong_rows": wrong_total,
        "scored_verdicts": dict(scored_verdicts),
        "usable": exact >= 30,
        "misses": misses,
    }


# ---------------------------------------------------------------------------
# 4. truth: contract + shape + text-derived checks
# ---------------------------------------------------------------------------
def parent_of(mid: str, bank: Mapping[str, Any],
              instances: Mapping[str, Any]) -> Mapping[str, Any]:
    parent_mid = (instances.get(mid) or {}).get("parent_mid") or mid.split("#")[0]
    return bank.get(parent_mid) or {}


def entity_text_mismatch(row: Mapping[str, Any],
                         parent: Mapping[str, Any] | None) -> dict[str, str] | None:
    """The question text names the parent's company while the answer is another one.

    Instances are renamed by ``instantiate.py``; a handful keep the parent's company in
    the question (Ola Electric's listing asked of Bosch).  The parent row is the
    authority: when its name or symbol is still in the instance text and the instance
    entity differs from it, the answer cannot be an answer to that text.
    """
    if not parent:
        return None
    # ``as_is`` rows run on the parent's own entities; only a substituted instance
    # (``stock`` / ``sector`` …) can keep the parent's company in a renamed question.
    if str(row.get("kind") or "") in ("", "original", "as_is"):
        return None
    parent_entities = [e for e in parent.get("entities") or [] if isinstance(e, Mapping)]
    parent_isins = {str(e.get("isin")) for e in parent_entities if e.get("isin")}
    answer_isin = str(row.get("entity") or "")
    # an index/sector row names no company: nothing to compare the text with
    if not answer_isin:
        return None
    if answer_isin in parent_isins:
        return None
    text = _norm(row.get("question"))
    for entity in parent_entities:
        for key in ("name", "symbol"):
            token = _norm(entity.get(key))
            if not token or len(token) < 4:
                continue
            words = [w for w in re.findall(r"[a-z0-9]+", token) if w not in _STOP]
            candidates = {token, " ".join(words[:2]) if len(words) >= 2 else token}
            # "State Bank of India" -> SBI: the instance text often keeps the parent's
            # acronym while the row entity has been renamed (MB1027#L: SBI -> BAJFINANCE).
            acronym = "".join(word[0] for word in words)
            if len(acronym) >= 3:
                candidates.add(acronym)
            if any(candidate and candidate in text for candidate in candidates):
                return _fail(
                    "TRUTH_ENTITY_TEXT_MISMATCH",
                    f"the question text names {entity.get('name') or entity.get('symbol')}, "
                    f"the answer is for {answer_isin or 'another entity'}")
    return None


def _evidence_text(row: Mapping[str, Any]) -> str:
    """What the results actually carry: atoms, dims, units, quotes — not the prose.

    The rendered answer echoes the question's own measure words, so a measure test run
    over it would always pass; this is the executor's output only.
    """
    parts: list[str] = []
    for result in _results(row):
        parts += [str(result.get("atom") or ""), str(result.get("formula") or ""),
                  str(result.get("unit") or ""), str(result.get("rule_used") or ""),
                  str(result.get("verdict") or ""),
                  " ".join(f"{key} {value}" for key, value in (result.get("dims") or {}).items())]
        for value in result.get("values") or []:
            if isinstance(value, Mapping):
                parts += [str(value.get("quote") or ""), str(value.get("metric") or "")]
                parts += [f"{key} {item}" for key, item in (value.get("dims") or {}).items()]
    return " ".join(parts)


def _sma_windows(row: Mapping[str, Any]) -> set[str]:
    """The SMA windows an answer actually declares (result or row dims)."""
    out: set[str] = set()
    for result in _covered_results(row):
        if str(result.get("atom") or "") != "price.sma":
            continue
        sources = [result.get("dims") or {}]
        sources += [value.get("dims") or {} for value in result.get("values") or []
                    if isinstance(value, Mapping)]
        for source in sources:
            for key in ("window", "window_days", "lag"):
                if source.get(key) not in (None, ""):
                    out.add(str(source[key]))
        for key in ("window", "window_days", "lag"):
            if result.get(key) not in (None, ""):
                out.add(str(result[key]))
    return out


def measure_shortfall(row: Mapping[str, Any],
                      shapes: Mapping[str, Any] | None = None) -> dict[str, str] | None:
    """A measure the question names that no part or passage answers.

    Two outcomes, both stated in the returned dict:
    * a one-entity "stored vs computed" ask with fewer than two distinct values is
      ``PARTIAL`` — half the comparison is missing (the read's MB0064 class);
    * a derived measure the question names and no part carries is ``WRONG`` — the
      answer returned a nearby measure (the read's dominant failure).
    """
    question = _norm(row.get("question"))
    text = _norm(_evidence_text(row))
    shapes = shapes or question_shapes(row.get("question") or "")
    if shapes.get("measure_vs") or re.search(r"\bvs\.?\s+(the\s+)?stored\b", question):
        values = {round(value, 6) for result in _covered_results(row)
                  for value in [_num(result.get("value"))] if value is not None}
        if len(values) < 2:
            return {"reason": "TRUTH_MEASURE_MISSING", "verdict": "PARTIAL",
                    "detail": "the question compares two measure readings; the answer "
                              "carries one value"}
    if any(str(result.get("atom") or "") == "price.sma" for result in _covered_results(row)):
        windows = _sma_windows(row)
        for match in _DAY_AVG_RE.finditer(question):
            window = match.group(1)
            if window in windows:
                continue
            return {"reason": "TRUTH_MEASURE_MISSING",
                    "verdict": "WRONG" if windows else "PARTIAL",
                    "detail": f"the question names the {window}-day average; the answer's "
                              f"SMA result declares {sorted(windows) if windows else 'no window'}"}
    for label, synonyms in _MEASURE_TERMS:
        if not any(synonym in question for synonym in synonyms):
            continue
        if any(synonym in text for synonym in synonyms):
            continue
        return {"reason": "TRUTH_MEASURE_MISSING", "verdict": "WRONG",
                "detail": f"the question asks for {label}; no part or passage carries it"}
    return None


def question_part_shortfall(row: Mapping[str, Any],
                            shapes: Mapping[str, Any]) -> dict[str, str] | None:
    """A two-ask question answered with fewer than two measured parts.

    ``_MULTI_RE`` reads "..., and what was ..." from the question text alone.  The
    decomposer's own Ask does not have to emit that second part, so the contract check
    cannot see the gap; this is the read's ``PART_MISSING`` class (MB0031#MS).
    """
    if not shapes.get("multi"):
        return None
    asked = max(2, str(row.get("question") or "").count("?"))
    answered = int(row.get("real_answered") or 0)
    if answered < asked:
        return {"reason": "TRUTH_PART_MISSING", "verdict": "PARTIAL",
                "detail": f"the question asks {asked} things; {answered} measured part(s) "
                          "were answered"}
    return None



def part_other_entity(row: Mapping[str, Any],
                      shapes: Mapping[str, Any]) -> dict[str, str] | None:
    """A part answers for a company other than the one the case resolved.

    ``run.py`` resolves one pilot ISIN per case and gives it to every non-cross part; a
    part whose row carries a different ISIN read another company (a ``count`` over a
    multi-entity series is the common way this happens).
    """
    entity = str(row.get("entity") or "")
    if not entity or shapes.get("set") or shapes.get("compare"):
        return None
    for result in _covered_results(row):
        isin = str(result.get("isin") or "")
        if isin and isin != entity:
            return _fail("TRUTH_PART_OTHER_ENTITY",
                         f"the case entity is {entity}; part "
                         f"{int(result.get('part_index') or 0) + 1} answers for {isin}")
    return None


def row_dim_mismatch(row: Mapping[str, Any]) -> dict[str, str] | None:
    """A part asks one slice of a dim; its stored rows all carry a different one.

    The contract grader compares the part's dims with the *result's* dims, and the
    executor copies them across, so it cannot see this; the rows are the evidence.  Only
    selector dims a row names in its own record are compared (the claim table puts
    ``topic`` / ``doctype`` at the top level, facts put dims under ``dims``).
    """
    for result in _covered_results(row):
        asked = {str(key).lower(): str(value).lower()
                 for key, value in (result.get("dims") or {}).items()
                 if str(key).lower() in _ROW_DIMS and value not in (None, "", "each", "sum")}
        if not asked:
            continue
        rows: list[dict[str, str]] = []
        for value in result.get("values") or []:
            if not isinstance(value, Mapping):
                continue
            record = {str(key).lower(): str(item).lower()
                      for key, item in (value.get("dims") or {}).items()}
            record.update({str(key).lower(): str(value[key]).lower()
                           for key in _ROW_DIMS if key in value})
            rows.append(record)
        for key, wanted in asked.items():
            got = [record[key] for record in rows if key in record]
            if got and all(item != wanted for item in got):
                return _fail(
                    "TRUTH_ROW_DIM_MISMATCH",
                    f"part {int(result.get('part_index') or 0) + 1} asks {key}={wanted}; "
                    f"every stored row says {key}={', '.join(sorted(set(got))[:3])}")
    return None


# ---------------------------------------------------------------------------
# 4. premise audit and the independent store read
# ---------------------------------------------------------------------------
_AUDIT_CACHE: dict[str, dict[str, dict]] = {}


def load_premise_audit(path: Path | str = PREMISE_AUDIT) -> dict[str, dict]:
    """``mid -> audit row`` from the committed premise audit (empty when absent)."""
    key = str(Path(path))
    if key not in _AUDIT_CACHE:
        out: dict[str, dict] = {}
        target = Path(path)
        if target.exists():
            with target.open(encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    out[str(row.get("mid"))] = row
        _AUDIT_CACHE[key] = out
    return _AUDIT_CACHE[key]


def premise_verdict(row: Mapping[str, Any], parent: Mapping[str, Any] | None,
                    audit: Mapping[str, dict] | None = None) -> dict[str, str] | None:
    """ILL_POSED when the stores contradict the question's premise.

    Two independent pieces of evidence, both deterministic:
    * the premise audit says ``false`` (the held stores contradict the stated fact);
    * the question text names the parent's company while the answer is another one.
    ``cannot_check`` is not evidence either way and never raises ILL_POSED.
    """
    mid = str(row.get("mid") or "")
    audit_row = (audit if audit is not None else load_premise_audit()).get(mid) or {}
    if str(audit_row.get("verdict") or "") == "false":
        evidence = (audit_row.get("evidence") or [{}])[0]
        reason = str(audit_row.get("reason") or "premise_false")
        detail = str(evidence.get("value") or reason)
        return {"verdict": "ILL_POSED", "reason": "ILL_POSED_PREMISE_FALSE",
                "detail": f"premise audit: {reason}: {detail}"[:500]}
    mismatch = entity_text_mismatch(row, parent)
    if mismatch:
        return {"verdict": "ILL_POSED", "reason": "ILL_POSED_ENTITY_MISMATCH",
                "detail": mismatch["detail"]}
    return None


def _row_dims(text: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in str(text or "").split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            out[key.strip().lower()] = value.strip().lower()
    return out


#: dims the pilot fact rows actually carry and a result may name.  Virtual dims the
#: executor adds (``basis=adjusted`` on a close) are not in the row and are ignored.
_STORE_DIMS = {"holder_class", "topic", "doctype", "basis", "period_kind", "derived",
               "consolidation", "event_kind"}


class StoreReader:
    """Read-only pilot store, by entity/measure/period — never by ``source_ref``."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root or V4_ROOT)
        self.fact = self._open(self.root / "fact_v4_pilot.db")
        self.v4 = self._open(self.root / "v4.db")
        self._cache: dict[tuple, list[dict[str, Any]]] = {}

    @staticmethod
    def _open(path: Path):
        if not path.is_file():
            return None
        try:
            return sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
        except sqlite3.Error:
            return None

    @property
    def available(self) -> bool:
        return self.fact is not None

    def fact_rows(self, isin: str, atom: str, start: str, end: str) -> list[dict[str, Any]]:
        """Rows for one entity/atom over a period window, ordered by period end."""
        if not self.fact or not isin or not atom:
            return []
        key = (isin, atom, start, end)
        if key in self._cache:
            return self._cache[key]
        try:
            rows = self.fact.execute(
                "SELECT entity_id, atom, dims, period_start, period_end, value, unit, known_at "
                "FROM fact WHERE entity_id=? AND atom=? AND period_end>=? AND period_end<=? "
                "ORDER BY period_end", (isin, atom, start, end)).fetchall()
        except sqlite3.Error:
            rows = []
        out = [dict(zip(("entity_id", "atom", "dims", "period_start", "period_end",
                         "value", "unit", "known_at"), row)) for row in rows]
        self._cache[key] = out
        return out

    def close(self) -> None:
        for connection in (self.fact, self.v4):
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error:
                    pass
        self.fact = self.v4 = None

    def __enter__(self) -> "StoreReader":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _match_dims(rows: list[dict[str, Any]], dims: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Filter rows to the named dims the rows actually carry (virtual dims ignored)."""
    asked = {str(key).lower(): str(value).lower()
             for key, value in (dims or {}).items()
             if str(key).lower() in _STORE_DIMS
             and str(value).lower() not in ("", "each", "sum", "all")}
    if not asked:
        return rows
    carried = {key for row in rows for key in _row_dims(row.get("dims"))}
    wanted = {key: value for key, value in asked.items() if key in carried}
    if not wanted:
        return rows
    return [row for row in rows
            if all(_row_dims(row.get("dims")).get(key) == value
                   for key, value in wanted.items())]


def _value_close(answer: Any, store_value: Any) -> bool:
    answer_num, store_num = _num(answer), _num(store_value)
    if answer_num is None or store_num is None:
        return False
    return abs(answer_num - store_num) <= max(
        VALUE_TOLERANCE_ABS, VALUE_TOLERANCE_REL * abs(store_num))


def _candidate_values(rows: list[dict[str, Any]]) -> list[float]:
    return [value for value in (_num(row.get("value")) for row in rows) if value is not None]


def _compare_rows(rows: list[dict[str, Any]], answer: Any) -> tuple[str, str]:
    """Match / mismatch / unverified for one value against its store candidates."""
    values = _candidate_values(rows)
    if not values:
        return "unverified", "the store has no numeric row for this measure and period"
    distinct = {round(value, 9) for value in values}
    matches = [value for value in values if _value_close(answer, value)]
    if len(matches) == len(values):
        return "match", f"store {values[0]:,.6g}"
    if len(distinct) == 1:
        return "mismatch", f"store {values[0]:,.6g} vs answer {answer}"
    if len(matches) == 1:
        return "unverified", (
            f"the store carries {len(values)} slices at this period "
            f"({', '.join(f'{value:,.6g}' for value in values)}); the answer names no slice")
    return "mismatch", f"store {values[0]:,.6g} vs answer {answer}"


def _result_entity(row: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    return str(result.get("isin") or row.get("entity") or "")


def _unverified(detail: str) -> dict[str, str]:
    return {"status": "unverified", "detail": detail}


def _mismatch(detail: str) -> dict[str, str]:
    return {"status": "mismatch", "detail": detail}


def _match(detail: str) -> dict[str, str]:
    return {"status": "match", "detail": detail}


def _verify_cagr(store: StoreReader, result: Mapping[str, Any], isin: str,
                 question: str) -> dict[str, str]:
    years = re.search(r"(\d+(?:\.\d+)?)[- ]year", question, re.I)
    end = (_day(result.get("period"))
           or max((period["end"] for period in asked_periods(question)), default=""))
    if not years or not end or not isin:
        return _unverified("a CAGR needs the question's stated years, end date and entity")
    from datetime import date, timedelta
    try:
        start_target = (date.fromisoformat(end)
                        - timedelta(days=round(365.25 * float(years.group(1))))).isoformat()
    except ValueError:
        return _unverified("the CAGR end date is not a date")
    rows = store.fact_rows(isin, "price.close", "1900-01-01", end)
    if not rows:
        return _unverified("the store has no close series for the entity")
    before_end = [row for row in rows if (_day(row.get("period_end")) or "") and
                  _day(row.get("period_end")) <= end]
    before_start = [row for row in before_end
                    if (_day(row.get("period_end")) or "") <= start_target]
    if not before_end or not before_start:
        return _unverified("the store has no close on or before an endpoint")
    first, last = before_start[-1], before_end[-1]
    first_value, last_value = _num(first.get("value")), _num(last.get("value"))
    if not first_value or last_value is None:
        return _unverified("the store endpoints carry no number")
    store_cagr = ((last_value / first_value) ** (1.0 / float(years.group(1))) - 1.0) * 100.0
    detail = (f"{_day(first.get('period_end'))} {first_value:,.2f} -> "
              f"{_day(last.get('period_end'))} {last_value:,.2f} = {store_cagr:,.4g}%")
    if _value_close(result.get("value"), store_cagr):
        return _match(detail)
    return _mismatch(f"{detail}; answer {result.get('value')}")


def verify_result(store: StoreReader, row: Mapping[str, Any],
                  result: Mapping[str, Any], question: str) -> dict[str, str]:
    """Reproduce one result's value from the store, or say why it cannot be.

    ``match`` certifies the value; ``mismatch`` is a wrong value; ``unverified`` is
    everything the independent read cannot settle (text, an estimate, an ambiguous
    slice).  Only ``match`` can contribute to RIGHT.
    """
    operator = str(result.get("operator") or "value_at")
    atom = str(result.get("atom") or "")
    formula = str(result.get("formula") or "")
    isin = _result_entity(row, result)
    if str(result.get("answer_type") or "") == "estimate":
        return _unverified("an estimate is our own forecast; the store holds no realised value")
    if atom.startswith("claim.") or atom == "text.passage" or result.get("value") is None:
        return _unverified("a text part carries no numeric store value")
    if formula == "f.cagr" or atom == "f.cagr":
        return _verify_cagr(store, result, isin, question)
    if formula or not atom:
        return _unverified(f"no independent read for formula {formula or atom or 'unknown'}")
    if atom == "price.shares_out":
        return _unverified("the fact store carries the XBRL-rounded count; the exact "
                           "filing count is the authority")
    if not store.available:
        return _unverified("the pilot store is not available")
    dims = result.get("dims") or {}

    if operator in ("value_at", "series", "last_visible", "first_visible"):
        period = _day(result.get("period"))
        if not period:
            return _unverified("the result names no period")
        rows = _match_dims(store.fact_rows(isin, atom, period, period), dims)
        if operator in ("last_visible", "first_visible"):
            history = _match_dims(store.fact_rows(isin, atom, "1900-01-01", period), dims)
            if not history:
                return _unverified("the store has no row at or before this period")
            edge = history[-1] if operator == "last_visible" else history[0]
            edge_period = _day(edge.get("period_end"))
            if edge_period != period:
                side = "last" if operator == "last_visible" else "first"
                return _mismatch(f"the store's {side} row is {edge_period}, "
                                 f"the answer says {period}")
            rows = [row for row in history if _day(row.get("period_end")) == edge_period]
        status, detail = _compare_rows(rows, result.get("value"))
        return {"status": status, "detail": detail}

    if operator in ("change", "pct_change", "growth"):
        numbers = result.get("numbers") or {}
        start, end = _day(numbers.get("from")), _day(numbers.get("to"))
        if not start or not end:
            return _unverified("the result names no endpoints")
        first_rows = _match_dims(store.fact_rows(isin, atom, start, start), dims)
        last_rows = _match_dims(store.fact_rows(isin, atom, end, end), dims)
        first_status, first_detail = _compare_rows(first_rows, numbers.get("first"))
        last_status, last_detail = _compare_rows(last_rows, numbers.get("last"))
        if first_status != "match" or last_status != "match":
            if "mismatch" in (first_status, last_status):
                return _mismatch(f"{first_detail}; {last_detail}")
            return _unverified(f"{first_detail}; {last_detail}")
        first_value = _num(first_rows[0].get("value"))
        last_value = _num(last_rows[0].get("value"))
        if first_value is None or last_value is None:
            return _unverified("an endpoint carries no number")
        if operator == "change":
            store_value = last_value - first_value
        else:
            if not first_value:
                return _unverified("the first endpoint is zero")
            store_value = 100.0 * (last_value - first_value) / abs(first_value)
        detail = f"{start} {first_value:,.6g} -> {end} {last_value:,.6g} = {store_value:,.6g}"
        if _value_close(result.get("value"), store_value):
            return _match(detail)
        return _mismatch(f"{detail}; answer {result.get('value')}")

    if operator in ("max_with_date", "min_with_date"):
        window = result.get("window") or {}
        start = _day(window.get("from") or window.get("start"))
        end = _day(window.get("to") or window.get("end"))
        if not start or not end:
            periods = asked_periods(question)
            if not periods:
                return _unverified("the extreme names no window")
            start = min(period["start"] for period in periods)
            end = max(period["end"] for period in periods)
        rows = _match_dims(store.fact_rows(isin, atom, start, end), dims)
        values = [(value, _day(row.get("period_end"))) for row in rows
                  for value in [_num(row.get("value"))] if value is not None]
        if not values:
            return _unverified("the store has no rows in the window")
        pick = (max if operator == "max_with_date" else min)(values, key=lambda pair: pair[0])
        detail = f"{pick[0]:,.6g} on {pick[1]}"
        if _value_close(result.get("value"), pick[0]) and (
                not _day(result.get("period")) or _day(result.get("period")) == pick[1]):
            return _match(detail)
        return _mismatch(f"{detail}; answer {result.get('value')} "
                         f"on {_day(result.get('period')) or 'no date'}")

    return _unverified(f"no independent read for operator {operator}")


def store_verdict(row: Mapping[str, Any], store: StoreReader | None,
                  question: str) -> dict[str, str]:
    """RIGHT only when every measured part is reproduced from the store."""
    results = _covered_results(row)
    if not results:
        return {"verdict": "PARTIAL", "reason": "TRUTH_VALUE_UNVERIFIED",
                "detail": "no measured part to compare with the store"}
    if store is None:
        return {"verdict": "PARTIAL", "reason": "TRUTH_VALUE_UNVERIFIED",
                "detail": "no independent store read was supplied"}
    outcomes = [verify_result(store, row, result, question) for result in results]
    mismatches = [outcome["detail"] for outcome in outcomes if outcome["status"] == "mismatch"]
    if mismatches:
        return {"verdict": "WRONG", "reason": "TRUTH_VALUE_WRONG",
                "detail": "; ".join(mismatches)[:500]}
    unverified = [outcome["detail"] for outcome in outcomes
                  if outcome["status"] == "unverified"]
    if unverified:
        return {"verdict": "PARTIAL", "reason": "TRUTH_VALUE_UNVERIFIED",
                "detail": "; ".join(unverified)[:500]}
    return {"verdict": "RIGHT", "reason": "TRUTH_OK",
            "detail": f"all {len(outcomes)} part(s) reproduced from the store within "
                      f"{100 * VALUE_TOLERANCE_REL:g}%"}


def _gold_numbers(value: Any) -> list[str]:
    """Only numeric gold readings are used; a prose gold is retired with the rubric."""
    if not value:
        return []
    gold = value if isinstance(value, str) else "; ".join(map(str, value))
    return [number for number in re.findall(r"\b\d[\d,.]{2,}\b", gold)
            if not re.fullmatch(r"20\d\d", number)]


def _gold_present_numeric(value: Any, text: str) -> bool:
    numbers = _gold_numbers(value)
    if not numbers:
        return True
    haystack = text.replace(",", "")
    return any(number.replace(",", "") in haystack for number in numbers)



def truth_verdict(row: Mapping[str, Any], parent: Mapping[str, Any] | None = None,
                  shapes: Mapping[str, Any] | None = None,
                  store: StoreReader | None = None,
                  audit: Mapping[str, dict] | None = None) -> dict[str, Any]:
    """RIGHT / PARTIAL / WRONG / ILL_POSED for one graded row, with a one-line reason.

    Order matters and is deliberately strict: ILL_POSED first (no answer can be right
    when the question is false), then a part read for another company, the named shape
    failures, the measure/part coverage tests, and only then the independent store
    read.  A RIGHT needs every measured part reproduced from the store; a text part,
    an estimate or an ambiguous slice is PARTIAL, never RIGHT.
    """
    shapes = shapes or question_shapes(row.get("question") or "")
    if not row.get("covered"):
        reasons = row.get("reasons") or []
        first = re.sub(r"\(.*", "", str(reasons[0])).strip() if reasons else "not covered"
        return {"verdict": "WRONG", "reason": "TRUTH_NOT_ANSWERED", "detail": first or "no answer"}

    premise = premise_verdict(row, parent, audit)
    if premise:
        return premise
    other = part_other_entity(row, shapes)
    if other:
        return other | {"verdict": "WRONG"}
    failures = shape_failures(row, shapes)
    if failures:
        first = failures[0]
        return {"verdict": "WRONG", "reason": first["reason"], "detail": first["detail"]}

    shortfall = measure_shortfall(row, shapes)
    if shortfall:
        return shortfall
    missing = question_part_shortfall(row, shapes)
    if missing:
        return missing
    dims = row_dim_mismatch(row)
    if dims:
        return dims | {"verdict": "WRONG"}

    rubric = (parent or {}).get("rubric") or {}
    gold = rubric.get("ground_truth")
    if gold and not _gold_present_numeric(gold, _norm(_answer_text(row))):
        return {"verdict": "PARTIAL", "reason": "TRUTH_GOLD_MISSING",
                "detail": "the rubric's numeric gold reading is not in the answer"}
    return store_verdict(row, store, str(row.get("question") or ""))



# ---------------------------------------------------------------------------
# 5. the panel
# ---------------------------------------------------------------------------
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials (0,0 -> (0,0))."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def _stratum(row: Mapping[str, Any], shapes: Mapping[str, Any]) -> tuple[str, str, str, str]:
    bucket = str(row.get("bucket") or row.get("entity_level") or "none")
    family = row.get("family") or []
    family_key = f"F{family[0]}" if isinstance(family, list) and family else "F?"
    return ("answered" if row.get("covered") else "unanswered", bucket, family_key,
            shape_label(shapes))


def _allocate(pools: Mapping[tuple, list[dict]],
              counts: Mapping[str, int]) -> list[dict]:
    """Round-robin over strata, taking the exact number of rows each group asks for."""
    picked: list[dict] = []
    for group, wanted in counts.items():
        keys = sorted(key for key in pools if key[0] == group)
        queues = {key: list(pools[key]) for key in keys}
        taken = 0
        while taken < wanted and any(queues.values()):
            for key in keys:
                if queues[key] and taken < wanted:
                    picked.append(queues[key].pop(0))
                    taken += 1
    return picked


def load_maps() -> tuple[dict[str, dict], dict[str, dict]]:
    def load(path: Path) -> dict[str, dict]:
        out = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    out[str(row.get("mid"))] = row
        return out
    return load(BANK), load(INSTANCES)


def panel_index(graded_path: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """Pass 1: per-stratum candidate lists (mids + shape labels), plus the answers.

    Only labels are kept per row — the graded file is ~355 MB and holding its rows as
    dicts is what the worker machine cannot afford.  Pass 2 re-reads the file for the
    handful of mids the panel actually picked.
    """
    pools: dict[tuple, list[dict]] = defaultdict(list)
    stats = Counter()
    with Path(graded_path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            shapes = question_shapes(row.get("question") or "")
            key = _stratum(row, shapes)
            stats["rows"] += 1
            stats["answered"] += int(bool(row.get("covered")))
            pools[key].append({"mid": str(row.get("mid")), "_group": key[0]})
    return pools, {"rows": stats["rows"], "answered": stats["answered"]}


def _pick(pools: Mapping[tuple, list[dict]], seed: int, total: int) -> list[dict]:
    rng = random.Random(seed)
    shuffled = {key: rng.sample(rows, len(rows)) for key, rows in pools.items()}
    answered = round(total * PANEL_ANSWERED_SHARE)
    return _allocate(shuffled, {"answered": answered, "unanswered": total - answered})


def _panel_row(row: Mapping[str, Any], parent: Mapping[str, Any], panel: str,
               seed: int, store: StoreReader | None = None,
               audit: Mapping[str, dict] | None = None) -> dict[str, Any]:
    shapes = question_shapes(row.get("question") or "")
    verdict = truth_verdict(row, parent, shapes, store=store, audit=audit)
    failures = shape_failures(row, shapes)
    if verdict["verdict"] == "ILL_POSED":
        # the split: a premise failure is reported as a premise failure, not as a
        # missing rule_used block (the read's SHAPE_JUDGEMENT_NO_RULE half)
        failures = [failure for failure in failures
                    if failure["reason"] != "SHAPE_JUDGEMENT_NO_RULE"]
    full = re.sub(r"\s+", " ", str(row.get("answer") or ""))
    return {
        "panel": panel, "seed": seed, "mid": row.get("mid"),
        "parent_mid": row.get("parent_mid") or str(row.get("mid")).split("#")[0],
        "bucket": row.get("bucket") or row.get("entity_level"),
        "family": row.get("family"), "shape": shape_label(shapes),
        "contract": bool(row.get("covered")),
        "real_answered": int(row.get("real_answered") or 0),
        "as_of": row.get("as_of"), "entity": row.get("entity"),
        "question": str(row.get("question") or "")[:240],
        "answer": full[:400],
        #: the full render, beside the display copy: 82 of 127 read-graded rows were
        #: truncated at 400 characters, which hides later parts from a reader.
        "answer_full": full,
        "verdict": verdict["verdict"], "reason": verdict["reason"],
        "detail": verdict.get("detail") or "",
        "premise": (verdict.get("detail") or "") if verdict["verdict"] == "ILL_POSED" else "",
        "shape_failures": [failure["reason"] for failure in failures],
    }


def _panel_summary(graded: list[dict[str, Any]], stats: Mapping[str, Any]) -> dict[str, Any]:
    """Per-panel counts.  ILL_POSED has its own column and stays in `answered`."""
    report: dict[str, Any] = {
        "rows": len(graded),
        "fixed": sum(1 for row in graded if row["panel"] == "fixed"),
        "fresh": sum(1 for row in graded if row["panel"] == "fresh40"),
        "answered": sum(1 for row in graded if row["contract"]),
        "bank_rows": stats["rows"], "bank_answered": stats["answered"],
    }
    for panel_name in ("fixed", "fresh40", "all"):
        subset = [row for row in graded if panel_name == "all" or row["panel"] == panel_name]
        answered = [row for row in subset if row["contract"]]
        answered_right = sum(1 for row in answered if row["verdict"] == "RIGHT")
        ill_posed = sum(1 for row in answered if row["verdict"] == "ILL_POSED")
        low, high = wilson(answered_right, len(answered))
        share = stats["answered"] / max(1, stats["rows"])
        report[panel_name] = {
            "rows": len(subset),
            "right": sum(1 for row in subset if row["verdict"] == "RIGHT"),
            "answered": len(answered), "answered_right": answered_right,
            "ill_posed": ill_posed,
            "ill_posed_share": round(100.0 * ill_posed / max(1, len(answered)), 2),
            "answered_precision": round(100.0 * answered_right / max(1, len(answered)), 2),
            "wilson_answered": [round(100.0 * low, 2), round(100.0 * high, 2)],
            "truth_pct": round(100.0 * share * answered_right / max(1, len(answered)), 2),
            "truth_wilson": [round(100.0 * share * low, 2), round(100.0 * share * high, 2)],
            "right_mids": [row["mid"] for row in subset if row["verdict"] == "RIGHT"],
            "ill_posed_mids": [row["mid"] for row in answered
                               if row["verdict"] == "ILL_POSED"],
            "by_reason": dict(Counter(row["reason"] for row in subset
                                      if row["verdict"] != "RIGHT").most_common(20)),
        }
    return report


def build_panel(graded_path: Path, out_path: Path = PANEL, fresh_seed: int | None = None,
                fixed_seed: int = SEED_PANEL, panel_n: int = PANEL_N,
                fresh_n: int = FRESH_N, verbose: bool = True,
                store: StoreReader | None = None,
                audit: Mapping[str, dict] | None = None) -> dict[str, Any]:
    """Draw the fixed 150-row panel plus a fresh 40 and grade every row.

    Pass 1 indexes the strata, pass 2 reads back only the picked rows.  The fixed block
    is the same rows (same seed) on every run; the fresh block's seed is printed and
    written into every one of its rows.  Every verdict is re-derived with the store
    read; ``answer_full`` rides beside the 400-character display copy.
    """
    bank, instances = load_maps()
    store = store if store is not None else StoreReader()
    audit = audit if audit is not None else load_premise_audit()
    pools, stats = panel_index(graded_path)
    fixed = _pick(pools, fixed_seed, panel_n)
    fresh_seed = fresh_seed if fresh_seed is not None else random.SystemRandom().randrange(1, 10**9)
    if fresh_seed == fixed_seed:
        # the same seed draws the same rows: a "fresh" block would duplicate the fixed one
        fresh_seed += 1
    fresh = _pick(pools, fresh_seed, fresh_n)
    wanted = {row["mid"] for row in fixed} | {row["mid"] for row in fresh}
    rows: dict[str, dict] = {}
    with Path(graded_path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            mid = str(row.get("mid"))
            if mid in wanted and mid not in rows:
                rows[mid] = row
    graded = []
    for pick in fixed:
        row = rows.get(pick["mid"])
        if row is not None:
            graded.append(_panel_row(row, parent_of(pick["mid"], bank, instances),
                                     "fixed", fixed_seed, store=store, audit=audit))
    for pick in fresh:
        row = rows.get(pick["mid"])
        if row is not None:
            graded.append(_panel_row(row, parent_of(pick["mid"], bank, instances),
                                     "fresh40", fresh_seed, store=store, audit=audit))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n"
                                for row in graded), encoding="utf-8")
    report = _panel_summary(graded, stats)
    report["fresh_seed"] = fresh_seed
    report["store_available"] = bool(store.available)
    if verbose and not store.available:
        print("panel: WARNING the pilot store is not available; every value stays "
              "PARTIAL (TRUTH_VALUE_UNVERIFIED)", flush=True)
    if verbose:
        for name in ("fixed", "fresh40", "all"):
            block = report[name]
            print(f"panel {name}: {block['rows']} rows, {block['right']} RIGHT, "
                  f"ILL_POSED {block['ill_posed']}/{block['answered']}, "
                  f"answered {block['answered']} ({block['answered_right']} RIGHT = "
                  f"{block['answered_precision']}%, Wilson {block['wilson_answered']}), "
                  f"truth {block['truth_pct']}% {block['truth_wilson']}", flush=True)
    return report



def read_confusion(graded_path: Path, read_path: Path = READ_PANEL,
                   store: StoreReader | None = None,
                   audit: Mapping[str, dict] | None = None) -> dict[str, Any]:
    """Run the new rules on the read-graded questions and tabulate read x new.

    ``read_path`` is ``TRUTH_PANEL_READ_2026-10-31.jsonl`` (the authority), one row per
    mid.  The graded file supplies the full answer, the results and the contract flags;
    the read file is never used as a grader input, only as the truth column.  A row is
    included when the read graded it and the contract answered it, so the denominator
    is the read's answered set.
    """
    read: dict[str, dict] = {}
    with Path(read_path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            read[str(row.get("mid"))] = row
    bank, instances = load_maps()
    store = store if store is not None else StoreReader()
    audit = audit if audit is not None else load_premise_audit()
    table: Counter = Counter()
    false_right: list[dict[str, Any]] = []
    missed_ill: list[dict[str, Any]] = []
    reasons: Counter = Counter()
    rows = 0
    with Path(graded_path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            mid = str(row.get("mid"))
            truth = read.get(mid)
            if truth is None or not row.get("covered"):
                continue
            verdict = truth_verdict(row, parent_of(mid, bank, instances),
                                    store=store, audit=audit)
            read_verdict = str(truth.get("verdict") or "UNVERIFIED")
            table[(read_verdict, verdict["verdict"])] += 1
            reasons[verdict["reason"]] += 1
            rows += 1
            if verdict["verdict"] == "RIGHT" and read_verdict != "RIGHT":
                false_right.append({
                    "mid": mid, "read": read_verdict, "read_reason": truth.get("reason_code"),
                    "reason": verdict["reason"], "detail": verdict.get("detail"),
                    "looked_up": truth.get("looked_up"),
                })
            if read_verdict == "ILL_POSED" and verdict["verdict"] != "ILL_POSED":
                missed_ill.append({
                    "mid": mid, "new": verdict["verdict"], "reason": verdict["reason"],
                    "read_reason": truth.get("reason_code"),
                    "read_evidence": str(truth.get("looked_up") or "")[:240],
                })
    read_rows = list(read.values())
    return {
        "rows": rows,
        "read_rows": len(read_rows),
        "read_right": sum(1 for row in read_rows if row.get("verdict") == "RIGHT"),
        "read_ill_posed": sum(1 for row in read_rows if row.get("verdict") == "ILL_POSED"),
        "new_ill_posed": sum(1 for (truth, new), count in table.items()
                             if new == "ILL_POSED" for _ in range(count)),
        "table": {f"{truth}|{new}": count for (truth, new), count in sorted(table.items())},
        "by_read": dict(Counter(
            truth for (truth, _new), count in table.items() for _ in range(count)).most_common()),
        "by_new": dict(Counter(
            new for (_truth, new), count in table.items() for _ in range(count)).most_common()),
        "false_right": false_right,
        "missed_ill_posed": missed_ill,
        "by_reason": dict(reasons.most_common(20)),
        "store_available": store.available,
        "graded": str(graded_path),
    }


def confusion_markdown(result: Mapping[str, Any]) -> str:
    """A compact read x new table for the report."""
    columns = ("RIGHT", "PARTIAL", "WRONG", "ILL_POSED")
    rows = ("RIGHT", "PARTIAL", "WRONG", "ILL_POSED")
    table = result.get("table") or {}
    lines = ["| read \\ new | " + " | ".join(columns) + " | total |",
             "|---|" + "---:|" * (len(columns) + 1)]
    for read in rows:
        cells = [int(table.get(f"{read}|{new}", 0)) for new in columns]
        lines.append(f"| {read} | " + " | ".join(str(cell) for cell in cells)
                     + f" | {sum(cells)} |")
    totals = [sum(int(table.get(f"{read}|{new}", 0)) for read in rows) for new in columns]
    lines.append("| total | " + " | ".join(str(cell) for cell in totals)
                 + f" | {sum(totals)} |")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--graded", type=Path,
                        default=BENCH / "GATE_RESULTS_v4_strict.jsonl")
    parser.add_argument("--rubric40", action="store_true",
                        help="the retired rubric's cheap test (diagnostic only)")
    parser.add_argument("--panel", action="store_true", help="build the truth panel")
    parser.add_argument("--read-check", action="store_true",
                        help="run the new rules on the read-graded questions")
    parser.add_argument("--read-panel", type=Path, default=READ_PANEL)
    parser.add_argument("--store-root", type=Path,
                        help="directory holding fact_v4_pilot.db / v4.db")
    parser.add_argument("--markdown", action="store_true", help="print the confusion table")
    parser.add_argument("--fresh-seed", type=int)
    args = parser.parse_args(list(argv) if argv is not None else None)
    bank, _ = load_maps()
    store = StoreReader(args.store_root)
    if args.rubric40:
        result = rubric40(args.graded, bank)
        print(json.dumps(result, indent=1, default=str))
        return 0
    if not args.graded.exists():
        print(f"no graded run at {args.graded}; the raw v4 run is gitignored — "
              "regenerate it with `python tasks/pilot60/gate_run.py v4`", flush=True)
        return 2
    if args.read_check:
        result = read_confusion(args.graded, args.read_panel, store=store)
        print(confusion_markdown(result) if args.markdown else "")
        print(json.dumps(result, indent=1, default=str))
        return 0
    if args.panel:
        report = build_panel(args.graded, fresh_seed=args.fresh_seed, store=store)
        print(json.dumps({key: value for key, value in report.items() if key != "fresh_seed"},
                         indent=1, default=str))
        return 0
    parser.error("pass --read-check, --panel or --rubric40")
    return 2



if __name__ == "__main__":
    raise SystemExit(main())
