"""Build B: 100 point-in-time insider/bulk-deal buy events, states and 20-day labels.

Insider: BUY / MARKET_PURCHASE, value >= Rs 50 lakh, known_at 2026-08-01..2026-09-10, one per company (largest).
Bulk: NSE bulk-deal BUY, same window, value >= Rs 50 lakh, one per company, fills the remainder.
State uses only data available at known_at: prior close/return/delivery (strictly before known_at date),
trade value vs market cap (shares from the latest results filing known before the event), sector, person category.
Label: stock total return vs Nifty 50 TRI over the next 20 trading days, entry at the first close after known_at.
"""
import json
import sqlite3
from datetime import datetime, date
from pathlib import Path

import duckdb
import numpy as np

ROOT = Path(r"C:\Users\warri\Downloads\IDM-worktrees\20261024T172743Z-a480564b")
DATA = Path(r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data")
SNAP = DATA / "snapshots" / "truth_2026-10-19.duckdb"
OUT = ROOT / "tasks/research/decision_pilot"
START, END = "2026-08-01", "2026-09-11"   # known_at window (end exclusive)
MIN_VALUE = 5_000_000
SEED = 20261024


def to_dt(s):
    if isinstance(s, datetime):
        return s
    s = str(s)
    for f in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:26], f)
        except ValueError:
            pass
    raise ValueError(s)


