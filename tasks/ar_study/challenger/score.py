"""Score the CPU extractor against the gold sets.

Each gold number is 'structured' (sits in a labelled row on its page +-1), 'captured' (only inside kept text), or
'missed'. Must-find items: numbers as above; prose items are found when their keywords sit in kept text on the page +-1.
"""
import json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).parent


def norm(s):
    return s.replace(',', '').replace('(', '').replace(')', '').replace('%', '').strip().lstrip('-')


def load(sym):
    o = json.loads((HERE / 'out' / f'{sym}.json').read_text(encoding='utf-8'))
    return {p['page']: p for p in o['pages']}


def has_label(lbl):
    return len(re.findall(r'[A-Za-z]', lbl or '')) >= 4


def locate(pages, value, page):
    rx = re.compile(r'(?<!\d)(?<!\d\.)' + re.escape(value) + r'(?![\d])')
    best = 'missed'
    for q in (page, page - 1, page + 1):
        p = pages.get(q)
        if not p: continue
        for r in p['rows']:
            if any(norm(v) == value for v in r.get('values', [])):
                return 'structured' if has_label(r.get('label')) else 'row-no-label'
        if any(rx.search(k['text'].replace(',', '')) for k in p['kept']):
            best = 'captured'
    return best


import pymupdf
sys.path.insert(0, str(HERE))
from build_gold import SRC
from extract_cpu import clean


def page_texts(sym):
    d = pymupdf.open(HERE.parent / SRC[sym])
    return {i + 1: clean(d[i].get_text()).replace(',', '') for i in range(len(d))}


def form_of(pages, value, page):
    rx = re.compile(r'(?<!\d)(?<!\d\.)' + re.escape(value) + r'(?![\d])')
    for q in (page, page - 1, page + 1):
        for line in pages.get(q, '').splitlines():
            if rx.search(line):
                rest = rx.sub('', line)
                return 'tabular' if len(re.findall(r'[A-Za-z]', rest)) < 25 else 'prose'
    return '?'


def main():
    gold = json.loads((HERE / 'gold_numbers.json').read_text(encoding='utf-8'))
    must = json.loads((HERE / 'gold_mustfind.json').read_text(encoding='utf-8'))
    P = {s: load(s) for s in {g['symbol'] for g in gold}}
    global TXT
    TXT = {s: page_texts(s) for s in P}
    by_form = defaultdict(Counter)
    res = Counter(); by_fam = defaultdict(Counter); by_sym = defaultdict(Counter); misses = []
    for g in gold:
        pg = P[g['symbol']].get(g['page'], {})
        fam = pg.get('family', '?')
        r = locate(P[g['symbol']], g['value'], g['page'])
        g['form'] = form_of(TXT[g['symbol']], g['value'], g['page'])
        by_form[g['form']][r] += 1
        res[r] += 1; by_fam[fam][r] += 1; by_sym[g['symbol']][r] += 1
        if r != 'structured': misses.append({**g, 'family': fam, 'result': r})
    n = len(gold)
    print(f'GOLD NUMBERS ({n}, cited by Haiku readers, verified on the page)')
    for k in ('structured', 'row-no-label', 'captured', 'missed'):
        print(f'  {k:13} {res[k]:5}  {res[k]/n:.0%}')
    print('\nby form of the number in the text (tabular = on its own line; prose = inside a sentence)')
    for f, c in by_form.items():
        t = sum(c.values())
        print(f'  {f:8} n={t:4}  structured {c["structured"]/t:4.0%}  no-label {c["row-no-label"]/t:4.0%}  captured {c["captured"]/t:4.0%}  missed {c["missed"]/t:4.0%}')
    print('\nby company'); [print(' ', s, dict(c)) for s, c in by_sym.items()]
    print('\nby section family (page of the fact)')
    for f, c in sorted(by_fam.items(), key=lambda x: -sum(x[1].values())):
        t = sum(c.values()); print(f'  {f:13} n={t:4}  structured {c["structured"]/t:4.0%}  no-label {c["row-no-label"]/t:4.0%}  captured {c["captured"]/t:4.0%}  missed {c["missed"]/t:4.0%}')
    print('\nMUST-FIND')
    for m in must:
        pages = P[m['symbol']]
        if m['kind'] == 'number':
            r = locate(pages, m['value'], m['page'])
        else:
            near = [pages.get(q, {}) for q in (m['page'] - 1, m['page'], m['page'] + 1)]
            kept = ' '.join([k['text'] for p in near for k in p.get('kept', [])] + [r.get('label', '') + ' ' + ' '.join(r.get('values', [])) for p in near for r in p.get('rows', [])])
            r = 'captured' if all(kw.lower() in kept.lower() for kw in m['keywords']) else 'missed'
        print(f"  {m['id']:3} {m['kind']:6} {r:12} p.{m['page']:<4} {pages.get(m['page'], {}).get('family', '?'):12} {m['what']}")
    (HERE / 'misses.json').write_text(json.dumps(misses, ensure_ascii=False, indent=1), encoding='utf-8')
    fams = {s: Counter(p['family'] for p in P[s].values()) for s in P}
    print('\npage families:'); [print(' ', s, dict(c)) for s, c in fams.items()]


if __name__ == '__main__':
    main()
