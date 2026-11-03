"""Rule-based forward-guidance extractor -> table ``guidance`` (T-049). No model, no OCR, no network.

CLI: ``python -m reality_engine.pilot3.guidance --out <db> [--symbols KEC,BAJFINANCE,HINDALCO] [--limit-docs N]``

One row per forward-looking numeric target stated in a held transcript, deck, results file or press release:
metric (revenue_growth, ebitda_margin, order_intake, nim, credit_cost, aum_growth, capex, cost_of_production,
interest_cost, ebitda_per_tonne, other), target period, low/high, unit, direction, the exact sentence, the speaker
(a transcript), the filing date and ``known_at``, and ``revision_of`` = the previous row of the same metric+period,
so a "what did they guide and did it change" question answers from one table.

Input is this database's own ``doc_page`` (transcripts read through ``transcript_statement`` so only management
sentences are stored, with their role and call period; decks/results/press releases are split into sentences and
keep the exact page slice).  A sentence is kept only when it carries a guidance cue, a number, a metric word (in the
sentence or the closest 700 characters before it, where the analyst's question sits) and a target period (explicit,
or the call/result year, with a Q4 call's unlabelled "for the year" read as the next fiscal year).  Macro forecasts
(GDP, inflation, IMF, repo), a metric level that cannot be right for that metric, and sentences whose only cue is a
past measurement (achieved, stood at, grew by, last year) are dropped, so ``pilot3_guidance`` returns targets, not
commentary.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter

from .schema import TABLES, GUIDANCE_INDEXES
from .transcripts import split_sentences

COLS = ("symbol isin metric target_period low high unit direction said_on doc_key page quote speaker "
        "known_at known_at_source revision_of extractor_rule").split()

DOC_TYPES = ("transcript", "deck", "results", "press_release")
MAX_ROWS_PER_PAGE = 6
BEFORE = 700
AFTER = 250

# --- sentences --------------------------------------------------------------------------------------
CUE = re.compile(
    r"\b(guidan\w*|guided|guide|corridor|target(?:s|ing|ed)?|estimates?|estimated|expect(?:s|ed|ing)?|"
    r"anticipate[sd]?|foresee|should be|would be|will be|going forward|outlook|we believe|"
    r"is expected to|are expected to|going to see|going to be|talking about)\b", re.I)
PAST_ONLY = re.compile(r"\b(achieved|stood at|reported|last year|lask year|previous year|prior year|year ago|"
                       r"grew by|improved by|rose by|was at|were at|was around|were around|increased by|"
                       r"declined by|margin of \d|up \d+% (?:yoy|year-on-year|y-o-y)|"
                       # T-049, 4 Nov 2026: a reported quarter's cost ("was impacted by ... $54 million",
                       # "Adjusted EBITDA down 9% YoY", "came in at $506") was stored as a forward target
                       r"down \d+(?:\.\d+)?\s*%\s*(?:yoy|year-on-year|y-o-y|q[1-4])|impacted by|came in at)\b", re.I)
# a percentage that is the rate OF something else ("232 aluminium tariffs at 50%", "a duty of 10%") is not a
# company target (T-049, 4 Nov 2026: a tariff rate was stored as an FY26 EBITDA margin)
RATE_OF = re.compile(r"\b(?:tariffs?|duty|customs duty|levy|surcharge|tax rate|repo rate)\b[^.%]{0,40}"
                     r"\d+(?:\.\d+)?\s*%", re.I)
FACT_SHAPE = re.compile(r"\b(today|currently|as of|as at|current level|stands? at|backlog)\b", re.I)
OWN_PERIOD = re.compile(r"\b(?:(?:next|this|current|following)\s+(?:fiscal|financial year|year)|for the (?:full )?year|"
                        r"full year|FY\s*'?\s*\d|fiscal\s*'?\s*\d|Q[1-4]\s*FY)\b", re.I)
FORWARD = re.compile(r"\b(expect\w*|anticipat\w*|will be|should be|would be|target\w*|estimat\w*|guidance|"
                     r"going forward|going to|foresee|outlook|corridor)\b", re.I)
MACRO = re.compile(r"\b(gdp|inflation|economy|economic growth|imf|world bank|repo rate|rbi projects|"
                   r"global growth|global|ex-china|headline inflation|consumer price|cy\s?\d{2})\b", re.I)
UP = re.compile(r"\b(increas\w*|rise|rising|grow\w*|improv\w*|expand\w*|higher|\bup\b|accelerat\w*|inflation)\b", re.I)
DOWN = re.compile(r"\b(decreas\w*|declin\w*|lower\w*|\bcut\b|moderat\w*|reduc\w*|come down|coming down|"
                  r"fall\w*|drop\w*|soften\w*|down\b)\b", re.I)
FLAT = re.compile(r"\b(maintain\w*|unchanged|intact|flat|steady|stable|remain\w*|same)\b", re.I)

# metric -> (sentence pattern, plausibility low, plausibility high); priority order matters
METRICS = (
    ("nim", re.compile(r"\bnim\b|net interest margin", re.I), 0.0, 20.0),
    ("credit_cost", re.compile(r"credit cost|loan loss", re.I), 0.0, 20.0),
    ("aum_growth", re.compile(r"\baum\b|assets under management", re.I), 0.0, 60.0),
    ("ebitda_per_tonne", re.compile(r"ebitda\s*(?:per|/)\s*(?:ton|tonne|t)\b|(?:downstream|upstream)\s+ebitda\b|"
                                    r"\bdownstream\b", re.I), 1.0, 5000.0),
    ("order_intake", re.compile(r"order intake|order inflow|order booking|order win", re.I), 50.0, 500000.0),
    ("capex", re.compile(r"\bcapex\b|capital expenditure|capital cost", re.I), 1.0, 5000000.0),
    ("interest_cost", re.compile(r"interest cost|interest expense|interest as %|finance cost", re.I), 0.0, 5000.0),
    ("cost_of_production", re.compile(r"cost of production|cash cost|cost inflation|inflation in cost|"
                                      r"input cost|energy cost|costs? (?:went|going|to) up", re.I), -20.0, 60.0),
    ("revenue_growth", re.compile(r"\brevenue\b|top ?line|net sales|\bsales\b", re.I), -20.0, 60.0),
    ("ebitda_margin", re.compile(r"ebitda margin|\bmargin\b|\bmargins\b", re.I), 0.0, 50.0),
    ("other", re.compile(r"order book|fixed|variable|volume|shipment|capacity|utilization|utilisation|"
                         r"customer|market share|pass[- ]through|price variation", re.I), -1e9, 1e9),
)
# --- numbers ----------------------------------------------------------------------------------------
MONEY = r"(?:rs\.?|inr|₹|usd|\$)"
AMT = r"(\d[\d,]*(?:\.\d+)?)"
UNITWORD = r"(crores?|\bcr\b|lakhs?|million|mn|billion|bn|kilotonnes?|kt\b|tonnes?|/t\b|per ton|per tonne|a ton)?"
R_PCT_RANGE = re.compile(r"(?<![\d.])" + AMT + r"\s*%\s*(?:to|-|–|—)\s*" + AMT + r"\s*%")
R_PCT_RANGE2 = re.compile(r"(?<![\d.])" + AMT + r"\s*(?:to|-|–|—)\s*" + AMT + r"\s*%")
R_BPS_RANGE = re.compile(AMT + r"\s*(?:to|-|–|—)\s*" + AMT + r"\s*(?:bps|basis points)", re.I)
R_MONEY_RANGE = re.compile(MONEY + r"\s*" + AMT + r"\s*" + UNITWORD + r"\s*(?:to|-|–|—)\s*" + MONEY + r"?\s*" + AMT +
                           r"\s*" + UNITWORD, re.I)
R_MONEY = re.compile(MONEY + r"\s*" + AMT + r"\s*" + UNITWORD, re.I)
# "INR20 crores, INR25 crores" / "5%, 6%": a range said as a pair, only next to a hedging word
R_PAIR = re.compile(r"(?<![\d.])" + AMT + r"\s*(%|crores?|\bcr\b)\s*,\s*(?:and\s+)?" + MONEY + r"?\s*" + AMT +
                    r"\s*(%|crores?|\bcr\b)", re.I)
PAIR_CUE = re.compile(r"\b(maybe|around|about|between|anywhere|roughly|approximately|another)\b", re.I)
R_PCT_SINGLE = re.compile(r"(?<![\d.])" + AMT + r"\s*%")
R_BPS_SINGLE = re.compile(AMT + r"\s*(?:bps|basis points)", re.I)
R_PER_TON = re.compile(MONEY + r"?\s*" + AMT + r"\s*(?:/t\b|per ton|per tonne|a ton)", re.I)
BULLETS = re.compile(r"[▪•❑●]")


def _num(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except (AttributeError, ValueError):
        return None


def _money_unit(word: str | None, raw: str = "") -> str:
    word = (word or "").lower()
    if "crore" in word or word.strip() == "cr":
        return "inr_cr"
    if "lakh" in word:
        return "inr_lakh"
    if "million" in word or word == "mn":
        return "usd_mn"
    if "billion" in word or word == "bn":
        return "usd_bn"
    if word in ("/t", "per ton", "per tonne", "a ton"):
        return "usd_per_t"
    return "usd" if re.search(r"(?:usd|\$)", raw, re.I) else "inr"


def _per_ton_unit(raw: str) -> str:
    return "inr_per_t" if re.search(r"(?:rs\.?|inr|₹)", raw, re.I) else "usd_per_t"


def numbers(text: str) -> list[dict]:
    """Every numeric target in a sentence: {start, end, low, high, unit}. Ranges first, then single values."""
    out: list[dict] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    def add(a: int, b: int, low: float, high: float, unit: str) -> None:
        if free(a, b):
            taken.append((a, b))
            out.append({"start": a, "end": b, "low": low, "high": high, "unit": unit})

    for m in R_PCT_RANGE.finditer(text):
        low, high = _num(m.group(1)), _num(m.group(2))
        if low is not None and high is not None:
            add(m.start(), m.end(), min(low, high), max(low, high), "pct")
    for m in R_PCT_RANGE2.finditer(text):
        low, high = _num(m.group(1)), _num(m.group(2))
        if low is not None and high is not None:
            add(m.start(), m.end(), min(low, high), max(low, high), "pct")
    for m in R_BPS_RANGE.finditer(text):
        low, high = _num(m.group(1)), _num(m.group(2))
        if low is not None and high is not None:
            add(m.start(), m.end(), min(low, high), max(low, high), "bps")
    for m in R_MONEY_RANGE.finditer(text):
        low, high = _num(m.group(1)), _num(m.group(3))
        if low is not None and high is not None:
            add(m.start(), m.end(), min(low, high), max(low, high), _money_unit(m.group(2) or m.group(4), m.group(0)))
    for m in R_PAIR.finditer(text):
        if not PAIR_CUE.search(text[max(0, m.start() - 30):m.start() + 5]):
            continue
        low, high = _num(m.group(1)), _num(m.group(3))
        u1, u2 = m.group(2), m.group(4)
        if low is None or high is None or (u1 == "%") != (u2 == "%"):
            continue
        add(m.start(), m.end(), min(low, high), max(low, high), "pct" if u1 == "%" else _money_unit(u1, m.group(0)))
    for m in R_PCT_SINGLE.finditer(text):
        v = _num(m.group(1))
        if v is not None:
            add(m.start(), m.end(), v, v, "pct")
    for m in R_BPS_SINGLE.finditer(text):
        v = _num(m.group(1))
        if v is not None:
            add(m.start(), m.end(), v, v, "bps")
    for m in R_MONEY.finditer(text):
        v = _num(m.group(1))
        if v is not None:
            add(m.start(), m.end(), v, v, _money_unit(m.group(2), m.group(0)))
    for m in R_PER_TON.finditer(text):
        v = _num(m.group(1))
        if v is not None and v >= 1:
            add(m.start(), m.end(), v, v, _per_ton_unit(m.group(0)))
    return out


# --- periods ----------------------------------------------------------------------------------------
Q_FY = re.compile(r"\bQ\s*([1-4])\s*[- ]?\s*FY\s*'?\s*(\d{2,4})", re.I)
H_FY = re.compile(r"\bH\s*([12])\s*[- ]?\s*FY\s*'?\s*(\d{2,4})", re.I)
FY_RANGE = re.compile(r"\bFY\s*'?\s*(\d{2})\s*[-/]\s*(\d{2,4})", re.I)
FY = re.compile(r"\b(?:FY|fiscal(?: year)?)\s*'?\s*(\d{2,4})", re.I)
NEXT = re.compile(r"\b(next|following)\s+(?:fiscal|financial year|year|fiscal)\b", re.I)
THIS = re.compile(r"\b(this|current)\s+(?:fiscal|financial year|year)\b|\bfor the (?:full )?year\b|\bfull year\b|"
                  r"\bannually\b|\bannual(?:ly)? basis\b", re.I)
BARE_Q = re.compile(r"(?<![\w.])(?:in\s+|from\s+|to\s+)?Q\s*([1-4])(?!\s*[- ]?FY)(?![\d])", re.I)


def _yy(text: str) -> str:
    return f"{int(text) % 100:02d}"


def doc_period(filing_date: str | None, known_at: str | None) -> tuple[int, str] | None:
    """(fiscal year number, quarter) of the period a filing reports: Apr-Jun files Q4 of that year, Jul-Sep Q1
    of the next, Oct-Dec Q2, Jan-Mar Q3."""
    day = (filing_date or (known_at or "")[:10] or "")[:10]
    m = re.match(r"(\d{4})-(\d{2})", day)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if 4 <= month <= 6:
        return year % 100, "Q4"
    if 7 <= month <= 9:
        return (year + 1) % 100, "Q1"
    if 10 <= month <= 12:
        return (year + 1) % 100, "Q2"
    return year % 100, "Q3"


def split_period(label: str | None) -> tuple[int | None, str | None]:
    """'Q4FY26' -> (26, 'Q4'); 'FY26' -> (26, None)."""
    if not label:
        return None, None
    m = re.fullmatch(r"(?:Q([1-4])|H([12]))?FY(\d{2})", label.upper())
    if not m:
        return None, None
    return int(m.group(3)), ("Q" + m.group(1) if m.group(1) else None)


def base_forward(call_period: str | None, doc: tuple[int, str] | None) -> int | None:
    """The fiscal year a guidance sentence in this document is about when it names none: the call/result year, and
    for a Q4 filing the year after (a Q4 earnings call guides the year ahead)."""
    fy, q = split_period(call_period)
    if fy is not None:
        return fy + 1 if q == "Q4" else fy
    if doc:
        return doc[0] + 1 if doc[1] == "Q4" else doc[0]
    return None


def _explicit_period(text: str) -> str | None:
    m = Q_FY.search(text)
    if m:
        return f"Q{m.group(1)}FY{_yy(m.group(2))}"
    m = H_FY.search(text)
    if m:
        return f"H{m.group(1)}FY{_yy(m.group(2))}"
    m = FY_RANGE.search(text)
    if m:
        return f"FY{_yy(m.group(2))}"
    m = FY.search(text)
    if m:
        return f"FY{_yy(m.group(1))}"
    return None


def target_period(sentence: str, before: str, after: str, call_period: str | None,
                  doc: tuple[int, str] | None, pos: int | None = None) -> str | None:
    """The period a target is about: explicit label in the sentence, else the nearest one before it (the question),
    else the call/result year rule; a bare "Q2" is the next quarter with that number after the call, and the bare
    quarter nearest the target number wins ("5%, 6% Q2 to Q1" names Q2)."""
    label = _explicit_period(sentence)
    if label:
        return label
    base = base_forward(call_period, doc)
    if base is None:
        return None
    if NEXT.search(sentence) or THIS.search(sentence):
        return f"FY{base:02d}"
    qs = list(BARE_Q.finditer(sentence))
    if qs:
        # the quarter the sentence is about: nearest one after the target number, but never a comparison base
        # ("versus Q4", "from Q3"); with no number position, the first one wins
        if pos is None:
            q = qs[0]
        else:
            kept = [m for m in qs
                    if not re.search(r"\b(?:versus|vs\.?|from|than|against|compared with)\s*$",
                                     sentence[max(0, m.start() - 14):m.start()], re.I)]
            after_q = [m for m in kept if m.start() >= pos]
            before_q = [m for m in kept if m.start() < pos]
            q = (min(after_q, key=lambda m: m.start()) if after_q else
                 (max(before_q, key=lambda m: m.start()) if before_q else qs[0]))
        fy, call_q = split_period(call_period)
        n = int(q.group(1))
        if fy is None and doc:
            fy, call_q = doc[0], doc[1]
        if fy is not None and call_q:
            return f"Q{n}FY{fy + (1 if n <= int(call_q[1]) else 0):02d}"
        if fy is not None:
            return f"Q{n}FY{fy:02d}"
    for text in (before[-500:], after):
        label = _explicit_period(text)
        if label:
            return label
    return f"FY{base:02d}"


# --- classification ---------------------------------------------------------------------------------
METRIC_UNITS = {
    "nim": {"pct", "bps"},
    "credit_cost": {"pct", "bps"},
    "aum_growth": {"pct"},
    "revenue_growth": {"pct"},
    "ebitda_margin": {"pct"},
    "cost_of_production": {"pct"},
    "interest_cost": {"pct", "inr_cr", "inr", "inr_lakh"},
    "order_intake": {"inr_cr", "inr", "inr_lakh", "usd", "usd_mn", "usd_bn", "count"},
    "capex": {"inr_cr", "inr", "inr_lakh", "usd", "usd_mn", "usd_bn"},
    # a per-tonne target is often said as a bare "$250", converted to usd_per_t / inr_per_t below
    "ebitda_per_tonne": {"usd_per_t", "inr_per_t", "usd", "inr"},
    "other": {"pct", "bps", "inr_cr", "inr", "inr_lakh", "usd", "usd_mn", "usd_bn", "count", "usd_per_t", "inr_per_t"},
}


def metric_candidates(symbol: str, sentence: str, before: str, after: str) -> list[str]:
    """Metric names in priority order: the sentence first, then the question before it, then the text after.
    ``other`` (a share or structural statement) ranks last whatever text it came from."""
    seen: list[str] = []
    for text in (sentence, before[-300:], after[:150]):
        for name, rx, _lo, _hi in METRICS:
            if name == "other" or not rx.search(text) or name in seen:
                continue
            if name == "ebitda_margin" and symbol == "BAJFINANCE" and not re.search(r"ebitda", text, re.I):
                name = "nim"          # a lender's "margin" is its NIM
            if name not in seen:
                seen.append(name)
    if any(rx.search(text) for text in (sentence, before[-300:], after[:150])
           for nm, rx, _lo, _hi in METRICS if nm == "other"):
        seen.append("other")
    return seen


def plausible(metric: str, low: float, high: float, unit: str) -> bool:
    """A unit the metric can be stated in and a level that can be right for it."""
    if unit not in METRIC_UNITS.get(metric, set()):
        return False
    for name, _rx, lo, hi in METRICS:
        if name == metric:
            break
    else:
        return False
    if unit == "bps":
        return 0 < high <= 2000
    if metric == "interest_cost":       # a percentage well above 15 is a market rate, not the company's target
        return 0 <= low <= high <= 15 if unit == "pct" else high > 0
    if unit == "pct":
        return lo <= low <= high <= hi
    if metric in ("revenue_growth", "aum_growth", "ebitda_margin", "cost_of_production", "nim", "credit_cost"):
        return False
    return lo <= low <= high <= hi and high > 0


def direction_of(sentence: str, metric: str) -> str:
    if DOWN.search(sentence):
        return "down"
    if FLAT.search(sentence):
        return "flat"
    if UP.search(sentence):
        return "up"
    return "up" if metric in ("revenue_growth", "aum_growth") else "flat"


def pick_number(sentence: str, nums: list[dict]) -> dict | None:
    """The number the guidance verb points at: the first one after the nearest cue, else the nearest to it."""
    cues = [m.start() for m in CUE.finditer(sentence)]
    if not cues:
        return nums[0] if nums else None
    after = [(n["start"] - max(c for c in cues if c <= n["start"]), n) for n in nums if any(c <= n["start"] for c in cues)]
    if after:
        return min(after, key=lambda t: t[0])[1]
    return min(nums, key=lambda n: min(abs(n["start"] - c) for c in cues))


# --- reading the database ---------------------------------------------------------------------------
def _docs(con: sqlite3.Connection, symbol: str):
    return con.execute(
        "SELECT doc_key, doc_type, isin, title, filing_date, known_at FROM doc WHERE symbol=? AND doc_type IN "
        f"({','.join('?' * len(DOC_TYPES))}) ORDER BY COALESCE(known_at, filing_date)", (symbol, *DOC_TYPES)).fetchall()


def _transcript_statements(con: sqlite3.Connection, symbol: str) -> dict[str, list[sqlite3.Row]]:
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='transcript_statement'").fetchone():
        return {}
    out: dict[str, list[sqlite3.Row]] = {}
    for row in con.execute("SELECT doc_key, page, call_period, speaker, role, statement, quote FROM "
                           "transcript_statement WHERE symbol=? ORDER BY doc_key, page, seq", (symbol,)):
        out.setdefault(row["doc_key"], []).append(row)
    return out


def _speaker_in(page_text: str, sentence: str) -> str | None:
    """Nearest "Name:" label before the sentence in the page text (used only when transcript_statement has no row)."""
    pos = page_text.find(sentence[:60])
    if pos < 0:
        return None
    labels = [m for m in re.finditer(r"(?m)^[ \t]*([A-Z][A-Za-z.'’\-]+(?: [A-Za-z.'’\-]+){0,4}):[ \t]*$", page_text[:pos])]
    return labels[-1].group(1) if labels else None


def page_sentences(raw: str) -> list[tuple[int, int]]:
    """Sentence spans of a page, broken again at bullet markers so a deck's bullets are separate sentences."""
    out: list[tuple[int, int]] = []
    for a, b in split_sentences(raw, 0):
        seg = raw[a:b]
        marks = [m.start() for m in BULLETS.finditer(seg)] + [len(seg)]
        for start, end in zip([0] + marks, marks):
            if seg[start:end].strip():
                out.append((a + start, a + end))
    return out


