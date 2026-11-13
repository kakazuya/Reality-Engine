"""What one pilot3 store holds for one company, for the model-written lookup plan (T-205 round 4).

``build(db, symbol, as_of)`` reads the SAME tables the pilot3 lookups read, so every name it prints is a name
``lookups_pilot3`` accepts; ``render(menu)`` is the text the planner sees (under 8,000 characters).

Read-only: one ``connect_ro`` connection, no writes.  A table or column an older build lacks is skipped, never an
error.  ``as_of`` keeps only rows known on or before that day, exactly as the lookups do.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from reality_engine.db.readonly import connect_ro

RENDER_LIMIT = 8000

# The words ``pilot3_fact`` serves without a metric name (``_FACT_SHARES`` / ``_FACT_HOLDING_WORDS``).
FACT_EXTRA = ("share_count", "shares_outstanding", "share_capital", "shares", "equity_shares",
              "promoter_holding", "shareholding", "promoter")

_PERIOD_RE = re.compile(r"^(?:(Q[1-4])|(H[12])|(9M))?\s*FY\s*(\d{2,4})$", re.I)
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_QUARTER_ORDER = {"H1": 0, "Q1": 1, "Q2": 2, "9M": 3, "Q3": 3, "Q4": 4, "H2": 5, "FY": 9}


def _period_key(label: str) -> tuple[int, int]:
    """Fiscal order of a Q/H/FY label; unparseable labels sort last."""
    m = _PERIOD_RE.match(str(label or "").replace(" ", ""))
    if not m:
        return (9999, 9)
    year = int(m.group(4))
    if year < 100:
        year += 2000
    head = (m.group(1) or m.group(2) or m.group(3) or "FY").upper()
    return (year, _QUARTER_ORDER.get(head, 7))


def _norm(name: str) -> str:
    """The spelling ``lookups_pilot3._metric_key`` uses: spaces / dashes / slashes / % become underscores."""
    return re.sub(r"[\s\-/%]+", "_", str(name or "").strip().lower())


def _canonical(label) -> str:
    """``q4fy23`` -> ``Q4FY23``; an ISO date or any other label is left alone."""
    text = str(label or "").strip()
    m = _PERIOD_RE.match(re.sub(r"\s+", "", text))
    if not m:
        return text
    head = (m.group(1) or m.group(2) or m.group(3) or "FY").upper()
    year = int(m.group(4))
    yy = year % 100 if year >= 100 else year
    return f"FY{yy:02d}" if head == "FY" else f"{head}FY{yy:02d}"


def _sort_periods(periods) -> list[str]:
    values = [_canonical(p) for p in periods if p]
    if values and all(_ISO_RE.match(p) for p in values):
        return sorted(values)
    return sorted(values, key=_period_key)


def _range(pairs) -> str:
    """``Q1FY25..Q2FY27`` (or the single label); a compact period range, never every row."""
    ordered = _sort_periods(pairs)
    if not ordered:
        return ""
    if len(ordered) == 1:
        return ordered[0]
    return f"{ordered[0]}..{ordered[-1]}"


def _table_exists(con, table: str) -> bool:
    try:
        row = con.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (table,)).fetchone()
        return bool(row)
    except sqlite3.Error:
        return False


def _q(con, sql: str, args=()) -> list[dict]:
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(sql, args)]
    except sqlite3.Error:
        return []


def _add(bucket: dict, name, period, table: str) -> None:
    entry = bucket.setdefault(str(name), {"periods": set(), "tables": set()})
    if period:
        entry["periods"].add(_canonical(period))
    entry["tables"].add(table)


def _col(con, table: str, column: str) -> bool:
    if not _table_exists(con, table):
        return False
    return any(str(r["name"]) == column for r in _q(con, f'PRAGMA table_info("{table}")'))


def build(db, symbol: str, as_of: str) -> dict:
    """The store's coverage for this company on or before ``as_of``, as a JSON-safe dict."""
    symbol = str(symbol or "").strip()
    if not symbol:
        raise ValueError("menu.build needs the company symbol: an empty symbol silently disables every lookup")
    as_of = str(as_of or "")[:10]
    con = connect_ro(Path(db), timeout_s=30.0)
    try:
        company = (_q(con, "SELECT name FROM company WHERE symbol=? LIMIT 1", (symbol,)) or [{}])[0].get("name", "")
        day = as_of or "9999-12-31"
        fin: dict[str, dict] = {}
        fin_periods: dict[str, set] = {}
        tables: dict[str, int] = {}
        for table, period_col in (("fin_annual_line", "fiscal_year"), ("fin_quarter_xbrl", "fiscal_period"),
                                  ("fin_quarter_printed", "fiscal_period")):
            if not _table_exists(con, table):
                continue
            rows = _q(con, f"SELECT COUNT(*) n FROM {table} WHERE symbol=? AND substr(known_at,1,10)<=?",
                      (symbol, day))
            tables[table] = int((rows or [{}])[0].get("n") or 0)
            for r in _q(con, f"SELECT line_item, {period_col} p FROM {table} WHERE symbol=? "
                             f"AND substr(known_at,1,10)<=? AND line_item IS NOT NULL", (symbol, day)):
                _add(fin, r["line_item"], r["p"], table)
                if r["p"]:
                    fin_periods.setdefault(table, set()).add(str(r["p"]))
        kpi: dict[str, dict] = {}
        for r in _q(con, "SELECT metric, fiscal_period p FROM kpi_series WHERE symbol=? "
                         "AND substr(known_at,1,10)<=? AND metric IS NOT NULL", (symbol, day)):
            _add(kpi, r["metric"], r["p"], "kpi_series")
        ratios: dict[str, dict] = {}
        for r in _q(con, "SELECT metric, fiscal_period p FROM ratio_panel WHERE symbol=? "
                         "AND substr(known_at,1,10)<=? AND metric IS NOT NULL", (symbol, day)):
            _add(ratios, r["metric"], r["p"], "ratio_panel")
        valuation: dict = {}
        if _table_exists(con, "valuation_daily"):
            row = (_q(con, "SELECT MIN(date) f, MAX(date) l, COUNT(*) n FROM valuation_daily WHERE symbol=? "
                           "AND date<=?", (symbol, as_of or "9999-12-31")) or [{}])[0]
            valuation = {"fields": ["pe", "pb", "ev_ebitda", "market_cap", "dividend_yield_pct", "trailing_eps",
                                    "trailing_pat"],
                         "start": row.get("f") or "", "end": row.get("l") or "", "rows": int(row.get("n") or 0)}
        guidance: dict[str, dict] = {}
        if _table_exists(con, "guidance"):
            for r in _q(con, "SELECT metric, target_period, said_on FROM guidance WHERE symbol=? "
                             "AND substr(known_at,1,10)<=? AND metric IS NOT NULL", (symbol, day)):
                entry = guidance.setdefault(str(r["metric"]), {"periods": set(), "calls": set()})
                entry["periods"].add(str(r["target_period"] or ""))
                if r.get("said_on"):
                    entry["calls"].add(str(r["said_on"])[:10])
        holding: dict = {"categories": [], "quarters": []}
        if _table_exists(con, "shp_category"):
            cats = _q(con, "SELECT category, quarter_end FROM shp_category WHERE symbol=? "
                           "AND substr(known_at,1,10)<=? AND category IS NOT NULL", (symbol, day))
            holding["categories"] = sorted({str(r["category"]) for r in cats})
            holding["quarters"] = _sort_periods({str(r["quarter_end"])[:10] for r in cats if r.get("quarter_end")})
        price: dict = {}
        if _table_exists(con, "price_delivery"):
            row = (_q(con, "SELECT MIN(date) f, MAX(date) l, COUNT(*) n FROM price_delivery WHERE symbol=? "
                           "AND date<=?", (symbol, as_of or "9999-12-31")) or [{}])[0]
            price = {"start": row.get("f") or "", "end": row.get("l") or "", "sessions": int(row.get("n") or 0)}
        share: dict = {}
        if _table_exists(con, "share_capital"):
            row = (_q(con, "SELECT MIN(as_of_date) f, MAX(as_of_date) l, COUNT(*) n FROM share_capital "
                           "WHERE symbol=? AND substr(known_at,1,10)<=?", (symbol, day)) or [{}])[0]
            share = {"start": row.get("f") or "", "end": row.get("l") or "", "rows": int(row.get("n") or 0)}
        docs: list[dict] = []
        if _table_exists(con, "doc"):
            for r in _q(con, "SELECT doc_key, doc_type, title, COALESCE(known_at, filing_date) d, pages FROM doc "
                             "WHERE symbol=? AND substr(COALESCE(known_at, filing_date),1,10)<=? "
                             "ORDER BY d DESC", (symbol, day)):
                docs.append({"doc_key": r["doc_key"], "doc_type": (r.get("doc_type") or "").lower(),
                             "title": r.get("title") or "", "date": str(r.get("d") or "")[:10],
                             "known_at": str(r.get("d") or ""), "pages": r.get("pages")})
        topics: set[str] = set()
        if _table_exists(con, "transcript_statement"):
            for r in _q(con, "SELECT DISTINCT topics FROM transcript_statement WHERE symbol=? "
                             "AND substr(known_at,1,10)<=? AND topics IS NOT NULL", (symbol, day)):
                for topic in str(r["topics"]).split(","):
                    if topic.strip():
                        topics.add(topic.strip())
        atoms: dict = {}
        if _table_exists(con, "page_atom"):
            row = (_q(con, "SELECT COUNT(*) n FROM page_atom WHERE symbol=? AND substr(known_at,1,10)<=?",
                      (symbol, day)) or [{}])[0]
            atoms = {"atoms": int(row.get("n") or 0),
                     "periods": _sort_periods({str(r.get("period") or "") for r in
                                               _q(con, "SELECT DISTINCT period FROM page_atom WHERE symbol=? "
                                                       "AND substr(known_at,1,10)<=? LIMIT 400",
                                                  (symbol, day))})}
        events: dict = {}
        if _table_exists(con, "event"):
            kinds = _q(con, "SELECT kind, COUNT(*) n FROM event WHERE symbol=? AND substr(known_at,1,10)<=? "
                            "GROUP BY kind", (symbol, day))
            events = {"kinds": [str(r["kind"]) for r in kinds if r.get("kind")],
                      "count": sum(int(r.get("n") or 0) for r in kinds)}
        doc_prefix = _common_prefix([d["doc_key"] for d in docs])
        periods = set()
        for bucket in (fin, kpi, ratios):
            for entry in bucket.values():
                periods.update(entry["periods"])
        periods.update(atoms.get("periods") or [])
        index = {
            "fact": sorted(set(fin) | set(kpi) | set(ratios) | set(FACT_EXTRA) | set(holding["categories"])
                           | set(valuation.get("fields") or [])),
            "fin": sorted(fin), "kpi": sorted(kpi), "ratio": sorted(ratios),
            "doc_keys": [d["doc_key"] for d in docs],
            "doc_types": sorted({d["doc_type"] for d in docs if d["doc_type"]}),
            "categories": holding["categories"],
            "periods": _sort_periods(periods),
        }
        return {"symbol": symbol, "as_of": as_of, "company": company, "tables": tables, "financial_lines": fin,
                "fin_periods": {t: _sort_periods(ps) for t, ps in fin_periods.items()},
                "kpi": kpi, "ratios": ratios, "valuation": valuation, "guidance": guidance,
                "holding": holding, "price": price, "share_capital": share, "docs": docs,
                "doc_prefix": doc_prefix, "topics": sorted(topics), "atoms": atoms, "events": events,
                "index": index}
    finally:
        con.close()


