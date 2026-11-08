"""Recompute an answer's numbers before it is recorded (T-072).

31 of the 120 answer misses in the 600-answer run were a head sum or a ten-times unit slip while the data was
right (ETERNAL-082 wrote a market cap of Rs 32.20 lakh crore for 3.22 lakh crore; HDFCBANK-097 wrote gross NPAs
of Rs 3,574 crore for 35,736).  This module recomputes what an answer states, each failure with its own reason
code, and ``answer_record`` refuses to record an answer that fails:

``formula_mismatch``   a number's ``formula`` + ``inputs`` (or, for an older answer, a ``computed: ...`` source)
                       does not recompute beyond the number's printed rounding.
``unit_slip``          an amount in the answer text matches a ``numbers`` entry only at 10x / 100x / 1000x.
``unmatched_amount``   an amount in the answer text matches no ``numbers`` entry (warning: an answer quotes
                       rounded intermediates it never listed, so this alone does not block a record).
``quote_mismatch``     a ``numbers`` value does not occur in the quote it cites (checked only where the quote
                       carries a unit word; a table blob of bare numbers has no readable scale).
``stated_working``     an arithmetic relation stated in the text does not hold: "A / B is C times",
                       "X% of Y is Z", "from A to B, a fall of C", "N% below Y", "A + B = C", "N bps".
``bad_grouping``       comma grouping that is neither Indian (12,34,567) nor Western (1,234,567).

    python -m reality_engine.pilot3.number_check KTEC_answers.jsonl HDFCBANK_answers.jsonl --tsv out.tsv
    python -m reality_engine.pilot3.number_check .tmp\\INFY_answers.jsonl      # one file
    python -m reality_engine.pilot3.number_check answers.json --dev t072_dev.tsv

Old answers carry no ``formula``, so their replay rests on the other checks.  A rule here is general: no qid, no
company and no fixed value is written into it.
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

from reality_engine.gap_loop import checks

SERVER = Path(__file__).resolve().parents[2] / "plugins" / "reality-data" / "server"

CODES = {
    "formula_mismatch": "a stated formula does not recompute beyond the number's printed rounding",
    "unit_slip": "an amount in the answer matches a numbers entry only at 10x / 100x / 1000x",
    "unmatched_amount": "an amount in the answer matches no numbers entry",
    "quote_mismatch": "a numbers value does not occur in the quote it cites",
    "source_scale_mismatch": "a numbers value's own source states the same digits at a different scale",
    "stated_working": "an arithmetic relation stated in the answer text does not hold",
    "bad_grouping": "comma grouping is neither Indian nor Western",
}
# The codes that block a record.  ``unmatched_amount`` is reported and counted as a warning: prose quotes
# rounded intermediates an answer never lists, and blocking on those would fail most honest answers.
FAILING = frozenset(CODES) - {"unmatched_amount"}
SLIPS = (10, 100, 1000)
TOLERANCE = 0.005   # a stated or recomputed value may be rounded; 0.2% is exact arithmetic, 0.5% is prose
APPROX = 0.01       # "about", "roughly", "~": a hand-rounded intermediate
APPROX_WORDS = re.compile(r"\b(?:about|roughly|around|approximately|approx|circa|nearly|over|under)\b|~", re.I)


def server_module(name: str) -> Any:
    """A module that lives beside the reality-data server (``calc``), imported without leaving its path behind."""
    sys.path.insert(0, str(SERVER))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SERVER))


# --- amounts in a text ---------------------------------------------------------------------------------
# A number, the currency or scale word that gives it a size, and the count noun that makes it a count.
# "Rs 2,711.9m", "Rs 3,41,79,459 crore", "14.53 crore shares", "1.11%", "101.6 times" are all one token each.
_AMOUNT = re.compile(
    r"(?<![\w.,])(?:(?P<cur>INR|Rs\.?|₹)\s*)?"
    r"(?P<num>-?\d+(?:,\d+)*(?:\.\d+)?)(?!\.\d)"
    r"(?P<glued>bn|mn|cr|k|m)?(?![\w])"
    r"(?:\s*(?P<scale>lakh[\s-]*crores?|lakh[\s-]*cr|crores?|crs?|cr|lakhs?|lacs?|millions?|mn|billions?|bn"
    r"|thousand))?"
    r"(?:\s*(?P<pct>%|percent(?:age)?|per\s*cent|bps|basis\s+points|pp|percentage\s+points))?"
    r"(?:\s*(?P<count>shares?|holders?|persons?|customers?|units?|sessions?|trading\s+days?|days?|months?|years?"
    r"|employees?|branches?|orders?|tonnes?))?"
    r"(?:\s*(?P<ratio>times|x)\b)?",
    re.I)
_SCALE_WORD = {"thousand": 10 ** 3, "lakh": 10 ** 5, "lac": 10 ** 5, "million": 10 ** 6, "mn": 10 ** 6,
               "k": 10 ** 3, "m": 10 ** 6, "crore": 10 ** 7, "cr": 10 ** 7, "billion": 10 ** 9, "bn": 10 ** 9}
_COUNT_NOUN = re.compile(
    r"\b(shares?|holders?|persons?|customers?|units?|sessions?|days?|months?|years?|employees?|branches?"
    r"|orders?|tonnes?|count|nos|number|times)\b", re.I)
_SCALE_SCAN = ((re.compile(r"lakh[\s_-]*(?:crores?|cr)\b", re.I), 10 ** 12),
               (re.compile(r"\bcrores?\b|\bcrs?\b|\bcr\b", re.I), 10 ** 7),
               (re.compile(r"\blakhs?\b|\blacs?\b", re.I), 10 ** 5),
               (re.compile(r"\bmillions?\b|\bmn\b", re.I), 10 ** 6),
               (re.compile(r"\bbillions?\b|\bbn\b", re.I), 10 ** 9),
               (re.compile(r"\bthousands?\b", re.I), 10 ** 3))


def _scale(scale: str | None, glued: str | None) -> int:
    word = (scale or glued or "").lower().strip()
    if not word:
        return 1
    if word.startswith("lakh"):
        return 10 ** 12 if "cr" in word else 10 ** 5
    for ending in ("crores", "crore", "crs", "cr", "lakhs", "lakh", "lacs", "lac", "millions", "million",
                   "mn", "billions", "billion", "bn", "thousand"):
        if word == ending:
            return _SCALE_WORD[ending.rstrip("s") if ending not in _SCALE_WORD else ending]
    return _SCALE_WORD.get(word.rstrip("s"), 1)


def _sig_digits(raw: Any) -> int:
    """Significant digits printed: "32.20" 4, "3.18" 3, "41" 2, "7.3" 2, "1,012.86" 6."""
    text = str(raw).lstrip("-").replace(",", "")
    whole, _, frac = text.partition(".")
    digits = (whole.lstrip("0") + frac) if frac else whole.lstrip("0").rstrip("0")
    return len(digits.lstrip("0")) or 1


_MONTH = re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)


def _is_date(text: str, start: int, end: int, value: Fraction, raw: str) -> bool:
    """A year or a day-of-month: "2025 to 2026", "4 August to 3 November" are not operands of anything."""
    if raw.lstrip("-").isdigit() and 1900 <= value <= 2100:
        return True
    if raw.lstrip("-").isdigit() and value <= 31:
        after, before = text[end:end + 14], text[max(0, start - 14):start]
        if _MONTH.match(after.lstrip()) or re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*$",
                                                     before, re.I):
            return True
    return False


def _tied(entry: dict, found: list[dict], amount: dict) -> bool:
    """Another amount in the same answer prints the entry exactly, near the slipped one: a restatement."""
    for other in found:
        if other is amount or other["family"] not in (entry["family"], "plain"):
            continue
        if abs(other["start"] - amount["start"]) > 200:
            continue
        if close(entry["value"], other["value"]) or close(entry["raw"], other["value"]):
            return True
    return False


def _pct_rounding(first: dict, second: dict, expected: Fraction) -> Fraction:
    """How far the two endpoints' own printed rounding can move their percentage change."""
    low_a = first["value"] - _precision(first["raw"], first["value"])
    high_a = first["value"] + _precision(first["raw"], first["value"])
    low_b = second["value"] - _precision(second["raw"], second["value"])
    high_b = second["value"] + _precision(second["raw"], second["value"])
    worst = Fraction(0)
    for a in (low_a, high_a):
        if a == 0:
            continue
        for b in (low_b, high_b):
            worst = max(worst, abs((b - a) / a * 100 - expected))
    return worst


