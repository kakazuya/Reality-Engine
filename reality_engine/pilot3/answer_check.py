"""Answer check (T-049 F, guide O5): how many of the 300 pilot questions the pilot3 database answers.

Oracle: the newest ``answers`` row per qid of the three sandboxes.  The rows whose status is ``answered``
passed the gap loop's checks (251 of 300 on 3 Nov 2026) and are the test set; every other question is still
mapped and called, so a question the loop could not answer but pilot3 can is visible, not lost.

Each question is mapped by fixed rules -- over the question text and the table its oracle number cites -- to
ONE call of ``plugins/reality-data/server/lookups_pilot3.py``, the same functions the reality-data MCP server
runs, against ``--db`` (default the real ``reality_engine\\data\\pilot3\\pilot3.db``), with ``as_of`` = the
question's as_of or 2026-10-19.  Every number in the oracle answer must occur in the reply within the loop's
rounding (``gap_loop.checks``: Indian digit grouping, crore/lakh/million scale) in the same period.

    python -m reality_engine.pilot3.answer_check --db .tmp\\pilot3.db \\
        --out .tmp\\ANSWERABILITY.xlsx --html .tmp\\ANSWERABILITY.html
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from reality_engine.db.readonly import connect_ro
from reality_engine.gap_loop import checks, company, loop
from reality_engine.pilot3 import REAL_DB, SYMBOLS, oracle as oracle_mod

AS_OF = "2026-10-19"
PASSED = "answered"  # the loop's status for a row whose numbers all passed its checks
SANDBOXES = Path(r"D:\RealityEngine\sandbox")
OUT = Path(r"D:\RealityEngine\pilot3\ANSWERABILITY.xlsx")
HTML = OUT.with_suffix(".html")
LIMIT = 50  # rows per lookup call: the comparison should not fail because of the default page size
CLASSES = ("match", "partial", "mismatch", "empty", "answered_no_oracle", "no_tool")
CLASS_HELP = {
    "match": "every oracle number found in the reply, same period",
    "partial": "some oracle numbers found",
    "mismatch": "the reply has rows but no oracle number matches",
    "empty": "the mapped call returned no rows",
    "answered_no_oracle": "the loop did not answer this question; the call returned rows",
    "no_tool": "no rule mapped the question to a lookup",
}
TOOL_CALL = {"pilot3_kpi": "kpi", "pilot3_fin": "fin", "pilot3_ratio": "ratio", "pilot3_holding": "holding",
             "pilot3_statements": "statements", "pilot3_docs": "docs", "pilot3_search": "search",
             "pilot3_sql": "sql"}
TABLE_TOOL = {"px_nse": "pilot3_sql", "px_bse": "pilot3_sql", "shp_index": "pilot3_holding",
              "deck_figures": "pilot3_kpi", "formulas": "pilot3_ratio", "ar_facts": "pilot3_fin",
              "results_quarterly": "pilot3_fin", "row_facts": "pilot3_fin", "facts": "pilot3_fin",
              "announcements": "pilot3_search", "concall_items": "pilot3_statements", "doc": "pilot3_search"}
MONTHS = {m: i + 1 for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
STOP = set("""what which was were did does do the its in on for of and to at by from as is are how why when
who with that this it a an ltd limited per cent percent year years latest reported report company consolidated
standalone india indian during give given made make said say says also into over after before between each
compared compare value values quarter quarters end ended full total share shares price prices""".split())
VALUATION = ((r"market cap", "market_cap"), (r"price[- ]to[- ]book|\bp/?b\b", "pb"),
             (r"price[- ]to[- ]earnings|\bp/?e\b", "pe"), (r"ev[- ]to[- ]ebitda|ev/ebitda", "ev_ebitda"),
             (r"dividend yield", "dividend_yield_pct"))
SPEECH = re.compile(r"\b(say|said|says|saying|state|stated|states|guide|guided|guidance|outlook|comment"
                    r"|according to|reason|reasons|why)\b", re.I)
ANNOUNCE = re.compile(r"\b(announc\w*|disclos\w*|press release|board meeting|annual general meeting|\bagm\b"
                      r"|record date|fund raise|stock split|bonus issue|rating action|acquire\w*|acquisition"
                      r"|joint venture|orders? (?:won|win|winning)|list the)\b", re.I)
HOLDING = re.compile(r"promoter holding|shareholding pattern|\bshp\b|promoter group|mutual funds?"
                     r"|foreign portfolio|\bfpi\b|\bfii\b|holding of |holding at the end|stake of ", re.I)
# (regex, store name) -- first match wins; the store is chosen by _store_for() from which tables hold the name.
MEASURES: tuple[tuple[str, str], ...] = (
    (r"order book (?:plus|and|&) ?l1|order book[^.]{0,20}\bl1\b", "order_book_l1"),
    (r"international share|share of (?:the )?order book[^.]{0,40}international|order book[^.]{0,40}international",
     "order_book_international_share"),
    (r"order book|order backlog|order pipeline", "order_book"),
    (r"order intake|order inflow|order wins? (?:value|worth)", "order_intake"),
    (r"revenue[^.]{0,40}(?:growth|grew|grow)|growth[^.]{0,40}revenue|revenue grow", "revenue_growth_yoy_pct"),
    (r"(?:profit after tax|\bpat\b)[^.]{0,40}(?:growth|grew|grow)|(?:growth|grew)[^.]{0,30}\bpat\b",
     "pat_growth_yoy_pct"),
    (r"\baum\b|assets under management", "aum"),
    (r"gross npa|\bgnpa\b|gross non[- ]performing", "gnpa_pct"),
    (r"net npa|\bnnpa\b", "nnpa_pct"),
    (r"net interest margin|\bnim\b", "nim_pct"),
    (r"cost of funds", "cost_of_funds_pct"),
    (r"credit cost", "credit_cost_bps"),
    (r"new loans", "new_loans"),
    (r"customer franchise", "customer_franchise"),
    (r"(?:new|added) customers", "customers_added"),
    (r"ebitda (?:per|/|a) ?(?:tonne|ton)\b", "ebitda_per_tonne"),
    (r"shipments?", "shipments_kt"),
    (r"metal production|primary aluminium|alumina (?:production|output|refining)", "production_kt"),
    (r"provision coverage|\bpcr\b", "pcr_stage3"),
    (r"capital adequacy|\bcrar\b", "crar_pct"),
    (r"tier[- ]?1", "tier1_pct"),
    (r"deposit book|deposits?", "deposits"),
    (r"utilisation|utilization", "utilisation"),
    (r"capacity", "capacity"),
    (r"cost of production", "cost_of_production"),
    (r"net debt to ebitda|net debt/ebitda", "net_debt_to_ebitda"),
    (r"debt to equity|debt/equity|gearing", "debt_to_equity"),
    (r"return on capital employed|\broce\b", "roce"),
    (r"return on equity|\broe\b", "roe"),
    (r"return on assets|\broa\b", "roa"),
    (r"book value per share|\bbvps\b", "book_value_per_share"),
    (r"dividend payout|payout ratio", "dividend_payout_pct"),
    (r"dividend per share|\bdps\b", "dividend_per_share"),
    (r"diluted eps|diluted earnings", "eps_diluted"),
    (r"\beps\b|earnings per share", "eps_basic"),
    (r"interest coverage|ebitda[^.]{0,14}finance cost", "interest_coverage"),
    (r"net working capital days|working capital days", "net_working_capital_days"),
    (r"receivables? (?:in|of|as) days|receivable days|debtor days", "receivable_days"),
    (r"pat margin|net profit margin|net margin", "pat_margin_pct"),
    (r"ebitda margin|operating margin|opm", "ebitda_margin_pct"),
    (r"ebit margin", "ebit_margin_pct"),
    (r"net interest income|\bnii\b", "net_interest_income"),
    (r"total income", "total_income"),
    (r"revenue from operations|revenue|turnover|topline", "revenue_from_operations"),
    (r"profit after tax|\bpat\b|profit for the (?:period|year)", "pat"),
    (r"profit before tax|\bpbt\b", "pbt"),
    (r"finance cost|interest cost|interest expense", "finance_cost"),
    (r"depreciation", "depreciation"),
    (r"impairment|loan loss|provisions?", "impairment_financial_instruments"),
    (r"capital expenditure|\bcapex\b", "capex"),
    (r"cash flow from operations|operating cash flow|operating activities|cash generated from operations",
     "cash_flow_from_operations"),
    (r"net debt", "net_debt"),
    (r"borrowings?", "total_borrowings"),
    (r"net worth|shareholders?[’' ]?equity|total equity", "net_worth"),
    (r"total assets", "total_assets"),
    (r"trade receivables|receivables", "trade_receivables"),
    (r"inventories|inventory", "inventories"),
    (r"employees|headcount|workforce", "employees"),
    (r"\bebitda\b", "ebitda"),
)
TOPICS = ("margin", "guidance", "capex", "order", "demand", "debt", "growth", "volume", "price", "cost",
          "aum", "credit", "acquisition", "dividend", "rating")
_UNIT_BY_COLUMN = {"close": "inr", "open": "inr", "high": "inr", "low": "inr", "prev_close": "inr",
                   "adj_close": "inr", "value_inr": "inr", "delivery_pct": "pct", "volume": "number",
                   "deliverable_qty": "number", "num_trades": "number", "sessions": "number",
                   "avg_delivery_pct": "pct", "avg_deliverable_qty": "number", "avg_volume": "number"}


# --- the lookups, with the db the brief names ------------------------------------------------------
def lookups():
    """``lookups_pilot3`` from the MCP server directory (the module the reality-data server runs)."""
    server = Path(__file__).resolve().parents[2] / "plugins" / "reality-data" / "server"
    if str(server) not in sys.path:
        sys.path.insert(0, str(server))
    import lookups_pilot3  # noqa: PLC0415 -- only needed when a call is made

    return lookups_pilot3


@contextmanager
def on_db(path: Path):
    """Point the lookups at ``path`` for the block (they read REALITY_PILOT3_DB), then restore."""
    p3 = lookups()
    previous = os.environ.get("REALITY_PILOT3_DB")
    p3.close()
    os.environ["REALITY_PILOT3_DB"] = str(path)
    try:
        yield p3
    finally:
        p3.close()
        if previous is None:
            os.environ.pop("REALITY_PILOT3_DB", None)
        else:
            os.environ["REALITY_PILOT3_DB"] = previous


# --- inputs -----------------------------------------------------------------------------------------
def load_questions(sandbox: Path, symbols: tuple = SYMBOLS) -> dict[str, dict]:
    """The question files the loop read (``gap_loop.loop.load_questions``), keyed by qid, with the symbol."""
    out: dict[str, dict] = {}
    for symbol in symbols:
        company.activate(symbol)
        for row in loop.load_questions(Path(sandbox) / f"{symbol.lower()}_loop"):
            row["symbol"] = symbol
            out[row["id"]] = row
    company.activate(company.DEFAULT)
    return out


def load_answers(sandbox: Path, symbols: tuple = SYMBOLS) -> dict[str, dict]:
    """The newest ``answers`` row per qid (any status): qid -> status, numbers, answer text."""
    out: dict[str, dict] = {}
    for symbol in symbols:
        path = Path(sandbox) / f"{symbol.lower()}_loop" / f"{symbol.lower()}.db"
        if not path.is_file():
            raise SystemExit(f"STOPPED sandbox database missing: {path}")
        con = connect_ro(path)
        try:
            for qid, status, blob in con.execute("SELECT qid, status, answer_json FROM answers ORDER BY round, rowid"):
                try:
                    payload = json.loads(blob) or {}
                except (TypeError, ValueError):
                    payload = {}
                out[qid] = {"symbol": symbol, "status": status, "numbers": payload.get("numbers") or [],
                            "answer": payload.get("answer") or ""}
        finally:
            con.close()
    return out


def vocabulary(db: Path) -> dict[str, dict[str, dict[str, frozenset]]]:
    """``{symbol: {tool: {measure name: periods it holds}}}``: a name only counts for the store of the company
    that holds it, and a store that holds the name for the question's own period is preferred."""
    out: dict[str, dict[str, dict[str, set]]] = {}
    con = connect_ro(db)
    try:
        for symbol, metric, period in con.execute(
                "SELECT symbol, metric, fiscal_period FROM kpi_series GROUP BY 1, 2, 3"):
            out.setdefault(symbol, {}).setdefault("pilot3_kpi", {}).setdefault(metric, set()).add(period)
        for symbol, item, period in con.execute(
                "SELECT symbol, line_item, fiscal_year FROM fin_annual_line GROUP BY 1, 2, 3 UNION "
                "SELECT symbol, line_item, fiscal_period FROM fin_quarter_xbrl GROUP BY 1, 2, 3"):
            out.setdefault(symbol, {}).setdefault("pilot3_fin", {}).setdefault(item, set()).add(period)
        for symbol, metric, period in con.execute(
                "SELECT symbol, metric, fiscal_period FROM ratio_panel GROUP BY 1, 2, 3"):
            out.setdefault(symbol, {}).setdefault("pilot3_ratio", {}).setdefault(metric, set()).add(period)
    finally:
        con.close()
    for symbol, tools in out.items():
        for name in ("pe", "pb", "ev_ebitda", "market_cap", "dividend_yield_pct"):
            tools.setdefault("pilot3_ratio", {}).setdefault(name, set())
    return {symbol: {tool: {name: frozenset(p for p in periods if p) for name, periods in names.items()}
                     for tool, names in tools.items()} for symbol, tools in out.items()}


