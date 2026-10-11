"""Step 4: full CPU pipeline on 13 FY24 reports (3 study + 10 unseen), no LLM.

extract (tables + kept text) -> XBRL tie-out -> validation gate -> year-over-year diff -> LLM slice.
Reports per report: tables cpu_ok / unchecked / send_to_llm (by count and by cells), XBRL facts found, LLM slice size,
must-find recall (study reports), and a random sample of cpu_ok rows for hand checking.
Runs at below-normal priority, one process (the deck extractor and concall ingestion keep running).
"""
import json, random, re, sqlite3, sys, time
from collections import Counter
from pathlib import Path
import pymupdf

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import extract_cpu, xbrl_tie, gate, yoy
from extract_cpu import AUDIT_TRIGGERS, LEXICON, LEXICON_FIN

OUT = HERE / 'out_step4'
SLICE_FAMILIES = {'auditor', 'caro', 'cag', 'secretarial', 'notes', 'directors', 'mda', 'fs_statement', 'overview'}


def prev_report(sym):
    if sym == 'GESHIP': return str(HERE.parent / 'src' / 'GESHIP_FY23_AR.pdf')
    c = sqlite3.connect(f"file:{ROOT / 'reality_engine' / 'data' / 'equity_intelligence.db'}?mode=ro", uri=True)
    r = c.execute("""select a.local_file_path from corporate_documents a join master_companies m on m.isin=a.isin
        join v_document_pit v on v.id=a.id where m.nse_symbol=? and a.doc_type='ANNUAL_REPORT' and a.local_file_path is not null
        and v.pit_date between '2023-05-01' and '2023-10-31' order by v.pit_date desc""", (sym,)).fetchone()
    return r[0] if r else None


