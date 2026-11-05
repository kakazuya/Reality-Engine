"""pilot3 lookups: the one database the reality-data server serves through the ``pilot3_*`` tools (T-049 F).

``pilot3.db`` is built by scripts (``python -m reality_engine.pilot3.build``): dated page text of every held
document, KPI series, reported and derived financial lines, ratios, shareholding, management statements.
``REALITY_PILOT3_DB`` names another build (a profile's, e.g. pilot10), and then the companies the tools accept
are the ones that database's ``company`` table holds (T-056); without it the three pilot3 companies.
These tools answer from it first; the raw files are touched only when a tool says NOT IN DATA.

Read-only (``connect_ro``), small replies, and every row carries ``provenance`` = table, source (document +
page, or store table + row) and ``known_at``.  ``as_of`` drops rows whose ``known_at`` is after that day, and
rows without a ``known_at`` (a row that cannot prove it was public is never shown to a point-in-time question).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import core
from core import DataError

PILOT3_SYMBOLS = ("KEC", "BAJFINANCE", "HINDALCO")
_MAIN = Path(r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\pilot3\pilot3.db")
MAX_LIMIT = 50
QUOTE_CHARS = 600
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_conn_path: Path | None = None

_DOC_TYPES = {
    "deck": "deck", "decks": "deck", "presentation": "deck", "investor presentation": "deck",
    "transcript": "transcript", "transcripts": "transcript", "concall": "transcript", "call": "transcript",
    "ar": "annual_report", "annual report": "annual_report", "annual_report": "annual_report",
    "announcement": "announcement", "announcements": "announcement", "filing": "announcement",
    "results": "results", "result": "results", "press release": "press_release", "press_release": "press_release",
    "audio_link": "audio_link",
}


def db_path() -> Path:
    env = os.environ.get("REALITY_PILOT3_DB")
    if env:
        return Path(env)
    here = core.DATA / "pilot3" / "pilot3.db"
    return here if here.is_file() else _MAIN


def connect() -> sqlite3.Connection:
    global _conn, _conn_path
    path = db_path()
    with _lock:
        if _conn is not None and _conn_path == path:
            return _conn
        if not path.is_file():
            raise DataError("pilot3_db_missing", f"pilot3.db not found at {path}; build it with "
                            "python -m reality_engine.pilot3.build")
        if _conn is not None:
            _conn.close()
        _conn = core.connect_ro(path, timeout_s=core.READ_TIMEOUT_S, check_same_thread=False, cache_size_kib=-65536)
        _conn.row_factory = sqlite3.Row
        _conn_path = path
        return _conn


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _q(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    try:
        return connect().execute(sql, params).fetchall()
    except core.QueryTimeout as exc:
        raise DataError("query_timeout", str(exc))
    except sqlite3.DatabaseError as exc:
        raise DataError("sql_error", f"{type(exc).__name__}: {exc}")


def _is_lender(sym: str) -> bool:
    """A bank, NBFC or insurer reports interest / premium income, so EV/EBITDA has no meaning for it."""
    return bool(_q("SELECT 1 FROM fin_quarter_xbrl WHERE symbol=? AND line_item IN "
                   "('interest_income','interest_earned','gross_premium','net_premium') LIMIT 1", (sym,)))


# --- symbols, periods, dates ------------------------------------------------------------------------
def pilot_symbols() -> tuple[str, ...]:
    """The companies this database holds: ``REALITY_PILOT3_DB`` -> its ``company`` table (T-056), else pilot3's."""
    if not os.environ.get("REALITY_PILOT3_DB"):
        return PILOT3_SYMBOLS
    try:
        return tuple(row[0] for row in _q("SELECT DISTINCT symbol FROM company ORDER BY symbol")) or PILOT3_SYMBOLS
    except DataError:
        return PILOT3_SYMBOLS


def resolve_symbol(symbol: str) -> str:
    """A symbol / BSE code / ISIN / name of a company the database holds; anything else is a DataError."""
    text = (symbol or "").strip()
    if not text:
        raise DataError("bad_symbol", "symbol is required")
    key = text.upper()
    allowed = pilot_symbols()
    if key in allowed:
        return key
    for row in _q("SELECT symbol FROM company WHERE isin=? OR bse_code=? OR upper(name) LIKE ? LIMIT 1",
                  (key, text, f"%{key}%")):
        if row[0] in allowed:
            return row[0]
    try:  # the shared resolver knows more spellings (BAJAJ FINANCE, KEC INTERNATIONAL)
        ident = core.resolve_one(text)
        for cand in (ident.get("nse_symbol"), ident.get("bse_symbol")):
            if cand and cand.upper() in allowed:
                return cand.upper()
    except Exception:
        pass
    raise DataError("not_pilot3", f"{symbol!r} is not a company of this pilot database ({', '.join(allowed)}); "
                    "use the general tools (facts, docs, search_docs) for it")


