"""How much of an annual report is repeated text? (CPU only)

Paragraph = PyMuPDF text block, normalised (lower case, digits -> #, whitespace collapsed); blocks < 80 chars ignored.
  yoy        - share of this year's paragraph text found verbatim (after normalising) in the same company's previous AR
  boilerplate- share found in at least 2 OTHER companies' ARs of the sample
  sa_vs_cons - share of consolidated-section paragraphs that also appear in the standalone section of the same AR
"""
import hashlib, json, re, sqlite3, sys
from collections import defaultdict
import pymupdf
sys.stdout.reconfigure(encoding='utf-8')

def paras(pdf):
    out = []
    for i, pg in enumerate(pymupdf.open(pdf)):
        for b in pg.get_text('blocks'):
            t = re.sub(r'\s+', ' ', re.sub(r'\d', '#', b[4].lower())).strip()
            if len(t) >= 80: out.append((i + 1, t, hashlib.md5(t.encode()).hexdigest()))
    return out

c = sqlite3.connect('file:reality_engine/data/equity_intelligence.db?mode=ro', uri=True)
def ar(sym, start, end):
    r = c.execute("""select a.local_file_path from corporate_documents a join master_companies m on m.isin=a.isin join v_document_pit v on v.id=a.id
        where m.nse_symbol=? and a.doc_type='ANNUAL_REPORT' and a.local_file_path is not null and v.pit_date between ? and ? order by v.pit_date desc""", (sym, start, end)).fetchone()
    return r[0] if r else None

U = json.load(open('tasks/ar_study/challenger/unseen.json'))
cur = {s: U[s]['pdf'] for s in U}
cur.update({'COCHINSHIP': ar('COCHINSHIP', '2024-05-01', '2024-10-31'), 'CONCOR': ar('CONCOR', '2024-05-01', '2024-10-31'), 'GESHIP': 'tasks/ar_study/src/GESHIP_FY24_AR.pdf'})
P = {s: paras(p) for s, p in cur.items() if p}
owners = defaultdict(set)
for s, ps in P.items():
    for _, _, h in ps: owners[h].add(s)
print(f"{'report':12} {'paras':>6} {'chars':>9} {'yoy-same':>9} {'boilerplate':>11} {'either':>7}")
tot = defaultdict(int)
for s, ps in P.items():
    prev = ar(s, '2023-05-01', '2023-10-31')
    prev_h = {h for _, _, h in paras(prev)} if prev else set()
    ch = sum(len(t) for _, t, _ in ps)
    yoy = sum(len(t) for _, t, h in ps if h in prev_h)
    bp = sum(len(t) for _, t, h in ps if len(owners[h] - {s}) >= 2)
    either = sum(len(t) for _, t, h in ps if h in prev_h or len(owners[h] - {s}) >= 2)
    print(f"{s:12} {len(ps):6} {ch:9,} {yoy/ch if prev else float('nan'):9.0%} {bp/ch:11.0%} {either/ch if prev else float('nan'):7.0%}{'' if prev else '  (no FY23 AR on disk)'}")
    if prev: tot['ch'] += ch; tot['yoy'] += yoy; tot['either'] += either
    tot['all'] += ch; tot['bp'] += bp
print(f"\nweighted: yoy-same {tot['yoy']/tot['ch']:.0%} | boilerplate {tot['bp']/tot['all']:.0%} | either {tot['either']/tot['ch']:.0%} (reports with a FY23 AR)")
# standalone vs consolidated duplication inside one report
for s in ('DABUR', 'CONCOR', 'GESHIP'):
    ps = P[s]; d = pymupdf.open(cur[s])
    cons_start = next((i for i in range(len(d)) if re.search(r'consolidated\s+balance\s+sheet\s+as\s+(at|on)', d[i].get_text()[:600], re.I)), None)
    if not cons_start: continue
    sa = {h for p, _, h in ps if p <= cons_start}
    cons = [(t, h) for p, t, h in ps if p > cons_start]
    dup = sum(len(t) for t, h in cons if h in sa) / max(1, sum(len(t) for t, _ in cons))
    print(f'{s}: consolidated section from p.{cons_start + 1}; {dup:.0%} of its paragraph text repeats the standalone section')