# --- dates and periods ------------------------------------------------------------------------------
def dates_in(text: str) -> list[str]:
    """``['2026-03-31', ...]`` for every date the question prints, in the order printed."""
    found: list[tuple[int, str]] = []
    for m in re.finditer(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", text):
        month = m.group(2).lower()[:3]
        if month in MONTHS:
            try:
                found.append((m.start(), date(int(m.group(3)), MONTHS[month], int(m.group(1))).isoformat()))
            except ValueError:
                pass
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        found.append((m.start(), m.group(0)))
    return [d for _pos, d in sorted(found)]


def month_in(text: str) -> str | None:
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})\b", text, re.I)
    return f"{m.group(2)}-{MONTHS[m.group(1).lower()[:3]]:02d}" if m else None


def periods_match(oracle_period: object, row_period: object) -> bool:
    """Same fiscal period?  A quarter-end date closes a quarter (and March closes the year); an unparsed
    period on either side is not judged."""
    first = oracle_mod.parse_period(oracle_period)
    second = oracle_mod.parse_period(row_period)
    if not first or not second:
        return True
    if first == second:
        return True
    if first[0] == "D" or second[0] == "D":
        day = first[1] if first[0] == "D" else second[1]
        closes = oracle_mod.fiscal_of(day)
        other = second if first[0] == "D" else first
        return bool(closes) and other[1] in closes
    return False


