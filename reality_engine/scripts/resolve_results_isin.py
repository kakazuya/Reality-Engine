"""Trading ISIN for every results XBRL filing (2026-10-19). New table results_xbrl.db `filings_isin`; `filings` is untouched.

Why: filings.isin is the ISIN written inside the XBRL, and many companies keep filing their pre-split / pre-face-value
ISIN for years (BEL files INE263A01016, which stopped trading before 2019; HAL, CANBK, DIXON, HINDZINC the same):
~15% of filings would not join to prices or to the other stores by ISIN.

Rule, per filing, at the dissemination date (the date the market saw it; period_end if missing):
  1 nse_symbol  NSE symbol_isin_history window of filings.symbol containing that date (nearest window otherwise)
  2 bse_code    BSE symbol_isin_history window of filings.scrip_code, same way
  3 filed       the filed ISIN, when security_master knows it
  else          unresolved (isin NULL)
`same_issuer` = resolved and filed ISIN share the issuer code (chars 3-7, e.g. INE263A); 0 means the symbol now
belongs to another issuer (symbol reuse) or the company changed issuer code - such rows keep method + both ISINs so a
reader can decide; state(isin, t) uses only same_issuer=1 or method='filed'.

    python -m reality_engine.scripts.resolve_results_isin [--check]
"""
import argparse
import bisect
import sqlite3
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"

DDL = """CREATE TABLE IF NOT EXISTS filings_isin (file TEXT PRIMARY KEY, isin_filed TEXT, isin TEXT, method TEXT,
    same_issuer INTEGER, as_of TEXT, resolved_at TEXT DEFAULT (datetime('now')));
CREATE INDEX IF NOT EXISTS ix_filings_isin_isin ON filings_isin(isin)"""


def windows(ei, exchange):
    w = defaultdict(list)
    for sym, isin, a, b in ei.execute("SELECT symbol, isin, first_date, last_date FROM symbol_isin_history "
                                      "WHERE exchange = ? ORDER BY symbol, first_date", (exchange,)):
        w[sym].append((a, b, isin))
    return w


def pick(wins, day):
    if not wins:
        return None
    starts = [a for a, _, _ in wins]
    i = bisect.bisect_right(starts, day) - 1
    if i >= 0 and day <= wins[i][1]:
        return wins[i][2]
    # nearest window: before the first one -> first; in a gap or after the last -> the one that started before
    return wins[max(i, 0)][2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="print the summary only, write nothing")
    a = ap.parse_args()
    ei = sqlite3.connect(f"file:{DATA / 'equity_intelligence.db'}?mode=ro", uri=True)
    nse, bse = windows(ei, "NSE"), windows(ei, "BSE")
    known = {r[0] for r in ei.execute("SELECT isin FROM security_master")}
    rx = sqlite3.connect(DATA / "results_xbrl.db", timeout=120)
    rows = []
    for file, isin_f, sym, code, pend, dissem in rx.execute(
            "SELECT file, isin, symbol, scrip_code, period_end, dissem_ts FROM filings"):
        day = (dissem or pend or "")[:10]
        isin, how = pick(nse.get(sym), day), "nse_symbol"
        if not isin:
            isin, how = pick(bse.get(code), day), "bse_code"
        if not isin:
            isin, how = (isin_f, "filed") if isin_f in known else (None, "unresolved")
        same = None if not (isin and isin_f) else int(isin[2:7] == isin_f[2:7])
        rows.append((file, isin_f, isin, how, same, day))
    n = len(rows)
    by = defaultdict(int)
    for r in rows:
        by[(r[3], r[4], r[1] == r[2])] += 1
    print(f"{n:,} filings")
    for (how, same, eq), k in sorted(by.items(), key=lambda x: -x[1]):
        print(f"  {how:<11} same_issuer={same} isin_changed={not eq}: {k:,}")
    if a.check:
        return
    rx.executescript(DDL)
    rx.executemany("INSERT OR REPLACE INTO filings_isin (file, isin_filed, isin, method, same_issuer, as_of) "
                   "VALUES (?,?,?,?,?,?)", rows)
    rx.commit()
    print("written filings_isin:", rx.execute("SELECT COUNT(*) FROM filings_isin").fetchone()[0])


if __name__ == "__main__":
    main()
