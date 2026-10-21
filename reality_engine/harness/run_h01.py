"""Run H01's eight variants under both reviewed PIT timing policies.

python -m reality_engine.harness.run_h01 --placebo-draws 499
No live database, network, package installation, or git mutation is used.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
from time import perf_counter

import numpy as np
import pandas as pd

from .adapter import inspect, load_tax, load_indexes, load_filings, Panel, Quotes, ADTV
from .benchmark import B5Path
from .book import run_book
from .cards.h01_pead import VARIANTS, TIMINGS, quarter_back, descriptive_quintiles
from .costs_tax import short_term_net, sale
from .data import ROOT, Snapshot
from .execution import next_close_indices
from .ledger import append_variants, previous_tests, append_run_note
from .stats import bh_fdr, student_p

OUT = ROOT / 'tasks/backtests'


def progress(message):
    print(datetime.now(timezone.utc).isoformat(timespec='seconds'), message, flush=True)


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k,v in value.items()}
    if isinstance(value, (tuple,list)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.floating,float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (date,datetime,np.datetime64)):
        return str(value)
    return value


def summarize_arrays(values, entries, regimes, days, *, detailed=False):
    n = len(values)
    mu = float(np.mean(values)) if n else None
    out = {'n_events': n, 'mean_net_excess': mu,
           'median_net_excess': float(np.median(values)) if n else None,
           't_stat': None, 'p': 1., 'n_month_clusters': 0}
    months = days[entries].astype('datetime64[M]').astype(int) if n else np.array([],dtype=int)
    if n > 1:
        _, groups = np.unique(months, return_inverse=True)
        g = int(groups.max())+1
        out['n_month_clusters'] = g
        if g > 1:
            sums = np.bincount(groups, weights=values-mu)
            se = float(np.sqrt(g/(g-1)*np.sum(sums*sums))/n)
            if se > 0:
                out['t_stat'] = mu/se
                out['p'] = student_p(mu/se,g-1)
    if detailed:
        years = days[entries].astype('datetime64[Y]').astype(int)+1970
        out['per_year'] = {}
        out['per_year_signs'] = {}
        for year in range(2021,2026):
            vals = values[years==year]
            avg = float(vals.mean()) if len(vals) else None
            out['per_year'][str(year)] = {'n':len(vals),'mean':avg}
            out['per_year_signs'][str(year)] = None if avg is None else '+' if avg>0 else '-' if avg<0 else '0'
        out['regimes'] = {}
        for up in (True,False):
            vals = values[regimes==up]
            out['regimes']['up' if up else 'down'] = {'n':len(vals),'mean':float(vals.mean()) if len(vals) else None}
    return out


class Evaluator:
    """One vectorized real/placebo path. No outcomes used to form surprises.

    Fixed first-file values and prior-quarter indices are cached. Every draw
    recomputes their availability, signal/entry date, U1 gate and returns.
    Therefore moving a filing earlier cannot expose unavailable history.
    """
    def __init__(self, records, panel, benchmark, rules, *, horizons=(20,60)):
        self.records, self.panel, self.benchmark = records, panel, benchmark
        self.rules = rules
        self.next_close = next_close_indices(panel.close)
        self.benchmark_cache = {}
        n, t = len(records), len(panel.days)
        self.original = np.array([r['trigger'] for r in records],dtype='datetime64[us]')
        self.lag = np.array([max(r['xbrl_at']-r['trigger'],datetime.min-datetime.min)
                             for r in records],dtype='timedelta64[us]')
        self.has_bse = np.array([r['trade_trigger'] is not None for r in records])
        self.columns = np.array([panel.col.get(r['entity'],-1) for r in records])
        lookup = {(r['entity'],r['period_end']):i for i,r in enumerate(records)}
        self.history = np.full((n,12),-1,dtype=np.int32)
        self.scores = np.full((n,2),np.nan)
        for i, row in enumerate(records):
            history = [lookup.get((row['entity'],quarter_back(row['period_end'],k)),-1)
                       for k in range(1,13)]
            self.history[i] = history
            if min(history) < 0:
                continue
            past = [records[k] for k in history]
            if any(r['basis_family'] != row['basis_family'] for r in past):
                continue
            for m, measure in enumerate(('PAT','revenue')):
                if measure == 'revenue' and any(r['revenue_metric'] != row['revenue_metric'] for r in past):
                    continue
                values = [r[measure] for r in past]
                if row[measure] is None or any(v is None for v in values):
                    continue
                values = np.array(values)
                sd = np.std(values[:8]-values[4:12],ddof=1)
                if np.isfinite(sd) and sd>0:
                    self.scores[i,m] = (row[measure]-values[3])/sd
        self.has_pat = np.array([r['PAT'] is not None for r in records])
        self.tax_rates = np.array([rules.rule('stcg_rate',d) for d in panel.calendar.days])
        self.lt_tax_rates = np.array([rules.rule('ltcg_rate',d) for d in panel.calendar.days])
        self.b5 = {}
        for horizon in horizons:
            out = np.full(t,np.nan)
            for entry in range(t):
                if panel.calendar.days[entry].year>=2021 and entry+horizon<t:
                    out[entry] = benchmark.event_return(entry,entry+horizon)
            self.b5[horizon] = out
        self.month_groups = [np.flatnonzero(self.original.astype('datetime64[M]')==m)
                             for m in np.unique(self.original.astype('datetime64[M]'))]

    def timing_meta(self, stamps, available, timing):
        p = self.panel
        decision = stamps if timing == 'bse_next_open' else available
        signals, entries = p.signal_indices(decision), p.entry_indices(decision)
        safe_signal = np.clip(signals, 0, len(p.days)-1)
        safe_entry = np.clip(entries, 0, len(p.days)-1)
        cols = np.maximum(self.columns, 0)
        entry_open = p.days[safe_entry].astype('datetime64[us]')+np.timedelta64(555, 'm')
        gate = (self.has_bse & self.has_pat & (self.columns >= 0) & (signals >= 0)
                & (entries < len(p.days)) & (decision >= np.datetime64('2021-01-01'))
                & (decision < np.datetime64('2026-01-01'))
                & (stamps >= np.datetime64('2021-01-01')))
        gate &= p.u1[safe_signal, cols]
        prior = available[np.maximum(self.history, 0)]
        prior_ok = (np.min(self.history, axis=1) >= 0) & np.all(prior < decision[:, None], axis=1)
        prior_ok &= np.any(np.isfinite(self.scores), axis=1)
        known_by_open = available < entry_open
        op = p.open[safe_entry, cols]
        entry_ok = np.isfinite(op) & (op > 0)
        qualified = gate & prior_ok & known_by_open & entry_ok
        audit = {'bse_pat_u1_events': int(gate.sum()),
                 'insufficient_or_late_history': int((gate & ~prior_ok).sum()),
                 'current_values_after_next_open': int((gate & prior_ok & ~known_by_open).sum()),
                 'known_history_and_current_before_open': int(qualified.sum()),
                 'missing_entry_open': int((gate & prior_ok & known_by_open & ~entry_ok).sum()),
                 'current_xbrl_after_bse_trigger': int((gate & (self.lag > np.timedelta64(0, 's'))).sum())}
        return {'signal_indices': signals, 'entry_indices': entries, 'decision_stamps': decision,
                'financial_gate': gate, 'history_gate': gate & prior_ok,
                'qualified': qualified, 'audit': audit}

    def returns(self, entries, columns, horizon):
        """Resolve genuine next quotes and match tax/B5 to the actual exit.

        No later quote through the evidence boundary is an unresolved recovery
        bound, never a claimed delisting or executable zero-price sale.
        """
        p = self.panel
        scheduled = entries + horizon
        next_exit = self.next_close[scheduled, columns]
        missing = next_exit == len(p.days)
        exits = np.where(missing, len(p.days)-1, next_exit)
        close = p.close[exits, columns]
        gross = np.where(missing, 0., close) / p.open[entries, columns] - 1
        long = (p.days[exits]-p.days[entries]).astype('timedelta64[D]').astype(int) > 365
        # Events claim no annual personal LTCG allowance. The book tracks it
        # across actual sales. Use calendar holding days, never session count.
        net = short_term_net(gross, np.where(long,self.lt_tax_rates[exits],self.tax_rates[exits]))
        bench = self.b5[horizon][entries].copy()
        for k in np.flatnonzero(exits != scheduled):
            pair = int(entries[k]), int(exits[k])
            if pair not in self.benchmark_cache:
                self.benchmark_cache[pair] = self.benchmark.event_return(*pair)
            bench[k] = self.benchmark_cache[pair]
        return {'entry_indices': entries, 'exit_indices': exits, 'scheduled_exit_indices': scheduled,
                'gross': gross, 'net': net, 'excess': net-bench, 'b5_net': bench,
                'missing_exit': missing, 'exit_delay': exits-scheduled}

    def evaluate(self, stamps=None, *, detailed=False):
        p = self.panel
        stamps = self.original if stamps is None else stamps
        available = stamps+self.lag
        by_timing = {timing: self.timing_meta(stamps, available, timing) for timing in TIMINGS}
        stats, event_sets = [], []
        for params in VARIANTS:
            meta = by_timing[params['entry_timing']]
            entries = meta['entry_indices']
            scores = self.scores[:, 0 if params['measure'] == 'PAT' else 1]
            direction = scores > 0 if params['sign'] == 'positive' else scores < 0
            ids = np.flatnonzero(meta['qualified'] & direction & (entries+params['horizon'] < len(p.days)))
            en, j = entries[ids], self.columns[ids]
            returns = self.returns(en, j, params['horizon'])
            ex = returns['exit_indices']
            row = summarize_arrays(returns['excess'], en, self.benchmark.regime_up[en], p.days, detailed=detailed)
            row['params'] = dict(params)
            if detailed:
                jumps = p.jump_prefix[ex+1, j]-p.jump_prefix[en, j]
                missing = returns['missing_exit']
                prev = p.close[np.maximum(en-1, 0), j]
                gaps = p.open[en, j]/prev-1
                valid_gaps = gaps[np.isfinite(gaps) & (prev > 0)]
                row.update({'missing_exit_total_loss_bounds': int(missing.sum()),
                            'delayed_exits_with_quote': int(np.sum((returns['exit_delay'] > 0) & ~missing)),
                            'max_exit_delay_sessions': int(returns['exit_delay'].max()) if len(en) else 0,
                            'events_crossing_truth_jump_flags': int(np.sum(jumps > 0)),
                            'mean_stock_net': float(returns['net'].mean()) if len(en) else None,
                            'mean_b5_net': float(returns['b5_net'].mean()) if len(en) else None,
                            'stock_entry_gap': {'n': len(valid_gaps),
                                                'mean': float(valid_gaps.mean()) if len(valid_gaps) else None,
                                                'median': float(np.median(valid_gaps)) if len(valid_gaps) else None},
                            'parsed_trigger_events': sum(self.records[k]['trigger_method'] == 'period_parsed' for k in ids)})
                event_sets.append({**returns, 'ids': ids, 'jump_flags': jumps,
                                   'decision_stamps': meta['decision_stamps'][ids], 'entry_gap': gaps})
            stats.append(row)
        if detailed:
            # Keep strict-timing keys for older callers; expose both explicitly.
            return stats, event_sets, {**by_timing[TIMINGS[0]], 'by_timing': by_timing}
        return stats

    def placebos(self, observed, draws=499, seed=20261020):
        rng = np.random.default_rng(seed)
        means = np.full((draws,len(VARIANTS)),np.nan)
        counts = np.zeros((draws,len(VARIANTS)),dtype=int)
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
            max_t[draw] = max((abs(r['t_stat']) for r in rows if r['t_stat'] is not None),default=0.)
            if (draw+1)%50==0:
                progress(f'placebo {draw+1}/{draws}')
        for i,row in enumerate(observed):
            valid = means[:,i][np.isfinite(means[:,i])]
            mu,tstat = row['mean_net_excess'],row['t_stat']
            row['placebo_p'] = float((1+np.sum(np.abs(valid)>=abs(mu)))/(1+len(valid))) if mu is not None and len(valid) else 1.
            desired = 1 if row['params']['sign'] == 'positive' else -1
            row['placebo_directional_p'] = float((1+np.sum(valid*desired >= mu*desired))/(1+len(valid))) if mu is not None and len(valid) else 1.
            row['reality_check_p'] = float((1+np.sum(max_t>=abs(tstat)))/(1+draws)) if tstat is not None else 1.
            row['placebo'] = {'draws':draws,'valid_draws':len(valid),'mean_distribution':means[:,i],
                              'n_event_distribution':counts[:,i],
                              'mean':float(valid.mean()) if len(valid) else None,
                              'sd':float(valid.std(ddof=1)) if len(valid)>1 else None,
                              'quantiles':np.quantile(valid,[.025,.5,.975]) if len(valid) else None}
        return {'seed':seed,'draws':draws,'max_abs_t_distribution':max_t,
                'method':'within-calendar-month permutation of filing timestamps; preserve XBRL lag; recompute PIT/U1/entry/returns'}

    def quintiles(self, meta, horizon, measure):
        """Descriptive grid includes zero surprises, outside the sign tests."""
        m = 0 if measure == 'PAT' else 1
        en = meta['entry_indices']
        keep = meta['qualified'] & np.isfinite(self.scores[:,m]) & (en+horizon<len(self.panel.days))
        ids = np.flatnonzero(keep)
        entries, exits, cols = en[ids],en[ids]+horizon,self.columns[ids]
        excess = self.returns(entries, cols, horizon)['excess']
        rows = [{measure+'_surprise':float(self.scores[i,m]),'net_excess':float(x)} for i,x in zip(ids,excess)]
        return descriptive_quintiles(rows,measure)


def coverage(panel, records, meta):
    out = []
    for year in range(2021,2026):
        days = np.array([d.year==year for d in panel.calendar.days])
        universe = set(panel.isin_code[days][panel.u1[days]].tolist())
        counts = []
        for name in ('financial_gate','history_gate','qualified'):
            keep = meta[name].copy()
            si = meta['signal_indices']
            trigger_year = np.array([r['trigger'].year for r in records])
            keep &= trigger_year==year
            ids = np.flatnonzero(keep)
            codes = {int(panel.isin_code[si[i],panel.col[records[i]['entity']]]) for i in ids}
            counts.append(len(codes&universe))
        out.append({'year':year,'u1_isins':len(universe),'financial_covered_isins':counts[0],
                    'usable_surprise_history_isins':counts[1],'known_by_entry_isins':counts[2],
                    'financial_coverage':counts[0]/len(universe) if universe else None,
                    'entry_coverage':counts[2]/len(universe) if universe else None,
                    'status':'provisional'})
    return out


def event_rows(params, event_set, records, panel):
    out = []
    for k,idx in enumerate(event_set['ids']):
        row = records[idx]
        en,ex = int(event_set['entry_indices'][k]),int(event_set['exit_indices'][k])
        col = panel.col[row['entity']]
        scheduled = int(event_set['scheduled_exit_indices'][k])
        out.append({'entry_timing':params['entry_timing'],
                    'horizon':params['horizon'],'measure':params['measure'],'sign':params['sign'],
                    'entity':row['entity'],'filing_trading_isin':row['trading_isin'],
                    'entry_isin':panel.actual_isin(en,col),'symbol':row['symbol'],
                    'file':row['file'],'basis':row['basis'],'period_end':row['period_end'],
                    'trigger':row['trigger'],'trigger_method':row['trigger_method'],
                    'decision_trigger':event_set['decision_stamps'][k],
                    'xbrl_at':row['xbrl_at'],'available_at':row['available_at'],
                    'entry':panel.calendar.days[en],'exit':panel.calendar.days[ex],
                    'scheduled_exit':panel.calendar.days[scheduled],
                    'exit_delay_sessions':int(event_set['exit_delay'][k]),
                    'bse_to_xbrl_lag_hours':max(0., (row['xbrl_at']-row['trigger']).total_seconds()/3600),
                    'stock_entry_gap':float(event_set['entry_gap'][k]),
                    'entry_open_tr':float(panel.open[en,col]),
                    'gross_return':float(event_set['gross'][k]),'stock_net':float(event_set['net'][k]),
                    'net_excess':float(event_set['excess'][k]),
                    'exit_missing_loss_bound':bool(event_set['missing_exit'][k]),
                    'truth_jump_flags':int(event_set['jump_flags'][k])})
    return out


def timing_diagnostics(evaluator, meta):
    out = {}
    for timing, block in meta['by_timing'].items():
        out[timing] = {}
        for gate in ('financial_gate', 'history_gate', 'qualified'):
            ids = np.flatnonzero(block[gate])
            hours = evaluator.lag[ids].astype('timedelta64[s]').astype(float)/3600
            original_entries = evaluator.panel.entry_indices(evaluator.original[ids])
            delay = block['entry_indices'][ids]-original_entries
            out[timing][gate] = {
                'n': len(ids), 'positive_lag_n': int(np.sum(hours > 0)),
                'lag_hours_quantiles_0_25_50_75_90_99_100': np.quantile(hours, [0,.25,.5,.75,.9,.99,1]) if len(ids) else None,
                'entry_delay_sessions_quantiles_0_50_90_99_100': np.quantile(delay, [0,.5,.9,.99,1]) if len(ids) else None}
    return out


def archive_previous_artifacts():
    path = OUT/'H01_results.json'
    if not path.exists():
        return None
    prior = json.loads(path.read_text(encoding='utf-8'))
    folder = OUT/'archive'/prior['ledger_run_id']
    folder.mkdir(parents=True, exist_ok=True)
    for name in ('H01_results.json', 'H01_report.md', 'H01_events.csv',
                 'H01_b5_monthly.csv', 'H01_verification.json'):
        source = OUT/name
        if source.exists() and not (folder/name).exists():
            shutil.copy2(source, folder/name)
    if prior.get('test_results') and not (folder/'H01_tests.json').exists():
        (folder/'H01_tests.json').write_text(json.dumps(prior['test_results'], indent=2)+'\n', encoding='utf-8')
    return str(folder.relative_to(ROOT)).replace('\\', '/')


def code_provenance():
    git_hash = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    files = sorted((ROOT/'reality_engine/harness').rglob('*.py'))
    files += [ROOT/'reality_engine/tests/test_harness_h01.py']
    return git_hash,{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--placebo-draws',type=int,default=499)
    parser.add_argument('--liquidity-threshold',type=float,default=5_000_000.)
    args = parser.parse_args(argv)
    if args.placebo_draws<199:
        parser.error('At least 199 placebo draws are required')
    started = perf_counter()
    OUT.mkdir(parents=True,exist_ok=True)
    archived = archive_previous_artifacts()
    progress('opening dated snapshot read-only; inspecting schemas')
    with Snapshot() as snapshot:
        stat_before = snapshot.path.stat()
        c = snapshot.connection
        c.execute('SET threads=2')
        c.execute("SET memory_limit='3GB'")
        schemas = inspect(c)
        truth = json.loads(c.execute('SELECT report_json FROM truth_report').fetchone()[0])
        snapshot_meta = c.execute('SELECT snapshot_date,built_from,built_to FROM snapshot_meta').fetchall()
        rules = load_tax(c)
        records,filing_audit = load_filings(c)
        progress(f'normalized {len(records)} first-file quarterly observations')
        panel = Panel(c,args.liquidity_threshold)
        benchmark = B5Path(load_indexes(c),panel.calendar,rules)
        evaluator = Evaluator(records,panel,benchmark,rules)
        variants,event_sets,meta = evaluator.evaluate(detailed=True)
        cov_by_timing = {timing: coverage(panel, records, block) for timing, block in meta['by_timing'].items()}
        cov = cov_by_timing[TIMINGS[0]]
        prior_tests = previous_tests()
        q_values = bh_fdr([p for _,p in prior_tests]+[r['p'] for r in variants])[-len(VARIANTS):]
        for row,q in zip(variants,q_values):
            row['bh_q'] = q
        progress('real variants calculated; running full-grid date placebos')
        null = evaluator.placebos(variants,args.placebo_draws)
        benchmark_nav,benchmark_book = benchmark.book_nav()
        books,flat_events,quintiles = {},[],[]
        for row,event_set in zip(variants,event_sets):
            params = row['params']
            label = f"{params['entry_timing']}_{params['measure']}_{params['sign']}_{params['horizon']}"
            rows = event_rows(params,event_set,records,panel)
            flat_events.extend(rows)
            if params['sign']=='positive':
                events = [{'isin':r['entity'],'entry':r['entry'],'exit':r['scheduled_exit'],'sign':'positive'} for r in rows]
                book = run_book(events,panel.calendar,Quotes(panel),ADTV(panel),rules,benchmark_nav)
                for fill in book['fills']:
                    fill['entity'] = fill.pop('isin')
                    i = panel.calendar.days.index(fill['date'])
                    fill['trading_isin'] = panel.actual_isin(i,panel.col[fill['entity']])
                books[label] = book
            yearly = [v['mean'] for v in row['per_year'].values() if v['mean'] is not None]
            desired = 1 if params['sign']=='positive' else -1
            row['proof_checks'] = {
                'bh_q_le_005':row['bh_q']<=.05,'directional_placebo_p_le_005':row['placebo_directional_p']<=.05,
                'max_t_p_le_005':row['reality_check_p']<=.05,
                'four_years_same_expected_sign':len(yearly)>=4 and all(v*desired>0 for v in yearly),
                'both_regimes_expected_sign':all(v['n']>=30 and v['mean'] is not None and v['mean']*desired>0
                                                 for v in row['regimes'].values())}
            if params['sign']=='positive':
                row['proof_checks']['book_positive_excess_and_not_killed'] = (
                    books[label]['excess_cagr']>0 and books[label]['kill_date'] is None
                    and not books[label]['unresolved_holdings'])
            row['status'] = 'provisional_pass' if all(row['proof_checks'].values()) else 'fail'
            row['promoted'] = False
        for timing in TIMINGS:
            for horizon in (20,60):
                for measure in ('PAT','revenue'):
                    quintiles.append({'entry_timing':timing,'horizon':horizon,'measure':measure,
                                      'table':evaluator.quintiles(meta['by_timing'][timing],horizon,measure),'descriptive_only':True})
        git_hash,source_hashes = code_provenance()
        examples = []
        for i,r in enumerate(records):
            if r['entity']=='INE615H' and str(r['period_end'])=='2024-12-31':
                examples.append({**r, 'timings': {
                    timing: {'decision_trigger':block['decision_stamps'][i],
                             'next_open':str(panel.days[block['entry_indices'][i]])+' 09:15 IST',
                             'eligible_with_values_by_open':bool(block['qualified'][i])}
                    for timing, block in meta['by_timing'].items()}})
        result = {'card_id':'H01','status':'completed_provisional','provisional':True,
                  'evidence_window':['2021-01-01','2025-12-31'],'warmup':['2019-01-01','2020-12-31'],
                  'run_timestamp_utc':datetime.now(timezone.utc).isoformat(),'snapshot_name':snapshot.path.name,
                  'snapshot_read_only':True,'snapshot_meta':snapshot_meta,'git_head':git_hash,
                  'source_sha256':source_hashes,'liquidity_threshold_inr':args.liquidity_threshold,
                  'coverage_report':cov,'coverage_by_timing':cov_by_timing,
                  'variants':variants,'quintiles':quintiles,'books':books,
                  'benchmark_choices':benchmark.choices,'benchmark_book':benchmark_book,
                  'placebo':null,'filing_audit':filing_audit,
                  'event_gate_audit':{timing:block['audit'] for timing,block in meta['by_timing'].items()},
                  'timing_diagnostics':timing_diagnostics(evaluator,meta),
                  'fdr_scope':{'current_variants':len(VARIANTS),'prior_ledger_tests':len(prior_tests),
                               'total_tests':len(prior_tests)+len(VARIANTS),'prior_run_ids':sorted({rid for rid,_ in prior_tests})},
                  'panel_audit':panel.audit,'truth_report':truth,'schemas':schemas,'pit_examples':examples,
                  'promotion_bar':'BH/directional placebo/maxT <=0.05; expected signs in >=4 years and both regimes (n>=30 each); positive books outperform B5 without kill; full data gate additionally required',
                  'correction_version':'normal_weekdays_actual_exit_two_pit_timings_v1',
                  'archived_previous_artifacts':archived,
                  'unresolved_exit_cases':[row for row in flat_events if row['exit_missing_loss_bound']],
                  'promoted':False,'full_data_completeness_gate_met':False,
                  'deviations':DEVIATIONS}
        tests_file = OUT/'H01_tests.json'
        if tests_file.exists():
            result['test_results'] = json.loads(tests_file.read_text(encoding='utf-8-sig'))
        result = clean(result)
        run_id = append_variants(result['variants'],snapshot=snapshot.path.name,git_hash=git_hash,
                                 coverage=result['coverage_report'],source_hashes=result['source_sha256'])
        result['ledger_run_id'] = run_id
        result['ledger_rows_appended'] = len(VARIANTS)
        append_run_note(run_id,json.dumps({'method':result['correction_version'],
                                          'prior_runs_in_bh':result['fdr_scope']['prior_run_ids'],
                                          'source_sha256':result['source_sha256']}))
        from .ledger import annotate_superseded_h01_runs
        result['superseded_buggy_runs'] = annotate_superseded_h01_runs(run_id)
        result['elapsed_seconds'] = perf_counter()-started
        stat_after = snapshot.path.stat()
        result['snapshot_file_unchanged'] = (stat_before.st_size, stat_before.st_mtime_ns) == (stat_after.st_size, stat_after.st_mtime_ns)
        if not result['snapshot_file_unchanged']:
            raise RuntimeError('Read-only source snapshot changed during run')
        (OUT/'H01_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        pd.DataFrame(flat_events).to_csv(OUT/'H01_events.csv',index=False)
        pd.DataFrame(clean(benchmark.choices)).to_csv(OUT/'H01_b5_monthly.csv',index=False)
        write_report(result)
    progress(f"finished; ledger run {run_id}; elapsed {result['elapsed_seconds']:.1f}s")


DEVIATIONS = [
    'Original BSE PDF values are not present as dated facts. bse_next_open requires values before the next BSE-triggered open; both_known_next_open waits until the next regular session after max(BSE, XBRL). Historical comparators must precede each policy decision trigger. No XBRL values are backdated to the PDF.',
    'Consolidated is preferred per issuer/quarter. First XBRL per basis is frozen; later duplicate/revised files are discarded. A missing consolidated PAT does not authorize standalone substitution. Standalone and Non-Consolidated are the same historical basis family.',
    'No index opens exist. B5 uses previous-session TRI close as its entry/switch proxy, including the entry-day gap while stocks enter at open. This unavoidable timing mismatch prevents a clean investable benchmark claim.',
    'BSE TRI method is derived, not official. Actual method is logged each month. Both event and book B5 pay the same 30 bp round-trip cost and sell-date capital-gains tax; actual index changes realize gains.',
    'Prices are joined across ISIN changes through security_master issuer, after resolving each filing by its trading_isin. Actual historical entry ISIN is logged. Current listing/active status never filters the universe. Ambiguous code/issuer mappings are rejected.',
    'U1 uses 20 complete prior exchange sessions. A pre-15:30 filing uses the previous completed close for the raw Rs10 test. Non-trading-day filings use the last session. Threshold is Rs50 lakh median; cap is 10% of lagged 20-session mean value. No zero imputation.',
    'Signal and taxable returns use total-return-adjusted stock units. Dividend income is conservatively included in the gains proxy. Full personal dividend tax, cess and income-dependent surcharge are not modeled; cess source coverage is incomplete in tax_rules. These are base capital-gains-tax results.',
    'The common calendar omits all weekend special sessions, including real budget/drill sessions. Missing scheduled closes exit at the stock\'s next actual regular-session close; tax and B5 use that actual date. Only no later quote through 2025 gets a terminal zero-recovery bound. This is an unresolved evidence-boundary case, not proof of delisting. Names are listed. Books retain holdings and retry actual exits; terminal unresolved holdings prevent promotion.',
    'Book targets equal weights on admissions, charges rebalancing trades, keeps spare capacity in zero-interest cash, suppresses overlapping same-issuer admissions, and uses fractional adjusted units. EOD kills fill next executable session and may overshoot 8%.',
    'No technical confirmation overlay is invented for this card. H06 is separate. Coverage and this missing deployment overlay prevent promotion even if statistical gates pass.',
    'P-values use entry-month clustered standard errors. Sixty-session overlaps cross months; full-grid within-month filing-date permutation and max-absolute-t calibration are also reported. These nulls preserve filing season and availability lags, but are not independent event draws.',
    'Quarter duration is 80-100 days, with calendar quarter ends. Semiannual SME filings are excluded from H01, while SME remains in U1. Warm-up uses no pre-2019 facts; no 2026 prices or outcomes are loaded.',
    'Bank status carries forward from earlier BANKING filings when the taxonomy becomes INTEGRATED. It never uses a future bank label. Earlier runs, including the bank-label correction and defective calendar runs, remain in the ledger/BH family with append-only superseded_by_bugfix notes. Both timing policies are tested together; no horizon or signal threshold was selected from their performance.'
]


def write_report(r):
    pct = lambda x:'—' if x is None else f'{100*x:.2f}%'
    num = lambda x:'—' if x is None else f'{x:.3g}'
    lines = ['# H01 PEAD — corrected calendar and timing comparison, provisional','',
             'No variant is promoted. Coverage is incomplete. The benchmark entry uses a close proxy.','',
             f"Snapshot: `{r['snapshot_name']}`, read-only. Evidence: 2021–2025. Warm-up: 2019–2020.",
             f"Run: `{r['ledger_run_id']}`. {r['ledger_rows_appended']} variants were appended to the shared ledger.",'',
             f"BH family: {r['fdr_scope']['total_tests']} tests, including {r['fdr_scope']['prior_ledger_tests']} prior ledger rows. Defective earlier runs are annotated superseded_by_bugfix and retained.",'',
             '## Coverage report','',
             '| Timing | Year | U1 ISINs | Results + BSE + U1 | Prior-history covered | Values by entry | Results / U1 |',
             '|---|---|---:|---:|---:|---:|---:|']
    for timing, coverage_rows in r['coverage_by_timing'].items():
        for v in coverage_rows:
            lines.append(f"| {timing} | {v['year']} | {v['u1_isins']} | {v['financial_covered_isins']} | {v['usable_surprise_history_isins']} | {v['known_by_entry_isins']} | {pct(v['financial_coverage'])} |")
    lines += ['', 'U1 counts each actual ISIN eligible on any session in the year. Delisted names remain.',
              'Coverage uses filing-trigger year. The final column is not full AR/concall/deck coverage.',
              'Twelve prior quarterly values are needed for eight prior YoY changes. No pre-2019 warm-up is used.','',
              '## All 16 variants','',
              'bse_next_open: next regular session after BSE, only if XBRL values are known before that open.',
              'both_known_next_open: next regular session after the later of BSE and XBRL. This is a timing sensitivity, not a new signal.','',
              'Returns are after 30 bp round trip and base capital-gains tax. Excess subtracts after-tax/cost B5.',
              'Negative surprise is an avoid cohort. Its return is not reversed into a short profit.','',
              '| Timing | Measure | Sign | Days | Events | Mean excess | Median excess | t | p | BH q | Placebo p | Directional p | Max-T p | 2021/22/23/24/25 |',
              '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for v in r['variants']:
        p=v['params']; signs='/'.join(v['per_year_signs'].get(str(y)) or 'NA' for y in range(2021,2026))
        lines.append(f"| {p['entry_timing']} | {p['measure']} | {p['sign']} | {p['horizon']} | {v['n_events']} | {pct(v['mean_net_excess'])} | {pct(v['median_net_excess'])} | {num(v['t_stat'])} | {num(v['p'])} | {num(v['bh_q'])} | {num(v['placebo_p'])} | {num(v['placebo_directional_p'])} | {num(v['reality_check_p'])} | {signs} |")
    lines += ['', '## Placebo and regimes','',
              f"{r['placebo']['draws']} within-month filing-date permutations. Seed {r['placebo']['seed']}.",
              'The same evaluator recomputes availability, liquidity, entry and returns in each draw.',
              'The JSON retains every placebo mean, event count and full-grid maximum absolute t.','',
              '| Variant | Placebo mean | Placebo 2.5% / median / 97.5% | Up-market mean (n) | Down-market mean (n) |',
              '|---|---:|---|---|---|']
    for v in r['variants']:
        p=v['params']; up,down=v['regimes']['up'],v['regimes']['down']
        qs=v['placebo']['quantiles'] or [None]*3
        lines.append(f"| {p['entry_timing']} {p['measure']} {p['sign']} {p['horizon']} | {pct(v['placebo']['mean'])} | {' / '.join(pct(x) for x in qs)} | {pct(up['mean'])} ({up['n']}) | {pct(down['mean'])} ({down['n']}) |")
    lines += ['', 'Up/down means the selected index rose/fell over 63 sessions ending before entry.',
              'Placebo p compares absolute observed mean excess with absolute shuffled means. It can be small for harmful effects.',
              'Directional p uses the claimed sign: positive excess for positive surprises and negative excess for the avoid cohort.',
              'Max-T p compares the absolute cluster t with the shuffled maximum absolute cluster t across all 16 current variants.',
              'Month-clustered t statistics are descriptive. Historical variants remain in BH; max-T covers this current grid.',
              'Promotion also needs four years with the expected sign, both regimes, and a surviving book.',
              'The full data gate is unmet regardless of those checks.','',
              '## Long-only books','',
              'Each positive variant gets its own Rs 10 lakh sleeve inside Rs 1 crore. They are alternatives, not added together.',
              'The other Rs 90 lakh stays in cash. Negative cohorts do not trade.','',
              '| Variant | Sleeve CAGR | Total-capital CAGR | Max sleeve DD | Max portfolio DD | B5 CAGR | Excess CAGR | Kill |',
              '|---|---:|---:|---:|---:|---:|---:|---|']
    for name,b in r['books'].items():
        lines.append(f"| {name} | {pct(b['allocation_cagr'])} | {pct(b['total_capital_cagr'])} | {pct(b['max_drawdown'])} | {pct(b['portfolio_max_drawdown'])} | {pct(b['b5_cagr'])} | {pct(b['excess_cagr'])} | {b['kill_date'] or 'none'} |")
    lines += ['', 'A killed sleeve stays in cash for the rest of the evidence window. Kill timing uses no future close.',
              'Daily NAV, fees, taxes, skipped admissions and fills are in the JSON.','',
              '## B5 monthly choices','',
              'The winner uses only TRI observations before each month. Lookback is 12 calendar months.',
              'The first session uses the chosen index’s own prior close. Index levels are never spliced.',
              'All 60 choices, source methods, as-of dates and lookback returns are in `H01_b5_monthly.csv` and JSON.','',
              '| Year | Chosen index: months |', '|---|---|']
    for year in range(2021,2026):
        counts=Counter(v['index'] for v in r['benchmark_choices'] if v['month'].startswith(str(year)))
        lines.append(f"| {year} | {'; '.join(f'{k}: {v}' for k,v in sorted(counts.items()))} |")
    lines += ['', '## Surprise quintiles','', 'These use ex-post ranks for description. They are not traded thresholds.','',
              '| Timing | Measure | Days | Quintile | n | Mean excess |', '|---|---|---:|---:|---:|---:|']
    for group in r['quintiles']:
        for v in group['table']:
            lines.append(f"| {group['entry_timing']} | {group['measure']} | {group['horizon']} | {v['quintile']} | {v['n_events']} | {pct(v['mean_net_excess'])} |")
    lines += ['', '## Timing and data checks','',f"Filing audit: `{json.dumps(r['filing_audit'])}`.",'',
              f"Event gates: `{json.dumps(r['event_gate_audit'])}`.",'',
              f"Price panel: `{json.dumps(r['panel_audit'])}`.",'']
    lines += ['| Variant | Delayed exits filled | Unresolved loss bounds | Truth jump flags | Mean stock entry gap |',
              '|---|---:|---:|---:|---:|']
    for v in r['variants']:
        p=v['params']
        lines.append(f"| {p['entry_timing']} {p['measure']} {p['sign']} {p['horizon']} | {v['delayed_exits_with_quote']} | {v['missing_exit_total_loss_bounds']} | {v['events_crossing_truth_jump_flags']} | {pct(v['stock_entry_gap']['mean'])} |")
    lines += ['', 'The stock gap is adjusted entry open / previous regular-session close minus one. It is a scale check, not the unobserved index overnight gap or an estimate of its bias.', '',
              '### BSE-to-XBRL and admission lag', '',
              '| Timing | Qualified events | XBRL later than BSE | XBRL lag hours p50 / p90 / p99 | Entry delay sessions p50 / p90 / p99 |',
              '|---|---:|---:|---|---|']
    for timing, blocks in r['timing_diagnostics'].items():
        v = blocks['qualified']
        hours = v['lag_hours_quantiles_0_25_50_75_90_99_100']
        delay = v['entry_delay_sessions_quantiles_0_50_90_99_100']
        lines.append(f"| {timing} | {v['n']} | {v['positive_lag_n']} | {' / '.join(num(hours[i]) for i in (2,4,5)) if hours else 'NA'} | {' / '.join(num(delay[i]) for i in (1,2,3)) if delay else 'NA'} |")
    lines += ['', 'JSON also gives lag distributions before history and entry gates, to expose the selection. Lag is floored at zero when XBRL preceded BSE.', '',
              '### Unresolved exits', '']
    unresolved = {(v['entity'],v['symbol'],v['scheduled_exit']) for v in r['unresolved_exit_cases']}
    lines += [f'- {symbol} ({entity}), scheduled {scheduled}: no later regular-session close through 2025-12-31; zero-recovery bound, no claimed sale.'
              for entity,symbol,scheduled in sorted(unresolved)] or ['None. Every missing scheduled close had a later quote within the evidence window.']
    lines.append('')
    for v in r['pit_examples']:
        lines.append(f"TITAGARH Q3 FY25: BSE `{v['trade_trigger']}` IST; XBRL `{v['xbrl_at']}` IST. Timing checks: `{json.dumps(v['timings'])}`.")
    lines += ['', '## Deviations','']+[f'{i+1}. {d}' for i,d in enumerate(r['deviations'])]
    tests=r.get('test_results',{})
    lines += ['', '## Tests','',
              f"{tests.get('total_tests','unrecorded')} tests passed: {tests.get('harness_tests','unrecorded')} harness tests and {tests.get('horizon_excess_tests','unrecorded')} existing horizon tests.",
              'Synthetic fixtures do not need the snapshot. Adapter tests use only an in-memory fixture database.',
              'The existing horizon suite uses its own temporary synthetic databases. No other source database was opened.']
    lines += ['', '## What could still be fooling us','',
              'This is a liquid XBRL-filer subset. Strict late-XBRL rejection selects different issuers; waiting changes the entry price and exposure.',
              'Unparsed announcement fallback can match the wrong results document. Basis preference can omit earlier standalone data.',
              'The snapshot cannot prove the first PDF and later XBRL have identical values.',
              'Results cluster. Horizons overlap. BSE total returns are estimates. Index opens are unavailable.',
              'Split mappings, inferred adjustments and unexplained jumps can still contaminate returns.',
              'A cohort edge can disappear after sizing, idle cash, rebalancing and a drawdown kill.','',
              '## Reproduction','',
              '`python -m reality_engine.harness.run_h01 --placebo-draws 499`','',
              f"Git HEAD `{r['git_head']}`. New source files are uncommitted; their SHA256 hashes are in JSON.",
              f"Compute runtime: {r['elapsed_seconds']:.1f} seconds. No 2026 results. No commit, push or stash."]
    (OUT/'H01_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