def _common_prefix(keys: list[str]) -> str:
    """The directory every doc key shares, so the menu can print relative keys (the plan expands them back)."""
    keys = [k for k in keys if k]
    if not keys:
        return ""
    prefix = keys[0]
    for key in keys[1:]:
        i = 0
        while i < min(len(prefix), len(key)) and prefix[i] == key[i]:
            i += 1
        prefix = prefix[:i]
    cut = prefix.rfind("/")
    return prefix[: cut + 1] if cut > 0 else ""


def _rel(key: str, prefix: str) -> str:
    return key[len(prefix):] if prefix and str(key).startswith(prefix) else str(key)


def _lines(menu: dict) -> list[str]:
    sym = menu.get("symbol") or ""
    lines: list[str] = []
    head = f"STORE MENU for {sym}"
    if menu.get("company"):
        head += f" ({menu['company']})"
    head += f", data known on or before {menu.get('as_of') or 'any day'}."
    lines.append(head)
    lines.append("Plan lookups with the names EXACTLY as printed below. "
                 + (f"Doc keys are relative to {menu.get('doc_prefix')}" if menu.get("doc_prefix") else ""))
    if menu.get("tables"):
        lines.append("FINANCIAL-LINE TABLES (rows): " + ", ".join(f"{t} {n}" for t, n in sorted(menu["tables"].items())))
    idx_periods = menu.get("index", {}).get("periods") or []
    if idx_periods:
        lines.append(f"FISCAL PERIODS HELD: {_range(idx_periods)} ({len(idx_periods)} labels)")
    fin = menu.get("financial_lines") or {}
    fin_periods = menu.get("fin_periods") or {}
    if fin:
        annual = sorted(n for n, e in fin.items() if "fin_annual_line" in e["tables"])
        quarterly = sorted(n for n, e in fin.items() if "fin_quarter_xbrl" in e["tables"])
        printed = sorted(n for n, e in fin.items() if "fin_quarter_printed" in e["tables"])
        only_annual = sorted(n for n in annual if n not in quarterly)
        lines.append("fin (measure=):")
        if annual:
            per = _range(fin_periods.get("fin_annual_line") or [])
            lines.append(f"  annual {per} (fin_annual_line, also quarterly): "
                         + ", ".join(n for n in annual if n not in only_annual))
        if only_annual:
            per = _range(fin_periods.get("fin_annual_line") or [])
            lines.append(f"  annual ONLY {per} (not in fin_quarter_xbrl; ask with an annual period; "
                         "cash flow and balance sheet live here): " + ", ".join(only_annual))
        if quarterly:
            per = _range(fin_periods.get("fin_quarter_xbrl") or [])
            lines.append(f"  quarterly {per} (fin_quarter_xbrl): " + ", ".join(quarterly))
        printed_only = sorted(n for n in printed if n not in quarterly)
        if printed_only:
            per = _range(fin_periods.get("fin_quarter_printed") or [])
            lines.append(f"  quarterly printed {per} (fin_quarter_printed, only): " + ", ".join(printed_only))
    if menu.get("guidance"):
        lines.append("guidance (metric=; target period; said_on call dates):")
        for metric, e in sorted(menu["guidance"].items()):
            calls = ", ".join(sorted(e["calls"]))
            lines.append(f"  {metric}: targets {', '.join(sorted(e['periods']))}; said on {calls}")
    hold = menu.get("holding") or {}
    if hold.get("categories"):
        quarters = hold["quarters"]
        shown = (f"{quarters[0]}..{quarters[-1]} ({len(quarters)} quarter ends)" if len(quarters) > 8
                 else ", ".join(quarters))
        lines.append(f"holding (category=; quarter ends held {shown}): " + ", ".join(hold["categories"]))
    price = menu.get("price") or {}
    if price:
        lines.append(f"price (tech route; NSE sessions {price.get('start')}..{price.get('end')}, "
                     f"{price.get('sessions')}): kinds reaction, gaps, rsi, ma, volume_spikes, range.")
        lines.append("price_rows (route price_rows; dates=[YYYY-MM-DD,...] or start=/end=): each session's "
                     "open/high/low/close, the previous session's close, the adjusted close; start/end also gives "
                     "the first-to-last adjusted return (use it for a prior close or a multi-year return).")
    if menu.get("share_capital"):
        s = menu["share_capital"]
        lines.append(f"share count (fact metric=share_count; {s.get('start')}..{s.get('end')})")
    docs = menu.get("docs") or []
    prefix = menu.get("doc_prefix") or ""
    transcripts = [d for d in docs if d["doc_type"] == "transcript"]
    decks = [d for d in docs if d["doc_type"] == "deck"]
    others: dict[str, list] = {}
    for d in docs:
        if d["doc_type"] not in ("transcript", "deck"):
            others.setdefault(d["doc_type"] or "other", []).append(d)
    if transcripts:
        lines.append("calls (doc_type=transcript; page route: doc_key=..., page=N):")
        for d in transcripts:
            lines.append(f"  {_rel(d['doc_key'], prefix)} {d['date']} {d.get('pages') or '?'}p")
    if decks:
        lines.append("decks (doc_type=deck; page route; doc_key; date; pages):")
        for d in decks:
            lines.append(f"  {_rel(d['doc_key'], prefix)} {d['date']} {d.get('pages') or '?'}p")
    results_docs = [d for d in docs if d["doc_type"] == "results"]
    if results_docs:
        lines.append("FILINGS for a reaction question (price_rows event_doc=...; filing timestamp IST; pages):")
        for d in results_docs[:12]:
            lines.append(f"  {_rel(d['doc_key'], prefix)} {d.get('known_at') or d['date']} {d.get('pages') or '?'}p")
    if menu.get("kpi"):
        lines.append("kpi (kpi=; periods held):")
        lines.append("  " + "; ".join(f"{n} {_range(e['periods'])}" for n, e in sorted(menu["kpi"].items())))
    if menu.get("ratios"):
        lines.append("ratio (ratio=; periods held):")
        lines.append("  " + "; ".join(f"{n} {_range(e['periods'])}" for n, e in sorted(menu["ratios"].items())))
    val = menu.get("valuation") or {}
    if val:
        lines.append(f"valuation (ratio= on a date, period=YYYY-MM-DD; {val.get('start')}..{val.get('end')}, "
                     f"{val.get('rows')} rows): " + ", ".join(val.get("fields") or []))
    if menu.get("topics"):
        lines.append("statements (topic=, or date_from=date_to=<call date>): " + ", ".join(menu["topics"]))
    if others:
        counts = ", ".join(f"{t} {len(v)} ({v[-1]['date']}..{v[0]['date']})" for t, v in sorted(others.items()))
        lines.append(f"other documents (doc_type=count, date range): {counts}")
    atoms = menu.get("atoms") or {}
    if atoms:
        lines.append(f"cells (terms=; {atoms.get('atoms')} page atoms; periods {_range(atoms.get('periods') or [])})")
    if menu.get("events"):
        lines.append(f"events (topic route finds these): {menu['events'].get('count')} rows, kinds "
                     + ", ".join(menu["events"].get("kinds") or []))
    return lines


def render(menu: dict, limit: int = RENDER_LIMIT) -> str:
    """The planner's view of the menu: under ``limit`` characters, the least useful tail lines cut first."""
    lines = _lines(menu)
    text = "\n".join(lines)
    if len(text) <= limit:
        return text
    kept = list(lines)
    dropped = 0
    while kept and len("\n".join(kept)) > limit - 40:
        kept.pop()
        dropped += 1
    return "\n".join(kept + [f"(menu trimmed at {limit} characters: {dropped} trailing lines cut)"])