def _day(value: str | None, field: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        raise DataError("bad_date", f"{field} must be YYYY-MM-DD, got {value!r}")


def _fy2(text: str) -> str:
    return text[-2:]


def norm_period(period: str | None) -> tuple[str | None, str | None]:
    """``(kind, label)``: Q2FY26 / H1FY26 / FY26 labels the tables use; ``kind`` is Q, H1, FY or None.
    Accepts Q2FY26, Q2 FY2026, FY2025-26, 2025-26, FY26, H1FY26 and a date (its fiscal quarter)."""
    if period in (None, ""):
        return None, None
    text = str(period).strip().upper().replace(" ", "")
    m = re.fullmatch(r"Q([1-4])-?FY?(\d{2}|\d{4})", text)
    if m:
        return "Q", f"Q{m[1]}FY{_fy2(m[2])}"
    m = re.fullmatch(r"H([12])-?FY?(\d{2}|\d{4})", text)
    if m:
        return "H" + m[1], f"H{m[1]}FY{_fy2(m[2])}"
    m = re.fullmatch(r"(?:FY)?(\d{4})-(\d{2}|\d{4})", text)
    if m:
        return "FY", f"FY{_fy2(m[2])}"
    m = re.fullmatch(r"(?:FY|YEAR)?-?(\d{2}|\d{4})", text)
    if m:
        return "FY", f"FY{_fy2(m[1])}"
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        year, month = int(m[1]), int(m[2])
        fy = year + 1 if month >= 4 else year
        q = {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3, 1: 4, 2: 4, 3: 4}[month]
        return "Q", f"Q{q}FY{str(fy)[-2:]}"
    return None, text


def _asof(as_of: str | None, col: str = "known_at") -> tuple[str, tuple]:
    day = _day(as_of, "as_of")
    return (f" AND {col} IS NOT NULL AND substr({col},1,10) <= ?", (day,)) if day else ("", ())


def _cap(limit: Any, default: int = 10) -> int:
    try:
        return max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        return default


def _trim(text: str | None, n: int = QUOTE_CHARS) -> str | None:
    if text is None:
        return None
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text if len(text) <= n else text[:n].rstrip() + " …"


def _prov(table: str, source: str, known_at: str | None, **extra: Any) -> dict[str, Any]:
    return {"table": table, "source": source, "known_at": known_at, **{k: v for k, v in extra.items() if v is not None}}


def _db_prov(**extra: Any) -> dict[str, Any]:
    path = db_path()
    built = time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime)) if path.exists() else None
    return {"db": "pilot3", "path": str(path), "read_only": True, "built": built, **extra}


def _reply(symbol: str, rows: list[dict], tool: str, **extra: Any) -> dict[str, Any]:
    out = {"found": bool(rows), "symbol": symbol, "tool": tool, "n": len(rows), "rows": rows, **extra,
           "provenance": _db_prov()}
    if not rows:
        out.setdefault("hint", "NOT IN DATA of pilot3 for these arguments: check the 'available' list, widen the "
                       "period or as_of, try pilot3_search; only then fall back to the raw tools.")
    return out


def _available(table: str, col: str, symbol: str, like: str | None = None, extra: str = "", n: int = 40) -> list[str]:
    sql = f"SELECT {col}, COUNT(*) c FROM {table} WHERE symbol=?{extra}"
    args: list[Any] = [symbol]
    if like:
        sql += f" AND {col} LIKE ?"
        args.append(f"%{like}%")
    sql += f" GROUP BY {col} ORDER BY c DESC LIMIT {n}"
    return [r[0] for r in _q(sql, tuple(args)) if r[0]]


def _pick(table: str, col: str, symbol: str, name: str, extra: str = "") -> tuple[list[str], list[str]]:
    """Names to match for a user's metric word: the exact one, else every name containing it (spaces as _)."""
    key = re.sub(r"[\s\-]+", "_", name.strip().lower())
    names = _available(table, col, symbol, extra=extra, n=500)
    if key in names:
        return [key], names
    near = [n for n in names if key in n]
    return near[:8], names


# --- pilot3_kpi -------------------------------------------------------------------------------------
_DOC_JOIN = ("LEFT JOIN doc d ON d.doc_key = COALESCE((SELECT a.doc_key FROM doc_alias a WHERE a.symbol=k.symbol "
             "AND a.alias_key=k.doc_key), k.doc_key)")


def kpi(symbol: str, kpi: str, period: str | None = None, as_of: str | None = None,
        dimension: str | None = None, basis: str | None = None, limit: int = 10) -> dict[str, Any]:
    """A company-stated KPI (order book, AUM, EBITDA/tonne, NIM ...) from decks, results, releases, transcripts."""
    sym = resolve_symbol(symbol)
    names, allnames = _pick("kpi_series", "metric", sym, kpi)
    if not names:
        return _reply(sym, [], "pilot3_kpi", available=allnames[:40], metric_asked=kpi)
    kind, label = norm_period(period)
    where, args = f"k.symbol=? AND k.metric IN ({','.join('?' * len(names))})", [sym, *names]
    if label:
        where += " AND k.fiscal_period=?"
        args.append(label)
    if dimension:
        where += " AND lower(k.dimension)=?"
        args.append(dimension.strip().lower())
    if basis:
        where += " AND k.basis=?"
        args.append(basis.strip().lower())
    extra, eargs = _asof(as_of, "k.known_at")
    rows = _q(f"SELECT k.id, k.metric, k.dimension, k.value, k.unit, k.scale, k.fiscal_period, k.period_type, "
              f"k.as_of_date, k.basis, k.doc_key, k.page, k.quote, k.known_at, k.conf_rank, d.doc_key AS dk, "
              f"d.title, d.doc_type FROM kpi_series k {_DOC_JOIN} WHERE {where}{extra} "
              # best evidence first: the extractor's confidence, then a deck/results/filing before a call remark.
              # The window must reach past a measure's duplicates (one value restated in many filings): at 3x the
              # reply size, a restated measure filled it and its lower-confidence period series never arrived (T-049,
              # 4 Nov 2026: Bajaj's quarterly GNPA and KEC's order-intake trend came back as old annual rows only).
              f"ORDER BY k.conf_rank DESC, "
              f"CASE d.doc_type WHEN 'deck' THEN 0 WHEN 'results' THEN 1 WHEN 'press_release' THEN 2 "
              f"WHEN 'annual_report' THEN 3 WHEN 'transcript' THEN 4 ELSE 5 END, "
              f"(k.dimension='total') DESC, k.known_at DESC, k.id LIMIT ?",
              (*args, *eargs, _cap(limit) * 30))
    out, seen = [], set()
    for r in rows:
        sig = (r["metric"], r["dimension"], r["fiscal_period"], r["value"], r["unit"])
        if sig in seen:
            continue
        seen.add(sig)
        out.append({"metric": r["metric"], "dimension": r["dimension"], "value": r["value"], "unit": r["unit"],
                    "period": r["fiscal_period"], "period_type": r["period_type"], "as_of_date": r["as_of_date"],
                    "basis": r["basis"], "quote": _trim(r["quote"], 300),
                    "provenance": _prov("kpi_series", f"{r['dk'] or r['doc_key']} p{r['page']}", r["known_at"],
                                        doc_type=r["doc_type"], title=r["title"], row_id=r["id"])})
    out = out[: _cap(limit)]
    held = None
    if not out:  # the metric exists: say which periods / dimensions hold it, so the next call can be exact
        held = [f"{r[0]} / {r[1]} ({r[2]} rows)" for r in _q(
            f"SELECT fiscal_period, dimension, COUNT(*) FROM kpi_series WHERE symbol=? AND metric IN "
            f"({','.join('?' * len(names))}) GROUP BY 1, 2 ORDER BY MAX(known_at) DESC LIMIT 40", (sym, *names))]
    return _reply(sym, out, "pilot3_kpi", metrics_matched=names, held_period_dimension=held)


