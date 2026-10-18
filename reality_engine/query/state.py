"""One query entry point (PIPELINE_TODO Q4, first version 2026-10-19): everything known about a company at time t.

    from reality_engine.query.state import state
    s = state("INE511C01022", "2026-08-01 09:15")      # naive time = IST; or a tz-aware datetime
    s["results"], s["guidance"], s["prices"], ...      # lists of dicts; s["_meta"] = snapshot, t_utc, counts

Reads the newest dated DuckDB snapshot (data/snapshots/truth_<date>.duckdb, Q2) unless `snapshot=` is given, and
returns only rows public before t (known_at_utc < t_utc). Prices: a day's bar counts as known at 18:00 IST that day
(bhavcopy publication), never earlier. Identity: the ISIN's issuer (first 7 characters = entity_id) joins the price
history across splits; NSE symbols and BSE codes come from symbol_isin_history, so renamed / re-ISINed lines are found.

Sections: identity, prices (last `price_days` bars), results (results_key, last 8 quarters x standalone/consolidated),
guidance (concall items of the latest calls with checks + computed direction), orders (Telegram order alerts +
schedule), deck_kpis (latest deck), ar_facts (latest AR filed before t), announcements (BSE), insider, sast, deals,
pead (Telegram PEAD posts), policy (events naming the company; sector mapping is Phase A3).

Raw metrics only: the metric ontology (Phase C) will give cross-source names. search(text, isin, t) comes with the
EmbeddingGemma index (reembed_gemma.py).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import duckdb

SNAP_DIR = Path(__file__).resolve().parents[1] / "data" / "snapshots"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
_CON: dict[str, duckdb.DuckDBPyConnection] = {}


def latest_snapshot() -> Path:
    snaps = sorted(SNAP_DIR.glob("truth_????-??-??.duckdb"))
    if not snaps:
        raise FileNotFoundError(f"no snapshot in {SNAP_DIR}: run build_truth_snapshot")
    return snaps[-1]


def _con(path: Path) -> duckdb.DuckDBPyConnection:
    key = str(path)
    if key not in _CON:
        _CON[key] = duckdb.connect(key, read_only=True)
    return _CON[key]


def to_utc(t) -> dt.datetime:
    """str / date / datetime -> naive UTC datetime. Naive input is IST; a bare date means end of that day IST."""
    if isinstance(t, str):
        t = t.strip().replace("T", " ")
        t = dt.datetime.fromisoformat(t + " 23:59:59") if len(t) <= 10 else dt.datetime.fromisoformat(t)
    elif isinstance(t, dt.date) and not isinstance(t, dt.datetime):
        t = dt.datetime.combine(t, dt.time(23, 59, 59))
    if t.tzinfo is None:
        t = t.replace(tzinfo=IST)
    return t.astimezone(dt.timezone.utc).replace(tzinfo=None)


def _rows(con, sql, params) -> list[dict[str, Any]]:
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def state(isin: str, t, snapshot: Path | None = None, price_days: int = 260, max_rows: int = 500) -> dict[str, Any]:
    snap = Path(snapshot) if snapshot else latest_snapshot()
    con = _con(snap)
    tu = to_utc(t)
    ent = isin[:7]
    syms = con.execute("SELECT DISTINCT symbol FROM symbol_isin_history WHERE exchange = 'NSE' AND isin LIKE ? || '%'",
                       [ent]).fetchall()
    codes = con.execute("SELECT DISTINCT symbol FROM symbol_isin_history WHERE exchange = 'BSE' AND isin LIKE ? || '%'",
                        [ent]).fetchall()
    nse_syms = [r[0] for r in syms] or [""]
    bse_codes = [r[0] for r in codes] or [""]
    ent_isins = [r[0] for r in con.execute(
        "SELECT isin FROM security_master WHERE isin LIKE ? || '%' UNION SELECT isin FROM symbol_isin_history "
        "WHERE isin LIKE ? || '%'", [ent, ent]).fetchall()] or [isin]
    out: dict[str, Any] = {}
    out["identity"] = _rows(con, "SELECT * FROM security_master WHERE isin IN (SELECT unnest(?))", [ent_isins])
    out["prices"] = _rows(con, """
        SELECT * FROM (SELECT date, exch, isin, symbol, open, high, low, close, volume, value_inr, delivery_pct,
                              adj_close, tr_close, cum_price_factor
                         FROM px_daily WHERE entity_id = ?
                          AND CAST(date AS TIMESTAMP) + INTERVAL 12 HOUR + INTERVAL 30 MINUTE <= ?
                        ORDER BY date DESC LIMIT ?) ORDER BY date""", [ent, tu, price_days])
    out["results"] = _rows(con, """
        SELECT * FROM results_key WHERE trading_isin IN (SELECT unnest(?)) AND known_at_utc < ?
        QUALIFY dense_rank() OVER (ORDER BY period_end DESC) <= 8
        ORDER BY period_end DESC, consolidated, known_at_utc DESC""", [ent_isins, tu])
    out["guidance"] = _rows(con, """
        SELECT i.*, c.value_in_quote, c.period_in_quote, c.direction_supported, c.speaker_role, c.metric_key,
               c.value_low, c.value_high, c.computed_direction, c.prev_value_mid
          FROM cc_items i LEFT JOIN cc_item_checks c USING (doc_id, list_name, idx)
         WHERE i.isin IN (SELECT unnest(?)) AND i.known_at_utc < ?
        QUALIFY dense_rank() OVER (ORDER BY i.known_at_utc DESC) <= 2
         ORDER BY i.known_at_utc DESC, i.list_name, i.idx LIMIT ?""", [ent_isins, tu, max_rows])
    out["orders"] = _rows(con, """
        SELECT o.*, (SELECT list({'fy': s.fy, 'q': s.q, 'amount_cr': s.amount_cr})
                       FROM tg_order_schedule s WHERE s.order_id = o.order_id) AS schedule
          FROM tg_orders o WHERE o.isin IN (SELECT unnest(?)) AND o.known_at_utc < ?
         ORDER BY o.known_at_utc DESC LIMIT ?""", [ent_isins, tu, max_rows])
    out["deck_kpis"] = _rows(con, """
        SELECT * FROM deck_facts WHERE isin IN (SELECT unnest(?)) AND known_at_utc < ?
        QUALIFY dense_rank() OVER (ORDER BY known_at_utc DESC, sha256) = 1
         ORDER BY page_no, line_no LIMIT ?""", [ent_isins, tu, max_rows])
    out["ar_facts"] = _rows(con, """
        SELECT * EXCLUDE (fact_id) FROM ar_facts WHERE isin IN (SELECT unnest(?)) AND known_at_utc < ?
        QUALIFY dense_rank() OVER (ORDER BY known_at_utc DESC, doc_id DESC) = 1
         ORDER BY category, page LIMIT ?""", [ent_isins, tu, max_rows])
    out["announcements"] = _rows(con, """
        SELECT NEWSID, SCRIP_CD, CATEGORYNAME, SUBCATNAME, HEADLINE, NEWSSUB, ATTACHMENTNAME, known_at_utc
          FROM bse_ann WHERE SCRIP_CD IN (SELECT unnest(?)) AND known_at_utc < ?
         ORDER BY known_at_utc DESC LIMIT 100""", [bse_codes, tu])
    out["insider"] = _rows(con, """
        SELECT * FROM nse_insider WHERE symbol IN (SELECT unnest(?)) AND known_at_utc < ?
         ORDER BY known_at_utc DESC LIMIT 100""", [nse_syms, tu])
    out["sast"] = _rows(con, """
        SELECT * FROM nse_sast WHERE symbol IN (SELECT unnest(?)) AND known_at_utc < ?
         ORDER BY known_at_utc DESC LIMIT 50""", [nse_syms, tu])
    out["deals"] = _rows(con, """
        SELECT 'NSE' exch, date, deal_type, client_name, buy_sell, quantity, price, known_at_utc FROM nse_deals
         WHERE symbol IN (SELECT unnest(?)) AND known_at_utc < ?
        UNION ALL
        SELECT 'BSE', date, deal_type, client_name, buy_sell, quantity, price, known_at_utc FROM bse_deals
         WHERE sc_code IN (SELECT unnest(?)) AND known_at_utc < ?
         ORDER BY known_at_utc DESC LIMIT 100""", [nse_syms, tu, bse_codes, tu])
    out["pead"] = _rows(con, """
        SELECT * FROM tg_pead_signals WHERE isin IN (SELECT unnest(?)) AND known_at_utc < ?
         ORDER BY known_at_utc DESC LIMIT 20""", [ent_isins, tu])
    # company name core ("Poonawalla Fincorp Limited" -> "poonawalla fincorp"), substring match on the companies list
    core = next((r["name"] for r in out["identity"] if r.get("name")), "")
    core = " ".join(w for w in core.lower().replace(".", " ").split() if w not in ("limited", "ltd", "the", "india"))
    out["policy"] = _rows(con, """
        SELECT * FROM policy_events WHERE known_at_utc < ? AND contains(lower(coalesce(companies, '')), ?)
         ORDER BY known_at_utc DESC LIMIT 50""", [tu, core]) if len(core) >= 4 else []
    out["_meta"] = {"isin": isin, "entity_id": ent, "t_utc": tu.isoformat(), "snapshot": snap.name,
                    "nse_symbols": nse_syms, "bse_codes": bse_codes, "isins": ent_isins,
                    "counts": {k: len(v) for k, v in out.items() if isinstance(v, list)},
                    "policy_note": "company-name match only; sector -> company mapping is Phase A3"}
    return out
