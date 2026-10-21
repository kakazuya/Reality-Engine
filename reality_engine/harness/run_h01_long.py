"""Declared longer-horizon H01 grid; separate outputs, same shared harness.

python -m reality_engine.harness.run_h01_long --placebo-draws 499
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from .adapter import inspect, load_tax, load_indexes, load_filings, Panel, Quotes, ADTV
from .benchmark import B5Path
from .book import run_book
from .cards.h01_pead import TIMINGS
from .data import ROOT, Snapshot
from .ledger import previous_tests, append_variants, append_run_note
from .run_h01 import Evaluator, clean, summarize_arrays, coverage, code_provenance, progress
from .stats import bh_fdr, student_p

OUT = ROOT/'tasks/backtests'
HORIZONS = (90,120,180,252,504)
ALL_HORIZONS = (20,60)+HORIZONS
COHORTS = ('any','abs_ge_1','abs_ge_2','abs_ge_2_trend200')
VARIANTS = tuple({'entry_timing':timing,'horizon':h,'measure':measure,'sign':sign,
                  'cohort':cohort,'sample':'available_horizon'}
                 for timing in TIMINGS for h in HORIZONS for measure in ('PAT','revenue')
                 for sign in ('positive','negative') for cohort in COHORTS) + tuple(
    {'entry_timing':'both_known_next_open','horizon':h,'measure':'PAT','sign':'positive',
     'cohort':cohort,'sample':'common_504'}
    for h in ALL_HORIZONS for cohort in ('any','abs_ge_2_trend200'))


def label(params):
    return '|'.join(str(params[key]) for key in ('sample','entry_timing','measure','sign','cohort','horizon'))


def cohort_mask(scores, trends, params):
    positive = params['sign']=='positive'
    keep = scores>0 if positive else scores<0
    cohort = params['cohort']
    if cohort!='any':
        keep &= np.abs(scores) >= (1 if cohort=='abs_ge_1' else 2)
    if cohort=='abs_ge_2_trend200':
        keep &= trends==(1 if positive else -1)
    return keep


def horizon_hac(values, entries, days, horizon):
    """Monthly equal-weight mean with exact-calendar-lag Newey-West SE.

    Missing event months stay missing. Require >2 bandwidths of observed
    months; otherwise return p=1/insufficient support, never false precision.
    """
    bandwidth = int(np.ceil(horizon/21))
    frame = pd.DataFrame({'month':days[entries].astype('datetime64[M]').astype(int),'value':values})
    monthly = frame.groupby('month').value.mean()
    n = len(monthly)
    out = {'bandwidth_months':bandwidth,'observed_months':n,'p':1.,'t':None,
           'mean':float(monthly.mean()) if n else None,'sufficient_support':False,
           'method':'equal-weight observed monthly cohorts; Bartlett horizon-lag HAC; no missing-month zero imputation'}
    if n<=max(12,2*bandwidth+1):
        return out
    months = monthly.index.to_numpy()
    z = monthly.to_numpy()-monthly.mean()
    lookup = dict(zip(months,z))
    lrv = float(z@z)/n
    for lag in range(1,bandwidth+1):
        gamma = sum(z[k]*lookup.get(month-lag,0.) for k,month in enumerate(months))/n
        lrv += 2*(1-lag/(bandwidth+1))*gamma
    se = np.sqrt(max(0.,lrv)/(n-1))
    out['sufficient_support'] = True
    if se>0:
        out['t'] = out['mean']/se
        out['p'] = student_p(out['t'],n-1)
    return out


class LongEvaluator(Evaluator):
    def __init__(self, records, panel, benchmark, rules):
        super().__init__(records,panel,benchmark,rules,horizons=ALL_HORIZONS)
        sma = pd.DataFrame(panel.close).rolling(200,min_periods=200).mean().to_numpy()
        valid = np.isfinite(panel.close)&np.isfinite(sma)&(panel.close>0)&(sma>0)
        self.trend = np.where(valid,np.sign(panel.close-sma),0).astype(np.int8)

    def evaluate(self, stamps=None, *, detailed=False):
        p = self.panel
        stamps = self.original if stamps is None else stamps
        available = stamps+self.lag
        meta = {timing:self.timing_meta(stamps,available,timing) for timing in TIMINGS}
        cache = {}
        for timing, block in meta.items():
            entries = block['entry_indices']
            signals = block['signal_indices']
            for horizon in ALL_HORIZONS:
                ids = np.flatnonzero(block['qualified']&(entries+horizon<len(p.days)))
                cols = self.columns[ids]
                returns = self.returns(entries[ids],cols,horizon)
                cache[timing,horizon] = {**returns,'ids':ids,
                    'trends':self.trend[signals[ids],cols],
                    'scores':self.scores[ids], 'decision_stamps':block['decision_stamps'][ids]}
        stats, selections = [], []
        for params in VARIANTS:
            data = cache[params['entry_timing'],params['horizon']]
            m = 0 if params['measure']=='PAT' else 1
            keep = cohort_mask(data['scores'][:,m],data['trends'],params)
            if params['sample']=='common_504':
                keep &= data['entry_indices']+504<len(p.days)
            values, entries = data['excess'][keep],data['entry_indices'][keep]
            row = summarize_arrays(values,entries,self.benchmark.regime_up[entries],p.days,detailed=detailed)
            row['params'] = dict(params)
            if detailed:
                gross, net, b5 = data['gross'][keep],data['net'][keep],data['b5_net'][keep]
                exits = data['exit_indices'][keep]
                holding = (p.days[exits]-p.days[entries]).astype('timedelta64[D]').astype(int)
                ids = data['ids'][keep]
                hac = horizon_hac(values,entries,p.days,params['horizon'])
                row.update({'cluster_p':row['p'],'hac':hac,'p':max(row['p'],hac['p']),
                    'mean_gross_stock':float(gross.mean()) if len(values) else None,
                    'mean_net_stock':float(net.mean()) if len(values) else None,
                    'mean_net_b5':float(b5.mean()) if len(values) else None,
                    'positive_excess_fraction':float(np.mean(values>0)) if len(values) else None,
                    'unique_issuers':len({self.records[k]['entity'] for k in ids}),
                    'entry_years':sorted(set(p.days[entries].astype('datetime64[Y]').astype(int)+1970)),
                    'ltcg_events':int(np.sum(holding>365)),
                    'delayed_exits':int(np.sum(data['exit_delay'][keep]>0)),
                    'unresolved_exits':int(np.sum(data['missing_exit'][keep]))})
                selections.append((params, data, keep))
            stats.append(row)
        return (stats,selections,meta,cache) if detailed else stats

    def placebos(self, observed, draws=499, seed=20261021):
        rng = np.random.default_rng(seed)
        means = np.full((draws,len(VARIANTS)),np.nan)
        counts = np.zeros((draws,len(VARIANTS)),dtype=np.int32)
        max_t = np.zeros(draws)
        for draw in range(draws):
            shuffled = self.original.copy()
            for ids in self.month_groups:
                shuffled[ids] = rng.permutation(shuffled[ids])
            rows = self.evaluate(shuffled)
            for i,row in enumerate(rows):
                if row['mean_net_excess'] is not None:
                    means[draw,i] = row['mean_net_excess']
                counts[draw,i] = row['n_events']
            max_t[draw] = max((abs(row['t_stat']) for row in rows if row['t_stat'] is not None),default=0.)
            if (draw+1)%25==0:
                progress(f'long-grid placebo {draw+1}/{draws}')
        for i,row in enumerate(observed):
            valid = means[:,i][np.isfinite(means[:,i])]
            desired = 1 if row['params']['sign']=='positive' else -1
            mu, t = row['mean_net_excess'],row['t_stat']
            row['placebo_p'] = float((1+np.sum(np.abs(valid)>=abs(mu)))/(1+len(valid))) if mu is not None and len(valid) else 1.
            row['placebo_directional_p'] = float((1+np.sum(valid*desired>=mu*desired))/(1+len(valid))) if mu is not None and len(valid) else 1.
            row['reality_check_p'] = float((1+np.sum(max_t>=abs(t)))/(1+draws)) if t is not None else 1.
            row['placebo'] = {'draws':draws,'valid_draws':len(valid),'mean_distribution':means[:,i],
                'n_event_distribution':counts[:,i],
                'quantiles':np.quantile(valid,[.025,.5,.975]) if len(valid) else None}
        return {'seed':seed,'draws':draws,'max_abs_t_distribution':max_t,
                'method':'within-month timestamp permutation; preserve XBRL lag; recompute PIT/U1/trend/entry/exit; current174-grid maxT'}


def outcome_frame(evaluator, cache):
    """Store each timing/horizon/issuer-quarter once; cohorts are reproducible."""
    p = evaluator.panel
    frames = []
    for (timing,horizon), data in cache.items():
        ids, en, ex = data['ids'],data['entry_indices'],data['exit_indices']
        frames.append(pd.DataFrame({
            'entry_timing':timing,'horizon':horizon,'record_id':ids,
            'entity':[evaluator.records[i]['entity'] for i in ids],
            'file':[evaluator.records[i]['file'] for i in ids],
            'trigger':[evaluator.records[i]['trigger'] for i in ids],
            'xbrl_at':[evaluator.records[i]['xbrl_at'] for i in ids],
            'decision_trigger':data['decision_stamps'],
            'entry':p.days[en],'scheduled_exit':p.days[data['scheduled_exit_indices']],
            'exit':p.days[ex],'entry_index':en,'exit_index':ex,
            'entry_price':p.open[en,evaluator.columns[ids]],
            'PAT_surprise':data['scores'][:,0],'revenue_surprise':data['scores'][:,1],
            'trend200':data['trends'],'gross_return':data['gross'],'stock_net':data['net'],
            'b5_net':data['b5_net'],'net_excess':data['excess'],
            'unresolved_exit':data['missing_exit'],'exit_delay_sessions':data['exit_delay'],
            'common_504':en+504<len(p.days)}))
    return pd.concat(frames,ignore_index=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placebo-draws',type=int,default=499)
    args = parser.parse_args(argv)
    if args.placebo_draws<499:
        parser.error('At least499 declared draws required')
    started = perf_counter()
    if (OUT/'H01_long_results.json').exists():
        raise FileExistsError('Preserve the completed long-grid run before another run; no silent overwrite')
    progress('long-grid: read-only snapshot and schema inspection')
    with Snapshot() as snapshot:
        before = snapshot.path.stat()
        c = snapshot.connection
        c.execute('SET threads=2')
        c.execute("SET memory_limit='3GB'")
        inspect(c)
        rules = load_tax(c)
        records,audit = load_filings(c)
        panel = Panel(c)
        benchmark = B5Path(load_indexes(c),panel.calendar,rules)
        evaluator = LongEvaluator(records,panel,benchmark,rules)
        rows,selections,meta,cache = evaluator.evaluate(detailed=True)
        prior = previous_tests()
        qs = bh_fdr([p for _,p in prior]+[row['p'] for row in rows])[-len(rows):]
        for row,q in zip(rows,qs):
            row['bh_q'] = q
        progress(f'long-grid: {len(rows)} declared variants; starting placebos')
        placebo = evaluator.placebos(rows,args.placebo_draws)
        nav,_ = benchmark.book_nav()
        books = {}
        progress('long-grid: constrained positive books')
        with gzip.open(OUT/'H01_long_books.jsonl.gz','wt',encoding='utf-8') as book_audit:
            for row,(params,data,keep) in zip(rows,selections):
                if params['sign']=='positive':
                    en = data['entry_indices'][keep]
                    scheduled = data['scheduled_exit_indices'][keep]
                    ids = data['ids'][keep]
                    events = [{'isin':records[i]['entity'],'entry':panel.calendar.days[a],
                               'exit':panel.calendar.days[b],'sign':'positive'} for i,a,b in zip(ids,en,scheduled)]
                    book = run_book(events,panel.calendar,Quotes(panel),ADTV(panel),rules,nav)
                    book_audit.write(json.dumps(clean({'variant':label(params),**book}),allow_nan=False)+'\n')
                    books[label(params)] = {key:value for key,value in book.items() if key not in ('nav','fills')}
                    books[label(params)]['n_fills'] = len(book['fills'])
                desired = 1 if params['sign']=='positive' else -1
                yearly = [v['mean'] for v in row['per_year'].values() if v['mean'] is not None]
                proof = {'bh_q_le_005':row['bh_q']<=.05,
                         'directional_placebo_le_005':row['placebo_directional_p']<=.05,
                         'maxT_le_005':row['reality_check_p']<=.05,
                         'hac_supported_and_p_le_005':row['hac']['sufficient_support'] and row['hac']['p']<=.05,
                         'four_years_expected_sign':len(yearly)>=4 and all(v*desired>0 for v in yearly),
                         'both_regimes_expected_sign':all(v['n']>=30 and v['mean'] is not None and v['mean']*desired>0
                                                           for v in row['regimes'].values()),
                         'no_unresolved_exits':row['unresolved_exits']==0}
                if params['sign']=='positive':
                    book = books[label(params)]
                    proof['book_outperforms_without_kill'] = book['excess_cagr']>0 and book['kill_date'] is None and not book['unresolved_holdings']
                row['proof_checks'] = proof
                row['status'] = 'provisional_pass' if all(proof.values()) else 'fail'
                row['promoted'] = False
        outcomes = outcome_frame(evaluator,cache)
        outcomes.to_csv(OUT/'H01_long_outcomes.csv.gz',index=False,compression='gzip')
        git_hash,hashes = code_provenance()
        test_path = ROOT/'reality_engine/tests/test_harness_h01_long.py'
        hashes[str(test_path.relative_to(ROOT)).replace('\\','/')] = hashlib.sha256(test_path.read_bytes()).hexdigest()
        cov = {timing:coverage(panel,records,block) for timing,block in meta.items()}
        plan = ROOT/'tasks/codex_tasks/H01_LONG_HORIZON_PLAN_2026-10-21.md'
        tests = json.loads((OUT/'H01_long_tests.json').read_text(encoding='utf-8'))
        result = clean({'card_id':'H01','exploration':'long_horizons_and_strength','variants':rows,'books':books,
            'evidence_window':['2021-01-01','2025-12-31'],'snapshot_name':snapshot.path.name,'snapshot_read_only':True,
            'run_timestamp_utc':datetime.now(timezone.utc).isoformat(),'git_head':git_hash,'source_sha256':hashes,
            'declared_plan_sha256':hashlib.sha256(plan.read_bytes()).hexdigest(),'coverage_by_timing':cov,
            'fdr_scope':{'current_variants':len(rows),'prior_ledger_tests':len(prior),'total_tests':len(rows)+len(prior),
                         'prior_run_ids':sorted({run for run,p in prior})},
            'placebo':placebo,'panel_audit':panel.audit,'filing_audit':audit,'benchmark_choices':benchmark.choices,
            'audit_outcomes_rows':len(outcomes),'test_results':tests,'promoted':False,'provisional':True,
            'full_data_completeness_gate_met':False,
            'limits':['2021 lacks sufficient12-quarter history; long horizons shorten entry coverage',
                '504-session evidence has too few independent years/months for promotion',
                'B5 previous-close proxy; derived BSE TRI; snapshot base tax, no personal cess/surcharge/dividend tax',
                'fixed thresholds declared after prior20/60 results; exploratory, all tests retained',
                'month-cluster SE plus conservative horizon-lag monthly HAC; extensive overlapping outcomes',
                'prior200 total-return-close trend, known completed sessions only; no fit thresholds']})
        run_id = append_variants(result['variants'],snapshot=snapshot.path.name,git_hash=git_hash,
                                 coverage=result['coverage_by_timing'],source_hashes=hashes)
        result['ledger_run_id'] = run_id
        append_run_note(run_id,json.dumps({'method':'H01_LONG_HORIZON_PLAN_2026-10-21.md',
            'tests':len(rows),'fdr_p':'max(entry-month cluster p, horizon-lag monthly HAC p)',
            'prior_runs_retained':result['fdr_scope']['prior_run_ids']}))
        after = snapshot.path.stat()
        result['snapshot_file_unchanged'] = (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
        if not result['snapshot_file_unchanged']:
            raise RuntimeError('Source snapshot changed')
        result['elapsed_seconds'] = perf_counter()-started
        (OUT/'H01_long_results.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
        write_report(result)
    progress(f'long-grid finished: {run_id}; {result["elapsed_seconds"]:.1f}s')


def write_report(r):
    pct = lambda x:'NA' if x is None else f'{100*x:.2f}%'
    num = lambda x:'NA' if x is None else f'{x:.3g}'
    rows = r['variants']
    lines = ['# H01 longer horizons and signal strength — provisional','',
        'This is an extension of H01, not a culling decision. No variant is promoted.', '',
        f"Run `{r['ledger_run_id']}`. {len(rows)} declared tests; BH family {r['fdr_scope']['total_tests']} including all prior {r['fdr_scope']['prior_ledger_tests']} tests.",
        'Evidence2021–2025; warm-up2019–2020; no2026 outcomes. Source snapshot read-only.', '',
        '## Both-known positive PAT: longer holding periods', '',
        '| Sessions | Cohort | Events | Issuers | Mean net excess | Median | Positive excess | Cluster p | HAC p | BH q | Directional placebo p | Max-T p | Years | Book CAGR | Kill |',
        '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|']
    for row in rows:
        p = row['params']
        if p['sample']=='available_horizon' and p['entry_timing']=='both_known_next_open' and p['measure']=='PAT' and p['sign']=='positive':
            b = r['books'][label(p)]
            lines.append(f"| {p['horizon']} | {p['cohort']} | {row['n_events']} | {row['unique_issuers']} | {pct(row['mean_net_excess'])} | {pct(row['median_net_excess'])} | {pct(row['positive_excess_fraction'])} | {num(row['cluster_p'])} | {num(row['hac']['p'])} | {num(row['bh_q'])} | {num(row['placebo_directional_p'])} | {num(row['reality_check_p'])} | {','.join(map(str,row['entry_years']))} | {pct(b['allocation_cagr'])} | {b['kill_date'] or 'none'} |")
    lines += ['', 'any means nonzero positive surprise; abs_ge_1/2 mean fixed standardized surprise thresholds; abs_ge_2_trend200 adds prior-known close above200-session SMA.', '',
        '## Same early entries, different horizons', '',
        'All entries have room for504 sessions before2025 ends. Positive PAT, both-known timing. These14 tests are included in BH and max-T.', '',
        '| Cohort | Sessions | Events | Mean gross stock | Mean net stock | Mean net B5 | Mean excess | Median excess | BH q |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        p = row['params']
        if p['sample']=='common_504':
            lines.append(f"| {p['cohort']} | {p['horizon']} | {row['n_events']} | {pct(row['mean_gross_stock'])} | {pct(row['mean_net_stock'])} | {pct(row['mean_net_b5'])} | {pct(row['mean_net_excess'])} | {pct(row['median_net_excess'])} | {num(row['bh_q'])} |")
    lines += ['', '## Full declared grid', '',
        '| Sample / timing / measure / sign / cohort / sessions | Events | Mean excess | Median | BH q | Directional placebo | Max-T | 2021/22/23/24/25 |',
        '|---|---:|---:|---:|---:|---:|---:|---|']
    for row in rows:
        signs = '/'.join(row['per_year_signs'].get(str(y)) or 'NA' for y in range(2021,2026))
        lines.append(f"| {label(row['params']).replace('|',' / ')} | {row['n_events']} | {pct(row['mean_net_excess'])} | {pct(row['median_net_excess'])} | {num(row['bh_q'])} | {num(row['placebo_directional_p'])} | {num(row['reality_check_p'])} | {signs} |")
    lines += ['', '## All positive books', '',
        'Each alternative uses a Rs10lakh sleeve inside Rs1crore, equal weight on admissions, liquidity cap and the unchanged8% drawdown kill. Killed books remain in cash. Event returns separately show the unmanaged signal through its declared horizon.', '',
        '| Variant | Sleeve CAGR | B5 CAGR | Excess CAGR | Max DD | Kill | Fills |',
        '|---|---:|---:|---:|---:|---|---:|']
    for name,b in r['books'].items():
        lines.append(f"| {name.replace('|',' / ')} | {pct(b['allocation_cagr'])} | {pct(b['b5_cagr'])} | {pct(b['excess_cagr'])} | {pct(b['max_drawdown'])} | {b['kill_date'] or 'none'} | {b['n_fills']} |")
    lines += ['', '## Coverage', '',
        '| Timing | Year | U1 ISINs | Results covered | Usable history | Known by entry |',
        '|---|---:|---:|---:|---:|---:|']
    for timing,table in r['coverage_by_timing'].items():
        for row in table:
            lines.append(f"| {timing} | {row['year']} | {row['u1_isins']} | {row['financial_covered_isins']} | {row['usable_surprise_history_isins']} | {row['known_by_entry_isins']} |")
    lines += ['', '## Statistical and data limits', '',
        'The ledger p is the larger of entry-month-clustered p and monthly cohort HAC p. HAC uses ceil(horizon/21) calendar-month lags and refuses precision unless observed months exceed twice that bandwidth plus one. Missing event months are not imputed to zero.',
        'Directional placebo compares each effect with shuffled effects in the claimed direction. Max-T covers all174 current tests. BH also retains earlier tests. A positive mean alone does not prove an earnings-specific effect.',
        'Four entry years with the expected sign, both market regimes, sufficient HAC support, statistical controls and an outperforming surviving book are required for a provisional pass; full data completeness is additionally required for promotion.', '']
    lines += [f'- {s}' for s in r['limits']]
    lines += ['', '## Verification and reproduction', '',
        f"Tests: {r['test_results']['total_tests']} passed. Compressed audit has {r['audit_outcomes_rows']} unique timing/horizon/issuer-quarter outcomes; book paths/fills are separately compressed.",
        'The verification JSON independently rebuilds cohort memberships, source timestamps/prices, returns, tax, counts, BH and book risk outcomes.',
        '`python -m reality_engine.harness.run_h01_long --placebo-draws 499`',
        '`python -m reality_engine.harness.verify_h01_long`',
        f"Runtime {r['elapsed_seconds']:.1f}s. Snapshot unchanged: {r['snapshot_file_unchanged']}. No commit/push/upload."]
    (OUT/'H01_long_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