_DERIVED = re.compile(r"\bcomput(?:ed|ation)?\b|\bderived\b|\bcalculated\b|\bcalc\b|\bformula\b", re.I)
_RATIO_UNIT = re.compile(r"\bshare of\b|\bratio\b|\b% of\b|\bpercent of\b|\bper\b.*\bof\b|\bmultiple\b|\bx\b",
                         re.I)


def amounts(text: str) -> list[dict[str, Any]]:
    """Every number in ``text`` with its family (money / count / pct / ratio / plain / date), base value and
    significant digits.

    A year or a day-of-month is its own family: "4 August to 3 November" and "2025 to 2026" are dates, never
    operands of a sum or a range.
    """
    out: list[dict[str, Any]] = []
    for match in _AMOUNT.finditer(text or ""):
        try:
            value = Fraction(match.group("num").replace(",", ""))
        except (ValueError, ZeroDivisionError):
            continue
        factor = _scale(match.group("scale"), match.group("glued"))
        if match.group("pct"):
            family, base = "pct", value
        elif match.group("ratio"):
            family, base = "ratio", value
        elif match.group("count"):
            family, base = "count", value * factor
        elif factor > 1 or match.group("cur"):
            family, base = "money", value * factor
        else:
            family, base = "plain", value
        raw = match.group("num")
        if family == "plain" and _is_date(text or "", match.start(), match.end(), value, raw):
            family = "date"
        out.append({"value": base, "family": family, "start": match.start(), "end": match.end(), "raw": raw,
                    "sig": _sig_digits(raw), "factor": factor, "text": match.group(0).strip()})
    return out

def _number(value: Any) -> Fraction | None:
    """A stored value as a Fraction; None for a range ("290-300"), prose or a missing value."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return Fraction(str(value))
    try:
        return Fraction(checks.normalise(value).replace(",", "").strip())
    except (ValueError, ZeroDivisionError):
        return None


def unit_family(unit: Any) -> tuple[str | None, int]:
    """The family a stored ``numbers`` unit names, and its rupee scale: ("money", 10**7) for "INR crore".

    A count is read as a count whatever scale word follows it ("shares held by that bucket (14.53 crore)" is
    1,452,606,975 shares, not 1.45e16): a stored count is stored in shares.  A per-unit money rate
    ("INR per share", "Rs per tonne") is money, not a count of shares.
    """
    text = checks.normalise(unit).lower()
    if not text:
        return None, 1
    if re.match(r"^(?:%|pct\b|percent)", text):
        return "pct", 1
    if re.match(r"^(?:x\b|times\b|ratio\b|multiple\b)", text):
        return "ratio", 1
    if re.search(r"\b(?:inr|rs|rupees?|usd)\b\s*(?:per|/)\b", text):
        return "money", 1
    noun, scale = _COUNT_NOUN.search(text), _first_scale(text)
    if noun and (scale is None or noun.start() < scale[0]):
        return "count", 1
    if scale is not None:
        return "money", scale[1]
    if re.search(r"\b(?:inr|rs|rupees?|₹)\b", text):
        return "money", 1
    if noun:
        return "count", 1
    return None, 1

def _first_scale(text: str) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    for pattern, factor in _SCALE_SCAN:
        found = pattern.search(text)
        if found and (best is None or found.start() < best[0]):
            best = (found.start(), factor)
    return best


def _half_unit(raw: Any) -> Fraction:
    """Half a unit of the last printed digit: the rounding a stated value is allowed."""
    text = str(raw).strip()
    if "." in text and "e" not in text.lower():
        return Fraction(1, 2 * 10 ** len(text.split(".")[1]))
    return Fraction(1, 2)


def close(stated: Fraction, expected: Fraction, raw: Any = None, approx: bool = False) -> bool:
    """The stated value within its own printed rounding (plus a relative slack for prose)."""
    energy = max(_half_unit(raw if raw is not None else stated),
                 Fraction(int((APPROX if approx else TOLERANCE) * 1000), 1000) * abs(expected))
    return abs(stated - expected) <= energy


def _precision(raw: Any, value: Fraction) -> Fraction:
    """Half a unit of the last digit printed, in the value's own scale: "3.18 crore" is 50,000 shares."""
    digits = _number(raw)
    if digits is None or digits == 0:
        return abs(value) / 1000 if value else Fraction(1, 2)
    return _half_unit(raw) * abs(value / digits)


