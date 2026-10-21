"""Independent pandas/source verification of the ten selection contrasts."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .adapter import inspect
from .data import ROOT, Snapshot, Calendar
from .ledger import LEDGER
from .run_h01_long import horizon_hac
from .stats import bh_fdr

OUT = ROOT/'tasks/backtests'


def pandas_cells(part, threshold):
    df = part[part.PAT_surprise.abs().ge(threshold)&part.PAT_surprise.ne(0)].copy()
    df['positive'] = df.PAT_surprise.gt(0)
    cells = df.groupby(['group','positive']).net_excess.agg(['count','mean']).unstack('positive')
    for side in (False,True):
        if ('count',side) not in cells:
            return pd.DataFrame(columns=['positive_n','negative_n','positive_mean','negative_mean','weight','lift'])
    keep = cells[('count',True)].ge(3)&cells[('count',False)].ge(3)
    cells = cells[keep]
    out = pd.DataFrame({'positive_n':cells[('count',True)],'negative_n':cells[('count',False)],
                        'positive_mean':cells[('mean',True)],'negative_mean':cells[('mean',False)]})
    out['weight'] = out[['positive_n','negative_n']].min(axis=1)
    out['lift'] = out.positive_mean-out.negative_mean
    return out


def main():
    r = json.loads((OUT/'H01_selection_results.json').read_text(encoding='utf-8'))
    features = pd.read_csv(OUT/'H01_selection_features.csv.gz')
    features['entry'] = pd.to_datetime(features.entry)
    outcomes = pd.read_csv(OUT/'H01_long_outcomes.csv.gz')
    outcomes = outcomes[outcomes.entry_timing=='both_known_next_open'].copy()
    checks = {'source_hashes_match':all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==v
                                        for p,v in r['source_sha256'].items()),
              'snapshot_read_only_unchanged':r['snapshot_read_only'] and r['snapshot_file_unchanged'],
              'ten_tests_no_promotion':len(r['variants'])==10 and not r['promoted'],
              'unique_master_records':not features.duplicated('record_id').any(),
              'all_features_use20_values':bool(features.n.eq(20).all()),
              'fixed_liquidity_bins':bool(np.all(features.liquidity_bin==np.digitize(features.adtv20,[1e7,1e8,1e9]))),
              'all_observed_cells_recompute':True,'all_cohort_statistics_recompute':True,
              'all_hac_support_and_p_recompute':True,'persisted_placebo_p_recomputes':True,
              'first_three_coherent_null_draws_recompute':True}
    merged = {}
    for horizon in (90,120,180,252,504):
        part = outcomes[outcomes.horizon==horizon][['record_id','net_excess']].merge(
            features[['record_id','group','entry_month','PAT_surprise','entity']],on='record_id',validate='one_to_one')
        merged[horizon] = part
    by_group_month = features.groupby('group').entry_month.first()
    for row in r['variants']:
        p = row['params']
        cells = pandas_cells(merged[p['horizon']],0 if p['cohort']=='any' else 1)
        mu = float(np.average(cells.lift,weights=cells.weight)) if len(cells) else None
        n = int(cells.positive_n.sum()+cells.negative_n.sum())
        checks['all_cohort_statistics_recompute'] &= n==row['n_events'] and len(cells)==row['matched_cells']
        checks['all_cohort_statistics_recompute'] &= (mu is None and row['mean_net_excess'] is None) or abs(mu-row['mean_net_excess'])<1e-12
        saved = {cell['group']:cell for cell in row['cells']}
        checks['all_observed_cells_recompute'] &= set(cells.index)==set(saved)
        for group,cell in cells.iterrows():
            checks['all_observed_cells_recompute'] &= all(abs(float(cell[key])-saved[group][key])<1e-12
                for key in ('positive_n','negative_n','positive_mean','negative_mean','weight','lift'))
        monthly = cells.assign(month=by_group_month.loc[cells.index].to_numpy())
        monthly['weighted_lift'] = monthly.weight*monthly.lift
        monthly = monthly.groupby('month')[['weighted_lift','weight']].sum()
        monthly_values = (monthly.weighted_lift/monthly.weight).to_numpy()
        month_days = np.array(monthly.index,dtype='datetime64[M]').astype('datetime64[D]')
        hac = horizon_hac(monthly_values,np.arange(len(month_days)),month_days,p['horizon'])
        checks['all_hac_support_and_p_recompute'] &= (hac['sufficient_support']==row['hac']['sufficient_support']
            and abs(hac['p']-row['hac']['p'])<1e-10 and abs(row['p']-max(row['cluster_p'],row['hac']['p']))<1e-12)
        valid = np.array(row['placebo']['mean_distribution'],dtype=float)
        valid = valid[np.isfinite(valid)]
        expected = (1+int(np.sum(valid>=row['mean_net_excess'])))/(1+len(valid))
        max_t = np.array(r['max_abs_t_distribution'])
        expected_max = (1+int(np.sum(max_t>=abs(row['t_stat']))))/1000 if row['t_stat'] is not None else 1.
        checks['persisted_placebo_p_recomputes'] &= len(valid)==999 and abs(expected-row['placebo_directional_p'])<1e-12 and abs(expected_max-row['reality_check_p'])<1e-12
    rng = np.random.default_rng(20261021)
    original = features.PAT_surprise.to_numpy()
    groups = [np.flatnonzero(features.group.to_numpy()==g) for g in range(int(features.group.max())+1)]
    for draw in range(3):
        shuffled = original.copy()
        for ids in groups:
            shuffled[ids] = rng.permutation(shuffled[ids])
        score_map = dict(zip(features.record_id,shuffled))
        for row in r['variants']:
            p = row['params']
            part = merged[p['horizon']].copy()
            part.PAT_surprise = part.record_id.map(score_map)
            cells = pandas_cells(part,0 if p['cohort']=='any' else 1)
            value = float(np.average(cells.lift,weights=cells.weight)) if len(cells) else None
            saved = row['placebo']['mean_distribution'][draw]
            checks['first_three_coherent_null_draws_recompute'] &= (value is None and saved is None) or abs(value-saved)<1e-12
    source_rows = []
    with Snapshot() as snapshot:
        c = snapshot.connection
        c.execute('SET threads=2')
        c.execute("SET memory_limit='2GB'")
        inspect(c)
        cal = Calendar.normal_sessions(row[0] for row in c.execute("""SELECT date FROM index_tri
            WHERE index_name='NIFTY 50' AND date BETWEEN '2019-01-01' AND '2025-12-31'""").fetchall())
        c.register('selection_verify_sessions',pd.DataFrame({'day':pd.to_datetime(cal.days)}))
        sample = pd.concat([features.head(10),features.sample(50,random_state=20261021)]).drop_duplicates('record_id')
        days = np.array(cal.days,dtype='datetime64[D]')
        checks['source_lagged_liquidity_sample'] = True
        for row in sample.itertuples():
            entry = int(np.searchsorted(days,np.datetime64(row.entry.date())))
            source = c.execute("""SELECT s.day,p.value_inr FROM selection_verify_sessions s
                LEFT JOIN px_daily p ON p.entity_id=? AND p.date=s.day
                WHERE s.day>=? AND s.day<? ORDER BY s.day""",
                [row.entity,str(days[entry-20]),row.entry.to_pydatetime()]).fetchall()
            average = np.mean([value for day,value in source])
            checks['source_lagged_liquidity_sample'] &= len(source)==20 and abs(average-row.adtv20)<max(1e-5,abs(average)*1e-12)
            if len(source_rows)<10:
                source_rows.append({'record_id':row.record_id,'entity':row.entity,'entry':str(row.entry),
                    'source_window_start':str(source[0][0]),'source_window_end':str(source[-1][0]),
                    'source_adtv20':average,'written_adtv20':row.adtv20})
        # Flag exposure is descriptive. No outcomes are dropped or clipped.
        keys = outcomes[['record_id','entity','horizon','entry','exit']].copy()
        keys['entry'],keys['exit'] = pd.to_datetime(keys.entry),pd.to_datetime(keys.exit)
        c.register('selection_verify_outcomes',keys)
        flag_rows = c.execute("""SELECT o.record_id,o.horizon,count(j.date) jump_flags
            FROM selection_verify_outcomes o LEFT JOIN unexplained_jumps j
              ON o.entity=j.entity_id AND cast(j.date AS DATE)>=o.entry AND cast(j.date AS DATE)<=o.exit
            GROUP BY o.record_id,o.horizon""").df()
        flagged = keys.merge(flag_rows,on=['record_id','horizon'],validate='one_to_one')
        source_flags = {str(h):{'outcomes_crossing_flags':int(group.jump_flags.gt(0).sum()),
                               'flagged_entities':sorted(group[group.jump_flags.gt(0)].entity.unique().tolist())}
                        for h,group in flagged.groupby('horizon')}
    import duckdb
    with duckdb.connect(str(LEDGER),read_only=True) as c:
        rows = c.execute('SELECT run_id,p FROM variants ORDER BY run_timestamp,row_id').fetchall()
    prior = [p for run,p in rows if run!=r['ledger_run_id']]
    qs = bh_fdr(prior+[row['p'] for row in r['variants']])[-10:]
    checks['ten_ledger_rows_all_prior_tests_retained'] = sum(run==r['ledger_run_id'] for run,p in rows)==10 and len(prior)==206
    checks['full216_test_bh_recomputed'] = all(abs(q-row['bh_q'])<1e-12 for q,row in zip(qs,r['variants']))
    checks = {key:bool(value) for key,value in checks.items()}
    payload = {'run_id':r['ledger_run_id'],'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
        'checks':checks,'all_checks_pass':all(checks.values()),'source_liquidity_first_written_rows':source_rows,
        'all_sign_outcomes_crossing_source_jump_flags':source_flags,
        'verifier_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (OUT/'H01_selection_verification.json').write_text(json.dumps(payload,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'checks':len(checks),'failed':[key for key,value in checks.items() if not value],
                      'source_flag_exposure':source_flags},indent=2))
    if not all(checks.values()):
        raise AssertionError('Selection audit failed')


if __name__=='__main__':
    main()
