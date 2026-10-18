"""Security master from the exchanges' own files (2026-10-19, Shivam: survivorship-safe universe).

Why: master_companies missed 3,923 of the 8,736 equity ISINs that have BSE prices (delisted, SME, BSE-only), and NSE's
price file (sec_bhavdata_full) has no ISIN, so 615 NSE symbols trading in 2026 had no ISIN. Any backtest joined through
master_companies silently dropped dead companies (survivorship bias) and broke on symbol changes.

Inputs (raw_market/): nse_cm (old NSE bhavcopy, ISIN column, 2019-01..2021-10), nse_cm_isin (old format to 2024-07-05,
UDiFF after), mkt_bse_eq_daily (BSE prices with ISIN + scrip code, 2019..), masters/ (BSE scrip master Active/Delisted/
Suspended for Equity + SME + MT; NSE EQUITY_L and SME_EQUITY_L with listing dates).
Outputs (equity_intelligence.db, new tables; master_companies is not touched):
  symbol_isin_history (exchange, symbol, isin, first_date, last_date, n_days): one row per (symbol, ISIN) run, so a
      symbol that changed ISIN (face-value change / split) or an ISIN that changed symbol is resolvable by date
  security_master (isin, issuer, name, nse_symbol, bse_code, bse_symbol, bse_status, segment, nse_listing_date,
      first_trade, last_trade, last_seen_nse, last_seen_bse, in_master_companies, source)
Equity ISINs only (INE + 4 + '01' + 3); ETFs, bonds, G-secs, warrants are left out.

    python -m reality_engine.scripts.build_security_master
"""
import csv
import glob
import io
import json
import re
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "reality_engine/data/raw_market"
DB = ROOT / "reality_engine/data/equity_intelligence.db"
EQ = re.compile(r"INE[0-9A-Z]{4}01[0-9A-Z]{3}")
DDL = """
DROP TABLE IF EXISTS symbol_isin_history;
CREATE TABLE symbol_isin_history (exchange TEXT, symbol TEXT, isin TEXT, first_date TEXT, last_date TEXT, n_days INTEGER,
    PRIMARY KEY (exchange, symbol, isin, first_date));
DROP TABLE IF EXISTS security_master;
CREATE TABLE security_master (isin TEXT PRIMARY KEY, issuer TEXT, name TEXT, nse_symbol TEXT, bse_code TEXT,
    bse_symbol TEXT, bse_status TEXT, segment TEXT, nse_listing_date TEXT, first_trade TEXT, last_trade TEXT,
    last_seen_nse TEXT, last_seen_bse TEXT, in_master_companies INTEGER, source TEXT);
CREATE INDEX idx_sih_isin ON symbol_isin_history(isin);
CREATE INDEX idx_sih_symbol ON symbol_isin_history(exchange, symbol, first_date);
"""


def nse_rows():
    """(date, symbol, series, isin, name) from every NSE bhavcopy that has an ISIN column"""
    for d in ("nse_cm", "nse_cm_isin"):
        for f in sorted(glob.glob(str(RAW / d / "*.zip"))):
            try:
                z = zipfile.ZipFile(f)
                txt = z.read(z.namelist()[0]).decode("latin1")
            except Exception:
                continue
            rd = csv.DictReader(io.StringIO(txt))
            for r in rd:
                r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
                if "TckrSymb" in r:     # UDiFF
                    yield r["TradDt"], r["TckrSymb"], r.get("SctySrs"), r.get("ISIN"), r.get("FinInstrmNm")
                elif "ISIN" in r:       # old format
                    try:
                        dd = datetime.strptime(r["TIMESTAMP"], "%d-%b-%Y").date().isoformat()
                    except ValueError:
                        continue
                    yield dd, r["SYMBOL"], r.get("SERIES"), r.get("ISIN"), None


def runs(rows):
    """collapse (exchange, symbol, isin, date) into contiguous runs per (symbol, isin)"""
    acc = {}
    for ex, sym, isin, d in rows:
        k = (ex, sym, isin)
        a = acc.get(k)
        if a is None:
            acc[k] = [d, d, 1]
        else:
            a[0] = min(a[0], d); a[1] = max(a[1], d); a[2] += 1
    return acc