def slip_factor(stated: Fraction, expected: Fraction, raw: Any = None) -> int | None:
    """10, 100 or 1000 when the stated value is expected shifted by that factor in either direction.

    The shift has to be the same DIGITS moved: "3.18 crore" for 31.8 crore is a slip; 253.64 crore against a
    real 2,552.20 crore is two different amounts, so it is not (it is only 0.6% away from a 10x ratio).  A
    value printed to one significant figure ("0.1", "1 bn") cannot be judged at all: its rounding is 10%.
    """
    precision = _precision(raw, stated) if raw is not None else abs(stated) / 10 ** 9
    if stated == 0 or precision / abs(stated) > Fraction(5, 100):
        return None
    for factor in SLIPS:
        if abs(stated / factor - expected) <= precision / factor:
            return factor
        if abs(stated * factor - expected) <= precision * factor:
            return -factor
    return None

def grouping_ok(raw: str) -> bool | None:
    """True for Indian or Western comma grouping, False for neither, None when there is no comma to judge."""
    text = raw.lstrip("-")
    if "," not in text:
        return None
    head = text.split(".")[0]
    return bool(re.fullmatch(r"\d{1,3}(?:,\d{3})+", head) or re.fullmatch(r"\d{1,2}(?:,\d{2})*,\d{3}", head))


def _finding(code: str, detail: str, severity: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity or ("fail" if code in FAILING else "warn"), "detail": detail,
            **extra}


# --- one numbers entry ---------------------------------------------------------------------------------
def entries(numbers: Iterable[Any]) -> list[dict[str, Any]]:
    """Every ``numbers`` row that carries a numeric value and a readable unit, as (family, base value)."""
    out = []
    for number in numbers or ():
        if not isinstance(number, dict):
            continue
        raw = _number(number.get("value"))
        if raw is None:
            continue
        family, scale = unit_family(number.get("unit"))
        if family is None:
            continue
        out.append({"raw": raw, "family": family, "scale": scale,
                    "value": raw * scale if family in ("money", "count") else raw,
                    "unit": str(number.get("unit") or ""), "period": number.get("period"),
                    "quote": number.get("quote"), "source": number.get("source"),
                    "formula": number.get("formula"), "inputs": number.get("inputs") or {}})
    return out


def computed_expression(source: Any) -> str | None:
    """The expression an older answer left in ``source``: "computed: 8,421.2/22,882" -> "8,421.2/22,882".

    Read as a WHOLE or not at all: the arithmetic characters plus ``^`` (an exponent, as in
    "(647.1/30)^(1/5)-1"), with a source whose arithmetic continues in words ("20.33% x RWA") or whose
    parentheses do not close left alone. A fragment would recompute to something the answer never claimed.
    """
    text = checks.normalise(source)
    match = re.search(r"\bcomput(?:ed|ation)?\b\s*:?\s*", text, re.I)
    if not match:
        return None
    rest = text[match.end():]
    keep = re.match(r"[0-9.,\s+\-*/x×÷()%^]+", rest)
    if not keep:
        return None
    tail = rest[keep.end():].lstrip()
    opens_note = keep.group(0).rstrip().endswith("(")
    if tail[:1].isalnum() and not opens_note:
        return None     # the formula goes on in words, not in arithmetic ("20.33% x RWA")
    # A comma is digit grouping here, never a tuple separator; "x 87%" is 0.87, not 87; "^" is an exponent.
    expression = (keep.group(0).replace(",", "").replace("x", "*").replace("×", "*").replace("÷", "/")
                  .replace("^", "**"))
    expression = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", expression)
    expression = re.sub(r"[+\-*/(\s]+$", "", expression).strip()
    if expression.count("(") != expression.count(")"):
        return None     # a truncated parenthesis group: the readable part is not the whole formula
    if not re.search(r"\d\s*[-+*/]\s*\d", expression):
        return None
    return expression

def _compare(computed: dict, entry: dict) -> tuple[bool, str]:
    """The computed value against the stored one, at every scale a hand-written source may be in.

    A ``computed:`` source is written sometimes in the entry's own unit ("2690.61 + 1253.52" for crore),
    sometimes in base units ("1,231,954,447 x 970" for a crore answer), and a percentage is sometimes a
    fraction of 1 and sometimes the printed percent: the entry is right if ANY of those readings lands on it.
    """
    if not computed.get("ok"):
        return False, str(computed.get("error") or "the formula did not evaluate")
    value = Fraction(str(computed["value"]))
    unit = computed.get("unit") or ""
    candidates = [value]
    if entry["family"] == "pct":
        candidates = [value, value * 100, value / 100, abs(value), abs(value) * 100]
    elif entry["family"] == "ratio":
        candidates = [value, value * 100] if unit == "percent" else [value, value / 100]
    for stated in (entry["value"], entry["raw"]):
        if any(close(stated, candidate, entry["raw"]) for candidate in candidates):
            return True, ""
    return False, f"recomputes to {float(value):g}, the answer states {float(entry['raw']):g}"

