"""Build a small, public-data-only sample of the live DB so the code can be run on another machine before the full DB is fetched.

Includes: full schema (tables/indexes/views/triggers/FTS), small reference tables in full, and for the Nifty 50 + Midcap 150 universe:
prices, corporate actions, document METADATA (with PIT columns), plus ~40 concall/presentation documents with chunk text (no embeddings).
Excludes: Telegram posts/tags, YouTube (member-video) rows, *_demo tables, quarantined/test rows, embeddings, anything from `pdfs/`.
Output: C:/pack_drive/sample/equity_intelligence_sample.db (+ .xz). NOT for git (third-party exchange data)."""
import csv, os, random, re, sqlite3, subprocess, time
from pathlib import Path
SRC = Path('reality_engine/data/equity_intelligence.db')
OUT = Path('C:/pack_drive/sample'); OUT.mkdir(parents=True, exist_ok=True)
DST = OUT / 'equity_intelligence_sample.db'
if DST.exists(): DST.unlink()
EXCLUDE = {'telegram_posts', 'telegram_post_tags', 'news_visual_artifacts', 'chunk_symbol_tags', 'substrate_quarantine'}
SMALL = 20_000
uni = set()
for f in ('nifty50_current.csv', 'niftymidcap150_current.csv'):
    uni |= {r['Symbol'].strip() for r in csv.DictReader(open(f'reality_engine/data/index_constituents/{f}', encoding='utf-8-sig'))}
s = sqlite3.connect(f'file:{SRC}?mode=ro', uri=True, timeout=600); d = sqlite3.connect(DST); d.execute('pragma foreign_keys=off')
objs = s.execute("select type, name, tbl_name, sql from sqlite_master where sql is not null and name not like 'sqlite_%'").fetchall()
virtual = [n for t, n, _, q in objs if t == 'table' and q.upper().startswith('CREATE VIRTUAL')]
def shadow(n): return any(n.startswith(v + '_') for v in virtual)
tables = [(n, q) for t, n, _, q in objs if t == 'table' and not shadow(n)]
for n, q in tables: d.execute(q)
for t in ('index', 'view', 'trigger'):
    for tt, n, _, q in objs:
        if tt == t and not shadow(n):
            try: d.execute(q)
            except Exception as e: print('skip', t, n, str(e)[:60])
d.commit()
syms = ','.join("'%s'" % x.replace("'", "") for x in uni)
report = {}
def copy(name, where='', limit=None):
    cols = [r[1] for r in s.execute(f'pragma table_info("{name}")')]
    q = f'select * from "{name}" {where}' + (f' limit {limit}' if limit else '')
    cur = s.execute(q); n = 0
    while True:
        rows = cur.fetchmany(50_000)
        if not rows: break
        d.executemany(f'insert or ignore into "{name}" values ({",".join("?"*len(cols))})', rows); n += len(rows)
    d.commit(); report[name] = n
skipped = []
for name, q in tables:
    if name in virtual or name in EXCLUDE or 'demo' in name or name in ('corporate_documents', 'document_chunks', 'raw_documents', 'daily_price_delivery'): continue
    cols = {r[1] for r in s.execute(f'pragma table_info("{name}")')}
    cnt = s.execute(f'select count(*) from "{name}"').fetchone()[0]
    if cnt <= SMALL: copy(name)
    elif 'symbol' in cols: copy(name, f'where symbol in ({syms})')
    else: skipped.append((name, cnt))
copy('daily_price_delivery', f'where symbol in ({syms})')
copy('corporate_documents', f'where symbol in ({syms})')
# ~40 public concall/presentation docs with chunk text (embeddings dropped)
random.seed(7)
ids = [r[0] for r in s.execute(f"select doc_id from raw_documents where source_type in ('CONCALL_TRANSCRIPT','INVESTOR_PRESENTATION') and doc_id in (select doc_id from document_chunks where symbol in ({syms}) and chunk_index=0)")]
pick = random.sample(ids, min(40, len(ids)))
ph = ','.join(map(str, pick))
copy('raw_documents', f'where doc_id in ({ph})')
ccols = [r[1] for r in s.execute('pragma table_info(document_chunks)')]
rows = s.execute(f'select * from document_chunks where doc_id in ({ph}) and chunk_index<100000').fetchall()
ei = ccols.index('embedding'); rows = [tuple(None if i == ei else v for i, v in enumerate(r)) for r in rows]
d.executemany(f'insert or ignore into document_chunks values ({",".join("?"*len(ccols))})', rows); report['document_chunks'] = len(rows)
ci = {c: i for i, c in enumerate(ccols)}
st = {r[0]: r[1] for r in s.execute(f'select doc_id, source_type from raw_documents where doc_id in ({ph})')}
d.executemany('insert into intelligence_fts(chunk_id, symbol, isin, source_type, document_date, document_text) values (?,?,?,?,?,?)',
              [(str(r[ci['chunk_id']]), r[ci['symbol']] or '', r[ci['isin']] or '', st.get(r[ci['doc_id']], ''), r[ci['published_date']], r[ci['content']]) for r in rows])
d.commit(); d.execute('vacuum'); d.close()
mb = DST.stat().st_size / 1e6
print(f'sample DB: {mb:.0f} MB, universe {len(uni)} symbols'); print({k: v for k, v in sorted(report.items(), key=lambda kv: -kv[1])[:14]})
print('large tables skipped (no symbol column):', skipped)
subprocess.run(['xz', '-T0', '-6', '-k', '-f', str(DST)], check=True); print('xz:', f'{Path(str(DST)+".xz").stat().st_size/1e6:.0f} MB')