def main():
    db = sqlite3.connect(DB, timeout=600)
    db.executescript(DDL)
    names, nse_last, first_any, last_any = {}, {}, {}, {}
    nse_tuples = []
    for d, sym, series, isin, name in nse_rows():
        if not isin or not EQ.fullmatch(isin):
            continue
        nse_tuples.append(("NSE", sym, isin, d))
        if name:
            names.setdefault(isin, name)
        if d > nse_last.get(isin, ("", ""))[0]:
            nse_last[isin] = (d, sym)
    bse_last, bse_tuples = {}, []
    for d, code, isin, sym, name in db.execute("SELECT date, sc_code, isin, symbol, name FROM mkt_bse_eq_daily WHERE isin LIKE 'INE%'"):
        if not EQ.fullmatch(isin or ""):
            continue
        bse_tuples.append(("BSE", str(code), isin, d))
        names.setdefault(isin, (name or "").strip())
        if d > bse_last.get(isin, ("", "", ""))[0]:
            bse_last[isin] = (d, str(code), sym)
    hist = runs(nse_tuples + bse_tuples)
    db.executemany("INSERT INTO symbol_isin_history VALUES (?,?,?,?,?,?)",
                   [(ex, sym, isin, a[0], a[1], a[2]) for (ex, sym, isin), a in hist.items()])
    for (ex, sym, isin), a in hist.items():
        first_any[isin] = min(first_any.get(isin, a[0]), a[0]); last_any[isin] = max(last_any.get(isin, a[1]), a[1])
    # exchange masters: status, segment, listing date, names
    bse_status, seg, listing, nse_sym_master = {}, {}, {}, {}
    for f in glob.glob(str(RAW / "masters/bse_scrips_*.json")):
        j = json.load(open(f, encoding="utf-8"))
        j = j if isinstance(j, list) else j.get("Table", [])
        for r in j:
            i = (r.get("ISIN_NUMBER") or "").strip()
            if EQ.fullmatch(i):
                bse_status.setdefault(i, r.get("Status"))
                seg.setdefault(i, "SME" if (r.get("Segment") or "").upper().startswith("SM") or "_SME_" in f else "main")
                names.setdefault(i, r.get("Issuer_Name") or r.get("Scrip_Name"))
                bse_last.setdefault(i, ("", r.get("SCRIP_CD"), r.get("scrip_id")))
    for fn, sg in (("nse_EQUITY_L.csv", "main"), ("nse_SME_EQUITY_L.csv", "SME")):
        p = RAW / "masters" / fn
        if not p.exists():
            continue
        for r in csv.DictReader(open(p, encoding="utf-8", errors="replace")):
            r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
            i = r.get("ISIN NUMBER") or r.get("ISIN_NUMBER") or ""
            if EQ.fullmatch(i):
                seg[i] = sg if i not in seg or sg == "SME" else seg[i]
                listing[i] = r.get("DATE OF LISTING") or r.get("LISTING_DATE")
                nse_sym_master[i] = r.get("SYMBOL")
                names.setdefault(i, r.get("NAME OF COMPANY") or r.get("NAME_OF_COMPANY"))
    known = {r[0] for r in db.execute("SELECT isin FROM master_companies")}
    allisin = set(first_any) | set(bse_status) | set(nse_sym_master)
    rows = []
    for i in sorted(allisin):
        bl = bse_last.get(i, ("", None, None))
        rows.append((i, i[:7], names.get(i), nse_sym_master.get(i) or nse_last.get(i, (None, None))[1], bl[1], bl[2],
                     bse_status.get(i), seg.get(i), listing.get(i), first_any.get(i), last_any.get(i),
                     nse_last.get(i, (None,))[0], bl[0] or None, int(i in known),
                     "+".join(s for s, ok in (("nse_px", i in nse_last), ("bse_px", bool(bl[0])), ("bse_master", i in bse_status),
                                              ("nse_master", i in nse_sym_master)) if ok)))
    db.executemany("INSERT INTO security_master VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.commit()
    q = lambda s: db.execute(s).fetchone()
    print("security_master", q("SELECT COUNT(*), SUM(in_master_companies), SUM(segment='SME'), SUM(last_trade < '2026-06-01') FROM security_master"))
    print("  bse_status", db.execute("SELECT bse_status, COUNT(*) FROM security_master GROUP BY 1").fetchall())
    print("symbol_isin_history", q("SELECT COUNT(*), COUNT(DISTINCT isin) FROM symbol_isin_history"))
    print("  NSE symbols with >1 ISIN", q("SELECT COUNT(*) FROM (SELECT symbol FROM symbol_isin_history WHERE exchange='NSE' GROUP BY symbol HAVING COUNT(DISTINCT isin)>1)"))
    print("  ISINs with >1 NSE symbol", q("SELECT COUNT(*) FROM (SELECT isin FROM symbol_isin_history WHERE exchange='NSE' GROUP BY isin HAVING COUNT(DISTINCT symbol)>1)"))
    print("  NSE symbols trading 2026 (sec_bhavdata_full EQ/BE/BZ/SM/ST) still without ISIN",
          q("""SELECT COUNT(DISTINCT f.symbol) FROM mkt_nse_full_daily f WHERE f.date>='2026-01-01' AND f.series IN ('EQ','BE','BZ','SM','ST')
               AND NOT EXISTS (SELECT 1 FROM symbol_isin_history h WHERE h.exchange='NSE' AND h.symbol=f.symbol
                               AND f.date BETWEEN h.first_date AND h.last_date)"""))


if __name__ == "__main__":
    main()
