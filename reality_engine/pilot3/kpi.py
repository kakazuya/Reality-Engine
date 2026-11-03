"""Rule-based company KPI extractor -> table kpi_series (T-049 B). No model, no OCR, no network.

CLI: python -m reality_engine.pilot3.kpi --out <db> [--symbols KEC,BAJFINANCE,HINDALCO] [--sandbox-root DIR]

Reads page text from <sandbox>/<sym>_loop/<sym>.db (doc_text + docs) and, for table/chart pages, word
positions from the PDF under <sandbox>/<sym>_loop/raw/<doc_key> (PyMuPDF). Pages whose doc_text method is
needs_ocr are skipped and counted. Three rules write rows (extractor_rule column):
  table_v1    label row + period header row, values paired to header columns by x position
  chart_v1    a bare number row sitting above a period axis row, titled by the nearest lexicon label above
  sentence_v1 label ... value [unit] [period] [vs value period] inside running text
A row is stored only if its quote is a literal substring of the page text.
Shared helpers (periods, numbers, units, lexicon loader) are imported by transcripts.py.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

LEX_DIR = Path(__file__).parent / "lexicon"
SANDBOX_ROOT = Path("D:/RealityEngine/sandbox")
COMPANIES = {"KEC": "kec", "BAJFINANCE": "bajfinance", "HINDALCO": "hindalco"}
KPI_DOC_TYPES = ("deck", "results", "press_release", "transcript", "annual_report", "announcement")
PDF_DOC_TYPES = ("deck", "results", "press_release", "annual_report")  # table/chart mode needs the PDF

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
  UNIQUE(symbol, metric, dimension, fiscal_period, value, unit, doc_key, page)
);
CREATE INDEX IF NOT EXISTS ix_kpi_sym_metric ON kpi_series(symbol, metric, fiscal_period);
"""

# confidence of a row by the rule that wrote it: table_row > table_chart > sentence > sentence_default (T-049 E)
RULE_CONF = {"table_v1": ("table_row", 4), "chart_v1": ("table_chart", 3), "sentence_v1": ("sentence", 2),
             "sentence_pair_v1": ("sentence", 2), "sentence_default_v1": ("sentence_default", 1)}
CONF_RANK = {name: rank for name, rank in RULE_CONF.values()}
NEW_COLS = (("confidence", "TEXT NOT NULL DEFAULT 'sentence'"), ("conf_rank", "INTEGER NOT NULL DEFAULT 2"),
            ("method", "TEXT NOT NULL DEFAULT 'text_layer'"), ("ocr_conf", "REAL"))

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
    ("MFY", re.compile(r"(?<![A-Za-z0-9])(9M|6M|3M|12M|H[12])\s?(?:FY\s?)?['’]?\s?(\d{4}|\d{2})(?![\d])", re.I)),
    ("FY", re.compile(r"(?<![A-Za-z0-9])FY\s?['’]?\s?(\d{4}-\d{2}|\d{2}-\d{2}|\d{4}|\d{2})(?![\d])", re.I)),
    ("DATE_DMY", re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s,.-]+(" + _MON_PAT + r")[a-z]*[\s,.-]+['’]?(\d{4}|\d{2})(?!\d)", re.I)),
    ("DATE_MDY", re.compile(r"(?<![A-Za-z])(" + _MON_PAT + r")[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)", re.I)),
    ("DATE_NUM", re.compile(r"(?<![\d.,/-])(\d{1,2})([./-])(\d{1,2})\2(20\d{2})(?![\d])")),
    ("MON_Y", re.compile(r"(?<![A-Za-z])(" + _MON_PAT + r")[a-z]*[-\s,']+['’]?(\d{4}|\d{2})(?!\d)", re.I)),
]


@dataclass
class Period:
    start: int
    end: int
    canon: str       # Q3FY24 | FY24 | 9MFY24 | H1FY24
    ptype: str       # Q | FY | M9 | H ...
    as_of: str | None = None


