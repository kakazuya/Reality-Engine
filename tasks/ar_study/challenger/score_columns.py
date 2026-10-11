"""Score the column parser: is each number tied to the right year, unit and a usable label?

Period truth comes from the Haiku readers' own wording, e.g. "329.45 (FY23 213.10)", "1,230.79 vs 1,169.08",
"₹ 10.00 crore (previous year ₹ 41.84 crore)": the first number is FY24, the second FY23. Each pair must sit on the
cited page (+-1) of the PDF text.
"""
import json, re, sys
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from score import load, norm, page_texts
from build_gold import snippets, PAGE

N = r'\(?-?[\d,]+\.\d+\)?%?'
PAIR = [re.compile(rf'({N})\s*(?:cr|crores?|lakhs?|%|mn)?\s*\(\s*(?:FY\s*[\'’]?23|PY|FY23:?|previous year|prior year|2022-23|vs\.?)\s*:?\s*(?:₹|Rs\.?)?\s*({N})', re.I),
        re.compile(rf'({N})\s*(?:cr|crores?|lakhs?|%)?\s*(?:vs\.?|versus|against)\s*(?:₹|Rs\.?)?\s*({N})\s*(?:cr|crores?|lakhs?|%)?\s*(?:\(?\s*(?:FY\s*23|PY|previous|prior|2022-23))', re.I),
        re.compile(rf'({N})\s*(?:cr|crores?|lakhs?)?\s*\((?:FY\s*[\'’]?23|PY)\s*({N})\)', re.I)]


def pairs():
    seen = set()
    for sym, text, f in snippets():
        pages = {int(a) for a, b in PAGE.findall(text)}
        if not pages: continue
        for rx in PAIR:
            for m in rx.finditer(text):
                cur, prev = norm(m.group(1)), norm(m.group(2))
                if cur == prev or (sym, cur, prev) in seen: continue
                seen.add((sym, cur, prev)); yield sym, cur, prev, sorted(pages)


def find(P, value, pages):
    for p in pages:
        for q in (p, p - 1, p + 1):
            for r in P.get(q, {}).get('rows', []):
                if r.get('via') == 'columns' and norm(r['values'][0]) == value:
                    return r, q
    return None, None


def main():
    P = {s: load(s) for s in ('COCHINSHIP', 'CONCOR', 'GESHIP')}
    T = {s: page_texts(s) for s in P}
    res, unit_res, label_res, bad = Counter(), Counter(), Counter(), []
    n = 0
    for sym, cur, prev, pages in pairs():
        rx = lambda v: re.compile(r'(?<!\d)(?<!\d\.)' + re.escape(v) + r'(?![\d])')
        if not any(rx(cur).search(T[sym].get(q, '')) and rx(prev).search(T[sym].get(q, '')) for p in pages for q in (p - 1, p, p + 1)):
            continue
        n += 1
        for v, want in ((cur, '2024'), (prev, '2023')):
            r, q = find(P[sym], v, pages)
            if not r: res['not in a column row'] += 1; continue
            per = r.get('period') or ''
            tag = 'ok' if per.startswith(want) else 'no period' if not per else 'wrong'
            tag += ' (2-col default)' if per.endswith('*') else ''
            res[tag] += 1
            label_res['label ok' if len(re.findall(r'[A-Za-z]', r['label'])) >= 4 else 'no label'] += 1
            unit_res[r.get('unit') or 'none'] += 1
            if not tag.startswith('ok'): bad.append((sym, q, v, want, per, r['label'][:50], r['column'][:50]))
    print(f'{n} current/previous pairs from reader text, both numbers present on the page')
    tot = sum(res.values())
    for k, c in res.most_common(): print(f'  {k:28} {c:4} {c/tot:.0%}')
    print('labels:', dict(label_res)); print('units:', dict(unit_res))
    print('sample of misses:'); [print('  ', b) for b in bad[:15]]


if __name__ == '__main__':
    main()
