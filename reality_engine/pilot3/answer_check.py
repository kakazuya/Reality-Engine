"""Answer check (T-049 F, guide O5): how many of the 300 pilot questions the pilot3 database answers.

Oracle: the newest ``answers`` row per qid of the three sandboxes.  The rows whose status is ``answered``
passed the gap loop's checks (251 of 300 on 3 Nov 2026) and are the test set; every other question is still
mapped and called, so a question the loop could not answer but pilot3 can is visible, not lost.

Each question is mapped by fixed rules -- over the question text and the table its oracle number cites -- to
ONE call of ``plugins/reality-data/server/lookups_pilot3.py``, the same functions the reality-data MCP server
runs, against ``--db`` (default the real ``reality_engine\\data\\pilot3\\pilot3.db``), with ``as_of`` = the
question's as_of or 2026-10-19.

THE ANSWER IS GRADED, NOT ITS INPUTS (T-049 F, 3 Nov 2026).  The loop's ``numbers[]`` are often the inputs of
a derived answer -- two revenues for a growth, revenue and finance cost for a cover, a price and a share count
for a market cap -- while the lookup returns the computed value, so no cited number matches and 111 of 300
questions read ``mismatch``.  For a question whose answer is derived (growth, share, margin, ratio,
difference, sum, CAGR) the check recomputes the value from the oracle's cited inputs, recomputes it from what
the reply holds (the ratio it returns, or the inputs it returns) and compares those two with the loop's own
tolerance (``gap_loop.checks``).  ``compared_on`` says which comparison decided the class, and ``cited_class``
keeps the old cited-number comparison beside it: nothing is hidden and no tolerance is loosened.

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
from reality_engine.pilot3 import REAL_DB, oracle as oracle_mod, profile, queries, transcripts

AS_OF = "2026-10-19"
PASSED = "answered"  # the loop's status for a row whose numbers all passed its checks
SANDBOXES = Path(r"D:\RealityEngine\sandbox")
OUT = Path(r"D:\RealityEngine\pilot3\ANSWERABILITY.xlsx")
HTML = OUT.with_suffix(".html")
LIMIT = 50  # rows per lookup call: the comparison should not fail because of the default page size
CLASSES = ("match", "partial", "mismatch", "empty", "answered_no_oracle", "no_tool")
CLASS_HELP = {
    "match": "the answer agrees: the derived value on both sides (compared_on=derived), or every oracle "
             "number found in the reply in the same period (compared_on=cited)",
    "partial": "some of the answer agrees: some derived values agree, or some oracle numbers are found",
    "mismatch": "the reply has rows but the answer disagrees: the derived values differ within the loop's "
                "tolerance, or no oracle number matches",
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
compared compare value values quarter quarters end ended full total share shares price prices about many much
list would their there they them then than example respectively call calls concall conference earnings
management said meet met deliver delivered change changed expect expected look looking""".split())
# The symbol scopes the search already; its words in a query only match every page.
def _company_words(symbol: str) -> set[str]:
    """The company's own words (its symbol and the words of its stored name): a search scoped to the symbol does
    not need them.  Read from the profile / default database, never a hand list (T-094)."""
    words = {symbol.lower()}
    try:
        name = profile.company(symbol).name.lower()
    except KeyError:
        name = ""
    words.update(w for w in re.findall(r"[a-z]{3,}", name) if w not in STOP)
    return words
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
_TAGGER_TAGS: frozenset | None = None


def tagger_tags() -> frozenset:
    """The topic tags ``pilot3.transcripts`` actually writes (``lexicon/topics.yaml``): a tag asked for that the
    tagger never emits -- ``price``, ``growth``, ``dividend``, ``rating`` -- returns nothing, so it is sent as a
    ``terms`` word instead."""
    global _TAGGER_TAGS  # noqa: PLW0603 -- one small read of a static file, cached for the run
    if _TAGGER_TAGS is None:
        topics, _roles = transcripts.load_topics()
        _TAGGER_TAGS = frozenset(tag for tag, _patterns, _companies in topics)
    return _TAGGER_TAGS


def topic_args(topic: str | None) -> dict:
    """``topic`` when the tagger can match that word, else ``terms``.

    ``pilot3_statements`` matches a topic with ``topics LIKE '%word%'``, so ``order`` still finds ``order_book``;
    a word no tag contains -- ``price``, ``growth``, ``dividend``, ``rating``, ``volume`` -- returns nothing and is
    sent as a ``terms`` word instead (read from ``lexicon/topics.yaml``).
    """
    if not topic:
        return {}
    return {"topic": topic} if any(topic in tag for tag in tagger_tags()) else {"terms": topic}
_UNIT_BY_COLUMN = {"close": "inr", "open": "inr", "high": "inr", "low": "inr", "prev_close": "inr",
                   "adj_close": "inr", "value_inr": "inr", "delivery_pct": "pct", "volume": "number",
                   "deliverable_qty": "number", "num_trades": "number", "sessions": "number",
                   "avg_delivery_pct": "pct", "avg_deliverable_qty": "number", "avg_volume": "number"}
# A valuation_daily reply row carries no unit of its own; the field it was asked for decides it.
_VALUATION_UNIT = {"pe": "x", "pb": "x", "ev_ebitda": "x", "market_cap": "inr", "trailing_eps": "inr_per_share",
                   "trailing_pat": "inr", "net_worth": "inr", "net_debt": "inr", "trailing_ebitda": "inr",
                   "close": "inr", "shares_outstanding": "number", "dividend_yield_pct": "pct"}