def main():
    d = duckdb.connect(str(SNAP), read_only=True)
    eq = sqlite3.connect(f"file:{DATA / 'equity_intelligence.db'}?mode=ro", uri=True)

    px = {}
    for sym, dt, close, tr, dl in d.execute("""select symbol, date, close, tr_close, delivery_pct
            from px_nse_adj where date between '2026-06-20' and '2026-10-19' order by symbol, date""").fetchall():
        px.setdefault(sym, []).append((str(dt)[:10], close, tr, dl))
    nifty = {str(dt)[:10]: tri for dt, tri in d.execute("""select date, tri from index_tri where index_name='NIFTY 50'
            and date between '2026-06-20' and '2026-10-19'""").fetchall()}
    sectors = dict(d.execute("select symbol, sector from company_industry").fetchall())

    insider = eq.execute("""select symbol, company, person_category, value_inr, qty, trade_from, known_at
        from insider_trades_v2 where known_at>=? and known_at<? and transaction_type='BUY'
        and mode='MARKET_PURCHASE' and value_inr>=? and coalesce(is_superseded,0)=0
        order by value_inr desc""", (START, END, MIN_VALUE)).fetchall()
    # one event per company: largest value (rows already sorted)
    ins, seen = [], set()
    for r in insider:
        if r[0] not in seen:
            seen.add(r[0]); ins.append(r)

    bulk = d.execute("""select symbol, security, quantity*price as val, quantity, price, date, known_at_utc
        from nse_deals where date between '2026-08-01' and '2026-09-10' and lower(deal_type) like '%bulk%'
        and lower(buy_sell) like 'buy%' and quantity*price>=? order by quantity*price desc""", [MIN_VALUE]).fetchall()

    def shares_before(sym, ts):
        r = d.execute("""select PaidUpValueOfEquityShareCapital, FaceValueOfEquityShareCapital, period_end, known_at_utc
            from results_key where symbol=? and PaidUpValueOfEquityShareCapital is not null
            and FaceValueOfEquityShareCapital is not null and FaceValueOfEquityShareCapital>0
            and cast(period_end as date)<=? and cast(known_at_utc as timestamp)<=?
            order by cast(period_end as date) desc, cast(known_at_utc as timestamp) desc limit 1""",
                      [sym, ts.date(), ts]).fetchone()
        if not r or not r[1]:
            return None
        return r[0] / r[1], r[2], r[3]

    def make(sym, company, pcat, val, known_at, etype, trade_date):
        bars = px.get(sym)
        if not bars or len(bars) < 26:
            return None
        known_at = to_dt(known_at)
        known_ds = known_at.date().isoformat()
        prev = [i for i, b in enumerate(bars) if b[0] < known_ds]
        if len(prev) < 21:
            return None
        pi = prev[-1]
        entry = next((i for i, b in enumerate(bars) if b[0] > known_ds), None)
        if entry is None or entry + 20 >= len(bars):
            return None
        sb = shares_before(sym, known_at)
        if not sb:
            return None
        shares, filing_period, filing_known = sb
        close_prev, tr_prev = bars[pi][1], bars[pi][2]
        if not close_prev or not tr_prev:
            return None
        d0, d1 = bars[entry][0], bars[entry + 20][0]
        if d0 not in nifty or d1 not in nifty:
            return None
        stock_ret = bars[entry + 20][2] / bars[entry][2] - 1
        nifty_ret = nifty[d1] / nifty[d0] - 1
        dlv = next((b[3] for b in reversed(bars[:pi + 1]) if b[3] is not None), None)
        prior = bars[pi][2] / bars[pi - 20][2] - 1
        mcap = shares * close_prev
        state = {
            "company": company, "sector": sectors.get(sym) or "Unknown",
            "event_type": etype, "person_category": pcat,
            "trade_value_inr": round(float(val), 2),
            "trade_size_pct_mcap": round(float(val) / mcap, 6) if mcap else None,
            "prior_20d_return": round(float(prior), 4),
            "delivery_pct": round(float(dlv), 2) if dlv is not None else None,
        }
        trade_ok = str(trade_date)[:10] <= known_ds
        return {
            "arm": "B", "id": f"{etype}_{sym}_{str(trade_date)[:10]}", "symbol": sym,
            "known_at": known_at.isoformat(sep=" "), "trade_date": str(trade_date)[:10],
            "state": state, "label": int(stock_ret > nifty_ret),
            "stock_ret": round(float(stock_ret), 4), "nifty_ret": round(float(nifty_ret), 4),
            "entry_date": str(d0), "exit_date": str(d1),
            "pit_check": {"price_asof": str(bars[pi][0]), "delivery_asof": str(bars[pi][0]),
                          "filing_period_end": str(filing_period), "filing_known_at": str(filing_known),
                          "trade_date_ok": bool(trade_ok), "sector_snapshot": "2026-10-19",
                          "ok": bool(bars[pi][0] < known_ds and dlv is not None and trade_ok)},
        }

    events = []
    for r in ins:
        e = make(r[0], r[1], r[2], r[3], r[6], "insider_buy", r[5] or r[6])
        if e:
            events.append(e)
    used = {e["symbol"] for e in events}
    print(f"insider eligible {len(events)} of {len(ins)} companies")

    rng = np.random.default_rng(SEED)
    pool = []
    for r in bulk:
        if r[0] in used:
            continue
        e = make(r[0], r[1], "Bulk deal buyer", r[2], r[6], "bulk_deal_buy", r[5])
        if e:
            pool.append(e)
            used.add(r[0])
    # keep the larger of duplicate symbols in the pool, then sample the remainder
    need = 100 - len(events)
    pick = rng.choice(len(pool), size=min(need, len(pool)), replace=False)
    events += [pool[i] for i in sorted(pick)]
    print(f"bulk eligible {len(pool)}, picked {len(events)-len([e for e in events if e['state']['event_type']=='insider_buy'])}")

    out = OUT / "data/b_events.json"
    json.dump(events, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    base = np.mean([e["label"] for e in events])
    print(f"events={len(events)} base_rate={base:.2f} "
          f"insider={sum(e['state']['event_type']=='insider_buy' for e in events)} "
          f"dates={min(e['known_at'] for e in events)[:10]}..{max(e['known_at'] for e in events)[:10]}")
    print("missing delivery:", sum(e["state"]["delivery_pct"] is None for e in events))
    print("sample:", json.dumps(events[0], ensure_ascii=False)[:700])


if __name__ == "__main__":
    main()
