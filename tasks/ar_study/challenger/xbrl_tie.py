"""Step 1: statements from XBRL, annual-report tables as the cross-check.

For a report (symbol, fiscal year end) take the NSE results XBRL 'Yearly' filings (standalone + consolidated):
  context FourD = full-year flows (P&L, cash flow), OneI = year-end balances, OneD = Q4 only (ignored here).
Every XBRL figure is looked for among the report's CPU-parsed column rows (current-year period) after converting
the row to rupees with the row's unit. A hit:
  - verifies that figure (two independent sources agree);
  - verifies the AR table's unit and year columns -> the whole table can be trusted (used by the validation gate).
Output: challenger/xbrl_tie/<SYM>.json  {xbrl: {...}, hits: [...], table_hits: {page: n}}
"""
import json, re, sqlite3, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).parent
ROOT = HERE.parents[2]
XDB = ROOT / 'reality_engine' / 'data' / 'results_xbrl.db'
SCALE = {'crore': 1e7, 'lakh': 1e5, 'million': 1e6, 'thousand': 1e3, 'billion': 1e9}
KEY = ['RevenueFromOperations', 'ProfitLossForPeriod', 'CashFlowsFromUsedInOperatingActivities', 'Assets',
       'EquityAndLiabilities', 'Equity', 'TradeReceivablesCurrent', 'BorrowingsNoncurrent', 'BorrowingsCurrent',
       'Inventories', 'ProfitBeforeTax', 'DepreciationDepletionAndAmortisationExpense', 'FinanceCosts']


def low_priority():
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL
    except Exception:
        pass


def xbrl_annual(symbol, fy_end='2024-03-31'):
    c = sqlite3.connect(f'file:{XDB}?mode=ro', uri=True)
    out = {}
    for file, cons in c.execute("""select file, consolidated from filings where symbol=? and reporting_quarter='Yearly'
                                   and period_end like ? order by dissem_ts desc""", (symbol, fy_end + '%')):
        scope = 'consolidated' if cons.lower().startswith('consol') else 'standalone'
        if scope in out: continue
        facts = {}
        for concept, ctx, v in c.execute("select concept, context, value from facts where file=? and context in ('FourD','OneI')", (file,)):
            if isinstance(v, (int, float)) and v not in (0, 0.0): facts[concept] = v
        out[scope] = facts
    return out


def decimals(raw):
    m = re.search(r'\.(\d+)', raw)
    return len(m.group(1)) if m else 0


def tie(symbol, ar_json, fy='2024'):
    o = json.loads(Path(ar_json).read_text(encoding='utf-8'))
    X = xbrl_annual(symbol, f'{fy}-03-31')
    rows = [(p['page'], r) for p in o['pages'] for r in p['rows']
            if r.get('via') == 'columns' and r.get('value') not in (None, 0) and r.get('unit') in SCALE and (r.get('period') or '').startswith(fy)]
    index = defaultdict(list)
    for pg, r in rows:
        index[round(abs(r['value']), 0)].append((pg, r))
    hits, by_scope = [], Counter()
    for scope, facts in X.items():
        for concept, v in facts.items():
            for unit, sc in SCALE.items():
                target = abs(v) / sc
                for cand in (round(target, 0), round(target, 0) - 1, round(target, 0) + 1):
                    for pg, r in index.get(cand, []):
                        if r['unit'] != unit: continue
                        d = decimals(r['values'][0])
                        if round(abs(r['value']), d) == round(target, d):
                            hits.append({'scope': scope, 'concept': concept, 'xbrl_inr': v, 'page': pg, 'label': r['label'][:80],
                                         'raw': r['values'][0], 'unit': unit, 'period': r['period']})
    # one hit per (scope, concept): prefer label words that resemble the concept
    best = {}
    for h in hits:
        k = (h['scope'], h['concept'])
        words = re.findall(r'[A-Z][a-z]+', h['concept'])
        score = sum(w.lower()[:5] in h['label'].lower() for w in words)
        if k not in best or score > best[k][0]: best[k] = (score, h)
    hits = [h for _, h in best.values()]
    table_hits = Counter(h['page'] for h in hits)
    n_facts = {s: len(f) for s, f in X.items()}
    key = {s: {k: (k in X.get(s, {}), any(h['scope'] == s and h['concept'] == k for h in hits)) for k in KEY if k in X.get(s, {})} for s in X}
    res = {'symbol': symbol, 'n_xbrl_facts': n_facts, 'n_hits': Counter(h['scope'] for h in hits), 'key': key,
           'hits': hits, 'table_hits': dict(table_hits)}
    (HERE / 'xbrl_tie').mkdir(exist_ok=True)
    (HERE / 'xbrl_tie' / f'{symbol}.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    return res


if __name__ == '__main__':
    low_priority()
    reports = {s: HERE / 'out' / f'{s}.json' for s in ('COCHINSHIP', 'CONCOR', 'GESHIP')}
    reports.update({s: HERE / 'out_unseen' / f'{s}.json' for s in json.loads((HERE / 'unseen.json').read_text())})
    print(f"{'report':11} {'XBRL facts sa/cons':>18} {'found in AR sa/cons':>20}  key items found (sa | cons)")
    for s, f in reports.items():
        r = tie(s, f)
        nf, nh = r['n_xbrl_facts'], r['n_hits']
        keys = ' | '.join(f"{sum(v[1] for v in r['key'].get(sc, {}).values())}/{len(r['key'].get(sc, {}))}" for sc in ('standalone', 'consolidated'))
        print(f"{s:11} {nf.get('standalone', 0):8}/{nf.get('consolidated', 0):<9} {nh.get('standalone', 0):9}/{nh.get('consolidated', 0):<10}  {keys}")