# --- numbers, with the loop's own normalisation -----------------------------------------------------
def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# The store's own scale wins when it is bigger than one (a kpi "inr_cr" row carries scale 1e7 and the value in
# crore); otherwise the unit name decides: "inr" is rupees, "inr_cr" crore, "kt" thousand tonnes.
_UNIT_FACTOR = {"kt": 1e3, "ktpa": 1e3, "mt": 1e6, "mtpa": 1e6, "count_mn": 1e6, "count_cr": 1e7,
                "million": 1e6, "mn": 1e6, "bn": 1e9, "billion": 1e9, "crore": 1e7, "cr": 1e7}


def to_base(value: float, unit: str, scale: float = 1.0) -> float | None:
    """A value in its base unit: rupees / USD / tonnes / count / percent ("23506 inr_cr" -> 2.3506e11)."""
    key = checks._norm_unit(unit)
    if checks.unit_family(key) == "money":
        if scale and scale > 1:
            return value * scale
        if key in checks._ABS_UNITS:
            return value * checks._ABS_UNITS[key]
        crore = checks._CRORE.get(key)
        return None if crore is None else value * crore * 1e7
    return value * (scale if scale and scale > 1 else _UNIT_FACTOR.get(key, 1.0))


def _currency(unit: str) -> str:
    return checks._currency(checks._norm_unit(unit))


def close_enough(left: float, right: float) -> bool:
    """The loop's tolerance, plus half a unit of the oracle's last printed decimal (answers are rounded)."""
    return checks._close(left, right) or abs(left - right) <= oracle_mod._half_unit(right) + 1e-9


def same_number(value: float, unit: str, other: float, other_unit: str, other_scale: float = 1.0) -> bool:
    """One oracle number against one value a lookup row holds (money across crore / million / rupee)."""
    mine, theirs = checks._norm_unit(unit), checks._norm_unit(other_unit)
    family = checks.unit_family(mine)
    if family != checks.unit_family(theirs):
        return False
    if family == "money" and _currency(mine) != _currency(theirs):
        return False
    left, right = to_base(value, mine), to_base(other, theirs, other_scale or 1.0)
    return left is not None and right is not None and close_enough(left, right)


def number_in_text(value: float, unit: str, text: str) -> bool:
    """The oracle number as the loop reads numbers in a quote (crore/lakh/million words, ₹ prefixes)."""
    key = checks._norm_unit(unit)
    if checks.unit_family(key) == "money" and key not in checks._ABS_UNITS:
        absolute = to_base(value, key)
        if absolute is not None and checks.check_number(absolute / 1e7, "inr_cr", text)[0]:
            return True
    return checks.check_number(value, key, text)[0]


def row_text(row: dict) -> str:
    return checks.normalise(" ".join(t for t in row.get("texts", ()) if t))


def find_number(value: float, number: dict, rows: list[dict]) -> dict | None:
    """The first reply row that carries the oracle number in the oracle number's period."""
    unit = str(number.get("unit") or "")
    period = number.get("period")
    for row in rows:
        if not periods_match(period, row.get("period")):
            continue
        for other, other_unit, other_scale in row.get("values", ()):
            if same_number(value, unit, other, other_unit, other_scale):
                return row
        text = row_text(row)
        if text and number_in_text(value, unit, text):
            return row
    return None


