"""Layout-robust repetition: share of this year's 8-word shingles (numbers -> #) present in last year's AR.
Reported per page then summarised: share of pages that are >= 80% / >= 50% repeated."""
import re, sys
import pymupdf
sys.path.insert(0, 'tasks/ar_study/challenger')
from redundancy import ar, cur
sys.stdout.reconfigure(encoding='utf-8')
K = 8
def words(t): return re.sub(r'[\d,.]+', '#', re.sub(r'[^\w\s.,]', ' ', t.lower())).split()
def shingles(ws): return {' '.join(ws[i:i + K]) for i in range(len(ws) - K + 1)}
tot = [0, 0, 0, 0]
for s, p in cur.items():
    prev = ar(s, '2023-05-01', '2023-10-31')
    if not prev: continue
    old = set()
    for pg in pymupdf.open(prev): old |= shingles(words(pg.get_text()))
    pages = [shingles(words(pg.get_text())) for pg in pymupdf.open(p)]
    pages = [x for x in pages if len(x) >= 30]
    shared = sum(len(x & old) for x in pages); allsh = sum(len(x) for x in pages)
    hi = sum(1 for x in pages if len(x & old) / len(x) >= 0.8); mid = sum(1 for x in pages if len(x & old) / len(x) >= 0.5)
    print(f'{s:11} shingles repeated {shared/allsh:4.0%} | pages >=80% repeated {hi/len(pages):4.0%} | >=50% {mid/len(pages):4.0%} | pages {len(pages)}')
    tot[0] += shared; tot[1] += allsh; tot[2] += hi; tot[3] += len(pages)
print(f'weighted: shingles repeated {tot[0]/tot[1]:.0%}; pages >=80% repeated {tot[2]/tot[3]:.0%}')
