"""Independent artifact/source checks for the reviewed H01 rerun.

No live databases or network. Snapshot and ledger are opened read-only.
Writes only H01_verification.json; raises on a failed check.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .adapter import inspect, load_indexes, load_tax
from .benchmark import B5Path
from .cards.h01_pead import VARIANTS
from .costs_tax import sale
from .data import Calendar, ROOT, Snapshot
from .ledger import LEDGER
from .stats import bh_fdr

OUT = ROOT/'tasks/backtests'
KEYS = ['entry_timing','horizon','measure','sign']


def main():
    r = json.loads((OUT/'H01_results.json').read_text(encoding='utf-8'))
    events = pd.read_csv(OUT/'H01_events.csv', keep_default_na=False)
    for name in ('entry','exit','scheduled_exit'):
        events[name] = pd.to_datetime(events[name])
    for name in ('trigger','decision_trigger','xbrl_at','available_at'):
        events[name] = pd.to_datetime(events[name], format='mixed')
    checks = {}
    checks['source_hashes_match'] = all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==v
                                        for p,v in r['source_sha256'].items())
    checks['snapshot_unchanged_during_run'] = r['snapshot_file_unchanged']
    checks['sixteen_variants'] = {tuple(v['params'][k] for k in KEYS) for v in r['variants']} == {
        tuple(v[k] for k in KEYS) for v in VARIANTS}
    checks['all_events_within_evidence'] = bool(((events.entry >= '2021-01-01') & (events.exit <= '2025-12-31')
                                                & (events.trigger >= '2021-01-01')).all())
    checks['no_special_weekend_fills'] = bool(((events.entry.dt.dayofweek < 5) & (events.exit.dt.dayofweek < 5)).all())
    open_stamp = events.entry + pd.Timedelta(hours=9,minutes=15)
    checks['current_numbers_known_before_open'] = bool((events.available_at < open_stamp).all())
    strict = events.entry_timing == 'bse_next_open'
    checks['decision_policies_exact'] = bool((events.loc[strict,'decision_trigger']==events.loc[strict,'trigger']).all()
        and (events.loc[~strict,'decision_trigger']==events.loc[~strict,'available_at']).all())
    checks['variant_csv_counts_and_means'] = True
    for v in r['variants']:
        subset = events
        for k in KEYS:
            subset = subset[subset[k] == v['params'][k]]
        checks['variant_csv_counts_and_means'] &= (len(subset)==v['n_events'] and
            (len(subset)==0 or abs(subset.net_excess.mean()-v['mean_net_excess']) < 1e-12))
    checks['all_placebo_draws_present'] = all(len(v['placebo']['mean_distribution'])==499 for v in r['variants'])
    checks['all_directional_p_values_valid'] = all(0 < v['placebo_directional_p'] <= 1 for v in r['variants'])

    with Snapshot() as snapshot:
        c = snapshot.connection
        c.execute('SET threads=2')
        c.execute("SET memory_limit='2GB'")
        inspect(c)
        cal = Calendar.normal_sessions(row[0] for row in c.execute("""SELECT date FROM index_tri
            WHERE index_name='NIFTY 50' AND date BETWEEN '2019-01-01' AND '2025-12-31'""").fetchall())
        positions = {pd.Timestamp(d):i for i,d in enumerate(cal.days)}
        en = events.entry.map(positions).to_numpy()
        scheduled = events.scheduled_exit.map(positions).to_numpy()
        exits = events.exit.map(positions).to_numpy()
        checks['scheduled_exit_horizons_exact'] = bool(np.all(scheduled-en==events.horizon))
        checks['exit_delays_exact'] = bool(np.all(exits-scheduled==events.exit_delay_sessions))
        expected_entry = np.searchsorted(np.array(cal.days,dtype='datetime64[D]'),
                                        events.decision_trigger.to_numpy().astype('datetime64[D]'), side='right')
        checks['t_plus_one_entries_exact'] = bool(np.all(expected_entry==en))
        rules = load_tax(c)
        pairs = events[['entry','exit','gross_return','stock_net']].drop_duplicates()
        errors = [abs(sale(row.gross_return,row.entry.date(),row.exit.date(),rules)['net_return']-row.stock_net)
                  for row in pairs.itertuples()]
        checks['event_tax_cost_matches_scalar'] = max(errors,default=0.) < 1e-12
        benchmark = B5Path(load_indexes(c),cal,rules)
        distinct = events[['entry','exit','stock_net','net_excess']].copy()
        distinct['en'], distinct['ex'] = en, exits
        expected_b5 = {(int(a),int(b)):benchmark.event_return(int(a),int(b))
                       for a,b in distinct[['en','ex']].drop_duplicates().itertuples(index=False,name=None)}
        checks['b5_matched_to_actual_exit'] = max((abs(row.stock_net-row.net_excess-expected_b5[row.en,row.ex])
                                                  for row in distinct.itertuples()),default=0.) < 1e-12
        checks['all_b5_choices_prior_and_weekday'] = all(choice['asof_date']<choice['month']
            and choice['asof_date'].weekday()<5 and choice['base_date'].weekday()<5 for choice in benchmark.choices)

        quote_keys = pd.concat([events[['entity','entry']].rename(columns={'entry':'day'}),
                                events[['entity','exit']].rename(columns={'exit':'day'})]).drop_duplicates()
        c.register('h01_quote_keys',quote_keys)
        quotes = c.execute("""SELECT k.entity,k.day,p.adj_open*p.cum_div_factor tr_open,p.tr_close
            FROM h01_quote_keys k LEFT JOIN px_daily p ON p.entity_id=k.entity AND p.date=k.day""").df()
        qmap = {(row.entity,pd.Timestamp(row.day)):(row.tr_open,row.tr_close) for row in quotes.itertuples()}
        checks['entry_prices_match_source'] = max((abs(qmap[row.entity,row.entry][0]-row.entry_open_tr)
                                                  for row in events.itertuples()),default=0.) < 1e-8
        quoted = events[~events.exit_missing_loss_bound]
        checks['returns_match_actual_source_close'] = max((abs(qmap[row.entity,row.exit][1]/row.entry_open_tr-1-row.gross_return)
                                                          for row in quoted.itertuples()),default=0.) < 1e-12

        exit_keys = events[['entity','scheduled_exit']].drop_duplicates().copy()
        c.register('h01_exit_keys',exit_keys)
        c.register('h01_sessions',pd.DataFrame({'day':pd.to_datetime(cal.days)}))
        actual_exits = c.execute("""SELECT e.entity,e.scheduled_exit,min(p.date) first_exit
            FROM h01_exit_keys e LEFT JOIN (
              SELECT p.entity_id,p.date FROM px_daily p JOIN h01_sessions s ON p.date=s.day
              WHERE p.tr_close>0 AND isfinite(p.tr_close)
            ) p ON p.entity_id=e.entity AND p.date>=e.scheduled_exit
            GROUP BY e.entity,e.scheduled_exit""").df()
        exit_map = {(row.entity,pd.Timestamp(row.scheduled_exit)):row.first_exit for row in actual_exits.itertuples()}
        checks['first_available_exit_or_true_boundary_censoring'] = all(
            (pd.isna(exit_map[row.entity,row.scheduled_exit]) and row.exit_missing_loss_bound
             and row.exit==pd.Timestamp(cal.days[-1]) and abs(row.gross_return+1)<1e-12)
            or (not row.exit_missing_loss_bound and pd.Timestamp(exit_map[row.entity,row.scheduled_exit])==row.exit)
            for row in events.itertuples())

        files = events[['file']].drop_duplicates()
        c.register('h01_files',files)
        stamps = c.execute("""SELECT f.file,f.known_at_utc FROM results_filings f
            JOIN h01_files k ON k.file=f.file""").fetchall()
        known = {file:pd.Timestamp(stamp+timedelta(hours=5,minutes=30)) for file,stamp in stamps}
        checks['all_xbrl_dates_match_source'] = all(known[row.file]==row.xbrl_at for row in events.itertuples())

        # First written rows and a deterministic sample: compare BSE timestamps
        # directly, without trusting the persisted derived available_at field.
        sample = pd.concat([events.head(10),events.sample(n=min(50,len(events)),random_state=20261021)]).drop_duplicates(['file','trigger'])
        checks['sample_bse_dates_match_source'] = True
        first_rows = []
        for row in sample.itertuples():
            match = c.execute("""SELECT a.DissemDT,a.NEWSSUB FROM bse_ann a
                JOIN security_master s ON cast(a.SCRIP_CD AS VARCHAR)=cast(s.bse_code AS VARCHAR)
                WHERE s.issuer=? AND a.SUBCATNAME='Financial Results'
                AND try_cast(a.DissemDT AS TIMESTAMP)=? LIMIT 1""",[row.entity,row.trigger.to_pydatetime()]).fetchone()
            checks['sample_bse_dates_match_source'] &= match is not None
            if len(first_rows)<10:
                first_rows.append({'file':row.file,'entity':row.entity,'source_bse_ist':match[0] if match else None,
                                   'source_subject':match[1] if match else None,'source_xbrl_ist':str(known[row.file]),
                                   'written_entry':str(row.entry),'policy':row.entry_timing})

    checks['book_cash_nonnegative'] = all(p['cash']>=-1e-6 for b in r['books'].values() for p in b['nav'])
    checks['no_buys_after_kill'] = all(b['kill_date'] is None or all(
        f['side']!='buy' or f['date']<=b['kill_date'] for f in b['fills']) for b in r['books'].values())
    checks['book_drawdown_and_kill_recompute'] = True
    for b in r['books'].values():
        peak = b['initial_allocation_inr']
        worst = 0.
        first_breach = None
        for point in b['nav']:
            peak = max(peak,point['allocation_nav'])
            dd = 1-point['allocation_nav']/peak
            worst = max(worst,dd)
            if dd>.08 and first_breach is None:
                first_breach = point['date']
        checks['book_drawdown_and_kill_recompute'] &= abs(worst-b['max_drawdown'])<1e-12 and first_breach==b['kill_date']
    import duckdb
    with duckdb.connect(str(LEDGER),read_only=True) as c:
        all_rows = c.execute('SELECT run_id,p FROM variants ORDER BY run_timestamp,row_id').fetchall()
        current = c.execute('SELECT variant_params,p,bh_q FROM variants WHERE run_id=?',[r['ledger_run_id']]).fetchall()
        checks['ledger_appended_sixteen'] = len(current)==16
        old_p = [p for run,p in all_rows if run!=r['ledger_run_id']]
        qs = bh_fdr(old_p+[v['p'] for v in r['variants']])[-16:]
        checks['bh_keeps_all_prior_tests'] = len(old_p)==r['fdr_scope']['prior_ledger_tests'] and all(
            abs(q-v['bh_q'])<1e-12 for q,v in zip(qs,r['variants']))
        notes = c.execute("SELECT run_id,note FROM run_notes WHERE note LIKE '%superseded_by_bugfix%'").fetchall()
        checks['buggy_runs_annotated_and_retained'] = set(r['superseded_buggy_runs']) <= {run for run,note in notes}
    checks = {k:bool(v) for k,v in checks.items()}
    payload = {'run_id':r['ledger_run_id'],'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
               'checks':checks,'all_checks_pass':all(checks.values()),
               'first_written_rows_source_comparison':first_rows,'event_rows_checked':len(events),
               'verifier_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (OUT/'H01_verification.json').write_text(json.dumps(payload,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'run_id':r['ledger_run_id'],'event_rows':len(events),
                      'checks':len(checks),'failed':[k for k,v in checks.items() if not v]},indent=2))
    if not all(checks.values()):
        raise AssertionError('H01 artifact verification failed')


if __name__=='__main__':
    main()