# --- the reply as rows ------------------------------------------------------------------------------
def row_value(value: object, unit: str | None, scale: object = 1.0) -> tuple | None:
    number = _as_float(value)
    if number is None or not unit:
        return None
    return (number, unit, _as_float(scale) or 1.0)


def reply_rows(tool: str, reply: dict) -> list[dict]:
    """Every reply row as {values, texts, period, provenance} whatever the tool returns."""
    if tool == "pilot3_sql":
        columns = reply.get("columns") or []
        out = []
        for raw in reply.get("rows") or []:
            record = dict(zip(columns, raw))
            values = [row_value(record[col], _UNIT_BY_COLUMN[col])
                      for col in columns if col in _UNIT_BY_COLUMN]
            out.append({"values": [v for v in values if v], "texts": [],
                        "period": next((record[c] for c in ("date", "month") if record.get(c)), None),
                        "provenance": {}})
        return out
    rows = []
    for row in reply.get("rows") or []:
        values = []
        if tool in ("pilot3_kpi", "pilot3_fin"):
            values = [row_value(row.get("value"), row.get("unit"), row.get("scale"))]
        elif tool == "pilot3_ratio":
            values = [row_value(row.get("value"), row.get("unit"))]
        elif tool == "pilot3_holding":
            values = [row_value(row.get("pct"), "pct"), row_value(row.get("shares"), "number")]
        rows.append({
            "values": [v for v in values if v],
            "texts": [str(row[key]) for key in ("quote", "snippet", "title", "statement")
                      if isinstance(row.get(key), str)],
            "period": row.get("period") or row.get("quarter_end") or row.get("date") or row.get("call_period"),
            "provenance": row.get("provenance") or {},
        })
    return rows


def provenance_of(row: dict | None) -> str:
    if not row or not row.get("provenance"):
        return ""
    prov = row["provenance"]
    bits = [str(prov["table"]) if prov.get("table") else "", str(prov.get("source") or ""),
            f"known_at={prov['known_at']}" if prov.get("known_at") else ""]
    return " | ".join(b for b in bits if b)


# --- the mapping rules ------------------------------------------------------------------------------
def _hint(numbers: list[dict]) -> str | None:
    """The tool whose store the oracle's own numbers came from (the loop says which table it used)."""
    seen = Counter(TABLE_TOOL.get(str(n.get("table") or ""), "") for n in numbers or ())
    seen.pop("", None)
    return seen.most_common(1)[0][0] if seen else None


def _keywords(text: str, symbol: str, n: int = 6) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z&.-]{3,}", text)
    out = []
    for word in words:
        key = word.lower().strip(".-")
        if key in STOP or key == symbol.lower() or key in out:
            continue
        out.append(key)
        if len(out) >= n:
            break
    return out


def _store_for(name: str, stores: dict, hint: str | None, period: str | None = None) -> str:
    """Which lookup holds a measure name: the store holding it for the question's period first, then the
    oracle's table, then the tools that best suit the name."""
    holds = [tool for tool in ("pilot3_kpi", "pilot3_fin", "pilot3_ratio") if name in stores.get(tool, {})]
    if not holds:
        return "pilot3_ratio" if name.endswith("_pct") else "pilot3_fin"
    if period:
        timed = [tool for tool in holds if period in stores[tool][name]]
        if len(timed) == 1:
            return timed[0]
        holds = timed or holds
    if name.endswith(("_pct", "_days", "_coverage")) and "pilot3_ratio" in holds:
        return "pilot3_ratio"  # the computed panel beats an extracted percentage of the same name
    if hint in holds:
        return hint
    order = ("pilot3_ratio", "pilot3_fin", "pilot3_kpi") if name.endswith(("_pct", "_days", "_coverage")) \
        else ("pilot3_fin", "pilot3_kpi", "pilot3_ratio")
    return next((tool for tool in order if tool in holds), holds[0])


def _name_by_words(text: str, stores: dict) -> str | None:
    """A stored measure name whose words the question uses ("net working capital days")."""
    words = {w.lower() for w in re.findall(r"[A-Za-z]+", text) if len(w) > 2}
    best: tuple | None = None
    for names in stores.values():
        for name in names:
            tokens = [t for t in name.split("_") if len(t) > 2]
            if not tokens:
                continue
            hits = sum(1 for token in tokens if token in words or token[:-1] in words)
            share = hits / len(tokens)
            if hits and share >= 0.5 and (best is None or (share, len(name)) > best[0]):
                best = ((share, len(name)), name)
    return best[1] if best else None


PERIOD_RE = re.compile(r"Q[1-4]\s*FY\s?'?\d{2,4}|H[12]\s*FY\s?'?\d{2,4}|\bFY\s?'?\d{2,4}\b", re.I)


def periods_in(text: str) -> list[tuple[str, str]]:
    """Every fiscal period the question names, in order ("FY25 ... Q1FY27")."""
    out: list[tuple[str, str]] = []
    for match in PERIOD_RE.finditer(text):
        period = oracle_mod.parse_period(match.group(0))
        if period and period not in out:
            out.append(period)
    return out


def _day_of(period: tuple[str, str] | None) -> str | None:
    if not period:
        return None
    try:
        return oracle_mod.to_date(period)
    except (IndexError, ValueError):
        return None


def _same_span(period: tuple[str, str], when: str) -> bool:
    """The period is the question's own, or a date inside it ("31 March 2026" closes FY26)."""
    if period[1] == when:
        return True
    if period[0] == "D":
        closes = oracle_mod.fiscal_of(period[1])
        return bool(closes) and when in closes
    return False


def _measure(text: str) -> str | None:
    """The measure asked: the alias that starts earliest, the more specific one when two start together."""
    best: tuple | None = None
    for pattern, name in MEASURES:
        match = re.search(pattern, text)
        if match and (best is None or (match.start(), -len(pattern)) < best[0]):
            best = ((match.start(), -len(pattern)), name)
    return best[1] if best else None


