"""H01 fall chronology and eight declared downside-control books."""
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from time import perf_counter

import numpy as np
import pandas as pd

from .adapter import inspect, Panel, Quotes, ADTV, load_indexes, load_tax
from .benchmark import B5Path, INDEX_NAMES
from .book import run_book
from .data import ROOT, Snapshot
from .ledger import append_variants, append_run_note, previous_tests
from .run_h01 import clean, code_provenance, progress, summarize_arrays
from .run_h01_long import horizon_hac
from .stats import bh_fdr

OUT = ROOT/'tasks/backtests'
GUARDS = (
    {'guard':'baseline','cap':None,'stop':None,'market200':False},
    {'guard':'cap10','cap':.10,'stop':None,'market200':False},
    {'guard':'cap10_stop5','cap':.10,'stop':'fixed5','market200':False},
    {'guard':'cap10_trail8','cap':.10,'stop':'trail8','market200':False},
    {'guard':'cap10_sma50','cap':.10,'stop':'sma50','market200':False},
    {'guard':'cap10_market200','cap':.10,'stop':None,'market200':True},
    {'guard':'cap10_trail8_market200','cap':.10,'stop':'trail8','market200':True},
    {'guard':'cap10_stop5_market200','cap':.10,'stop':'fixed5','market200':True})


def risk_features(panel, benchmark):
    sma50 = pd.DataFrame(panel.close).rolling(50,min_periods=50).mean().to_numpy()
    t = len(panel.days)
    admission, close_pass = np.zeros(t,dtype=bool),np.zeros(t,dtype=bool)
    market_sma, market_close = np.full(t,np.nan),np.full(t,np.nan)
    for name in INDEX_NAMES:
        levels = np.array([benchmark.series[name].get(day,(np.nan,''))[0] for day in panel.calendar.days])
        sma = pd.Series(levels).rolling(200,min_periods=200).mean().to_numpy()
        valid = np.isfinite(levels)&np.isfinite(sma)&(levels>0)&(sma>0)
        passes = valid&(levels>sma)
        for i,selected in enumerate(benchmark.names):
            if selected==name:
                close_pass[i] = passes[i]
                admission[i] = i>0 and passes[i-1]
                market_sma[i],market_close[i] = sma[i],levels[i]
    return {'sma50':sma50,'market_admission':admission,'market_close_pass':close_pass,
            'market_sma200':market_sma,'market_close':market_close}


class WallPolicy:
    def __init__(self,panel,features,params):
        self.panel,self.features,self.params = panel,features,params

    def admit(self,entity,day):
        p,f = self.panel,self.features
        i = int(np.searchsorted(p.days,np.datetime64(day)))
        j = p.col[entity]
        if self.params['market200'] and not f['market_admission'][i]:
            return False
        if self.params['stop']=='sma50':
            return i>0 and np.isfinite(f['sma50'][i-1,j]) and p.close[i-1,j]>f['sma50'][i-1,j]
        return True

    def exit_reason(self,entity,day,lot,close):
        p,f = self.panel,self.features
        i = int(np.searchsorted(p.days,np.datetime64(day)))
        j = p.col[entity]
        if self.params['market200'] and not f['market_close_pass'][i]:
            return 'market200'
        if close is None:
            return None
        stop = self.params['stop']
        basis = sum(t['qty']*t['cost_price'] for t in lot['tranches'])/lot['qty']
        if stop=='fixed5' and close<=basis*.95:
            return 'fixed5'
        if stop=='trail8' and close<=lot.get('peak_close',lot['cost_price'])*.92:
            return 'trail8'
        if stop=='sma50' and np.isfinite(f['sma50'][i,j]) and close<f['sma50'][i,j]:
            return 'stock_sma50'
        return None


def first_cross(mask):
    hit = mask.any(axis=1)
    return np.where(hit,np.argmax(mask,axis=1),-1)