def check_formula(entry: dict, calc: Any) -> dict[str, Any] | None:
    """A number whose ``formula`` + ``inputs`` (or an old ``computed:`` source) is recomputed exactly.

    A ``formula`` the worker wrote must work: an error there fails.  A source scraped out of prose that does not
    parse ("455 - 496 (-(8.2/100))") is only a warning -- the reading may be the checker's, not the answer's.
    """
    if entry["formula"]:
        computed = calc.evaluate(str(entry["formula"]), entry["inputs"])
        ok, why = _compare(computed, entry)
        if not ok:
            return _finding("formula_mismatch", f"formula {entry['formula']!r}: {why}", field="formula")
        return None
    expression = computed_expression(entry["source"])
    if not expression:
        return None
    # A "computed:" source may be written in the entry's own unit ("2,690.61 + 1,253.52" for INR crore) or
    # in base units ("1,231,954,447 x 970" for a crore answer): both readings are accepted.
    computed = calc.evaluate(expression)
    if not computed.get("ok"):
        return _finding("formula_mismatch", f"source {expression!r} does not evaluate: "
                                            f"{computed.get('error')}", severity="warn", field="source")
    ok, why = _compare(computed, entry)
    if ok:
        return None
    return _finding("formula_mismatch", f"source {expression!r}: {why}", field="source")

def check_quote(entry: dict) -> dict[str, Any] | None:
    """The stored value against the quote it cites.

    Passes when the quote prints the value's own digits at any scale ("2.9 million units" for a 2.9 row), or when
    the entry is a computed/derived figure or a ratio of quoted ones -- the quote is then an input, not the
    number.  A value simply absent from a cut quote is a warning; only the same quantity printed at a different
    scale fails.
    """
    quote = checks.normalise(entry["quote"])
    if not quote:
        return None
    if _DERIVED.search(str(entry["source"] or "")) or _RATIO_UNIT.search(str(entry["unit"] or "")):
        return None
    found = amounts(quote)
    for amount in found:
        if amount["family"] in ("date", "pct"):
            continue
        if _same_digits(entry["raw"], amount["raw"]):
            # "14445.4 crore" and "144,454 million" carry the same digits and are the same quantity: only a
            # different VALUE behind the same digits is a scale slip.
            if (amount["factor"] > 1 and entry["scale"] > 1 and amount["factor"] != entry["scale"]
                    and not close(entry["value"], amount["value"], entry["raw"])):
                return _finding("quote_mismatch", f"{float(entry['raw']):g} {entry['unit']!r} is quoted at a "
                                                  f"different scale ({amount['text']!r}): {quote[:80]!r}",
                                field="quote")
            return None     # printed as it stands, whatever scale the other side's unit word implies
        if entry["family"] in (amount["family"], "plain") and close(entry["value"], amount["value"], entry["raw"]):
            return None
    same = [a for a in found if a["family"] == entry["family"] and a["family"] != "date"]
    if len(same) > 1 and close(entry["value"], sum((a["value"] for a in same), Fraction(0)), entry["raw"]):
        return None     # the quote prints the components, the entry their total (a demand plus its penalty)
    for amount in found:
        if amount["family"] in ("date", "pct", "plain"):
            continue
        if _same_digits(entry["raw"], amount["raw"]) and not close(entry["value"], amount["value"], entry["raw"]):
            return _finding("quote_mismatch", f"{float(entry['raw']):g} {entry['unit']!r} is quoted at a "
                                              f"different scale ({amount['text']!r}): {quote[:80]!r}",
                            field="quote")
    return _finding("quote_mismatch", f"{float(entry['raw']):g} {entry['unit']!r} is not in its quote: "
                                      f"{quote[:80]!r}", severity="warn", field="quote")


def _same_digits(left: Any, right: Any) -> bool:
    """The same printed digits, whatever scale each side carries: 2,711.9 and 2711900000 are one number."""
    def digits(value: Any) -> str:
        if isinstance(value, Fraction) and value.denominator != 1:
            value = float(value)
        elif isinstance(value, Fraction):
            value = int(value)
        text = str(value).lstrip("-").replace(",", "")
        return text.split(".")[0] + (text.split(".")[1].rstrip("0") if "." in text else "")
    first, second = digits(left).lstrip("0"), digits(right).lstrip("0")
    return bool(first) and bool(second) and first == second


def check_source_scale(entry: dict) -> dict[str, Any] | None:
    """T-129: a money entry whose own ``source`` prints the same digits at a different scale fails.

    MARUTI-127 stores 4,136 crore with the source "fin_quarter_current other_income, consolidated, Rs 4,136
    million": the digits match the stored value while the scale word does not (4,136 million is 413.6 crore), so
    the figure is ten times the sourced amount.  The same amount written at its real scale passes, and the cited
    quote is ``check_quote``'s job."""
    if entry["family"] != "money" or entry["scale"] <= 1:
        return None
    text = checks.normalise(entry.get("source") or "")
    if not text:
        return None
    for amount in amounts(text):
        if amount["family"] != "money" or amount["factor"] <= 1:
            continue
        if not _same_digits(entry["raw"], amount["raw"]):
            continue
        if close(entry["value"], amount["value"], entry["raw"]):
            return None             # the same amount, written at its real scale ("4,136 million" for 413.6 crore)
        return _finding("source_scale_mismatch",
                        f"{float(entry['raw']):g} {entry['unit']!r} is sourced at a different scale "
                        f"({amount['text']!r}): {text[:80]!r}", field="source")
    return None