def _price_sql(text: str, symbol: str, as_of: str) -> str | None:
    """The one price_delivery query a share-price question needs (pilot3_sql is the price route)."""
    sym = symbol.upper()
    dates = dates_in(text)
    day = dates[-1] if dates else None
    where = f"symbol='{sym}' AND exchange='NSE'"
    if "deliver" in text:
        if "average" in text or re.search(r"\bavg\b", text):
            month = month_in(text) or (day or as_of)[:7]
            return (f"SELECT COUNT(*) AS sessions, ROUND(AVG(delivery_pct), 2) AS avg_delivery_pct, "
                    f"ROUND(AVG(deliverable_qty), 0) AS avg_deliverable_qty FROM price_delivery "
                    f"WHERE {where} AND substr(date, 1, 7) = '{month}'")
        if not day:
            return None
        return (f"SELECT date, close, volume, deliverable_qty, delivery_pct FROM price_delivery "
                f"WHERE {where} AND date = '{day}'")
    if "52" in text and "low" in text:
        day = day or as_of
        start = (date.fromisoformat(day) - timedelta(days=365)).isoformat()
        return (f"SELECT date, low, close FROM price_delivery WHERE {where} "
                f"AND date BETWEEN '{start}' AND '{day}' ORDER BY low ASC LIMIT 1")
    if "highest" in text or ("high" in text and "price" in text):
        day = day or as_of
        return (f"SELECT date, high, close FROM price_delivery WHERE {where} "
                f"AND date BETWEEN '{day[:4]}-01-01' AND '{day}' ORDER BY high DESC LIMIT 1")
    if "return" in text and len(dates) >= 2:
        return (f"SELECT date, close, adj_close FROM price_delivery WHERE {where} "
                f"AND date IN ('{dates[0]}', '{dates[-1]}') ORDER BY date")
    if day and re.search(r"sessions? after|days? after|day after|trading (?:day|session)s? after", text):
        return (f"SELECT date, close, prev_close FROM price_delivery WHERE {where} AND date > '{day}' "
                f"ORDER BY date LIMIT 4")
    if day and re.search(r"closing price|price on|share price|close", text):
        return (f"SELECT date, close, prev_close, volume, delivery_pct FROM price_delivery "
                f"WHERE {where} AND date = '{day}'")
    return None


def _basis(text: str) -> str | None:
    if "standalone" in text:
        return "standalone"
    if "consolidated" in text:
        return "consolidated"
    return None


def plan(question: dict, numbers: list[dict], vocab: dict, as_of: str = AS_OF) -> dict | None:
    """ONE lookup call for one question, from its text and the table its oracle number cites."""
    text = str(question.get("question") or "")
    low = text.lower()
    symbol = str(question.get("symbol") or "")
    kind = str(question.get("kind") or "").lower()
    stores = vocab.get(symbol, {})
    periods = periods_in(text)
    dates = dates_in(text)
    stated = bool(re.search(r"\bas (?:of|at)\b", low))
    # "as of <day>" is a cut-off, not a fiscal period: ask for the latest row known by that day.
    as_of_call = dates[-1] if stated and dates else as_of
    when = periods[0][1] if len(periods) == 1 and not (stated and dates) else None
    # A balance-sheet question fixes its own date ("at the end of June 2026"): holding must use it.
    point = dates[-1] if dates else _day_of(periods[-1] if periods else oracle_mod.parse_period(text))
    hint = _hint(numbers)
    basis = _basis(low)
    arg_name = {"pilot3_kpi": "kpi", "pilot3_fin": "measure", "pilot3_ratio": "ratio"}
    # The loop's own answer rows say which periods it needed: a change over two years is not one period.
    oracle_periods = [p for p in (oracle_mod.parse_period(n.get("period")) for n in numbers or ()) if p]
    if when and oracle_periods and not all(_same_span(p, when) for p in oracle_periods):
        when = None

    def call(tool: str, why: str, **args) -> dict:
        return {"tool": tool, "args": {"symbol": symbol, **args}, "why": why}

    def measure_call(tool: str, name: str, why: str) -> dict:
        args = {"symbol": symbol, arg_name[tool]: name, "period": when, "as_of": as_of_call, "limit": LIMIT}
        if basis:
            args["basis"] = basis
        return {"tool": tool, "args": args, "why": why}

    def search_call(why: str) -> dict:
        return call("pilot3_search", why, query=" ".join(_keywords(text, symbol)), as_of=as_of_call)

    # 1. documents held
    if re.search(r"\b(what|which|how many) (documents|filings)\b|latest (deck|presentation|transcript|annual report)",
                 low):
        doc_type = ("deck" if re.search(r"deck|presentation", low) else
                    "transcript" if re.search(r"transcript|call", low) else
                    "annual_report" if "annual report" in low else None)
        return call("pilot3_docs", "documents question", doc_type=doc_type, as_of=as_of_call, limit=LIMIT)

    # 2. share price / delivery (pilot3_sql over price_delivery is the only price route)
    if re.search(r"closing price|share price|price on|price (?:move|return|rose|fell|rise|fall)|highest price"
                 r"|52[- ]week|deliver\w*|trading sessions?|price (?:to|jumped|moved)", low) or hint == "pilot3_sql":
        query = _price_sql(low, symbol, as_of_call)
        if query:
            return {"tool": "pilot3_sql", "args": {"query": query, "limit": 20},
                    "why": "price_delivery query from the question's date(s)"}

    # 3. valuation on a date
    for pattern, name in VALUATION:
        if re.search(pattern, low):
            day = (dates or [as_of_call])[-1]
            return call("pilot3_ratio", f"valuation field {name} on {day}", ratio=name, period=day,
                        as_of=as_of_call)

    # 4. what management said / guidance -> transcripts, else document text
    if SPEECH.search(low):
        topic = next((word for word in TOPICS if re.search(rf"\b{word}", low)), None)
        if "call" in low or "concall" in low or kind == "guidance" or hint == "pilot3_statements":
            return call("pilot3_statements", "management statement from a transcript", topic=topic,
                        as_of=as_of_call, limit=20)
        return search_call("what the documents say (text search)")

    # 5. announcements and corporate events
    if ANNOUNCE.search(low) or hint == "pilot3_search" or kind == "event":
        return search_call("announcement / event text")
    if re.search(r"\bcredit rating\b|\bratings?\b|\besg\b|sustainability rating", low):
        return search_call("rating text")

    # 6. shareholding: the quarter asked for is the quarter_end, the cut-off stays the question's as_of
    if HOLDING.search(low) or hint == "pilot3_holding":
        return call("pilot3_holding", "shareholding pattern for the quarter asked",
                    as_of=as_of_call, quarter_end=point)

    # 7. a measure the stores hold
    name = _measure(low)
    if name:
        tool = _store_for(name, stores, hint, when)
        # A derived question's answer row cites the inputs it used (revenue, finance cost): when the loop
        # named one such measure, ask for that measure -- the answer check says whether the cited numbers are
        # reachable, and for a derived question that is what the loop's own answer needed.
        if numbers and not any(name in stores.get(tool, {}) for tool in ("pilot3_fin", "pilot3_kpi")):
            cited = {found for number in numbers if (found := _measure(str(number.get("measure") or "")))}
            if len(cited) == 1:
                name = cited.pop()
                tool = _store_for(name, stores, hint, when)
        return measure_call(tool, name, f"measure {name!r} (question text), period {when or 'all'}")
    name = _name_by_words(low, stores)
    if name:
        tool = _store_for(name, stores, hint, when)
        return measure_call(tool, name, f"stored measure {name!r} matched by word, period {when or 'all'}")

    # 8. a text question with no measure in it
    if kind in ("text", "guidance", "ripple"):
        return search_call("text question -> document search")

    # 9. the oracle's own table names the store; ask it for the question's words
    if hint in ("pilot3_kpi", "pilot3_fin", "pilot3_ratio"):
        name = _name_by_words(low, {hint: stores.get(hint, ())}) or " ".join(_keywords(text, symbol, 3))
        return measure_call(hint, name, f"oracle cites this store; measure guessed {name!r}")
    if hint == "pilot3_statements":
        return call("pilot3_statements", "oracle cites transcripts", as_of=as_of_call, limit=20)
    if hint == "pilot3_search":
        return search_call("oracle cites documents")
    return None