# --- pilot3_fin -------------------------------------------------------------------------------------
def fin(symbol: str, measure: str, period: str | None = None, basis: str | None = None,
        definition: str | None = None, as_of: str | None = None, limit: int = 12) -> dict[str, Any]:
    """Reported / derived / company-stated financial lines: annual (FY26, H1FY26) and quarterly (Q2FY26)."""
    sym = resolve_symbol(symbol)
    kind, label = norm_period(period)
    use_q = kind in (None, "Q")
    use_a = kind in (None, "FY", "H1", "H2")
    out: list[dict] = []
    avail: list[str] = []
    cap = _cap(limit)
    bas = basis.strip().lower() if basis else None
    if use_a:
        names, allnames = _pick("fin_annual_line", "line_item", sym, measure)
        avail += allnames
        if names:
            where, args = f"symbol=? AND line_item IN ({','.join('?' * len(names))})", [sym, *names]
            for col, val in (("fiscal_year", label), ("basis", bas), ("definition", definition)):
                if val:
                    where += f" AND {col}=?"
                    args.append(val)
            extra, eargs = _asof(as_of)
            for r in _q(f"SELECT rowid, * FROM fin_annual_line WHERE {where}{extra} "
                        f"ORDER BY fiscal_year DESC, known_at DESC LIMIT ?", (*args, *eargs, cap * 2)):
                out.append(_fin_row(r, "fin_annual_line", r["fiscal_year"], r["definition"],
                                    _fin_source(r)))
    if use_q:
        names, allnames = _pick("fin_quarter_xbrl", "line_item", sym, measure)
        printed_names: list[str] = []
        if _has_table("fin_quarter_printed"):     # a quarter the XBRL window does not hold lives only here (T-057)
            printed_names, printed_avail = _pick("fin_quarter_printed", "line_item", sym, measure)
            allnames = sorted(set(allnames) | set(printed_avail))
        avail += allnames
        got: set = set()
        if names:
            where, args = f"symbol=? AND line_item IN ({','.join('?' * len(names))})", [sym, *names]
            for col, val in (("fiscal_period", label), ("basis", bas)):
                if val:
                    where += f" AND {col}=?"
                    args.append(val)
            extra, eargs = _asof(as_of)
            for r in _q(f"SELECT rowid, * FROM fin_quarter_xbrl WHERE {where}{extra} "
                        f"ORDER BY period_end DESC, known_at DESC LIMIT ?", (*args, *eargs, cap * 2)):
                out.append(_fin_row(r, "fin_quarter_xbrl", r["fiscal_period"], "xbrl_reported",
                                    _fin_source(r)))
                got.add((r["line_item"], r["fiscal_period"]))
        # T-057: the printed comparative columns of the results table, when a check confirmed the cell
        if printed_names:
            where, args = f"symbol=? AND line_item IN ({','.join('?' * len(printed_names))})", [sym, *printed_names]
            for col, val in (("fiscal_period", label), ("basis", bas)):
                if val:
                    where += f" AND {col}=?"
                    args.append(val)
            extra, eargs = _asof(as_of)
            printed = _q(f"SELECT rowid, * FROM fin_quarter_printed WHERE {where} "
                         f"AND check_status IN ('xbrl_ok','sum_ok','repeat_ok') AND basis IN ('standalone','consolidated'){extra} "
                         f"ORDER BY period_end DESC, known_at DESC LIMIT ?", (*args, *eargs, cap * 2))
            for r in printed:
                if (r["line_item"], r["fiscal_period"]) in got:
                    continue             # the XBRL row for that quarter is the evidence; no duplicate
                out.append(_fin_row(r, "fin_quarter_printed", r["fiscal_period"], "printed_comparative",
                                    _fin_source(r)))
    out = _dedupe(out)
    # No basis asked: a group question means the consolidated statement.  T-049 (4 Nov 2026): HINDALCO's
    # diluted EPS FY26 came back standalone 45.31 where the consolidated 60.20 was wanted; standalone is one
    # explicit argument away, so a mixed reply is filtered to consolidated when it holds the same measure.
    assumed = None
    if bas is None:
        consolidated = [row for row in out if row["basis"] == "consolidated"]
        if consolidated and len(consolidated) < len(out):
            out, assumed = consolidated, "consolidated"
    out = out[:cap]
    return _reply(sym, out, "pilot3_fin", available=sorted(set(avail))[:50] if not out else None, measure_asked=measure,
                  basis_assumed=assumed)


def _fin_source(r: sqlite3.Row) -> str:
    """The filing and the store row: XBRL file name (no page), or document + page when the line came from a PDF."""
    keys = r.keys()
    doc = (r["doc_key"] if "doc_key" in keys else None) or (r["source_file"] if "source_file" in keys else None)
    page = r["page"] if "page" in keys and r["page"] else None
    where = f"{doc} p{page}" if doc and page else (doc or "")
    store = (f"[{r['source_db']}.{r['source_table']} row {r['source_rowid']}]"
             if {"source_db", "source_table", "source_rowid"} <= set(keys) else "")
    return f"{where} {store}".strip()


def _has_table(name: str) -> bool:
    """A pilot3 table may be absent from an older build (fin_quarter_printed came with T-057)."""
    return bool(_q("SELECT 1 FROM sqlite_master WHERE name=? LIMIT 1", (name,)))