# --- the lookups, with the db the brief names ------------------------------------------------------
def lookups():
    """``lookups_pilot3`` from the MCP server directory (the module the reality-data server runs)."""
    server = Path(__file__).resolve().parents[2] / "plugins" / "reality-data" / "server"
    # The dsh-worker server has a ``core.py`` too, and another test may have imported that one and left its
    # directory ahead of this one: put this server first and swap a shadowing ``core`` out for these imports
    # only.  The imported module keeps its own ``core``; the other server gets its module and path back.
    order = list(sys.path)
    sys.path[:] = [entry for entry in order if entry != str(server)]
    sys.path.insert(0, str(server))
    shadow = sys.modules.get("core")
    if shadow is not None and Path(getattr(shadow, "__file__", "") or "").resolve().parent != server.resolve():
        sys.modules.pop("core", None)
    try:
        import lookups_pilot3  # noqa: PLC0415 -- only needed when a call is made
    finally:
        sys.path[:] = order
        if shadow is not None and sys.modules.get("core") is not shadow:
            sys.modules["core"] = shadow
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
def load_questions(sandbox: Path, symbols: tuple | None = None) -> dict[str, dict]:
    """The question files the loop read (``gap_loop.loop.load_questions``), keyed by qid, with the symbol."""
    symbols = tuple(symbols or profile.symbols())
    out: dict[str, dict] = {}
    for symbol in symbols:
        company.activate(symbol)
        for row in loop.load_questions(Path(sandbox) / f"{symbol.lower()}_loop"):
            row["symbol"] = symbol
            out[row["id"]] = row
    company.activate(company.DEFAULT)
    return out


def load_answers(sandbox: Path, symbols: tuple | None = None) -> dict[str, dict]:
    """The newest ``answers`` row per qid (any status): qid -> status, numbers, answer text."""
    symbols = tuple(symbols or profile.symbols())
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


def periods_within(oracle_period: object, row_period: object) -> bool:
    """A quarter or half inside its fiscal year ("Q1FY27" discussed in a year the question calls FY27).

    Used for a number quoted in a sentence only: a stored value keeps the strict ``periods_match``, so a derived
    answer never mixes a quarter with a year.
    """
    first = oracle_mod.parse_period(oracle_period)
    second = oracle_mod.parse_period(row_period)
    if not first or not second:
        return False
    for half, whole in ((first, second), (second, first)):
        if half[0] in ("Q", "H") and whole[0] == "FY" and half[1].endswith(whole[1]):
            return True
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
    """The first reply row that carries the oracle number in the oracle number's period.

    A stored value needs the same period; a number quoted in a sentence also counts when the sentence discusses a
    quarter of the year asked ("Q1FY27" for "FY27") -- the quote's own period_discussed often names the quarter.
    """
    unit = str(number.get("unit") or "")
    period = number.get("period")
    for row in rows:
        same = periods_match(period, row.get("period"))
        for other, other_unit, other_scale in row.get("values", ()):
            if not same:
                continue
            if same_number(value, unit, other, other_unit, other_scale):
                return row
        text = row_text(row)
        # periods_within is kept for a later ruling but not applied: Shivam's rule, a grader is never loosened
        # to raise a score (Opus at merge, 3 Nov; it moved 5 classes, 2 of them to match).
        if text and same and number_in_text(value, unit, text):
            return row
    return None


# --- the reply as rows ------------------------------------------------------------------------------
def row_value(value: object, unit: str | None, scale: object = 1.0) -> tuple | None:
    number = _as_float(value)
    if number is None or not unit:
        return None
    return (number, unit, _as_float(scale) or 1.0)