# --- comparison and report --------------------------------------------------------------------------
def classify(tool: str, reply: dict | None, numbers: list[dict], passed: bool) -> dict:
    """The result class, the numbers found, the ones missing, and the row that carries the answer."""
    if reply is None:
        return {"class": "no_tool", "hit": [], "miss": [], "row": None, "rows": []}
    rows = reply_rows(tool, reply)
    answer = {"rows": rows, "row": rows[0] if rows else None}
    if not rows:
        return {"class": "empty", "hit": [], "miss": [], **answer}
    if not passed:
        return {"class": "answered_no_oracle", "hit": [], "miss": [], **answer}
    if not numbers:
        return {"class": "match", "hit": [], "miss": [], **answer}  # a text answer: the call returned rows
    hit, miss = [], []
    for number in numbers:
        value = _as_float(number.get("value"))
        row = find_number(value, number, rows) if value is not None else None
        (hit if row else miss).append((number, row))
    if not hit:
        return {"class": "mismatch", "hit": [], "miss": [n for n, _ in miss], **answer}
    if miss:
        return {"class": "partial", "hit": [n for n, _ in hit], "miss": [n for n, _ in miss],
                "row": hit[0][1] or answer["row"], "rows": rows}
    return {"class": "match", "hit": [n for n, _ in hit], "miss": [], "row": hit[0][1] or answer["row"],
            "rows": rows}


def numbers_text(numbers: list[dict]) -> str:
    bits = []
    for number in numbers or ():
        value = number.get("value")
        shown = f"{value:g}" if isinstance(value, (int, float)) else str(value)
        unit = number.get("unit") or ""
        period = number.get("period") or ""
        bits.append(f"{number.get('measure') or '?'}: {shown} {unit}" + (f" [{period}]" if period else ""))
    return "; ".join(bits)


def rows_text(rows: list[dict], n: int = 4) -> str:
    bits = []
    for row in rows[:n]:
        shown = ", ".join(f"{value:g} {unit}" for value, unit, _scale in row.get("values", ())[:3])
        bits.append(f"{shown} [{row.get('period') or ''}]" if row.get("period") else shown)
    return " | ".join(b for b in bits if b)


def evaluate(db: Path, sandbox: Path = SANDBOXES, as_of: str = AS_OF,
             symbols: tuple = SYMBOLS) -> dict:
    """Every question: its one mapped call, the comparison with the oracle, and the summary counts."""
    questions = load_questions(sandbox, symbols)
    answers = load_answers(sandbox, symbols)
    vocab = vocabulary(db)
    records: list[dict] = []
    errors = 0
    with on_db(db) as p3:
        for qid in sorted(set(questions) | set(answers)):
            question = questions.get(qid) or {"id": qid, "symbol": answers[qid]["symbol"], "question": "",
                                              "kind": "", "as_of": as_of}
            answer = answers.get(qid) or {"status": "", "numbers": [], "symbol": question.get("symbol")}
            numbers = answer.get("numbers") or []
            mapping = plan(question, numbers, vocab, str(question.get("as_of") or as_of))
            reply, error = None, ""
            if mapping:
                fn = getattr(p3, TOOL_CALL[mapping["tool"]])
                try:
                    reply = fn(**mapping["args"])
                except Exception as exc:  # noqa: BLE001 -- a failed call is a result, never a crash
                    error = f"{type(exc).__name__}: {str(exc)[:200]}"
                    errors += 1
            passed = answer.get("status") == PASSED
            verdict = classify(mapping["tool"], reply, numbers, passed) if mapping else classify("", None,
                                                                                               numbers, passed)
            records.append({
                "qid": qid, "company": str(question.get("symbol") or answer.get("symbol") or ""),
                "kind": question.get("kind") or "", "question": question.get("question") or "",
                "tool": mapping["tool"] if mapping else "", "arguments": json.dumps(mapping["args"], default=str)
                if mapping else "", "why": mapping["why"] if mapping else "no rule matched the question",
                "class": verdict["class"], "oracle_status": answer.get("status") or "",
                "oracle_numbers": numbers_text(numbers),
                "returned_numbers": rows_text(verdict["rows"]) if verdict["rows"] else "",
                "provenance": provenance_of(verdict["row"]), "error": error,
            })
    summary = summarise(records)
    summary["errors"] = errors
    summary["database"] = str(db)
    summary["sandbox"] = str(sandbox)
    summary["as_of"] = as_of
    summary["questions"] = len(records)
    summary["passed_oracle"] = sum(1 for r in records if r["oracle_status"] == PASSED)
    return {"records": records, "summary": summary}


