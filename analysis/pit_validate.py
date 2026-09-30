import sqlite3, datetime as dt, statistics as st, collections
live = sqlite3.connect('file:reality_engine/data/equity_intelligence.db?mode=ro', uri=True, timeout=120)
ann = sqlite3.connect('file:analysis/bse_announcements.db?mode=ro', uri=True)
done = {str(r[0]) for r in ann.execute("select distinct scrip from done")}
full = {s for (s,) in ann.execute("select scrip from (select scrip, count(*) n from done group by scrip) where n>=7")}
print('harvested symbols (any window):', len(done), '| all windows complete:', len(full))
codes = {r[0]: str(r[1]) for r in live.execute("select nse_symbol, bse_code from master_companies where bse_code is not null")}
H = {s for s, c in codes.items() if c in full}
rows = live.execute("select id,symbol,doc_type,doc_date,call_date,publication_date,bse_dissem_ts,bse_news_dt,bse_subcat,source_url from corporate_documents").fetchall()
inH = [r for r in rows if r[1] in H]
j = [r for r in inH if r[6]]
print(f'docs for fully-harvested symbols: {len(inH):,}; joined with BSE timestamp: {len(j):,} ({100*len(j)/len(inH):.1f}%)')
by = collections.Counter(); byj = collections.Counter()
for r in inH: by[r[2]] += 1; byj[r[2]] += bool(r[6])
for k in by: print(f'   {k:24s} {byj[k]:>6,}/{by[k]:>6,} ({100*byj[k]/by[k]:.0f}%)')
P = lambda s: dt.datetime.fromisoformat(s[:19])
# 1. sanity of the timestamp itself
bad = [r for r in j if not r[6][:4].isdigit()]; print('unparseable dissem ts:', len(bad))
lag = [(P(r[6]) - P(r[7])).total_seconds() / 3600 for r in j if r[7]]
print(f'dissem - news_dt (hours): median {st.median(lag):.2f}, p99 {sorted(lag)[int(.99*len(lag))]:.1f}, negative {sum(x<-0.01 for x in lag)}')
# 2. old label vs new
off = [(P(r[6]).date() - dt.date.fromisoformat(r[3])).days for r in j]
print(f'old doc_date vs true dissemination date: same day {sum(x==0 for x in off)/len(off)*100:.1f}%, median off {st.median(off)} days, >30d off {sum(abs(x)>30 for x in off)/len(off)*100:.1f}%')
# 3. cross-check against independent body-derived dates (concalls)
cc = [r for r in j if r[2] == 'CONCALL_TRANSCRIPT' and r[4]]
d2 = [(P(r[6]).date() - dt.date.fromisoformat(r[4])).days for r in cc]
if d2: print(f'concalls with both feed ts and body call_date: {len(d2)}; filing lag days median {st.median(d2)}, negative {sum(x<0 for x in d2)}, >45d {sum(x>45 for x in d2)}')
pp = [r for r in j if r[5]]
d3 = [(P(r[6]).date() - dt.date.fromisoformat(r[5][:10])).days for r in pp]
if d3: print(f'docs with feed ts and body publication_date: {len(d3)}; exact same day {sum(x==0 for x in d3)/len(d3)*100:.0f}%, within 1d {sum(abs(x)<=1 for x in d3)/len(d3)*100:.0f}%')
# 4. session assignment relevance
after = sum(1 for r in j if P(r[6]).time() >= dt.time(15, 30)); wkend = sum(1 for r in j if P(r[6]).weekday() >= 5)
print(f'disseminated after 15:30 IST: {after/len(j)*100:.0f}% (belong to next session) | on weekend: {wkend/len(j)*100:.1f}%')
# 5. why unjoined
un = [r for r in inH if not r[6]]
cnt = collections.Counter()
for r in un:
    u = r[9] or ''
    cnt['no-BSE-filename-url' if ('Pname=' not in u and '/AttachHis/' not in u) else ('pre-2020' if (r[3] or '') < '2020-01-01' else 'in-range-but-not-in-feed')] += 1
print('unjoined reasons:', dict(cnt))
print('unjoined by type/url:', collections.Counter((r[2], 'bseplus/AnnualReport' if 'bseplus/AnnualReport' in (r[9] or '') else 'other') for r in un if True).most_common(6))