# --- the answer text -----------------------------------------------------------------------------------
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
_RESULT_X = re.compile(r"(?<![\w.])(?P<res>-?\d+(?:\.\d+)?)\s*(?:x\b|times\b)", re.I)
_CHANGE_WORD = re.compile(r"\b(?:fall|fell|drop(?:ped)?|down|rose|risen|rise|up|increase[ds]?|gain(?:ed)?|change[ds]?"
                          r"|decline[ds]?|lower|higher)\b", re.I)
_RELATION = re.compile(r"=|→|->|\b(?:is|was|are|were|gives?|give|gives us|equals?|comes?\s+to|works?\s+out\s+to"
                       r"|amounts?\s+to|makes?|in\s+total)\b", re.I)
_SUM_MARK = re.compile(r"\s*\+\s*|\bplus\b|\bcombined with\b|\badding\b", re.I)
_SUM_RELATION = re.compile(r"=|\b(?:equals?|totals?|in total|combined|adds up to)\b", re.I)
_RATIO_CUE = re.compile(r"\bcovers?\b|\bdivided\b|\bover\b|\bagainst\b|\bvs\.?\b|\bper\b|/|÷", re.I)
_PCT_OF = re.compile(r"(?<![\w.])(?P<pct>-?\d+(?:\.\d+)?)\s*%\s+of\s+", re.I)
_PCT_BELOW = re.compile(r"(?<![\w.])(?P<pct>\d+(?:\.\d+)?)\s*%\s*(?P<dir>below|above|higher than|lower than"
                        r"|more than|less than|up|down)\b", re.I)
_FROM = re.compile(r"\bfrom\b", re.I)
_TO = re.compile(r"\b(?:to|until|down to|up to|through)\b", re.I)
_PCT = re.compile(r"(?<![\w.])(?P<pct>-?\d+(?:\.\d+)?)\s*%")
_BPS = re.compile(r"(?<![\w.])(?P<low>\d+(?:\.\d+)?)(?:\s*-\s*(?P<high>\d+(?:\.\d+)?))?\s*(?:bps|basis\s+points)",
                  re.I)


def sentences(text: str) -> list[str]:
    return [part for part in _SENTENCE.split(checks.normalise(text)) if part.strip()]


def _is_approx(text: str, position: int) -> bool:
    return bool(APPROX_WORDS.search(text[max(0, position - 18):position]))


def _first_after(found: list[dict], position: int, gap: int = 90) -> dict | None:
    return next((a for a in found if a["start"] >= position and a["start"] - position <= gap), None)


def _before(found: list[dict], position: int, gap: int = 90) -> dict | None:
    near = [a for a in found if a["end"] <= position and position - a["end"] <= gap]
    return near[-1] if near else None


def _diff_ratio(first: Fraction, second: Fraction) -> Fraction | None:
    if first == 0:
        return None
    return (second - first) / first * 100


def _same_family(first: dict, second: dict) -> bool:
    """Money, count or pct match their own family; a bare number ("5,58,41,68,636 to ... shares") matches any."""
    return first["family"] == second["family"] or "plain" in (first["family"], second["family"])


def check_ratio(sentence: str, found: list[dict], text: str) -> list[dict[str, Any]]:
    """``A covers B 97.2 times``: two money amounts and a stated multiple in one sentence (INFY-019 101.6)."""
    money = [a for a in found if a["family"] in ("money", "count")]
    if len(money) != 2:
        return []
    first, second = money
    gap = sentence[first["end"]:second["start"]]
    if not _RATIO_CUE.search(gap):
        return []       # two amounts side by side are not a division
    for match in _RESULT_X.finditer(sentence):
        if match.start() < second["end"] or match.start() - second["end"] > 20:
            continue    # the multiple is stated right after the divisor it was computed from
        if sentence[:match.start()].count("(") > sentence[:match.start()].count(")"):
            continue    # a value inside a parenthesis belongs to a range or a caveat
        stated = Fraction(match.group("res"))
        if first["value"] == 0 or second["value"] == 0:
            return []
        for expected in (first["value"] / second["value"], second["value"] / first["value"],
                         first["value"] / second["value"] * 100):
            if close(stated, expected, match.group("res"), _is_approx(sentence, match.start())):
                return []
        factor = slip_factor(stated, first["value"] / second["value"], match.group("res"))
        code = "unit_slip" if factor else "stated_working"
        return [_finding(code, f"{float(first['value']):g} / {float(second['value']):g} is "
                               f"{float(first['value'] / second['value']):.4g}, the answer states "
                               f"{match.group('res')}x", where=sentence[:120])]
    return []

def check_percent_of(sentence: str, found: list[dict], previous_pct: str | None) -> list[dict[str, Any]]:
    """``X% of Y is Z`` -- including "Applying those ratios to Rs Y gives Z", where X is the previous sentence\'s.

    Bound tightly: the relation word must follow the base amount at once and the result must be the same
    family as the base (money in, money out).  A looser binding reads the next unrelated sentence as a result.
    """
    claims: list[tuple[str, int]] = [(m.group("pct"), m.end()) for m in _PCT_OF.finditer(sentence)]
    if not claims:
        if previous_pct is None or not re.search(r"\bratios?\b|\bproportions?\b", sentence, re.I):
            return []
        of = re.search(r"\bof\s+", sentence)
        if not of:
            return []
        claims = [(previous_pct, of.end())]
    for pct_text, position in claims:
        base = _first_after(found, position, 30)
        if base is None or base["family"] == "pct":
            continue
        relation = _RELATION.search(sentence, base["end"])
        if not relation or relation.start() - base["end"] > 15:
            continue
        result = _first_after(found, relation.end(), 30)
        if result is None or result["family"] == "pct" or not _same_family(result, base):
            continue
        expected = base["value"] * Fraction(pct_text) / 100
        if close(result["value"], expected, result["raw"], _is_approx(sentence, result["start"])):
            continue
        factor = slip_factor(result["value"], expected, result["raw"])
        code = "unit_slip" if factor else "stated_working"
        return [_finding(code, f"{pct_text}% of {float(base['value']):g} is {float(expected):g}, the answer "
                               f"states {float(result['value']):g}", where=sentence[:120])]
    return []

