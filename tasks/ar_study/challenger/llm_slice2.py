"""LLM slice = text the CPU extractor KEPT (statutory blocks + red-flag lexicon lines) that is NEW vs last year's AR."""
import json, re, sys
from pathlib import Path
import pymupdf
sys.path.insert(0, 'tasks/ar_study/challenger')
import redundancy3  # noqa (prints its table; harmless)
from redundancy import ar, cur
from redundancy3 import words, shingles
sys.stdout.reconfigure(encoding='utf-8')
H = Path('tasks/ar_study/challenger')
tot = [0, 0, 0, 0]
print('\nreport       all chars   kept    kept&new  share  ~pages')
for s, p in cur.items():
    f = H / 'out_unseen' / f'{s}.json'
    if not f.exists(): f = H / 'out' / f'{s}.json'
    o = json.loads(f.read_text(encoding='utf-8'))
    prev = ar(s, '2023-05-01', '2023-10-31'); old = set()
    if prev:
        for pg in pymupdf.open(prev): old |= shingles(words(pg.get_text()))
    allc = sum(pg['chars'] for pg in o['pages']); kept = new = 0
    for pg in o['pages']:
        for k in pg['kept']:
            for para in re.split(r'\n(?=\S)', k['text']):
                kept += len(para); sh = shingles(words(para))
                if not old or not sh or len(sh & old) / len(sh) < 0.6: new += len(para)
    print(f'{s:11} {allc:10,} {kept/allc:6.0%} {new:10,} {new/allc:6.0%} {new/3800:6.0f}')
    tot[0] += allc; tot[1] += kept; tot[2] += new; tot[3] += 1
print(f'total kept {tot[1]/tot[0]:.0%}, kept&new {tot[2]/tot[0]:.0%} of characters; ~{tot[2]/tot[3]/3800:.0f} page-equivalents per report')
