"""Rule-based company KPI extractor -> table kpi_series (T-049 B). No model, no OCR, no network.

CLI: python -m reality_engine.pilot3.kpi --out <db> [--symbols KEC,BAJFINANCE,HINDALCO] [--sandbox-root DIR]
                                      [--pages-db D:\\RealityEngine\\pilot3\\pages.db]

Reads page text from pages.db when --pages-db is given (the collector's every held document, the same source
the pilot3 registry writes; PDF from doc.source_path, else decks_full/<sha>), then from
<sandbox>/<sym>_loop/<sym>.db (doc_text + docs) for the documents pages.db does not hold; for table/chart
pages the word positions come from the PDF (PyMuPDF). Pages whose method is needs_ocr are skipped and counted,
the OCR text of a page already read into doc_page (method ocr_rapid or ocr_textrec) is used. Three rules write rows:
  table_v1    label row + period header row, values paired to header columns by x position
  chart_v1    a bare number row sitting above a period axis row, titled by the nearest lexicon label above
  sentence_v1 label ... value [unit] [period] [vs value period] inside running text
A row is stored only if its quote is a literal substring of the page text, and only if its period can have closed
by the document's ``known_at``: a document cannot report a period that ended after it was filed, so a misread
period label ("June 26, 2019" read as June 2026, which made the KEC FY19 annual report's figures Q1FY27) drops the
row instead of storing it (``keep_period``, counted as ``period_after_doc``). A transcript's ``known_at`` is raised
to the call date printed in it (``call_dates``): a call cannot be known before it was held.
Shared helpers (periods, numbers, units, lexicon loader) are imported by transcripts.py.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import re
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import call_dates, profile

LEX_DIR = Path(__file__).parent / "lexicon"
SANDBOX_ROOT = Path("D:/RealityEngine/sandbox")
COMPANIES = {"KEC": "kec", "BAJFINANCE": "bajfinance", "HINDALCO": "hindalco"}
KPI_DOC_TYPES = ("deck", "results", "press_release", "transcript", "annual_report", "announcement")
PDF_DOC_TYPES = ("deck", "results", "press_release", "annual_report")  # table/chart mode needs the PDF
OCR_METHOD_RANK = {"ocr_textrec": 2, "ocr_rapid": 1}  # several --ocr-db: the HP TextRecognizer reading wins

SCHEMA = """
CREATE TABLE IF NOT EXISTS kpi_series (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL, isin TEXT, metric TEXT NOT NULL, dimension TEXT NOT NULL DEFAULT 'total',
  value REAL NOT NULL, unit TEXT NOT NULL, scale REAL NOT NULL DEFAULT 1,
  period_type TEXT NOT NULL, fiscal_period TEXT NOT NULL, as_of_date TEXT,
  basis TEXT NOT NULL DEFAULT 'not_stated', doc_key TEXT NOT NULL, page INTEGER NOT NULL,
  quote TEXT NOT NULL, known_at TEXT, known_at_source TEXT, is_reported INTEGER NOT NULL DEFAULT 1,
  raw_label TEXT, raw_value TEXT, extractor_rule TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'sentence', conf_rank INTEGER NOT NULL DEFAULT 2,
  method TEXT NOT NULL DEFAULT 'text_layer', ocr_conf REAL,
  source_type TEXT NOT NULL DEFAULT '',
  UNIQUE(symbol, metric, dimension, fiscal_period, value, unit, doc_key, page)
);
CREATE INDEX IF NOT EXISTS ix_kpi_sym_metric ON kpi_series(symbol, metric, fiscal_period);
"""

# confidence of a row by the rule that wrote it: table_row > table_chart > sentence > sentence_default (T-049 E)
RULE_CONF = {"table_v1": ("table_row", 4), "mix_v1": ("table_row", 4), "chart_v1": ("table_chart", 3),
             "sentence_v1": ("sentence", 2), "sentence_pair_v1": ("sentence", 2),
             "sentence_default_v1": ("sentence_default", 1)}
CONF_RANK = {name: rank for name, rank in RULE_CONF.values()}
NEW_COLS = (("confidence", "TEXT NOT NULL DEFAULT 'sentence'"), ("conf_rank", "INTEGER NOT NULL DEFAULT 2"),
            ("method", "TEXT NOT NULL DEFAULT 'text_layer'"), ("ocr_conf", "REAL"),
            ("source_type", "TEXT NOT NULL DEFAULT ''"))

# ---------------------------------------------------------------- periods
_MONTHS = {m: i + 1 for i, m in enumerate(
    "january february march april may june july august september october november december".split())}
_MON_PAT = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_QEND = {3: (4, 31), 6: (1, 30), 9: (2, 30), 12: (3, 31)}


def _yy(s: str) -> int:
    s = s.replace("’", "").replace("'", "")
    if "-" in s:
        s = s.split("-")[-1]
    return int(s[-2:])


def _mon(s: str) -> int:
    return _MONTHS[[k for k in _MONTHS if k.startswith(s.lower()[:3])][0]]


PERIOD_PATTERNS = [
    ("QFY", re.compile(r"(?<![A-Za-z0-9])(?:Q\s?([1-4])|([1-4])\s?Q)\s?[-]?\s?(?:FY\s?)?['’]?\s?(\d{4}-\d{2}|\d{4}|\d{2})(?![\d])", re.I)),
    ("MFY", re.compile(r"(?<![A-Za-z0-9])(9M|6M|3M|12M|H[12])[\s-]?(?:FY\s?)?['’]?\s?(\d{4}|\d{2})(?![\d])", re.I)),
    ("FY", re.compile(r"(?<![A-Za-z0-9])FY\s?['’]?\s?(\d{4}-\d{2}|\d{2}-\d{2}|\d{4}|\d{2})(?![\d])", re.I)),
    ("DATE_DMY", re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s,.-]+(" + _MON_PAT + r")[a-z]*[\s,.-]+['’]?(\d{4}|\d{2})(?!\d)", re.I)),
    ("DATE_MDY", re.compile(r"(?<![A-Za-z])(" + _MON_PAT + r")[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)", re.I)),
    ("DATE_NUM", re.compile(r"(?<![\d.,/-])(\d{1,2})([./-])(\d{1,2})\2(20\d{2})(?![\d])")),
    ("MON_Y", re.compile(r"(?<![A-Za-z])(" + _MON_PAT + r")[a-z]*[-\s,'’]+['’]?(\d{4}|\d{2})(?!\d)(?!\s*,\s*\d{4})", re.I)),
]


@dataclass
class Period:
    start: int
    end: int
    canon: str       # Q3FY24 | FY24 | 9MFY24 | H1FY24
    ptype: str       # Q | FY | M9 | H ...
    as_of: str | None = None


def _fiscal_of_date(y: int, m: int, d: int, force_end: bool = False):
    """Fiscal period of a quarter-end date. 31 March closes the Indian fiscal year, so 2026-03-31 is FY26 (the
    annual period), not Q4FY26: a stock figure dated at the year end is the year-end one, and an FY26 question
    must find it. The date is kept in `as_of` either way."""
    fy = y + 1 if m > 3 else y
    if m == 3 and (force_end or d >= _QEND[3][1] - 1):
        return f"FY{fy % 100:02d}", "FY", f"{y:04d}-{m:02d}-{d:02d}" if d else None
    if m in _QEND and (force_end or d >= _QEND[m][1] - 1):
        q = _QEND[m][0]
        asof = f"{y:04d}-{m:02d}-{d:02d}" if d else None
        return f"Q{q}FY{fy % 100:02d}", "Q", asof
    return None


_QUARTER_START = {"Q1": (4, 1), "Q2": (7, 1), "Q3": (10, 1), "Q4": (1, 1)}
_MONTH_START = {"3M": (4, 1), "6M": (4, 1), "9M": (4, 1), "12M": (4, 1), "H1": (4, 1), "H2": (10, 1)}
_YEAR_START = (4, 1)
_QUARTER_END = {"Q1": (6, 30), "Q2": (9, 30), "Q3": (12, 31), "Q4": (3, 31)}
_MONTH_END = {"3M": (6, 30), "6M": (9, 30), "9M": (12, 31), "12M": (3, 31), "H1": (9, 30), "H2": (3, 31)}


def _period_bounds(period_type: str, fiscal_period: str | None, start: bool) -> str | None:
    canon = (fiscal_period or "").upper()
    m = re.search(r"FY(\d{2})$", canon)
    if not m:
        return None
    ye, head = 2000 + int(m.group(1)), canon[: m.start()] or (period_type or "")
    if head in _QUARTER_END:
        month, day = (_QUARTER_START if start else _QUARTER_END)[head]
        year = ye - 1 if head != "Q4" else ye
    elif head in _MONTH_END:
        if start:
            month, day = _MONTH_START[head]
            year = ye - 1
        else:
            month, day = _MONTH_END[head]
            year = ye if head in ("12M", "H2") else ye - 1
    elif head in ("", "FY"):
        month, day, year = (*_YEAR_START, ye - 1) if start else (3, 31, ye)
    else:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def period_start(period_type: str, fiscal_period: str | None) -> str | None:
    """First day of the period a row states (Q3FY24 -> 2023-10-01, 9MFY25 -> 2024-04-01, FY26 -> 2025-04-01), or
    None for a label this reader does not know.  FY26 is the year ending 2026-03-31, so Q1FY26 starts 2025-04-01."""
    return _period_bounds(period_type, fiscal_period, True)


def period_end(period_type: str, fiscal_period: str | None) -> str | None:
    """Last day of the period a row states (Q3FY24 -> 2023-12-31, FY26 -> 2026-03-31); None for an unknown label."""
    return _period_bounds(period_type, fiscal_period, False)


def window_floor() -> str | None:
    """Oldest period end a profile keeps: one year before its ``window_start`` (the YoY base).  Decks print history;
    a row whose period closed earlier than the floor is history, not a KPI of the window."""
    ws = profile.window_start()
    return f"{int(ws[:4]) - 1:04d}{ws[4:]}" if ws else None


def drop_reason(period_type: str, fiscal_period: str | None, known_at: str | None) -> str | None:
    """Why a row is dropped, or None when it can be stored: the period cannot begin after the document was filed,
    and under a profile it cannot end before the window floor (``window_floor``)."""
    start = period_start(period_type, fiscal_period)
    day = (known_at or "")[:10]
    if start and day and start > day:
        return "period_after_doc"
    if profile.under_profile():
        end, floor = period_end(period_type, fiscal_period), window_floor()
        if end and floor and end < floor:
            return "period_before_window"
    return None


def keep_period(period_type: str, fiscal_period: str | None, known_at: str | None) -> bool:
    """False when the period begins after the document was filed, so the document cannot report it.

    The KEC FY2019 annual report (known_at 2019-06-26) carried Q1FY27 rows because the date line "June 26, 2019"
    was read as "June 2026" (the day taken for a two-digit year) and the misread date became the document's default
    period.  The test is the period's own start, as the rule states: a period can never begin after its document's
    ``known_at``.  A row whose label is one this reader does not know is kept (None start).  Under a profile a row
    also has to end inside the window (``drop_reason``)."""
    return drop_reason(period_type, fiscal_period, known_at) is None


def parse_periods(text: str) -> list[Period]:
    """All period mentions in text, non-overlapping, in order."""
    found: list[Period] = []
    for kind, rx in PERIOD_PATTERNS:
        for m in rx.finditer(text):
            p = None
            if kind == "QFY":
                q = m.group(1) or m.group(2)
                y = _yy(m.group(3))
                p = Period(m.start(), m.end(), f"Q{q}FY{y:02d}", "Q")
            elif kind == "MFY":
                code = m.group(1).upper()
                y = _yy(m.group(2))
                p = Period(m.start(), m.end(), f"{code}FY{y:02d}", "H" if code.startswith("H") else code)
            elif kind == "FY":
                p = Period(m.start(), m.end(), f"FY{_yy(m.group(1)):02d}", "FY")
            elif kind == "DATE_DMY":
                d, mo, y = int(m.group(1)), _mon(m.group(2)), m.group(3)
                y = int(y) if len(y) == 4 else 2000 + int(y)
                r = _fiscal_of_date(y, mo, d)
                if r:
                    p = Period(m.start(), m.end(), r[0], r[1], r[2])
            elif kind == "DATE_NUM":     # 30.06.2025 / 31-03-2026: day.month.year, quarter ends only
                d, mo, y = int(m.group(1)), int(m.group(3)), int(m.group(4))
                if 1 <= d <= 31 and mo in _QEND:
                    r = _fiscal_of_date(y, mo, d)
                    if r:
                        p = Period(m.start(), m.end(), r[0], r[1], r[2])
            elif kind == "DATE_MDY":
                mo, d, y = _mon(m.group(1)), int(m.group(2)), int(m.group(3))
                r = _fiscal_of_date(y, mo, d)
                if r:
                    p = Period(m.start(), m.end(), r[0], r[1], r[2])
            elif kind == "MON_Y":
                mo = _mon(m.group(1))
                y = m.group(2)
                y = int(y) if len(y) == 4 else 2000 + int(y)
                if 2000 <= y <= 2035 and mo in _QEND:
                    last = _QEND[mo][1]
                    r = _fiscal_of_date(y, mo, last, True)
                    p = Period(m.start(), m.end(), r[0], r[1], r[2])
            if p:
                found.append(p)
    found.sort(key=lambda p: (p.start, -(p.end - p.start)))
    out: list[Period] = []
    for p in found:
        if out and p.start < out[-1].end:
            continue
        out.append(p)
    return out


# ---------------------------------------------------------------- numbers and units
NUM_CORE = r"\(?-?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\)?|\(?-?\d+(?:\.\d+)?\)?"
VAL_RX = re.compile(
    r"(?P<cur>₹|`|Rs\.?|INR|US\$|USD|\$|EUR|€)?\s?(?P<num>" + NUM_CORE + r")\s?"
    r"(?P<suf>crores?|crs?\b\.?|lakhs?|mn\b|mm\b|million|billion|trillion|bn\b|tn\b|kt\b|kilo ?tonnes?|tonnes?|tons?|mt\b|%|per ?cent|bps|basis points|x\b|times|days)?",
    re.I)
_UNIT_BY_SUFFIX = {
    "crore": "inr_cr", "crores": "inr_cr", "cr": "inr_cr", "crs": "inr_cr",
    "mn": "mn", "mm": "mn", "million": "mn", "billion": "bn", "bn": "bn", "trillion": "tn", "tn": "tn",
    "kt": "kt", "kilotonne": "kt", "kilotonnes": "kt", "kilo tonne": "kt", "kilo tonnes": "kt",
    "tonne": "tonnes", "tonnes": "tonnes", "ton": "tonnes", "tons": "tonnes", "mt": "mt",
    "%": "pct", "per cent": "pct", "percent": "pct", "bps": "bps", "basis points": "bps",
    "x": "x", "times": "x", "days": "days",
}


def to_float(s: str) -> float | None:
    t = s.strip()
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _comma_decimal(num: str) -> bool:
    """A trailing one/two-digit comma group is a decimal comma ("0,37%" printed for 0.37%), never a thousand group:
    no number is written with a comma before exactly two final digits."""
    return bool(re.search(r",\d{1,2}[\"'’]?$", num.strip("()")))


def _whole_printed(text: str, num: str) -> bool:
    """The token as printed, bounded by characters that cannot continue a number: "791.0" inside "7,791.02" is a
    fragment of another value, and a token the page never prints whole is not a table value."""
    t = num.strip("()")
    return bool(t) and bool(re.search(r"(?<![\d,.])" + re.escape(t) + r"(?![\d,.])", text))


@dataclass
class Val:
    value: float
    unit: str | None       # canonical unit or None when only a bare number
    start: int
    end: int
    raw: str
    cur: str | None = None


def _norm_cur(c: str | None) -> str | None:
    if not c:
        return None
    c = c.lower().strip()
    if c in ("₹", "`", "rs", "rs.", "inr"):
        return "inr"
    if c in ("$", "us$", "usd"):
        return "usd"
    return c


def value_unit(v_cur: str | None, suf: str | None, kind: str, default_unit: str) -> str | None:
    """Canonical unit for a matched token under a metric kind, or None when the token cannot be this kind."""
    cur = _norm_cur(v_cur)
    s = (suf or "").lower().strip().rstrip(".")
    base = _UNIT_BY_SUFFIX.get(s)
    if default_unit == "usd_mn" and base == "bn":
        return None      # a USD-million metric keeps the printed value, so a "$4.8 billion" row would break its quote
    if kind == "money":
        if profile.under_profile() and default_unit.startswith("usd") and (cur == "inr" or base == "inr_cr"):
            return None                      # a rupee figure never fills a US-dollar metric (profile builds only)
        if base == "inr_cr" or (cur == "inr" and base in (None, "inr_cr")):
            return "inr_cr" if (base == "inr_cr" or default_unit == "inr_cr") and cur != "usd" else None
        if cur == "inr":                     # a rupee figure never fills a US-dollar metric
            if default_unit.startswith("usd"):
                return None
            return {"mn": "inr_mn", "bn": "inr_bn", "tn": "inr_tn"}.get(base)
        if cur == "usd" or (cur is None and default_unit.startswith("usd") and base in ("mn", "bn")):
            if base == "bn":
                return "usd_bn"
            if base == "mn":
                return "usd_mn"
            return None
        return None
    if kind == "pct":
        return "pct" if base == "pct" else None
    if kind == "bps":
        return "bps" if base == "bps" else ("pct_as_bps" if base == "pct" else None)
    if kind == "volume":
        if base in ("kt", "tonnes", "mt"):
            return {"kt": "kt", "tonnes": "tonnes", "mt": "mt"}[base]
        return None
    if kind == "per_tonne":
        return "usd_per_tonne" if cur == "usd" or base in (None, "tonnes") else None
    if kind == "count":
        if base in ("mn", "inr_cr", None) and cur is None:
            return {"mn": "count_mn", "inr_cr": "count_cr", None: "count"}[base]
        return None
    if kind == "ratio":
        return "x" if base == "x" else None
    if kind == "num":        # a bare ratio printed without a suffix (solvency ratio 1.97)
        return "x" if base in (None, "x") and cur is None else None
    if kind == "days":
        return "days" if base == "days" else None
    return None


def _value_matches(s: str):
    """VAL_RX hits that are whole tokens: "2" inside "2W" or "B2C" is part of a word, not a table value."""
    for m in VAL_RX.finditer(s):
        a, b = m.start("num"), m.end("num")
        if a > 0 and (s[a - 1].isalnum() or s[a - 1] in ".,-"):
            continue
        if b < len(s) and s[b].isalpha():
            continue
        yield m


def find_values(text: str, kind: str, default_unit: str, start: int, end: int, skip: list[tuple[int, int]]):
    """Values of the wanted kind inside text[start:end] in order, skipping period spans."""
    out = []
    for m in VAL_RX.finditer(text, start, end):
        if any(a <= m.start("num") < b for a, b in skip):
            continue
        num = to_float(m.group("num"))
        if num is None:
            continue
        unit = value_unit(m.group("cur"), m.group("suf"), kind, default_unit)
        if unit is None:
            continue
        out.append(Val(num, unit, m.start(), m.end(), m.group(0).strip(), _norm_cur(m.group("cur"))))
    return out


# ---------------------------------------------------------------- lexicon
@dataclass
class Entry:
    metric: str
    kind: str
    unit: str
    labels: list[re.Pattern]
    neg: re.Pattern | None
    companies: list[str] | None
    family: str = ""
    generic: list[bool] = field(default_factory=list)   # per label: a bare one-word label (margin, revenue, ebitda ...)
    sectors: list[str] | None = None    # file key `sectors`: the entry applies only to companies of these sectors (profile build)
    no_profile: bool = False            # file key `no_profile`: with no profile (the pilot3 three) the family still applies
    labels_strict: list[re.Pattern] = field(default_factory=list)  # file key `strict` (per entry): sentence-path labels
    #                                    that require the value right after the label; tables keep the plain `labels`
    max_pct: float = 100.0              # file key `max_pct`: highest value a pct entry may store (a rate can exceed 100)


@dataclass
class Dim:
    dimension: str
    patterns: list[re.Pattern]
    companies: list[str] | None


def _rx(p: str) -> re.Pattern:
    # literal spaces in the lexicon may be a line break in the page text
    return re.compile(p.replace(" ", r"\s+"), re.I)


GENERIC_WORDS = {"margin", "margins", "revenue", "ebitda", "sales", "pat", "production", "shipments", "shipment"}


def is_generic_label(src: str) -> bool:
    """True for a label pattern that is one bare word of GENERIC_WORDS (anchors, word boundaries and a trailing
    optional s or star are ignored)."""
    w = re.sub(r"\^|\\b|\\\*|\?|\$", "", src).strip().lower()
    return w in GENERIC_WORDS


def load_lexicon() -> tuple[list[Entry], list[Dim]]:
    entries, dims = [], []
    for f in sorted(LEX_DIR.glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        if "entries" in d:
            for e in d["entries"]:
                entries.append(Entry(e["metric"], e["kind"], e["unit"], [_rx(x) for x in e["labels"]],
                                     _rx(e["neg"]) if e.get("neg") else None, e.get("companies"), d.get("family", f.stem),
                                     [is_generic_label(x) for x in e["labels"]], d.get("sectors"), bool(d.get("no_profile")),
                                     [_rx(x) for x in e.get("strict") or []], float(e.get("max_pct", 100.0))))
        if "dimensions" in d:
            for e in d["dimensions"]:
                dims.append(Dim(e["dimension"], [_rx(x) for x in e["patterns"]], e.get("companies")))
    return entries, dims


def _sector_of(company: str) -> str | None:
    """Sector of a profile company; None without a profile (the pilot3 three: every family applies, as before)."""
    prof = profile.active()
    if prof is None:
        return None
    try:
        return prof.company(company).sector or None
    except KeyError:
        return None


def label_matches(entries: list[Entry], company: str, text: str):
    """[(entry, match)] for entries whose label hits text and neg does not. First hit per metric."""
    res = []
    sector = _sector_of(company)
    for e in entries:
        if e.companies and company not in e.companies:
            continue
        if e.sectors and (sector not in e.sectors if sector is not None else not e.no_profile):
            continue
        for rx in e.labels:
            m = rx.search(text)
            if m:
                lo = max(0, m.start() - 10)
                if e.neg and e.neg.search(text[lo:m.end() + 14]):
                    continue
                res.append((e, m))
                break
    return res


_SENT_END = re.compile(r"[.!?](?=\s+[A-Z0-9(])")


def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    """Start and end of the sentence holding ``pos`` (a full stop before a capital or digit, or a blank line)."""
    start = 0
    for m in _SENT_END.finditer(text, 0, pos):
        start = m.end()
    blank = text.rfind("\n\n", 0, pos)
    if blank >= 0:
        start = max(start, blank)
    m = _SENT_END.search(text, pos)
    end = m.start() + 1 if m else len(text)
    blank = text.find("\n\n", pos)
    if blank >= 0:
        end = min(end, blank)
    return start, end


def find_dimension(dims: list[Dim], company: str, text: str, pos: int, window: int = 90) -> str:
    """Dimension word nearest before pos (within window), else nearest after within 40 chars, else total.

    The word must sit in the same sentence: a segment named in an earlier sentence describes something else
    (a 36,267 total order book was tagged T&D off the previous sentence's "T&D business").  A figure stated as a
    share of the whole ("63% of our unexecuted order book") keeps the segment the paragraph has been about, so
    that one may look back up to 400 chars."""
    lo_s, hi_s = _sentence_bounds(text, pos)

    def nearest(a: int, b: int):
        best, best_d = None, 10 ** 9
        seg = text[a:b]
        for d in dims:
            if d.companies and company not in d.companies:
                continue
            for rx in d.patterns:
                for m in rx.finditer(seg):
                    p = a + m.start()
                    if text[max(0, p - 4):p].lower() == "kec ":     # the company name "KEC International Limited"
                        continue
                    dist = (pos - (a + m.end())) if a + m.end() <= pos else (a + m.start() - pos) + 15
                    if dist < best_d:
                        best, best_d = d.dimension, dist
        return best

    best = nearest(max(lo_s, pos - 260), min(hi_s, pos + 40))
    if best is None and re.search(r"\d+(?:\.\d+)?\s*%\s*of\b", text[lo_s:hi_s], re.I):
        best = nearest(max(0, pos - 400), pos)
    return best or "total"


# ---------------------------------------------------------------- output rows
@dataclass
class Row:
    metric: str
    dimension: str
    value: float
    unit: str
    scale: float
    period_type: str
    fiscal_period: str
    as_of: str | None
    basis: str
    page: int
    quote: str
    raw_label: str
    raw_value: str
    rule: str


_PAGE_UNIT_RX = re.compile(r"(?:₹|`|rs\.?|inr)\s*(?:in\s+|\()?\s*(billion|bn|million|mn|mm)\b"
                           r"|\(\s*(?:in\s+)?(billion|bn|million|mn|mm)\s*\)", re.I)


def page_money_unit(text: str) -> str | None:
    """inr_bn / inr_mn when the page declares one such unit for its rupee table ("(₹ in billion)"), else None.
    The currency glyph is often lost from the text layer ("( in billion)"), so a parenthetical unit note counts too.
    Two different declarations on a page: None (ambiguous)."""
    found = set()
    for m in _PAGE_UNIT_RX.finditer(text):
        u = (m.group(1) or m.group(2) or "").lower()
        found.add("inr_bn" if u in ("billion", "bn") else "inr_mn")
    return found.pop() if len(found) == 1 else None


def finalize_unit(unit: str, value: float, metric_default: str):
    """-> (value, unit, scale)."""
    if unit == "inr_cr":
        return value, "inr_cr", 1e7
    if unit == "usd_mn":
        return value, "usd_mn", 1e6
    if unit == "usd_bn":
        return value * 1000.0, "usd_mn", 1e6   # normalised to million dollars
    if unit == "inr_bn":
        return value, "inr_bn", 1e9
    if unit == "inr_mn":
        return value, "inr_mn", 1e6
    if unit == "inr_tn":                    # 1 trillion = 1 lakh crore
        return value * 1e5, "inr_cr", 1e7
    if unit == "pct_as_bps":
        return value * 100.0, "bps", 1.0
    if unit == "kt":
        return value, "kt", 1e3
    if unit == "mt":
        return value * 1000.0, "kt", 1e3        # million tonnes -> kt
    if unit == "tonnes":
        return value, "tonnes", 1.0
    if unit == "count_mn":
        return value, "count_mn", 1e6
    if unit == "count_cr":
        return value, "count_cr", 1e7
    return value, unit, 1.0


def _page_unit_canon(unit: str | None, raw: str, e: Entry, text: str) -> str | None:
    """A bare rupee figure on a page that declares its table unit ("₹ In billion") keeps that unit: the label
    fallback reads every rupee token as crore, which stored SBILIFE's 1,012.9 bn premium as crore."""
    if not profile.under_profile() or e.kind != "money" or unit != "inr_cr":
        return unit
    if re.search(r"crore|\bcr\b|lakh", raw or "", re.I):
        return unit
    pu = page_money_unit(text)
    return pu if pu in ("inr_bn", "inr_mn") else unit


def page_basis(text: str) -> str:
    """Entity the page reports, from its heading: 'consolidated', 'standalone', or the subsidiary it names ('bhfl').

    A BAJFINANCE deck prints one entity per summary page ("Financial summary – Bajaj Housing Finance",
    "Business segment wise AUM - Consolidated", "Executive summary – Bajaj Finance"), and a BHFL results page says
    "Summary of standalone financial results of Bajaj Housing Finance Limited"; that heading decides, so a
    subsidiary's AUM is not stored as the consolidated 'total' with basis not_stated.  Any other page keeps the old
    count rule (consolidated / standalone mentioned, one of them)."""
    for ln in [ln.strip() for ln in text.splitlines() if ln.strip()][:6]:
        low = ln.lower()
        if not re.search(r"summary|aum|snapshot|wise|financial results", low):
            continue
        if "bajaj housing" in low or re.search(r"\bbhfl\b", low):
            return "bhfl"
        if "bajaj finance" in low:
            return "standalone"
        if re.search(r"\bstandalone\b", low):
            return "standalone"
        if "consolidated" in low:
            return "consolidated"
    c = len(re.findall(r"consolidated", text, re.I))
    s = len(re.findall(r"standalone", text, re.I))
    if c and not s:
        return "consolidated"
    if s and not c:
        return "standalone"
    return "not_stated"


def span_quote(text: str, parts: list[str], start: int = 0, maxspan: int = 360):
    """Literal slice of text from first part to the end of the last part, parts found in order."""
    pos, first = start, None
    last_end = None
    for p in parts:
        i = text.find(p, pos)
        if i < 0:
            return None
        if first is None:
            first = i
        pos = i + len(p)
        last_end = pos
    if last_end is None or last_end - first > maxspan:
        return None
    return text[first:last_end]


# ---------------------------------------------------------------- sentence rule
VS_RX = re.compile(r"\b(?:v/?s\.?|versus|against|as against|compared (?:to|with)|from|up from|down from|vs)\b", re.I)


_PRIOR_YR = re.compile(r"(?:last|previous|prior|preceding|corresponding)\s+(?:year|fiscal|quarter|period)"
                       r"|year[- ]ago|compared|versus|\bvs\b|vis-à-vis", re.I)


def doc_default_period(texts: list[str]) -> list[Period]:
    """Reporting-period hint from the first pages of a document: the quarter/year-ended headline.

    The title page wins over a comparison mentioned later: the KEC Q4 FY26 call says "recognized last year in
    FY '25" on page 3, which used to become the default period of every unlabelled figure (the 36,267 crore
    order book was stored FY25). A Q4 document is the annual-results one, so its unlabelled figures default to
    the fiscal year (FY26), not to Q4FY26: decks and calls state "Q4 FY26" on the figures that are quarterly."""
    for n in (1, 2, 3):
        head = " \n".join(texts[:n])
        ps = [p for p in parse_periods(head)
              if not _PRIOR_YR.search(head[max(0, p.start - 40):p.start])]
        if not ps:
            continue
        pref = [p for p in ps if re.search(r"(ended|quarter|results|performance|year|call)",
                                           head[max(0, p.start - 40):p.start], re.I)]
        p = (pref or ps)[0]
        if p.ptype == "Q" and p.canon.startswith("Q4"):
            return [Period(p.start, p.end, f"FY{p.canon[-2:]}", "FY", p.as_of)]
        return [p]
    return []


_BREAK = re.compile(r"[.;]\s+[A-Z]|\n\s*\n")


def _pair_before(text, pers, pos):
    """Last 'A v/s B' period pair that ends before pos and lies within 1500 chars of it."""
    best = None
    for a, b in zip(pers, pers[1:]):
        if b.end <= pos and pos - b.end < 1500 and re.fullmatch(r"\s*(v/?s\.?|vs\.?|versus|against|as against)\s*", text[a.end:b.start], re.I):
            best = (a, b)
    return best


BY_RX = re.compile(r"\b(?:reduc|increas|decreas|declin|improv|grew|grow|rose|fell|expan|add|lower|higher|up|down)\w*\b[^.]{0,30}\bby\s*"
                   r"(?:over|more than|about|around|nearly|approximately|~)?\s*(?:₹|`|rs\.?|inr|us\$|usd|\$)?\s*$", re.I)
TO_RX = re.compile(r"\bto\s*(?:₹|`|rs\.?|inr|us\$|usd|\$)?\s*$", re.I)
_LEVEL_RX = re.compile(r"\b(?:to|at)\s*(?:end|close|stand|reach)?\s*(?:at|of)?\s*(?:₹|`|rs\.?|inr|us\$|usd|\$)?\s*$", re.I)
FROM_RX = re.compile(r"\bfrom\s*(?:₹|`|rs\.?|inr|us\$|usd|\$)?\s*$", re.I)
_OTHER_SUBJECT = re.compile(r"\b(?:impacted by|impact of|on account of|charge of|hit of)\b", re.I)
_OTHER_SUBJECT_PROFILE = re.compile(r"\b(?:driven by|owing to|because of|on the back of|supported by|partly offset|"
                                    r"partially offset|due to)\b", re.I)
_NOT_A_LEVEL = re.compile(r"\bis an?\s*(?:₹|`|rs\.?|inr|us\$|usd|\$)?\s*$", re.I)   # "is an $18 million [impact]"
_THRESHOLD = re.compile(r"\b(?:larger|more|greater|fewer|less|higher|lower|over|above|below|under)\s+than\s*"
                        r"(?:₹|`|rs\.?|inr|us\$|usd|\$)?\s*$", re.I)     # "larger than $50 mn" is a client threshold
_CLIENT_TIER = re.compile(r"\s*(?:mn|million|bn|billion)?\s*plus\s+(?:clients|customers)", re.I)  # "$50 mn plus clients"
_FORWARD = re.compile(r"\b(?:target(?:ed|s)?|guidance|guided|expect(?:s|ed)?|will|would|projected|projection|outlook|"
                      r"range of|falling below|fall below|decline below|drop below|by FY\s?'?\d{2}|"
                      r"regulatory requirement|minimum|mandated)\b", re.I)
_PRIOR_VALUE = re.compile(r"\b(?:last|previous|prior|preceding|corresponding)\s+(?:year|fiscal|quarter|period)\b"
                          r"[^.]{0,40}?\b(?:was|were|at|stood|had)\b|\byear[- ]ago\b", re.I)


def _second_of_pair(text: str, start: int, v2_end: int, entries, company: str, metric: str) -> bool:
    """True when the label at `start` is the second of "<other label> and <this label> ... a and b respectively"."""
    before = text[max(0, start - 40):start]
    if not re.search(r"(?:\band\b|&)\s*$", before, re.I):
        return False
    if not re.search(r"respectively", text[v2_end:v2_end + 25], re.I):
        return False
    head = re.sub(r"(?:\band\b|&)\s*$", "", before, flags=re.I)
    return any(e.metric != metric for e, _ in label_matches(entries, company, head[-30:]))


_STOCK_METRICS = {"aum", "order_book", "order_book_l1", "net_debt", "net_debt_incl_acceptances", "deposits",
                  "customer_franchise", "loan_loss_provisions"}


def _q4_twin(e: Entry, period: Period) -> Period | None:
    """A stock figure dated 31 March is the year-end and also the Q4 point: GNPA at "31 March 2025" must answer
    both FY25 and Q4FY25 (the hand-read grade's quarterly GNPA trend was missing Q4 FY25).  A flow (revenue, PAT)
    is annual only."""
    if period.ptype == "FY" and period.as_of and period.as_of.endswith("-03-31") \
            and (e.kind in ("pct", "x", "days", "bps") or e.metric in _STOCK_METRICS):
        return Period(period.start, period.end, "Q4" + period.canon, "Q", period.as_of)
    return None


def sentence_rows(text: str, page: int, company: str, entries, dims, default_pers: list[Period]) -> list[Row]:
    rows: list[Row] = []
    pers = parse_periods(text)
    per_spans = [(p.start, p.end) for p in pers]
    basis = page_basis(text)
    for e, lm in label_matches(entries, company, text):
        # every occurrence of any label of the entry; `strict` labels (sentence-only) demand the value right after
        strict = e.labels_strict
        for li, rx in enumerate(strict or e.labels):
            generic = not strict and li < len(e.generic) and e.generic[li]
            for m in rx.finditer(text):
                lo = max(0, m.start() - 10)
                if e.neg and e.neg.search(text[lo:m.end() + 14]):
                    continue
                # stop the window at a paragraph break or sentence end of >1 sentence
                wend = min(len(text), m.end() + 170)
                brk = text.find("\n\n", m.end(), wend)
                if brk > 0:
                    wend = brk
                vals = find_values(text, e.kind, e.unit, m.end(), wend, per_spans)
                if not vals:
                    continue
                v1 = vals[0]
                if v1.start - m.end() > 120:
                    continue
                gap = text[m.end():v1.start]
                if "\n" in gap and label_matches(entries, company, gap):
                    continue      # a fact-sheet block: another label sits between this one and its value
                lead = text[m.start():v1.start] if e.labels_strict else gap   # a strict label swallows the words between
                if _OTHER_SUBJECT.search(lead) or _NOT_A_LEVEL.search(lead) \
                        or (profile.under_profile() and _OTHER_SUBJECT_PROFILE.search(lead)):
                    continue      # "impacted by an estimated negative $104 million": not the level
                if _THRESHOLD.search(lead) or _CLIENT_TIER.match(text[v1.end:v1.end + 24]):
                    continue      # a client-size threshold ("$50 mn plus clients") is not the metric
                if profile.under_profile() and (
                        _FORWARD.search(lead) or _PRIOR_VALUE.search(lead)
                        or gap.count("\n") > 2 or re.search(r"\n\s*\n", gap)
                        or v1.start > _sentence_bounds(text, m.start())[1]
                        or re.match(r"\s*[-–—]\s*\d", text[v1.end:v1.end + 12])):
                    # guidance wording, the prior year's value, a fact-sheet column, a footnote's figure,
                    # or a range band ("0.9%-1.5%") - profile builds only, so the pilot3 pages do not move
                    continue
                if FROM_RX.search(lead):
                    to_v = find_values(text, e.kind, e.unit, v1.end, min(len(text), v1.end + 24), per_spans)
                    if not (to_v and re.fullmatch(r"\s*to\s*", text[v1.end:to_v[0].start], re.I)):
                        continue  # "increased from 8.1% to 8.4%": the current value is the one after "to"
                    v1 = to_v[0]
                elif BY_RX.search(lead):     # "reduced by INR150 crores to INR6,568 crores": 150 is a change
                    lvl = next((v for v in vals[1:] if _LEVEL_RX.search(text[max(m.end(), v.start - 6):v.start])), None)
                    if lvl is None:
                        continue
                    v1 = lvl
                elif VS_RX.search(text[max(0, v1.start - 14):v1.start]):
                    continue      # "was 67 days ... compared to 69 days": the token after the link is the old value
                    lvl = next((v for v in vals[1:] if TO_RX.search(text[max(m.end(), v.start - 6):v.start])), None)
                    if lvl is None:
                        continue
                    v1 = lvl
                if e.kind == "days" and v1.value < 1:
                    continue              # "long term debt to working capital ratio 0.19" is a ratio, not a day count
                elif len(vals) >= 2 and _second_of_pair(text, m.start(), vals[1].end, entries, company, e.metric):
                    v1 = vals[1]                              # "GNPA and NNPA at 0.96% and 0.39% respectively"
                items: list[tuple] = [(v1, None)]
                # comparative second value
                tail = text[v1.end:min(len(text), v1.end + 90)]
                vm = VS_RX.search(tail)
                if vm and vm.start() < 60:
                    v2s = find_values(text, e.kind, e.unit, v1.end + vm.end(), min(len(text), v1.end + 90), per_spans)
                    if v2s and v2s[0].start - (v1.end + vm.end()) < 14:
                        items.append((v2s[0], vm))
                dim = find_dimension(dims, company, text, m.start())
                first_canon = None
                for idx, (v, _) in enumerate(items):
                    # period: same-sentence mention after the value (<=45 chars), else before the label (<=60),
                    # else the nearest earlier "A v/s B" header pair, else the document's reporting period
                    rule = "sentence_v1"
                    cand = [p for p in pers if 0 <= p.start - v.end <= 45 and not _BREAK.search(text[v.end:p.start])
                            and (idx == len(items) - 1 or p.start < items[idx + 1][0].start)]
                    if not cand:
                        cand = [p for p in pers if 0 <= m.start() - p.end <= 60 and '\n' not in text[p.end:m.start()]]
                        cand = cand[-1:]
                    if not cand:   # "GNPA ... as of 30 September 2025 stood at 1.24%": the date is before the value
                        cand = [p for p in pers if m.end() <= p.start and p.end <= v.start][-1:]
                    period = cand[0] if cand else None
                    if period is None:
                        pair = _pair_before(text, pers, m.start())
                        if pair:
                            period, rule = pair[min(idx, 1)], "sentence_pair_v1"
                    if period is None and idx == 0 and default_pers:
                        period, rule = default_pers[0], "sentence_default_v1"
                    if period is None:
                        continue
                    if idx and period.canon == first_canon:
                        continue        # the comparative restates the current period: the same value, not a prior one
                    if generic and rule != "sentence_v1":   # a bare "margin" / "revenue" needs its own period in the sentence
                        continue
                    val, unit, scale = finalize_unit(_page_unit_canon(v.unit, v.raw, e, text) or v.unit, v.value, e.unit)
                    end = v.end if period.start < v.end else period.end
                    end = max(end, period.end if 0 <= period.start - v.end <= 45 else v.end)
                    q = text[m.start():end]
                    if len(q) > 300:
                        q = text[max(m.start(), v.start - 120):end]
                    if q not in text:
                        continue
                    rows.append(Row(e.metric, dim, val, unit, scale, period.ptype, period.canon, period.as_of, basis,
                                    page, q, text[m.start():m.end()], v.raw, rule))
                    if idx == 0:
                        first_canon = period.canon
                    twin = _q4_twin(e, period)
                    if twin:
                        rows.append(Row(e.metric, dim, val, unit, scale, twin.ptype, twin.canon, twin.as_of, basis,
                                        page, q, text[m.start():m.end()], v.raw, rule))
    return rows


# ---------------------------------------------------------------- word-position rules
@dataclass
class WRow:
    y: float
    toks: list = field(default_factory=list)   # (x0, x1, text)
    y0: float = 0.0                            # y of the first word, used for clustering

    def text(self):
        return " ".join(t[2] for t in sorted(self.toks))


def page_rows(words) -> list[WRow]:
    ws = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows: list[WRow] = []
    for w in ws:
        yc = (w[1] + w[3]) / 2
        if rows and abs(rows[-1].y0 - yc) <= 8.0:
            r = rows[-1]
            r.toks.append((w[0], w[2], w[4]))
            r.y = (r.y * (len(r.toks) - 1) + yc) / len(r.toks)
        else:
            rows.append(WRow(yc, [(w[0], w[2], w[4])], yc))
    for r in rows:
        r.toks.sort()
    return rows


def _row_string(r: WRow):
    s, spans = "", []
    for x0, x1, t in r.toks:
        if s:
            s += " "
        spans.append((len(s), len(s) + len(t), x0, x1))
        s += t
    return s, spans


def _x_of(spans, a, b):
    xs = [(x0, x1) for (s, e, x0, x1) in spans if s < b and e > a]
    if not xs:
        return None
    return (min(x[0] for x in xs) + max(x[1] for x in xs)) / 2


def row_periods(r: WRow):
    s, spans = _row_string(r)
    out = []
    for p in parse_periods(s):
        xc = _x_of(spans, p.start, p.end)
        if xc is not None:
            out.append((xc, p))
    return s, spans, out


def _anchored_quote(text: str, label: str, num: str, nth: int, maxgap: int = 170):
    """Literal slice from the nth occurrence of a label anchor to the value string that follows it."""
    for anchor in _label_anchors(text, label):
        occ = [m.start() for m in re.finditer(re.escape(anchor), text)]
        if not occ:
            continue
        order = [occ[nth]] + [o for k, o in enumerate(occ) if k != nth] if nth < len(occ) else occ
        for o in order:
            j = text.find(num, o + len(anchor))
            if 0 <= j and j - (o + len(anchor)) <= maxgap:
                nxt = text.find(anchor, o + len(anchor))     # value must come before the next copy of the same label
                if nxt < 0 or j < nxt:
                    return text[o:j + len(num)]
    return None


_PROSE_ROW = re.compile(r"\b(?:stood|stands?|was|were|grew|grow|increased|decreased|rose|fell|amounted|reported|"
                        r"respectively|compared|against|improved|declined)\b", re.I)
_PCT_LINE = re.compile(r"^\s*(?:\d{1,3}(?:\.\d+)?%\s*)+$")
_PCT_NUM = re.compile(r"(\d{1,3}(?:\.\d+)?)%")
_REV_LINE = re.compile(r"revenues?\b[^\n]{0,50}?(?:rs\.?|₹|inr)\s*(?P<num>[\d,]+(?:\.\d+)?)\s*(?:cr\b|crores?)", re.I)


def _label_dim(label: str, dims: list[Dim], company: str) -> str | None:
    """Dimension the whole row label names ("Mortgages", "Cables & Conductors", "Others"), else None."""
    t = " ".join(label.split())
    if re.fullmatch(r"other[s]?", t, re.I):
        return "others"
    for d in dims:
        if d.companies and company not in d.companies:
            continue
        for rx in d.patterns:
            if rx.search(t):
                return d.dimension
    return None


def _heading_dim(line: str, nxt: str, dims: list[Dim], company: str) -> tuple[str | None, int]:
    """(dimension, lines consumed) of a heading line; a legend entry may wrap ("Cables &" / "Conductors").
    A two-line entry is tried first, so the wrap is one entry, not "cables" plus a stray "Conductors"."""
    def full(t: str) -> str | None:
        t = " ".join(t.split())
        if re.fullmatch(r"other[s]?", t, re.I):
            return "others"
        for d in dims:
            if d.companies and company not in d.companies:
                continue
            for rx in d.patterns:
                if rx.fullmatch(t):
                    return d.dimension
        return None

    if nxt and len((line + " " + nxt).split()) <= 5 and not re.search(r"\d", line + nxt):
        d = full(line + " " + nxt)
        if d:
            return d, 2
    if len(line.split()) <= 4 and not re.search(r"\d", line):
        d = full(line)
        if d:
            return d, 1
    return None, 1


def _mix_title(rows, hi: int, entries, company):
    """(entry, title, unit) of the table title just above header row `hi` ("Business segment wise AUM - Consolidated"):
    a short row that names a lexicon metric and a unit, and carries no period of its own."""
    cand = []
    for j, r in enumerate(rows):
        dy = rows[hi].y - r.y
        if not (4 <= dy <= 175):
            continue
        s, _ = _row_string(r)
        if len(s) > 70 or parse_periods(s) or _PROSE_ROW.search(s):
            continue
        hit = label_matches(entries, company, s)
        if not hit:
            continue
        e = hit[0][0]
        hint = _unit_from_label(s, e) if e.kind == "money" else e.unit
        if hint is None:
            continue
        cand.append((dy, e, s, hint))
    if not cand:
        return None
    _, e, s, hint = min(cand, key=lambda c: c[0])
    return e, s, hint


_ENTITY_WORDS = {"consolidated": "consolidated", "standalone": "standalone", "bfl": "standalone", "bhfl": "bhfl"}


def _column_entities(rows, hi: int) -> list[tuple[float, str]]:
    """(x centre, entity) from the heading band above a period header ("Consolidated | BFL | BHFL | Consolidated")."""
    top = rows[hi].y
    out = []
    for r in rows:
        if not (top - 75 <= r.y <= top - 2):
            continue
        for x0, x1, tok in r.toks:
            ent = _ENTITY_WORDS.get(tok.strip().lower())
            if ent:
                out.append(((x0 + x1) / 2, ent))
    return out


def mix_rows(rows, info, headers, text: str, page: int, company: str, entries, dims, basis, default_pers) -> list[Row]:
    """Segment-mix table: a title naming a metric (AUM, order book ...) over rows that are segment names, one value
    column per period ("Business segment wise AUM - Consolidated": 13 segment lines and a Total).  Each line is a row
    with the segment as dimension and the total as 'total' (T-049: "the deck table has it" was answered "not held")."""
    if not headers:
        return []
    hy = headers[0]
    title = _mix_title(rows, hy, entries, company)
    if title is None:
        return []
    e, tlabel, unit_hint = title
    cols = info[hy][2]
    ents = _column_entities(rows, hy)

    def col_entity(x: float) -> str | None:
        near = [(abs(xc - x), ent) for xc, ent in ents if abs(xc - x) <= 55]
        return min(near)[1] if near else None

    def rank(i: int):
        per = cols[i][1]
        y = int(per.canon[-2:])
        q = int(per.canon[1]) if per.canon[1:2].isdigit() else 5
        ent = col_entity(cols[i][0])
        pref = 0 if ent == basis or ent is None else 1
        return (y, q, -pref)

    tgt = max(range(len(cols)), key=rank)
    tx, tper = cols[tgt]
    tgt_ent = col_entity(tx) or basis
    segs, total, total_q4 = [], None, None
    for i, r in enumerate(rows):
        if i in headers or rows[i].y <= rows[hy].y:
            continue
        s, spans = _row_string(r)
        nums = [(_x_of(spans, m.start(), m.end()), m) for m in _value_matches(s)]
        nums = [(x, m) for x, m in nums if x is not None]
        if not nums:
            continue
        label = s[:nums[0][1].start()].strip()
        dim = _label_dim(label, dims, company)
        if dim is None and not re.fullmatch(r"total", label, re.I):
            continue
        near = [(abs(x - tx), m) for x, m in nums if abs(x - tx) <= 28]
        if not near:
            continue
        m = min(near, key=lambda t: t[0])[1]
        num = to_float(m.group("num"))
        unit = value_unit(m.group("cur"), m.group("suf"), e.kind, e.unit)
        if unit is None and not (m.group("suf") or "").strip():
            unit = _unit_from_label(tlabel, e) or unit_hint
        if unit is None or num is None:
            continue
        val, u, scale = finalize_unit(unit, num, e.unit)
        nth = sum(1 for k in range(i) if _row_string(rows[k])[0].startswith(label))
        q = _anchored_quote(text, label, m.group("num"), nth)
        if not q:
            continue
        row = Row(e.metric, "total" if dim is None else dim, val, u, scale, tper.ptype, tper.canon, tper.as_of,
                  tgt_ent, page, q, tlabel, m.group("num"), "mix_v1")
        twin = _q4_twin(e, tper)
        if dim is None:
            total = row
        else:
            segs.append(row)
        if twin:   # a year-end mix is also its Q4 point (AUM at 31 Mar 2026 answers Q4FY26 too)
            t = Row(row.metric, row.dimension, row.value, row.unit, row.scale, twin.ptype, twin.canon, twin.as_of,
                    tgt_ent, page, q, tlabel, m.group("num"), "mix_v1")
            if dim is None:
                total_q4 = t
            else:
                segs.append(t)
        else:
            total_q4 = None
    if len(segs) < 3:     # a table of sub-lines (mortgage products) is not the segment mix
        return []
    return segs + ([total] if total else []) + ([total_q4] if total_q4 else [])


def _text_offsets(lines: list[str]) -> list[int]:
    offs, n = [], 0
    for ln in lines:
        offs.append(n)
        n += len(ln) + 1
    return offs


def _legend(lines: list[str], dims, company):
    """(dimensions, first line, last line) of the chart legend: the last run of >=3 lines that are segment names."""
    best = None
    i = 0
    while i < len(lines):
        got, j = [], i
        while j < len(lines):
            nxt = lines[j + 1].strip() if j + 1 < len(lines) else ""
            d, used = _heading_dim(lines[j].strip(), nxt, dims, company)
            if d is None:
                break
            got.append(d)
            j += used
        if len(got) >= 3:
            best = (got, i, j - 1)
        i = max(j, i + 1)
    return best


def pie_mix_rows(text: str, page: int, company: str, entries, dims, basis: str, default_pers) -> list[Row]:
    """Donut-chart mix: the chart's percentages sit in one contiguous run of lines, its legend in another, its title
    ("Order Book – 31 Mar'26") between or beside them.  Paired in printed order, so the 63/27/7/2/1 order book mix is
    stored (T-049: "says split not quotable")."""
    lines = text.split("\n")
    offs = _text_offsets(lines)
    legend = _legend(lines, dims, company)
    if legend is None:
        return []
    ddims, lstart, lend = legend
    runs, i = [], 0
    while i < len(lines):
        if _PCT_LINE.match(lines[i]):
            j, nums = i, []
            while j < len(lines) and _PCT_LINE.match(lines[j]):
                nums += [float(x) for x in _PCT_NUM.findall(lines[j])]
                j += 1
            runs.append((i, j - 1, nums))
            i = j
        else:
            i += 1
    out = []
    for t, ln in enumerate(lines):
        if t >= lstart:
            break
        if re.search(r"[✓•●▪]", ln):
            continue
        ps = parse_periods(ln)
        rest = ln
        for p in sorted(ps, key=lambda p: -p.start):
            rest = rest[:p.start] + " " + rest[p.end:]
        if not ps or re.search(r"\d{3,}", rest) or re.search(r"[₹`]|\brs\b|\binr\b", rest, re.I) or len(rest.split()) > 8:
            continue                 # a chart title is short and has no figure of its own
        hit = (label_matches(entries, company, rest) or [None])[0]
        if not hit:
            continue
        e = hit[0]

        def other_title(a: int, b: int) -> bool:
            """Another chart's title between this title and the run: the run belongs to that chart."""
            return any(label_matches(entries, company, lines[k]) for k in range(a, b) if lines[k].strip())

        near = [(abs(t - end) if end < t else abs(start - t), start, end, nums)
                for start, end, nums in runs
                if (end < t and not other_title(end + 1, t)) or (start > t and not other_title(t + 1, start))]
        near = [(d, start, end, nums) for d, start, end, nums in near
                if len(nums) == len(ddims) and abs(sum(nums) - 100.0) <= 1.0]
        if not near:
            continue
        d, start, end, nums = min(near)
        per = ps[0]
        a, b = (offs[start], offs[t] + len(lines[t])) if end < t else (offs[t], offs[end] + len(lines[end]))
        q = text[a:b]
        if q not in text:
            continue
        for k, dim in enumerate(ddims):
            out.append(Row(f"{e.metric}_mix_pct", dim, nums[k], "pct", 1.0, per.ptype, per.canon, per.as_of, basis,
                           page, q, ln.strip(), f"{nums[k]:g}%", "chart_v1"))
    return out


def segment_revenue_rows(text: str, page: int, company: str, entries, dims, basis: str, default_pers) -> list[Row]:
    """A business-wise revenue bullet block whose segment heading follows it ("Revenues of Rs. 15,883 Cr" ... "T&D"):
    one revenue row per business, so the revenue mix is stored with its segments (KEC FY26: T&D 15,883, Civil 3,823)."""
    if not default_pers:
        return []
    lines = text.split("\n")
    offs = _text_offsets(lines)
    out = []
    for i, ln in enumerate(lines):
        m = _REV_LINE.search(ln)
        if not m:
            continue
        num = to_float(m.group("num"))
        if num is None:
            continue
        dim, qend = None, -1
        for j in range(i + 1, min(len(lines), i + 14)):
            nxt = lines[j + 1].strip() if j + 1 < len(lines) else ""
            d, used = _heading_dim(lines[j].strip(), nxt, dims, company)
            if d:
                dim, qend = d, j + used - 1
                break
        if dim is None:
            continue
        per = default_pers[0]
        q = text[offs[i]:offs[qend] + len(lines[qend])]
        if q not in text:
            continue
        out.append(Row("revenue", dim, num, "inr_cr", 1e7, per.ptype, per.canon, per.as_of, basis, page, q,
                       ln.strip(), m.group("num"), "sentence_default_v1"))
    return out


_GROUP_RX = [("half", re.compile(r"half[- ]year(?:ly)?\s+ended|six\s+months?\s+ended", re.I)),
             ("nine", re.compile(r"nine\s+months?\s+ended", re.I)),
             ("year", re.compile(r"(?<!half )(?<!half-)year\s+ended|twelve\s+months?\s+ended", re.I)),
             ("quarter", re.compile(r"quarter\s+ended|three\s+months?\s+ended", re.I))]


def relabel_group_columns(rows, info) -> None:
    """A results table prints bare dates under group headings ("Quarter ended | Half Year ended | Year ended" over
    30.09.2025 30.06.2025 ... 30.09.2025 ...): the date alone reads as the quarter.  Relabel each date column by the
    nearest group heading above it in x (H1/H2, 9M or FY of the same fiscal year).  Rows without such a heading keep
    the reader's labels."""
    for h, (_, _, ps) in enumerate(info):
        dated = [(x, pr) for x, pr in ps if pr.as_of]
        if len({pr.canon for _, pr in ps}) < 2 or not dated:
            continue
        heads = []
        for j, r in enumerate(rows):
            if not (0 < rows[h].y - r.y <= 90):
                continue
            sj, spj = _row_string(r)
            for kind, rx in _GROUP_RX:
                for m in rx.finditer(sj):
                    xc = _x_of(spj, m.start(), m.end())
                    if xc is not None:
                        heads.append((xc, kind))
        if len({k for _, k in heads}) < 2:
            continue
        for x, pr in dated:
            kind = min(heads, key=lambda t: abs(t[0] - x))[1]
            mo = int(pr.as_of[5:7])
            m = re.search(r"FY(\d\d)", pr.canon)
            if not m or kind == "quarter":
                continue
            yy = m.group(1)
            if kind == "half" and mo in (9, 3):
                pr.canon, pr.ptype = f"H{1 if mo == 9 else 2}FY{yy}", "H"
            elif kind == "nine" and mo == 12:
                pr.canon, pr.ptype = f"9MFY{yy}", "9M"
            elif kind == "year" and mo == 3:
                pr.canon, pr.ptype = f"FY{yy}", "FY"


def _xspan(spans, a: int, b: int):
    """(x0, x1) of the characters a..b of a row's reconstructed string."""
    xs = [(x0, x1) for (s, e, x0, x1) in spans if s < b and e > a]
    return (min(x[0] for x in xs), max(x[1] for x in xs)) if xs else None


def _headings(rows, h: int):
    """(x0, x1, kind) of every group heading above period header row `h` ("Quarter ended | Half year ended ...")."""
    best: dict[str, tuple[float, float]] = {}
    for r in rows:
        if not (0 < rows[h].y - r.y <= 90):
            continue
        sj, spj = _row_string(r)
        for kind, rx in _GROUP_RX:
            for m in rx.finditer(sj):
                sp = _xspan(spj, m.start(), m.end())
                if sp and (kind not in best or sp[1] - sp[0] > best[kind][1] - best[kind][0]):
                    best[kind] = sp
    return sorted((x0, x1, k) for k, (x0, x1) in best.items())


def _date_fits(kind: str, month: int) -> bool:
    """A column's own date must agree with its group heading: only Sep/Mar closes a half year, only March a year."""
    if kind == "quarter":
        return True
    if kind == "half":
        return month in (9, 3)
    return month == 12 if kind == "nine" else month == 3


def _set_column_kind(pr: Period, kind: str) -> None:
    if not pr.as_of:                      # only a dated column has a kind to set
        return
    mo, y = int(pr.as_of[5:7]), int(pr.as_of[:4])
    yy = y if mo == 3 else y + 1          # fiscal year of a period ending in month mo
    if kind == "quarter":
        if pr.ptype != "Q":               # a 31 March date reads as the year end; in a quarter column it is Q4
            pr.canon, pr.ptype = f"Q4FY{yy % 100:02d}", "Q"
    elif kind == "half" and mo in (9, 3):
        pr.canon, pr.ptype = (f"H1FY{yy % 100:02d}" if mo == 9 else f"H2FY{yy % 100:02d}"), "H"
    elif kind == "nine" and mo == 12:
        pr.canon, pr.ptype = f"9MFY{yy % 100:02d}", "9M"
    elif kind == "year" and mo == 3:
        pr.canon, pr.ptype = f"FY{yy % 100:02d}", "FY"


def _relabel_columns(rows, info) -> None:
    """A results table's bare dates take their meaning from the group heading over their own column.

    The group boundary is the first column whose date repeats the first column's date: a results table prints the
    current quarter, the prior quarter, the year-ago quarter, and then the year-to-date columns that END ON THE SAME
    DATES (Q2FY27 ends 30.09.2026 and so does H1FY27), so the repeat marks where the year-to-date block starts.  With
    no such repeat the heading that is centred over the run decides (a heading is never interleaved with another)."""
    for h, (_, _, ps) in enumerate(info):
        dated = [(x, pr) for x, pr in ps if pr.as_of]
        if len({pr.canon for _, pr in ps}) < 2 or not dated:
            continue
        heads = _headings(rows, h)
        if len(heads) < 2:
            continue
        dates = [ps[i][1].as_of for i in range(len(ps))]
        groups: list[list[int]] | None = None
        rep = next((i for i in range(1, len(dates)) if dates[i] and dates[i] == dates[0]), None) if dates[0] else None
        if rep and 2 <= rep <= 4 and len(heads) in (2, 3):
            if len(heads) == 2:
                groups = [list(range(0, rep)), list(range(rep, len(ps)))]
            else:
                j = next((k for k in range(rep, len(ps)) if dates[k] and int(dates[k][5:7]) == 3), len(ps))
                groups = [list(range(0, rep)), list(range(rep, j)), list(range(j, len(ps)))]
            if any(not g for g in groups):
                groups = None
        if groups is None:
            xs = [x for x, _ in ps]
            best = None
            for cuts in itertools.combinations(range(1, len(ps)), len(heads) - 1):
                bounds = (0,) + cuts + (len(ps),)
                cand = [list(range(bounds[i], bounds[i + 1])) for i in range(len(heads))]
                score = 0.0
                for gi, idxs in enumerate(cand):
                    mean = sum(xs[i] for i in idxs) / len(idxs)
                    score += abs(mean - (heads[gi][0] + heads[gi][1]) / 2)   # a heading is centred over its columns
                    score += 1e6 * sum(0 if _date_fits(heads[gi][2], int(ps[i][1].as_of[5:7]) if ps[i][1].as_of else 0)
                                       else 1 for i in idxs)
                if best is None or score < best[0]:
                    best = (score, cand)
            if not best:
                continue
            groups = best[1]
        for gi, idxs in enumerate(groups):
            for i in idxs:
                if ps[i][1].as_of:
                    _set_column_kind(ps[i][1], heads[gi][2])


def _result_columns(cols):
    """A results table's quarter columns after the first are prior periods (Q2FY27, Q1FY27, Q2FY26): one printed
    quarter already answers the quarter, so only the first is read.  Half-year and nine-month columns keep
    themselves, because their own header says which they are.  A deck table of several quarters is not a results
    table: it is the only place those quarters print, so every column stays."""
    qs = [i for i, (_, p) in enumerate(cols) if p.ptype == "Q"]
    if len(qs) <= 1:
        return cols
    return [c for i, c in enumerate(cols) if i == qs[0] or cols[i][1].ptype != "Q"]


def _bump(stats: dict | None, key: str) -> None:
    if stats is not None:
        stats[key] = stats.get(key, 0) + 1


# Tuned on the first hand read: 25 dropped KEC's true "net debt including acceptances" 6,722 crore against a group
# median polluted by subsidiary figures (36 crore); the named unit slips stay far above 500x their own group.
OUTLIER_FACTOR = 500


_UNIT_WORD_RX = re.compile(r"\b(?:rs|inr|usd|us\$|crs?|crores?|lakhs?|mn|mm|million|billion|bn|kt|mt|tonnes?|tons?|"
                           r"days?|times|x|per|cent|units?|nos?|audited|unaudited|restated|"
                           r"as|on|at|for|the|in|of|and|amount|amounts|particulars|figures?|total)\b", re.I)


def _label_owns_value(s: str, label_end: int, m, e: Entry) -> bool:
    """A table row's label owns the value only when nothing but unit words and period tokens sits between them:
    "Advances / 3195566.06 / 2746359.78 / 2937166.26 / Fixed assets / 14645.26 / 13854.09" makes 13854.09 the
    next row's cell, not advances.  A row reconstructed from two tables side by side fails here.  `label_end` is the
    row's own label end (the first value), so the label's remaining words are never foreign text; the entry's own
    aliases in brackets ("Value of New Business (VoNB)") are part of the label too."""
    seg = s[label_end:m.start("num")]
    for p in reversed(parse_periods(seg)):
        seg = seg[:p.start] + " " + seg[p.end:]
    for rx in list(e.labels) + list(e.labels_strict):
        seg = rx.sub(" ", seg)
    return not re.search(r"[A-Za-z]{2,}", _UNIT_WORD_RX.sub(" ", seg))


def _quote_names_label(quote: str, label: str | None) -> bool:
    """True when the quote prints at least one word of the row's own label (a sector row must carry its label)."""
    words = [w for w in re.findall(r"[A-Za-z]{4,}", label or "")]
    if not words:
        return True
    low = quote.lower()
    return any(w.lower() in low for w in words)


def _table_value_ok(text: str, s: str, m, e: Entry) -> bool:
    """A table value is whole and possible: a printed token (never a fragment of a neighbour), a number of its kind
    (a percentage at most ``max_pct``, a day count at least one, no negative level), and not a signed change token."""
    num = m.group("num")
    if _comma_decimal(num) or not _whole_printed(text, num):
        return False
    v = to_float(num)
    if v is None:
        return False
    a = m.start("num")
    if a > 0 and s[a - 1] in "+-" and e.kind in ("count", "money"):
        return False            # "+118.4" / "-9" in a delta column is a change, not a level
    if v < 0 and e.kind in ("count", "money"):
        return False
    if e.kind == "pct" and (v > e.max_pct or v < 0):
        return False
    if e.kind == "days" and v < 1:
        return False
    return True


def _kind_candidate(m, e: Entry) -> bool:
    """A printed token that could be a value of this entry's kind: a change column's "4%" is not a money cell, a
    crore figure is not a percent cell.  Used only to count a table row's values against its period columns."""
    suf = (m.group("suf") or "").lower().strip().rstrip(".")
    if e.kind in ("money", "count", "volume", "per_tonne", "days"):
        return suf not in ("%", "per cent", "percent", "bps", "basis points", "x", "times")
    if e.kind == "pct":
        return suf not in ("crore", "crores", "cr", "crs", "lakh", "lakhs", "mn", "mm", "bn", "million", "billion")
    return True


def table_and_chart_rows(page_words, text: str, page: int, company: str, entries, dims, default_pers,
                         stats: dict | None = None) -> list[Row]:
    rows = _merge_stacked_axes(page_rows(page_words))
    info = [row_periods(r) for r in rows]
    strict = profile.under_profile()
    if strict:
        _relabel_columns(rows, info)
    else:
        relabel_group_columns(rows, info)
    headers = [i for i, (_, _, ps) in enumerate(info) if len({p.canon for _, p in ps}) >= 2 and _axis_like(rows[i], ps)]
    if not headers:
        return []
    basis = page_basis(text)
    out: list[Row] = []
    dim_rows = []   # (y, x_center, dimension, row_first_x, has_values): a row with values is data, not a block heading
    for i, r in enumerate(rows):
        s, spans = _row_string(r)
        has_vals = bool(VAL_RX.search(s))
        for d in dims:
            if d.companies and company not in d.companies:
                continue
            ms = [rx.search(s) for rx in d.patterns]
            ms = [m for m in ms if m]
            if ms:
                m = ms[0]
                dim_rows.append((r.y, _x_of(spans, m.start(), m.end()), d.dimension, r.toks[0][0], has_vals))
                break

    # every segment word of every row with its x centre: column headings ("Aluminium upstream | Copper" above the period row)
    all_dims = []
    for r in rows:
        s_, sp_ = _row_string(r)
        for d in dims:
            if d.dimension == "total" or (d.companies and company not in d.companies):
                continue
            for rx in d.patterns:
                for m in rx.finditer(s_):
                    xc_ = _x_of(sp_, m.start(), m.end())
                    if xc_ is not None:
                        all_dims.append((r.y, xc_, d.dimension, r.toks[0][0]))

    def _first_col(hdr):
        return min(x for x, _ in info[hdr][2]) if hdr is not None else None

    def col_dim(hy, x, first_x=None):
        """Segment named in the heading band just above (or on) the period header row, nearest in x to the column.
        The word's row must start at or left of the table's columns: a page title ("Novelis, Aluminium and Copper
        Businesses") sits over them and used to label the Q1FY27 column novelis."""
        near = [(abs(xc - x), dn) for (dy, xc, dn, fx) in all_dims
                if hy - 60 <= dy <= hy + 6 and abs(xc - x) <= 90 and (first_x is None or fx <= first_x + 25)]
        return min(near)[1] if near else None

    def nearest_dim(y, own_text, label_x, hdr=None, x=None):
        for d in dims:
            if d.companies and company not in d.companies:
                continue
            if d.dimension != "total" and any(rx.search(own_text) for rx in d.patterns):
                return d.dimension
        first_x = _first_col(hdr)
        if hdr is not None and x is not None:
            cd = col_dim(rows[hdr].y, x, first_x)
            if cd:
                return cd
        left = [(dy, dn) for (dy, dx, dn, fx, hv) in dim_rows if fx < label_x - 40 and dx is not None]
        if left:   # left-margin block headings sit on the block's last row: take the first heading at or below
            below = [(dy, dn) for dy, dn in left if dy >= y - 12]
            if below and min(below)[0] - y < 200:
                return min(below)[1]
        best, bd = "total", 10 ** 9
        for (dy, dx, dn, fx, has_vals) in dim_rows:
            if not has_vals and (first_x is None or fx <= first_x + 25) and fx >= label_x - 40 and dy <= y + 1 \
                    and (y - dy) < bd and y - dy < 220:
                best, bd = dn, y - dy
        return best

    def pick_header(y, xcs):
        best, bs = None, None
        for hi in headers:
            hy = rows[hi].y
            cols = [x for x, _ in info[hi][2]]
            ok = sum(1 for x in xcs if min(abs(x - c) for c in cols) <= 28)
            if ok == 0:
                continue
            gap = (y - hy) if hy <= y else (hy - y) * 1.5
            score = (-ok, gap)
            if bs is None or score < bs:
                best, bs = hi, score
        return best

    label_seen: dict[str, int] = {}
    series_per_axis: dict[int, int] = {}
    for i, r in enumerate(rows):
        s, _ = _row_string(r)
        if i not in headers and not re.search(r'[A-Za-z]{2,}', VAL_RX.sub('', s)) and len(VAL_RX.findall(s)) >= 2:
            hi0 = pick_header(r.y, [x for x, _ in [(_x_of(_row_string(r)[1], m.start(), m.end()), m) for m in VAL_RX.finditer(s)] if x is not None])
            if hi0 is not None:
                series_per_axis[hi0] = series_per_axis.get(hi0, 0) + 1
    for i, r in enumerate(rows):
        s, spans = _row_string(r)
        if i in headers:
            continue
        pspans = [(p.start, p.end) for _, p in info[i][2]]
        nums = []
        for m in _value_matches(s):
            if any(a <= m.start("num") < b for a, b in pspans):
                continue
            xc = _x_of(spans, m.start(), m.end())
            if xc is not None:
                nums.append((xc, m))
        if not nums:
            continue
        label = s[:nums[0][1].start()].strip()
        if _PROSE_ROW.search(label):     # running text under a distant header is a sentence, not a table row
            continue                     # ("GNPA ... as of 31 March 2021 stood at 0.35%" used to be its Q4FY20 column)
        if len(re.findall(r"[A-Za-z]{3,}", label)) >= 1 and len(label) < 90:
            nth = label_seen.get(label, 0)
            label_seen[label] = nth + 1
            hit = label_matches(entries, company, label)
            if not hit:
                continue
            hi = pick_header(r.y, [x for x, _ in nums])
            if hi is None:
                continue
            cols = info[hi][2]
            assign = nums
            if strict:
                lo_x = min(x for x, _ in cols) - 28
                hi_x = max(x for x, _ in cols) + 28
                assign = [(x, m) for x, m in nums if lo_x <= x <= hi_x]
                ncols = len(cols)
                if len(_headings(rows, hi)) >= 2:     # a results table: only its first (current) quarter column
                    cols = _result_columns(cols)
            for e, lm in hit:
                cand = assign if not strict else [(x, m) for x, m in assign if _kind_candidate(m, e)]
                if strict and len(cand) > ncols:
                    _bump(stats, "column_mismatch")
                    continue      # more values than columns: extra figures are deltas or captions, not cells
                for xc, m, per in _assign_columns(cand, cols, 28):
                    if strict and not _label_owns_value(s, nums[0][1].start(), m, e):
                        _bump(stats, "label_not_owner")
                        continue      # another row's label sits between this label and the figure
                    dim = nearest_dim(r.y, label, r.toks[0][0], hi, xc)
                    if strict and not _table_value_ok(text, s, m, e):
                        _bump(stats, "value_refused")
                        continue
                    unit = value_unit(m.group("cur"), m.group("suf"), e.kind, e.unit)
                    if unit is None and not (m.group("suf") or "").strip():   # a "%" / "x" token never borrows the label's unit
                        unit = _unit_from_label(label, e)
                        if unit == "inr_cr" and e.kind == "money" and not re.search(r"crore|\bcr\b", label, re.I):
                            unit = page_money_unit(text) or unit     # "(₹ in billion)" over the table
                    unit = _page_unit_canon(unit, m.group("num"), e, text)
                    num = to_float(m.group("num"))
                    if unit is None or num is None:
                        continue
                    val, u, scale = finalize_unit(unit, num, e.unit)
                    q = _anchored_quote(text, label, m.group("num"), nth)
                    if not q:
                        continue
                    out.append(Row(e.metric, dim, val, u, scale, per.ptype, per.canon, per.as_of, basis, page, q, label,
                                   m.group("num"), "table_v1"))
                    twin = _q4_twin(e, per)
                    if twin:
                        out.append(Row(e.metric, dim, val, u, scale, twin.ptype, twin.canon, twin.as_of, basis, page,
                                       q, label, m.group("num"), "table_v1"))
            continue
        # ---- chart series: bare numbers aligned to an axis row, titled by a short label above/near
        if not label and len(nums) >= 2 and not re.search(r'[A-Za-z]{2,}', VAL_RX.sub('', s)):
            hi = pick_header(r.y, [x for x, _ in nums])
            if hi is None or abs(rows[hi].y - r.y) > 95:
                continue
            if series_per_axis.get(hi, 0) != 1:      # stacked or multi-series chart: titles cannot be told apart
                continue
            cols = info[hi][2]
            xs = [x for x, _ in nums]
            title = _chart_title(rows, i, min(xs) - 90, max(xs) + 90, entries, company)
            if not title:
                continue
            e, tlabel, unit_hint = title
            for xc, m, per in _assign_columns(nums, cols, 24):
                dim = nearest_dim(r.y, tlabel, min(xs) - 60, hi, xc)
                unit = unit_hint or value_unit(m.group("cur"), m.group("suf"), e.kind, e.unit)
                num = to_float(m.group("num"))
                if unit is None or num is None:
                    continue
                val, u, scale = finalize_unit(unit, num, e.unit)
                q = _chart_quote(text, m.group("num"), tlabel)
                if not q:
                    continue
                out.append(Row(e.metric, dim, val, u, scale, per.ptype, per.canon, per.as_of, basis, page, q, tlabel,
                               m.group("num"), "chart_v1"))
    out.extend(mix_rows(rows, info, headers, text, page, company, entries, dims, basis, default_pers))
    return out


_PART_A = re.compile(r"^(?:Q[1-4]|H[12]|[369]M|12M)$", re.I)
_PART_B = re.compile(r"^(?:FY\s?'?\d{2,4}(?:-\d{2})?)$", re.I)


def _merge_stacked_axes(rows: list[WRow]) -> list[WRow]:
    """Chart axes often stack a period over its year ("Q2 H1" over "FY25 FY26"): a row made only of Q1..Q4 / H1 / 9M
    tokens followed by a row of the same number of FYyy tokens, aligned in x, becomes one row of "Q2 FY25" tokens at
    the lower row's height, so the axis is read as periods (T-049 E)."""
    out: list[WRow] = []
    i = 0
    while i < len(rows):
        r = rows[i]
        if i + 1 < len(rows) and 4 <= rows[i + 1].y - r.y <= 24:
            a, b = r.toks, rows[i + 1].toks
            if (len(a) == len(b) and len(a) >= 2 and all(_PART_A.match(t[2]) for t in a)
                    and all(_PART_B.match(t[2]) for t in b)
                    and all(abs((x[0] + x[1]) / 2 - (y[0] + y[1]) / 2) <= 25 for x, y in zip(a, b))):
                m = WRow(rows[i + 1].y, [(min(x[0], y[0]), max(x[1], y[1]), f"{x[2]} {y[2]}") for x, y in zip(a, b)], rows[i + 1].y0)
                out.append(m)
                i += 2
                continue
        out.append(r)
        i += 1
    return out


def _axis_like(r: WRow, ps) -> bool:
    """A period header is a row of period tokens with a few caption words ("Particulars", "YoY"), not a sentence that
    happens to name two periods ("In H1 FY26 Domestic sales mix was 10% higher vs prior period")."""
    s, _ = _row_string(r)
    for _, p in sorted(ps, key=lambda t: -t[1].start):
        s = s[:p.start] + " " + s[p.end:]
    return len(re.findall(r"[A-Za-z]{3,}", s)) <= 6


def _assign_columns(nums, cols, tol):
    """[(x, match, period)]: each value goes to its nearest period column within tol, and a column takes one value only
    (two numbers over one column header mean one of them is a caption figure, e.g. 'up 4%'): the nearer one wins."""
    best: dict = {}
    for xc, m in nums:
        ci = min(range(len(cols)), key=lambda k: abs(cols[k][0] - xc))
        d = abs(cols[ci][0] - xc)
        if d <= tol and (ci not in best or d < best[ci][0]):
            best[ci] = (d, xc, m, cols[ci][1])
    return sorted(((xc, m, per) for _, xc, m, per in best.values()), key=lambda t: t[0])


def _label_anchors(text: str, label: str) -> list[str]:
    """Runs of the label's words that occur literally in the page text (text layers split labels oddly), best first:
    the whole label, then runs ending nearest the label's end (the values follow it), longer first."""
    lab = " ".join(label.split())
    if lab in text:
        return [lab]
    parts = lab.split()
    cands = []
    for n in range(1, len(parts)):
        for s in range(0, len(parts) - n + 1):
            c = " ".join(parts[s:s + n])
            if len(c) >= 4 and c in text:
                cands.append((s + n, len(c), c))
    cands.sort(reverse=True)
    return [c for _, _, c in cands] or [lab]


def _label_anchor(text: str, label: str) -> str:
    return _label_anchors(text, label)[0]


def _unit_from_label(label: str, e: Entry) -> str | None:
    l = label.lower()
    if e.kind == "money":
        if re.search(r"₹|rs|inr|crore|\bcr\b", l):
            return "inr_cr"
        if re.search(r"\$|usd", l) and re.search(r"million|mn", l):
            return "usd_mn"
        if re.search(r"\$|usd", l) and re.search(r"billion|bn", l):
            return "usd_bn"
        return e.unit if e.unit == "inr_cr" and not re.search(r"\$|usd", l) else None
    if e.kind == "volume":
        return "kt" if re.search(r"\bkt\b|kilo|'000|000 ?t", l) else None
    if e.kind == "per_tonne":
        return "usd_per_tonne" if re.search(r"\$|usd", l) or "ton" in l else None
    if e.kind == "pct":
        return "pct" if "%" in l else None     # a pct row needs the sign: "R&D expenditure 23,676" is rupees, not %
    if e.kind == "days":
        return "days"
    if e.kind == "count":
        return "count_mn" if re.search(r"\bmn\b|\bmm\b|million", l) else ("count" if e.unit == "count" else None)
    if e.kind in ("ratio", "num"):
        return "x"
    return None


_TITLE_BAD = re.compile(r"\b(were|was|is|are|at|up|down|grew|rose|fell|vs|against|due|backed|stood)\b", re.I)


def _chart_title(rows, i, xlo, xhi, entries, company):
    """Short lexicon-label row near the chart (within x range), above first then below; needs a unit in the title."""
    cand = []
    for j in range(len(rows)):
        if j == i:
            continue
        dy = rows[i].y - rows[j].y
        if not (-70 <= dy <= 150):
            continue
        s, spans = _row_string(rows[j])
        if len(s) > 48 or _TITLE_BAD.search(s) or parse_periods(s):
            continue
        x0 = rows[j].toks[0][0]
        if not (xlo <= x0 <= xhi):
            continue
        hit = label_matches(entries, company, s)
        if not hit:
            continue
        e = hit[0][0]
        hint = _unit_from_label(s, e)
        if hint is None:
            continue
        cand.append((abs(dy) if dy >= 0 else abs(dy) + 40, e, s, hint))
    if not cand:
        return None
    _, e, s, hint = min(cand, key=lambda c: c[0])
    return e, s, hint


def _chart_quote(text: str, num: str, title: str):
    t = title.strip()
    ta = _label_anchor(text, t)
    best = None
    for jm in re.finditer(re.escape(ta), text):
        for im in re.finditer(re.escape(num), text):
            lo, hi = min(im.start(), jm.start()), max(im.end(), jm.end())
            if hi - lo <= 500 and (best is None or hi - lo < best[1] - best[0]):
                best = (lo, hi)
    return text[best[0]:best[1]] if best else None


# ---------------------------------------------------------------- driver
def _open_pdf_path(path: Path | str | None):
    """PyMuPDF document at `path`, or None when it is not set or not on this machine."""
    p = Path(path) if path else None
    if p is None or not p.is_file():
        return None
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz
    try:
        return fitz.open(str(p))
    except Exception:
        return None


def _open_pdf(sandbox: Path, sym: str, doc_key: str):
    return _open_pdf_path(sandbox / f"{COMPANIES[sym]}_loop" / "raw" / doc_key)

RAW_ROOT = Path("D:/RealityEngine/raw")


def _pages_docs(sym: str, pages_db: Path | str | None, raw_root: Path | None, ocr: dict, st: dict, shas: set):
    """Yield (doc_key, doc_type, known_at, usable_pages, pdf, ocr_pages, 'pages.db.doc.known_at') for every document
    `pages.db` holds for the symbol (doc types KPI_DOC_TYPES), oldest filing first.  Page text is the collector's
    `doc_page` row (its OCR text included, method ocr_rapid or ocr_textrec); the PDF for table/chart pages is `doc.source_path`,
    else the sha256 copy under <raw_root>/decks_full.  This is the same source the pilot3 registry writes, so the
    FY25-FY27 decks and results presentations are read instead of only the sandbox's older documents.  Every
    document's sha256 is added to `shas`, so the decks_full fallback below does not read the same file twice."""
    path = Path(pages_db) if pages_db else None
    if path is None or not path.is_file():
        return
    try:
        pg = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
    except sqlite3.DatabaseError:
        return
    try:
        docs = pg.execute(
            f"SELECT doc_key, doc_type, known_at, source_path, sha256 FROM doc WHERE symbol=? AND doc_type IN "
            f"({','.join('?' * len(KPI_DOC_TYPES))}) ORDER BY known_at, doc_key", (sym, *KPI_DOC_TYPES)).fetchall()
        for doc_key, doc_type, known_at, source_path, sha in docs:
            if sha:
                shas.add(sha)
            pages = pg.execute("SELECT page, text, method FROM doc_page WHERE doc_key=? ORDER BY page",
                               (doc_key,)).fetchall()
            opg = ocr.get(doc_key, {})
            if not pages and not opg:
                continue
            st["docs"] += 1
            st["needs_ocr"] += sum(1 for _, _, m in pages if m == "needs_ocr")
            usable = [(p, t) for p, t, m in pages if m in ("script_text", "ocr_rapid", "ocr_textrec") and t]
            if opg:
                have = {p for p, _ in usable}
                usable = sorted(usable + [(p, v[0]) for p, v in opg.items() if p not in have and v[0]])
                st["ocr_pages_used"] = st.get("ocr_pages_used", 0) + len([p for p in opg if p not in have])
            pdf = None
            if doc_type in PDF_DOC_TYPES:
                pdf = _open_pdf_path(source_path)
                if pdf is None and raw_root is not None and sha:
                    pdf = _open_pdf_path(Path(raw_root) / "decks_full" / sha[:2] / f"{sha}.pdf")
                if pdf is None:
                    st["pdf_missing"] += 1
            yield doc_key, doc_type, known_at, usable, pdf, opg, "pages.db.doc.known_at"
            if pdf is not None:
                pdf.close()
    finally:
        pg.close()


def _doc_sources(con: sqlite3.Connection | None, sym: str, sandbox: Path | None, raw_root: Path | None,
                 limit_docs: int | None, st: dict, ocr: dict | None = None, pages_db: Path | str | None = None):
    """Yield (doc_key, doc_type, known_at, usable_pages, pdf_or_None, ocr_pages, known_at_source). pages.db first
    (when `pages_db` is given), then the sandbox's own documents that pages.db does not hold, then (optional) the
    decks that deck_figures cites but neither holds (read straight from the text layer of the raw PDF).
    ocr = {doc_key: {page: (text, words, conf)}} from pilot3.ocr: those pages are added to usable (text = OCR text)
    and the 6th item is the {page: ...} dict of the pages read by OCR."""
    ocr = ocr or {}
    held: set[str] = set()
    shas: set[str] = set()
    if pages_db:
        for i, item in enumerate(_pages_docs(sym, pages_db, raw_root, ocr, st, shas)):
            if limit_docs and i >= limit_docs:
                break
            held.add(item[0])
            yield item
    names = {Path(k).name for k in held}
    if con is not None:      # a profile build has no sandbox: pages.db is every document
        docs = con.execute(
            f"SELECT doc_key, doc_type, known_at FROM docs WHERE doc_type IN ({','.join('?' * len(KPI_DOC_TYPES))}) ORDER BY known_at",
            KPI_DOC_TYPES).fetchall()
        if limit_docs:
            docs = docs[:limit_docs]
        for doc_key, doc_type, known_at in docs:
            if doc_key in held or Path(doc_key).name in names:      # pages.db already holds this document
                continue
            pages = con.execute("SELECT page, text, method FROM doc_text WHERE doc_key=? ORDER BY page", (doc_key,)).fetchall()
            if not pages:
                continue
            st["docs"] += 1
            st["needs_ocr"] += sum(1 for _, _, m in pages if m == "needs_ocr")
            usable = [(p, t) for p, t, m in pages if m == "script_text" and t]
            pdf = _open_pdf(sandbox, sym, doc_key) if doc_type in PDF_DOC_TYPES and sandbox is not None else None
            if pdf is None and doc_type in PDF_DOC_TYPES:
                st["pdf_missing"] += 1
            opg = ocr.get(doc_key, {})
            if opg:
                have = {p for p, _ in usable}
                usable = sorted(usable + [(p, v[0]) for p, v in opg.items() if p not in have and v[0]])
                st["ocr_pages_used"] = st.get("ocr_pages_used", 0) + len([p for p in opg if p not in have])
            yield doc_key, doc_type, known_at, usable, pdf, opg, "docs.known_at"
            if pdf is not None:
                pdf.close()
    if raw_root is None or con is None:
        return
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz
    extra = con.execute("SELECT sha256, min(known_at) FROM deck_figures GROUP BY sha256 ORDER BY 2").fetchall()
    sandbox_shas = {r[0] for r in con.execute("SELECT source_key FROM docs WHERE source_key IS NOT NULL")}
    for sha, known_at in extra:
        if sha in shas or sha in sandbox_shas:
            continue
        path = raw_root / "decks_full" / sha[:2] / f"{sha}.pdf"
        if not path.exists():
            st["extra_missing"] = st.get("extra_missing", 0) + 1
            continue
        try:
            pdf = fitz.open(str(path))
        except Exception:
            st["extra_missing"] = st.get("extra_missing", 0) + 1
            continue
        usable = []
        for i in range(pdf.page_count):
            t = pdf[i].get_text("text")
            if len(t.strip()) >= 20:
                usable.append((i + 1, t))
            else:
                st["extra_needs_ocr"] = st.get("extra_needs_ocr", 0) + 1
        st["extra_docs"] = st.get("extra_docs", 0) + 1
        key = f"decks_full/{sha[:2]}/{sha}.pdf"
        opg = ocr.get(key, {})
        if opg:
            have = {p for p, _ in usable}
            usable = sorted(usable + [(p, v[0]) for p, v in opg.items() if p not in have and v[0]])
            st["ocr_pages_used"] = st.get("ocr_pages_used", 0) + len([p for p in opg if p not in have])
        yield key, "deck", known_at, usable, pdf, opg, "deck_figures.known_at"
        pdf.close()



def extract_company(sym: str, sandbox: Path | None, stats: dict, limit_docs: int | None = None, raw_root: Path | None = None,
                    ocr: dict | None = None, only_docs: list[str] | None = None, pages_db: Path | str | None = None):
    if sandbox is None or profile.under_profile():
        con = None      # a profile company has no sandbox: every document and page comes from pages_db
    else:
        dbp = sandbox / f"{COMPANIES[sym]}_loop" / f"{COMPANIES[sym]}.db"
        con = sqlite3.connect(f"file:{dbp.as_posix()}?mode=ro", uri=True)
    entries, dims = load_lexicon()
    # a sector family's row must quote its own label; a common metric may take its label from the line above
    sector_only = ({e.metric for e in entries if e.sectors} - {e.metric for e in entries if not e.sectors}) \
        if profile.under_profile() else set()
    st = stats.setdefault(sym, {"pages": 0, "needs_ocr": 0, "docs": 0, "pdf_missing": 0})
    for doc_key, doc_type, known_at, usable, pdf, opg, src in _doc_sources(con, sym, sandbox, raw_root, limit_docs, st, ocr,
                                                                          pages_db):
        if only_docs and not any(k in doc_key for k in only_docs):
            continue
        if doc_type == "transcript" and known_at:   # a call cannot be known before it was held (call_dates)
            known_at = call_dates.clamp(None, known_at, [t for _, t in usable[:3]])[1]
        default_pers = doc_default_period([t for _, t in usable])
        # an annual report (or any document over 80 pages) prints last year's figures everywhere, so the document
        # headline is no default: only a period on the page itself may stand in for one the sentence does not name
        long_doc = profile.under_profile() and (doc_type == "annual_report" or len(usable) > 80)
        for page, text in usable:
            st["pages"] += 1
            page_pers = default_pers
            if long_doc:
                page_pers = doc_default_period([text])
                if not page_pers:
                    st["no_period_long_doc"] = st.get("no_period_long_doc", 0) + 1
            try:
                srows = sentence_rows(text, page, sym, entries, dims, page_pers)
            except Exception:  # keep the run going, count it
                srows = []
                st["errors"] = st.get("errors", 0) + 1
            trows: list[Row] = []
            method, ocr_conf = "text_layer", None
            words = None
            if page in opg:                      # page read by OCR: word boxes come from the stored OCR, not the PDF
                method, ocr_conf = opg[page][3], opg[page][2]
                words = opg[page][1]
                st["ocr_pages"] = st.get("ocr_pages", 0) + 1
            elif pdf is not None and 0 < page <= pdf.page_count and _page_may_have_table(text):
                words = pdf[page - 1].get_text("words")
            if words is not None and _page_may_have_table(text):
                try:
                    trows = table_and_chart_rows(words, text, page, sym, entries, dims, page_pers, st)
                except Exception:
                    st["errors"] = st.get("errors", 0) + 1
            basis = page_basis(text)
            try:     # chart mix and business-wise revenue bullets: no word boxes needed
                erows = pie_mix_rows(text, page, sym, entries, dims, basis, page_pers)
                seg = segment_revenue_rows(text, page, sym, entries, dims, basis, page_pers)
            except Exception:
                erows, seg = [], []
                st["errors"] = st.get("errors", 0) + 1
            if seg:  # a business-wise block states the segment's revenue; its total-dimension sentence is the same number
                srows = [r for r in srows if not (r.metric == "revenue" and r.dimension == "total"
                                                  and any(abs(r.value - x.value) < 1e-6 for x in seg))]
            if trows:   # on a table page, running-text hits that span line breaks are table fragments: drop them
                srows = [r for r in srows if "\n" not in r.quote]
            for r in sorted(srows + trows + erows + seg, key=lambda r: -RULE_CONF[r.rule][1]):   # best confidence first: INSERT OR IGNORE keeps it
                if r.metric in sector_only and not _quote_names_label(r.quote, r.raw_label):
                    _bump(st, "quote_without_label")
                    continue      # a sector row's quote must print its own label, not a bare column of numbers
                why = drop_reason(r.period_type, r.fiscal_period, known_at)
                if why:
                    st[why] = st.get(why, 0) + 1
                    continue              # the document cannot report a period that ended after it was filed,
                                          # nor (under a profile) one that closed before the window's YoY base
                conf, rank = RULE_CONF[r.rule]
                if doc_type == "transcript":     # a call's number is not the deck KPI: its own row, lowest tier (T-049)
                    rank = max(1, rank - 2)
                yield dict(symbol=sym, metric=r.metric, dimension=r.dimension, value=r.value, unit=r.unit, scale=r.scale,
                           period_type=r.period_type, fiscal_period=r.fiscal_period, as_of_date=r.as_of, basis=r.basis,
                           doc_key=doc_key, page=page, quote=r.quote, known_at=known_at, known_at_source=src,
                           is_reported=1, raw_label=r.raw_label, raw_value=r.raw_value, extractor_rule=r.rule,
                           confidence=conf, conf_rank=rank, method=method, ocr_conf=ocr_conf, source_type=doc_type)
    if con is not None:
        con.close()


def _page_may_have_table(text: str) -> bool:
    return len(parse_periods(text)) >= 2


COLS = ("symbol metric dimension value unit scale period_type fiscal_period as_of_date basis doc_key page quote "
        "known_at known_at_source is_reported raw_label raw_value extractor_rule confidence conf_rank method ocr_conf "
        "source_type").split()


def _review_outliers(con: sqlite3.Connection, symbol: str, max_pct: dict[str, float], review: list,
                     st: dict | None = None) -> None:
    """Drop a row that is absurd beside its own group (same symbol, metric, unit) and file it for review.

    A units slip ("Gross sales: Rs 582,201 mn" stored as USD), a fragment or a caption figure is usually 25 times
    away from its group's median.  A percentage above its entry's ceiling is impossible whatever the group.  Only
    extracted rows are reviewed; the segment reader's xbrl_segment rows are not touched."""
    groups: dict[tuple[str, str], list] = {}
    for row in con.execute("SELECT id, metric, unit, value, quote, doc_key, page FROM kpi_series "
                           "WHERE symbol=? AND value>0 AND coalesce(source_type,'')<>'xbrl_segment'", (symbol,)):
        groups.setdefault((row[1], row[2]), []).append(row)
    drop: dict[int, tuple] = {}
    for (metric, unit), rows in groups.items():
        if len(rows) < 4:
            continue
        med = statistics.median(r[3] for r in rows)
        if med <= 0:
            continue
        for rid, met, u, v, quote, doc_key, page in rows:
            if v > OUTLIER_FACTOR * med:
                drop[rid] = (rid, symbol, met, v, u, quote, doc_key, page,
                             f"above {OUTLIER_FACTOR:g}x group median {med:g} (n={len(rows)})")
            elif v * OUTLIER_FACTOR < med:
                drop[rid] = (rid, symbol, met, v, u, quote, doc_key, page,
                             f"below 1/{OUTLIER_FACTOR:g} of group median {med:g} (n={len(rows)})")
    for rid, met, u, v, quote, doc_key, page in con.execute(
            "SELECT id, metric, unit, value, quote, doc_key, page FROM kpi_series WHERE symbol=? AND unit='pct' "
            "AND value>100 AND coalesce(source_type,'')<>'xbrl_segment'", (symbol,)):
        if v > max_pct.get(met, 100.0):
            drop[rid] = (rid, symbol, met, v, u, quote, doc_key, page, f"pct above max_pct {max_pct.get(met, 100.0):g}")
    if not drop:
        return
    con.executemany("DELETE FROM kpi_series WHERE id=?", [(rid,) for rid in drop])
    review.extend(drop.values())
    if st is not None:
        st["kpi_review"] = len(drop)


def _review_path(out: str) -> Path:
    stem = out[:-3] if out.lower().endswith(".db") else out
    return Path(stem + "_kpi_review.csv")


def run(out: str, symbols: list[str], sandbox: Path | None, limit_docs: int | None = None, raw_root: Path | None = None,
        ocr_db: str | Path | list | tuple | None = None, only_docs: list[str] | None = None,
        pages_db: Path | str | None = None) -> dict:
    t0 = time.time()
    con = sqlite3.connect(out)
    con.executescript(SCHEMA)
    have_cols = {r[1] for r in con.execute("PRAGMA table_info(kpi_series)")}
    for name, ddl in NEW_COLS:
        if name not in have_cols:
            con.execute(f"ALTER TABLE kpi_series ADD COLUMN {name} {ddl}")
    ocr_paths = [ocr_db] if isinstance(ocr_db, (str, Path)) else list(ocr_db or ())
    ocr_cons = [sqlite3.connect(f"file:{Path(d).as_posix()}?mode=ro", uri=True) for d in ocr_paths]
    stats: dict = {}
    review: list = []
    max_pct = {e.metric: e.max_pct for e in load_lexicon()[0]} if profile.under_profile() else {}
    sql = f"INSERT OR IGNORE INTO kpi_series({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})"
    for sym in symbols:
        con.execute("DELETE FROM kpi_series WHERE symbol=? AND source_type<>'xbrl_segment'", (sym,))
        batch = []
        ocr = None
        if ocr_cons:
            from reality_engine.pilot3.ocr import load_ocr

            ocr = {}
            for c in ocr_cons:
                for doc_key, pages in load_ocr(c, sym).items():
                    cur = ocr.setdefault(doc_key, {})
                    for page, value in pages.items():
                        # HP TextRecognizer beats MSI RapidOCR when both read the same page
                        if page not in cur or OCR_METHOD_RANK.get(value[3], 0) >= OCR_METHOD_RANK.get(cur[page][3], 0):
                            cur[page] = value
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='doc_alias'").fetchone():
                for alias_key, doc_key in con.execute("SELECT alias_key, doc_key FROM doc_alias WHERE symbol=?", (sym,)):
                    if doc_key in ocr and alias_key not in ocr:   # an OCR page under the pilot3 key serves its sandbox key
                        ocr[alias_key] = ocr[doc_key]
        for row in extract_company(sym, sandbox, stats, limit_docs, raw_root, ocr, only_docs, pages_db):
            batch.append([row[c] for c in COLS])
            if len(batch) >= 2000:
                con.executemany(sql, batch)
                batch = []
        if batch:
            con.executemany(sql, batch)
        con.commit()
        if profile.under_profile():
            _review_outliers(con, sym, max_pct, review, stats[sym])
            con.commit()
        stats[sym]["rows"] = con.execute("SELECT count(*) FROM kpi_series WHERE symbol=?", (sym,)).fetchone()[0]
    if profile.under_profile():
        rp = _review_path(out)
        with rp.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(("symbol", "metric", "value", "unit", "quote", "doc_key", "page", "reason"))
            for d in review:
                w.writerow((d[1], d[2], d[3], d[4], d[5], d[6], d[7], d[8]))
        stats["kpi_review_rows"] = len(review)
    stats["seconds"] = round(time.time() - t0, 1)
    con.close()
    for c in ocr_cons:
        c.close()
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default=None, help="default: every company of the profile, else every pilot3 company")
    ap.add_argument("--profile", default=None, help="build profile JSON (T-056): companies, pages db, raw root, output")
    ap.add_argument("--sandbox-root", default=str(SANDBOX_ROOT))
    ap.add_argument("--limit-docs", type=int, default=None)
    ap.add_argument("--raw-root", default=str(RAW_ROOT), help="also read the decks deck_figures cites but docs does not hold (text layer only); '' to disable")
    ap.add_argument("--ocr-db", action="append", default=None, help="ocr_page table written by pilot3.ocr: its pages are read too (repeat for one per company)")
    ap.add_argument("--only-docs", default=None, help="comma list of doc_key substrings (debug: read only these documents)")
    ap.add_argument("--pages-db", default="", help="docs_collect pages.db: read every held document from it (the pilot3 registry's source); '' disables, a profile uses its own")
    a = ap.parse_args(argv)
    if a.profile:
        profile.activate(profile.load(a.profile))
    symbols = [s.strip().upper() for s in (a.symbols or ",".join(profile.symbols())).split(",") if s.strip()]
    pages_db = Path(a.pages_db) if a.pages_db else (profile.pages_db() if a.profile else None)
    stats = run(a.out, symbols, None if a.profile else Path(a.sandbox_root), a.limit_docs,
                Path(a.raw_root) if a.raw_root else None, a.ocr_db, [x for x in (a.only_docs or "").split(",") if x] or None,
                pages_db)
    for k, v in stats.items():
        print(k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
