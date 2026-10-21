"""Ten declared stock-selection contrasts after the H01 timing extension."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from time import perf_counter

import numpy as np
import pandas as pd

from .adapter import inspect
from .data import ROOT, Snapshot, Calendar
from .ledger import previous_tests, append_variants, append_run_note
from .run_h01 import clean, code_provenance, progress
from .run_h01_long import horizon_hac
from .stats import bh_fdr, student_p

OUT = ROOT/'tasks/backtests'
HORIZONS = (90,120,180,252,504)
VARIANTS = tuple({'analysis':'selection_contrast','entry_timing':'both_known_next_open',
                 'horizon':h,'measure':'PAT','sign':'positive_minus_negative_control',
                 'cohort':cohort,'sample':'entry_month_trend_liquidity_matched'}
                for h in HORIZONS for cohort in ('any','abs_ge_1'))


def contrast(values, scores, groups, group_months, threshold=0., detailed=False):
    n_groups = len(group_months)
    pos = (scores>0)&(np.abs(scores)>=threshold)
    neg = (scores<0)&(np.abs(scores)>=threshold)
    np_ = np.bincount(groups[pos],minlength=n_groups)
    nn = np.bincount(groups[neg],minlength=n_groups)
    ps = np.bincount(groups[pos],weights=values[pos],minlength=n_groups)
    ns = np.bincount(groups[neg],weights=values[neg],minlength=n_groups)
    usable = (np_>=3)&(nn>=3)
    ids = np.flatnonzero(usable)
    weight = np.minimum(np_[ids],nn[ids]).astype(float)
    positive,negative = ps[ids]/np_[ids],ns[ids]/nn[ids]
    lift = positive-negative
    mu = float(np.average(lift,weights=weight)) if len(ids) else None
    months,inverse = np.unique(group_months[ids],return_inverse=True)
    n_months = len(months)
    cluster_p,tstat = 1.,None
    if n_months>1:
        residual = np.bincount(inverse,weights=weight*(lift-mu))
        se = np.sqrt(n_months/(n_months-1)*np.sum(residual**2))/weight.sum()
        if se>0:
            tstat = mu/se
            cluster_p = student_p(tstat,n_months-1)
    row = {'n_events':int(np_[ids].sum()+nn[ids].sum()),'mean_net_excess':mu,
           'median_net_excess':float(np.median(lift)) if len(ids) else None,
           't_stat':tstat,'p':cluster_p,'cluster_p':cluster_p,
           'matched_cells':len(ids),'matched_months':n_months}
    if detailed:
        monthly_weight = np.bincount(inverse,weights=weight)
        monthly_lift = np.bincount(inverse,weights=weight*lift)/monthly_weight if len(ids) else np.array([])
        month_days = np.array(months,dtype='datetime64[M]').astype('datetime64[D]')
        row.update({'positive_mean':float(np.average(positive,weights=weight)) if len(ids) else None,
                    'negative_mean':float(np.average(negative,weights=weight)) if len(ids) else None,
                    'positive_events':int(np_[ids].sum()),'negative_events':int(nn[ids].sum()),
                    'matched_fraction':row['n_events']/len(values) if len(values) else 0.,
                    'cells':[{'group':int(g),'month':str(month_days[np.searchsorted(months,group_months[g])]),
                              'positive_n':int(np_[g]),'negative_n':int(nn[g]),'weight':float(w),
                              'positive_mean':float(a),'negative_mean':float(b),'lift':float(d)}
                             for g,w,a,b,d in zip(ids,weight,positive,negative,lift)]})
        row['per_year_signs'],row['per_year'] = {},{}
        years = np.array(month_days,dtype='datetime64[Y]').astype(int)+1970
        for year in range(2021,2026):
            keep = years==year
            avg = float(np.average(monthly_lift[keep],weights=monthly_weight[keep])) if keep.any() else None
            row['per_year'][str(year)] = {'months':int(keep.sum()),'mean':avg}
            row['per_year_signs'][str(year)] = None if avg is None else '+' if avg>0 else '-' if avg<0 else '0'
        row['_monthly_lift'],row['_month_days'] = monthly_lift,month_days
    return row


def main():
    started = perf_counter()
    if (OUT/'H01_selection_results.json').exists():
        raise FileExistsError('Preserve completed selection follow-up before rerunning')
    frame = pd.read_csv(OUT/'H01_long_outcomes.csv.gz')
    frame = frame[frame.entry_timing=='both_known_next_open'].copy()
    frame['entry'] = pd.to_datetime(frame.entry)
    master = frame[frame.horizon==20].drop_duplicates('record_id').copy()
    master = master[np.isfinite(master.PAT_surprise)].reset_index(drop=True)
    with Snapshot() as snapshot:
        before = snapshot.path.stat()
        c = snapshot.connection
        c.execute('SET threads=2')
        c.execute("SET memory_limit='2GB'")
        inspect(c)
        cal = Calendar.normal_sessions(row[0] for row in c.execute("""SELECT date FROM index_tri
            WHERE index_name='NIFTY 50' AND date BETWEEN '2019-01-01' AND '2025-12-31'""").fetchall())
        days = np.array(cal.days,dtype='datetime64[D]')
        idx = np.searchsorted(days,master.entry.to_numpy().astype('datetime64[D]'))
        keys = master[['record_id','entity','entry']].copy()
        keys['start'] = days[idx-20]
        c.register('h01_selection_keys',keys)
        c.register('h01_selection_sessions',pd.DataFrame({'day':pd.to_datetime(cal.days)}))
        liquidity = c.execute("""SELECT k.record_id,avg(p.value_inr) adtv20,count(p.value_inr) n
            FROM h01_selection_keys k JOIN h01_selection_sessions s ON s.day>=k.start AND s.day<k.entry
            LEFT JOIN px_daily p ON p.entity_id=k.entity AND p.date=s.day GROUP BY k.record_id""").df()
        master = master.merge(liquidity,on='record_id',validate='one_to_one')
        n_before = len(master)
        master = master[(master.n==20)&np.isfinite(master.adtv20)&master.adtv20.gt(0)].reset_index(drop=True)
        master['liquidity_bin'] = np.digitize(master.adtv20,[10_000_000.,100_000_000.,1_000_000_000.])
        master['entry_month'] = master.entry.to_numpy().astype('datetime64[M]').astype(int)
        strata,inv = np.unique(master[['entry_month','trend200','liquidity_bin']].to_numpy(dtype=int),axis=0,return_inverse=True)
        master['group'] = inv
        group_months = strata[:,0]
        scores = master.PAT_surprise.to_numpy()
        label_groups = [np.flatnonzero(inv==g) for g in range(len(strata))]
        record_index = pd.Index(master.record_id)
        data = {}
        for horizon in HORIZONS:
            part = frame[(frame.horizon==horizon)&frame.record_id.isin(master.record_id)].copy()
            positions = record_index.get_indexer(part.record_id)
            data[horizon] = {'values':part.net_excess.to_numpy(),'positions':positions,'groups':inv[positions],
                             'entities':part.entity.to_numpy()}
        rows = []
        for params in VARIANTS:
            d = data[params['horizon']]
            row = contrast(d['values'],scores[d['positions']],d['groups'],group_months,
                           0 if params['cohort']=='any' else 1,detailed=True)
            hac = horizon_hac(row.pop('_monthly_lift'),np.arange(row['matched_months']),
                              row.pop('_month_days'),params['horizon'])
            row.update({'params':params,'hac':hac,'p':max(row['cluster_p'],hac['p'])})
            matched_groups = {cell['group'] for cell in row['cells']}
            positive = (scores[d['positions']]>0)&np.isin(d['groups'],list(matched_groups))
            if params['cohort']=='abs_ge_1':
                positive &= scores[d['positions']]>=1
            contribution = pd.DataFrame({'entity':d['entities'][positive],
                                         'gain':np.maximum(d['values'][positive],0)}).groupby('entity').gain.sum().sort_values(ascending=False)
            row['top5_share_positive_excess_mass'] = float(contribution.head(5).sum()/contribution.sum()) if contribution.sum()>0 else None
            row['matched_positive_issuers'] = int(len(contribution))
            row['top5_contributors'] = contribution.head(5).to_dict()
            rows.append(row)
        progress('selection follow-up:999 coherent within-stratum label permutations')
        rng = np.random.default_rng(20261021)
        means = np.full((999,len(rows)),np.nan)
        max_t = np.zeros(999)
        for draw in range(999):
            shuffled = scores.copy()
            for ids in label_groups:
                shuffled[ids] = rng.permutation(shuffled[ids])
            ts = []
            for j,params in enumerate(VARIANTS):
                d = data[params['horizon']]
                stat = contrast(d['values'],shuffled[d['positions']],d['groups'],group_months,
                                0 if params['cohort']=='any' else 1)
                if stat['mean_net_excess'] is not None:
                    means[draw,j] = stat['mean_net_excess']
                if stat['t_stat'] is not None:
                    ts.append(abs(stat['t_stat']))
            max_t[draw] = max(ts,default=0.)
        prior = previous_tests()
        qs = bh_fdr([p for _,p in prior]+[row['p'] for row in rows])[-len(rows):]
        for j,(row,q) in enumerate(zip(rows,qs)):
            valid = means[:,j][np.isfinite(means[:,j])]
            mu,t = row['mean_net_excess'],row['t_stat']
            row['bh_q'] = q
            row['placebo_p'] = float((1+np.sum(np.abs(valid)>=abs(mu)))/(1+len(valid))) if mu is not None and len(valid) else 1.
            row['placebo_directional_p'] = float((1+np.sum(valid>=mu))/(1+len(valid))) if mu is not None and len(valid) else 1.
            row['reality_check_p'] = float((1+np.sum(max_t>=abs(t)))/1000) if t is not None else 1.
            row['placebo'] = {'draws':999,'mean_distribution':means[:,j],
                              'quantiles':np.quantile(valid,[.025,.5,.975]) if len(valid) else None}
            row['status'] = 'research_lead' if row['bh_q']<=.05 and row['placebo_directional_p']<=.05 and row['reality_check_p']<=.05 else 'unproven'
            row['promoted'] = False
        plan = ROOT/'tasks/codex_tasks/H01_SELECTION_FOLLOWUP_PLAN_2026-10-21.md'
        git_hash,hashes = code_provenance()
        test = ROOT/'reality_engine/tests/test_harness_h01_selection.py'
        hashes[str(test.relative_to(ROOT)).replace('\\','/')] = hashlib.sha256(test.read_bytes()).hexdigest()
        after = snapshot.path.stat()
        result = clean({'analysis':'H01 selection versus timing','variants':rows,
            'snapshot_name':snapshot.path.name,'snapshot_read_only':True,
            'snapshot_file_unchanged':(before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),
            'git_head':git_hash,'source_sha256':hashes,'declared_plan_sha256':hashlib.sha256(plan.read_bytes()).hexdigest(),
            'fdr_scope':{'current_variants':10,'prior_ledger_tests':len(prior),'total_tests':len(prior)+10},
            'master_events':len(master),'missing_liquidity_excluded':n_before-len(master),'strata':len(strata),
            'permutations':999,'max_abs_t_distribution':max_t,'prior_long_run':'03f51f86-ee1c-4e9f-af61-b67905a0817c',
            'promoted':False,'full_data_completeness_gate_met':False,
            'interpretation':'selection contrast uses negative-surprise controls; no short or investable long-short return',
            'limits':['no PIT sector/market-cap controls','long outcomes overlap;504 has too few independent years',
                      'same stocks can recur across quarters','existing94 positive books all hit the drawdown kill',
                      'exploratory follow-up after prior results; all prior tests remain in BH']})
        if not result['snapshot_file_unchanged']:
            raise RuntimeError('Source snapshot changed')
        run_id = append_variants(result['variants'],snapshot=snapshot.path.name,git_hash=git_hash,
                                 coverage={'master_events':len(master),'strata':len(strata)},source_hashes=hashes)
        result['ledger_run_id'] = run_id
        append_run_note(run_id,json.dumps({'method':'H01_SELECTION_FOLLOWUP_PLAN_2026-10-21.md',
            'scope':'positive-minus-negative association, never short trade','prior_tests':len(prior)}))
        result['elapsed_seconds'] = perf_counter()-started
        master[['record_id','entity','entry','PAT_surprise','adtv20','n','liquidity_bin','trend200','entry_month','group']].to_csv(
            OUT/'H01_selection_features.csv.gz',index=False,compression='gzip')
        (OUT/'H01_selection_results.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
        write_report(result)
    progress(f'selection follow-up finished:{run_id};{result["elapsed_seconds"]:.1f}s')


def write_report(r):
    pct = lambda v:'NA' if v is None else f'{v*100:.2f}%'
    num = lambda v:'NA' if v is None else f'{v:.3g}'
    lines = ['# H01 stock selection versus announcement timing — exploratory','',
        'The date-placebo test retained stock identities. This follow-up shuffles earnings labels within entry month, prior200-session trend and lagged-liquidity group. Positive-minus-negative is an association contrast, not a short-book profit.', '',
        f"Run `{r['ledger_run_id']}`.10 new tests;{r['fdr_scope']['total_tests']} tests in BH including all{r['fdr_scope']['prior_ledger_tests']} prior tests.999 coherent label permutations. No2026 outcomes.", '',
        '| Sessions | Cohort | Matched events | Matched cells | Positive mean excess | Negative mean excess | Difference | Cluster p | HAC p | BH q | Label placebo p | Max-T p | 2021/22/23/24/25 | Top5 positive payoff share |',
        '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|']
    for row in r['variants']:
        p = row['params']
        signs = '/'.join(row['per_year_signs'][str(y)] or 'NA' for y in range(2021,2026))
        lines.append(f"| {p['horizon']} | {p['cohort']} | {row['n_events']} | {row['matched_cells']} | {pct(row['positive_mean'])} | {pct(row['negative_mean'])} | {pct(row['mean_net_excess'])} | {num(row['cluster_p'])} | {num(row['hac']['p'])} | {num(row['bh_q'])} | {num(row['placebo_directional_p'])} | {num(row['reality_check_p'])} | {signs} | {pct(row['top5_share_positive_excess_mass'])} |")
    lines += ['', 'Strata require at least3 observations of each sign. Cell weight=min(positive n,negative n). Ledger p=max(cluster p,HAC p). Missing/too-short HAC support gives p1. Thresholds and liquidity boundaries were declared before this follow-up.', '',
        f"Master events:{r['master_events']}; strata:{r['strata']}; excluded for incomplete prior20 liquidity:{r['missing_liquidity_excluded']}.", '',
        '## Limits and deployment', '',
        'A selection association can be useful in a future challenger without being a proven standalone PEAD strategy. No variant is promoted. The94 constrained positive books from the longer-horizon grid all hit their strategy kill. Sector/size confounding and full coverage still need work.', '']
    lines += [f'- {item}' for item in r['limits']]
    lines += ['', f"Read-only snapshot unchanged:{r['snapshot_file_unchanged']}; runtime{r['elapsed_seconds']:.1f}s.",
              'Reproduce: `python -m reality_engine.harness.run_h01_selection`. Features, cell statistics, null distributions and source hashes are saved.']
    (OUT/'H01_selection_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
