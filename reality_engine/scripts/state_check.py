"""Check for reality_engine/query/state.py (PIPELINE_TODO Q4): leak test + latency over random (isin, t).

For N random equity ISINs from security_master and random times 2021-01-01 .. snapshot date: every returned row with a
known_at_utc must be < t, every price bar's date must be on or before t's IST date; state() latency p50 / p95 / max
(first call excluded: it opens the snapshot). Prints ALL CHECKS PASSED or the failures.

    python -m reality_engine.scripts.state_check [--n 300] [--seed 7]
"""
import argparse
import datetime as dt
import random
import time

from reality_engine.query.state import IST, _con, latest_snapshot, state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    snap = latest_snapshot()
    con = _con(snap)
    isins = [r[0] for r in con.execute(
        "SELECT isin FROM security_master WHERE isin LIKE 'INE%' AND isin IN (SELECT isin FROM px_daily) ORDER BY isin").fetchall()]
    rng = random.Random(a.seed)
    end = dt.datetime.strptime(snap.stem.split("_")[1], "%Y-%m-%d")
    start = dt.datetime(2021, 1, 1)
    state(isins[0], "2024-01-01")   # warm-up: opens the snapshot
    times, leaks, nonempty = [], [], {}
    for _ in range(a.n):
        isin = rng.choice(isins)
        t = start + dt.timedelta(seconds=rng.randrange(int((end - start).total_seconds())))
        t0 = time.perf_counter()
        s = state(isin, t.strftime("%Y-%m-%d %H:%M:%S"))
        times.append(time.perf_counter() - t0)
        tu = dt.datetime.fromisoformat(s["_meta"]["t_utc"])
        t_ist_date = (tu + dt.timedelta(hours=5, minutes=30)).date()
        for k, rows in s.items():
            if not isinstance(rows, list):
                continue
            nonempty[k] = nonempty.get(k, 0) + bool(rows)
            for r in rows:
                ku = r.get("known_at_utc")
                if ku is not None and ku >= tu:
                    leaks.append((isin, t, k, ku))
                if k == "prices" and r["date"] > t_ist_date:
                    leaks.append((isin, t, k, r["date"]))
    times.sort()
    p50, p95, mx = times[len(times) // 2], times[int(len(times) * 0.95)], times[-1]
    print(f"snapshot {snap.name}; {a.n} calls; latency p50 {p50:.3f}s p95 {p95:.3f}s max {mx:.3f}s")
    print("sections non-empty:", nonempty)
    fails = []
    if leaks:
        fails.append(f"{len(leaks)} leaked rows, e.g. {leaks[:5]}")
    if p95 > 1.0:
        fails.append(f"p95 latency {p95:.2f}s > 1 s")
    print("ALL CHECKS PASSED" if not fails else "FAILED: " + "; ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