def extract_sentences(symbol: str, doc: sqlite3.Row, page: int, raw: str, statements: list[sqlite3.Row],
                      stats: dict) -> list[tuple]:
    """Guidance rows (without revision_of) from one page: transcript statements when held, else split sentences."""
    collapsed = " ".join(raw.split())
    items: list[tuple[str, str, str | None]] = []      # (sentence, quote, speaker)
    if statements:
        for st in statements:
            stmt = " ".join((st["statement"] or "").split())
            if stmt:
                items.append((stmt, " ".join((st["quote"] or stmt).split()), st["speaker"]))
    else:
        for a, b in page_sentences(raw):
            s = " ".join(raw[a:b].split())
            if s:
                items.append((s, s, _speaker_in(raw, s)))
    call_period = statements[0]["call_period"] if statements else None
    docper = doc_period(doc["filing_date"], doc["known_at"])
    rows = []
    for sentence, quote, speaker in items:
        if len(sentence) < 30 or len(sentence) > 400:
            continue
        nums = numbers(sentence)
        if not nums:
            continue
        pos = collapsed.find(sentence)
        before = collapsed[max(0, pos - BEFORE):pos] if pos >= 0 else ""
        after = collapsed[pos + len(sentence):pos + len(sentence) + AFTER] if pos >= 0 else ""
        strong = bool(CUE.search(sentence))
        if not strong:
            # a range answer to a guidance question asked in the 300 characters before it
            question = before[-300:]
            if not (any(n["high"] > n["low"] for n in nums) and CUE.search(question)
                    and metric_candidates(symbol, "", question, "")):
                stats["no_cue"] += 1
                continue
        if PAST_ONLY.search(sentence) and not FORWARD.search(sentence):
            stats["past_only"] += 1
            continue
        if MACRO.search(sentence) and not re.search(
                r"ebitda|revenue|margin|aum|nim|order intake|credit|inflation in cost|cost inflation|cost of production",
                sentence, re.I):
            stats["macro"] += 1
            continue
        chosen = metric = None
        rx_by_name = {name: rx for name, rx, _lo, _hi in METRICS}
        for name in metric_candidates(symbol, sentence, before, after):
            if name == "other" and (not strong or FACT_SHAPE.search(sentence)):
                continue
            if name == "credit_cost" and re.search(r"gnpa|nnpa|\bnpa\b", sentence, re.I) \
                    and not re.search(r"credit cost|loan loss", sentence, re.I):
                continue                    # asset-quality actuals are not the credit-cost target
            options = [n for n in nums if plausible(name, n["low"], n["high"], n["unit"])]
            marks = [m.start() for m in rx_by_name[name].finditer(sentence)]
            if marks:
                # the metric word is in this sentence: the target is the number it introduces, not a chart blob's
                near = [n for n in options
                        if any((p <= n["start"] and n["start"] - p <= 150) or (n["start"] < p and p - n["start"] <= 40)
                               for p in marks)]
                if not near:
                    continue
                options = near
            if options:
                metric, chosen = name, pick_number(sentence, options)
                break
        if not chosen:
            stats["no_metric" if not metric_candidates(symbol, sentence, before, after) else "implausible"] += 1
            continue
        rate = RATE_OF.search(sentence)
        if rate and rate.start() <= chosen["start"] <= rate.end():
            stats["rate_not_target"] += 1
            continue                        # the number is the rate of a tariff/duty, not a target
        cues = [m.start() for m in CUE.finditer(sentence)]
        if PAST_ONLY.search(sentence) and cues and chosen["start"] < min(cues):
            stats["past_only"] += 1
            continue                        # the number is the measurement, the forward part has no number
        if PAST_ONLY.search(sentence) and not OWN_PERIOD.search(sentence):
            stats["past_only"] += 1
            continue                        # "last year would be 7.5%": a measurement, not a target period
        if metric == "other" and (FACT_SHAPE.search(sentence) or "market share" in sentence.lower()
                                  or not any(abs(c - chosen["start"]) <= 80 for c in cues)):
            stats["other_fact"] += 1
            continue
        period = target_period(sentence, before, after, call_period, docper, chosen["start"])
        if not period:
            stats["no_period"] += 1
            continue
        if metric == "ebitda_per_tonne" and chosen["unit"] in ("usd", "inr"):
            chosen = {**chosen, "unit": "usd_per_t" if chosen["unit"] == "usd" else "inr_per_t"}
        rows.append((symbol, doc["isin"], metric, period, chosen["low"], chosen["high"], chosen["unit"],
                     direction_of(sentence, metric or "other"), (doc["filing_date"] or (doc["known_at"] or "")[:10]),
                     doc["doc_key"], page, quote, speaker, doc["known_at"], "doc.known_at",
                     None, "guidance_cue_v1"))
        if len(rows) >= MAX_ROWS_PER_PAGE:
            break
    return rows


