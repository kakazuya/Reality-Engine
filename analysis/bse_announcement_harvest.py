"""Harvest BSE corporate-announcement metadata (exact dissemination timestamps) into a SEPARATE sqlite.

Never writes to the live DB. Resumable per (scrip, year-window). PDF name (ATTACHMENTNAME) is the join key to
corporate_documents.source_url (AnnPdfOpen.aspx?Pname=<guid>.pdf).
usage: python analysis/bse_announcement_harvest.py [--limit-symbols N] [--symbols A,B] [--workers 3] [--start-year 2020]
"""
import argparse, re, sqlite3, threading, time, datetime as dt
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests as cr

LIVE = 'reality_engine/data/equity_intelligence.db'
OUT = 'analysis/bse_announcements.db'
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
     "Referer": "https://www.bseindia.com/", "Accept": "application/json, text/plain, */*", "Origin": "https://www.bseindia.com"}
URL = ("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno={p}&strCat=-1&strPrevDate={f}"
       "&strScrip={c}&strSearch=P&strToDate={t}&strType=C&subcategory=-1")
COLS = ['NEWSID', 'SCRIP_CD', 'ATTACHMENTNAME', 'NEWSSUB', 'HEADLINE', 'CATEGORYNAME', 'SUBCATNAME', 'NEWS_DT',
        'DT_TM', 'News_submission_dt', 'DissemDT', 'QUARTER_ID', 'Fld_Attachsize', 'ANNOUNCEMENT_TYPE']
lock = threading.Lock()
fails = 0
DELAY = 0.15
BLOCKED_UNTIL = 0.0  # set when BSE/Akamai answers 403; every worker waits it out (penalty box ~10 min)


def session():
    for attempt in range(8):  # ride out transient DNS/network drops
        try:
            s = cr.Session(impersonate="chrome120")
            s.get('https://www.bseindia.com/corporates/ann.html', headers=H, timeout=20)
            return s
        except Exception:
            time.sleep(min(15 * (attempt + 1), 120))
    raise RuntimeError("session: network unavailable after retries")


def windows(start_year):
    today = dt.date.today()
    for y in range(start_year, today.year + 1):
        yield y, f"{y}0101", (f"{y}1231" if y < today.year else today.strftime('%Y%m%d'))


def fetch_window(s, code, f, t):
    rows, p = [], 1
    while True:
        global BLOCKED_UNTIL
        while time.time() < BLOCKED_UNTIL:
            time.sleep(15)
        r = s.get(URL.format(p=p, f=f, c=code, t=t), headers=H, timeout=30)
        if r.status_code == 403:
            BLOCKED_UNTIL = max(BLOCKED_UNTIL, time.time() + 600)
            print(f"[{dt.datetime.now():%H:%M:%S}] 403 from BSE - all workers pausing 10 min", flush=True)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        tb = r.json().get('Table', [])
        rows += tb
        if len(tb) < 50:
            return rows
        p += 1
        time.sleep(DELAY)


def work(item, db, start_year):
    global fails
    global fails
    sym, code = item
    try:
        s = session()
    except Exception:
        with lock:
            fails += 1
        return sym, 'FAILED'
    for y, f, t in windows(start_year):
        with lock:
            if db.execute("select 1 from done where scrip=? and win=?", (code, y)).fetchone():
                continue
        for attempt in range(2):  # fail fast; stragglers go to the single-worker retry pass (bse_harvest_missing.py)
            try:
                rows = fetch_window(s, code, f, t)
                break
            except Exception as e:
                time.sleep(5 * (attempt + 1))
                try: s = session()
                except Exception: pass
        else:
            with lock:
                fails += 1
            return sym, 'FAILED'
        with lock:
            db.executemany(f"insert or ignore into ann({','.join(COLS)},symbol) values({','.join('?' * (len(COLS) + 1))})",
                           [tuple(r.get(c) for c in COLS) + (sym,) for r in rows])
            db.execute("insert or replace into done values(?,?,?,?)", (code, y, len(rows), dt.datetime.now().isoformat()))
            db.commit()
        time.sleep(DELAY)
    return sym, 'ok'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit-symbols', type=int, default=0)
    ap.add_argument('--symbols', default='')
    ap.add_argument('--symbols-file', default='', help='CSV/text with nse_symbol in first column (e.g. analysis/bse_harvest_failed.csv)')
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--start-year', type=int, default=2020)
    ap.add_argument('--delay', type=float, default=0.15, help='seconds between requests per worker')
    a = ap.parse_args()
    global DELAY
    DELAY = a.delay
    live = sqlite3.connect(f'file:{LIVE}?mode=ro', uri=True); live.execute('pragma query_only=1')
    where = "bse_code is not null and is_active=1"
    if a.symbols_file:
        import csv
        names = [r[0].strip() for r in csv.reader(open(a.symbols_file, encoding='utf-8')) if r and r[0].strip() and r[0] != 'nse_symbol']
        a.symbols = ','.join(names)
    if a.symbols:
        where += " and nse_symbol in (%s)" % ','.join("'%s'" % x for x in a.symbols.split(','))
    rows = live.execute(f"select nse_symbol,bse_code,isin from master_companies where {where} "
                        "order by is_nifty200 desc,is_nifty500 desc,is_nifty100 desc,nse_symbol").fetchall()
    # Only equity ISINs (INE + 4-char issuer + '01' security type). ETFs / MF units / segregated
    # portfolios (INF...) and partly-paid variants (IN9...) have no company announcement feed and
    # burn ~100s of retries each. Digit-leading tickers (3MINDIA, 360ONE...) are real equities and stay.
    EQ = re.compile(r'INE[0-9A-Z]{4}01[0-9A-Z]{3}')
    todo = [(s, c) for s, c, i in rows if EQ.fullmatch(i or '')]
    print(f"universe {len(rows)} -> equity-ISIN {len(todo)} (skipped {len(rows) - len(todo)}; see analysis/bse_skipped_symbols.csv)", flush=True)
    if a.limit_symbols:
        todo = todo[:a.limit_symbols]
    db = sqlite3.connect(OUT, check_same_thread=False)
    db.execute("pragma journal_mode=wal")
    db.execute(f"create table if not exists ann({','.join(c + (' TEXT PRIMARY KEY' if c == 'NEWSID' else '') for c in COLS)},symbol TEXT)")
    db.execute("create table if not exists done(scrip TEXT,win INT,n INT,at TEXT,primary key(scrip,win))")
    db.execute("create index if not exists ix_att on ann(ATTACHMENTNAME)")
    t0 = time.time(); n = 0
    with ThreadPoolExecutor(a.workers) as ex:
        for sym, st in ex.map(lambda it: work(it, db, a.start_year), todo):
            n += 1
            if n % 20 == 0 or st != 'ok':
                tot = db.execute("select count(*) from ann").fetchone()[0]
                print(f"[{n}/{len(todo)}] {sym} {st} rows={tot} {time.time()-t0:.0f}s", flush=True)
    print('DONE', n, 'symbols, failures', fails, f"{time.time()-t0:.0f}s")


if __name__ == '__main__':
    main()
