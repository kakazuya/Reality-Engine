"""Run the CPU extractor UNCHANGED on unseen reports and check quality without any LLM.

Checks per report:
  balance   - balance sheet totals: the largest 'Total...' value on a balance-sheet page appears twice (assets side =
              equity-and-liabilities side), for FY24 and FY23, standalone and consolidated;
  external  - consolidated revenue from operations and profit for the year (FY24) vs yfinance annual_financials (+-3%);
  coverage  - on statement and notes pages, share of decimal figures that landed in a labelled column row with a period;
  confidence- distribution of the parser's per-table confidence.
Writes challenger/out_unseen/<SYM>.json and challenger/unseen_report.md, plus a random row sample for hand checking.
"""
import json, random, re, sys, time
from collections import Counter
from pathlib import Path
import pymupdf

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import extract_cpu
from extract_cpu import clean

TO_CR = {'crore': 1.0, 'lakh': 0.01, 'million': 0.1, 'thousand': 1e-4, 'billion': 100.0}
DEC = re.compile(r'(?<![\d.,])\(?-?(?:\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+\.\d+)\)?(?![\d])')


def fy_of(per):
    return (per or '')[:4]


def balance_check(pages):
    out = Counter()
    for p in pages:
        if not p['rows'] or not p.get('is_bs'):
            continue
        for fy in ('2024', '2023'):
            vals = [r['value'] for r in p['rows'] if r.get('via') == 'columns' and r.get('value') and fy_of(r.get('period')) == fy
                    and re.match(r'\s*total\b', r['label'], re.I)]
            if len(vals) < 2: continue
            top = max(vals)
            if top > 0 and vals.count(top) >= 2: out[f'{p["scope"]} FY{fy[2:]} balanced'] += 1
    return out


def external_check(pages, yf):
    if not yf: return {}
    _, rev, pat = yf
    res = {}
    for name, rx, ref in (('revenue', r'^\s*(i\.?\s*)?revenue from operations\s*$', rev), ('profit', r'^\s*(xi+\.?\s*|\w\)\s*)?profit for the (year|period)\b', pat)):
        best = None
        for p in pages:
            if p['scope'] != 'consolidated': continue
            for r in p['rows']:
                if r.get('via') != 'columns' or not r.get('value') or fy_of(r.get('period')) != '2024': continue
                if not re.search(rx, r['label'], re.I) or not r.get('unit'): continue
                v = r['value'] * TO_CR.get(r['unit'], 0)
                err = abs(v - ref) / abs(ref) if ref else 9
                if best is None or err < best[0]: best = (round(err, 4), round(v, 2), ref, p['page'], r['unit'])
        res[name] = best
    return res


def coverage(doc, pages):
    tot = got = 0
    for p in pages:
        figs = {f.replace(',', '').strip('()-') for f in DEC.findall(clean(doc[p['page'] - 1].get_text()))}
        if len(figs) < 15 or p.get('dropped'): continue      # table-dense pages only, any section
        rows = {r['values'][0].replace(',', '').strip('()-') for r in p['rows']
                if r.get('via') == 'columns' and r.get('period') and len(re.findall(r'[A-Za-z]', r['label'])) >= 4}
        tot += len(figs); got += len(figs & rows)
    return got, tot


def main():
    cases = json.loads((HERE / 'unseen.json').read_text())
    (HERE / 'out_unseen').mkdir(exist_ok=True)
    extract_cpu.OUT = HERE / 'out_unseen'
    lines = ['# Unseen-report test (rules unchanged)\n', '| Report | pages | s | balance checks passed | revenue vs yfinance | profit vs yfinance | coverage (table-dense pages) | tables conf<0.5 |', '|---|---|---|---|---|---|---|---|']
    sample = []
    random.seed(11)
    for sym, c in cases.items():
        t0 = time.time()
        o = extract_cpu.run(sym, c['pdf'], fy=2024)
        doc = pymupdf.open(c['pdf'])
        pages = o['pages']
        for p in pages:
            p['is_bs'] = bool(re.search(r'balance\s+sheet', clean(doc[p['page'] - 1].get_text())[:500], re.I) and bool(re.search(r'total\s+(equity\s+and\s+liabilities|liabilities\s+and\s+equity|assets)|capital\s+and\s+liabilities', clean(doc[p['page'] - 1].get_text()) + (clean(doc[p['page']].get_text()) if p['page'] < len(doc) else ''), re.I)))
        bal = balance_check(pages)
        ext = external_check(pages, None if sym == 'INFY' else c.get('yf'))
        got, tot = coverage(doc, pages)
        confs = [r['confidence'] for p in pages for r in p['rows'] if r.get('via') == 'columns']
        low = sum(1 for x in confs if x < 0.5) / max(1, len(confs))
        fmt = lambda e: '-' if not e else f"{'✔' if e[0] <= 0.03 else '✘'} {e[1]:,.0f} vs {e[2]:,.0f} (p.{e[3]}, {e[4]})"
        lines.append(f"| {sym} ({c['sector']}) | {len(pages)} | {time.time() - t0:.0f} | {len(bal)}: {', '.join(sorted(k.split(' (')[0] for k in bal)) or 'none'} | "
                     f"{fmt(ext.get('revenue'))} | {fmt(ext.get('profit'))} | {got}/{tot} = {got / max(1, tot):.0%} | {low:.0%} |")
        rows = [(p['page'], r) for p in pages for r in p['rows'] if r.get('via') == 'columns' and r.get('value') is not None and p['family'] in ('fs_statement', 'notes', 'brsr', 'mda', 'directors')]
        for pg, r in random.sample(rows, min(3, len(rows))):
            sample.append(f"| {sym} | {pg} | {r['label'][:60]} | {r['column'][:40]} | {r['period']} | {r['unit']} | {r['values'][0]} | {r['confidence']} |")
        print(lines[-1], flush=True)
    lines += ['\n## Random rows for hand checking\n', '| Report | page | label | column | period | unit | value | conf |', '|---|---|---|---|---|---|---|---|'] + sample
    (HERE / 'unseen_report.md').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    main()