def _result_pct(sentence: str, first: dict, second: dict) -> tuple[str, int] | None:
    """The percentage a "from A to B" range states, when it is plainly that range's: just before or just after."""
    head = list(_PCT.finditer(sentence[:first["start"]]))
    if head and first["start"] - head[-1].end() <= 30:
        return head[-1].group("pct"), head[-1].start()
    tail = sentence[second["end"]:]
    outside = [m for m in _PCT.finditer(tail) if tail[:m.start()].count("(") <= tail[:m.start()].count(")")]
    if outside and outside[0].start() <= 20:
        return outside[0].group("pct"), second["end"] + outside[0].start()
    return None


def check_from_to(sentence: str, found: list[dict]) -> list[dict[str, Any]]:
    """"from A to B, a fall of C" and "from A to B, X%": both sides readable, so recompute (HDFCBANK-030/063)."""
    for start in _FROM.finditer(sentence):
        first = _first_after(found, start.end(), 60)
        if first is None or first["family"] not in ("money", "count", "plain"):
            continue
        if first["family"] == "plain" and abs(first["value"]) < 1000:
            continue    # a day number or a small count, not a quantity a change is read from
        between = _TO.search(sentence, first["end"])
        if not between or between.start() - first["end"] > 100:
            continue
        second = _first_after(found, between.end(), 40)
        if second is None or not _same_family(first, second) or second["value"] == first["value"]:
            continue
        if second["family"] in ("date",):
            continue
        tail = sentence[second["end"]:]
        pct = _result_pct(sentence, first, second)
        if pct:
            stated = Fraction(pct[0])
            expected = _diff_ratio(first["value"], second["value"])
            if expected is None:
                continue
            # "a 66% decline" and "-66%" are the same claim: the sign lives in the wording.  The tolerance
            # carries both endpoints' printed rounding (50.4 to 45.7 is -9.3%, and -9.4% from unrounded EPS
            # is not a slip).
            allowed = (_pct_rounding(first, second, expected) + _half_unit(pct[0])
                       + Fraction(TOLERANCE) * abs(expected))
            if abs(abs(stated) - abs(expected)) <= allowed:
                continue
            factor = slip_factor(abs(stated), abs(expected), pct[0])
            return [_finding("unit_slip" if factor else "stated_working",
                             f"{float(first['value']):g} to {float(second['value']):g} is {float(expected):.4g}%, "
                             f"the answer states {pct[0]}%", where=sentence[:120])]
        change = _CHANGE_WORD.search(tail)
        if change:
            gap = tail[change.end():change.end() + 20]
            if "," in gap:
                continue
            result = _first_after(found, second["end"] + change.end(), 20)
            if result is None or not _same_family(result, first) or result is first or result is second:
                continue
            expected = abs(second["value"] - first["value"])
            if close(result["value"], expected, result["raw"], _is_approx(sentence, result["start"])):
                continue
            factor = slip_factor(result["value"], expected, result["raw"])
            return [_finding("unit_slip" if factor else "stated_working",
                             f"{float(first['value']):g} to {float(second['value']):g} is a change of "
                             f"{float(expected):g}, the answer states {float(result['value']):g}",
                             where=sentence[:120])]
    return []

def check_percent_change(sentence: str, found: list[dict]) -> list[dict[str, Any]]:
    """"N% below the Rs Y": the result is the amount stated just before the phrase (BAJFINANCE-123 31.91)."""
    for match in _PCT_BELOW.finditer(sentence):
        base = _first_after(found, match.end(), 40)
        if base is None or base["family"] not in ("money", "count"):
            continue
        result = _before(found, match.start(), 70)
        if result is None or result["family"] != base["family"] or result is base:
            continue
        if sentence[result["end"]:match.start()].strip() not in ("", "("):
            continue    # the phrase does not qualify the number before it ("... EPS about 31.91 (10% below ...")
        pct = Fraction(match.group("pct"))
        below = match.group("dir").lower() in ("below", "lower than", "less than", "down")
        expected = base["value"] * (1 - pct / 100 if below else 1 + pct / 100)
        if close(result["value"], expected, result["raw"], _is_approx(sentence, result["start"])):
            continue
        factor = slip_factor(result["value"], expected, result["raw"])
        return [_finding("unit_slip" if factor else "stated_working",
                         f"{match.group('pct')}% {'below' if below else 'above'} {float(base['value']):g} is "
                         f"{float(expected):g}, the answer states {float(result['value']):g}",
                         where=sentence[:120])]
    return []


