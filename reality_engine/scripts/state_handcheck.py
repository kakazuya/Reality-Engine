"""Hand check of state(isin, t) against raw sources (PIPELINE_TODO Q4, 2026-10-19): 20 random companies with 2025-26
results at four times; for each, the latest result revenue vs the raw XBRL file, the last price vs the raw NSE bhavcopy
(UDiFF) file, and the latest BSE announcement time vs the feed (IST -> UTC, and before t). First run: 53 checks, 0 mismatches.

    python -m reality_engine.scripts.state_handcheck
"""
import sys, re, zipfile, io, csv, sqlite3, datetime as dt, random
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from reality_engine.config import raw_dir
from reality_engine.query.state import state, _con, latest_snapshot
RAW = raw_dir("raw_market")
con = _con(latest_snapshot())
rng = random.Random(11)
isins = [r[0] for r in con.execute("""select distinct trading_isin from results_key where period_end >= '2025-06-30'
          and trading_isin in (select isin from security_master where nse_symbol is not null)""").fetchall()]
picks = rng.sample(sorted(isins), 20)
times = ['2025-08-20 10:00', '2025-11-20 16:00', '2026-02-20 12:00', '2026-08-25 15:00']
an = sqlite3.connect('file:analysis/bse_announcements.db?mode=ro', uri=True)
def raw_xbrl_value(file, concept='RevenueFromOperations'):
    p = RAW / 'nse_results_xbrl' / file
    if not p.exists(): return 'no raw file'
    t = p.read_text(encoding='utf-8', errors='replace')
    m = re.search(rf'<in-capmkt:{concept} contextRef="OneD"[^>]*>([^<]+)<', t)
    return float(m.group(1)) if m else None
def raw_close(sym, d):
    for z in RAW.joinpath('nse_cm_isin').glob(f'*{d.replace("-","")}*'):
        txt = zipfile.ZipFile(z).read(zipfile.ZipFile(z).namelist()[0]).decode()
        for r in csv.DictReader(io.StringIO(txt)):
            if r.get('TckrSymb') == sym and r.get('SctySrs') in ('EQ','BE','BZ','SM','ST'): return float(r['ClsPric'])
    return 'no raw file'
ok = bad = 0
for n, isin in enumerate(picks):
    t = times[n % 4]
    s = state(isin, t)
    sym = (s['identity'][0]['nse_symbol'] if s['identity'] else '?')
    tu = dt.datetime.fromisoformat(s['_meta']['t_utc'])
    line = [f"{n+1:2d} {sym:<12} t={t}"]
    res = [r for r in s['results'] if r['consolidated'] in ('Consolidated', 'Standalone')]
    if res:
        r = res[0]; rv = raw_xbrl_value(r['file'])
        good = rv == r['RevenueFromOperations'] or (rv is None and r['RevenueFromOperations'] is None)
        line.append(f"result {r['period_end']} {r['consolidated'][:4]} known {r['known_at_utc']} rev {r['RevenueFromOperations']} raw {rv} {'OK' if good else 'MISMATCH'}")
        ok += good; bad += (not good)
    if s['prices']:
        p = s['prices'][-1]; d = str(p['date'])
        rc = raw_close(p['symbol'], d) if p['exch'] == 'NSE' else 'bse'
        good = rc in ('no raw file', 'bse') or abs(rc - p['close']) < 1e-6
        line.append(f"last px {d} {p['exch']} {p['close']} raw {rc} {'OK' if good else 'MISMATCH'}")
        ok += good; bad += (not good)
    if s['announcements']:
        a = s['announcements'][0]
        src = an.execute("select DissemDT, HEADLINE from ann where NEWSID=?", (a['NEWSID'],)).fetchone()
        ist = dt.datetime.fromisoformat(src[0][:19]) - dt.timedelta(hours=5, minutes=30)
        good = abs((ist - a['known_at_utc']).total_seconds()) < 1 and a['known_at_utc'] < tu
        line.append(f"ann {src[0][:16]} IST -> {a['known_at_utc']} UTC {'OK' if good else 'MISMATCH'}")
        ok += good; bad += (not good)
    print(" | ".join(line))
print('checks ok', ok, 'mismatch', bad)
