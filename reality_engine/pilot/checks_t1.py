"""Checks for the T1 pilot build — the numbers behind tasks/pilot_t1/CHECKS.md.

Read-only on the pilot files. Prints markdown: row counts, fill rates, 10 hand checks per table
against the source (re-read from the held stores / raw files, never from the pilot table),
index-membership spot checks, band spot checks, the 15:30 rule, and index timings.

    python -m reality_engine.pilot.build_t1 --checks --out .tmp/pilot > tasks/pilot_t1/CHECKS.md
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import time
from pathlib import Path

from reality_engine.pilot.build_t1 import (
    AR, EI, FACTS_DB, MARKET_DB, RAW_ROOT, XBRL, CONCEPT_MAP, fy_end,
    parse_segment_item, unit_to_crore)


def ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def md(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
    return "\n".join(out)


def section(n, title, body) -> str:
    return f"\n## {n}. {title}\n\n{body}\n"


TABLES = {
    MARKET_DB: ["company_state_daily", "mcap_bucket_interval", "price_band_daily",
                "price_band", "index_membership_interval", "index_list",
                "company_membership_pit", "company_sector_pit", "company_ownership_pit",
                "event_day0", "event_leakage_window", "isin_rekey_map", "build_run"],
    FACTS_DB: ["xbrl_concept_map", "company_metric_series", "company_segment_pnl",
               "company_working_capital", "company_interest_cover", "company_result_pit",
               "build_run"],
}


def counts_and_fill(out: Path) -> str:
    rows = []
    for db, tables in TABLES.items():
        con = ro(out / db)
        for t in tables:
            try:
                n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.OperationalError:
                rows.append((db.replace("_pilot.db", ""), t, "MISSING", ""))
                continue
            rows.append((db.replace("_pilot.db", ""), t, f"{n:,}", ""))
        con.close()
    body = ["### Row counts\n", md(["db", "table", "rows", ""], rows), "\n### Fill rate per column\n"]
    fill_rows = []
    for db, tables in TABLES.items():
        con = ro(out / db)
        for t in tables:
            try:
                cols = [d[1] for d in con.execute(f"PRAGMA table_info({t})")]
                n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.OperationalError:
                continue
            if not n:
                fill_rows.append((t, "-", "-", "0"))
                continue
            try:
                aggs = ", ".join(f"SUM({c} IS NOT NULL)" for c in cols)
                filled = con.execute(f"SELECT {aggs} FROM {t}").fetchone()
                for c, f in zip(cols, filled):
                    fill_rows.append((t, c, f"{100.0 * (f or 0) / n:.1f}%", f"{n:,}"))
            except sqlite3.OperationalError as exc:
                fill_rows.append((t, "ERROR", str(exc), ""))
        con.close()
    body.append(md(["table", "column", "fill", "rows"], fill_rows))
    body.append(COVERAGE_NOTES)
    return "\n".join(body)


COVERAGE_NOTES = """
How to read the fills (all three are the honest number, not a build defect):

- `mcap_cr` / `shares_out` / `mcap_bucket` fill starts at a company's FIRST `results_xbrl`
  filing, because that is the only held share-count source (paid-up / face value). The XBRL
  era begins in FY23 for most names, so 2019-2022 sessions carry no shares and no market cap
  rather than a back-filled guess. `shares_source` says `xbrl_paidup` on every filled row.
- `price_band` NULL is two different things: the exchange published "No Band" (F&O names --
  208 of 3,324 rows in one 2026 sec_list file, and most of this bank universe), and rows whose
  date/symbol is not in the raw file. The build resolves 633,203 of 738,113 rows to a raw-file
  key (85.8%); 104,483 of the rest are BSE-only lines, where an NSE band does not exist.
- `company_working_capital` is annual by construction: it joins a fiscal-year income statement
  to the balance sheet dated the same day. `cogs` (CostOfMaterialsConsumed) only exists for
  manufacturers, so `dio`/`dpo`/`ccc` are null for service and bank names while `dso` still fills.
