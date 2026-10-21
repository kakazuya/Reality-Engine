"""Source, FIFO, chronology and executable-price review of the H01 wall."""
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .adapter import inspect, load_tax
from .costs_tax import tax_on_gains
from .data import ROOT, Snapshot, Calendar
from .ledger import LEDGER
from .stats import bh_fdr

OUT = ROOT/'tasks/backtests'
RISK_REASONS = {'fixed5','trail8','market200','stock_sma50'}


def main():
    r = json.loads((OUT/'H01_wall_results.json').read_text(encoding='utf-8'))
    falls = pd.read_csv(OUT/'H01_falls.csv.gz')
    books = [json.loads(line) for line in gzip.open(OUT/'H01_wall_books.jsonl.gz','rt',encoding='utf-8')]
    params = {row['params']['guard']:row['params'] for row in r['variants']}
    checks = {'eight_books_and_variants':len(books)==8 and set(params)=={b['guard'] for b in books},
              'source_hashes_match':all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==v for p,v in r['source_sha256'].items()),
              'source_snapshot_unchanged':r['snapshot_read_only'] and r['snapshot_file_unchanged'],
              'baseline_matches_prior_saved_nav':r['baseline_audit']['reproduces_prior_book'],
              'baseline_daily_attribution_reconciles':r['baseline_audit']['max_daily_reconciliation_error_inr']<1e-5,
              'all_source_fill_prices':True,'all_fifo_fees_taxes':True,'all_cash_and_nav_replay':True,
              'all_kill_dates_and_no_later_buys':True,'caps_use_open_pretrade_nav':True,
              'risk_decisions_use_source_eod_information':True,'risk_fills_next_real_open':True,
              'no_same_day_risk_reentry':True,'risk_admissions_use_only_prior_quotes':True}
    overshoots,stopped_winners = [],defaultdict(int)
    with Snapshot() as snapshot:
        c = snapshot.connection
        c.execute('SET threads=2')
        c.execute("SET memory_limit='2GB'")
        inspect(c)
        cal = Calendar.normal_sessions(row[0] for row in c.execute("""SELECT date FROM index_tri
            WHERE index_name='NIFTY 50' AND date BETWEEN '2019-01-01' AND '2025-12-31'""").fetchall())
        days = np.array(cal.days,dtype='datetime64[D]')
        day_index = {str(day):i for i,day in enumerate(cal.days)}
        entities = sorted(set(falls.entity)|{f['isin'] for b in books for f in b['fills']})
        col = {entity:j for j,entity in enumerate(entities)}
        c.register('wall_verify_entities',pd.DataFrame({'entity':entities}))
        quotes = c.execute("""SELECT p.entity_id,p.date,p.adj_open*p.cum_div_factor tr_open,p.tr_close,p.value_inr
            FROM px_daily p JOIN wall_verify_entities e ON p.entity_id=e.entity
            WHERE p.date BETWEEN '2019-01-01' AND '2025-12-31'""").df()
        def matrix(field):
            return quotes.pivot(index='date',columns='entity_id',values=field).reindex(index=pd.to_datetime(days),columns=entities).to_numpy()
        opens,closes,values = matrix('tr_open'),matrix('tr_close'),matrix('value_inr')
        sma50 = pd.DataFrame(closes).rolling(50,min_periods=50).mean().to_numpy()
        adtv = pd.DataFrame(values).rolling(20,min_periods=20).mean().shift(1).to_numpy()
        index_rows = c.execute("SELECT index_name,cast(date AS DATE),tri FROM index_tri WHERE date<'2026-01-01'").fetchall()
        index_values = defaultdict(dict)
        for name,day,level in index_rows:
            index_values[name.upper()][str(day)] = level
        long_r = json.loads((OUT/'H01_long_results.json').read_text(encoding='utf-8'))
        chosen = {v['month']:v['index'].upper() for v in long_r['benchmark_choices']}
        level_arrays = {name:np.array([data.get(str(day),np.nan) for day in cal.days]) for name,data in index_values.items()}
        ma200 = {name:pd.Series(array).rolling(200,min_periods=200).mean().to_numpy() for name,array in level_arrays.items()}
        def market_pass(day,i):
            name = chosen[day[:7]+'-01']
            return np.isfinite(ma200[name][i]) and level_arrays[name][i]>ma200[name][i]
        rules = load_tax(c)
        original = pd.read_csv(OUT/'H01_long_outcomes.csv.gz')
        original = original[(original.entry_timing=='both_known_next_open')&original.horizon.eq(180)&original.PAT_surprise.gt(0)]
        winner = {(row.entity,row.entry):row.net_excess>0 for row in original.itertuples()}
        for book in books:
            p = params[book['guard']]
            by_day = defaultdict(list)
            decisions = defaultdict(list)
            for fill in book['fills']:
                by_day[fill['date']].append(fill)
            for decision in book['risk_decisions']:
                decisions[decision['date']].append(decision)
            lots,marks,peaks,entry_dates = {},{},{},{}
            cash,peak,total_peak = book['initial_allocation_inr'],book['initial_allocation_inr'],10_000_000.
            allowance = {}
            first_kill,previous_b5 = None,None
            for point in book['nav']:
                day = point['date']; i = day_index[day]
                before_open = cash+sum(sum(t['qty'] for t in tranches)*(
                    opens[i,col[e]] if np.isfinite(opens[i,col[e]]) and opens[i,col[e]]>0 else marks[e])
                    for e,tranches in lots.items())
                risk_exited = {f['isin'] for f in by_day[day] if f['reason'] in RISK_REASONS}
                # Preserve exact fill sequence: open orders precede close orders.
                for fill in by_day[day]:
                    entity,j = fill['isin'],col[fill['isin']]
                    source_price = closes[i,j] if fill['reason']=='scheduled_exit' else opens[i,j]
                    checks['all_source_fill_prices'] &= np.isfinite(source_price) and abs(source_price-fill['price'])<1e-8
                    qty,price = fill['qty'],fill['price']
                    if fill['side']=='buy':
                        checks['no_same_day_risk_reentry'] &= entity not in risk_exited
                        checks['all_kill_dates_and_no_later_buys'] &= book['kill_date'] is None or day<=book['kill_date']
                        if p['market200']:
                            checks['risk_admissions_use_only_prior_quotes'] &= i>0 and market_pass(day,i-1)
                        if p['stop']=='sma50':
                            checks['risk_admissions_use_only_prior_quotes'] &= i>0 and np.isfinite(sma50[i-1,j]) and closes[i-1,j]>sma50[i-1,j]
                        if entity not in lots:
                            lots[entity]=[]
                            peaks[entity]=price
                            entry_dates[entity]=day
                        lots[entity].append({'qty':qty,'price':price,'entry':day})
                        cash -= qty*price+fill['fee']
                        expected_fee,expected_tax = qty*price*.0015,0.
                    else:
                        remaining,basis,gains = qty,0.,[]
                        for tranche in lots[entity]:
                            take = min(remaining,tranche['qty'])
                            if take>0:
                                basis += take*tranche['price']
                                gains.append({'gain':take*(price-tranche['price']),
                                              'holding_days':(pd.Timestamp(day)-pd.Timestamp(tranche['entry'])).days})
                                tranche['qty']-=take
                                remaining-=take
                        expected_fee = basis*.0015
                        expected_tax = tax_on_gains(gains,day,rules,allowance)
                        checks['all_fifo_fees_taxes'] &= abs(remaining)<1e-6
                        cash += qty*price-fill['fee']-fill['tax']
                        lots[entity]=[t for t in lots[entity] if t['qty']>1e-10]
                        if fill['reason'] in RISK_REASONS:
                            di = day_index[fill['risk_decision_date']]
                            available = np.flatnonzero(np.isfinite(opens[di+1:,j])&(opens[di+1:,j]>0))
                            checks['risk_fills_next_real_open'] &= i>di and len(available)>0 and i==di+1+available[0]
                            if winner.get((entity,entry_dates[entity]),False):
                                stopped_winners[book['guard']]+=1
                            if fill['reason'] in ('fixed5','trail8'):
                                reference = fill['risk_weighted_cost'] if fill['reason']=='fixed5' else fill['risk_peak_close']
                                threshold = reference*(.95 if fill['reason']=='fixed5' else .92)
                                overshoots.append({'guard':book['guard'],'entity':entity,'decision_date':fill['risk_decision_date'],
                                    'fill_date':day,'reason':fill['reason'],'actual_price':price,'threshold':threshold,
                                    'fill_below_threshold':price/threshold-1})
                        if not lots[entity]:
                            del lots[entity]
                    checks['all_fifo_fees_taxes'] &= abs(fill['fee']-expected_fee)<1e-6 and abs(fill['tax']-expected_tax)<1e-6
                    marks.setdefault(entity,price)
                    # Check caps using all open trades up to this point. At an
                    # intermediate admission a reduction later that same open
                    # may still be pending; final open state is checked below.
                # All caps are enforced before close fills; a close sale only
                # reduces exposure, so the remaining positions suffice here.
                if p['cap'] is not None:
                    for entity,tranches in lots.items():
                        j = col[entity]
                        op = opens[i,j]
                        if np.isfinite(op) and op>0:
                            notional = sum(t['qty'] for t in tranches)*op
                            checks['caps_use_open_pretrade_nav'] &= notional<=p['cap']*before_open+1e-5
                            checks['caps_use_open_pretrade_nav'] &= notional<=.1*adtv[i,j]+1e-5
                for entity,tranches in lots.items():
                    close = closes[i,col[entity]]
                    if np.isfinite(close) and close>0:
                        marks[entity]=close
                        peaks[entity]=max(peaks[entity],close)
                for decision in decisions[day]:
                    entity,j = decision['isin'],col[decision['isin']]
                    tranches = lots[entity]
                    qty = sum(t['qty'] for t in tranches)
                    basis = sum(t['qty']*t['price'] for t in tranches)/qty
                    close = closes[i,j]
                    observed = decision['observed_close']
                    if observed is not None:
                        checks['risk_decisions_use_source_eod_information'] &= abs(close-observed)<1e-8
                    checks['risk_decisions_use_source_eod_information'] &= abs(basis-decision['weighted_cost'])<1e-8 and abs(peaks[entity]-decision['peak_close'])<1e-8
                    reason = decision['reason']
                    if reason=='market200':
                        condition = p['market200'] and not market_pass(day,i)
                    elif reason=='fixed5':
                        condition = p['stop']=='fixed5' and close<=basis*.95+1e-10
                    elif reason=='trail8':
                        condition = p['stop']=='trail8' and close<=peaks[entity]*.92+1e-10
                    else:
                        condition = p['stop']=='sma50' and np.isfinite(sma50[i,j]) and close<sma50[i,j]
                    checks['risk_decisions_use_source_eod_information'] &= condition
                value = sum(sum(t['qty'] for t in tranches)*marks[e] for e,tranches in lots.items())
                if day==book['nav'][-1]['date'] and book['unresolved_holdings']:
                    value=0.
                reconstructed = cash+value
                checks['all_cash_and_nav_replay'] &= abs(cash-point['cash'])<1e-5 and abs(reconstructed-point['allocation_nav'])<1e-5 and cash>=-1e-6
                total = 9_000_000.+reconstructed
                peak,total_peak = max(peak,reconstructed),max(total_peak,total)
                dd,pdd = 1-reconstructed/peak,1-total/total_peak
                limit = .08 if previous_b5 is not None and point['b5_unit_nav']<previous_b5 else .05
                previous_b5 = point['b5_unit_nav']
                if first_kill is None and (dd>.08 or pdd>limit):
                    first_kill=day
            checks['all_kill_dates_and_no_later_buys'] &= first_kill==book['kill_date']

        # Rebuild every retrospective fall path independently from source.
        en = np.array([day_index[d] for d in falls.entry])
        js = np.array([col[e] for e in falls.entity])
        windows = closes[en[:,None]+np.arange(181),js[:,None]]
        valid = np.isfinite(windows)&(windows>0)
        entry_price = opens[en,js]
        ret = windows/entry_price[:,None]-1
        peak_path = np.maximum.accumulate(np.where(valid,np.maximum(windows,entry_price[:,None]),entry_price[:,None]),axis=1)
        drawdown = 1-windows/peak_path
        checks['all4285_fall_paths_recompute'] = len(falls)==4285
        for mask,column in [(valid&(ret<0),'first_below_entry_age'),(valid&(ret<=-.05),'first_loss5_age'),
                            (valid&(ret<=-.08),'first_loss8_age'),(valid&(drawdown>=.08),'first_trail8_age')]:
            first = np.where(mask.any(axis=1),mask.argmax(axis=1),-1)
            checks['all4285_fall_paths_recompute'] &= bool(np.all(first==falls[column]))
        mae_age = np.argmin(np.where(valid,ret,np.inf),axis=1)
        dd_age = np.argmax(np.where(valid,drawdown,-np.inf),axis=1)
        checks['all4285_fall_paths_recompute'] &= (np.all(mae_age==falls.worst_entry_return_age) and np.all(dd_age==falls.max_close_drawdown_age)
            and np.max(np.abs(ret[np.arange(len(falls)),mae_age]-falls.worst_entry_return))<1e-12
            and np.max(np.abs(drawdown[np.arange(len(falls)),dd_age]-falls.max_close_drawdown))<1e-12)
    # Reconstruct every bootstrap draw, using coherent blocks across guards.
    monthly = np.array([np.array(row['monthly_strategy_returns'])-row['monthly_b5_returns'] for row in r['variants']]).T
    checks['sixty_monthly_observations'] = monthly.shape==(60,8)
    centered = monthly-monthly.mean(axis=0)
    scale = monthly.std(axis=0,ddof=1)/np.sqrt(len(monthly))
    rng = np.random.default_rng(20261021)
    null = np.zeros((999,8)); max_t = np.zeros(999)
    for draw in range(999):
        starts = rng.integers(0,60,size=7)
        idx = np.concatenate([(s+np.arange(9))%60 for s in starts])[:60]
        null[draw]=centered[idx].mean(axis=0)
        max_t[draw]=np.max(np.abs(np.divide(null[draw],scale,out=np.zeros(8),where=scale>0)))
    checks['all999_bootstrap_draws_recompute'] = max(abs(np.array(row['bootstrap']['centered_monthly_mean_distribution'])-null[:,j]).max()
        for j,row in enumerate(r['variants']))<1e-12 and np.max(abs(max_t-r['bootstrap']['max_abs_t_distribution']))<1e-12
    import duckdb
    with duckdb.connect(str(LEDGER),read_only=True) as c:
        ledger = c.execute('SELECT run_id,p FROM variants ORDER BY run_timestamp,row_id').fetchall()
    prior = [p for run,p in ledger if run!=r['ledger_run_id']]
    qs = bh_fdr(prior+[row['p'] for row in r['variants']])[-8:]
    checks['all224_tests_retained_and_bh_recomputes'] = len(prior)==216 and sum(run==r['ledger_run_id'] for run,p in ledger)==8 and all(
        abs(q-row['bh_q'])<1e-12 for q,row in zip(qs,r['variants']))
    checks = {k:bool(v) for k,v in checks.items()}
    overshoots.sort(key=lambda row:row['fill_below_threshold'])
    payload = {'run_id':r['ledger_run_id'],'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
        'checks':checks,'all_checks_pass':all(checks.values()),'worst_stock_stop_gaps':overshoots[:10],
        'risk_exits_from_eventual_positive_excess_opportunities':dict(stopped_winners),
        'verifier_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (OUT/'H01_wall_verification.json').write_text(json.dumps(payload,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'checks':len(checks),'failed':[key for key,value in checks.items() if not value],
                      'worst_stop_gap':overshoots[:1],'stopped_eventual_winners':dict(stopped_winners)},indent=2))
    if not all(checks.values()):
        raise AssertionError('H01 downside-wall review failed')


if __name__=='__main__':
    main()