def summarise(records: list[dict]) -> dict:
    """Counts per company and class, per tool and class, and the most common reason for no_tool / empty."""
    by_company: dict[str, Counter] = defaultdict(Counter)
    by_tool: dict[str, Counter] = defaultdict(Counter)
    reasons: Counter = Counter()
    reason_qids: dict[str, str] = {}
    for record in records:
        by_company[record["company"] or "?"][record["class"]] += 1
        by_tool[record["tool"] or "no_tool"][record["class"]] += 1
        if record["class"] == "no_tool":
            reason = f"no_tool [{record['kind'] or '-'}]: {record['question'][:80]}"
        elif record["class"] == "empty":
            reason = f"empty [{record['tool']}]: {record['arguments']}"
        else:
            continue
        reason = re.sub(r'"as_of": "[^"]*",? ?', "", reason)
        reasons[reason] += 1
        reason_qids.setdefault(reason, record["qid"])
    return {"by_company": {k: dict(v) for k, v in by_company.items()},
            "by_tool": {k: dict(v) for k, v in by_tool.items()},
            "reasons": [(reason, count, reason_qids[reason]) for reason, count in reasons.most_common(10)]}


# --- the two reports --------------------------------------------------------------------------------
def render(summary: dict) -> str:
    lines = [f"pilot3 answer check: {summary['questions']} questions, {summary['passed_oracle']} with a "
             f"loop-passing oracle answer; as_of {summary['as_of']}; db {summary['database']}"]
    head = f"{'company':<12}" + "".join(f"{name:>13}" for name in CLASSES) + f"{'total':>7}"
    lines.append(head)
    for company, counts in sorted(summary["by_company"].items()):
        total = sum(counts.values())
        lines.append(f"{company:<12}" + "".join(f"{counts.get(name, 0):>13}" for name in CLASSES) +
                     f"{total:>7}")
    lines.append("")
    lines.append(f"{'tool':<20}" + "".join(f"{name:>13}" for name in CLASSES) + f"{'total':>7}")
    for tool, counts in sorted(summary["by_tool"].items(), key=lambda kv: -sum(kv[1].values())):
        lines.append(f"{tool:<20}" + "".join(f"{counts.get(name, 0):>13}" for name in CLASSES) +
                     f"{sum(counts.values()):>7}")
    lines.append("")
    for reason, count, qid in summary.get("reasons") or ():
        lines.append(f"  {count:>3} x {reason}  (e.g. {qid})")
    if summary.get("errors"):
        lines.append(f"  {summary['errors']} call(s) raised")
    return "\n".join(lines)


