"""Independent longer-horizon artifact/source review; no inference/live DB."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .adapter import inspect, load_tax, load_filings, load_indexes
from .benchmark import B5Path
from .cards.h01_pead import surprise
from .data import ROOT, Snapshot, Calendar
from .ledger import LEDGER
from .stats import bh_fdr
from .run_h01_long import VARIANTS, label

OUT = ROOT/'tasks/backtests'


def main():
    r = json.loads((OUT/'H01_long_results.json').read_text(encoding='utf-8'))
    frame = pd.read_csv(OUT/'H01_long_outcomes.csv.gz')
    for field in ('entry','exit','scheduled_exit','trigger','xbrl_at','decision_trigger'):
        frame[field] = pd.to_datetime(frame[field],format='mixed')
    checks = {'declared_grid_exact': {label(v['params']) for v in r['variants']}=={label(v) for v in VARIANTS},
              'source_hashes_match':all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==v for p,v in r['source_sha256'].items()),
              'snapshot_unchanged':r['snapshot_file_unchanged'],
              'no_2026_outcomes':bool((frame.entry.ge('2021-01-01')&frame.exit.le('2025-12-31')).all()),
              'no_duplicate_audit_outcomes':not frame.duplicated(['entry_timing','horizon','record_id']).any(),
              'all499_placebos':all(len(v['placebo']['mean_distribution'])==499 for v in r['variants']),
              'prior_short_report_preserved':len(json.loads((OUT/'H01_results.json').read_text(encoding='utf-8'))['variants'])==16}
    checks['cohort_counts_means_and_ltcg'] = True
    matched_sets = defaultdict(list)
    for row in r['variants']:
        p = row['params']
        part = frame[(frame.entry_timing==p['entry_timing'])&(frame.horizon==p['horizon'])]
        scores = part[p['measure']+'_surprise']
        mask = scores.gt(0) if p['sign']=='positive' else scores.lt(0)
        if p['cohort']!='any':
            mask &= scores.abs().ge(1 if p['cohort']=='abs_ge_1' else 2)
        if p['cohort']=='abs_ge_2_trend200':
            mask &= part.trend200.eq(1 if p['sign']=='positive' else -1)
        if p['sample']=='common_504':
            mask &= part.common_504
        group = part[mask]
        long_n = int(((group.exit-group.entry).dt.days>365).sum())
        checks['cohort_counts_means_and_ltcg'] &= (len(group)==row['n_events'] and long_n==row['ltcg_events']
            and group.entity.nunique()==row['unique_issuers'] and
            (len(group)==0 or abs(group.net_excess.mean()-row['mean_net_excess'])<1e-12))
        if p['sample']=='common_504':
            matched_sets[p['cohort']].append(set(group.record_id))
    checks['matched_entry_identity_across_all_horizons'] = all(len(sets)==7 and all(v==sets[0] for v in sets) for sets in matched_sets.values())
    checks['conservative_inference_p'] = all(abs(row['p']-max(row['cluster_p'],row['hac']['p']))<1e-12 for row in r['variants'])
    checks['two_year_precision_not_invented'] = all(not row['hac']['sufficient_support'] and row['hac']['p']==1.
                                                  for row in r['variants'] if row['params']['horizon']==504)
    first_rows = []
    with Snapshot() as snapshot:
        c = snapshot.connection
        c.execute('SET threads=2')
        c.execute("SET memory_limit='2GB'")
        inspect(c)
        cal = Calendar.normal_sessions(row[0] for row in c.execute("""SELECT date FROM index_tri
            WHERE index_name='NIFTY 50' AND date BETWEEN '2019-01-01' AND '2025-12-31'""").fetchall())
        days = np.array(cal.days,dtype='datetime64[D]')
        en = np.searchsorted(days,frame.entry.to_numpy().astype('datetime64[D]'))
        ex = np.searchsorted(days,frame.exit.to_numpy().astype('datetime64[D]'))
        scheduled = np.searchsorted(days,frame.scheduled_exit.to_numpy().astype('datetime64[D]'))
        entries_expected = np.searchsorted(days,frame.decision_trigger.to_numpy().astype('datetime64[D]'),side='right')
        checks['exact_t_plus_one_and_horizons'] = bool(np.all(en==entries_expected)&np.all(scheduled-en==frame.horizon)
                                                       &np.all(ex-scheduled==frame.exit_delay_sessions))
        checks['audit_index_matches_calendar'] = bool(np.all(en==frame.entry_index)&np.all(ex==frame.exit_index))
        checks['all_regular_session_fills'] = bool((frame.entry.dt.dayofweek.lt(5)&frame.exit.dt.dayofweek.lt(5)).all())
        later = frame[['trigger','xbrl_at']].max(axis=1)
        decision = frame.trigger.where(frame.entry_timing=='bse_next_open',later)
        checks['policy_and_numbers_available_before_open'] = bool((decision==frame.decision_trigger).all()
            and (later<frame.entry+pd.Timedelta(hours=9,minutes=15)).all())
        rules = load_tax(c)
        rate_st = {d:rules.rule('stcg_rate',d.date()) for d in frame.exit.unique().astype('datetime64[us]').tolist()}
        rate_lt = {d:rules.rule('ltcg_rate',d.date()) for d in frame.exit.unique().astype('datetime64[us]').tolist()}
        st = frame.exit.map(rate_st).to_numpy()
        lt = frame.exit.map(rate_lt).to_numpy()
        expected_net = frame.gross_return-.003-np.maximum(frame.gross_return,0)*np.where((frame.exit-frame.entry).dt.days>365,lt,st)
        checks['calendar_day_stcg_ltcg_and_costs'] = bool(np.max(np.abs(expected_net-frame.stock_net))<1e-12)
        checks['excess_arithmetic'] = bool(np.max(np.abs(frame.stock_net-frame.b5_net-frame.net_excess))<1e-12)
        benchmark = B5Path(load_indexes(c),cal,rules)
        bench_sample = frame[['entry_index','exit_index','b5_net']].drop_duplicates().sample(
            n=min(100,len(frame[['entry_index','exit_index','b5_net']].drop_duplicates())),random_state=20261021)
        checks['sample_b5_matches_actual_long_exit'] = all(abs(benchmark.event_return(int(a),int(b))-value)<1e-12
            for a,b,value in bench_sample.itertuples(index=False,name=None))
        quotes = pd.concat([frame[['entity','entry']].rename(columns={'entry':'day'}),
                            frame[['entity','exit']].rename(columns={'exit':'day'})]).drop_duplicates()
        c.register('h01_long_quote_keys',quotes)
        source = c.execute("""SELECT k.entity,k.day,p.adj_open*p.cum_div_factor tr_open,p.tr_close
            FROM h01_long_quote_keys k LEFT JOIN px_daily p ON p.entity_id=k.entity AND p.date=k.day""").df()
        qmap = {(row.entity,pd.Timestamp(row.day)):(row.tr_open,row.tr_close) for row in source.itertuples()}
        checks['all_entry_prices_from_source'] = max(abs(qmap[row.entity,row.entry][0]-row.entry_price) for row in frame.itertuples())<1e-8
        checks['all_exit_returns_from_source'] = max(abs(qmap[row.entity,row.exit][1]/row.entry_price-1-row.gross_return)
            for row in frame[~frame.unresolved_exit].itertuples())<1e-12
        records,_ = load_filings(c)
        by_file = {row['file']:row for row in records}
        histories = defaultdict(list)
        for row in records:
            histories[row['entity']].append(row)
        checks['all_written_filing_dates_from_source'] = all(by_file[row.file]['xbrl_at']==row.xbrl_at.to_pydatetime()
            and by_file[row.file]['trigger']==row.trigger.to_pydatetime() for row in frame.itertuples())
        sample = pd.concat([frame.head(10),frame.sample(n=min(50,len(frame)),random_state=20261021)]).drop_duplicates(['file','entry_timing'])
        checks['sample_surprises_pit_recomputed'] = True
        checks['sample_trend_only_prior200_sessions'] = True
        c.register('h01_long_sessions',pd.DataFrame({'day':pd.to_datetime(cal.days)}))
        delayed = frame[frame.exit_delay_sessions.gt(0)|frame.unresolved_exit][['entity','scheduled_exit','exit','unresolved_exit']].drop_duplicates()
        checks['delayed_exit_uses_first_actual_quote'] = True
        for row in delayed.itertuples():
            first = c.execute("""SELECT min(p.date) FROM px_daily p JOIN h01_long_sessions s ON p.date=s.day
                WHERE p.entity_id=? AND p.date>=? AND p.tr_close>0 AND isfinite(p.tr_close)""",
                [row.entity,row.scheduled_exit.to_pydatetime()]).fetchone()[0]
            checks['delayed_exit_uses_first_actual_quote'] &= (first is None if row.unresolved_exit else pd.Timestamp(first)==row.exit)
        for row in sample.itertuples():
            current = {**by_file[row.file],'trigger':row.decision_trigger.to_pydatetime()}
            for measure in ('PAT','revenue'):
                score = getattr(row,measure+'_surprise')
                if not np.isfinite(score):
                    continue
                value = surprise(current,histories[row.entity],measure)
                checks['sample_surprises_pit_recomputed'] &= value is not None and abs(value['surprise']-score)<1e-8
            decision_stamp = row.decision_trigger
            signal = int(np.searchsorted(days,np.datetime64(decision_stamp.date()),side='right')-1)
            if days[signal]==np.datetime64(decision_stamp.date()) and (decision_stamp.hour*60+decision_stamp.minute)<930:
                signal-=1
            prior_dates = days[max(0,signal-199):signal+1]
            history = c.execute("""SELECT s.day,p.tr_close FROM h01_long_sessions s LEFT JOIN px_daily p
                ON p.date=s.day AND p.entity_id=? WHERE s.day BETWEEN ? AND ? ORDER BY s.day""",
                [row.entity,str(prior_dates[0]),str(prior_dates[-1])]).fetchall()
            closes = np.array([np.nan if v is None else v for _,v in history])
            trend = int(np.sign(closes[-1]-closes.mean())) if len(closes)==200 and np.isfinite(closes).all() and np.all(closes>0) else 0
            checks['sample_trend_only_prior200_sessions'] &= trend==row.trend200
            if len(first_rows)<10:
                first_rows.append({'file':row.file,'source_bse_ist':str(by_file[row.file]['trigger']),
                    'source_xbrl_ist':str(by_file[row.file]['xbrl_at']),'written_entry':str(row.entry),
                    'written_exit':str(row.exit),'trend_recomputed':trend})

        # Buy capacity is based only on the preceding20 normal sessions.
        cap_cache = {}
        checks['all_book_buys_within_liquidity_cap'] = True
        checks['all_books_cash_drawdown_and_kill'] = True
        book_labels = set()
        with gzip.open(OUT/'H01_long_books.jsonl.gz','rt',encoding='utf-8') as fh:
            for line in fh:
                book = json.loads(line)
                book_labels.add(book['variant'])
                peak = book['initial_allocation_inr']
                total_peak = 10_000_000.
                first_kill = None
                worst = 0.
                previous_b5 = None
                for point in book['nav']:
                    peak = max(peak,point['allocation_nav'])
                    total_peak = max(total_peak,point['total_nav'])
                    dd = 1-point['allocation_nav']/peak
                    pdd = 1-point['total_nav']/total_peak
                    limit = .08 if previous_b5 is not None and point['b5_unit_nav']<previous_b5 else .05
                    previous_b5 = point['b5_unit_nav']
                    worst = max(worst,dd)
                    if first_kill is None and (dd>.08 or pdd>limit):
                        first_kill = point['date']
                    checks['all_books_cash_drawdown_and_kill'] &= point['cash']>=-1e-6 and abs(dd-point['drawdown'])<1e-12
                checks['all_books_cash_drawdown_and_kill'] &= first_kill==book['kill_date'] and abs(worst-book['max_drawdown'])<1e-12
                for fill in book['fills']:
                    if fill['side']!='buy':
                        continue
                    checks['all_books_cash_drawdown_and_kill'] &= book['kill_date'] is None or fill['date']<=book['kill_date']
                    key = fill['isin'],fill['date']
                    if key not in cap_cache:
                        idx = int(np.searchsorted(days,np.datetime64(fill['date'])))
                        last = c.execute("""SELECT p.value_inr FROM h01_long_sessions s LEFT JOIN px_daily p
                            ON p.date=s.day AND p.entity_id=? WHERE s.day>=? AND s.day<? ORDER BY s.day""",
                            [fill['isin'],str(days[idx-20]),fill['date']]).fetchall()
                        cap_cache[key] = .1*np.mean([value for value, in last]) if len(last)==20 and all(value is not None for value, in last) else 0.
                    checks['all_book_buys_within_liquidity_cap'] &= fill['qty']*fill['price']<=cap_cache[key]+1e-6
        checks['all_positive_books_present'] = book_labels=={label(v) for v in VARIANTS if v['sign']=='positive'}
    import duckdb
    with duckdb.connect(str(LEDGER),read_only=True) as c:
        ledger = c.execute('SELECT run_id,p FROM variants ORDER BY run_timestamp,row_id').fetchall()
        current = c.execute('SELECT count(*) FROM variants WHERE run_id=?',[r['ledger_run_id']]).fetchone()[0]
    prior = [p for run,p in ledger if run!=r['ledger_run_id']]
    qs = bh_fdr(prior+[row['p'] for row in r['variants']])[-174:]
    checks['all_tests_logged_and_prior_family_retained'] = current==174 and len(prior)==r['fdr_scope']['prior_ledger_tests'] and all(
        abs(q-row['bh_q'])<1e-12 for q,row in zip(qs,r['variants']))
    checks = {k:bool(v) for k,v in checks.items()}
    payload = {'run_id':r['ledger_run_id'],'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
        'checks':checks,'all_checks_pass':all(checks.values()),'outcomes':len(frame),'first_written_rows':first_rows,
        'verifier_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (OUT/'H01_long_verification.json').write_text(json.dumps(payload,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'run_id':r['ledger_run_id'],'checks':len(checks),'outcomes':len(frame),
                      'failed':[k for k,v in checks.items() if not v]},indent=2))
    if not all(checks.values()):
        raise AssertionError('H01 longer-horizon verification failed')


if __name__=='__main__':
    main()