def fall_paths(events,panel,names):
    en = events.entry_index.to_numpy(dtype=int)
    cols = np.array([panel.col[e] for e in events.entity])
    age = np.arange(181)
    quote = panel.close[en[:,None]+age,cols[:,None]]
    valid = np.isfinite(quote)&(quote>0)
    entry = panel.open[en,cols]
    returns = quote/entry[:,None]-1
    peaks = np.maximum.accumulate(np.where(valid,np.maximum(quote,entry[:,None]),entry[:,None]),axis=1)
    dd = 1-quote/peaks
    first_down = first_cross(valid&(returns<0))
    first5 = first_cross(valid&(returns<=-.05))
    first8 = first_cross(valid&(returns<=-.08))
    first_trail8 = first_cross(valid&(dd>=.08))
    adverse_age = np.argmin(np.where(valid,returns,np.inf),axis=1)
    worst_age = np.argmax(np.where(valid,dd,-np.inf),axis=1)
    audit = events[['record_id','entity','file','entry','scheduled_exit','net_excess','stock_net']].copy()
    audit['symbol'] = [names.get(e,{}).get('symbol') for e in events.entity]
    audit['first_below_entry_age'] = first_down
    audit['first_loss5_age'],audit['first_loss8_age'] = first5,first8
    audit['first_trail8_age'] = first_trail8
    for name,ages in [('first_loss5',first5),('first_loss8',first8),('first_trail8',first_trail8)]:
        audit[name+'_date'] = [str(panel.days[a+k]) if k>=0 else None for a,k in zip(en,ages)]
    audit['worst_entry_return'] = returns[np.arange(len(en)),adverse_age]
    audit['worst_entry_return_age'] = adverse_age
    audit['worst_entry_return_date'] = panel.days[en+adverse_age]
    audit['max_close_drawdown'] = dd[np.arange(len(en)),worst_age]
    audit['max_close_drawdown_age'] = worst_age
    audit['max_close_drawdown_date'] = panel.days[en+worst_age]
    summary = {}
    for name,column in [('loss5','first_loss5_age'),('loss8','first_loss8_age'),('trail8','first_trail8_age')]:
        a = audit[column].to_numpy()
        bins = {'0-5':int(np.sum((a>=0)&(a<=5))), '6-20':int(np.sum((a>=6)&(a<=20))),
                '21-60':int(np.sum((a>=21)&(a<=60))),'61-120':int(np.sum((a>=61)&(a<=120))),
                '121-180':int(np.sum((a>=121)&(a<=180))),'never':int(np.sum(a<0))}
        winners = audit.net_excess.to_numpy()>0
        summary[name] = {'first_crossing_age_bins':bins,'events_hit':int(np.sum(a>=0)),
                         'eventual_positive_excess_after_crossing':int(np.sum((a>=0)&winners)),
                         'eventual_positive_excess_after_crossing_by20':int(np.sum((a>=0)&(a<=20)&winners))}
    audit['entry_year'] = pd.to_datetime(audit.entry).dt.year
    by_year = audit.groupby('entry_year').agg(events=('record_id','count'),
        median_worst_entry_return=('worst_entry_return','median'),median_max_close_drawdown=('max_close_drawdown','median'))
    return audit,{'events':len(audit),'fall_timing':summary,'by_entry_year':by_year.reset_index().to_dict('records')}