def run(out: str, symbols: list[str], limit_docs: int | None = None) -> dict:
    t0 = time.time()
    con = sqlite3.connect(out)
    con.row_factory = sqlite3.Row
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='guidance'").fetchone():
        con.execute(TABLES["guidance"])
    con.executescript(";".join(GUIDANCE_INDEXES))
    stats_all: dict = {}
    ins = f"INSERT INTO guidance({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})"
    for symbol in symbols:
        con.execute("DELETE FROM guidance WHERE symbol=?", (symbol,))
        st = stats_all[symbol] = Counter()
        statements = _transcript_statements(con, symbol)
        for index, doc in enumerate(_docs(con, symbol)):
            if limit_docs is not None and index >= limit_docs:
                break
            by_page: dict[int, list[sqlite3.Row]] = {}
            for row in statements.get(doc["doc_key"], []):
                by_page.setdefault(row["page"], []).append(row)
            seen: set[tuple] = set()
            pages = con.execute("SELECT page, text FROM doc_page WHERE doc_key=? ORDER BY page", (doc["doc_key"],))
            for page, text in pages:
                if not (text or "").strip():
                    continue
                st["pages"] += 1
                for row in extract_sentences(symbol, doc, page, text, by_page.get(page, []), st):
                    sig = (row[9], row[10], row[2], row[3], row[4], row[5])
                    if sig in seen:
                        st["duplicate"] += 1
                        continue
                    seen.add(sig)
                    con.execute(ins, row)
                    st["rows"] += 1
                    st[row[2]] += 1
        con.commit()
        revs = revisions(con, symbol)
        st["revisions"] = revs
        stats_all[symbol] = {k: v for k, v in st.items() if not isinstance(v, Counter)}
    stats_all["seconds"] = round(time.time() - t0, 1)
    stats_all["rows"] = dict(con.execute("SELECT symbol, COUNT(*) FROM guidance GROUP BY symbol"))
    con.close()
    return stats_all


def revisions(con: sqlite3.Connection, symbol: str) -> int:
    """Link every row to the previous row of the same metric+period from an earlier document."""
    rows = con.execute("SELECT id, metric, target_period, doc_key FROM guidance WHERE symbol=? "
                       "ORDER BY COALESCE(known_at, said_on), said_on, id", (symbol,)).fetchall()
    prev: dict[tuple, tuple[int, str]] = {}
    linked = 0
    for row in rows:
        key = (row[1], row[2])
        old = prev.get(key)
        if old and old[1] != row[3]:
            con.execute("UPDATE guidance SET revision_of=? WHERE id=?", (old[0], row[0]))
            linked += 1
        prev[key] = (row[0], row[3])
    con.commit()
    return linked


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default="KEC,BAJFINANCE,HINDALCO")
    ap.add_argument("--limit-docs", type=int, default=None)
    a = ap.parse_args(argv)
    stats = run(a.out, [s.strip().upper() for s in a.symbols.split(",") if s.strip()], a.limit_docs)
    print(json.dumps(stats, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