def _fiscal_of_date(y: int, m: int, d: int, force_end: bool = False):
    fy = y + 1 if m > 3 else y
    if m in _QEND and (force_end or d >= _QEND[m][1] - 1):
        q = _QEND[m][0]
        asof = f"{y:04d}-{m:02d}-{d:02d}" if d else None
        return f"Q{q}FY{fy % 100:02d}", "Q", asof
    return None


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
    r"(?P<suf>crores?|crs?\b\.?|lakhs?|mn\b|million|billion|bn\b|kt\b|kilo ?tonnes?|tonnes?|tons?|mt\b|%|per ?cent|bps|basis points|x\b|times|days)?",
    re.I)
_UNIT_BY_SUFFIX = {
    "crore": "inr_cr", "crores": "inr_cr", "cr": "inr_cr", "crs": "inr_cr",
    "mn": "mn", "million": "mn", "billion": "bn", "bn": "bn",
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
    if kind == "money":
        if base == "inr_cr" or (cur == "inr" and base in (None, "inr_cr")):
            return "inr_cr" if (base == "inr_cr" or default_unit == "inr_cr") and cur != "usd" else None
        if cur == "usd" or (default_unit.startswith("usd") and base in ("mn", "bn")):
            if base == "bn":
                return "usd_bn"
            if base == "mn":
                return "usd_mn"
            return None
        if base in ("mn", "bn") and cur == "inr":
            return "inr_mn" if base == "mn" else "inr_bn"
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
    if kind == "days":
        return "days" if base == "days" else None
    return None


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
                                     [is_generic_label(x) for x in e["labels"]]))
        if "dimensions" in d:
            for e in d["dimensions"]:
                dims.append(Dim(e["dimension"], [_rx(x) for x in e["patterns"]], e.get("companies")))
    return entries, dims


def label_matches(entries: list[Entry], company: str, text: str):
    """[(entry, match)] for entries whose label hits text and neg does not. First hit per metric."""
    res = []
    for e in entries:
        if e.companies and company not in e.companies:
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


def find_dimension(dims: list[Dim], company: str, text: str, pos: int, window: int = 90) -> str:
    """Dimension word nearest before pos (within window), else nearest after within 40 chars, else total."""
    best, best_d = None, 10 ** 9
    lo, hi = max(0, pos - window), min(len(text), pos + 40)
    seg = text[lo:hi]
    for d in dims:
        if d.companies and company not in d.companies:
            continue
        for rx in d.patterns:
            for m in rx.finditer(seg):
                dist = (pos - (lo + m.end())) if lo + m.end() <= pos else (lo + m.start() - pos) + 15
                if dist < best_d:
                    best, best_d = d.dimension, dist
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


def finalize_unit(unit: str, value: float, metric_default: str):
    """-> (value, unit, scale)."""
    if unit == "inr_cr":
        return value, "inr_cr", 1e7
    if unit == "usd_mn":
        return value, "usd_mn", 1e6
    if unit == "usd_bn":
        return value * 1000.0, "usd_mn", 1e6   # normalised to million dollars
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


def page_basis(text: str) -> str:
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


def doc_default_period(texts: list[str]) -> list[Period]:
    """Reporting-period hint from the first pages of a document: quarter/year-ended headline."""
    head = " \n".join(texts[:3])
    ps = parse_periods(head)
    # prefer periods near 'ended' / 'quarter' words
    pref = [p for p in ps if re.search(r"(ended|quarter|results|performance|year)", head[max(0, p.start - 40):p.start], re.I)]
    return pref or ps


_BREAK = re.compile(r"[.;]\s+[A-Z]|\n\s*\n")


def _pair_before(text, pers, pos):
    """Last 'A v/s B' period pair that ends before pos and lies within 1500 chars of it."""
    best = None
    for a, b in zip(pers, pers[1:]):
        if b.end <= pos and pos - b.end < 1500 and re.fullmatch(r"\s*(v/?s\.?|vs\.?|versus|against|as against)\s*", text[a.end:b.start], re.I):
            best = (a, b)
    return best


