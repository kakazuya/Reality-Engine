"""Independent H02 verification: different queries and arithmetic paths.

python -m reality_engine.harness.verify_h02

Reads only the authorized snapshot, the completed H02 artifacts and the
append-only ledger.  Never writes to the snapshot or the ledger.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
import random

import numpy as np
import pandas as pd

from .data import ROOT, Snapshot, as_date
from .stats import bh_fdr

OUT = ROOT / "tasks/backtests"


def normalize(text):
    import re
    s = str(text or "").upper()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def query_days(con):
    rows = con.execute("""
        SELECT DISTINCT cast(date AS DATE) FROM index_tri
        WHERE index_name='NIFTY 50' AND cast(date AS DATE) BETWEEN '2019-01-01' AND '2025-12-31'
          AND dayofweek(cast(date AS DATE)) BETWEEN 1 AND 5
        ORDER BY 1""").fetchall()
    return np.array([r[0] for r in rows], dtype="datetime64[D]")


def query_tax(con, rule, day):
    row = con.execute("""
        SELECT value FROM tax_rules WHERE rule=?
          AND cast(effective_from AS DATE)<=cast(? AS DATE)
          AND (effective_to IS NULL OR cast(effective_to AS DATE)>=cast(? AS DATE))""",
                      [rule, str(day), str(day)]).fetchone()
    if row is None:
        raise ValueError(f"missing tax rule {rule} at {day}")
    return float(row[0])


def independent_dedupe(rows):
    """Small-sample one-for-one dedupe; deliberately separate implementation."""
    rows = [dict(r) for r in rows]
    for r in rows:
        r["client_n"] = normalize(r["client_name"])
        r["side"] = str(r["buy_sell"]).strip().upper()
        r["qty"] = round(float(r["quantity"]), 4)
        r["px"] = round(float(r["price"]), 4)
    # Cross-exchange: pair each BSE row with an unmatched NSE row.
    used_nse = set()
    drop = set()
    for i, b in enumerate(rows):
        if b["exch"] != "BSE":
            continue
        for j, n in enumerate(rows):
            if j in used_nse or n["exch"] != "NSE":
                continue
            if all(b[k] == n[k] for k in ("date", "client_n", "side", "qty", "px", "issuer")):
                used_nse.add(j)
                drop.add(i)
                break
    left = [r for i, r in enumerate(rows) if i not in drop]
    # BULK/BLOCK: pair each BLOCK row with an unmatched BULK row on the same exchange.
    used_bulk = set()
    drop2 = set()
    for i, b in enumerate(left):
        if b["deal_type"] != "BLOCK":
            continue
        for j, n in enumerate(left):
            if j in used_bulk or n["deal_type"] != "BULK" or n["exch"] != b["exch"]:
                continue
            if all(b[k] == n[k] for k in ("date", "client_n", "side", "qty", "px", "issuer")):
                used_bulk.add(j)
                drop2.add(i)
                break
    return [r for i, r in enumerate(left) if i not in drop2]


def insider_names(con, issuer):
    rows = con.execute("""
        SELECT DISTINCT lower(trim(ni.acquirer_name)) FROM nse_insider ni
        JOIN symbol_isin_history h ON h.exchange='NSE' AND h.symbol=ni.symbol
          AND substr(ni.disseminated_at,1,10) BETWEEN h.first_date AND h.last_date
        JOIN security_master sm ON sm.isin=h.isin
        WHERE sm.issuer=? AND ni.acquirer_name IS NOT NULL
        UNION
        SELECT DISTINCT lower(trim(json_extract_string(bi.raw_json,
          '$."Name(s) of the promoter and/or persons in promoter group"')))
        FROM bse_insider bi JOIN security_master sm ON sm.isin=bi.isin
        WHERE sm.issuer=?""", [issuer, issuer]).fetchall()
    return {normalize(r[0]) for r in rows if r[0]}


def raw_event_deals(con, issuer, day):
    nse = con.execute("""
        SELECT d.date,d.deal_type,d.symbol,d.client_name,d.buy_sell,
               d.quantity::DOUBLE quantity,d.price::DOUBLE price,'NSE' exch,sm.issuer
        FROM nse_deals d
        JOIN symbol_isin_history h ON h.exchange='NSE' AND h.symbol=d.symbol
          AND d.date BETWEEN h.first_date AND h.last_date
        JOIN security_master sm ON sm.isin=h.isin
        WHERE d.date=? AND sm.issuer=?""", [str(day), issuer]).df()
    bse = con.execute("""
        WITH bse_map AS (
          SELECT bse_code, min(isin) AS isin, min(issuer) AS issuer
          FROM security_master WHERE bse_code IS NOT NULL
          GROUP BY bse_code HAVING count(DISTINCT issuer)=1
        )
        SELECT d.date,d.deal_type,d.sc_code symbol,d.client_name,d.buy_sell,
               d.quantity::DOUBLE quantity,d.price::DOUBLE price,'BSE' exch,m.issuer
        FROM bse_deals d JOIN bse_map m ON m.bse_code=d.sc_code
        WHERE d.date=? AND m.issuer=?""", [str(day), issuer]).df()
    return pd.concat([nse, bse], ignore_index=True).to_dict("records")


def independent_event(con, issuer, day, definition, m2_names, m1_pattern, m1_exclude):
    import re
    deals = independent_dedupe(raw_event_deals(con, issuer, day))
    insiders = insider_names(con, issuer)
    pattern = re.compile(m1_pattern, re.I)
    exclude = re.compile(m1_exclude, re.I)
    kept = []
    for row in deals:
        client = row["client_n"]
        if client in insiders or "PROMOTER" in client:
            continue
        if definition == "M1":
            if not (pattern.search(client) and not exclude.search(client)):
                continue
        elif definition == "M2":
            if client not in m2_names:
                continue
        else:
            raise ValueError(definition)
        kept.append(row)
    buy = sum(r["qty"] * r["px"] for r in kept if r["side"] == "BUY")
    sell = sum(r["qty"] * r["px"] for r in kept if r["side"] == "SELL")
    buy_qty = sum(r["qty"] for r in kept if r["side"] == "BUY")
    return {"buy_value": buy, "sell_value": sell, "net_value": buy - sell,
            "buy_vwap": buy / buy_qty if buy_qty else None,
            "rows": len(kept)}


def independent_b5(con, entry, exit_day, choices, days):
    """Recompute B5 event return, including the documented previous-close proxy.

    B5Path enters at the previous session's TRI close: its first daily factor
    is tri[entry]/tri[entry-1].  Each index switch realizes the old segment at
    the session before the switch and starts the new segment from that same
    previous close.  Reproducing that convention is the point of this check.
    """
    chosen = {date.fromisoformat(str(r["month"])[:10]): r["index"] for r in choices}
    entry_i = int(np.searchsorted(days, np.datetime64(entry)))
    if entry_i < 1 or days[entry_i] != np.datetime64(entry):
        raise ValueError("entry not on the normal-session calendar")
    sessions = [d for d in days if np.datetime64(entry) <= d <= np.datetime64(exit_day)]
    if not sessions or sessions[-1] != np.datetime64(exit_day):
        raise ValueError("exit not on the normal-session calendar")
    segments = []
    prev_start = days[entry_i - 1]
    current = None
    for i, day in enumerate(sessions):
        day_date = date.fromisoformat(str(day))
        name = chosen.get(day_date.replace(day=1))
        if name is None:
            raise ValueError(f"no B5 choice for {day}")
        if current is None:
            current = name
        elif name != current:
            segments.append((prev_start, sessions[i - 1], current))
            prev_start, current = sessions[i - 1], name
    segments.append((prev_start, sessions[-1], current))
    value = 1.0
    for start_day, end_day, name in segments:
        row_start = con.execute("SELECT tri FROM index_tri WHERE upper(index_name)=upper(?) AND cast(date AS DATE)=?",
                                [name, str(start_day)]).fetchone()
        row_end = con.execute("SELECT tri FROM index_tri WHERE upper(index_name)=upper(?) AND cast(date AS DATE)=?",
                              [name, str(end_day)]).fetchone()
        if not row_start or not row_end:
            raise ValueError(f"missing TRI {name} {start_day} {end_day}")
        gross = float(row_end[0]) / float(row_start[0]) - 1
        rate = query_tax(con, "stcg_rate", end_day)
        value *= 1 + (gross - 0.003 - max(gross, 0.0) * rate)
    return value - 1


def replay_fills(fills, panel_conn):
    """Replay one variant's fills in execution order with FIFO; return cash."""
    lots = {}
    cash = 1_000_000.0
    failures = []
    for f in fills:
        isin, side, qty, price = f["isin"], f["side"], float(f["qty"]), float(f["price"])
        notional = qty * price
        if side == "buy":
            expected_fee = notional * 0.003 / 2
            if abs(float(f["fee"]) - expected_fee) > max(1e-6, 1e-8 * notional):
                failures.append({"fill": str(f), "issue": "fee"})
            cash -= notional + float(f["fee"])
            lots.setdefault(isin, []).append([qty, price, f["date"]])
        else:
            remaining = qty
            basis = 0.0
            gains = []
            while remaining > 1e-9 and lots.get(isin):
                lot = lots[isin][0]
                take = min(remaining, lot[0])
                basis += take * lot[1]
                gains.append({"gain": take * price - take * lot[1],
                              "holding_days": (as_date(f["date"]) - as_date(lot[2])).days})
                lot[0] -= take
                remaining -= take
                if lot[0] <= 1e-9:
                    lots[isin].pop(0)
            expected_fee = basis * 0.003 / 2
            if abs(float(f["fee"]) - expected_fee) > max(1e-6, 1e-8 * max(basis, 1.0)):
                failures.append({"fill": str(f), "issue": "fee"})
            st = sum(g["gain"] for g in gains if g["holding_days"] <= 365)
            lt = sum(g["gain"] for g in gains if g["holding_days"] > 365)
            rate_st = query_tax(panel_conn, "stcg_rate", f["date"])
            rate_lt = query_tax(panel_conn, "ltcg_rate", f["date"])
            tax = max(0.0, st) * rate_st + max(0.0, lt) * rate_lt
            if abs(tax - float(f["tax"])) > 1e-4:
                failures.append({"fill": str(f), "issue": "tax", "expected": tax,
                                 "actual": f["tax"]})
            cash += notional - float(f["fee"]) - float(f["tax"])
    return cash, failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(OUT / "H02_results.json"))
    parser.add_argument("--events", default=str(OUT / "H02_events.csv.gz"))
    parser.add_argument("--fills", default=str(OUT / "H02_book_fills.csv.gz"))
    parser.add_argument("--sample", type=int, default=30)
    args = parser.parse_args(argv)
    results_path = Path(args.results)
    events_path = Path(args.events)
    fills_path = Path(args.fills)
    results = json.loads(results_path.read_text(encoding="utf-8"))
    events = pd.read_csv(events_path)
    fills = pd.read_csv(fills_path) if fills_path.exists() else pd.DataFrame()
    checks, failures = [], []

    def check(name, passed, detail=None):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        if not passed:
            failures.append({"check": name, "detail": detail})

    with Snapshot() as snapshot:
        before = snapshot.path.stat()
        con = snapshot.connection
        days = query_days(con)
        m2_names = {r["client_n"] for r in results["m2_list"]}
        rng = random.Random(20261022)
        sample = events.sample(min(args.sample, len(events)), random_state=20261022)
        deal_failures = []
        for _, row in sample.iterrows():
            recomputed = independent_event(con, row["issuer"], row["event_date"],
                                           row["definition"], m2_names,
                                           results["m1_pattern"], results["m1_exclude"])
            if abs(recomputed["net_value"] - row["net_value_inr"]) > 1.0:
                deal_failures.append({"row": row.to_dict(), "recomputed": recomputed})
        check("sample_net_values", not deal_failures, deal_failures[:3])

        price_failures = []
        net_failures = []
        b5_failures = []
        for _, row in sample.iterrows():
            date_value = np.datetime64(row["event_date"])
            entry_index = int(np.searchsorted(days, date_value, side="right"))
            if entry_index >= len(days):
                price_failures.append({"row": row["event_date"], "issue": "no entry"})
                continue
            expected_entry = days[entry_index]
            entry = np.datetime64(row["entry"])
            exit_day = np.datetime64(row["exit"])
            if entry != expected_entry:
                price_failures.append({"row": row["event_date"], "issue": "entry",
                                       "expected": str(expected_entry), "actual": str(entry)})
            close = con.execute("""
                SELECT tr_close FROM px_daily WHERE entity_id=? AND cast(date AS DATE)=?""",
                                [row["issuer"], str(exit_day)]).fetchone()
            adj_open = con.execute("""
                SELECT adj_open*cum_div_factor FROM px_daily WHERE entity_id=? AND cast(date AS DATE)=?""",
                                   [row["issuer"], str(entry)]).fetchone()
            if not close or not adj_open:
                price_failures.append({"row": row["event_date"], "issue": "missing price"})
                continue
            gross = float(close[0]) / float(adj_open[0]) - 1
            rate = query_tax(con, "stcg_rate", exit_day)
            net = gross - 0.003 - max(gross, 0.0) * rate
            if abs(gross - row["gross_return"]) > 1e-6:
                price_failures.append({"row": row["event_date"], "expected": gross,
                                       "actual": row["gross_return"]})
            if abs(net - row["stock_net"]) > 1e-6:
                net_failures.append({"row": row["event_date"], "expected": net,
                                     "actual": row["stock_net"]})
            if row["exit"] == row["scheduled_exit"]:
                try:
                    b5 = independent_b5(con, entry, exit_day,
                                        results["benchmark_choices"], days)
                    if abs(b5 - row["b5_net"]) > 1e-6:
                        b5_failures.append({"row": row["event_date"], "expected": b5,
                                            "actual": row["b5_net"]})
                except Exception as exc:
                    b5_failures.append({"row": row["event_date"], "error": str(exc)})
        check("sample_entry_exit_prices", not price_failures, price_failures[:3])
        check("sample_tax_and_net", not net_failures, net_failures[:3])
        check("sample_b5", not b5_failures, b5_failures[:3])

        # Event-set means and BH q.
        mean_failures = []
        for variant in results["variants"]:
            definition, horizon = variant["params"]["definition"], variant["params"]["horizon"]
            subset = events[(events.definition == definition) & (events.horizon == horizon)]
            if abs(float(subset["net_excess"].mean()) - variant["mean_net_excess"]) > 1e-9:
                mean_failures.append({"variant": [definition, horizon]})
        check("event_means", not mean_failures, mean_failures[:3])

        import duckdb
        with duckdb.connect(str(ROOT / "reality_engine/data/backtests/ledger.duckdb"),
                            read_only=True) as ledger:
            allowed = set(results["fdr_scope"]["prior_run_ids"])
            prior = [p for rid, p in ledger.execute(
                "SELECT run_id,p FROM variants ORDER BY run_timestamp,row_id").fetchall()
                if rid in allowed]
        qs = bh_fdr(prior + [v["p"] for v in results["variants"]])[-len(results["variants"]):]
        q_failures = [{"variant": v["params"], "expected": q, "actual": v["bh_q"]}
                      for v, q in zip(results["variants"], qs)
                      if abs(q - v["bh_q"]) > 1e-12]
        check("bh_q_recomputation", not q_failures, q_failures[:3])

        # Full FIFO replay of one book, and price/fee checks on sampled fills.
        fill_failures = []
        if len(fills):
            variant = fills["variant"].iloc[0]
            subset = fills[fills.variant == variant]
            cash, replay_failures = replay_fills(subset.to_dict("records"), con)
            book = results["books"][variant]
            if not book.get("unresolved_holdings") and abs(cash - book["final_allocation_inr"]) > max(1e-4, 1e-9 * abs(cash)):
                fill_failures.append({"variant": variant, "cash": cash,
                                      "book_final": book["final_allocation_inr"]})
            fill_failures.extend(replay_failures[:3])
            sampled_fills = fills.sample(min(20, len(fills)), random_state=7)
            for _, f in sampled_fills.iterrows():
                if f["side"] == "buy" or f["reason"] != "scheduled_exit":
                    field = "adj_open*cum_div_factor"
                else:
                    field = "tr_close"
                row = con.execute(f"SELECT {field} FROM px_daily WHERE entity_id=? AND cast(date AS DATE)=?",
                                  [f["isin"], str(f["date"])]).fetchone()
                if not row or abs(float(row[0]) - float(f["price"])) > 1e-9:
                    fill_failures.append({"fill": f.to_dict(), "issue": "price"})
        check("book_fill_replay_and_prices", not fill_failures, fill_failures[:3])

        # Snapshot and pre-registration integrity.
        after = snapshot.path.stat()
        check("snapshot_size_mtime_unchanged",
              (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
              {"before": [before.st_size, before.st_mtime_ns],
               "after": [after.st_size, after.st_mtime_ns]})
        prereg = OUT / "H02_preregistration.md"
        check("pre_registration_hash",
              prereg.exists() and hashlib.sha256(prereg.read_bytes()).hexdigest()
              == results["pre_registration_sha256"],
              str(prereg))

    report = {"card_id": "H02", "verified_at_utc": datetime.now(timezone.utc).isoformat(),
              "results_file": str(results_path), "events_file": str(events_path),
              "fills_file": str(fills_path), "checks": checks,
              "passed": len(checks) - len(failures), "failed": len(failures),
              "failures": failures, "sample_size": len(sample)}
    (OUT / "H02_verification.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "failed": report["failed"],
                      "failures": failures[:5]}, indent=1))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
