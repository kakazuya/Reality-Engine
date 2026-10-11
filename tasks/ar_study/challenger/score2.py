"""Finer scoring: how usable is each CPU hit without an LLM?

clean      = labelled row, label <= 12 words, <= 2 values (current / previous year)  -> storable by rules
multicol   = labelled row with > 2 values: needs the column headers mapped           -> rules (header parser) or LLM
sentence   = the 'label' is a sentence fragment: the number sits in prose           -> needs an LLM (or stays text)
no-label / captured / missed as in score.py
Also: unit check against the unit words the Haiku reader wrote next to the number.
"""
import json, re, sys
from collections import Counter, defaultdict
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from score import load, norm, page_texts, form_of

def grade(pages, g):
    rx = re.compile(r'(?<!\d)(?<!\d\.)' + re.escape(g['value']) + r'(?![\d])')
    best, unit = 'missed', None
    for q in (g['page'], g['page'] - 1, g['page'] + 1):
        p = pages.get(q)
        if not p: continue
        for r in p['rows']:
            if any(norm(v) == g['value'] for v in r.get('values', [])):
                lab = r.get('label') or ''
                if len(re.findall(r'[A-Za-z]', lab)) < 4: return 'no-label', p['unit']
                if len(lab.split()) > 12 or re.search(r'\b(was|were|is|are|has|have|of the|during|amount)\b', lab): return 'sentence', p['unit']
                return ('multicol' if len(r['values']) > 2 else 'clean'), p['unit']
        if any(rx.search(k['text'].replace(',', '')) for k in p['kept']): best, unit = 'captured', p['unit']
    return best, unit

gold = json.load(open('gold_numbers.json', encoding='utf-8'))
P = {s: load(s) for s in ('COCHINSHIP', 'CONCOR', 'GESHIP')}
T = {s: page_texts(s) for s in P}
res, by_form, unit_chk = Counter(), defaultdict(Counter), Counter()
for g in gold:
    r, u = grade(P[g['symbol']], g)
    res[r] += 1; by_form[form_of(T[g['symbol']], g['value'], g['page'])][r] += 1
    c = g['context'].lower()
    i = c.find(g['value'][:6].split('.')[0])
    near = c[i:i + 40] if i >= 0 else ''
    said = 'crore' if re.search(r'\bcr\b|crore', near) else 'lakh' if 'lakh' in near else None
    if said and u and r in ('clean', 'multicol', 'sentence', 'no-label'): unit_chk['ok' if said == u else f'wrong ({u} vs reader {said})'] += 1
n = len(gold)
print(f'{n} gold numbers')
for k in ('clean', 'multicol', 'sentence', 'no-label', 'captured', 'missed'): print(f'  {k:9} {res[k]:4} {res[k]/n:4.0%}')
for f, c in by_form.items():
    t = sum(c.values()); print(f'  [{f}] n={t} ' + ' '.join(f'{k} {c[k]/t:.0%}' for k in ('clean', 'multicol', 'sentence', 'no-label', 'captured', 'missed')))
print('unit check (page-header unit vs unit the reader wrote):', dict(unit_chk))