def check_sum(sentence: str, found: list[dict]) -> list[dict[str, Any]]:
    """"A + B + C = D": the stated total against the chain joined by sum markers.

    Both sides are read the same way (base units or the printed digits), so a crore word on the total alone
    does not make the sum wrong.  A chain with a subtraction word ("178,650 less 141,688 plus 4,902") is read
    WHOLE or skipped, never two operands out of it.
    """
    for relation in _SUM_RELATION.finditer(sentence):
        total = _first_after(found, relation.end(), 40)
        if total is None or total["family"] in ("pct", "date"):
            continue
        previous = _before(found, relation.start(), 40)
        if previous is None or previous is total or not _same_family(previous, total):
            continue
        if previous["family"] == "date":
            continue
        chain = [previous]
        cursor = previous["start"]
        while True:
            earlier = _before(found, cursor, 40)
            if earlier is None or earlier is total or earlier["family"] == "date" or not _same_family(earlier,
                                                                                                     total):
                break
            if not _SUM_MARK.search(sentence, earlier["end"], cursor):
                break
            chain.insert(0, earlier)
            cursor = earlier["start"]
        if len(chain) < 2:
            continue
        span = sentence[chain[0]["start"]:relation.start()]
        if re.search(r"[/÷*×]", sentence[:relation.start()]) or \
                re.search(r"\b(?:less|minus|net of|excluding|offset|barring)\b", sentence[:relation.start()]):
            continue    # a compound or mixed expression, not a chain of sums
        sums = sum((a["value"] for a in chain), Fraction(0))
        raws = sum((Fraction(a["raw"].replace(",", "")) for a in chain), Fraction(0))
        if close(total["value"], sums, total["raw"]) or close(Fraction(total["raw"].replace(",", "")), raws,
                                                              total["raw"]):
            continue
        factor = slip_factor(total["value"], sums, total["raw"])
        parts = " + ".join(format(float(a["value"]), "g") for a in chain)
        return [_finding("unit_slip" if factor else "stated_working",
                         f"{parts} is {float(sums):g}, the answer states {float(total['value']):g}",
                         where=sentence[:120])]
    return []

def check_bps(sentence: str, found: list[dict], text: str) -> list[dict[str, Any]]:
    """"from 5.0% to 9-10% is 400-500 bps": a bps range recomputed from the two percentages of one sentence."""
    claim = _BPS.search(sentence)
    if not claim or not re.search(r"\bfrom\b", sentence, re.I) or not re.search(r"\bto\b", sentence, re.I):
        return []
    pcts = [Fraction(m.group("pct")) for m in _PCT.finditer(sentence)]
    if len(pcts) != 2:
        return []
    low = Fraction(claim.group("low"))
    high = Fraction(claim.group("high")) if claim.group("high") else low
    first, second = pcts
    for expected in ((max(first, second) - min(first, second)) * 100,
                     (max(first, second) - min(first, second)) / min(first, second) * 100):
        if low - 5 <= expected <= high + 5:
            return []
    return [_finding("stated_working", severity="warn", detail=f"{float(first):g}% to {float(second):g}% is "
                                       f"{float((max(first, second) - min(first, second)) * 100):.4g} bps, the answer "
                                       f"states {claim.group('low')}"
                                       f"{'-' + claim.group('high') if claim.group('high') else ''} bps",
                     where=sentence[:120])]

def check_text(text: str, numbered: list[dict]) -> list[dict[str, Any]]:
    """Every stated working in the text, plus every amount against the ``numbers`` list."""
    findings: list[dict[str, Any]] = []
    found = amounts(text)
    previous_pct: str | None = None
    for sentence in sentences(text):
        inner = amounts(sentence)
        for check in (check_ratio(sentence, inner, text), check_from_to(sentence, inner),
                      check_percent_change(sentence, inner), check_sum(sentence, inner),
                      check_bps(sentence, inner, text),
                      check_percent_of(sentence, inner, previous_pct)):
            findings.extend(check)
        stated_pct = _PCT.search(sentence)
        previous_pct = stated_pct.group("pct") if stated_pct else previous_pct
    # every money and count amount in the text against the numbers list: a match only at 10x/100x/1000x is a slip
    pools: dict[str, list[dict]] = defaultdict(list)
    for entry in numbered:
        pools[entry["family"]].append(entry)
    reported: set[tuple] = set()
    for amount in found:
        if amount["family"] not in ("money", "count") or amount["value"] == 0:
            continue
        if amount["family"] == "money" and abs(amount["value"]) < 10 ** 6:
            continue    # a per-unit figure (Rs 1.70 a share), not a money total
        pool = pools.get(amount["family"]) or []
        if not pool or any(close(amount["value"], entry["value"]) for entry in pool):
            continue
        # A slip is the same digits moved.  Two printed significant figures ("Rs 41 crore" beside 408, "Rs 7.3 bn"
        # beside 72.5) are chance unless the answer also prints that entry exactly nearby -- the restatement case.
        slip = None
        for entry in pool:
            if not slip_factor(amount["value"], entry["value"], amount["raw"]):
                continue
            if amount["sig"] >= 3 or _tied(entry, found, amount):
                slip = entry
                break
        key = (amount["family"], str(amount["value"]))
        if key in reported:
            continue
        reported.add(key)
        if slip is not None:
            findings.append(_finding("unit_slip", f"text amount {amount['text']!r} is "
                                                  f"{float(amount['value']):g}; the numbers list has "
                                                  f"{float(slip['value']):g} ({slip['unit']!r})",
                                     where=amount["text"]))
        else:
            findings.append(_finding("unmatched_amount", f"text amount {amount['text']!r} matches no numbers "
                                                         f"entry", where=amount["text"]))
    for amount in found:
        if grouping_ok(amount["raw"]) is False:
            findings.append(_finding("bad_grouping", f"{amount['raw']!r} is neither Indian nor Western grouping",
                                     where=amount["text"]))
    return findings


# --- one answer ----------------------------------------------------------------------------------------
def check_answer(row: dict) -> dict[str, Any]:
    """Every finding for one answer row, in a stable order, with ``ok`` false when a check fails."""
    calc = server_module("calc")
    numbered = entries(row.get("numbers") or [])
    findings: list[dict[str, Any]] = []
    for entry in numbered:
        for check in (check_quote(entry), check_source_scale(entry), check_formula(entry, calc)):
            if check:
                findings.append(check)
    findings.extend(check_text(str(row.get("answer") or ""), numbered))
    order = list(CODES)
    findings.sort(key=lambda f: (order.index(f["code"]), f["detail"]))
    deduped: list[dict[str, Any]] = []
    for finding in findings:
        if finding not in deduped:
            deduped.append(finding)
    return {"qid": row.get("qid"), "status": row.get("status"), "findings": deduped,
            "ok": not any(f["severity"] == "fail" for f in deduped)}