def _fin_row(r: sqlite3.Row, table: str, period: str, definition: str, source: str) -> dict[str, Any]:
    unit, scale, value = r["unit"], r["scale"] or 1.0, r["value"]
    row = {"measure": r["line_item"], "period": period, "basis": r["basis"] or "not_stated", "definition": definition,
           "value": value, "unit": unit, "scale": scale,
           "provenance": _prov(table, source, r["known_at"], row_id=r["rowid"], period_end=r["period_end"])}
    if unit in ("inr", "inr_cr", "inr_mn", "inr_lakh") or (unit or "").startswith("inr") and "share" not in (unit or ""):
        row["value_inr"] = value * scale
    keys = r.keys()
    if "column_role" in keys and r["column_role"]:
        row["column_role"] = r["column_role"]
    if table in ("fin_annual_line", "fin_quarter_printed") and r["quote"]:
        row["quote"] = _trim(r["quote"], 240)
    return row


def _dedupe(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        sig = (r["measure"], r["period"], r["basis"], r["definition"], r["value"])
        if sig not in seen:
            seen.add(sig)
            out.append(r)
    return out


# --- pilot3_ratio -----------------------------------------------------------------------------------
VALUATION_FIELDS = ("pe", "pb", "ev_ebitda", "market_cap", "dividend_yield_pct", "trailing_eps", "trailing_pat",
                    "net_worth", "net_debt", "trailing_ebitda", "close", "shares_outstanding")


def ratio(symbol: str, ratio: str, period: str | None = None, as_of: str | None = None,
          basis: str | None = None, limit: int = 8) -> dict[str, Any]:
    """Derived ratios (margins, ROE, growth, days ...) from ratio_panel; PE/PB/EV-EBITDA/market cap on a date
    from valuation_daily (``period`` or ``as_of`` as a YYYY-MM-DD day; latest on or before it)."""
    sym = resolve_symbol(symbol)
    key = re.sub(r"[\s\-/]+", "_", ratio.strip().lower())
    cap = _cap(limit)
    bas = (basis or "").strip().lower() or None
    day = _day(as_of, "as_of")
    if key in VALUATION_FIELDS or key in ("p_e", "p_b", "ev_to_ebitda", "dividend_yield"):
        key = {"p_e": "pe", "p_b": "pb", "ev_to_ebitda": "ev_ebitda", "dividend_yield": "dividend_yield_pct"}.get(key, key)
        when = period if period and re.fullmatch(r"\d{4}-\d{2}-\d{2}", period) else day or dt.date.today().isoformat()
        sql = (f"SELECT rowid, date, basis, {key} AS value, close, shares_outstanding, known_at, input_refs "
               f"FROM valuation_daily WHERE symbol=? AND date<=? AND {key} IS NOT NULL")
        args: list[Any] = [sym, when]
        if bas:
            sql += " AND basis=?"
            args.append(bas)
        extra, eargs = _asof(as_of)
        rows = _q(sql + extra + " ORDER BY date DESC, (basis='consolidated') DESC LIMIT ?", (*args, *eargs, cap))
        reply = _reply(sym, [{"ratio": key, "date": r["date"], "basis": r["basis"], "value": r["value"],
                              "inputs": {"close": r["close"], "shares_outstanding": r["shares_outstanding"]},
                              "provenance": _prov("valuation_daily", f"row {r['rowid']}", r["known_at"],
                                                  input_refs=_trim(r["input_refs"], 200))} for r in rows],
                       "pilot3_ratio")
        if key == "ev_ebitda" and not rows and _is_lender(sym):
            reply["note"] = ("EV/EBITDA is not defined for a bank, NBFC or insurer: the store keeps no such row "
                             "for a lender by design, it is not missing data")
        return reply
    names, allnames = _pick("ratio_panel", "metric", sym, ratio)
    if not names:
        return _reply(sym, [], "pilot3_ratio", available=allnames[:40] + list(VALUATION_FIELDS), metric_asked=ratio)
    kind, label = norm_period(period)
    where, args = f"p.symbol=? AND p.metric IN ({','.join('?' * len(names))})", [sym, *names]
    if label:
        where += " AND p.fiscal_period=?"
        args.append(label)
    if bas:
        where += " AND p.basis=?"
        args.append(bas)
    extra, eargs = _asof(as_of, "p.known_at")
    rows = _q(f"SELECT p.rowid, p.*, f.expression FROM ratio_panel p LEFT JOIN formula f ON f.formula_id=p.formula_id "
              f"WHERE {where}{extra} ORDER BY p.period_end DESC, (p.period_type='Q') DESC, "
              f"(p.basis='consolidated') DESC, p.known_at DESC LIMIT ?", (*args, *eargs, cap))
    return _reply(sym, [{"ratio": r["metric"], "period": r["fiscal_period"], "period_type": r["period_type"],
                         "basis": r["basis"], "value": r["value"], "unit": r["unit"], "formula": r["expression"],
                         "provenance": _prov("ratio_panel", f"row {r['rowid']}", r["known_at"],
                                             formula_id=r["formula_id"], input_refs=_trim(r["input_refs"], 240),
                                             derived=bool(r["is_derived"]))} for r in rows],
                  "pilot3_ratio", metrics_matched=names)


# --- pilot3_holding ---------------------------------------------------------------------------------
HOLDING_MAIN = ("promoter", "public", "fpi", "fpi_total", "institutions_domestic", "institutions_foreign",
                "mutual_funds", "insurance", "banks", "foreign", "indian", "bodies_corporate")


def holding(symbol: str, as_of: str, quarter_end: str | None = None, all_categories: bool = False) -> dict[str, Any]:
    """Shareholding pattern in force on ``as_of`` (the latest quarter whose filing was out by then) + shares
    outstanding.  Main categories by default; all_categories=true lists every filed category."""
    sym = resolve_symbol(symbol)
    day = _day(as_of, "as_of")
    if not day:
        raise DataError("bad_date", "as_of (YYYY-MM-DD) is required")
    qe = _day(quarter_end, "quarter_end")
    extra, eargs = _asof(day)
    row = _q(f"SELECT MAX(quarter_end) q FROM shp_category WHERE symbol=? AND quarter_end<=?{extra}"
             + (" AND quarter_end=?" if qe else ""), (sym, day, *eargs, *((qe,) if qe else ())))
    quarter = row[0]["q"] if row else None
    rows: list[dict] = []
    if quarter:
        flt = "" if all_categories else f" AND category IN ({','.join('?' * len(HOLDING_MAIN))})"
        cand = _q(f"SELECT rowid, * FROM shp_category WHERE symbol=? AND quarter_end=?{extra}{flt} "
                  "ORDER BY category, (source_kind='xbrl') DESC, known_at DESC",
                  (sym, quarter, *eargs, *(() if all_categories else HOLDING_MAIN)))
        seen = set()
        for r in cand:
            if r["category"] in seen:
                continue
            seen.add(r["category"])
            rows.append({"category": r["category"], "pct": r["pct"], "shares": r["shares"], "holders": r["holders"],
                         "quarter_end": r["quarter_end"], "source_kind": r["source_kind"],
                         "provenance": _prov("shp_category", f"{r['source_file'] or ''} [{r['source_db']}.{r['source_table']} "
                                             f"row {r['source_rowid']}]".strip(), r["known_at"],
                                             category_raw=r["category_raw"])})
    sc = _q(f"SELECT rowid, * FROM share_capital WHERE symbol=? AND event IS NULL AND as_of_date<=?{extra} "
            "AND shares_outstanding IS NOT NULL ORDER BY as_of_date DESC, (source_table='shp_category') DESC, "
            "known_at DESC LIMIT 1", (sym, day, *eargs))
    shares = None
    if sc:
        r = sc[0]
        shares = {"shares_outstanding": r["shares_outstanding"], "paid_up_capital": r["paid_up_capital"],
                  "face_value": r["face_value"], "as_of_date": r["as_of_date"], "basis": r["basis"],
                  "provenance": _prov("share_capital", f"{r['source_db']}.{r['source_table']} row {r['source_rowid']}",
                                      r["known_at"])}
    return _reply(sym, rows, "pilot3_holding", quarter_end=quarter, as_of=day, share_capital=shares,
                  hint=None if rows else "no shareholding row filed by that day for this company")


# --- pilot3_statements ------------------------------------------------------------------------------
def _term_hits(column: str, words: list[str]) -> tuple[str, list]:
    """SQL that scores a row by how many of ``words`` it carries (0 when no word was asked)."""
    if not words:
        return "0", []
    expr = " + ".join(f"({column} LIKE ?)" for _ in words)
    return expr, [f"%{word}%" for word in words]


def statements(symbol: str, topic: str | None = None, terms: str | None = None, date_from: str | None = None,
               date_to: str | None = None, as_of: str | None = None, limit: int = 10,
               role: str | None = None, period: str | None = None,
               rank_terms: str | None = None, latest: bool = False) -> dict[str, Any]:
    """Management statements from concall transcripts, exact quotes: topic tag (margin, guidance, capex, order ...),
    free ``terms`` (all words must appear), call-date window, role (ceo / cfo / md / mgmt).

    ``period`` (Q4FY26 / FY26) and ``rank_terms`` (the question's own words) rank the rows: a statement of the
    period asked, carrying more of the question's words, comes first; the newest call breaks a tie.  ``latest``
    keeps only the newest call's statements."""
    sym = resolve_symbol(symbol)
    where, args = "t.symbol=?", [sym]
    if latest:
        extra_latest, latest_args = _asof(as_of, "t2.known_at")
        where += (f" AND t.call_date=(SELECT MAX(t2.call_date) FROM transcript_statement t2 "
                  f"WHERE t2.symbol=?{extra_latest})")
        args += [sym, *latest_args]
    topic_sql, topic_args = "1", []
    if topic:
        # the tag ranks first rather than filtering: the sentence that answers a "what did they say about margins"
        # question is often tagged ``nim`` (or untagged) instead of ``margin``
        topic_sql = "t.topics LIKE ?"
        topic_args = [f"%{topic.strip().lower()}%"]
    for word in re.findall(r"[\w₹%&\-\.]+", terms or ""):
        where += " AND (t.statement LIKE ? OR t.quote LIKE ?)"
        args += [f"%{word}%", f"%{word}%"]
    if role:
        where += " AND t.role=?"
        args.append(role.strip().lower())
    for col, val, op in (("t.call_date", _day(date_from, "date_from"), ">="), ("t.call_date", _day(date_to, "date_to"), "<=")):
        if val:
            where += f" AND {col} {op} ?"
            args.append(val)
    extra, eargs = _asof(as_of, "t.known_at")
    _kind, label = norm_period(period)
    period_sql, period_args = "1", []
    if label:
        # a year's question is answered by its quarters too ("FY26": Q1FY26 ... Q4FY26)
        labels = ([f"Q{q}FY{label[2:]}" for q in (1, 2, 3, 4)] + [label]) if label.startswith("FY") else [label]
        period_sql = "(" + " OR ".join("(t.call_period=? OR t.period_discussed LIKE ?)" for _x in labels) + ")"
        for item in labels:
            period_args += [item, f"{item}%"]
    words = [w for w in re.findall(r"[\w₹%&\-\.]+", rank_terms or "") if len(w) > 2]
    score_sql, score_args = _term_hits("t.statement", words[:8])
    rows = _q(f"SELECT t.id, t.call_date, t.call_period, t.page, t.speaker, t.role, t.section, t.topics, "
              f"t.period_discussed, t.quote, t.is_fragment, t.known_at, t.doc_key, d.title, "
              f"(CASE WHEN {topic_sql} THEN 0 ELSE 1 END) AS topic_rank, "
              f"(CASE WHEN {period_sql} THEN 0 ELSE 1 END) AS period_rank, ({score_sql}) AS term_score "
              f"FROM transcript_statement t "
              f"LEFT JOIN doc d ON d.doc_key=COALESCE((SELECT a.doc_key FROM doc_alias a WHERE a.symbol=t.symbol "
              f"AND a.alias_key=t.doc_key), t.doc_key) WHERE {where}{extra} "
              f"ORDER BY topic_rank, period_rank, term_score DESC, t.is_fragment, t.call_date DESC, t.seq LIMIT ?",
              # the SELECT-list placeholders bind before the WHERE ones
              (*topic_args, *period_args, *score_args, *args, *eargs, _cap(limit)))
    out = [{"call_date": r["call_date"], "call_period": r["call_period"], "speaker": r["speaker"],
            "role": r["role"], "section": r["section"], "topics": r["topics"],
            "period_discussed": r["period_discussed"], "quote": _trim(r["quote"]),
            "provenance": _prov("transcript_statement", f"{r['doc_key']} p{r['page']}", r["known_at"],
                                title=r["title"], row_id=r["id"])} for r in rows]
    matched = any(topic in (row["topics"] or "") for row in out) if topic else None
    fallback = None
    if topic and not matched:
        # the tagger never emitted this topic: search the calls' own page text before answering "nothing said"
        alt = _call_page_hits(sym, topic, terms, rank_terms, date_from, date_to, as_of, latest, _cap(limit))
        if alt:
            out, fallback = alt, "doc_page_bm25"
    return _reply(sym, out, "pilot3_statements", fallback=fallback,
                  topic_matched=matched, hint=None if out else "no statement in the held calls matches these arguments")


def _call_page_hits(sym: str, topic: str, terms: str | None, rank_terms: str | None, date_from: str | None,
                    date_to: str | None, as_of: str | None, latest: bool, cap: int) -> list[dict]:
    """bm25 over the transcript ``doc_page`` text when ``transcript_statement`` has no row carrying the topic tag:
    the page's own sentence around the match, newest call first.  Empty when the pages carry nothing either."""
    words = [w for w in re.findall(r"[\w₹%&\-\.]+", " ".join(x for x in (topic, terms, rank_terms) if x or ""))
             if len(w) > 2][:8]
    if not words:
        return []
    match = _fts_query(" ".join(words), "and") or _fts_query(" ".join(words), "or")
    if not match:
        return []
    extra, eargs = _asof(as_of, "COALESCE(p.known_at, d.known_at)")
    date_sql, date_args = "", []
    for col, val, op in (("d.filing_date", _day(date_from, "date_from"), ">="),
                         ("d.filing_date", _day(date_to, "date_to"), "<=")):
        if val:
            date_sql += f" AND {col} {op} ?"
            date_args.append(val)
    latest_sql, latest_args = "", []
    if latest:
        latest_sql = (" AND COALESCE(d.known_at, d.filing_date)=(SELECT MAX(COALESCE(d2.known_at, d2.filing_date)) "
                      "FROM doc d2 WHERE d2.symbol=? AND d2.doc_type='transcript')")
        latest_args = [sym]
    rows = _q(f"SELECT d.doc_key, d.title, d.filing_date, p.page, p.known_at, "
              f"snippet(doc_page_fts, 0, '[', ']', ' … ', 40) snip FROM doc_page_fts f "
              f"JOIN doc_page p ON p.rowid=f.rowid JOIN doc d ON d.doc_key=p.doc_key "
              f"WHERE doc_page_fts MATCH ? AND p.symbol=? AND d.doc_type='transcript'{date_sql}{latest_sql}{extra} "
              f"ORDER BY d.filing_date DESC, rank LIMIT ?",
              (match, sym, *date_args, *latest_args, *eargs, cap))
    return [{"call_date": r["filing_date"], "call_period": None, "speaker": None, "role": None,
             "section": None, "topics": None, "period_discussed": None, "quote": _trim(r["snip"], QUOTE_CHARS),
             "provenance": _prov("doc_page", f"{r['doc_key']} p{r['page']}", r["known_at"] or None,
                                 title=_trim(r["title"], 120))} for r in rows]


# --- pilot3_guidance --------------------------------------------------------------------------------
GUIDANCE_METRICS = ("revenue_growth", "ebitda_margin", "order_intake", "nim", "credit_cost", "aum_growth",
                    "capex", "cost_of_production", "interest_cost", "ebitda_per_tonne", "other")


def guidance(symbol: str, metric: str | None = None, period: str | None = None, as_of: str | None = None,
             limit: int = 12) -> dict[str, Any]:
    """Rule-extracted forward guidance: one row per target (metric, target period, low/high, unit, direction,
    exact quote, speaker), newest first, with the row it revised (``revision_of`` and the previous low/high/date,
    so "did the guidance change between the two calls" is one call).  ``low`` and ``high`` are NULL on a target
    said in words ("high single-digit", "in the 70s, mid-70s or higher"): the direction and the quote carry it."""
    sym = resolve_symbol(symbol)
    names, allnames = ([], list(GUIDANCE_METRICS))
    if metric:
        names, allnames = _pick("guidance", "metric", sym, metric)
        if not names:
            return _reply(sym, [], "pilot3_guidance", available=allnames[:40], metric_asked=metric)
    kind, label = norm_period(period)
    where, args = "g.symbol=?", [sym]
    if names:
        where += f" AND g.metric IN ({','.join('?' * len(names))})"
        args += names
    if kind and label:
        where += " AND g.target_period=?"
        args.append(label)
    extra, eargs = _asof(as_of, "g.known_at")
    rows = _q(f"SELECT g.id, g.metric, g.target_period, g.low, g.high, g.unit, g.direction, g.said_on, g.doc_key, "
              f"g.page, g.quote, g.speaker, g.known_at, g.revision_of, g.extractor_rule, d.title, d.doc_type, "
              f"pv.low prev_low, pv.high prev_high, pv.said_on prev_said_on, pv.direction prev_direction "
              f"FROM guidance g LEFT JOIN doc d ON d.doc_key=g.doc_key "
              f"LEFT JOIN guidance pv ON pv.id=g.revision_of WHERE {where}{extra} "
              f"ORDER BY COALESCE(g.known_at, g.said_on) DESC, g.id DESC LIMIT ?", (*args, *eargs, _cap(limit)))
    out = []
    for r in rows:
        previous = None
        if r["revision_of"] is not None:
            previous = {"row_id": r["revision_of"], "low": r["prev_low"], "high": r["prev_high"],
                        "said_on": r["prev_said_on"], "direction": r["prev_direction"]}
        out.append({"metric": r["metric"], "period": r["target_period"], "low": r["low"], "high": r["high"],
                    "unit": r["unit"], "direction": r["direction"], "said_on": r["said_on"],
                    "quote": _trim(r["quote"]), "speaker": r["speaker"], "revision_of": r["revision_of"],
                    "previous": previous,
                    "changed": bool(previous and (previous["low"], previous["high"]) != (r["low"], r["high"])),
                    "provenance": _prov("guidance", f"{r['doc_key']} p{r['page']}", r["known_at"],
                                        doc_type=r["doc_type"], title=_trim(r["title"], 120), row_id=r["id"])})
    held = None
    if not out:   # say what the table does hold, so the next call can be exact
        held = [f"{r[0]} / {r[1]} ({r[2]} rows)" for r in _q(
            f"SELECT metric, target_period, COUNT(*) FROM guidance WHERE symbol=?"
            + (f" AND metric IN ({','.join('?' * len(names))})" if names else "")
            + " GROUP BY 1, 2 ORDER BY MAX(known_at) DESC LIMIT 40", (sym, *names))]
    return _reply(sym, out, "pilot3_guidance", metrics_matched=names or None, held_options=held)


# --- pilot3_docs ------------------------------------------------------------------------------------
def docs(symbol: str, doc_type: str | None = None, date_from: str | None = None, date_to: str | None = None,
         as_of: str | None = None, limit: int = 20) -> dict[str, Any]:
    """The documents pilot3 holds for a company, newest first (known_at = filing record), with page counts."""
    sym = resolve_symbol(symbol)
    where, args = "symbol=?", [sym]
    if doc_type:
        dtype = _DOC_TYPES.get(doc_type.strip().lower(), doc_type.strip().lower())
        where += " AND doc_type=?"
        args.append(dtype)
    for val, op in ((_day(date_from, "date_from"), ">="), (_day(date_to, "date_to"), "<=")):
        if val:
            where += f" AND substr(COALESCE(known_at, filing_date),1,10) {op} ?"
            args.append(val)
    extra, eargs = _asof(as_of)
    rows = _q(f"SELECT doc_key, doc_type, title, filing_date, known_at, pages, source, source_key FROM doc "
              f"WHERE {where}{extra} ORDER BY known_at DESC LIMIT ?", (*args, *eargs, _cap(limit, 20)))
    counts = {r[0]: r[1] for r in _q(f"SELECT doc_type, COUNT(*) FROM doc WHERE {where}{extra} GROUP BY doc_type",
                                     (*args, *eargs))}
    return _reply(sym, [{"doc_key": r["doc_key"], "doc_type": r["doc_type"], "title": _trim(r["title"], 160),
                         "filing_date": r["filing_date"], "pages": r["pages"],
                         "provenance": _prov("doc", r["source_key"] or r["source"], r["known_at"])} for r in rows],
                  "pilot3_docs", counts_by_type=counts)


# --- pilot3_search ----------------------------------------------------------------------------------
def _fts_query(text: str, mode: str) -> str:
    words = [w for w in re.findall(r"[\w₹%]+", text or "") if len(w) > 1 or w.isdigit()]
    return (" AND " if mode == "and" else " OR ").join(f'"{w}"' for w in words[:12])


_FY_TEXT = re.compile(r"(Q[1-4]|H[12])?\s*FY\s*'?\s*(\d{2,4})", re.I)


def _period_labels(text: str) -> list[str]:
    """['Q1FY27', 'FY26'] for the fiscal periods printed in a query ("Q1 FY27 results")."""
    out: list[str] = []
    for match in _FY_TEXT.finditer(text or ""):
        kind = (match.group(1) or "FY").upper()
        label = f"{kind}FY{match.group(2)[-2:]}"
        if label not in out:
            out.append(label)
    return out[:3]


def _period_in(text: str, label: str) -> bool:
    """Does a page print the period ("Q1FY27": Q1 FY27, Q1FY27, Q1 FY '27, Q1 FY2027; "FY26": FY26, FY '26, FY2026)?"""
    match = re.fullmatch(r"(Q[1-4]|H[12]|FY)FY(\d{2})", label or "")
    if not match:
        return False
    kind = match.group(1)
    year = f"(?:{match.group(2)}|20{match.group(2)})"
    pattern = rf"(?:\b{kind}\s*FY\s*'?\s*{year}\b)" if kind != "FY" else rf"\bFY\s*'?\s*{year}\b"
    return bool(re.search(pattern, text or "", re.I))


def _rank_hits(rows: list[sqlite3.Row], exact: set[int], or_ids: set[int], period: str | None,
               date_from: str | None, date_to: str | None, dtype: str | None) -> list[sqlite3.Row]:
    """bm25 order with a boost for an all-word match, the period asked, the filing window and the document type.

    bm25's own scale is not comparable across queries, so it is normalised inside the OR candidate set (1 = best
    match, the only set every row's rank comes from) and the boosts are added to that: the page that prints the
    quarter and was filed in the window the question names outranks a page that only happens to repeat its words.
    """
    ranks = [row["rank"] for row in rows if row["rid"] in or_ids]
    low = min(ranks) if ranks else 0.0
    scored = []
    for index, row in enumerate(rows):
        if row["rid"] in or_ids:
            # bm25's scale is not comparable across queries: the best hit is 1.0 and the rest keep their distance
            # from it as a ratio, so a boost means the same thing whatever the query's size.
            score = row["rank"] / low if low else 1.0
        else:
            score = 1.0                                   # an all-word hit outside the OR top
        if row["rid"] in exact:
            score += 0.20                                    # every query word is on the page
        day = str(row["filing_date"] or row["pk"] or row["dk"] or "")[:10]
        if date_from and date_to and date_from <= day <= date_to:
            score += 0.35                                    # filed inside the window the question names
        if period and _period_in(row["text"], period):
            score += 0.35                                    # the page prints the period asked
        if dtype and row["doc_type"] == dtype:
            score += 0.20                                    # the document type the question names
        scored.append((score, index, row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [row for _score, _index, row in scored]


def search(symbol: str, query: str, as_of: str | None = None, limit: int = 10,
           doc_type: str | None = None, period: str | None = None,
           date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
    """Full-text search over every held page (FTS5 bm25, ranked); exact snippet around the match, page and filing
    date.  ``period`` (Q1FY27 / FY26), ``date_from``+``date_to`` and ``doc_type`` boost the pages that print the
    period / were filed in the window / are of that document type."""
    sym = resolve_symbol(symbol)
    extra, eargs = _asof(as_of, "COALESCE(p.known_at, d.known_at)")
    dflt, dargs = "", ()
    dtype = _DOC_TYPES.get(doc_type.strip().lower(), doc_type.strip().lower()) if doc_type else None
    if dtype:
        dflt, dargs = " AND d.doc_type=?", (dtype,)
    start, end = _day(date_from, "date_from"), _day(date_to, "date_to")
    cap = _cap(limit)
    # the period the caller names is normalised to the label the pages print (FY27, Q1FY27), never prefixed twice:
    # norm_period('FY27') is ('FY', 'FY27'), so the reply can only ever echo a canonical label.
    kind, label = norm_period(period)
    labels = [label] if kind else _period_labels(query)
    period = labels[0] if labels else None
    select = (f"SELECT p.rowid rid, p.doc_key, p.page, p.text, p.known_at pk, d.known_at dk, d.doc_type, "
              f"d.title, d.filing_date, rank, snippet(doc_page_fts, 0, '[', ']', ' … ', 40) snip "
              f"FROM doc_page_fts f JOIN doc_page p ON p.rowid=f.rowid JOIN doc d ON d.doc_key=p.doc_key "
              f"WHERE doc_page_fts MATCH ? AND p.symbol=?{dflt}{extra} ORDER BY rank LIMIT ?")
    rows_or, rows_and = [], []
    for mode in ("or", "and"):
        match = _fts_query(query, mode)
        if not match:
            raise DataError("bad_query", "query needs at least one word")
        found_rows = _q(select, (match, sym, *dargs, *eargs, cap * 20))
        if mode == "or":
            rows_or = found_rows
        else:
            rows_and = found_rows
        if mode == "or" and not rows_and and _fts_query(query, "and") == match:
            rows_and = rows_or       # one word: the two queries are the same
    or_ids = {row["rid"] for row in rows_or}
    exact = {row["rid"] for row in rows_and}
    found: dict[int, sqlite3.Row] = {row["rid"]: row for row in rows_or}
    for row in rows_and:
        found.setdefault(row["rid"], row)
    rows = _rank_hits(list(found.values()), exact, or_ids, period, start, end, dtype)[:cap]
    match_mode = None if not rows else ("and" if rows[0]["rid"] in exact else "or")
    return _reply(sym, [{"doc_type": r["doc_type"], "title": _trim(r["title"], 120), "filing_date": r["filing_date"],
                         "page": r["page"], "snippet": _trim(r["snip"], 420),
                         "provenance": _prov("doc_page", f"{r['doc_key']} p{r['page']}", r["pk"] or r["dk"])}
                        for r in rows], "pilot3_search", match_mode=match_mode, period=period)


# --- pilot3_sql -------------------------------------------------------------------------------------
SQL_TEXT_CHARS = 400          # the per-cell cut the answer tools have always used
SQL_MAX_TEXT_CHARS = 8000     # hard cap: long page text must be asked for, never returned by default


def sql(query: str, limit: int = 100, timeout_seconds: float = 5.0,
        max_chars: int = SQL_TEXT_CHARS) -> dict[str, Any]:
    """Bounded, read-only SELECT/WITH over pilot3.db (any table; see ``schema`` rows below on a miss).

    Text cells are cut at ``max_chars`` (default 400, hard cap 8000): a question about wording, a whole
    paragraph or a long quote passes ``max_chars`` explicitly, otherwise the page text is truncated."""
    text = core._strip_sql(query or "")
    if not text:
        raise DataError("bad_query", "pilot3_sql needs a SELECT or WITH query")
    if len(core._statements(text)) != 1:
        raise DataError("not_select", "only one read-only statement is allowed")
    if not re.match(r"^(SELECT|WITH)\b", text, re.IGNORECASE):
        raise DataError("not_select", "only SELECT / WITH queries are allowed")
    if core._WRITE_WORDS.search(text):
        raise DataError("not_select", "write/DDL keywords are not allowed")
    limit = max(1, min(int(limit), 500))
    try:
        chars = max(1, min(int(max_chars), SQL_MAX_TEXT_CHARS))
    except (TypeError, ValueError):
        raise DataError("bad_max_chars", f"max_chars must be an integer 1..{SQL_MAX_TEXT_CHARS}")
    started = time.perf_counter()
    con = connect()
    wrapped = f"SELECT * FROM ({text}) AS _q LIMIT {limit + 1}"
    try:
        cur = con.execute(wrapped)
        columns = [d[0] for d in cur.description]
        raw = cur.fetchall()
    except core.QueryTimeout as exc:
        raise DataError("query_timeout", str(exc))
    except sqlite3.DatabaseError as exc:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '%fts%'")]
        raise DataError("sql_error", f"{type(exc).__name__}: {exc}. Tables: {', '.join(tables)}")
    rows = [[core._jsonable(v) if not isinstance(v, str) else _trim(v, chars) for v in r] for r in raw[:limit]]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": len(raw) > limit,
            "max_chars": chars, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "provenance": _db_prov(note="read-only SELECT/WITH, row-limited")}