def reconcile_attribution(book,panel,names):
    """P&L = end marked value - start value + net trading cash flow."""
    fills = defaultdict(list)
    for fill in book['fills']:
        fills[str(fill['date'])].append(fill)
    quantities,marks = {},{}
    rows = []
    previous_nav = book['initial_allocation_inr']
    max_error = 0.
    for point in book['nav']:
        day = str(point['date'])
        i = int(np.searchsorted(panel.days,np.datetime64(day)))
        start = {entity:q*marks[entity] for entity,q in quantities.items()}
        flow = defaultdict(float)
        fees,taxes = defaultdict(float),defaultdict(float)
        touched = set(quantities)
        for fill in fills.get(day,[]):
            entity = fill['isin']
            touched.add(entity)
            sign = 1 if fill['side']=='buy' else -1
            quantities[entity] = quantities.get(entity,0.)+sign*fill['qty']
            flow[entity] += -sign*fill['qty']*fill['price']-fill['fee']-fill['tax']
            fees[entity] += fill['fee']
            taxes[entity] += fill['tax']
            marks.setdefault(entity,fill['price'])
        total = 0.
        for entity in touched:
            price = panel.close[i,panel.col[entity]]
            if np.isfinite(price) and price>0:
                marks[entity] = price
            end = max(0.,quantities.get(entity,0.))*marks[entity]
            if point is book['nav'][-1] and book['unresolved_holdings']:
                end = 0.
            pnl = end-start.get(entity,0.)+flow[entity]
            total += pnl
            if abs(pnl)>1e-8 or fees[entity]:
                rows.append({'date':day,'entity':entity,'symbol':names.get(entity,{}).get('symbol'),
                             'pnl_inr':pnl,'start_value_inr':start.get(entity,0.),'end_value_inr':end,
                             'fees_inr':fees[entity],'taxes_inr':taxes[entity]})
        max_error = max(max_error,abs(total-(point['allocation_nav']-previous_nav)))
        previous_nav = point['allocation_nav']
        quantities = {e:q for e,q in quantities.items() if q>1e-8}
    frame = pd.DataFrame(rows)
    stock = frame.groupby(['entity','symbol'],dropna=False).agg(pnl_inr=('pnl_inr','sum'),
        fees_inr=('fees_inr','sum'),taxes_inr=('taxes_inr','sum')).reset_index().sort_values('pnl_inr')
    daily = frame.groupby('date').pnl_inr.sum().sort_values()
    return frame,{'max_daily_reconciliation_error_inr':max_error,'issuer_attribution':stock.to_dict('records'),
                  'worst_book_days':[{'date':d,'pnl_inr':v} for d,v in daily.head(10).items()]}


def monthly_returns(book,calendar,benchmark_nav):
    points = pd.DataFrame(book['nav'])
    points['month'] = pd.to_datetime(points.date).dt.to_period('M')
    endpoints = points.groupby('month',sort=True).tail(1)
    nav = np.r_[book['initial_allocation_inr'],endpoints.allocation_nav.to_numpy()]
    b5 = np.r_[1.,[benchmark_nav[d] for d in endpoints.date]]
    strategy,benchmark = nav[1:]/nav[:-1]-1,b5[1:]/b5[:-1]-1
    indices = np.array([calendar.days.index(d) for d in endpoints.date])
    return strategy,benchmark,indices


def block_bootstrap(matrix,rows,draws=999):
    """Same9-month circular blocks for all eight centered monthly series."""
    rng = np.random.default_rng(20261021)
    means = matrix.mean(axis=0)
    centered = matrix-means
    scales = matrix.std(axis=0,ddof=1)/np.sqrt(len(matrix))
    null = np.zeros((draws,matrix.shape[1]))
    max_t = np.zeros(draws)
    for draw in range(draws):
        starts = rng.integers(0,len(matrix),size=int(np.ceil(len(matrix)/9)))
        idx = np.concatenate([(s+np.arange(9))%len(matrix) for s in starts])[:len(matrix)]
        null[draw] = centered[idx].mean(axis=0)
        max_t[draw] = np.max(np.abs(np.divide(null[draw],scales,out=np.zeros_like(scales),where=scales>0)))
    for j,row in enumerate(rows):
        row['placebo_p'] = float((1+np.sum(np.abs(null[:,j])>=abs(means[j])))/(draws+1))
        row['placebo_directional_p'] = float((1+np.sum(null[:,j]>=means[j]))/(draws+1))
        observed_t = means[j]/scales[j] if scales[j]>0 else 0.
        row['reality_check_p'] = float((1+np.sum(max_t>=abs(observed_t)))/(draws+1))
        row['bootstrap'] = {'centered_monthly_mean_distribution':null[:,j],
                            'quantiles':np.quantile(null[:,j],[.025,.5,.975])}
    return {'draws':draws,'block_length_months':9,'max_abs_t_distribution':max_t,
            'method':'coherent circular9-month blocks, centered monthly book excess; current8-grid maxT'}


