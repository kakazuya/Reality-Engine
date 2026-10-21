"""Independent artifact checks; only snapshot and authorized ledger are read.

Run from repo root: python tasks/backtests/H01_verify.py
"""
import hashlib
import json
import sys
from bisect import bisect_right
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import duckdb
import numpy as np
import pandas as pd
from reality_engine.harness.data import Snapshot, Calendar
from reality_engine.harness.adapter import load_tax
from reality_engine.harness.costs_tax import sale


def main():
    out = ROOT/'tasks/backtests'
    r = json.loads((out/'H01_results.json').read_text(encoding='utf-8'))
    events = pd.read_csv(out/'H01_events.csv')
    checks = {}
    checks['all_source_hashes_match'] = all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==v
                                           for p,v in r['source_sha256'].items())
    with Snapshot() as snapshot:
        c = snapshot.connection
        rules = load_tax(c)
        days = [x[0] for x in c.execute("""select distinct cast(date as date) from index_tri
            where index_name='NIFTY 50' and date between '2019-01-01' and '2025-12-31' order by 1""").fetchall()]
        cal = Calendar(days)
        checks['t_plus_one_entries'] = all(cal.next_session(datetime.fromisoformat(x.trigger))==date.fromisoformat(x.entry)
                                          for x in events.itertuples())
        checks['exact_exit_horizons'] = all(cal.offset(date.fromisoformat(x.entry),x.horizon)==date.fromisoformat(x.exit)
                                           for x in events.itertuples())
        checks['no_2026_events'] = bool(all(events.entry.ge('2021-01-01') & events.exit.le('2025-12-31')))
        checks['numbers_known_before_open'] = all(datetime.fromisoformat(x.available_at)<datetime.fromisoformat(x.entry+'T09:15:00')
                                                 for x in events.itertuples())
        errors = [abs(sale(x.gross_return,x.entry,x.exit,rules)['net_return']-x.stock_net) for x in events.itertuples()]
        checks['cost_tax_max_absolute_error'] = max(errors)
        checks['cost_tax_matches_scalar_sale'] = max(errors)<1e-12
        checks['all_monthly_choices_before_period'] = all(v['asof_date']<v['month'] for v in r['benchmark_choices'])
        c.register('audit_events',events[['entity','entry','exit','entry_open_tr','gross_return','exit_missing_loss_bound']])
        errors = c.execute('''select max(abs(e.entry_open_tr-p.adj_open*p.cum_div_factor)),
          max(case when not e.exit_missing_loss_bound then abs(e.gross_return-(x.tr_close/(p.adj_open*p.cum_div_factor)-1)) else 0 end)
          from audit_events e join px_daily p on p.entity_id=e.entity and p.date=cast(e.entry as date)
          left join px_daily x on x.entity_id=e.entity and x.date=cast(e.exit as date)''').fetchone()
        checks['stock_open_price_max_error'],checks['stock_return_max_error'] = errors
        checks['prices_match_snapshot'] = max(errors)<1e-10
        signal_rows = []
        for row in events[['entity','trigger']].drop_duplicates().itertuples():
            stamp = datetime.fromisoformat(row.trigger)
            i = bisect_right(days,stamp.date())-1
            if days[i]==stamp.date() and (stamp.hour,stamp.minute)<(15,30):
                i -= 1
            signal_rows.append((row.entity,days[i]))
        c.register('audit_signals',pd.DataFrame(signal_rows,columns=['entity','day']))
        gates = c.execute('''with q as (select entity_id,date,close,
            median(value_inr) over(partition by entity_id order by date rows between 20 preceding and 1 preceding) med,
            count(*) over(partition by entity_id order by date rows between 20 preceding and 1 preceding) n
            from px_daily where date between '2019-01-01' and '2025-12-31')
            select min(close),min(med),min(n) from audit_signals s join q on s.entity=q.entity_id and s.day=q.date''').fetchone()
        checks['u1_raw_floor_min'] = gates[0]
        checks['u1_prior20_median_min_inr'] = gates[1]
        checks['u1_gates_recomputed'] = gates[0]>=10 and gates[1]>=r['liquidity_threshold_inr'] and gates[2]==20
        fills = []
        for name,book in r['books'].items():
            positions = {}
            for fill in book['fills']:
                qty = positions.get(fill['entity'],0.)+(fill['qty'] if fill['side']=='buy' else -fill['qty'])
                positions[fill['entity']] = qty
                if fill['side']=='buy':
                    fills.append((name,fill['entity'],fill['date'],qty*fill['price']))
        c.register('audit_buys',pd.DataFrame(fills,columns=['variant','entity','day','position_value']))
        cap = c.execute('''with q as (select entity_id,date,
            avg(value_inr) over(partition by entity_id order by date rows between 20 preceding and 1 preceding) a,
            count(*) over(partition by entity_id order by date rows between 20 preceding and 1 preceding) n from px_daily)
            select max(b.position_value-.1*q.a),min(n) from audit_buys b join q on b.entity=q.entity_id and cast(b.day as date)=q.date''').fetchone()
        checks['buy_liquidity_cap_max_excess_inr'] = cap[0]
        checks['buy_liquidity_cap_passed'] = cap[0]<=1e-6 and cap[1]==20
    checks['all_eight_variants_present'] = len(r['variants'])==8
    checks['all_variant_counts_match_csv'] = all(
        sum((events.horizon==v['params']['horizon'])&(events.measure==v['params']['measure'])&(events.sign==v['params']['sign']))==v['n_events']
        for v in r['variants'])
    checks['all_499_placebos_present'] = all(len(v['placebo']['mean_distribution'])==499 for v in r['variants'])
    checks['book_cash_nonnegative'] = all(min(p['cash'] for p in b['nav'])>=-1e-6 for b in r['books'].values())
    checks['kill_dates_match_first_gt_8pct'] = all(next((p['date'] for p in b['nav'] if p['drawdown']>.08),None)==b['kill_date']
                                                for b in r['books'].values())
    checks['no_buys_after_kill'] = all(all(f['side']!='buy' or f['date']<=b['kill_date'] for f in b['fills'])
                                      for b in r['books'].values() if b['kill_date'])
    checks['book_dd_recomputes'] = all(abs(max(1-p['allocation_nav']/max([1_000_000.]+[x['allocation_nav'] for x in b['nav'][:i+1]])
                                                    for i,p in enumerate(b['nav']))-b['max_drawdown'])<1e-12 for b in r['books'].values())
    with duckdb.connect(str(ROOT/'reality_engine/data/backtests/ledger.duckdb'),read_only=True) as c:
        ledger = c.execute('select count(*),count(distinct variant_params) from variants where run_id=?',[r['ledger_run_id']]).fetchone()
        checks['ledger_rows_this_run'] = ledger[0]
        checks['ledger_grid_complete'] = ledger==(8,8)
        prior = [p for rid,p in c.execute('select run_id,p from variants').fetchall() if rid!=r['ledger_run_id']]
        values = prior+[v['p'] for v in r['variants']]
        q = [1.]*len(values)
        running = 1.
        for rank,i in reversed(list(enumerate(sorted(range(len(values)),key=values.__getitem__),start=1))):
            running = min(running,len(values)*values[i]/rank)
            q[i] = running
        checks['bh_includes_prior_and_current_tests'] = len(values)==r['fdr_scope']['total_tests'] and all(
            abs(a-b['bh_q'])<1e-12 for a,b in zip(q[-8:],r['variants']))
        details = c.execute('select details from variants where run_id=?',[r['ledger_run_id']]).fetchall()
        checks['ledger_has_exact_working_source_hashes'] = all(json.loads(d[0])['source_sha256']==r['source_sha256'] for d in details)
    checks = {k:bool(v) if isinstance(v,np.bool_) else v for k,v in checks.items()}
    checks['all_boolean_checks_pass'] = all(v for v in checks.values() if type(v) is bool)
    (out/'H01_verification.json').write_text(json.dumps({'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
                                                      'run_id':r['ledger_run_id'],'checks':checks},indent=2),encoding='utf-8')
    print(json.dumps(checks,indent=2))
    assert checks['all_boolean_checks_pass']


if __name__=='__main__':
    main()
