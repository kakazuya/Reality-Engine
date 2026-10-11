"""Row-level verification: a row is 'verified' when one of its own cells equals an XBRL annual figure or the same
figure printed as current year in last year's report (prior-year tie). Then the row's label, unit and year mapping
are confirmed by an independent source, and its other cells (e.g. the FY24 value next to a matched FY23 value) can be
stored. Reports the share of table cells that are verified this way and a random sample to hand-check."""
import json, random, re, sys
from collections import defaultdict
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from gate import prior_index, norm, storable

OUT = HERE / 'out_step4'
random.seed(21)
tot = defaultdict(int); sample = []
print(f"{'report':11} {'cells':>7} {'verified rows -> cells':>22}  via xbrl / prior-year")
for f in sorted(OUT.glob('*.json')):
    sym = f.stem
    o = json.loads(f.read_text(encoding='utf-8'))
    tie = json.loads((HERE / 'xbrl_tie' / f'{sym}.json').read_text(encoding='utf-8'))
    xh = {(h['page'], norm(h['raw'])) for h in tie['hits']}
    prev_f = OUT / 'prev' / f'{sym}.json'
    prev = prior_index(prev_f, '2023') if prev_f.exists() else set()
    rows = defaultdict(list)
    for p in o['pages']:
        for r in p['rows']:
            if r.get('via') == 'columns' and r.get('value') is not None:
                rows[(p['page'], r['block'], r['row'])].append(r)
    cells = sum(len(v) for v in rows.values()); ver = vx = vp = 0; vrows = []
    for (pg, b, i), rs in rows.items():
        by_x = any((pg, norm(r['values'][0])) in xh for r in rs)
        by_p = sum(1 for r in rs if (r.get('period') or '').startswith('2023') and len(norm(r['values'][0]).replace('.', '')) >= 3
                   and (r.get('unit'), norm(r['values'][0])) in prev) >= 1
        if by_x or by_p:
            good = [r for r in rs if storable(r)]
            ver += len(good); vx += by_x; vp += (by_p and not by_x)
            vrows += [(pg, r) for r in good]
    print(f'{sym:11} {cells:7} {ver:9} = {ver / max(1, cells):5.0%}        {vx} / {vp}')
    tot['cells'] += cells; tot['ver'] += ver
    sample += [(sym, pg, r) for pg, r in random.sample(vrows, min(3, len(vrows)))]
print(f"\nall: {tot['ver'] / tot['cells']:.0%} of table cells verified at row level")
print('\n| report | page | label | column | period | unit | value |\n|---|---|---|---|---|---|---|')
for sym, pg, r in sample:
    print(f"| {sym} | {pg} | {r['label'][:60]} | {r['column'][:40]} | {r['period']} | {r['unit']} | {r['values'][0]} |")