def reply_rows(tool: str, reply: dict) -> list[dict]:
    """Every reply row as {values, texts, period, measure, provenance} whatever the tool returns."""
    if tool == "pilot3_sql":
        columns = reply.get("columns") or []
        out = []
        for raw in reply.get("rows") or []:
            record = dict(zip(columns, raw))
            values = [row_value(record[col], _UNIT_BY_COLUMN[col])
                      for col in columns if col in _UNIT_BY_COLUMN]
            out.append({"values": [v for v in values if v], "texts": [],
                        "period": next((record[c] for c in ("date", "month") if record.get(c)), None),
                        "measure": "", "provenance": {}})
        return out
    rows = []
    for row in reply.get("rows") or []:
        values = []
        if tool in ("pilot3_kpi", "pilot3_fin"):
            values = [row_value(row.get("value"), row.get("unit"), row.get("scale"))]
        elif tool == "pilot3_ratio":
            unit = row.get("unit") or _VALUATION_UNIT.get(str(row.get("ratio") or ""))
            values = [row_value(row.get("value"), unit)]
        elif tool == "pilot3_holding":
            values = [row_value(row.get("pct"), "pct"), row_value(row.get("shares"), "number")]
        rows.append({
            "values": [v for v in values if v],
            "texts": [str(row[key]) for key in ("quote", "snippet", "title", "statement")
                      if isinstance(row.get(key), str)],
            "period": (row.get("period") or row.get("quarter_end") or row.get("date")
                       or row.get("period_discussed") or row.get("call_period")),
            "measure": str(row.get("metric") or row.get("measure") or row.get("ratio") or ""),
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


def _keywords(text: str, symbol: str, n: int = 8) -> list[str]:
    """The question's own words, without the company (the symbol scopes the search) or the ask-words.

    Fiscal labels ("FY26", "Q1FY27") are kept: they are the strongest period evidence a page can carry.
    """
    words = re.findall(r"[A-Za-z][A-Za-z0-9&.\-]{2,}", text)
    company = _company_words(symbol)
    out = []
    for word in words:
        key = word.lower().strip(".-")
        if key in STOP or key in company or key in out:
            continue
        out.append(key)
        if len(out) >= n:
            break
    return out


_MONTHS_RX = ("January|February|March|April|May|June|July|August|September|October|November|December|"
              "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec")
_SPAN_RX = re.compile(r"\b(?:(?:between|from)\s+)?(?:the\s+)?(" + _MONTHS_RX + r")(?:\s+(\d{1,2}))?(?:,?\s+\d{4})?\s+"
                      r"(?:and|to|through|until)\s+(" + _MONTHS_RX + r")(?:\s+(\d{1,2}))?,?\s+(\d{4})\b", re.I)
_MONTH_RX = re.compile(r"\b(?:in|during|for|of)\s+(?:the\s+)?(" + _MONTHS_RX + r")\s+(\d{4})\b", re.I)


def _last_day(year: int, month: int) -> str:
    first_next = date(year + (month == 12), (month % 12) + 1, 1)
    return (first_next - timedelta(days=1)).isoformat()


def date_window(text: str) -> tuple[str, str] | None:
    """(from, to) when the question names a window: "between July and October 2026", "in July 2026"."""
    match = _SPAN_RX.search(text)
    if match:
        first, day1, last, day2, year = match.groups()
        year_i = int(year)
        start = date(year_i, MONTHS[first[:3].lower()], int(day1 or 1)).isoformat()
        end = (date(year_i, MONTHS[last[:3].lower()], int(day2)).isoformat() if day2
               else _last_day(year_i, MONTHS[last[:3].lower()]))
        return start, end
    match = _MONTH_RX.search(text)
    if match:
        month, year_i = MONTHS[match.group(1)[:3].lower()], int(match.group(2))
        return date(year_i, month, 1).isoformat(), _last_day(year_i, month)
    return None


def _doc_type(low: str) -> str | None:
    """The document type the question names, so search boosts it (only explicit document nouns)."""
    if "annual report" in low:
        return "annual_report"
    if re.search(r"\bdeck\b|\bpresentation\b|investor deck", low):
        return "deck"
    if re.search(r"\btranscript\b|concall transcript|earnings call transcript|conference call transcript", low):
        return "transcript"
    return None


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


def _price_sql(text: str, symbol: str, as_of: str, day: str | None = None) -> str | None:
    """The one price_delivery query a share-price question needs (pilot3_sql is the price route).

    ``day`` is the results date resolved from ``pilot3_docs`` when the question prints no date ("4 trading
    sessions after its Q1 FY27 results"); a printed date still wins.  A date the market was shut for (31 March
    2025 and 31 March 2026 were holidays) reads the last session on or before it, and the reply says which
    (``as_traded_on``).
    """
    sym = symbol.upper()
    dates = dates_in(text)
    day = dates[-1] if dates else day
    # "sessions / day after [results]": with a date of its own the question dates the anchor day itself.
    after = bool(re.search(r"(?:sessions?|days?|trading day) after|after (?:its |the )?(?:q[1-4] )?(?:fy\d\d )?results",
                           text))
    where = f"symbol='{sym}' AND exchange='NSE'"

    def traded(bound: str, value: str) -> str:
        """The last session on or before ``value`` (``bound`` '<='), or the first on or after it ('>=')."""
        pick = "MAX" if bound == "<=" else "MIN"
        return f"(SELECT {pick}(date) FROM price_delivery WHERE {where} AND date {bound} '{value}')"

    if "deliver" in text:
        if "average" in text or re.search(r"\bavg\b", text):
            month = month_in(text) or (day or as_of)[:7]
            return (f"SELECT COUNT(*) AS sessions, ROUND(AVG(delivery_pct), 2) AS avg_delivery_pct, "
                    f"ROUND(AVG(deliverable_qty), 0) AS avg_deliverable_qty FROM price_delivery "
                    f"WHERE {where} AND substr(date, 1, 7) = '{month}'")
        if not day:
            return None
        if after and not dates:  # the trading day after the results date resolved from pilot3_docs
            return (f"SELECT date, deliverable_qty, delivery_pct, close, {traded('>=', day)} AS as_traded_on "
                    f"FROM price_delivery WHERE {where} AND date > '{day}' ORDER BY date LIMIT 1")
        anchor = traded("<=", day)
        return (f"SELECT date, close, volume, deliverable_qty, delivery_pct, date AS as_traded_on "
                f"FROM price_delivery WHERE {where} AND date = {anchor}")
    if "52" in text and "low" in text:
        day = day or as_of
        start = (date.fromisoformat(day) - timedelta(days=365)).isoformat()
        return (f"SELECT date, low, close, date AS as_traded_on FROM price_delivery WHERE {where} "
                f"AND date BETWEEN '{start}' AND '{day}' ORDER BY low ASC LIMIT 1")
    if "highest" in text or ("high" in text and "price" in text):
        day = day or as_of
        return (f"SELECT date, high, close, date AS as_traded_on FROM price_delivery WHERE {where} "
                f"AND date BETWEEN '{day[:4]}-01-01' AND '{day}' ORDER BY high DESC LIMIT 1")
    if "return" in text and len(dates) >= 2:
        start, end = traded("<=", dates[0]), traded(">=", dates[-1])
        return (f"SELECT date, close, adj_close, {end} AS as_traded_on FROM price_delivery WHERE {where} "
                f"AND date BETWEEN {start} AND {end} ORDER BY date")
    if day and after:  # the anchor day and the sessions after it, so both of the answer's prices are in the reply
        anchor = traded("<=", day)
        return (f"SELECT date, close, prev_close, {anchor} AS as_traded_on FROM price_delivery WHERE {where} "
                f"AND date >= {anchor} ORDER BY date LIMIT 5")
    if day and re.search(r"closing price|price on|share price|close", text):
        if len(dates) >= 2:     # a price on each of two dates: both resolved to the last session on or before
            picks = ", ".join(traded("<=", value) for value in (dates[0], dates[-1]))
            return (f"SELECT date, close, prev_close, volume, delivery_pct, date AS as_traded_on "
                    f"FROM price_delivery WHERE {where} AND date IN ({picks}) ORDER BY date")
        anchor = traded("<=", day)
        return (f"SELECT date, close, prev_close, volume, delivery_pct, date AS as_traded_on "
                f"FROM price_delivery WHERE {where} AND date = {anchor}")
    return None


def _basis(text: str) -> str | None:
    if "standalone" in text:
        return "standalone"
    if "consolidated" in text:
        return "consolidated"
    return None


def plan(question: dict, numbers: list[dict], vocab: dict, as_of: str = AS_OF,
         results_day: str | None = None) -> dict | None:
    """ONE lookup call for one question, from its text and the table its oracle number cites.

    ``results_day`` is the results filing date resolved from pilot3_docs for a question that asks about the
    sessions after results without printing the date (T-049 F: HINDALCO085)."""
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
    # The question's own fiscal period, even when the answer cites several quarters inside it ("FY26" -> Q1-Q4):
    # search and statements use it to rank, never to grade.
    qperiod = periods[0][1] if len(periods) == 1 and not (stated and dates) else None
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
        args = {"symbol": symbol, "query": " ".join(_keywords(text, symbol)), "as_of": as_of_call, "limit": LIMIT}
        dtype = _doc_type(low)
        if dtype:
            args["doc_type"] = dtype
        if qperiod:
            args["period"] = qperiod
        window = date_window(text)      # a printed month range only: a fiscal year is too wide a filing window
        if window:
            args["date_from"], args["date_to"] = window
        return {"tool": "pilot3_search", "args": args, "why": why}

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
        query = _price_sql(low, symbol, as_of_call, results_day)
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
            args = {"as_of": as_of_call, "limit": LIMIT, "rank_terms": " ".join(_keywords(text, symbol)),
                    **topic_args(topic)}
            if periods:      # the first period a "what did they say in the Q1 FY27 call" question prints is the call
                args["period"] = periods[0][1]
            if re.search(r"\blatest (?:earnings |investor )?(?:call|concall|transcript)\b", low):
                args["latest"] = True
            return call("pilot3_statements", "management statement from a transcript", **args)
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
        # named one such measure AND the chosen store does not hold the derived name, ask for that measure --
        # the answer check says whether the cited numbers are reachable.  A store that does hold the ratio
        # (revenue_growth_yoy_pct in ratio_panel) is asked for the ratio, and the answer is graded on it.
        if numbers and name not in stores.get(tool, {}):
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


# --- derived answers: grade the computed value, not the inputs --------------------------------------
# The loop's numbers[] are often the INPUTS of the answer it gave (two revenues for a growth, revenue and
# finance cost for a cover, a price and a share count for a market cap) while the lookup returns the computed
# value, so no cited number matches.  These rules recompute the answer on both sides with the same formula and
# compare those two values with the loop's own tolerance.  The cited comparison stays beside it (``cited_class``).
OPS: tuple[tuple[str, re.Pattern], ...] = (
    ("cagr", re.compile(r"\bcagr\b|compounded annual", re.I)),
    ("growth", re.compile(r"\bgrowth\b|\bgrew\b|\bgrow(?:ing|s)?\b|by what percentage|"
                          r"\b(?:increase|rise|fall|decline|improvement) of\b", re.I)),
    ("margin", re.compile(r"\bmargins?\b", re.I)),
    ("market_cap", re.compile(r"market (?:capitali[sz]ation|cap)\b", re.I)),
    ("share", re.compile(r"\bshare (?:of|in)\b|as a share|percent(?:age)? of\b|%\s*of\b|proportion of", re.I)),
    ("ratio", re.compile(r"\bratios?\b|book-to-bill|divided by|\btimes\b|price[- ]to[- ]|p/?e\b|p/?b\b|"
                         r"ev[- ]to[- ]|interest coverage|\bcover(?:ed|age)\b|\bto\b[^.]{0,40}\b(?:revenue|aum|"
                         r"income|equity|ebitda)\b", re.I)),
    ("difference", re.compile(r"\bchange[ds]?\b|\bdifference\b|how much (?:more|less|higher|lower)|basis points"
                              r"|\bbps\b|\bby how much did\b", re.I)),
    ("sum", re.compile(r"\bcombined\b|\bsum of\b|\btotal value of\b", re.I)),
)
_METHOD_OP = ((re.compile(r"yoy|qoq|cagr|growth", re.I), "growth"), (re.compile(r"mix|share", re.I), "share"),
              (re.compile(r"margin", re.I), "margin"), (re.compile(r"b2b|book_to_bill|cover|ratio|per_tonne", re.I),
                                                         "ratio"),
              (re.compile(r"diff|change", re.I), "difference"), (re.compile(r"sum|total", re.I), "sum"))
_DIRECT = {"growth": re.compile(r"growth|grew|cagr", re.I), "margin": re.compile(r"margin", re.I),
           "share": re.compile(r"share|percent(?:age)? of|%\s*of|mix", re.I),
           "market_cap": re.compile(r"market[_ ]?cap", re.I)}
_DIRECT_FAMILY = {"growth": ("pct",), "cagr": ("pct",), "share": ("pct",), "margin": ("pct",),
                  "ratio": ("x", "pct"), "market_cap": ("money",)}
_DENOM = re.compile(r"revenue|income|turnover|sales|\baum\b|assets|equity|net worth|debt", re.I)
_NOISE = re.compile(r"\([^)]*\)|\b(?:consolidated|standalone|group|company|reported|basis|as at|as of|inr|usd|"
                    r"crore|cr|million|mn|billion|bn|q[1-4]|fy\d\d|h[12]fy\d\d)\b", re.I)


def derived_op(question: str, numbers: list[dict]) -> tuple[str, str]:
    """(op, why) when the oracle answer is a formula over its cited numbers, else ('', '').

    The cited row's own ``method``/``formula`` field decides first (a loop that names its formula); today the
    loop's ``numbers[]`` carry no such field, so the question text decides (T-049 F, 3 Nov 2026).
    """
    for number in numbers or ():
        how = f"{number.get('method') or ''} {number.get('formula') or ''}".strip()
        if not how:
            continue
        for pattern, op in _METHOD_OP:
            if pattern.search(how):
                return op, f"cited row carries method/formula {how[:60]!r}"
    for op, pattern in OPS:
        if pattern.search(str(question or "")):
            return op, f"question asks for a {op}"
    return "", ""


def _stem(measure: object) -> str:
    """A measure name without its basis, scale and period words, so two rows of one measure group."""
    return " ".join(re.findall(r"[a-z][a-z]+", _NOISE.sub(" ", str(measure or "")).lower()))


def _tokens(text: object) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9]+", str(text or "").lower()) if len(w) > 2 and w not in STOP}


def _family(unit: str) -> str:
    """pct / x / bps / money / the unit itself: what a derived value is measured in."""
    key = checks._norm_unit(unit)
    if key in ("x", "ratio", "times"):
        return "x"
    if key in ("bps", "basis_points"):
        return "bps"
    return checks.unit_family(key) or key


def operand(number: dict) -> dict | None:
    """A cited or returned number as one operand: value in base units, with its measure, unit and period."""
    value = _as_float(number.get("value"))
    unit = checks._norm_unit(number.get("unit") or "")
    if value is None or not unit:
        return None
    base = to_base(value, unit, _as_float(number.get("scale")) or 1.0)
    if base is None:
        return None
    return {"measure": str(number.get("measure") or ""), "stem": _stem(number.get("measure")), "value": base,
            "unit": unit, "family": _family(unit), "period": number.get("period")}


def reply_operands(rows: list[dict]) -> list[dict]:
    """Every number a reply row holds, as an operand (the row's measure and period travel with it)."""
    out = []
    for row in rows:
        for value, unit, scale in row.get("values", ()):
            found = operand({"measure": row.get("measure"), "value": value, "unit": unit, "scale": scale,
                             "period": row.get("period")})
            if found:
                out.append(found)
    return out


def _period_day(period: object) -> str:
    parsed = oracle_mod.parse_period(period)
    if not parsed:
        return ""
    try:
        return oracle_mod.to_date(parsed)
    except (IndexError, ValueError):
        return ""


def _years(first: object, last: object) -> float | None:
    start, end = _period_day(first), _period_day(last)
    if not start or not end:
        return None
    return (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25


def _levels(group: list[dict]) -> list[dict]:
    """One measure's operands in period order (a row without a period cannot be ordered, so it is dropped)."""
    return sorted((o for o in group if o.get("period")), key=lambda o: _period_day(o["period"]))


def _question_period(question: str) -> tuple[str, str] | None:
    """The fiscal period a question compares or asks about: the latest one it prints ("FY25 over FY26" -> FY26)."""
    periods = periods_in(question)
    if not periods:
        return None
    target = max(periods, key=lambda p: _period_day(p[1]))
    if target[0] == "D":
        closes = oracle_mod.fiscal_of(target[1])
        return ("Q", closes[0]) if closes else None
    return target


def _fy_sums(levels: list[dict]) -> dict[str, dict]:
    """F_FY_SUM: a fiscal year's four stored quarters summed, per measure (one row per quarter, first wins)."""
    by_period: dict[str, list[dict]] = {}
    for o in levels:
        parsed = oracle_mod.parse_period(o["period"])
        if parsed and parsed[0] == "Q":
            by_period.setdefault(parsed[1], []).append(o)     # the canonical label, whatever the spelling
    years: dict[str, list[dict]] = defaultdict(list)
    for period, rows in by_period.items():
        years[f"FY{period[4:]}"].append(rows[0])
    out = {}
    for fy, rows in years.items():
        if len(rows) == 4 and len({o["family"] for o in rows}) == 1:
            out[fy] = {**rows[0], "value": sum(o["value"] for o in rows), "period": fy}
    return out


def _span_pairs(levels: list[dict], question: str) -> list[tuple[dict, dict]]:
    """(earlier, later) operand pairs of one measure: the question's period against the year before it."""
    if len(levels) < 2:
        return []
    target = _question_period(question)
    if not target:
        out = []
        for index, later in enumerate(levels):
            for earlier in levels[:index]:
                years = _years(earlier["period"], later["period"])
                if years is not None and 0.9 <= years <= 1.1:
                    out.append((earlier, later))
        return out
    prior = queries.prior_period(target[1])
    later = [o for o in levels if periods_match(target, o["period"])]
    earlier = [o for o in levels if prior and periods_match(prior, o["period"])]
    if not later or not earlier:                     # four quarters sum to the year the question names
        sums = _fy_sums(levels)
        if target[0] == "FY" and target[1] in sums and prior in sums:
            return [(sums[prior], sums[target[1]])]
    return [(e, l) for e in earlier for l in later]


def _loose_groups(operands: list[dict]) -> list[list[dict]]:
    """Operands of one fiscal span together: '31 Mar 2026 (FY26)', 'FY2026' and 'FY26' are one group."""
    out: list[list[dict]] = []
    for o in operands:
        for group in out:
            if periods_match(group[0].get("period"), o.get("period")):
                group.append(o)
                break
        else:
            out.append([o])
    return out


def _position(measure: str, question: str) -> int | None:
    """Where the measure's first word appears in the question (the first measure named is the numerator)."""
    low = (question or "").lower()
    spots = [low.find(token) for token in _tokens(measure) if low.find(token) >= 0]
    return min(spots) if spots else None


def _pair_numerator(period_ops: list[dict], question: str, op: str) -> tuple[dict, dict] | None:
    """(numerator, denominator) for a share / margin / ratio written as one measure over another."""
    if len(period_ops) < 2:
        return None
    score = {id(o): len(_tokens(o["measure"]) & _tokens(question)) for o in period_ops}
    if op == "margin":
        numerator = max(period_ops, key=lambda o: (score[id(o)], len(_tokens(o["measure"]))))
        denominator = next((o for o in period_ops if o is not numerator and _DENOM.search(o["measure"])), None) \
            or next((o for o in period_ops if o is not numerator), None)
        return (numerator, denominator) if denominator else None
    if op == "share":
        part = max(period_ops, key=lambda o: (score[id(o)], len(_tokens(o["measure"]))))
        rest = [o for o in period_ops if o is not part]
        whole = next((o for o in rest if _tokens(o["measure"]) and
                      _tokens(o["measure"]) < _tokens(part["measure"])), None) \
            or next((o for o in rest if _DENOM.search(o["measure"])), None) or (rest[0] if rest else None)
        return (part, whole) if whole else None
    positions = [_position(o["measure"], question) for o in period_ops]
    if any(p is None for p in positions):
        # Neither measure is named in the question: only two cited numbers of one period can be read in
        # cited order ("debt to equity" over borrowings and net worth).  More than two is ambiguous.
        if len(period_ops) != 2:
            return None
        return period_ops[0], period_ops[1]
    ordered = sorted(period_ops, key=lambda o: _position(o["measure"], question) or 0)
    return ordered[0], ordered[1]


def _price_count(group: list[dict]) -> tuple[dict, dict] | None:
    """(price per share, share count) for a market cap: a price row times a share-count row."""
    price = next((o for o in group if "per_share" in o["unit"]
                  or re.search(r"price|close", o["measure"], re.I)), None)
    count = next((o for o in group if o is not price and (
        re.search(r"\bshares?\b|equity|outstanding", o["measure"], re.I) or o["family"] in ("count", "number"))),
                 None)
    return (price, count) if price and count else None


def _is_direct(op: str, o: dict, asked: str) -> bool:
    """A row whose own measure already IS the derived value (a stored ratio, or the name the call asked for)."""
    families = _DIRECT_FAMILY.get(op)
    if not families or o["family"] not in families:
        return False
    name = (o["measure"] or "").lower()
    if not name:
        return False
    if asked:  # the name the call asked for, as whole words ("pe" must not match "capex")
        words = re.findall(r"[a-z0-9]+", name)
        want = re.findall(r"[a-z0-9]+", asked.lower())
        if want and (any(words[i:i + len(want)] == want for i in range(len(words) - len(want) + 1))
                     or any(want[i:i + len(words)] == words for i in range(len(want) - len(words) + 1))):
            return True
    pattern = _DIRECT.get(op)
    return bool(pattern and pattern.search(name))


def derived_values(op: str, operands: list[dict], question: str, asked: str = "") -> list[dict]:
    """The derived values this set of numbers supports: the stored ratio it names, else the formula over it."""
    out: list[dict] = [{"value": o["value"], "family": o["family"], "unit": o["unit"], "period": o["period"],
                        "how": o["measure"] or asked} for o in operands if _is_direct(op, o, asked)]
    groups: dict[str, list[dict]] = defaultdict(list)
    for o in operands:
        groups[o["stem"] or o["measure"].lower()].append(o)
    if op in ("growth", "cagr", "difference", "sum"):
        scored = [(len(_tokens(name) & _tokens(question)), len(groups[name]), name) for name in groups]
        scored = sorted((s for s in scored if s[0]), reverse=True)
        names = [name for _score, _size, name in scored]
        if not names:
            names = [name for name, rows in groups.items() if len({str(o["period"]) for o in rows}) > 1]
            names = names[:1] if len(names) == 1 else []
        if op == "difference":
            for name in names[:1]:
                out += [{"value": o["value"], "family": o["family"], "unit": o["unit"], "period": o["period"],
                         "how": o["measure"]} for o in _levels(groups[name])]
        elif op == "sum":
            for name in names[:1]:
                group = _levels(groups[name])
                if group and len({o["family"] for o in group}) == 1:
                    out.append({"value": sum(o["value"] for o in group), "family": group[0]["family"],
                                "unit": group[0]["unit"], "period": group[-1]["period"],
                                "how": "sum of " + group[0]["stem"]})
        else:
            for name in names:                      # the measure the question names that supports the formula
                pairs = _span_pairs(_levels(groups[name]), question)
                if not pairs:
                    continue
                for earlier, later in pairs:
                    if not earlier["value"] or earlier["family"] != later["family"]:
                        continue
                    ratio = later["value"] / earlier["value"]
                    if op == "growth":
                        out.append({"value": 100.0 * (ratio - 1.0), "family": "pct", "unit": "pct",
                                    "period": later["period"], "how": f"growth of {later['stem']}"})
                    else:
                        years = _years(earlier["period"], later["period"])
                        if years and years > 0 and ratio > 0:
                            out.append({"value": 100.0 * (ratio ** (1.0 / years) - 1.0), "family": "pct",
                                        "unit": "pct", "period": later["period"],
                                        "how": f"cagr of {later['stem']}"})
                break
        return out
    if op == "market_cap":
        pair = _price_count(operands)
        if pair:
            price, count = pair
            out.append({"value": price["value"] * count["value"], "family": "money", "unit": "inr",
                        "period": price["period"], "how": "price x shares"})
        return out
    for period_ops in _loose_groups(operands):
        pair = _pair_numerator(period_ops, question, op)
        if not pair:
            continue
        numerator, denominator = pair
        if numerator["stem"] == denominator["stem"] or not denominator["value"] \
                or numerator["family"] != denominator["family"] or numerator["family"] in ("pct", "x"):
            continue
        value = numerator["value"] / denominator["value"]
        how = f"{numerator['measure']} / {denominator['measure']}"
        if op in ("share", "margin"):
            out.append({"value": 100.0 * value, "family": "pct", "unit": "pct",
                        "period": numerator["period"] or denominator["period"], "how": how})
        else:
            out.append({"value": value, "family": "x", "unit": "x",
                        "period": numerator["period"] or denominator["period"], "how": how})
    if op == "ratio" and not out:  # price over a trailing sum of one measure (the trailing PE)
        price = next((o for o in operands if "per_share" in o["unit"]
                      or re.search(r"price|close", o["measure"], re.I)), None)
        others = [name for name, rows in groups.items() if len(_levels(rows)) >= 2]
        if price and len(others) == 1:
            group = _levels(groups[others[0]])
            total = sum(o["value"] for o in group)
            if total:
                out.append({"value": price["value"] / total, "family": "x", "unit": "x",
                            "period": price["period"], "how": f"{price['measure']} / sum({others[0]})"})
    return out


def same_derived(left: dict, right: dict) -> bool:
    """Two derived values agree: same unit family, in the loop's own tolerance (bps / percent only converted)."""
    two = {"pct": "pct", "x": "x", "bps": "bps", "money": "money"}
    mine, theirs = left["family"], right["family"]
    if mine == theirs == "money":
        return _currency(left["unit"]) == _currency(right["unit"]) and close_enough(left["value"], right["value"])
    if mine in two and theirs in two:
        if mine == "bps" and theirs == "pct":
            return close_enough(left["value"] / 100.0, right["value"])
        if mine == "pct" and theirs == "bps":
            return close_enough(left["value"], right["value"] / 100.0)
        if mine == "x" and theirs == "pct":
            return close_enough(100.0 * left["value"], right["value"])
        if mine == "pct" and theirs == "x":
            return close_enough(left["value"], 100.0 * right["value"])
        return mine == theirs and close_enough(left["value"], right["value"])
    return mine == theirs and close_enough(left["value"], right["value"])


def derived_verdict(question: str, numbers: list[dict], rows: list[dict], asked: str = "") -> dict | None:
    """Grade the answer: the derived value from the oracle's inputs against the derived value of the reply.

    None when the answer is not derived; when the reply supports no derived value at all, the caller keeps the
    cited comparison, because there was nothing to grade (``compared_on`` then says ``cited``).
    """
    op, why = derived_op(question, numbers)
    if not op:
        return None
    oracle = []
    for number in numbers or ():
        found = operand(number)
        if found:
            oracle.append(found)
    targets = derived_values(op, oracle, question)
    if not targets:
        return None
    reply = derived_values(op, reply_operands(rows), question, asked)
    if not reply:
        return None
    hit, miss = [], []
    for target in targets:
        found = next((r for r in reply if (not target["period"] or not r["period"]
                                           or periods_match(target["period"], r["period"]))
                      and same_derived(target, r)), None)
        (hit if found else miss).append((target, found))
    return {"op": op, "why": why, "class": "match" if not miss else "mismatch" if not hit else "partial",
            "hit": hit, "miss": miss, "returned": reply}


def derived_text(verdict: dict | None) -> str:
    """The derived values side by side, for the report: the oracle's and the reply's."""
    if not verdict:
        return ""
    bits = []
    for found, rows in ((True, verdict["hit"]), (False, verdict["miss"])):
        for target, reply in rows:
            mine = f"{target['value']:.6g} {target['family']} [{target['period'] or ''}]"
            theirs = f"{reply['value']:.6g} {reply['family']}" if reply else "not in the reply"
            bits.append(f"{verdict['op']} {target['how']}: oracle {mine} vs reply {theirs}"
                        + ("" if found else " (!)"))
    return "; ".join(bits)[:400]


# --- comparison and report --------------------------------------------------------------------------
def classify(tool: str, reply: dict | None, numbers: list[dict], passed: bool, question: str = "",
             asked: str = "") -> dict:
    """The result class, the numbers found, the ones missing, and the row that carries the answer.

    ``class`` is the answer grade: for a derived answer (growth, share, margin, ratio, difference, sum, CAGR) it
    compares the derived value on both sides; ``cited_class`` always keeps the old cited-number comparison.
    """
    if reply is None:
        return {"class": "no_tool", "cited_class": "no_tool", "compared_on": "", "hit": [], "miss": [],
                "row": None, "rows": [], "derived": ""}
    rows = reply_rows(tool, reply)
    answer = {"rows": rows, "row": rows[0] if rows else None}
    if not rows:
        return {"class": "empty", "cited_class": "empty", "compared_on": "", "hit": [], "miss": [], **answer,
                "derived": ""}
    if not passed:
        return {"class": "answered_no_oracle", "cited_class": "answered_no_oracle", "compared_on": "",
                "hit": [], "miss": [], **answer, "derived": ""}
    if not numbers:
        return {"class": "match", "cited_class": "match", "compared_on": "", "hit": [], "miss": [], **answer,
                "derived": ""}  # a text answer: the call returned rows
    cited = _cited_verdict(rows, numbers)
    derived = derived_verdict(question, numbers, rows, asked)
    if derived:  # the lookup returns the ratio, or the inputs of it: grade the derived value
        return {"class": derived["class"], "cited_class": cited["class"], "compared_on": "derived",
                "hit": cited["hit"], "miss": cited["miss"], "derived": derived_text(derived),
                "row": cited["row"] or answer["row"], "rows": rows}
    return {"class": cited["class"], "cited_class": cited["class"], "compared_on": "cited", **cited, **answer,
            "derived": ""}


def _cited_verdict(rows: list[dict], numbers: list[dict]) -> dict:
    """The old comparison: every oracle number must occur in a reply row of the same period."""
    hit, miss = [], []
    for number in numbers:
        value = _as_float(number.get("value"))
        row = find_number(value, number, rows) if value is not None else None
        (hit if row else miss).append((number, row))
    if not hit:
        return {"class": "mismatch", "hit": [], "miss": [n for n, _ in miss], "row": None}
    if miss:
        return {"class": "partial", "hit": [n for n, _ in hit], "miss": [n for n, _ in miss],
                "row": hit[0][1]}
    return {"class": "match", "hit": [n for n, _ in hit], "miss": [], "row": hit[0][1]}


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


_RESULTS_AFTER = re.compile(r"(?:sessions?|days?|trading day) after|after (?:its |the )?(?:q[1-4] )?(?:fy\d\d )?results",
                            re.I)


def results_day(p3, question: dict, as_of: str) -> str | None:
    """The results filing date for a question about the sessions after results that prints no date.

    Read from ``pilot3_docs`` (the results filing's ``known_at``) -- T-049 F, HINDALCO085.  When the question
    names a fiscal period, only a results filing after that period end and within 75 days counts (a listed
    company files within 45 days), so a later quarter's board meeting cannot stand in for it.
    """
    text = str(question.get("question") or "")
    if dates_in(text) or not _RESULTS_AFTER.search(text):
        return None
    symbol = str(question.get("symbol") or "")
    if not symbol:
        return None
    try:
        reply = p3.docs(symbol, doc_type="results", as_of=as_of, limit=8)
    except Exception:  # noqa: BLE001 -- an unresolvable date is not a crash
        return None
    ends = [end for end in (_period_day(p) for p in periods_in(text)) if end]
    for row in reply.get("rows") or ():
        day = str((row.get("provenance") or {}).get("known_at") or row.get("filing_date") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            continue
        if ends and not any(end < day <= (date.fromisoformat(end) + timedelta(days=75)).isoformat()
                            for end in ends):
            continue
        return day
    return None


def evaluate(db: Path, sandbox: Path = SANDBOXES, as_of: str = AS_OF,
             symbols: tuple | None = None) -> dict:
    """Every question: its one mapped call, the comparison with the oracle, and the summary counts."""
    symbols = tuple(symbols or profile.symbols())
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
            when = str(question.get("as_of") or as_of)
            mapping = plan(question, numbers, vocab, when, results_day(p3, question, when))
            reply, error = None, ""
            if mapping:
                fn = getattr(p3, TOOL_CALL[mapping["tool"]])
                try:
                    reply = fn(**mapping["args"])
                except Exception as exc:  # noqa: BLE001 -- a failed call is a result, never a crash
                    error = f"{type(exc).__name__}: {str(exc)[:200]}"
                    errors += 1
            asked = ""
            if mapping:
                asked = str(mapping["args"].get("ratio") or mapping["args"].get("kpi")
                            or mapping["args"].get("measure") or "")
            passed = answer.get("status") == PASSED
            verdict = classify(mapping["tool"], reply, numbers, passed, str(question.get("question") or ""),
                               asked) if mapping else classify("", None, numbers, passed)
            records.append({
                "qid": qid, "company": str(question.get("symbol") or answer.get("symbol") or ""),
                "kind": question.get("kind") or "", "question": question.get("question") or "",
                "tool": mapping["tool"] if mapping else "", "arguments": json.dumps(mapping["args"], default=str)
                if mapping else "", "why": mapping["why"] if mapping else "no rule matched the question",
                "class": verdict["class"], "compared_on": verdict.get("compared_on") or "",
                "cited_class": verdict.get("cited_class") or "", "oracle_status": answer.get("status") or "",
                "oracle_numbers": numbers_text(numbers),
                "returned_numbers": rows_text(verdict["rows"]) if verdict["rows"] else "",
                "derived_numbers": verdict.get("derived") or "",
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
            "by_compared_on": dict(Counter(record.get("compared_on") or "none" for record in records)),
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
    counts = summary.get("by_compared_on") or {}
    lines.append(f"  compared_on: derived {counts.get('derived', 0)}, cited {counts.get('cited', 0)}"
                 f" (cited_class keeps the cited-number comparison for every row)")
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
    columns = ("qid", "company", "kind", "question", "tool", "arguments", "class", "compared_on", "cited_class",
               "oracle_status", "oracle_numbers", "returned_numbers", "derived_numbers", "provenance", "why",
               "error")
    widths = {"qid": 15, "company": 11, "kind": 9, "question": 60, "tool": 18, "arguments": 46, "class": 16,
              "compared_on": 11, "cited_class": 12, "oracle_status": 11, "oracle_numbers": 40,
              "returned_numbers": 40, "derived_numbers": 50, "provenance": 46, "why": 34, "error": 30}
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
    summary_sheet.append(["how the answer was graded", "questions"])
    for name, count in sorted((summary.get("by_compared_on") or {}).items()):
        summary_sheet.append([name, count])
    summary_sheet.append([])
    summary_sheet.append(["what each class means"])
    for name in CLASSES:
        summary_sheet.append([name, CLASS_HELP[name]])
    summary_sheet.append([])
    summary_sheet.append(["column", "meaning"])
    summary_sheet.append(["compared_on", "derived = the class compares the computed answer on both sides; "
                                        "cited = the class compares the oracle's cited numbers (the old check)"])
    summary_sheet.append(["cited_class", "the cited-number comparison for every row, kept beside the answer "
                                         "grade so nothing is hidden"])
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

    parts.append("<h2>Every question</h2><table><tr><th>qid</th><th>class</th><th>compared on</th>"
                 "<th>cited class</th><th>tool</th><th>arguments</th><th>oracle numbers</th>"
                 "<th>returned numbers</th><th>derived (oracle vs reply)</th><th>provenance</th></tr>")
    for record in records:
        colour = _COLOURS.get(record["class"], "#ffffff")
        parts.append(
            f'<tr class="q"><td>{esc(record["qid"])}</td>'
            f'<td><span class="sw" style="background:{colour}"></span>{esc(record["class"])}</td>'
            f'<td>{esc(record["compared_on"] or "")}</td><td>{esc(record["cited_class"] or "")}</td>'
            f'<td>{esc(record["tool"])}</td><td class="n">{esc(record["arguments"])}</td>'
            f'<td class="n">{esc(record["oracle_numbers"] or "none")}</td>'
            f'<td class="n">{esc(record["returned_numbers"] or record["error"] or "")}</td>'
            f'<td class="n">{esc(record.get("derived_numbers") or "")}</td>'
            f'<td>{esc(record["provenance"])}</td></tr>')
        parts.append(f'<tr class="q"><td></td><td colspan="9" style="color:#444">'
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
    parser.add_argument("--symbols", default=None, help="comma list to check (default: the profile's companies)")
    parser.add_argument("--out", default=str(OUT), help=f"xlsx report (default: {OUT})")
    parser.add_argument("--html", default=str(HTML), help=f"html summary (default: {HTML})")
    args = parser.parse_args(argv)
    db = Path(args.db).expanduser()
    if not db.is_file():
        raise SystemExit(f"STOPPED pilot3 database missing: {db}")
    symbols = tuple(part.strip().upper() for part in args.symbols.split(",") if part.strip()) if args.symbols else None
    result = evaluate(db, Path(args.sandboxes), args.as_of, symbols)
    records, summary = result["records"], result["summary"]
    print(render(summary))
    print(f"wrote {write_xlsx(Path(args.out).expanduser(), records, summary)}")
    print(f"wrote {write_html(Path(args.html).expanduser(), records, summary)}")


if __name__ == "__main__":
    main()
