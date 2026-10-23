"""Independent Stage 2 verification of the declared C1-C6 combination.

python -m reality_engine.harness.verify_h01xh02

Uses the official H01 long-outcome artifact, independent deal-event queries
via load_deals (sample-checked separately by verify_h02), independently
rebuilt confirmation/entry/exit arithmetic, and a FIFO replay of saved book
fills.  Never writes to the snapshot or ledger.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import random

import numpy as np
import pandas as pd

from .cards.h02_combine import cluster_diff, tercile_labels, zscore
from .cards.h02_deals import M1_EXCLUDE, M1_PATTERN, load_deals, pit_indices
from .data import ROOT, Snapshot, as_date
from .stats import bh_fdr, student_p
from .verify_h02 import independent_b5, independent_event, query_days, query_tax

OUT = ROOT / "tasks/backtests"
WINDOW = (-20, 5)


def load_prices(con, entities):
    marks = ",".join("?" * len(entities))
    frame = con.execute(f"""
        SELECT entity_id, cast(date AS DATE) AS day,
               adj_open*cum_div_factor AS tr_open, tr_close
        FROM px_daily WHERE entity_id IN ({marks})
          AND cast(date AS DATE) BETWEEN '2019-01-01' AND '2025-12-31'
    """, list(entities)).df()
    frame["day"] = pd.to_datetime(frame["day"]).dt.date
    frame = frame.drop_duplicates(["entity_id", "day"], keep="first")
    return frame.set_index(["entity_id", "day"]).sort_index()


def load_tri(con):
    rows = con.execute("""
        SELECT upper(index_name), cast(date AS DATE), tri FROM index_tri
        WHERE cast(date AS DATE) BETWEEN '2019-01-01' AND '2025-12-31'
    """).fetchall()
    return {(name, day): float(tri) for name, day, tri in rows}


def b5_return(entry, exit_day, days, tri, choices, tax_cache):
    chosen = {date.fromisoformat(str(r["month"])[:10]): r["index"] for r in choices}
    entry_i = int(np.searchsorted(days, np.datetime64(entry)))
    if entry_i < 1 or days[entry_i] != np.datetime64(entry):
        raise ValueError("entry not on calendar")
    sessions = [d for d in days if np.datetime64(entry) <= d <= np.datetime64(exit_day)]
    if not sessions or sessions[-1] != np.datetime64(exit_day):
        raise ValueError("exit not on calendar")
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
        a = tri[(name.upper(), as_date(start_day))]
        b = tri[(name.upper(), as_date(end_day))]
        gross = b / a - 1
        key = (end_day,)
        if key not in tax_cache:
            tax_cache[key] = query_tax_cache(end_day)
        value *= 1 + (gross - .003 - max(gross, 0.) * tax_cache[key])
    return value - 1


def query_tax_cache(day):
    # rates are constant within the evidence window after 23-Jul-2024
    return .20 if as_date(day) >= date(2024, 7, 23) else .15


def compute_returns(entries, entities, horizon, days, prices, tri, choices, tax_cache):
    rows = []
    for entry, entity in zip(entries, entities):
        entry = int(entry)
        if entry + horizon >= len(days):
            continue
        exit_day = days[entry + horizon]
        entry_day = days[entry]
        try:
            p0 = float(prices.loc[(entity, as_date(entry_day)), "tr_open"])
            p1 = float(prices.loc[(entity, as_date(exit_day)), "tr_close"])
        except KeyError:
            continue
        if not (np.isfinite(p0) and np.isfinite(p1) and p0 > 0):
            continue
        gross = p1 / p0 - 1
        rate = query_tax_cache(exit_day)
        net = gross - .003 - max(gross, 0.) * rate
        try:
            b5 = b5_return(entry_day, exit_day, days, tri, choices, tax_cache)
        except (KeyError, ValueError):
            continue
        rows.append({"entry_index": entry, "entity": entity, "exit_index": entry + horizon,
                     "entry": entry_day, "exit": exit_day, "gross": gross, "net": net,
                     "b5": b5, "excess": net - b5})
    return pd.DataFrame(rows)


def confirm(h01, deals):
    by = {}
    for i, entity in enumerate(deals["issuer"]):
        by.setdefault(entity, []).append(i)
    for entity in by:
        ids = np.asarray(by[entity], dtype=int)
        order = np.argsort(deals["signal"][ids], kind="mergesort")
        by[entity] = ids[order]
    chosen = np.full(len(h01["entity"]), -1, dtype=int)
    combined = np.asarray(h01["h01_entry"], dtype=int).copy()
    for i, (entity, signal, entry) in enumerate(zip(h01["entity"], h01["h01_signal"],
                                                    h01["h01_entry"])):
        ids = by.get(entity)
        if ids is None:
            continue
        sig = deals["signal"][ids]
        lo = int(np.searchsorted(sig, signal + WINDOW[0], side="left"))
        hi = int(np.searchsorted(sig, signal + WINDOW[1], side="right"))
        if lo >= hi:
            continue
        cand = ids[lo:hi]
        # latest t+1 open, then largest net
        best = sorted(cand.tolist(),
                      key=lambda j: (-int(deals["entry"][j]), -float(deals["net"][j])))[0]
        chosen[i] = best
        combined[i] = max(int(entry), int(deals["entry"][best]))
    return chosen, combined


def replay_fills(fills, con):
    lots, cash, failures = {}, 1_000_000.0, []
    for f in fills:
        isin, side = f["isin"], f["side"]
        qty, price = float(f["qty"]), float(f["price"])
        if side == "buy":
            cash -= qty * price + float(f["fee"])
            lots.setdefault(isin, []).append([qty, price, f["date"]])
        else:
            remaining, basis, gains = qty, 0.0, []
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
            tax = sum(max(0., g["gain"]) * (query_tax_cache(f["date"]))
                      for g in gains)
            if abs(tax - float(f["tax"])) > 1e-4:
                failures.append({"fill": str(f), "issue": "tax"})
            cash += qty * price - float(f["fee"]) - float(f["tax"])
    return cash, failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(OUT / "H01xH02_results.json"))
    parser.add_argument("--fills", default=str(OUT / "H01xH02_book_fills.csv.gz"))
    parser.add_argument("--sample", type=int, default=30)
    args = parser.parse_args(argv)
    results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    fills = pd.read_csv(args.fills) if Path(args.fills).exists() else pd.DataFrame()
    checks, failures = [], []

    def check(name, passed, detail=None):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        if not passed:
            failures.append({"check": name, "detail": detail})

    with Snapshot() as snapshot:
        before = snapshot.path.stat()
        con = snapshot.connection
        days = query_days(con)
        tri = load_tri(con)
        choices = results["benchmark_choices"]
        tax_cache = {}

        h01_out = pd.read_csv(OUT / "H01_long_outcomes.csv.gz")
        h01_out = h01_out[(h01_out.entry_timing == "both_known_next_open")
                          & (h01_out.horizon == 180)
                          & (h01_out.PAT_surprise > 0)].copy()
        h01_out["h01_signal"] = [
            int(np.searchsorted(days, np.datetime64(str(t)[:10]), side="right") - 1)
            for t in h01_out.decision_trigger]
        h01_out["h01_entry"] = [int(np.searchsorted(days, np.datetime64(str(d)[:10])))
                                for d in h01_out.entry]
        h01 = {"entity": h01_out.entity.astype(str).to_numpy(),
               "h01_signal": h01_out.h01_signal.to_numpy(dtype=int),
               "h01_entry": h01_out.h01_entry.to_numpy(dtype=int),
               "net_excess": h01_out.net_excess.to_numpy(dtype=float)}
        check("h01_lead_count", len(h01_out) == results["h01_lead_audit"]["n_events"],
              {"found": len(h01_out), "recorded": results["h01_lead_audit"]["n_events"]})

        data = load_deals(snapshot.path)
        deals = {}
        for definition in ("M1", "M2"):
            frame = data.events(definition)
            dates = np.array(frame["date"], dtype="datetime64[D]")
            signal, entry = pit_indices(days, dates)
            deals[definition] = {"issuer": frame["issuer"].astype(str).to_numpy(),
                                 "signal": signal, "entry": entry,
                                 "net": frame["net_value"].to_numpy(dtype=float),
                                 "frame": frame}

        prices = load_prices(con, sorted(set(h01["entity"]) | set(data.clean["issuer"])))
        c1_chosen, c1_combined = confirm(h01, deals["M1"])
        c2_chosen, c2_combined = confirm(h01, deals["M2"])

        # Map return rows back to H01 indices for C5/C3.
        def returns_with_ids(chosen, combined, horizon):
            mask = chosen >= 0
            h01_ids = np.flatnonzero(mask)
            entries = combined[mask]
            entities = h01["entity"][mask]
            frame = compute_returns(entries, entities, horizon, days, prices,
                                    tri, choices, tax_cache)
            if len(frame):
                valid_map = {}
                for h, (entry, entity) in zip(h01_ids, zip(entries, entities)):
                    valid_map[(int(entry), str(entity))] = int(h)
                frame["h01_index"] = [
                    valid_map[(int(r.entry_index), str(r.entity))] for r in frame.itertuples()]
            else:
                frame["h01_index"] = []
            return frame, mask

        c1_frame, c1_mask = returns_with_ids(c1_chosen, c1_combined, 180)
        c2_frame, c2_mask = returns_with_ids(c2_chosen, c2_combined, 180)
        c6_frame, _ = returns_with_ids(c1_chosen, c1_combined, 60)

        c3_confirmed = c1_frame
        unconfirmed_ids = np.flatnonzero(~c1_mask)
        unconfirmed = pd.DataFrame({"excess": h01["net_excess"][unconfirmed_ids],
                                    "entry_index": h01["h01_entry"][unconfirmed_ids]})
        diff = cluster_diff(c3_confirmed["excess"].to_numpy(),
                            c3_confirmed["entry_index"].to_numpy(),
                            unconfirmed["excess"].to_numpy(),
                            unconfirmed["entry_index"].to_numpy(),
                            days, student_p)

        # C5 fixed 0.5/0.5 score on M1-confirmed events.
        c5 = c1_frame.copy()
        if len(c5):
            c5["deal_net"] = [deals["M1"]["net"][c1_chosen[int(i)]]
                              for i in c5["h01_index"]]
            c5["pat"] = h01_out.PAT_surprise.to_numpy()[c5["h01_index"].to_numpy(dtype=int)]
            score = .5 * zscore(c5["pat"]) + .5 * zscore(np.log(np.maximum(c5["deal_net"], 1.0)))
            labels = tercile_labels(score)
            top, bottom = labels == 2, labels == 0
            c5_diff = cluster_diff(c5["excess"].to_numpy()[top],
                                   c5["entry_index"].to_numpy()[top],
                                   c5["excess"].to_numpy()[bottom],
                                   c5["entry_index"].to_numpy()[bottom],
                                   days, student_p)
        else:
            c5_diff = {"diff": None, "p": 1.0, "n_a": 0, "n_b": 0}

        recorded = {r["params"]["combination"]: r for r in results["combinations"]}
        for name, frame, key in (("C1", c1_frame, "mean_net_excess"),
                                 ("C2", c2_frame, "mean_net_excess"),
                                 ("C6", c6_frame, "mean_net_excess")):
            recomputed = float(frame["excess"].mean()) if len(frame) else None
            check(f"{name}_mean", recomputed is not None
                  and abs(recomputed - recorded[name][key]) < 1e-6,
                  {"recomputed": recomputed, "recorded": recorded[name][key],
                   "n": len(frame), "recorded_n": recorded[name]["n_events"]})
        check("C3_diff", abs(diff["diff"] - recorded["C3"]["mean_net_excess"]) < 1e-6,
              {"recomputed": diff["diff"], "recorded": recorded["C3"]["mean_net_excess"],
               "n_confirmed": len(c1_frame), "n_unconfirmed": len(unconfirmed)})
        check("C5_diff", (c5_diff["diff"] is None and recorded["C5"]["mean_net_excess"] is None)
              or abs(c5_diff["diff"] - recorded["C5"]["mean_net_excess"]) < 1e-6,
              {"recomputed": c5_diff["diff"], "recorded": recorded["C5"]["mean_net_excess"]})

        # Sample deal-event recomputation, independent SQL path.
        sample = c1_frame.sample(min(args.sample, len(c1_frame)), random_state=11) if len(c1_frame) else pd.DataFrame()
        deal_failures = []
        for _, row in sample.iterrows():
            h = h01_out.iloc[int(row["h01_index"])]
            day = str(h.decision_trigger)[:10]
            # Find the chosen deal date from the M1 event list.
            chosen = int(c1_chosen[int(row["h01_index"])])
            deal_day = deals["M1"]["frame"].iloc[chosen]["date"]
            recomputed = independent_event(con, str(h.entity), deal_day, "M1",
                                           set(), M1_PATTERN, M1_EXCLUDE)
            expected = float(deals["M1"]["frame"].iloc[chosen]["net_value"])
            if abs(recomputed["net_value"] - expected) > 1.0:
                deal_failures.append({"entity": str(h.entity), "day": deal_day,
                                      "recomputed": recomputed["net_value"],
                                      "expected": expected})
        check("sample_deal_net_values", not deal_failures, deal_failures[:3])

        # Full FIFO replay of one saved book.
        fill_failures = []
        if len(fills):
            book_name = "union" if "union" in set(fills["book"]) else fills["book"].iloc[0]
            subset = fills[fills.book == book_name]
            cash, replay_failures = replay_fills(subset.to_dict("records"), con)
            book = results["books"][book_name]
            if not book.get("unresolved_holdings"):
                if abs(cash - book["final_allocation_inr"]) > max(1e-4, 1e-9 * abs(cash)):
                    fill_failures.append({"book": book_name, "cash": cash,
                                          "final": book["final_allocation_inr"]})
            fill_failures.extend(replay_failures[:3])
        check("book_fill_replay", not fill_failures, fill_failures[:3])

        # BH recomputation.
        import duckdb
        with duckdb.connect(str(ROOT / "reality_engine/data/backtests/ledger.duckdb"),
                            read_only=True) as ledger:
            prior = [p for rid, p in ledger.execute(
                "SELECT run_id,p FROM variants ORDER BY run_timestamp,row_id").fetchall()
                if rid != results.get("ledger_run_id")]
        qs = bh_fdr(prior + [r["p"] for r in results["combinations"]])[-len(results["combinations"]):]
        q_failures = [{"combination": r["params"]["combination"], "expected": q,
                       "actual": r["bh_q"]}
                      for r, q in zip(results["combinations"], qs)
                      if abs(q - r["bh_q"]) > 1e-12]
        check("bh_q_recomputation", not q_failures, q_failures[:3])

        after = snapshot.path.stat()
        check("snapshot_size_mtime_unchanged",
              (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns))
        prereg = OUT / "H01xH02_preregistration.md"
        check("pre_registration_hash",
              prereg.exists() and hashlib.sha256(prereg.read_bytes()).hexdigest()
              == results["pre_registration_sha256"])

    report = {"card_id": "H01xH02", "verified_at_utc": datetime.now(timezone.utc).isoformat(),
              "results_file": str(args.results), "checks": checks,
              "passed": len(checks) - len(failures), "failed": len(failures),
              "failures": failures, "sample_size": len(sample)}
    (OUT / "H01xH02_verification.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "failed": report["failed"],
                      "failures": failures[:5]}, indent=1))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
