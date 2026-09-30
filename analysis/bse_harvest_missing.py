"""List equity-ISIN symbols whose BSE harvest is incomplete (any year-window missing in `done`).

Writes analysis/bse_harvest_failed.csv. Safe to run any time (read-only on both DBs).
Retry those symbols gently, single worker:
    python analysis/bse_announcement_harvest.py --workers 1 --symbols-file analysis/bse_harvest_failed.csv
"""
import csv, datetime as dt, re, sqlite3

EQ = re.compile(r'INE[0-9A-Z]{4}01[0-9A-Z]{3}')
live = sqlite3.connect('file:reality_engine/data/equity_intelligence.db?mode=ro', uri=True)
out = sqlite3.connect('file:analysis/bse_announcements.db?mode=ro', uri=True)
years = set(range(2020, dt.date.today().year + 1))
have = {}
for scrip, win in out.execute("select scrip, win from done"):
    have.setdefault(str(scrip), set()).add(win)
rows = live.execute("select nse_symbol,bse_code,isin from master_companies where bse_code is not null and is_active=1").fetchall()
missing = [(s, c, len(years - have.get(str(c), set()))) for s, c, i in rows if EQ.fullmatch(i or '') and years - have.get(str(c), set())]
started = [m for m in missing if m[2] < len(years)]
with open('analysis/bse_harvest_failed.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(['nse_symbol', 'bse_code', 'windows_missing'])
    w.writerows(sorted(missing, key=lambda m: m[0]))
print(f"equity symbols: {sum(1 for r in rows if EQ.fullmatch(r[2] or ''))}; incomplete: {len(missing)} "
      f"(partially done: {len(started)}, untouched: {len(missing) - len(started)}) -> analysis/bse_harvest_failed.csv")