def main():
    xbrl_tie.low_priority()
    OUT.mkdir(exist_ok=True)
    extract_cpu.OUT = OUT
    U = json.loads((HERE / 'unseen.json').read_text())
    from build_gold import SRC
    cases = {s: {'pdf': str((HERE.parent / p).resolve()) if not Path(p).is_absolute() else p, 'sector': None} for s, p in SRC.items()}
    cases.update({s: {'pdf': c['pdf'], 'sector': c['sector']} for s, c in U.items()})
    must = json.loads((HERE / 'gold_mustfind.json').read_text(encoding='utf-8'))
    lines = ['# Step 4: CPU pipeline on 13 FY24 reports (no LLM)\n',
             '| Report | s | XBRL figures found in AR (sa/cons) | tables: cpu_ok / unchecked / to LLM | cells stored by CPU | LLM slice: new prose | + LLM tables | diff baseline |',
             '|---|---|---|---|---|---|---|---|']
    sample, totals, must_res = [], Counter(), []
    random.seed(5)
    for sym, c in cases.items():
        t0 = time.time()
        o = extract_cpu.run(sym, c['pdf'], fy=2024, sector=c['sector'])
        tie = xbrl_tie.tie(sym, OUT / f'{sym}.json')
        prev = prev_report(sym)
        prev_json = None
        if prev:
            extract_cpu.OUT = OUT / 'prev'; (OUT / 'prev').mkdir(exist_ok=True)
            extract_cpu.run(sym, prev, fy=2023, sector=c['sector'])
            extract_cpu.OUT = OUT
            prev_json = OUT / 'prev' / f'{sym}.json'
        tabs = gate.gate(OUT / f'{sym}.json', HERE / 'xbrl_tie' / f'{sym}.json', prev_json)
        paras = yoy.diff(c['pdf'], prev)
        fam = {p['page']: p['family'] for p in o['pages']}
        lex = LEXICON_FIN if c['sector'] == 'Financial Services' else LEXICON
        statutory = {'auditor', 'caro', 'cag', 'secretarial'}
        doc = pymupdf.open(c['pdf'])
        STAT = re.compile(r"independent auditor|auditor'?s report|comptroller and auditor|secretarial audit|companies \(auditor'?s report\) order", re.I)
        stat_pages = {i + 1 for i in range(len(doc)) if STAT.search(doc[i].get_text()[:1500])}
        cand = [p for p in paras if fam.get(p['page']) != 'agm']
        tierA = [p for p in cand if p['novelty'] >= 0.4 and (p['page'] in stat_pages or lex.search(p['text']) or AUDIT_TRIGGERS.search(p['text']))]
        tierB = tierA + [p for p in cand if p not in tierA and p['novelty'] >= 0.6 and fam.get(p['page']) in ('notes', 'directors') and len(p['text']) >= 300]
        sl = tierB
        totals['tierA'] += sum(len(p['text']) for p in tierA)
        slice_chars = sum(len(p['text']) for p in sl)
        st = Counter(t['status'] for t in tabs); cells = Counter()
        for t in tabs:
            cells[t['status']] += t['ok_cells']; cells['send_to_llm'] += t['cells'] - t['ok_cells'] if t['status'] != 'send_to_llm' else 0
            if t['status'] == 'send_to_llm': cells['send_to_llm'] += t['cells']
        llm_tab_chars = 0
        rows_by = {(p['page'], r.get('block')): r for p in o['pages'] for r in p['rows'] if r.get('via') == 'columns'}
        for t in tabs:
            if t['status'] == 'send_to_llm': llm_tab_chars += t['cells'] * 40
        allc = sum(p['chars'] for p in o['pages'])
        nt = len(tabs) or 1
        lines.append(f"| {sym} | {time.time() - t0:.0f} | {tie['n_hits'].get('standalone', 0)}/{tie['n_xbrl_facts'].get('standalone', 0)} · "
                     f"{tie['n_hits'].get('consolidated', 0)}/{tie['n_xbrl_facts'].get('consolidated', 0)} | "
                     f"{st['cpu_ok']/nt:.0%} / {st['stored_unchecked']/nt:.0%} / {st['send_to_llm']/nt:.0%} of {len(tabs)} | "
                     f"{(cells['cpu_ok'] + cells['stored_unchecked']) / max(1, sum(cells.values())):.0%} | "
                     f"{slice_chars/allc:.1%} (~{slice_chars/3800:.0f} pp) | ~{llm_tab_chars/3800:.0f} pp | {'FY23 AR' if prev else 'none'} |")
        print(lines[-1], flush=True)
        totals['allc'] += allc; totals['slice'] += slice_chars; totals['tabllm'] += llm_tab_chars; totals['n'] += 1
        for k in ('cpu_ok', 'stored_unchecked', 'send_to_llm'): totals[k] += cells[k]
        ok_blocks = {(t['page'], t['block']) for t in tabs if t['status'] == 'cpu_ok'}
        ok_rows = [(p['page'], r) for p in o['pages'] for r in p['rows'] if r.get('via') == 'columns' and (p['page'], r.get('block')) in ok_blocks and r.get('value') is not None and gate.storable(r)]
        for pg, r in random.sample(ok_rows, min(3, len(ok_rows))):
            sample.append((sym, c['pdf'], pg, r))
        # must-find recall on the study reports
        for m in [m for m in must if m['symbol'] == sym]:
            near = {m['page'] - 1, m['page'], m['page'] + 1}
            txt = ' '.join(p['text'] for p in sl if p['page'] in near).lower()
            if m['kind'] == 'prose':
                res = 'LLM slice' if all(k.lower() in txt for k in m['keywords']) else 'MISSED'
            else:
                v = m['value']
                hit = [(t, r) for t in tabs if t['page'] in near for (pg, b), r in [((t['page'], t['block']), None)]]
                in_ok = any(norm(r['values'][0]) == v for p in o['pages'] if p['page'] in near for r in p['rows']
                            if r.get('via') == 'columns' and (p['page'], r.get('block')) in ok_blocks)
                in_rows = any(norm(r['values'][0]) == v for p in o['pages'] if p['page'] in near for r in p['rows'] if r.get('via') == 'columns')
                res = 'cpu_ok table' if in_ok else 'table to LLM/unchecked' if in_rows else ('LLM slice' if v in txt.replace(',', '') else 'MISSED')
            must_res.append(f"| {m['id']} | {sym} | {m['what']} | {res} |")
    n = sum(totals[k] for k in ('cpu_ok', 'stored_unchecked', 'send_to_llm')) or 1
    lines.append(f"\n**All 13:** cells in cpu_ok tables {totals['cpu_ok']/n:.0%}, stored unchecked {totals['stored_unchecked']/n:.0%}, "
                 f"to LLM {totals['send_to_llm']/n:.0%}. LLM slice: new prose {totals['slice']/totals['allc']:.1%} of characters (flagged-only tier {totals['tierA']/totals['allc']:.1%}) "
                 f"(~{totals['slice']/totals['n']/3800:.0f} page-equivalents per report) + failed tables ~{totals['tabllm']/totals['n']/3800:.0f} pp per report.\n")
    lines += ['\n## Must-find signals (study reports)\n', '| id | report | item | where it ends up |', '|---|---|---|---|'] + must_res
    lines += ['\n## Random cpu_ok rows (check against the page)\n', '| report | page | label | column | period | unit | value | on page? |', '|---|---|---|---|---|---|---|---|']
    for sym, pdf, pg, r in sample:
        t = pymupdf.open(pdf)[pg - 1].get_text()
        line_ok = any(r['values'][0] in l and r['label'].split()[0][:6].lower() in l.lower() for l in t.splitlines()) if r['label'].split() else False
        lines.append(f"| {sym} | {pg} | {r['label'][:60]} | {r['column'][:40]} | {r['period']} | {r['unit']} | {r['values'][0]} | {'yes' if r['values'][0] in t else 'NO'} |")
    (HERE / 'step4_report.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines[-(len(sample) + len(must_res) + 8):]))


def norm(s):
    return s.replace(',', '').replace('(', '').replace(')', '').replace('%', '').strip().lstrip('-')


if __name__ == '__main__':
    main()
