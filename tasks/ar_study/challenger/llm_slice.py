"""Estimate the text an LLM would still need to read per report after CPU filters:
  drop AGM-notice pages; drop table lines (numeric cells -> CPU/XBRL); drop lines whose 8-word shingles mostly (>=60%)
  appeared in last year's AR; keep the rest (new prose). Lines < 25 chars ignored."""
import re, sys
import pymupdf
sys.path.insert(0, 'tasks/ar_study/challenger')
from redundancy import ar, cur
from redundancy3 import words, shingles
from columns import lines_of, cells_of
sys.stdout.reconfigure(encoding='utf-8')
AGM = re.compile(r'notice is hereby given|agm notice|notice of (the )?\d+\w* annual general meeting', re.I)
tot = [0, 0, 0]
print(f"{'report':11} {'all chars':>10} {'new prose chars':>15} {'share':>6} {'~pages':>7}")
for s, p in cur.items():
    prev = ar(s, '2023-05-01', '2023-10-31')
    old = set()
    if prev:
        for pg in pymupdf.open(prev): old |= shingles(words(pg.get_text()))
    d = pymupdf.open(p); allc = keep = 0; agm = False
    for pg in d:
        t = pg.get_text(); allc += len(t)
        if AGM.search(t[:700]): agm = True
        elif re.search(r"directors'?|board'?s report|chairman|corporate overview", t[:400], re.I): agm = False
        if agm: continue
        lines = lines_of(pg)
        # group consecutive non-table lines into paragraphs, judge novelty per paragraph
        para = []
        def flush():
            global keep
            txt = ' '.join(para); para.clear()
            if len(txt) < 25: return 0
            sh = shingles(words(txt))
            if old and sh and len(sh & old) / len(sh) >= 0.6: return 0
            return len(txt)
        for ln in lines:
            if cells_of(ln):
                keep += flush(); continue
            para.append(' '.join(w for *_, w in ln['words']))
        keep += flush()
    print(f'{s:11} {allc:10,} {keep:15,} {keep/allc:6.0%} {keep/3800:7.0f}{"" if prev else "  (no FY23 AR: no diff)"}')
    tot[0] += allc; tot[1] += keep; tot[2] += 1
print(f'total: {tot[1]/tot[0]:.0%} of characters would go to an LLM; average ~{tot[1]/tot[2]/3800:.0f} page-equivalents per report')