BY_RX = re.compile(r"\b(?:reduc|increas|decreas|declin|improv|grew|grow|rose|fell|expan|add|lower|higher|up|down)\w*\b[^.]{0,30}\bby\s*"
                   r"(?:over|more than|about|around|nearly|approximately|~)?\s*$", re.I)
TO_RX = re.compile(r"\bto\s*$", re.I)


def _second_of_pair(text: str, start: int, v2_end: int, entries, company: str, metric: str) -> bool:
    """True when the label at `start` is the second of "<other label> and <this label> ... a and b respectively"."""
    before = text[max(0, start - 40):start]
    if not re.search(r"(?:\band\b|&)\s*$", before, re.I):
        return False
    if not re.search(r"respectively", text[v2_end:v2_end + 25], re.I):
        return False
    head = re.sub(r"(?:\band\b|&)\s*$", "", before, flags=re.I)
    return any(e.metric != metric for e, _ in label_matches(entries, company, head[-30:]))


def sentence_rows(text: str, page: int, company: str, entries, dims, default_pers: list[Period]) -> list[Row]:
    rows: list[Row] = []
    pers = parse_periods(text)
    per_spans = [(p.start, p.end) for p in pers]
    basis = page_basis(text)
    for e, lm in label_matches(entries, company, text):
        # every occurrence of any label of the entry
        for li, rx in enumerate(e.labels):
            generic = li < len(e.generic) and e.generic[li]
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
                if BY_RX.search(text[m.end():v1.start]):     # "reduced by INR150 crores to INR6,568 crores": 150 is a change
                    lvl = next((v for v in vals[1:] if TO_RX.search(text[max(m.end(), v.start - 6):v.start])), None)
                    if lvl is None:
                        continue
                    v1 = lvl
                elif len(vals) >= 2 and _second_of_pair(text, m.start(), vals[1].end, entries, company, e.metric):
                    v1 = vals[1]                              # "GNPA and NNPA at 0.96% and 0.39% respectively"
                items = [(v1, None)]
                # comparative second value
                tail = text[v1.end:min(len(text), v1.end + 90)]
                vm = VS_RX.search(tail)
                if vm and vm.start() < 60:
                    v2s = find_values(text, e.kind, e.unit, v1.end + vm.end(), min(len(text), v1.end + 90), per_spans)
                    if v2s and v2s[0].start - (v1.end + vm.end()) < 14:
                        items.append((v2s[0], vm))
                dim = find_dimension(dims, company, text, m.start())
                for idx, (v, _) in enumerate(items):
                    # period: same-sentence mention after the value (<=45 chars), else before the label (<=60),
                    # else the nearest earlier "A v/s B" header pair, else the document's reporting period
                    rule = "sentence_v1"
                    cand = [p for p in pers if 0 <= p.start - v.end <= 45 and not _BREAK.search(text[v.end:p.start])
                            and (idx == len(items) - 1 or p.start < items[idx + 1][0].start)]
                    if not cand:
                        cand = [p for p in pers if 0 <= m.start() - p.end <= 60 and '\n' not in text[p.end:m.start()]]
                        cand = cand[-1:]
                    period = cand[0] if cand else None
                    if period is None:
                        pair = _pair_before(text, pers, m.start())
                        if pair:
                            period, rule = pair[min(idx, 1)], "sentence_pair_v1"
                    if period is None and idx == 0 and default_pers:
                        period, rule = default_pers[0], "sentence_default_v1"
                    if period is None:
                        continue
                    if generic and rule != "sentence_v1":   # a bare "margin" / "revenue" needs its own period in the sentence
                        continue
                    val, unit, scale = finalize_unit(v.unit, v.value, e.unit)
                    end = v.end if period.start < v.end else period.end
                    end = max(end, period.end if 0 <= period.start - v.end <= 45 else v.end)
                    q = text[m.start():end]
                    if len(q) > 300:
                        q = text[max(m.start(), v.start - 120):end]
                    if q not in text:
                        continue
                    rows.append(Row(e.metric, dim, val, unit, scale, period.ptype, period.canon, period.as_of, basis,
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


def table_and_chart_rows(page_words, text: str, page: int, company: str, entries, dims, default_pers) -> list[Row]:
    rows = _merge_stacked_axes(page_rows(page_words))
    info = [row_periods(r) for r in rows]
    headers = [i for i, (_, _, ps) in enumerate(info) if len({p.canon for _, p in ps}) >= 2 and _axis_like(rows[i], ps)]
    if not headers:
        return []
    basis = page_basis(text)
    out: list[Row] = []
    dim_rows = []   # (y, x_center, dimension, row_first_x)
    for i, r in enumerate(rows):
        s, spans = _row_string(r)
        for d in dims:
            if d.companies and company not in d.companies:
                continue
            ms = [rx.search(s) for rx in d.patterns]
            ms = [m for m in ms if m]
            if ms:
                m = ms[0]
                dim_rows.append((r.y, _x_of(spans, m.start(), m.end()), d.dimension, r.toks[0][0]))
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
                        all_dims.append((r.y, xc_, d.dimension))

    def col_dim(hy, x):
        """Segment named in the heading band just above (or on) the period header row, nearest in x to the column."""
        near = [(abs(xc - x), dn) for (dy, xc, dn) in all_dims if hy - 60 <= dy <= hy + 6 and abs(xc - x) <= 90]
        return min(near)[1] if near else None

    def nearest_dim(y, own_text, label_x, hdr=None, x=None):
        for d in dims:
            if d.companies and company not in d.companies:
                continue
            if d.dimension != "total" and any(rx.search(own_text) for rx in d.patterns):
                return d.dimension
        if hdr is not None and x is not None:
            cd = col_dim(rows[hdr].y, x)
            if cd:
                return cd
        left = [(dy, dn) for (dy, dx, dn, fx) in dim_rows if fx < label_x - 40 and dx is not None]
        if left:   # left-margin block headings sit on the block's last row: take the first heading at or below
            below = [(dy, dn) for dy, dn in left if dy >= y - 12]
            if below and min(below)[0] - y < 200:
                return min(below)[1]
        best, bd = "total", 10 ** 9
        for (dy, dx, dn, fx) in dim_rows:
            if fx >= label_x - 40 and dy <= y + 1 and (y - dy) < bd and y - dy < 220:
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
        for m in VAL_RX.finditer(s):
            if any(a <= m.start("num") < b for a, b in pspans):
                continue
            xc = _x_of(spans, m.start(), m.end())
            if xc is not None:
                nums.append((xc, m))
        if not nums:
            continue
        label = s[:nums[0][1].start()].strip()
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
            for e, lm in hit:
                for xc, m, per in _assign_columns(nums, cols, 28):
                    dim = nearest_dim(r.y, label, r.toks[0][0], hi, xc)
                    unit = value_unit(m.group("cur"), m.group("suf"), e.kind, e.unit)
                    if unit is None and not (m.group("suf") or "").strip():   # a "%" / "x" token never borrows the label's unit
                        unit = _unit_from_label(label, e)
                    num = to_float(m.group("num"))
                    if unit is None or num is None:
                        continue
                    val, u, scale = finalize_unit(unit, num, e.unit)
                    q = _anchored_quote(text, label, m.group("num"), nth)
                    if not q:
                        continue
                    out.append(Row(e.metric, dim, val, u, scale, per.ptype, per.canon, per.as_of, basis, page, q, label,
                                   m.group("num"), "table_v1"))
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
        return "pct" if "%" in l or e.metric.endswith("_pct") else None
    if e.kind == "days":
        return "days"
    if e.kind == "count":
        return "count_mn" if re.search(r"\bmn\b|million", l) else ("count" if e.unit == "count" else None)
    if e.kind == "ratio":
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
def _open_pdf(sandbox: Path, sym: str, doc_key: str):
    p = sandbox / f"{COMPANIES[sym]}_loop" / "raw" / doc_key
    if not p.exists():
        return None
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz
    try:
        return fitz.open(str(p))
    except Exception:
        return None


RAW_ROOT = Path("D:/RealityEngine/raw")


def _doc_sources(con, sym: str, sandbox: Path, raw_root: Path | None, limit_docs: int | None, st: dict, ocr: dict | None = None):
    """Yield (doc_key, doc_type, known_at, usable_pages, pdf_or_None, tag). Sandbox docs first, then (optional) the
    decks that deck_figures cites but docs does not hold (read straight from the text layer of the raw PDF).
    ocr = {doc_key: {page: (text, words, conf)}} from pilot3.ocr: those pages are added to usable (text = OCR text)
    and the 6th item yielded is the {page: ...} dict of the pages read by OCR."""
    ocr = ocr or {}
    docs = con.execute(
        f"SELECT doc_key, doc_type, known_at FROM docs WHERE doc_type IN ({','.join('?' * len(KPI_DOC_TYPES))}) ORDER BY known_at",
        KPI_DOC_TYPES).fetchall()
    if limit_docs:
        docs = docs[:limit_docs]
    for doc_key, doc_type, known_at in docs:
        pages = con.execute("SELECT page, text, method FROM doc_text WHERE doc_key=? ORDER BY page", (doc_key,)).fetchall()
        if not pages:
            continue
        st["docs"] += 1
        st["needs_ocr"] += sum(1 for _, _, m in pages if m == "needs_ocr")
        usable = [(p, t) for p, t, m in pages if m == "script_text" and t]
        pdf = _open_pdf(sandbox, sym, doc_key) if doc_type in PDF_DOC_TYPES else None
        if pdf is None and doc_type in PDF_DOC_TYPES:
            st["pdf_missing"] += 1
        opg = ocr.get(doc_key, {})
        if opg:
            have = {p for p, _ in usable}
            usable = sorted(usable + [(p, v[0]) for p, v in opg.items() if p not in have and v[0]])
            st["ocr_pages_used"] = st.get("ocr_pages_used", 0) + len([p for p in opg if p not in have])
        yield doc_key, doc_type, known_at, usable, pdf, opg
        if pdf is not None:
            pdf.close()
    if raw_root is None:
        return
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz
    held = {r[0] for r in con.execute("SELECT source_key FROM docs WHERE source_key IS NOT NULL")}
    extra = con.execute("SELECT sha256, min(known_at) FROM deck_figures GROUP BY sha256 ORDER BY 2").fetchall()
    for sha, known_at in extra:
        if sha in held:
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
        yield key, "deck", known_at, usable, pdf, opg
        pdf.close()


def extract_company(sym: str, sandbox: Path, stats: dict, limit_docs: int | None = None, raw_root: Path | None = None,
                    ocr: dict | None = None, only_docs: list[str] | None = None):
    dbp = sandbox / f"{COMPANIES[sym]}_loop" / f"{COMPANIES[sym]}.db"
    con = sqlite3.connect(f"file:{dbp.as_posix()}?mode=ro", uri=True)
    entries, dims = load_lexicon()
    st = stats.setdefault(sym, {"pages": 0, "needs_ocr": 0, "docs": 0, "pdf_missing": 0})
    for doc_key, doc_type, known_at, usable, pdf, opg in _doc_sources(con, sym, sandbox, raw_root, limit_docs, st, ocr):
        if only_docs and not any(k in doc_key for k in only_docs):
            continue
        default_pers = doc_default_period([t for _, t in usable])
        for page, text in usable:
            st["pages"] += 1
            try:
                srows = sentence_rows(text, page, sym, entries, dims, default_pers)
            except Exception:  # keep the run going, count it
                srows = []
                st["errors"] = st.get("errors", 0) + 1
            trows: list[Row] = []
            method, ocr_conf = "text_layer", None
            words = None
            if page in opg:                      # page read by OCR: word boxes come from the stored OCR, not the PDF
                method, ocr_conf = "ocr_rapid", opg[page][2]
                words = opg[page][1]
                st["ocr_pages"] = st.get("ocr_pages", 0) + 1
            elif pdf is not None and 0 < page <= pdf.page_count and _page_may_have_table(text):
                words = pdf[page - 1].get_text("words")
            if words is not None and _page_may_have_table(text):
                try:
                    trows = table_and_chart_rows(words, text, page, sym, entries, dims, default_pers)
                except Exception:
                    st["errors"] = st.get("errors", 0) + 1
            if trows:   # on a table page, running-text hits that span line breaks are table fragments: drop them
                srows = [r for r in srows if "\n" not in r.quote]
            for r in sorted(srows + trows, key=lambda r: -RULE_CONF[r.rule][1]):   # best confidence first: INSERT OR IGNORE keeps it
                yield dict(symbol=sym, metric=r.metric, dimension=r.dimension, value=r.value, unit=r.unit, scale=r.scale,
                           period_type=r.period_type, fiscal_period=r.fiscal_period, as_of_date=r.as_of, basis=r.basis,
                           doc_key=doc_key, page=page, quote=r.quote, known_at=known_at,
                           known_at_source="docs.known_at" if not doc_key.startswith("decks_full/") else "deck_figures.known_at",
                           is_reported=1, raw_label=r.raw_label, raw_value=r.raw_value, extractor_rule=r.rule,
                           confidence=RULE_CONF[r.rule][0], conf_rank=RULE_CONF[r.rule][1], method=method, ocr_conf=ocr_conf)
    con.close()


def _page_may_have_table(text: str) -> bool:
    return len(parse_periods(text)) >= 2


COLS = ("symbol metric dimension value unit scale period_type fiscal_period as_of_date basis doc_key page quote "
        "known_at known_at_source is_reported raw_label raw_value extractor_rule confidence conf_rank method ocr_conf").split()


def run(out: str, symbols: list[str], sandbox: Path, limit_docs: int | None = None, raw_root: Path | None = None,
        ocr_db: str | Path | list | tuple | None = None, only_docs: list[str] | None = None) -> dict:
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
    sql = f"INSERT OR IGNORE INTO kpi_series({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})"
    for sym in symbols:
        con.execute("DELETE FROM kpi_series WHERE symbol=?", (sym,))
        batch = []
        ocr = None
        if ocr_cons:
            from reality_engine.pilot3.ocr import load_ocr

            ocr = {}
            for c in ocr_cons:
                for doc_key, pages in load_ocr(c, sym).items():
                    ocr.setdefault(doc_key, {}).update(pages)
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='doc_alias'").fetchone():
                for alias_key, doc_key in con.execute("SELECT alias_key, doc_key FROM doc_alias WHERE symbol=?", (sym,)):
                    if doc_key in ocr and alias_key not in ocr:   # an OCR page under the pilot3 key serves its sandbox key
                        ocr[alias_key] = ocr[doc_key]
        for row in extract_company(sym, sandbox, stats, limit_docs, raw_root, ocr, only_docs):
            batch.append([row[c] for c in COLS])
            if len(batch) >= 2000:
                con.executemany(sql, batch)
                batch = []
        if batch:
            con.executemany(sql, batch)
        con.commit()
        stats[sym]["rows"] = con.execute("SELECT count(*) FROM kpi_series WHERE symbol=?", (sym,)).fetchone()[0]
    stats["seconds"] = round(time.time() - t0, 1)
    con.close()
    for c in ocr_cons:
        c.close()
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default="KEC,BAJFINANCE,HINDALCO")
    ap.add_argument("--sandbox-root", default=str(SANDBOX_ROOT))
    ap.add_argument("--limit-docs", type=int, default=None)
    ap.add_argument("--raw-root", default=str(RAW_ROOT), help="also read the decks deck_figures cites but docs does not hold (text layer only); '' to disable")
    ap.add_argument("--ocr-db", action="append", default=None, help="ocr_page table written by pilot3.ocr: its pages are read too (repeat for one per company)")
    ap.add_argument("--only-docs", default=None, help="comma list of doc_key substrings (debug: read only these documents)")
    a = ap.parse_args(argv)
    stats = run(a.out, [s.strip().upper() for s in a.symbols.split(",") if s.strip()], Path(a.sandbox_root), a.limit_docs,
                Path(a.raw_root) if a.raw_root else None, a.ocr_db, [x for x in (a.only_docs or "").split(",") if x] or None)
    for k, v in stats.items():
        print(k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