# --- files ---------------------------------------------------------------------------------------------
def load_answers(path: Path) -> list[dict]:
    """The ``event=answer`` rows of a jsonl file, or one answer object (or a list of them) in a json file."""
    rows: list[dict] = []
    if path.suffix.lower() == ".jsonl":
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("event", "answer") == "answer" and row.get("qid"):
                rows.append(row)
        return rows
    payload = json.loads(path.read_text(encoding="utf-8"))
    for row in payload if isinstance(payload, list) else [payload]:
        if isinstance(row, dict) and row.get("qid"):
            rows.append(row)
    return rows


def check_files(paths: Iterable[Path]) -> dict[str, dict]:
    """``{file: {"rows": [...], "findings": [...]}}`` for every answer file given."""
    out: dict[str, dict] = {}
    for path in paths:
        rows = load_answers(path)
        checked = [check_answer(row) for row in rows]
        findings = [{"file": path.name, "qid": answer["qid"], **finding}
                    for answer in checked for finding in answer["findings"]]
        out[path.name] = {"path": path, "answers": checked, "findings": findings}
    return out


def write_tsv(path: Path, results: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("file\tqid\tcode\tseverity\tdetail\twhere\n")
        for name, result in results.items():
            for finding in result["findings"]:
                where = str(finding.get("where") or "").replace("\t", " ").replace("\n", " ")
                handle.write(f"{name}\t{finding.get('qid')}\t{finding['code']}\t{finding['severity']}\t"
                             f"{finding['detail'].replace(chr(9), ' ')}\t{where}\n")


def read_dev(path: Path) -> dict[str, str]:
    """``{qid: kind}`` from a dev-set TSV with a qid, kind and reason column."""
    kinds: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        cells = line.split("\t")
        if len(cells) >= 2:
            kinds[cells[0].strip()] = cells[1].strip()
    return kinds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m reality_engine.pilot3.number_check",
                                     description="Recompute an answer's numbers and flag what fails.")
    parser.add_argument("paths", nargs="+", help="answers .jsonl files, answer .json files, or a directory")
    parser.add_argument("--tsv", help="write one row per finding here")
    parser.add_argument("--dev", help="a dev-set TSV (qid, kind, ...) to report caught rows and false alarms")
    parser.add_argument("--quiet", action="store_true", help="summary only, no per-finding lines")
    args = parser.parse_args(argv)
    paths: list[Path] = []
    for raw in args.paths:
        path = Path(raw)
        if path.is_dir():
            paths.extend(sorted(path.glob("*_answers.jsonl")) or sorted(path.glob("*.json")))
        elif path.is_file():
            paths.append(path)
        else:
            print(f"missing: {path}", file=sys.stderr)
            return 2
    if not paths:
        print("no answer files found", file=sys.stderr)
        return 2
    results = check_files(paths)
    if args.tsv:
        write_tsv(Path(args.tsv), results)
    by_qid = {answer["qid"]: answer for result in results.values() for answer in result["answers"]}
    print(f"{'file':34s} {'answers':>7s} {'flagged':>7s} {'warned':>6s}  by reason code")
    totals = Counter()
    for name, result in results.items():
        flagged = [answer for answer in result["answers"] if not answer["ok"]]
        warned = [answer for answer in result["answers"] if answer["ok"]
                  and any(f["severity"] == "warn" for f in answer["findings"])]
        codes = Counter(f["code"] for f in result["findings"] if f["severity"] == "fail")
        totals.update(codes)
        print(f"{name:34s} {len(result['answers']):7d} {len(flagged):7d} {len(warned):6d}  "
              + ", ".join(f"{code}={count}" for code, count in sorted(codes.items())))
        if not args.quiet:
            for answer in result["answers"]:
                for finding in answer["findings"]:
                    print(f"  {answer['qid']:14s} {finding['severity']:4s} {finding['code']:16s} "
                          f"{finding['detail'][:150]}")
    print(f"\n{len(by_qid)} answers, {sum(totals.values())} failing findings: "
          + ", ".join(f"{code}={count}" for code, count in sorted(totals.items())))
    if args.dev:
        kinds = read_dev(Path(args.dev))
        missed = [qid for qid, kind in kinds.items() if kind == "arith_miss" and qid in by_qid
                  and by_qid[qid]["ok"]]
        caught = [qid for qid, kind in kinds.items() if kind == "arith_miss" and qid in by_qid
                  and not by_qid[qid]["ok"]]
        false_alarms = [qid for qid, kind in kinds.items() if kind == "right" and qid in by_qid
                        and not by_qid[qid]["ok"]]
        missing = [qid for qid in kinds if qid not in by_qid]
        print(f"\ndev set: {len(caught)} of {len(caught) + len(missed)} arith_miss caught, "
              f"{len(false_alarms)} of {sum(1 for k in kinds.values() if k == 'right')} right flagged")
        print("  caught:   " + ", ".join(sorted(caught)))
        print("  NOT caught: " + ", ".join(sorted(missed)))
        for qid in sorted(false_alarms):
            answer = by_qid[qid]
            print(f"  flagged right: {qid}")
            for finding in answer["findings"]:
                if finding["severity"] == "fail":
                    print(f"    {finding['code']}: {finding['detail'][:160]}")
        if missing:
            print("  not in the files given: " + ", ".join(sorted(missing)[:8]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
