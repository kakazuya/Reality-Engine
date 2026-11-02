"""The checks a KEC gap-loop row must pass before it is stored or an answer counted (T-048).

A number cites one of two sources.  A ``doc_text`` page: the quote occurs on it; the number occurs
in the quote (Indian digit grouping and crore/lakh/million words allowed); ``known_at`` is the page's
filing date and not after the as-of date.  A row of the sandbox's ``kec.db`` (``table`` + ``rowid``):
the value, and the quote when one is given, must occur in that row, and the row's own ``known_at``
is checked against the as-of date.  Both kinds also need a measure, a unit that suits it and a stated
period.  A malformed row fails the report; a number that fails a check only makes its row
``unverified``.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from reality_engine.contracts import CONTRACTS

STATUSES = ("answered", "partial", "not_found")
GAP_TYPES = ("text_missing", "not_extracted", "needs_formula", "wrong_store", "absent")
# A row the loop rewrote because a number failed a check.  Never reported by a model.
UNVERIFIED = "unverified"
MIN_QUOTE = 12
MAX_QUOTE = 2000
TOLERANCE = 0.002

MONEY_UNITS = {"inr", "rs", "rupees", "inr_cr", "crore", "cr", "inr_mn", "million", "mn",
               "billion", "bn", "lakh", "lac", "usd_mn"}
PCT_UNITS = {"pct", "%", "percent", "percentage"}
COUNT_UNITS = {"count", "nos", "units", "no", "number", "mw", "kw", "kt", "mt", "tonnes",
               "tpa", "tpd", "sqft", "days", "years", "x", "ratio", "times", "inr_per_unit"}
KNOWN_UNITS = MONEY_UNITS | PCT_UNITS | COUNT_UNITS

_PERIOD = re.compile(
    r"\b(?:FY\s?'?\d{2,4}|Q[1-4]\s?'?FY\s?'?\d{2,4}|[QH][1-4]\s?(?:FY\s?'?\d{2,4})?"
    r"|9M|6M|3M|CY\s?'?\d{2,4}|TTM|\d{4}-\d{2}-\d{2}"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}"
    r"|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4})\b",
    re.I,
)
_PCT_WORDS = re.compile(
    r"margin|growth|yield|return|ratio|rate|percent|share|utilisation|utilization|\bcagr\b|drawdown|\bmix\b",
    re.I,
)
_MONEY_WORDS = re.compile(
    r"revenue|turnover|income|ebitda|\bpat\b|profit|order ?book|order intake|order inflow|"
    r"net worth|capex|capital expenditure|debt|cash|amount|value|cost|receivable|inventory|"
    r"borrowing|investment|awarded|contract value|sales|ebit\b|expense|capacity",
    re.I,
)
_NUM = re.compile(
    # A number is not part of a word or a decimal fraction.  A period before it only disqualifies
    # when a digit precedes that period, so "Rs.1,23,456 crore" is read and "1.56" is not split.
    r"(?<![\w])(?<!\d\.)(\d[\d,]*(?:\.\d+)?)\s*"
    r"(?:(lakh|lac|crore|cr|million|mn|billion|bn|thousand)\b(?:\s*(crore|cr)\b)?"
    r"|(%|percent|per\s*cent)\b)?",
    re.I,
)
_WS = re.compile(r"\s+")
_DASHES = str.maketrans({"\u2013": "-", "\u2014": "-", "\u2212": "-", "\u00a0": " "})
_CRORE = {"inr_cr": 1.0, "crore": 1.0, "cr": 1.0, "inr_mn": 0.1, "million": 0.1, "mn": 0.1,
          "inr": 1e-7, "rs": 1e-7, "rupees": 1e-7, "billion": 100.0, "bn": 100.0,
          "lakh": 0.01, "lac": 0.01}


def normalise(text: object) -> str:
    return _WS.sub(" ", str(text or "").translate(_DASHES)).strip()


def _norm_unit(unit: object) -> str:
    return normalise(unit).lower().strip(".")


def _contract_units(measure: str) -> set[str]:
    """Units the typed contracts allow for this measure, when one of them names it."""
    key = re.sub(r"[^a-z0-9]+", "_", measure.lower()).strip("_")
    units: set[str] = set()
    for contract in CONTRACTS.values():
        for name, spec in contract.measures.items():
            if name == "_":
                continue
            if name == key or name.startswith(key + "_"):
                units.update(spec.units)
    return units


def measure_family(measure: str) -> str | None:
    """'pct', 'money' or None.  Growth and margin words win over money words: order intake growth is a percentage."""
    text = measure or ""
    if _PCT_WORDS.search(text):
        return "pct"
    if _MONEY_WORDS.search(text):
        return "money"
    return None


def unit_family(unit: str) -> str | None:
    value = _norm_unit(unit)
    if value in PCT_UNITS:
        return "pct"
    if value in MONEY_UNITS:
        return "money"
    return None


def check_unit(measure: str, unit: str) -> tuple[bool, str | None]:
    value = _norm_unit(unit)
    if not value:
        return False, "unit: missing"
    allowed = _contract_units(measure or "")
    if allowed and value not in allowed:
        return False, f"unit: {unit!r} is not in the typed contract for {measure!r} ({sorted(allowed)})"
    family, family_unit = measure_family(measure or ""), unit_family(value)
    if family and family_unit and family != family_unit:
        return False, f"unit: {unit!r} does not suit {measure!r} (a {family} measure)"
    if family_unit is None and value not in KNOWN_UNITS and not allowed:
        return False, f"unit: {unit!r} is not a known unit"
    return True, None


def check_quote(quote: str, page_text: str | None) -> tuple[bool, str | None]:
    text = normalise(quote)
    if len(text) < MIN_QUOTE:
        return False, "quote: missing or shorter than 12 characters"
    if len(text) > MAX_QUOTE:
        return False, "quote: longer than 2000 characters"
    page = normalise(page_text)
    if not page:
        return False, "quote: the cited page has no text in doc_text"
    if text not in page:
        return False, "quote: not on the cited page"
    return True, None


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= max(0.01, TOLERANCE * abs(right))


def _suffix_crore(suffix: str, compound: str) -> float | None:
    """A printed money suffix in Rs crore; None when the token carries no money suffix."""
    word = (suffix or "").lower()
    second = (compound or "").lower()
    if word in ("lakh", "lac"):
        return 1e5 if second in ("crore", "cr") else 0.01
    if word in ("crore", "cr"):
        return 1.0
    if word in ("million", "mn"):
        return 0.1
    if word in ("billion", "bn"):
        return 100.0
    if word == "thousand":
        return 0.001
    return None


def check_number(value: object, unit: str, quote: str) -> tuple[bool, str | None]:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False, "number: missing or not numeric"
    unit = _norm_unit(unit)
    family = unit_family(unit)
    target_crore = _CRORE.get(unit) if family == "money" else None
    text = normalise(quote)
    seen = False
    for match in _NUM.finditer(text):
        seen = True
        raw = float(match.group(1).replace(",", ""))
        suffix = match.group(2) or ""
        compound = match.group(3) or ""
        pct_suffix = (match.group(4) or "").lower().rstrip(".")
        if family == "money":
            if pct_suffix or target_crore is None:
                continue
            if _close(raw, number):
                return True, None
            scale = _suffix_crore(suffix, compound)
            if scale is not None and _close(raw * scale, number * target_crore):
                return True, None
        elif family == "pct":
            if _suffix_crore(suffix, compound) is not None:
                continue
            if _close(raw, number):
                return True, None
        else:
            if _suffix_crore(suffix, compound) is not None:
                continue
            if _close(raw, number):
                return True, None
    if not seen:
        return False, "number: the quote has no number"
    return False, "number: does not occur in the quote with that unit"


def check_period(period: str) -> tuple[bool, str | None]:
    text = normalise(period)
    if not text:
        return False, "period: not stated"
    if not _PERIOD.search(text):
        return False, f"period: {period!r} is not a period"
    return True, None


def _as_date(text: object) -> date | None:
    raw = normalise(text)
    if not raw:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def check_known_at(known_at: object, as_of: object, doc_known_at: object = None) -> tuple[bool, str | None]:
    when, limit = _as_date(known_at), _as_date(as_of)
    if when is None:
        return False, "known_at: missing or not a date"
    if limit is None:
        return False, "as_of: missing or not a date"
    if when > limit:
        return False, "known_at: after the as-of date"
    if doc_known_at is not None and _as_date(doc_known_at) != when:
        return False, "known_at: not the cited page's filing date"
    return True, None


def check_fact(row: dict, page_text: str | None, doc_known_at: object, as_of: object) -> tuple[bool, str | None]:
    """Every check a single fact/answer number must pass."""
    if not normalise(row.get("measure")):
        return False, "measure: missing, so its unit cannot be judged"
    for ok, reason in (
        check_quote(str(row.get("quote") or ""), page_text),
        check_number(row.get("value"), str(row.get("unit") or ""), str(row.get("quote") or "")),
        check_unit(str(row.get("measure") or ""), str(row.get("unit") or "")),
        check_period(str(row.get("period") or "")),
        check_known_at(row.get("known_at"), as_of, doc_known_at),
    ):
        if not ok:
            return False, reason
    return True, None


def _leaves(node, key: str | None = None):
    """``(key, leaf)`` for every scalar in a nested record."""
    if isinstance(node, dict):
        for name, value in node.items():
            yield from _leaves(value, str(name))
    elif isinstance(node, list):
        for value in node:
            yield from _leaves(value, key)
    else:
        yield key, node


def _as_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = normalise(value).replace(",", "").rstrip("%").strip()
    try:
        return float(text)
    except ValueError:
        return None


def check_row_fact(row: dict, as_of: object, row_lookup) -> tuple[bool, str | None]:
    """A number sourced from a ``kec.db`` row: the value, and the quote when given, must be in it."""
    table = normalise(row.get("table"))
    if not table:
        return False, "table: missing"
    if not normalise(row.get("measure")):
        return False, "measure: missing, so its unit cannot be judged"
    for ok, reason in (check_unit(str(row.get("measure") or ""), str(row.get("unit") or "")),
                       check_period(str(row.get("period") or ""))):
        if not ok:
            return False, reason
    try:
        record = row_lookup(table, row.get("rowid")) if row_lookup else None
    except Exception as exc:  # noqa: BLE001 -- a failed lookup is a failed check, never a crash
        return False, f"table: {table} lookup raised {type(exc).__name__}: {str(exc)[:200]}"
    if not isinstance(record, dict) or not record:
        return False, f"table: no {table} row {row.get('rowid')!r} in kec.db"
    leaves = list(_leaves(record))
    try:
        number = float(row.get("value"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False, "number: missing or not numeric"
    if not any(_close(value, number) for _, leaf in leaves
               if (value := _as_number(leaf)) is not None):
        # ponytail: any number in the row counts, so a value beside the cited field (public_pct
        # for a promoter holding) also passes; match the field name if a wrong number gets through.
        return False, f"number: {number:g} is not in the {table} row"
    quote = normalise(row.get("quote"))
    if quote:
        if len(quote) < MIN_QUOTE:
            return False, "quote: missing or shorter than 12 characters"
        if not any(quote in normalise(leaf) for _, leaf in leaves if isinstance(leaf, str)):
            return False, f"quote: not in the {table} row"
    limit = _as_date(as_of)
    if limit is None:
        return False, "as_of: missing or not a date"
    when = _as_date(row.get("known_at"))
    if when is None:
        return False, "known_at: missing or not a date"
    if when > limit:
        return False, "known_at: after the as-of date"
    row_known = _as_date(record.get("known_at"))
    if row_known is not None and row_known != when:
        return False, "known_at: not the cited row's own date"
    return True, None


def check_answer_row(row: dict, page_lookup, as_of: object, row_lookup=None) -> tuple[str | None, list[str]]:
    """``(malformed, number reasons)`` for one answer row.

    A malformed row -- a bad status, a bad gap type, an empty answer, a number that is not an object
    -- fails the report.  A number that fails a check is one of the reasons; the row is still stored,
    as ``unverified`` with that reason, and it is not counted as answered.
    """
    status = str(row.get("status") or "")
    if status not in STATUSES:
        return f"status: {status!r} is not one of {STATUSES}", []
    if status == "not_found":
        gap = str(row.get("gap_type") or "")
        if gap not in GAP_TYPES:
            return f"gap_type: {gap!r} is not one of {GAP_TYPES}", []
    elif not normalise(row.get("answer")):
        return "answer: empty", []
    reasons: list[str] = []
    for number in row.get("numbers") or []:
        if not isinstance(number, dict):
            return "number: not an object", []
        fact = {**number, "measure": number.get("measure") or row.get("measure") or ""}
        if normalise(number.get("table")):
            ok, reason = check_row_fact(fact, as_of, row_lookup)
        else:
            lookup = page_lookup(number.get("doc_key"), number.get("page")) if page_lookup else None
            if not lookup:
                reasons.append("source: page not in doc_text")
                continue
            ok, reason = check_fact(fact, lookup[0], lookup[1], as_of)
        if not ok:
            reasons.append(str(reason))
    return None, reasons