def write_xlsx(path: Path, records: list[dict], summary: dict) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    sheet = wb.active or wb.create_sheet("answers")
    sheet.title = "answers"
    columns = ("qid", "company", "kind", "question", "tool", "arguments", "class", "oracle_status",
               "oracle_numbers", "returned_numbers", "provenance", "why", "error")
    widths = {"qid": 15, "company": 11, "kind": 9, "question": 60, "tool": 18, "arguments": 46, "class": 16,
              "oracle_status": 11, "oracle_numbers": 40, "returned_numbers": 40, "provenance": 46, "why": 34,
              "error": 30}
    sheet.append([name.replace("_", " ") for name in columns])
    for record in records:
        sheet.append([record.get(name) or "" for name in columns])
    head_fill = PatternFill("solid", fgColor="DDE4EE")
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = head_fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for index, name in enumerate(columns, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = widths[name]
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = sheet.dimensions

    summary_sheet = wb.create_sheet("summary")
    summary_sheet.append(["pilot3 answer check"])
    for line in (f"database: {summary['database']}", f"sandboxes: {summary['sandbox']}",
                 f"as of: {summary['as_of']}", f"questions: {summary['questions']}",
                 f"oracle answers that passed the loop's checks: {summary['passed_oracle']}"):
        summary_sheet.append([line])
    summary_sheet.append([])
    matrix_head = ["company", *CLASSES, "total"]
    summary_sheet.append(matrix_head)
    for company, counts in sorted(summary["by_company"].items()):
        summary_sheet.append([company, *[counts.get(name, 0) for name in CLASSES], sum(counts.values())])
    summary_sheet.append(["total", *[sum(c.get(name, 0) for c in summary["by_company"].values())
                                     for name in CLASSES],
                          sum(sum(c.values()) for c in summary["by_company"].values())])
    summary_sheet.append([])
    summary_sheet.append(["tool", *CLASSES, "total"])
    for tool, counts in sorted(summary["by_tool"].items(), key=lambda kv: -sum(kv[1].values())):
        summary_sheet.append([tool, *[counts.get(name, 0) for name in CLASSES], sum(counts.values())])
    summary_sheet.append([])
    summary_sheet.append(["what each class means"])
    for name in CLASSES:
        summary_sheet.append([name, CLASS_HELP[name]])
    summary_sheet.append([])
    summary_sheet.append(["most common reasons for no_tool / empty", "count", "example qid"])
    for reason, count, qid in summary.get("reasons") or ():
        summary_sheet.append([reason, count, qid])
    for cell in summary_sheet[1]:
        cell.font = Font(bold=True, size=13)
    for row in summary_sheet.iter_rows():
        row[0].alignment = Alignment(wrap_text=True, vertical="top")
    summary_sheet.column_dimensions["A"].width = 74
    for letter in "BCDEFG":
        summary_sheet.column_dimensions[letter].width = 15
    wb.save(path)
    return path


_COLOURS = {"match": "#2f7d3a", "partial": "#c98a12", "mismatch": "#b23c3c", "empty": "#8a8a8a",
            "answered_no_oracle": "#5a6b8c", "no_tool": "#d9d9d9"}


def write_html(path: Path, records: list[dict], summary: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    esc = html.escape
    parts = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>pilot3 answer check</title><style>
body{{font:14px/1.45 Segoe UI,Arial,sans-serif;margin:24px;color:#1a1a1a;background:#fff}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:16px;margin:26px 0 8px}}
table{{border-collapse:collapse;margin:6px 0 14px}} th,td{{border:1px solid #ccc;padding:5px 9px;text-align:right}}
th:first-child,td:first-child{{text-align:left}} th{{background:#eef1f6}}
.bar{{display:flex;height:26px;width:100%;border:1px solid #bbb;margin:2px 0 12px;background:#f6f6f6}}
.bar div{{color:#fff;font-size:12px;text-align:center;line-height:26px;overflow:hidden;white-space:nowrap}}
.label{{font-weight:600;margin-top:10px}} .legend span{{display:inline-block;margin-right:14px;font-size:12px}}
.sw{{display:inline-block;width:11px;height:11px;margin-right:4px;vertical-align:-1px}}
.meta{{color:#555;font-size:12px}} tr.q td{{text-align:left;font-size:12px}} tr.q td.n{{text-align:right}}
</style></head><body>
<h1>pilot3 answer check</h1>
<p class="meta">database: {esc(summary['database'])}<br>sandboxes: {esc(summary['sandbox'])} &middot;
as of {esc(summary['as_of'])} &middot; {summary['questions']} questions &middot;
{summary['passed_oracle']} with an oracle answer that passed the gap loop's checks</p>
<div class="legend">""" + "".join(
        f'<span><i class="sw" style="background:{_COLOURS[name]}"></i>{esc(name)}</span>' for name in CLASSES) +
        "</div>"]

    parts.append("<h2>Result classes per company</h2>")
    for company, counts in sorted(summary["by_company"].items()):
        total = sum(counts.values()) or 1
        segments = "".join(
            f'<div style="background:{_COLOURS[name]};width:{100 * counts.get(name, 0) / total:.1f}%">'
            f'{counts.get(name, 0) if counts.get(name, 0) / total > 0.05 else ""}</div>' for name in CLASSES)
        parts.append(f'<div class="label">{esc(company)} ({total} questions)</div>')
        parts.append(f'<div class="bar" title="{esc(company)}">{segments}</div>')
        parts.append("<table><tr><th>class</th>" + "".join(f"<th>{esc(name)}</th>" for name in CLASSES) +
                     "<th>total</th></tr><tr><td>count</td>" +
                     "".join(f"<td>{counts.get(name, 0)}</td>" for name in CLASSES) + f"<td>{total}</td></tr></table>")

    parts.append("<h2>Per tool</h2><table><tr><th>tool</th>" +
                 "".join(f"<th>{esc(name)}</th>" for name in CLASSES) + "<th>total</th></tr>")
    for tool, counts in sorted(summary["by_tool"].items(), key=lambda kv: -sum(kv[1].values())):
        parts.append(f"<tr><td>{esc(tool)}</td>" +
                     "".join(f"<td>{counts.get(name, 0)}</td>" for name in CLASSES) +
                     f"<td>{sum(counts.values())}</td></tr>")
    parts.append("</table>")

    parts.append("<h2>Why questions went unmapped or came back empty</h2><table>"
                 "<tr><th>reason</th><th>count</th><th>example qid</th></tr>")
    for reason, count, qid in summary.get("reasons") or ():
        parts.append(f"<tr><td>{esc(reason)}</td><td>{count}</td><td>{esc(qid)}</td></tr>")
    parts.append("</table>")

    parts.append("<h2>Every question</h2><table><tr><th>qid</th><th>class</th><th>tool</th>"
                 "<th>arguments</th><th>oracle numbers</th><th>returned numbers</th><th>provenance</th></tr>")
    for record in records:
        colour = _COLOURS.get(record["class"], "#ffffff")
        parts.append(
            f'<tr class="q"><td>{esc(record["qid"])}</td>'
            f'<td><span class="sw" style="background:{colour}"></span>{esc(record["class"])}</td>'
            f'<td>{esc(record["tool"])}</td><td class="n">{esc(record["arguments"])}</td>'
            f'<td class="n">{esc(record["oracle_numbers"] or "none")}</td>'
            f'<td class="n">{esc(record["returned_numbers"] or record["error"] or "")}</td>'
            f'<td>{esc(record["provenance"])}</td></tr>')
        parts.append(f'<tr class="q"><td></td><td colspan="6" style="color:#444">'
                     f'{esc(record["question"])}</td></tr>')
    parts.append("</table></body></html>")
    path.write_text("".join(parts), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(REAL_DB), help=f"pilot3 database (default: {REAL_DB})")
    parser.add_argument("--sandboxes", default=str(SANDBOXES),
                        help="folder holding <sym>_loop/<sym>.db and its questions/")
    parser.add_argument("--as-of", default=AS_OF)
    parser.add_argument("--symbols", default=",".join(SYMBOLS), help="comma list to check (default: all three)")
    parser.add_argument("--out", default=str(OUT), help=f"xlsx report (default: {OUT})")
    parser.add_argument("--html", default=str(HTML), help=f"html summary (default: {HTML})")
    args = parser.parse_args(argv)
    db = Path(args.db).expanduser()
    if not db.is_file():
        raise SystemExit(f"STOPPED pilot3 database missing: {db}")
    symbols = tuple(part.strip().upper() for part in args.symbols.split(",") if part.strip())
    result = evaluate(db, Path(args.sandboxes), args.as_of, symbols)
    records, summary = result["records"], result["summary"]
    print(render(summary))
    print(f"wrote {write_xlsx(Path(args.out).expanduser(), records, summary)}")
    print(f"wrote {write_html(Path(args.html).expanduser(), records, summary)}")


if __name__ == "__main__":
    main()
