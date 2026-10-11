"""Step 3: validation gate. Decides per table: cpu_ok (store without an LLM) or send_to_llm.

A table = one parsed block on one page (rows share `block`). A table is cpu_ok when either:
  xbrl  - one of its figures equals an XBRL annual figure (xbrl_tie hit on that page with the same label): two
          independent sources agree, so its unit and year columns are right; or
  sums  - confidence >= MIN_CONF and at least one 'Total' row equals the sum of the rows above it (back to the
          previous total, or the earlier totals: hierarchical subtotals), with no checked total failing badly.
Tables with neither are send_to_llm (as that table only). Tables with no Total row and no XBRL hit are
'unchecked': they go to the LLM too unless confidence is high (>= HIGH_CONF) and every row has a label and a period;
those are stored but flagged unchecked.
"""
import json, re
from collections import defaultdict

MIN_CONF = 0.7
HIGH_CONF = 0.9
TOTAL = re.compile(r'^\s*(\(?[a-z0-9]{1,4}[.)]\s*)?(sub[- ]?)?total\b|^\s*net\s+(total|cash)|^\s*grand total', re.I)


def tol(vals_raw):
    d = max((len(r.split('.')[1]) if '.' in r else 0) for r in vals_raw) if vals_raw else 0
    return max(0.011, 0.6 * 10 ** (-d) * max(2, len(vals_raw)))


def sum_check(rows):
    """rows: list of row dicts (one table), each with label, col, value, raw, row. Returns (passed, failed)."""
    by_col = defaultdict(list)
    for r in rows:
        if r.get('value') is not None and r.get('unit') != '%': by_col[r['col']].append(r)
    passed = failed = 0
    for col, rs in by_col.items():
        rs.sort(key=lambda r: r['row'])
        plain, totals = [], []
        for r in rs:
            if TOTAL.search(r['label'] or ''):
                cands = []
                if plain: cands.append([p for p in plain])
                if totals: cands.append([t for t in totals])
                if plain and totals: cands.append(totals + plain)
                ok = False
                for c in cands:
                    s = sum(x['value'] for x in c)
                    if abs(s - r['value']) <= tol([x['values'][0] for x in c] + [r['values'][0]]) or abs(abs(s) - abs(r['value'])) <= tol([r['values'][0]]):
                        ok = True; break
                if ok: passed += 1
                elif cands and abs(r['value']) > 0: failed += 1
                totals.append(r); plain = []
            else:
                plain.append(r)
    return passed, failed


MONEY = {'crore', 'lakh', 'million', 'thousand', 'billion', 'rupee'}


def norm(raw):
    return raw.replace(',', '').replace('(', '').replace(')', '').strip().lstrip('-')


def prior_index(prev_json, fy_prev):
    """Values printed as the current year in last year's report: {(unit, value string)}."""
    if not prev_json: return set()
    o = json.load(open(prev_json, encoding='utf-8'))
    return {(r.get('unit'), norm(r['values'][0])) for p in o['pages'] for r in p['rows']
            if r.get('via') == 'columns' and (r.get('period') or '').startswith(fy_prev) and r.get('value') not in (None, 0)}


def storable(r):
    """A row can be stored without an LLM only with a real label and a year (or a non-money unit that needs none)."""
    lab = r.get('label') or ''
    if len(re.findall(r'[A-Za-z]', lab)) < 4 or re.fullmatch(r'\W*(total|march \d+,? \d{4}|as at.*)\W*', lab, re.I): return False
    return bool(r.get('period')) or r.get('unit') in ('%', 'count')


def gate(ar_json, tie_json=None, prev_json=None, fy='2024'):
    o = json.load(open(ar_json, encoding='utf-8'))
    prev = prior_index(prev_json, str(int(fy) - 1))
    tie = json.load(open(tie_json, encoding='utf-8')) if tie_json else {'hits': []}
    xhits = defaultdict(set)
    for h in tie['hits']:
        xhits[h['page']].add((h['label'][:40], h['raw']))
    tables = []
    for p in o['pages']:
        blocks = defaultdict(list)
        for r in p['rows']:
            if r.get('via') == 'columns': blocks[r['block']].append(r)
        for b, rows in blocks.items():
            conf = min(r.get('confidence', 0) for r in rows)
            x = any((r['label'][:40], r['values'][0]) in xhits.get(p['page'], ()) for r in rows)
            ps, fl = sum_check(rows)
            py = [r for r in rows if (r.get('period') or '').startswith(str(int(fy) - 1)) and r.get('value') not in (None, 0)
                  and len(norm(r['values'][0]).replace('.', '')) >= 3]
            py_hit = sum(1 for r in py if (r.get('unit'), norm(r['values'][0])) in prev)
            labelled = all(len(re.findall(r'[A-Za-z]', r['label'])) >= 4 for r in rows)
            dated = all(r.get('period') for r in rows if r.get('unit') not in ('%', 'count'))
            if x: status, why = 'cpu_ok', 'xbrl'
            elif conf >= MIN_CONF and ps >= 1 and fl <= ps: status, why = 'cpu_ok', f'sums {ps}/{ps + fl}'
            elif len(py) >= 2 and py_hit >= max(2, 0.5 * len(py)): status, why = 'cpu_ok', f'prior-year {py_hit}/{len(py)}'
            elif ps == 0 and fl == 0 and conf >= HIGH_CONF and labelled and dated: status, why = 'stored_unchecked', 'high confidence, no total'
            else: status, why = 'send_to_llm', f'conf {conf}, sums {ps}/{ps + fl}'
            ok_cells = sum(1 for r in rows if storable(r)) if status != 'send_to_llm' else 0
            tables.append({'page': p['page'], 'block': b, 'rows': len({r['row'] for r in rows}), 'cells': len(rows), 'ok_cells': ok_cells,
                           'status': status, 'why': why, 'confidence': conf})
    return tables
