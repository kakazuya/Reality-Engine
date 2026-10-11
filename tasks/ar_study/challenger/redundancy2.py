"""Sentence-level repetition: share of this year's sentence text that appeared (normalised) in last year's AR,
and in >= 2 other companies' ARs. Sentences < 40 chars ignored. Numbers -> '#', so a sentence whose only change is
a figure counts as repeated (the figure itself is caught by the table parser)."""
import json, re, sys
from collections import defaultdict
import pymupdf
sys.path.insert(0, 'tasks/ar_study/challenger')
from redundancy import ar, cur
sys.stdout.reconfigure(encoding='utf-8')

def sents(pdf):
    out = []
    for i, pg in enumerate(pymupdf.open(pdf)):
        t = re.sub(r'\s+', ' ', pg.get_text().lower())
        for s in re.split(r'(?<=[.;:])\s+(?=[a-z(])', t):
            n = re.sub(r'[\d,.]+', '#', s).strip()
            if len(n) >= 40: out.append((i + 1, n))
    return out

S = {s: sents(p) for s, p in cur.items() if p}
owners = defaultdict(set)
for s, ss in S.items():
    for _, n in ss: owners[n].add(s)
tot = defaultdict(int)
for s, ss in S.items():
    prev = ar(s, '2023-05-01', '2023-10-31')
    ps = {n for _, n in sents(prev)} if prev else set()
    ch = sum(len(n) for _, n in ss)
    yoy = sum(len(n) for _, n in ss if n in ps); bp = sum(len(n) for _, n in ss if len(owners[n] - {s}) >= 2)
    ei = sum(len(n) for _, n in ss if n in ps or len(owners[n] - {s}) >= 2)
    print(f'{s:11} yoy-same {yoy/ch:4.0%}  boilerplate {bp/ch:4.0%}  either {ei/ch:4.0%}')
    tot['ch'] += ch; tot['yoy'] += yoy; tot['bp'] += bp; tot['ei'] += ei
print(f"weighted: yoy-same {tot['yoy']/tot['ch']:.0%}, boilerplate {tot['bp']/tot['ch']:.0%}, either {tot['ei']/tot['ch']:.0%}")
