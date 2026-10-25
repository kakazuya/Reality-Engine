"""Build point-in-time theme universes from the data itself.

    python -m reality_engine.scripts.build_universe_membership \
        [--db PATH] [--data-root PATH] [--themes PATH] [--dry-run]

Every run rebuilds ``equity_intelligence.db:universe_membership`` from evidence and
writes one diff row to ``universe_membership_runs``.  Source databases are opened
read-only; only the target ``--db`` is written (default:
``<data-root>/equity_intelligence.db``).

Signals, strongest first:
  segment       XBRL segment revenue (contexts carrying the theme name) or AR/deck
                segment rows; weight = that segment's share of revenue
  subsidiary    BSE announcement of a subsidiary / acquisition / JV in the theme
  stated_pivot  concall statement about entering the theme
  industry      NSE industry classification (company_industry)
  curated       seed in plugins/reality-data/server/universes.yaml

A segment membership exits after the segment is 0/absent for 2 consecutive quarters
(measured on the XBRL quarterly filing series).  ``pivot`` is true when the theme's
segment is the company's largest by revenue in that filing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_THEMES = ROOT / "plugins" / "reality-data" / "server" / "universes.yaml"
METHOD_RANK = {"segment": 4, "subsidiary": 3, "stated_pivot": 2, "industry": 1, "curated": 0}
ENTRY_WORDS = ("enter", "entering", "foray", "launch", "commission", "new segment",
               "diversif", "set up", "setting up", "ventur", "expand", "expanding")
SHARE_WORDS = ("share", "mix", "contribution", "of revenue", "of sales", "of income")
GROWTH_WORDS = ("growth", "change", "yoy", "y-on-y", "margin", "ebitda", "roce", "roe",
                "cagr", "increase", "decline", "per cent", "% change")
SEGMENT_CONCEPTS = ("SegmentRevenue", "SegmentRevenueFromOperations")


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _hit(text: Any, keywords: list[str]) -> str:
    """Whole-token keyword match: "oil" matches "oil", not "boiler"."""
    hay = _norm(text)
    if not hay:
        return ""
    words = set(hay.split())
    for keyword in keywords:
        needle = _norm(keyword)
        if needle and (needle in hay if " " in needle else needle in words):
            return keyword
    return ""


def _date(value: Any) -> str:
    try:
        return dt.date.fromisoformat(str(value or "")[:10]).isoformat()
    except ValueError:
        return ""


def _money_unit(unit: str) -> bool:
    low = str(unit or "").lower()
    return any(tok in low for tok in ("rs", "inr", "crore", "lakh", "million", "billion"))


def _pct_weight(text: Any, unit: str, value: Any) -> float:
    """A percent row is a revenue share only when it says share/mix and is not growth."""
    low = str(text or "").lower()
    if str(unit or "") != "%" or any(w in low for w in GROWTH_WORDS):
        return 0.0
    if not any(w in low for w in SHARE_WORDS):
        return 0.0
    return min(float(value) / 100.0, 1.0)


def _open(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def _query(con: sqlite3.Connection | None, sql: str, params: tuple = ()) -> list[tuple]:
    if con is None:
        return []
    try:
        return con.execute(sql, params).fetchall()
    except sqlite3.DatabaseError:
        return []


def load_themes(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw.get("themes") or {}


# ---------------------------------------------------------------------------
# Segment evidence: XBRL quarterly series (drives joins, exits and pivots)
# ---------------------------------------------------------------------------
def xbrl_points(xb: sqlite3.Connection | None, themes: dict[str, Any],
                symbols: dict[str, str]) -> dict[tuple[str, str], list[tuple]]:
    filings = {}
    for file, isin, symbol, period_end, known_at in _query(
        xb,
        "SELECT f.file, fi.isin, f.symbol, f.period_end, "
        "COALESCE(f.dissem_ts, f.broadcast_ts, f.filing_ts, f.period_end) "
        "FROM filings f JOIN filings_isin fi ON fi.file = f.file WHERE f.period_end IS NOT NULL",
    ):
        if isin:
            filings[file] = (str(isin), str(symbol or ""), str(period_end), str(known_at or period_end))
            symbols.setdefault(str(isin), str(symbol or ""))

    facts: dict[str, dict[str, float]] = {}
    for file, concept, context, value in _query(
        xb, f"SELECT file, concept, context, value FROM facts "
            f"WHERE concept IN {SEGMENT_CONCEPTS} AND value IS NOT NULL",
    ):
        if file not in filings or not context:
            continue
        bucket = facts.setdefault(file, {})
        if context not in bucket or concept == "SegmentRevenue":
            bucket[context] = float(value)

    # Per-ISIN quarterly timelines, so a segment that disappears can be recorded
    # as a zero quarter (the exit rule needs the absence, not just the absence of
    # a positive fact).
    timeline: dict[str, list[tuple]] = {}
    for file, contexts in facts.items():
        isin, _symbol, period_end, known_at = filings[file]
        positives = {ctx: val for ctx, val in contexts.items() if val > 0}
        total = sum(positives.values())
        if total > 0:
            timeline.setdefault(isin, []).append(
                (period_end, known_at, positives, total,
                 max(positives, key=positives.get), file))

    points: dict[tuple[str, str], list[tuple]] = {}
    for isin, filings_for_isin in timeline.items():
        filings_for_isin.sort(key=lambda row: (row[0] or "", row[1] or ""))
        for theme, cfg in themes.items():
            keywords = cfg.get("keywords") or []
            appeared = False
            for period_end, known_at, positives, total, largest_ctx, file in filings_for_isin:
                known = _date(known_at) or _date(period_end)
                matched = [(ctx, val) for ctx, val in positives.items() if _hit(ctx, keywords)]
                if matched:
                    ctx, val = max(matched, key=lambda pair: pair[1])
                    share, pivot = val / total, ctx == largest_ctx
                    quote = f"{ctx} segment revenue = {val:g} ({share:.1%} of segment revenue)"
                    evidence_id = f"results_xbrl.db:facts:{file}:{ctx}:{period_end}"
                    appeared = True
                elif appeared:
                    share, pivot, quote = 0.0, False, "no theme segment in this quarter"
                    evidence_id = f"results_xbrl.db:facts:{period_end}:{theme}:absent"
                else:
                    continue
                points.setdefault((isin, theme), []).append(
                    (period_end, known, share, pivot, evidence_id, quote))
    return points


def segment_intervals(points: list[tuple]) -> list[dict[str, Any]]:
    """Merge quarterly evidence into memberships; exit after 2 empty quarters."""
    out: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    zero_run, prev_period = 0, ""
    for period_end, known, share, pivot, evidence_id, quote in sorted(points):
        consecutive = bool(
            prev_period and period_end
            and (dt.date.fromisoformat(period_end) - dt.date.fromisoformat(prev_period)).days <= 200
        )
        prev_period = period_end
        if share > 0:
            if current is None:
                current = {"valid_from": known or period_end, "weight": share,
                           "evidence_id": evidence_id, "evidence_quote": quote, "pivot": bool(pivot)}
            else:
                current.update(weight=share, evidence_id=evidence_id,
                               evidence_quote=quote, pivot=current["pivot"] or bool(pivot))
            zero_run = 0
        elif current is not None:
            zero_run = zero_run + 1 if consecutive else 1
            if zero_run >= 2:
                current["valid_to"] = known or period_end
                out.append(current)
                current, zero_run = None, 0
    if current is not None:
        out.append(current)
    return out


# ---------------------------------------------------------------------------
# Other evidence
# ---------------------------------------------------------------------------
def _fts_query(keywords: list[str]) -> str:
    return " OR ".join('"' + str(kw).replace('"', "") + '"' for kw in keywords)


def _ar_evidence(ar: sqlite3.Connection | None, themes: dict[str, Any],
                 symbols: dict[str, str]) -> list[dict[str, Any]]:
    keywords = [kw for cfg in themes.values() for kw in (cfg.get("keywords") or [])]
    if not keywords:
        return []
    # ar_facts has 32M rows: the FTS index (0.04s) picks the keyword rows, then
    # only the matched documents are read for a segment-revenue denominator.
    rows = _query(
        ar,
        "SELECT a.doc_id, a.piece, a.isin, a.symbol, a.fiscal_year, a.filed_at, a.category, "
        "a.item, a.value, a.unit, a.quote FROM ar_facts_fts f JOIN ar_facts a ON a.rowid = f.rowid "
        "WHERE ar_facts_fts MATCH ? AND a.value IS NOT NULL LIMIT 20000",
        (_fts_query(keywords),),
    )
    rows = [r for r in rows
            if "segment" in str(r[6]).lower() or "segment" in str(r[7]).lower()
            or "mix" in str(r[7]).lower()]
    doc_ids = sorted({r[0] for r in rows if str(r[9] or "") != "%" and r[0] is not None})
    denom: dict[tuple, float] = {}
    if doc_ids:
        marks = ",".join("?" for _ in doc_ids)
        for doc, fy, unit, total in _query(
            ar,
            "SELECT doc_id, fiscal_year, unit, SUM(value) FROM ar_facts "
            f"WHERE doc_id IN ({marks}) AND value > 0 "
            "AND (lower(category) LIKE '%segment%' OR lower(item) LIKE '%segment%') "
            "AND (lower(item) LIKE '%revenue%' OR lower(category) LIKE '%revenue%') "
            "GROUP BY doc_id, fiscal_year, unit",
            tuple(doc_ids),
        ):
            denom[(doc, fy, unit)] = float(total or 0)
    out = []
    for doc, piece, isin, symbol, fy, filed_at, category, item, value, unit, quote in rows:
        # Only the company's own revenue line counts as segment evidence: item /
        # category, never the prose quote (a bank's MD&A mentions crude oil too).
        text = f"{item} {category}"
        unit = str(unit or "")
        item_low = str(item or "").lower()
        revenue_like = any(w in item_low for w in ("revenue", "turnover", "sales", "income"))
        if unit != "%" and not (revenue_like and _money_unit(unit)):
            continue
        theme = next((t for t, cfg in themes.items() if _hit(text, cfg.get("keywords") or [])), "")
        if not theme or not isin:
            continue
        if unit == "%":
            share = _pct_weight(item, unit, value)
        else:
            total = denom.get((doc, fy, unit)) or 0.0
            share = (float(value) / total if total > 0
                     and not any(w in item_low for w in GROWTH_WORDS) else 0.0)
        symbols.setdefault(str(isin), str(symbol or ""))
        out.append({
            "theme": theme, "isin": str(isin), "method": "segment",
            "valid_from": _date(filed_at), "weight": round(min(share, 1.0), 6),
            "evidence_id": f"ar_facts.db:ar_facts:{doc}:{piece}",
            "evidence_quote": f"{str(item)[:150]}: {value} {unit}".strip(),
            "pivot": False,
        })
    return out


def _deck_evidence(dk: sqlite3.Connection | None, themes: dict[str, Any],
                   symbols: dict[str, str]) -> list[dict[str, Any]]:
    keywords = [kw for cfg in themes.values() for kw in (cfg.get("keywords") or [])]
    if not keywords:
        return []
    # deck_sources.sha256 is not indexed, so resolve sources through a dict; the
    # FTS index itself matches in ~0.3s and the rowid join costs ~4s.
    sources = {
        str(sha): (isin, symbol, known_at)
        for sha, isin, symbol, known_at in _query(
            dk, "SELECT sha256, isin, symbol, known_at FROM deck_sources")
        if sha
    }
    rows = _query(
        dk,
        "SELECT f.sha256, f.metric, f.raw_number, f.value, f.unit, f.page_no, f.line_no "
        "FROM facts_metric_fts m JOIN facts f ON f.rowid = m.rowid "
        "WHERE facts_metric_fts MATCH ? AND f.value IS NOT NULL LIMIT 100000",
        (_fts_query(keywords),),
    )
    out = []
    for sha, metric, raw_number, value, unit, page, line in rows:
        isin, symbol, known_at = sources.get(str(sha), ("", "", ""))
        if not isin:
            continue
        metric_low = str(metric or "").lower()
        # Revenue-mix / segment metrics only: a bank's "sector exposure" table is
        # not the company's own segment, even though it names the theme.
        if any(w in metric_low for w in ("exposure", "sectoral", "portfolio", "advances")):
            continue
        if not any(w in metric_low for w in ("segment", "revenue", "sales", "mix", "turnover")):
            continue
        theme = next((t for t, cfg in themes.items() if _hit(metric, cfg.get("keywords") or [])), "")
        if not theme:
            continue
        unit = str(unit or "")
        weight = _pct_weight(metric, unit, value)
        symbols.setdefault(str(isin), str(symbol or ""))
        out.append({
            "theme": theme, "isin": str(isin), "method": "segment",
            "valid_from": _date(known_at), "weight": round(min(weight, 1.0), 6),
            "evidence_id": f"deck_figures.db:facts:{sha}:{page}:{line}",
            "evidence_quote": f"{str(metric)[:120]}: {raw_number} {unit}".strip(),
            "pivot": False,
        })
    return out


def _subsidiary_evidence(ann: sqlite3.Connection | None, themes: dict[str, Any],
                         sym_isin: dict[str, str], code_isin: dict[str, str]) -> list[dict[str, Any]]:
    rows = _query(
        ann,
        "SELECT NEWSID, SCRIP_CD, symbol, HEADLINE, NEWSSUB, NEWS_DT FROM ann WHERE "
        "lower(HEADLINE) LIKE '%subsidiar%' OR lower(HEADLINE) LIKE '%acquisition%' "
        "OR lower(HEADLINE) LIKE '%joint venture%' OR lower(HEADLINE) LIKE '%amalgamation%' "
        "OR lower(NEWSSUB) LIKE '%subsidiar%' OR lower(NEWSSUB) LIKE '%acquisition%' "
        "OR lower(NEWSSUB) LIKE '%joint venture%'",
    )
    out = []
    for newsid, scrip, symbol, headline, newssub, news_dt in rows:
        text = f"{headline} {newssub}"
        theme = next((t for t, cfg in themes.items() if _hit(text, cfg.get("keywords") or [])), "")
        if not theme:
            continue
        isin = sym_isin.get(str(symbol or "").upper()) or code_isin.get(str(scrip or ""))
        if not isin:
            continue
        out.append({
            "theme": theme, "isin": isin, "method": "subsidiary",
            "valid_from": _date(news_dt), "weight": 0.0,
            "evidence_id": f"bse_announcements.db:ann:{newsid}",
            "evidence_quote": str(headline or newssub)[:180], "pivot": False,
        })
    return out


def _pivot_evidence(cc: sqlite3.Connection | None, themes: dict[str, Any]) -> list[dict[str, Any]]:
    keywords = [kw for cfg in themes.values() for kw in (cfg.get("keywords") or [])]
    if not keywords:
        return []
    rows = _query(
        cc,
        "SELECT c.doc_id, c.idx, c.isin, c.filed_at, c.metric, c.statement, c.quote "
        "FROM cc_items_fts f JOIN cc_items c ON c.rowid = f.rowid "
        "WHERE cc_items_fts MATCH ? LIMIT 20000",
        (_fts_query(keywords),),
    )
    out = []
    for doc, idx, isin, filed_at, metric, statement, quote in rows:
        text = f"{metric} {statement} {quote}"
        theme = next((t for t, cfg in themes.items() if _hit(text, cfg.get("keywords") or [])), "")
        if not theme or not isin or not _hit(text, list(ENTRY_WORDS)):
            continue
        out.append({
            "theme": theme, "isin": str(isin), "method": "stated_pivot",
            "valid_from": _date(filed_at), "weight": 0.0,
            "evidence_id": f"concall_facts.db:cc_items:{doc}:{idx}",
            "evidence_quote": str(quote or statement or metric)[:180], "pivot": False,
        })
    return out


def _industry_evidence(eq: sqlite3.Connection | None, themes: dict[str, Any],
                       symbols: dict[str, str]) -> list[dict[str, Any]]:
    rows = _query(
        eq, "SELECT isin, symbol, sector, industry, basic_industry, fetched_at FROM company_industry"
    )
    out = []
    for isin, symbol, sector, industry, basic, fetched_at in rows:
        theme = next(
            (t for t, cfg in themes.items()
             if any(_norm(w) in (_norm(industry), _norm(basic)) for w in (cfg.get("industries") or []))),
            "",
        )
        if not theme or not isin:
            continue
        symbols.setdefault(str(isin), str(symbol or ""))
        out.append({
            "theme": theme, "isin": str(isin), "method": "industry",
            "valid_from": _date(fetched_at) or "2000-01-01", "weight": 0.0,
            "evidence_id": f"equity_intelligence.db:company_industry:{isin}",
            "evidence_quote": f"NSE industry: {sector} / {industry} / {basic}".strip(" /"),
            "pivot": False,
        })
    return out


def _curated_evidence(themes: dict[str, Any], sym_isin: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for theme, cfg in themes.items():
        for seed in cfg.get("seeds") or []:
            symbol = str(seed.get("symbol") or "").upper()
            isin = sym_isin.get(symbol) or str(seed.get("isin") or "")
            if not symbol or not isin:
                continue
            out.append({
                "theme": theme, "isin": isin, "method": "curated",
                "valid_from": _date(seed.get("since")) or "2000-01-01",
                "weight": float(seed.get("weight") or 0.0),
                "evidence_id": f"universes.yaml:{theme}.seeds.{symbol}",
                "evidence_quote": str(seed.get("reason") or ""), "pivot": False,
            })
    return out


# ---------------------------------------------------------------------------
# Rebuild + diff
# ---------------------------------------------------------------------------
def _company_maps(eq: sqlite3.Connection | None):
    sym_isin, code_isin, symbols = {}, {}, {}
    for isin, nse, bse, name in _query(
        eq, "SELECT isin, nse_symbol, bse_code, company_name FROM master_companies"
    ):
        isin = str(isin or "")
        if not isin:
            continue
        for key in (nse, name):
            if key:
                sym_isin.setdefault(str(key).upper(), isin)
        if bse:
            code_isin.setdefault(str(bse), isin)
        if nse and isin not in symbols:
            symbols[isin] = str(nse)
    return sym_isin, code_isin, symbols


def build(data_root: Path, themes_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    themes = load_themes(themes_path)
    eq_source = _open(data_root / "equity_intelligence.db")
    sym_isin, code_isin, symbols = _company_maps(eq_source)
    for isin, symbol, sector, industry, basic, fetched in _query(
        eq_source, "SELECT isin, symbol, sector, industry, basic_industry, fetched_at FROM company_industry"
    ):
        if isin and isin not in symbols and symbol:
            symbols[str(isin)] = str(symbol)
        if symbol:
            sym_isin.setdefault(str(symbol).upper(), str(isin))

    xb = _open(data_root / "results_xbrl.db")
    ar = _open(data_root / "ar_facts.db")
    dk = _open(data_root / "deck_figures.db")
    ann = _open(data_root / "bse_announcements.db")
    cc = _open(data_root / "concall_facts.db")
    try:
        points = xbrl_points(xb, themes, symbols)
        evidence = (_ar_evidence(ar, themes, symbols)
                    + _deck_evidence(dk, themes, symbols)
                    + _subsidiary_evidence(ann, themes, sym_isin, code_isin)
                    + _pivot_evidence(cc, themes)
                    + _industry_evidence(eq_source, themes, symbols)
                    + _curated_evidence(themes, sym_isin))
    finally:
        for con in (eq_source, xb, ar, dk, ann, cc):
            if con is not None:
                con.close()

    rows: list[dict[str, Any]] = []
    covered: set[tuple[str, str]] = set()
    for (isin, theme), pts in points.items():
        intervals = segment_intervals(pts)
        if not intervals:
            continue
        covered.add((theme, isin))
        for interval in intervals:
            rows.append({"theme": theme, "isin": isin, "symbol": symbols.get(isin, ""),
                         "method": "segment", **interval})

    # One row per (theme, ISIN) for non-segment signals: strongest method wins,
    # earliest date of that method becomes the join date.
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for item in evidence:
        key = (item["theme"], item["isin"])
        if key in covered:
            continue
        cur = best.get(key)
        if (cur is None or METHOD_RANK[item["method"]] > METHOD_RANK[cur["method"]]
                or (METHOD_RANK[item["method"]] == METHOD_RANK[cur["method"]]
                    and item["valid_from"] < cur["valid_from"])):
            best[key] = item
    for item in best.values():
        rows.append({"theme": item["theme"], "isin": item["isin"],
                     "symbol": symbols.get(item["isin"], ""),
                     "method": item["method"], "valid_from": item["valid_from"],
                     "valid_to": None, "weight": item["weight"],
                     "evidence_id": item["evidence_id"],
                     "evidence_quote": item["evidence_quote"], "pivot": item["pivot"]})

    rows.sort(key=lambda r: (r["theme"], -float(r["weight"] or 0),
                             -METHOD_RANK.get(r["method"], 0), r["isin"], r["valid_from"]))
    return rows, list(themes)


def _existing(con: sqlite3.Connection) -> dict[tuple[str, str], tuple]:
    try:
        return {(str(r[0]), str(r[1])): tuple(r) for r in con.execute(
            "SELECT theme, isin, valid_from, valid_to, weight, method, pivot FROM universe_membership")}
    except sqlite3.DatabaseError:
        return {}


def _open_ended(valid_to: Any) -> bool:
    return valid_to in (None, "")


def write(con: sqlite3.Connection, rows: list[dict[str, Any]], built_at: str) -> dict[str, Any]:
    old = _existing(con)
    new = {(r["theme"], r["isin"]): r for r in rows}
    joins = sorted(k for k in new if k not in old)
    exits = sorted(k for k in old if k not in new
                   or (_open_ended(old[k][3]) and not _open_ended(new[k].get("valid_to"))))
    pivots = sorted(k for k, r in new.items()
                    if r["pivot"] and not (len(old.get(k, ())) > 6 and old[k][6]))
    run_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    con.executescript(
        "CREATE TABLE IF NOT EXISTS universe_membership("
        " theme TEXT NOT NULL, isin TEXT NOT NULL, symbol TEXT, valid_from TEXT NOT NULL,"
        " valid_to TEXT, weight REAL, method TEXT, evidence_id TEXT, evidence_quote TEXT,"
        " pivot INTEGER DEFAULT 0, built_at TEXT NOT NULL,"
        " PRIMARY KEY(theme, isin, valid_from));"
        "CREATE INDEX IF NOT EXISTS ix_universe_membership_theme"
        " ON universe_membership(theme, valid_from, valid_to);"
        "CREATE TABLE IF NOT EXISTS universe_membership_runs("
        " run_id TEXT PRIMARY KEY, built_at TEXT NOT NULL, joins TEXT NOT NULL,"
        " exits TEXT NOT NULL, pivots TEXT NOT NULL, report_json TEXT NOT NULL);"
    )
    with con:
        con.execute("DELETE FROM universe_membership")
        con.executemany(
            "INSERT INTO universe_membership(theme, isin, symbol, valid_from, valid_to, weight,"
            " method, evidence_id, evidence_quote, pivot, built_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(r["theme"], r["isin"], r.get("symbol") or "", r["valid_from"], r.get("valid_to"),
              float(r.get("weight") or 0.0), r["method"], r.get("evidence_id") or "",
              r.get("evidence_quote") or "", 1 if r.get("pivot") else 0, built_at) for r in rows],
        )
        report = {"built_at": built_at, "members": len(rows), "themes": {},
                  "joins": len(joins), "exits": len(exits), "pivots": len(pivots)}
        for r in rows:
            report["themes"].setdefault(r["theme"], []).append(
                {"symbol": r.get("symbol"), "isin": r["isin"], "weight": r.get("weight"),
                 "method": r["method"], "since": r["valid_from"], "until": r.get("valid_to"),
                 "evidence_id": r.get("evidence_id"), "evidence_quote": r.get("evidence_quote"),
                 "pivot": bool(r.get("pivot"))})
        con.execute(
            "INSERT INTO universe_membership_runs(run_id, built_at, joins, exits, pivots, report_json)"
            " VALUES (?,?,?,?,?,?)",
            (run_id, built_at, json.dumps(joins), json.dumps(exits),
             json.dumps(pivots), json.dumps(report)),
        )
    return {"run_id": run_id, "members": len(rows), "joins": len(joins),
            "exits": len(exits), "pivots": len(pivots), "themes": report["themes"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", help="target equity_intelligence.db (default: <data-root>/equity_intelligence.db)")
    parser.add_argument("--data-root", default=os.environ.get("REALITY_DATA_ROOT"),
                        help="source data directory (default: REALITY_DATA_ROOT)")
    parser.add_argument("--themes", default=str(DEFAULT_THEMES))
    parser.add_argument("--dry-run", action="store_true", help="print the result, write nothing")
    args = parser.parse_args(argv)

    data_root = Path(args.data_root or ROOT / "reality_engine" / "data")
    target = Path(args.db or data_root / "equity_intelligence.db")
    rows, theme_names = build(data_root, Path(args.themes))
    built_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    report = {"run_id": None, "built_at": built_at, "members": len(rows), "themes": {},
              "joins": 0, "exits": 0, "pivots": 0, "dry_run": bool(args.dry_run),
              "target": str(target), "theme_count": len(theme_names)}
    for r in rows:
        report["themes"].setdefault(r["theme"], []).append(
            {"symbol": r.get("symbol"), "isin": r["isin"], "weight": r.get("weight"),
             "method": r["method"], "since": r["valid_from"], "until": r.get("valid_to"),
             "evidence_id": r.get("evidence_id"), "evidence_quote": r.get("evidence_quote"),
             "pivot": bool(r.get("pivot"))})
    for members in report["themes"].values():
        members.sort(key=lambda m: (-(m["weight"] or 0), m["symbol"] or ""))
        del members[40:]

    if args.dry_run:
        print(json.dumps(report, indent=1, default=str))
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target, timeout=300)
    try:
        written = write(con, rows, built_at)
    finally:
        con.close()
    report.update({k: written[k] for k in ("run_id", "members", "joins", "exits", "pivots")})
    print(json.dumps({k: v for k, v in report.items() if k != "themes"}, default=str))
    print("members per theme:", {t: len(v) for t, v in written["themes"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