def main():
    started = perf_counter()
    if (OUT/'H01_wall_results.json').exists():
        raise FileExistsError('Preserve completed wall run before rerun')
    opportunities = pd.read_csv(OUT/'H01_long_outcomes.csv.gz')
    opportunities = opportunities[(opportunities.entry_timing=='both_known_next_open')&
        opportunities.horizon.eq(180)&opportunities.PAT_surprise.gt(0)].copy()
    progress(f'wall: {len(opportunities)} positivePAT180 opportunities; read-only source')
    with Snapshot() as snapshot:
        before = snapshot.path.stat()
        c = snapshot.connection
        c.execute('SET threads=2')
        c.execute("SET memory_limit='3GB'")
        inspect(c)
        panel = Panel(c)
        rules = load_tax(c)
        benchmark = B5Path(load_indexes(c),panel.calendar,rules)
        nav,_ = benchmark.book_nav()
        features = risk_features(panel,benchmark)
        names = {e:{'name':name,'symbol':symbol} for e,name,symbol in c.execute(
            'SELECT issuer,name,nse_symbol FROM security_master ORDER BY isin').fetchall()}
        events = [{'isin':row.entity,'entry':panel.calendar.days[int(row.entry_index)],
                   'exit':panel.calendar.days[int(row.entry_index)+180],'sign':'positive'}
                  for row in opportunities.itertuples()]
        falls,fall_summary = fall_paths(opportunities,panel,names)
        falls.to_csv(OUT/'H01_falls.csv.gz',index=False,compression='gzip')
        rows,books,monthly = [],{},[]
        with gzip.open(OUT/'H01_wall_books.jsonl.gz','wt',encoding='utf-8') as fh:
            for params in GUARDS:
                progress('wall book '+params['guard'])
                policy = WallPolicy(panel,features,params) if params['stop'] or params['market200'] else None
                book = run_book(events,panel.calendar,Quotes(panel),ADTV(panel),rules,nav,
                                issuer_fraction=params['cap'],risk_policy=policy)
                fh.write(json.dumps(clean({'guard':params['guard'],**book}),allow_nan=False)+'\n')
                stock,b5,indices = monthly_returns(book,panel.calendar,nav)
                excess = stock-b5
                row = summarize_arrays(excess,indices,benchmark.regime_up[indices],panel.days,detailed=True)
                hac = horizon_hac(excess,indices,panel.days,180)
                row.update({'params':{**params,'analysis':'downside_wall','horizon':180,'measure':'PAT',
                                      'entry_timing':'both_known_next_open','sign':'positive'},
                    'cluster_p':row['p'],'p':max(row['p'],hac['p']),'hac':hac,
                    'candidate_events':len(events),'mean_monthly_book_excess':float(excess.mean()),
                    'monthly_strategy_returns':stock,'monthly_b5_returns':b5,'monthly_dates':panel.days[indices]})
                rows.append(row)
                monthly.append(excess)
                books[params['guard']] = {k:v for k,v in book.items() if k not in ('nav','fills','risk_decisions')}
                books[params['guard']]['n_fills'] = len(book['fills'])
                books[params['guard']]['n_risk_decisions'] = len(book['risk_decisions'])
                books[params['guard']]['mean_cash_fraction'] = float(np.mean([point['cash']/point['allocation_nav'] for point in book['nav']]))
                if params['guard']=='baseline':
                    attribution,baseline_audit = reconcile_attribution(book,panel,names)
                    attribution.to_csv(OUT/'H01_baseline_fall_attribution.csv',index=False)
                    saved = None
                    with gzip.open(OUT/'H01_long_books.jsonl.gz','rt',encoding='utf-8') as old:
                        for line in old:
                            candidate = json.loads(line)
                            if candidate['variant']=='available_horizon|both_known_next_open|PAT|positive|any|180':
                                saved = candidate
                                break
                    baseline_audit['reproduces_prior_book'] = saved is not None and all(
                        abs(float(a['allocation_nav'])-b['allocation_nav'])<1e-6 for a,b in zip(book['nav'],saved['nav']))
                    baseline_audit['first_entry'] = str(next(fill['date'] for fill in book['fills'] if fill['side']=='buy'))
                    baseline_audit['first5_drawdown'] = next(str(p['date']) for p in book['nav'] if p['drawdown']>=.05)
                    baseline_audit['kill_date'] = str(book['kill_date'])
                    first_i = panel.calendar.days.index(next(fill['date'] for fill in book['fills'] if fill['side']=='buy'))
                    kill_i = panel.calendar.days.index(book['kill_date'])
                    baseline_audit['b5_gross_proxy_first_entry_to_kill'] = float(np.prod(benchmark.factors[first_i:kill_i+1])-1)
        matrix = np.array(monthly).T
        null = block_bootstrap(matrix,rows)
        prior = previous_tests()
        qs = bh_fdr([p for _,p in prior]+[row['p'] for row in rows])[-8:]
        for row,q in zip(rows,qs):
            row['bh_q'] = q
            book = books[row['params']['guard']]
            row['status'] = 'provisional_pass' if (q<=.05 and row['placebo_directional_p']<=.05 and row['reality_check_p']<=.05
                and book['kill_date'] is None and book['excess_cagr']>0 and not book['unresolved_holdings']) else 'fail'
            row['promoted'] = False
        git_hash,hashes = code_provenance()
        test = ROOT/'reality_engine/tests/test_harness_h01_wall.py'
        hashes[str(test.relative_to(ROOT)).replace('\\','/')] = hashlib.sha256(test.read_bytes()).hexdigest()
        plan = ROOT/'tasks/codex_tasks/H01_DOWNSIDE_WALL_PLAN_2026-10-21.md'
        after = snapshot.path.stat()
        result = clean({'variants':rows,'books':books,'fall_summary':fall_summary,'baseline_audit':baseline_audit,
            'bootstrap':null,'snapshot_name':snapshot.path.name,'snapshot_read_only':True,
            'snapshot_file_unchanged':(before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),
            'git_head':git_hash,'source_sha256':hashes,'declared_plan_sha256':hashlib.sha256(plan.read_bytes()).hexdigest(),
            'input_long_outcomes_sha256':hashlib.sha256((OUT/'H01_long_outcomes.csv.gz').read_bytes()).hexdigest(),
            'fdr_scope':{'current_variants':8,'prior_ledger_tests':len(prior),'total_tests':len(prior)+8},
            'test_results':json.loads((OUT/'H01_wall_tests.json').read_text(encoding='utf-8')),
            'promoted':False,'provisional':True,'full_data_completeness_gate_met':False,
            'limits':['caps checked against sleeve NAV at open before trading fees; price drift can breach between checks',
                      'EOD exits execute at next real open; no intraday stop fills or guaranteed stop price',
                      'no automatic restart after strategy kill; killed sleeves remain cash',
                      'current names may differ from historical company names; issuer/actual ISIN anchors retained',
                      'B5 previous-close proxy, derived BSE TRI, snapshot base capital-gains tax and incomplete coverage',
                      'guard grid motivated by observed earlier startup concentration; exploratory; all prior tests retained']})
        if not result['snapshot_file_unchanged'] or not baseline_audit['reproduces_prior_book'] or baseline_audit['max_daily_reconciliation_error_inr']>1e-5:
            raise AssertionError('Source/baseline P&L audit failed')
        run_id = append_variants(result['variants'],snapshot=snapshot.path.name,git_hash=git_hash,
                                 coverage={'positive_PAT180_opportunities':len(events)},source_hashes=hashes)
        result['ledger_run_id'] = run_id
        append_run_note(run_id,json.dumps({'method':'H01_DOWNSIDE_WALL_PLAN_2026-10-21.md',
            'inference_unit':'60 monthly constrained-book excess returns','prior_tests':len(prior)}))
        result['elapsed_seconds'] = perf_counter()-started
        (OUT/'H01_wall_results.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
        write_report(result)
    progress(f'wall finished:{run_id};{result["elapsed_seconds"]:.1f}s')


def write_report(r):
    pct = lambda x:f'{100*x:.2f}%'
    lines = ['# H01 downside wall and when stocks fell — provisional','',
        f"Run `{r['ledger_run_id']}`. Eight declared guard tests;{r['fdr_scope']['total_tests']} tests in BH including all{r['fdr_scope']['prior_ledger_tests']} prior tests. Evidence2021–2025 only.", '',
        '## Original book failure', '',
        f"First entry:{r['baseline_audit']['first_entry']}; first5% sleeve drawdown:{r['baseline_audit']['first5_drawdown']}; kill:{r['baseline_audit']['kill_date']}.",
        f"B5 gross previous-close proxy over first entry through kill:{pct(r['baseline_audit']['b5_gross_proxy_first_entry_to_kill'])}.",
        'The sleeve initially invested almost entirely in one issuer. Market weakness and individual-stock losses overlapped; this is price evidence, not a verified news-causality claim.', '',
        '| Stock label | Net P&L INR through liquidation | Fees INR | Tax INR |','|---|---:|---:|---:|']
    for row in r['baseline_audit']['issuer_attribution'][:10]:
        lines.append(f"| {row['symbol']} ({row['entity']}) | {row['pnl_inr']:.0f} | {row['fees_inr']:.0f} | {row['taxes_inr']:.0f} |")
    lines += ['', '## When the180-session opportunities fell', '',
        f"All{r['fall_summary']['events']} original positive-PAT180 events are retained. Threshold dates are retrospective audit labels; guard orders use only each actual EOD observation.", '',
        '| Fall | 0–5 sessions | 6–20 | 21–60 | 61–120 | 121–180 | Never | Eventually positive excess despite fall |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name,row in r['fall_summary']['fall_timing'].items():
        b = row['first_crossing_age_bins']
        lines.append(f"| {name} | {b['0-5']} | {b['6-20']} | {b['21-60']} | {b['61-120']} | {b['121-180']} | {b['never']} | {row['eventual_positive_excess_after_crossing']} |")
    lines += ['', 'loss5/loss8 are close declines from entry open; trail8 is close drawdown from the running close high, seeded by entry open. Full stock/date rows and extrema are in H01_falls.csv.gz.', '',
        '## Guard books', '',
        '| Guard | Sleeve CAGR | B5 excess CAGR | Max DD | Kill | Mean cash | Costs INR | Tax INR | EOD exit decisions | Monthly BH q | Block placebo p | Max-T p |',
        '|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in r['variants']:
        p = row['params']; b = r['books'][p['guard']]
        lines.append(f"| {p['guard']} | {pct(b['allocation_cagr'])} | {pct(b['excess_cagr'])} | {pct(b['max_drawdown'])} | {b['kill_date'] or 'none'} | {pct(b['mean_cash_fraction'])} | {b['costs_inr']:.0f} | {b['taxes_inr']:.0f} | {b['n_risk_decisions']} | {row['bh_q']:.3g} | {row['placebo_directional_p']:.3g} | {row['reality_check_p']:.3g} |")
    lines += ['', 'cap10 limits each issuer to10% of pre-trade sleeve NAV at open, with excess capacity in cash. fixed5 uses FIFO weighted cost. trail8 uses the observed high water mark. SMA50 vetoes admissions below the prior completed stock average and exits on an EOD breach. Market200 uses the index already selected by B5 for that month.',
        'Every risk decision fills at the next actual open; stock gaps and missing quotes can overshoot. Scheduled exits remain close fills. The unchanged8% strategy kill can still trigger. These are whole-book results including cash; the event-return averages in earlier reports are different quantities.', '',
        '## Audit and inference', '',
        f"Baseline matches its earlier saved NAV:{r['baseline_audit']['reproduces_prior_book']}; maximum daily issuer-P&L reconciliation error:{r['baseline_audit']['max_daily_reconciliation_error_inr']:.3g} INR.",
        'Monthly p=max(simple monthly t-test p,9-month HAC p).999 coherent9-month circular block draws calibrate centered monthly excess and the current8-test maximum absolute statistic. All earlier tests remain in BH.', '']
    lines += [f'- {s}' for s in r['limits']]
    lines += ['',f"Tests:{r['test_results']['total_tests']} passed. Snapshot read-only/unchanged:{r['snapshot_file_unchanged']}. Runtime:{r['elapsed_seconds']:.1f}s. No2026 outcomes or deployment.",
        'Reproduce:`python -m reality_engine.harness.run_h01_wall`; independent check:`python -m reality_engine.harness.verify_h01_wall`.']
    (OUT/'H01_wall_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