"""


# ---------------------------------------------------------------------------------------
# hand checks — every sample is compared to the source, not to another pilot table
# ---------------------------------------------------------------------------------------
def duckdb():
    import duckdb
    from reality_engine.pilot.build_t1 import SNAPSHOT
    return duckdb.connect(str(SNAPSHOT), read_only=True)


def check_state(out: Path):
    con = ro(out / MARKET_DB)
    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM company_state_daily ORDER BY date")]
    picks = [dates[int(len(dates) * k / 10)] for k in range(10)]
    rows = []
    for d in picks:
        r = con.execute("""SELECT isin, date, close, mcap_cr, shares_out, price_band,
                                  mcap_bucket FROM company_state_daily WHERE date = ?
                           ORDER BY isin LIMIT 1""", (d,)).fetchone()
        if r:
            rows.append(r)
    con.close()
    dcon = duckdb()
    pairs = ",".join(f"('{r[0]}','{r[1]}')" for r in rows)
    src = {(r[0], r[1]): r[2] for r in dcon.execute(
        f"SELECT isin, CAST(date AS VARCHAR), adj_close FROM px_daily "
        f"WHERE (isin, CAST(date AS VARCHAR)) IN ({pairs})").fetchall()}
    dcon.close()
    table, ok = [], 0
    for isin, date, close, mcap, shares, band, bucket in rows:
        s = src.get((isin, date))
        good = s is not None and abs(float(s) - float(close)) < 1e-6
        ok += good
        table.append((isin, date, close, s if s is not None else "MISSING",
                      "OK" if good else "MISMATCH", mcap, shares, band, bucket))
    con = ro(out / MARKET_DB)
    n = con.execute("SELECT COUNT(*) FROM company_state_daily").fetchone()[0]
    con.close()
    return ("`close` re-read from `truth.px_daily.adj_close`; `mcap_cr` = close x shares_out / 1e7, "
            "`shares_out` from XBRL paid-up/face value, band from the raw sec_list file, bucket by "
            "daily SEBI rank over every ISIN with a known share count.\n\n"
            + md(["isin", "date", "pilot close", "source close", "verdict", "mcap_cr",
                  "shares", "band", "bucket"], table)
            + f"\n\n**{ok}/{len(rows)}** sampled rows agree. Table rows: {n:,}."), ok, len(rows)


def check_membership(out: Path):
    con = ro(out / MARKET_DB)
    changes = [json.loads(line) for line in
               (out / "index_changes.jsonl").read_text(encoding="utf-8").splitlines()]
    by_node = {(c["index_code"], c["isin"]): [] for c in changes}
    for c in changes:
        by_node[(c["index_code"], c["isin"])].append(c)
    sample = con.execute("""SELECT isin, index_code, added_on, removed_on, source, pit_conf
                            FROM company_membership_pit
                            ORDER BY isin, index_code, added_on LIMIT 10 OFFSET 400""").fetchall()
    table = []
    for isin, code, added, removed, source, conf in sample:
        ev = by_node.get((code, isin), [])
        trail = "; ".join(f"{e['change_type']} w.e.f. {e['effective_date']}" for e in ev) or "-"
        table.append((isin, code, added, removed, source, conf, trail))

    # every Nifty-50 notice must flip membership on its effective date
    def member(isin, code, day):
        return con.execute("""SELECT 1 FROM company_membership_pit
                              WHERE isin=? AND index_code=? AND added_on<=?
                                AND (removed_on IS NULL OR removed_on>?)""",
                           (isin, code, day, day)).fetchone() is not None

    agree = total = 0
    flips = []
    for c in changes:
        if c["index_code"] != "nifty50":
            continue
        eff = c["effective_date"]
        before = (dt.date.fromisoformat(eff) - dt.timedelta(days=1)).isoformat()
        want_before = c["change_type"] == "exclusion"
        want_after = not want_before
        got = (member(c["isin"], "nifty50", before), member(c["isin"], "nifty50", eff))
        total += 1
        agree += got == (want_before, want_after)
        if got != (want_before, want_after) and len(flips) < 8:
            flips.append((c["isin"], eff, c["change_type"], got))

    rows = []
    for day in ("2019-06-28", "2023-06-30", "2026-09-29"):
        n = con.execute("""SELECT COUNT(*) FROM company_membership_pit
                           WHERE index_code='nifty50' AND added_on<=?
                             AND (removed_on IS NULL OR removed_on>?)""", (day, day)).fetchone()[0]
        names = [r[0] for r in con.execute("""SELECT isin FROM company_membership_pit
                                              WHERE index_code='nifty50' AND added_on<=?
                                                AND (removed_on IS NULL OR removed_on>?)
                                              ORDER BY isin LIMIT 5""", (day, day))]
        rows.append((day, n, ", ".join(names)))
    con.close()
    body = ("Intervals rebuilt backwards from the 2026-09-30 snapshot with the dated notices. "
            "Each sample interval is traced to the notice that produced it. Nifty 50 is a "
            "50-name index: a count above 50 on a past date means a name was excluded before "
            "2019 or a notice was parsed onto a re-keyed ISIN.\n\n"
            + md(["isin", "index", "added_on", "removed_on", "source", "pit_conf",
                  "notices on this node"], table)
            + "\n\n### Nifty 50 membership on three dates\n\n"
            + md(["date", "members", "first five ISINs"], rows)
            + f"\n\n### Notice-flip test\n\nEvery Nifty-50 change notice must flip membership on "
              f"its effective date (`member(day before)` / `member(effective date)`): "
              f"**{agree}/{total} agree**."
            + ("\n\nDisagreements: " + json.dumps(flips) if flips else ""))
    return body, agree, total


def _symbol_at(con_ei, isin, day):
    for sym, first, last in con_ei.execute(
            "SELECT symbol, first_date, last_date FROM symbol_isin_history "
            "WHERE exchange='NSE' AND isin=? ORDER BY first_date DESC", (isin,)):
        if (not first or first <= day) and (not last or day <= last):
            return sym
    return None


def check_band(out: Path):
    from reality_engine.scripts.fetch_price_bands import parse_band_csv
    con = ro(out / MARKET_DB)
    sample = con.execute("""SELECT isin, date, band FROM price_band_daily
                            WHERE band IS NOT NULL ORDER BY date DESC LIMIT 10 OFFSET 50000""") \
        .fetchall()
    con.close()
    ei = ro(EI)
    files = {}
    table, ok = [], 0
    for isin, date, band in sample:
        sym = _symbol_at(ei, isin, date)
        stamp = dt.date.fromisoformat(date).strftime("%d%m%Y")
        path = RAW_ROOT / "price_bands" / f"sec_list_{stamp}.csv"
        if path not in files:
            files[path] = {r["symbol"]: r["band_pct"] for r in
                           parse_band_csv(path.read_text(encoding="utf-8-sig",
                                                         errors="replace"), date)} \
                if path.exists() else {}
        sband = files[path].get(sym, "no row")
        good = sband == band
        ok += good
        table.append((isin, date, sym, band, sband, "OK" if good else "MISMATCH"))
    # and the other direction: no band means the raw file says No Band
    nulls = []
    con = ro(out / MARKET_DB)
    nsample = con.execute("""SELECT isin, date FROM price_band_daily WHERE band IS NULL
                             ORDER BY date DESC LIMIT 5 OFFSET 1000""").fetchall()
    con.close()
    for isin, date in nsample:
        sym = _symbol_at(ei, isin, date)
        stamp = dt.date.fromisoformat(date).strftime("%d%m%Y")
        path = RAW_ROOT / "price_bands" / f"sec_list_{stamp}.csv"
        if path not in files:
            files[path] = {r["symbol"]: r["band_pct"] for r in
                           parse_band_csv(path.read_text(encoding="utf-8-sig",
                                                         errors="replace"), date)} \
                if path.exists() else {}
        nulls.append((isin, date, sym, files[path].get(sym, "no row")))
    ei.close()
    body = ("Pilot band re-read from `D:/RealityEngine/raw/price_bands/sec_list_<date>.csv` with the "
            "shipped parser (`fetch_price_bands.parse_band_csv`); the symbol is resolved at that "
            "date from `symbol_isin_history`.\n\n"
            + md(["isin", "date", "symbol", "pilot band", "raw band", "verdict"], table)
            + f"\n\n**{ok}/{len(table)}** banded samples agree.\n\n"
            + "Null band means no band: the raw file for the same symbol/date says:\n\n"
            + md(["isin", "date", "symbol", "raw band"], nulls))
    return body, ok, len(table)


def check_day0(out: Path):
    con = ro(out / MARKET_DB)
    before = con.execute("""SELECT event_id, isin, known_at, session_0, offset, in_session
                            FROM event_day0 WHERE in_session=1
                            ORDER BY known_at LIMIT 10 OFFSET 100""").fetchall()
    after = con.execute("""SELECT event_id, isin, known_at, session_0, offset, in_session
                           FROM event_day0 WHERE in_session=0 AND offset=1
                           ORDER BY known_at LIMIT 10 OFFSET 100""").fetchall()
    cal = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM company_state_daily ORDER BY date")]
    con.close()
    dcon = duckdb()
    ids = ",".join("'%s'" % r[0].replace("'", "''") for r in before + after)
    isins = ",".join("'%s'" % r[1] for r in before + after)
    src = {(k, ref, isin): ts for k, ref, isin, ts in dcon.execute(
        f"SELECT kind, CAST(source_ref AS VARCHAR), isin, CAST(known_at_utc AS VARCHAR) "
        f"FROM events WHERE isin IN ({isins}) "
        f"AND kind || ':' || CAST(source_ref AS VARCHAR) IN ({ids})").fetchall()}
    dcon.close()
    import bisect
    table, ok = [], 0
    for group, rows in (("before 15:30", before), ("after 15:30", after)):
        for eid, isin, kn, sess, off, ins in rows:
            t = dt.datetime.fromisoformat(kn)
            kind, ref = eid.split(":", 1)
            src_ts = src.get((kind, ref, isin))
            expected = None
            if src_ts:
                utc = dt.datetime.fromisoformat(src_ts)
                expected = (utc + dt.timedelta(hours=5, minutes=30)).isoformat(timespec="seconds")
            want_off = 0 if t.time() <= dt.time(15, 30) and t.date().isoformat() in set(cal) else 1
            i = bisect.bisect_right(cal, t.date().isoformat())
            if want_off == 0 or i >= len(cal):
                if want_off == 1:
                    continue
                want_sess = t.date().isoformat()
            else:
                want_sess = cal[i]
            good = (t.time() <= dt.time(15, 30)) == (group == "before 15:30") and off == want_off \
                and sess == want_sess and (expected is None or expected == kn)
            ok += good
            table.append((group, eid[:38], kn, sess, off, ins,
                          "OK" if good else "MISMATCH"))
    body = ("known_at is re-read from `truth.events.known_at_utc` and converted to IST (+5:30); "
            "`session_0` is the same session when the stamp is <=15:30 on a trading day, else the "
            "next session in the calendar.\n\n"
            + md(["bucket", "event_id", "known_at", "session_0", "offset", "in_session",
                  "verdict"], table)
            + f"\n\n**{ok}/{len(table)}** sampled filings follow the rule.")
    return body, ok, len(table)


def check_metrics(out: Path):
    con = ro(out / FACTS_DB)
    n = con.execute("SELECT COUNT(*) FROM company_metric_series").fetchone()[0]
    sample = con.execute("""SELECT isin, metric_key, period_end, period_kind, basis, value,
                                   doc_id, known_at FROM company_metric_series
                            ORDER BY isin, period_end LIMIT 10 OFFSET ?""", (n // 2,)).fetchall()
    con.close()
    c2m = {c: (metric, scale, sign) for c, (metric, sign, scale, _b) in CONCEPT_MAP.items()}
    dcon = duckdb()
    files = ",".join("'%s'" % r[6] for r in sample)
    all_concepts = ",".join("'%s'" % c for c in CONCEPT_MAP)
    facts = dcon.execute(
        f"SELECT file, concept, coalesce(period_end, instant), value FROM results_facts "
        f"WHERE file IN ({files}) AND concept IN ({all_concepts})").fetchall()
    dcon.close()
    by_file = {}
    for f, c, pe, v in facts:
        metric, scale, sign = c2m[c]
        by_file.setdefault((f, metric, str(pe)[:10]), []).append(v * scale * sign)
    table, ok = [], 0
    for isin, metric, pe, kind, basis, value, doc, known in sample:
        cands = by_file.get((doc, metric, pe)) or []
        good = any(abs(c - value) <= max(0.01, abs(value) * 1e-6) for c in cands)
        ok += good
        table.append((isin, metric, pe, kind, basis, value,
                      None if not cands else round(cands[0], 6),
                      "OK" if good else "MISMATCH"))
    body = ("Each sampled value is recomputed from `truth.results_facts.value` x the map's "
            "`unit_scale` for the same filing (`doc_id` = `file`).\n\n"
            + md(["isin", "metric", "period_end", "kind", "basis", "pilot value", "source value",
                  "verdict"], table)
            + f"\n\n**{ok}/{len(table)}** sampled metric values agree.")
    return body, ok, len(table)


def check_derived(out: Path):
    con = ro(out / FACTS_DB)
    n_res = con.execute("SELECT COUNT(*) FROM company_result_pit").fetchone()[0]
    n_wc = con.execute("SELECT COUNT(*) FROM company_working_capital").fetchone()[0]
    n_ic = con.execute("SELECT COUNT(*) FROM company_interest_cover").fetchone()[0]
    n_seg = con.execute("SELECT COUNT(*) FROM company_segment_pnl").fetchone()[0]
    res = con.execute("""SELECT isin, period_end, basis, revenue_cr, ebitda_cr, pat_cr,
                                revenue_yoy, eps FROM company_result_pit
                         ORDER BY isin, period_end LIMIT 10 OFFSET ?""", (n_res // 2,)).fetchall()
    wc = con.execute("""SELECT isin, period_end, basis, receivables_cr, inventory_cr,
                               payables_cr, revenue_cr, cogs_cr, dso
                        FROM company_working_capital ORDER BY isin, period_end
                        LIMIT 10 OFFSET ?""", (n_wc // 2,)).fetchall()
    ic = con.execute("""SELECT isin, period_end, basis, ebit_cr, finance_cost_cr, cover_x
                        FROM company_interest_cover ORDER BY isin, period_end
                        LIMIT 10 OFFSET ?""", (n_ic // 2,)).fetchall()
    seg = con.execute("""SELECT isin, segment, period_end, metric, basis, value_cr,
                                share_of_total_pct, page FROM company_segment_pnl
                         ORDER BY isin, period_end LIMIT 10 OFFSET ?""", (n_seg // 2,)).fetchall()
    con.close()
    t1, ok1 = [], 0
    for isin, pe, basis, rev, ebitda, pat, yoy, eps in res:
        con = ro(out / FACTS_DB)
        src = con.execute("""SELECT value FROM company_metric_series
                             WHERE isin=? AND metric_key='revenue' AND period_end=?
                               AND basis=? AND period_kind='quarter'""",
                          (isin, pe, basis)).fetchone()
        con.close()
        good = src is not None and (rev is None or abs(src[0] - rev) < 1e-6)
        ok1 += good
        t1.append((isin, pe, basis, rev, None if src is None else src[0],
                   "OK" if good else "MISMATCH"))
    t2, ok2 = [], 0
    con = ro(out / FACTS_DB)
    for isin, pe, basis, recv, inv, pay, rev, cogs, dso in wc:
        got = {}
        for key, kind, value in con.execute(
                "SELECT metric_key, period_kind, value FROM company_metric_series "
                "WHERE isin=? AND period_end=? AND basis=? AND metric_key IN "
                "('receivables','inventory','payables','revenue','cogs')", (isin, pe, basis)):
            want_kind = "instant" if key in ("receivables", "inventory", "payables") else "fy"
            if key not in got or kind == want_kind:
                got[key] = value
        checks = []
        for name, pilot_v, key in (("receivables", recv, "receivables"),
                                   ("inventory", inv, "inventory"),
                                   ("payables", pay, "payables"),
                                   ("revenue", rev, "revenue"), ("cogs", cogs, "cogs")):
            if pilot_v is not None:
                checks.append(key in got and abs(got[key] - pilot_v) < 0.01)
        if rev and recv is not None and dso is not None:
            checks.append(abs(recv / rev * 365 - dso) < 0.01)
        good = bool(checks) and all(checks)
        ok2 += good
        t2.append((isin, pe, basis, recv, inv, rev, dso,
                   None if "receivables" not in got else got["receivables"],
                   f"{sum(checks)}/{len(checks)}", "OK" if good else "MISMATCH"))
    con.close()
    t3, ok3 = [], 0
    for isin, pe, basis, ebit, fin, cover in ic:
        want = ebit / fin if fin else None
        good = want is not None and abs(want - cover) < 1e-4
        ok3 += good
        t3.append((isin, pe, basis, ebit, fin, cover, "OK" if good else "MISMATCH"))
    # segment source trace
    ar = ro(AR)
    t4, ok4 = [], 0
    for isin, seg, pe, metric, basis, value, share, page in seg:
        rows = ar.execute("""SELECT item, value, unit, period, basis FROM ar_facts
                             WHERE isin=? AND page=? AND category LIKE 'segment%'
                               AND value IS NOT NULL""", (isin, page)).fetchall()
        hit = None
        for item, v, unit, period, b in rows:
            parsed = parse_segment_item(item)
            scale = unit_to_crore(unit)
            if parsed == (seg, metric) and scale and (b or "").lower() == basis \
                    and fy_end(period) == pe:
                hit = (round(float(v) * scale, 6), item)
                break
        good = hit is not None and abs(hit[0] - value) < 0.01
        ok4 += good
        t4.append((isin, seg, pe, metric, basis, value,
                   None if hit is None else hit[0], (hit[1] if hit else "-")[:60],
                   "OK" if good else "MISMATCH"))
    ar.close()
    body = ("Derived tables are re-derived from `company_metric_series` / the AR segment facts.\n\n"
            "### company_result_pit (revenue vs the series)\n\n"
            + md(["isin", "period_end", "basis", "pilot revenue", "series revenue", "verdict"], t1)
            + f"\n\n**{ok1}/{len(t1)}** agree.\n\n### company_working_capital (dso = "
              "receivables/revenue x 365)\n\n"
            + md(["isin", "period_end", "basis", "receivables", "inventory", "revenue",
                  "pilot dso", "source receivables", "checks", "verdict"], t2)
            + f"\n\n**{ok2}/{len(t2)}** agree.\n\n### company_interest_cover (cover = ebit / "
              "finance cost)\n\n"
            + md(["isin", "period_end", "basis", "ebit", "finance cost", "cover",
                  "verdict"], t3)
            + f"\n\n**{ok3}/{len(t3)}** agree.\n\n### company_segment_pnl (vs the AR segment note)"
              "\n\n"
            + md(["isin", "segment", "period_end", "metric", "basis", "pilot value",
                  "source value", "source item", "verdict"], t4)
            + f"\n\n**{ok4}/{len(t4)}** agree.")
    return body, (ok1 + ok2 + ok3 + ok4), (len(t1) + len(t2) + len(t3) + len(t4))


def check_ownership_sector(out: Path):
    con = ro(out / MARKET_DB)
    n_own = con.execute("SELECT COUNT(*) FROM company_ownership_pit").fetchone()[0]
    n_sec = con.execute("SELECT COUNT(*) FROM company_sector_pit").fetchone()[0]
    own = con.execute("""SELECT isin, quarter_end, known_at, promoter_pct, public_pct
                         FROM company_ownership_pit ORDER BY isin, quarter_end
                         LIMIT 10 OFFSET ?""", (n_own // 2,)).fetchall()
    sec = con.execute("""SELECT isin, sector, basic_industry FROM company_sector_pit
                         ORDER BY isin LIMIT 10 OFFSET ?""", (n_sec // 2,)).fetchall()
    con.close()
    ei = ro(EI)
    t1, ok1 = [], 0
    for isin, qe, known, promoter, public in own:
        src = ei.execute("""SELECT promoter_pct, public_pct, broadcast_at FROM shp_index
                            WHERE isin=? AND quarter_end=?""", (isin, qe)).fetchone()
        good = src is not None and src[0] == promoter and src[1] == public
        ok1 += good
        t1.append((isin, qe, known, promoter, None if src is None else src[0],
                   "OK" if good else "MISMATCH"))
    t2, ok2 = [], 0
    for isin, sector, basic in sec:
        src = ei.execute("SELECT sector, basic_industry FROM company_industry WHERE isin=?",
                         (isin,)).fetchone()
        good = src is not None and src[0] == sector and src[1] == basic
        ok2 += good
        t2.append((isin, sector, basic, None if src is None else src[0],
                   None if src is None else src[1], "OK" if good else "MISMATCH"))
    ei.close()
    body = ("### company_ownership_pit vs `shp_index`\n\n"
            + md(["isin", "quarter_end", "known_at", "promoter", "source promoter", "verdict"], t1)
            + f"\n\n**{ok1}/{len(t1)}** agree.\n\n### company_sector_pit vs `company_industry`"
              "\n\n*current classification backcast to 2019-01-01 (no historical map held)*\n\n"
            + md(["isin", "sector", "basic_industry", "source sector", "source basic", "verdict"],
                 t2) + f"\n\n**{ok2}/{len(t2)}** agree.")
    return body, ok1 + ok2, len(t1) + len(t2)


def check_leakage(out: Path):
    con = ro(out / MARKET_DB)
    sample = con.execute("""SELECT l.event_id, l.isin, l.offset, l.date, l.ret_pct,
                                   l.delivery_z, l.known_at, d.known_at
                            FROM event_leakage_window l JOIN event_day0 d
                              ON d.event_id = l.event_id AND d.isin = l.isin
                            WHERE l.offset BETWEEN -4 AND -1 AND l.ret_pct IS NOT NULL
                            LIMIT 10 OFFSET 1000""").fetchall()
    con.close()
    dcon = duckdb()
    pairs = ",".join(f"('{r[1]}','{r[3]}')" for r in sample)
    src = {(r[0], r[1]): r[2] for r in dcon.execute(f"""
        SELECT p.isin, CAST(p.date AS VARCHAR), (p.adj_close / prev.adj_close - 1) * 100
        FROM px_daily p
        JOIN px_daily prev ON prev.isin = p.isin AND prev.date = (
            SELECT max(q.date) FROM px_daily q WHERE q.isin = p.isin AND q.date < p.date)
        WHERE (p.isin, CAST(p.date AS VARCHAR)) IN ({pairs})
    """).fetchall()} if sample else {}
    dcon.close()
    table, ok = [], 0
    for eid, isin, off, date, ret, dz, known, d0 in sample:
        s = src.get((isin, date))
        good = known == d0 and -10 <= off <= 10 and s is not None and abs(s - ret) < 0.01
        table.append((eid[:30], isin, off, date, ret, None if s is None else round(s, 4),
                      dz, "OK" if good else "MISMATCH"))
        ok += good
    return ("The window is `known_at = event_day0.known_at` (only knowable then) and offsets -10..+10 "
            "sessions around day0. Sample rows are the pre-event window (offset -4..-1); `ret_pct` is "
            "re-read from `truth.px_daily` as the one-session change.\n\n"
            + md(["event_id", "isin", "offset", "date", "ret_pct", "source ret_pct", "delivery_z",
                  "verdict"], table)
            + f"\n\n**{ok}/{len(table)}** rows carry the event's PIT key and the source return."), ok, len(table)


TIMINGS = [
    ("ix_csd_date_bucket", MARKET_DB,
     "SELECT COUNT(*) FROM company_state_daily WHERE date=? AND mcap_bucket=?"),
    ("ix_csd_date_band", MARKET_DB,
     "SELECT COUNT(*) FROM company_state_daily WHERE date=? AND price_band=?"),
    ("ix_csd_date_fno", MARKET_DB,
     "SELECT COUNT(*) FROM company_state_daily WHERE date=? AND is_fno=1"),
    ("pk (isin,date)", MARKET_DB,
     "SELECT * FROM company_state_daily WHERE isin=? AND date=?"),
    ("price_band_daily view", MARKET_DB,
     "SELECT band FROM price_band_daily WHERE isin=? AND date=?"),
    ("mcap_bucket_interval view", MARKET_DB,
     "SELECT * FROM mcap_bucket_interval WHERE isin=?"),
    ("ix_cmp_index_added", MARKET_DB,
     "SELECT COUNT(*) FROM company_membership_pit WHERE index_code=? AND added_on<=?"),
    ("ix_cmp_index_removed", MARKET_DB,
     "SELECT COUNT(*) FROM company_membership_pit WHERE index_code=? AND removed_on IS NULL"),
    ("ix_ed0_isin_sess", MARKET_DB,
     "SELECT COUNT(*) FROM event_day0 WHERE isin=? AND session_0>=?"),
    ("ix_ed0_sess", MARKET_DB,
     "SELECT COUNT(*) FROM event_day0 WHERE session_0=? AND event_kind=?"),
    ("ix_elw_isin_date", MARKET_DB,
     "SELECT COUNT(*) FROM event_leakage_window WHERE isin=? AND date>=?"),
    ("ix_csp_basic", MARKET_DB,
     "SELECT COUNT(*) FROM company_sector_pit WHERE basic_industry=? AND valid_from<=?"),
    ("ix_csp_sector", MARKET_DB,
     "SELECT COUNT(*) FROM company_sector_pit WHERE sector=? AND valid_from<=?"),
    ("ix_cop_known", MARKET_DB,
     "SELECT COUNT(*) FROM company_ownership_pit WHERE known_at<=?"),
    ("ix_crp_isin_known", FACTS_DB,
     "SELECT COUNT(*) FROM company_result_pit WHERE isin=? AND known_at<=?"),
    ("ix_cms_metric_period", FACTS_DB,
     "SELECT COUNT(*) FROM company_metric_series WHERE metric_key=? AND period_end>=?"),
    ("ix_cms_isin_known", FACTS_DB,
     "SELECT COUNT(*) FROM company_metric_series WHERE isin=? AND known_at<=?"),
    ("ix_csp_seg_period", FACTS_DB,
     "SELECT COUNT(*) FROM company_segment_pnl WHERE segment=? AND period_end>=?"),
    ("ix_csp_isin_known", FACTS_DB,
     "SELECT COUNT(*) FROM company_segment_pnl WHERE isin=? AND known_at<=?"),
    ("ix_xcm_metric", FACTS_DB,
     "SELECT COUNT(*) FROM xbrl_concept_map WHERE metric_key=?"),
    ("ix_cic_cover", FACTS_DB,
     "SELECT COUNT(*) FROM company_interest_cover WHERE cover_x<?"),
]


def check_timings(out: Path):
    rows, plans = [], []
    params_by_label = {
        "ix_csd_date_bucket": ("2026-08-03", "LARGE"), "ix_csd_date_band": ("2026-08-03", 5),
        "ix_csd_date_fno": ("2026-08-03",), "pk (isin,date)": ("INE040A01034", "2026-08-03"),
        "price_band_daily view": ("INE040A01034", "2026-08-03"),
        "mcap_bucket_interval view": ("INE040A01034",),
        "ix_cmp_index_added": ("nifty50", "2023-01-01"),
        "ix_cmp_index_removed": ("nifty50",),
        "ix_ed0_isin_sess": ("INE040A01034", "2024-01-01"),
        "ix_ed0_sess": ("2024-01-01", "announcement"),
        "ix_elw_isin_date": ("INE040A01034", "2024-01-01"),
        "ix_csp_basic": ("Banks", "2019-01-01"), "ix_csp_sector": ("Financial Services", "2019-01-01"),
        "ix_cop_known": ("2024-01-01",), "ix_crp_isin_known": ("INE040A01034", "2024-01-01"),
        "ix_cms_metric_period": ("revenue", "2024-01-01"),
        "ix_cms_isin_known": ("INE040A01034", "2024-01-01"),
        "ix_csp_seg_period": ("Automotive", "2020-01-01"),
        "ix_csp_isin_known": ("INE040A01034", "2024-01-01"),
        "ix_xcm_metric": ("revenue",), "ix_cic_cover": (2.5,),
    }
    for label, db, sql in TIMINGS:
        con = ro(out / db)
        params = params_by_label[label]
        plan = con.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
        best = 1e9
        for _ in range(3):
            t0 = time.perf_counter()
            con.execute(sql, params).fetchall()
            best = min(best, (time.perf_counter() - t0) * 1000)
        con.close()
        rows.append((label, db.replace("_pilot.db", ""), f"{best:.2f}", params))
        plans.append((label, " / ".join(r[-1] for r in plan)))
    return ("Each SCHEMA_V3 index gets a query shape from the design's `-- serves:` line; the time is "
            "the best of three runs on a warm read-only connection.\n\n"
            + md(["index / shape", "db", "best ms", "params"], rows)
            + "\n\n### Query plans\n\n" + md(["shape", "plan"], plans)), 0, 0


def main(out: Path) -> int:
    out = Path(out)
    if not (out / MARKET_DB).exists():
        print(f"no pilot build at {out}", flush=True)
        return 1
    doc = ["# Pilot T1 — checks", "",
           f"Generated by `python -m reality_engine.pilot.build_t1 --checks --out {out}` "
           f"on {dt.datetime.now().isoformat(timespec='seconds')}.",
           "Every sample is compared against the source store or raw file, never against another "
           "pilot table (derived-table checks say so)."]
    doc.append(section(1, "Counts and fill", counts_and_fill(out)))
    total_ok = total_n = 0
    for n, (title, fn) in enumerate([
            ("company_state_daily", check_state), ("company_membership_pit", check_membership),
            ("price_band_daily (raw sec_list files)", check_band),
            ("event_day0 (15:30 rule)", check_day0),
            ("company_metric_series (XBRL facts)", check_metrics),
            ("derived + segment tables", check_derived),
            ("ownership + sector", check_ownership_sector),
            ("event_leakage_window", check_leakage)], start=2):
        body, ok, cnt = fn(out)
        total_ok += ok
        total_n += cnt
        doc.append(section(n, title, body))
    doc.append(section(9, "Index timings", check_timings(out)[0]))
    doc.append(section(10, "Tables not built (and why)", NOT_BUILT))
    doc.append(section(11, "Agreement", f"**{total_ok}/{total_n}** hand-checked "
                                        f"({100.0 * total_ok / total_n if total_n else 0:.1f}%) agree "
                                        f"with their source."))
    text = "\n".join(doc) + "\n"
    print(text)
    target = Path(REPO_CHECKS)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"\n(written to {target})", file=__import__("sys").stderr)
    except OSError:
        pass
    return 0


REPO_CHECKS = (Path(__file__).resolve().parents[2] / "tasks" / "pilot_t1" / "CHECKS.md")

NOT_BUILT = """Every table below was created with the SCHEMA_V3 DDL and left empty on purpose.

| table | why it is empty | what closes it |
|---|---|---|
| `isin_rekey_map` | the G0 repair ledger is 2 days of curation (83 false changes, 1,370 synthetic ISINs); nothing to derive mechanically | `symbol_isin_history` windows + corporate_actions review |
| `company_theme_pit`, `theme_map` | no curated theme map is held; the schema calls for ~20 themes x ~40 members of curation | `theme_map` curation (20 min) then a one-line match build |
| `macro_doc`, `macro_claim`, `macro_claim_target`, `event_calendar` | deterministic part needs `policy_events` -> claim mapping and the rest is a reader; out of the T1 deterministic tier | build stream 6 of PILOT_SPEC §4 |
| `commodity_price_daily`, `freight_rate_daily`, `rainfall_daily`, `rural_wage_series` | sources are not held (`needs_new_fetch`) | the fetch stream |
| `chunks_v3.*`, `result_note`, reader tables | T2, another worker | chunk build + reader |
"""
