"""Point-in-time wall, gap, cap and P&L reconciliation regressions."""
from datetime import date
from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd

from reality_engine.harness.book import run_book
from reality_engine.harness.data import Calendar
from reality_engine.harness.benchmark import INDEX_NAMES
from reality_engine.harness.run_h01_wall import WallPolicy, GUARDS, risk_features, reconcile_attribution, block_bootstrap
from reality_engine.tests.test_harness_h01 import rules


class WallTests(unittest.TestCase):
    def setUp(self):
        self.days = [date(2021,1,1),date(2021,1,4),date(2021,1,5),date(2021,1,6)]
        self.cal = Calendar(self.days)
        self.panel = SimpleNamespace(days=np.array(self.days,dtype='datetime64[D]'),col={'A':0},
                                     close=np.full((4,1),100.))
        self.features = {'sma50':np.full((4,1),99.),'market_admission':np.ones(4,dtype=bool),
                         'market_close_pass':np.ones(4,dtype=bool)}
        self.quotes = {('A',day):{'open':100.,'close':100.} for day in self.days}
        self.adtv = {('A',day):50e6 for day in self.days}
        self.events = [{'isin':'A','entry':self.days[1],'exit':self.days[-1],'sign':'positive'}]

    def run_fixture(self,stop=None,market=False,cap=.1):
        params = {'stop':stop,'market200':market}
        policy = WallPolicy(self.panel,self.features,params) if stop or market else None
        return run_book(self.events,self.cal,self.quotes,self.adtv,rules(),{day:1. for day in self.days},
                        issuer_fraction=cap,risk_policy=policy)

    def test_declared_eight_guards(self):
        self.assertEqual(len(GUARDS),8)
        self.assertEqual(len({p['guard'] for p in GUARDS}),8)

    def test_cap_keeps_startup_cash(self):
        book = self.run_fixture()
        fill = next(f for f in book['fills'] if f['side']=='buy')
        self.assertLessEqual(fill['qty']*fill['price'],100000.)
        self.assertAlmostEqual(book['final_allocation_inr'],999700.)
        self.assertGreater(book['nav'][1]['cash'],899000.)

    def test_eod_stop_fills_next_actual_open_with_gap(self):
        self.quotes['A',self.days[1]]['close']=94.
        self.quotes['A',self.days[2]]['open']=80.
        book = self.run_fixture(stop='fixed5')
        stop = next(f for f in book['fills'] if f['reason']=='fixed5')
        self.assertEqual(stop['risk_decision_date'],self.days[1])
        self.assertEqual(stop['date'],self.days[2])
        self.assertEqual(stop['price'],80.)
        self.assertNotEqual(stop['price'],95.)

    def test_missing_open_retains_pending_liquidation(self):
        self.quotes['A',self.days[1]]['close']=94.
        self.quotes['A',self.days[2]]={'open':float('nan'),'close':94.}
        self.quotes['A',self.days[3]]['open']=90.
        book = self.run_fixture(stop='fixed5')
        stops = [f for f in book['fills'] if f['reason']=='fixed5']
        self.assertEqual(len(stops),1)
        self.assertEqual(stops[0]['date'],self.days[3])
        self.assertEqual(book['skipped']['risk_exit_missing_open'],1)

    def test_trailing_stop_uses_observed_peak(self):
        self.quotes['A',self.days[1]]['close']=110.
        self.quotes['A',self.days[2]]['close']=100.
        self.quotes['A',self.days[3]]['open']=95.
        book = self.run_fixture(stop='trail8')
        stop = next(f for f in book['fills'] if f['reason']=='trail8')
        self.assertEqual(stop['risk_peak_close'],110.)
        self.assertEqual(stop['risk_decision_date'],self.days[2])
        self.assertEqual(stop['date'],self.days[3])

    def test_market_exit_can_be_requested_without_stock_close(self):
        self.features['market_close_pass'][1]=False
        self.quotes['A',self.days[1]]['close']=float('nan')
        book = self.run_fixture(market=True)
        stop = next(f for f in book['fills'] if f['reason']=='market200')
        self.assertEqual(stop['risk_decision_date'],self.days[1])
        self.assertEqual(stop['date'],self.days[2])

    def test_sma_entry_only_uses_completed_day(self):
        self.panel.close[1,0]=1.
        policy = WallPolicy(self.panel,self.features,{'stop':'sma50','market200':False})
        self.assertTrue(policy.admit('A',self.days[1]))
        self.panel.close[0,0]=98.
        self.assertFalse(policy.admit('A',self.days[1]))

    def test_month_switch_gate_uses_new_selected_index_prior_close(self):
        cal = Calendar(pd.bdate_range('2019-01-01',periods=300).date)
        p = SimpleNamespace(calendar=cal,days=np.array(cal.days,dtype='datetime64[D]'),close=np.ones((300,1)))
        series = {name:{day:(100.+i if n==0 else 500.-i,'fixture') for i,day in enumerate(cal.days)}
                  for n,name in enumerate(INDEX_NAMES)}
        benchmark = SimpleNamespace(series=series,names=[INDEX_NAMES[0]]*250+[INDEX_NAMES[1]]*50)
        f = risk_features(p,benchmark)
        self.assertTrue(f['market_close_pass'][249])
        self.assertFalse(f['market_admission'][250])

    def test_pnl_reconciles_cash_and_quotes(self):
        self.quotes['A',self.days[-1]]['close']=110.
        self.panel.close[-1,0]=110.
        book = self.run_fixture(cap=None)
        _,audit = reconcile_attribution(book,self.panel,{'A':{'symbol':'A'}})
        self.assertLess(audit['max_daily_reconciliation_error_inr'],1e-6)
        self.assertAlmostEqual(sum(row['pnl_inr'] for row in audit['issuer_attribution']),
                               book['final_allocation_inr']-book['initial_allocation_inr'])

    def test_block_null_handles_cash_and_zero_variance(self):
        rows = [{},{}]
        null = block_bootstrap(np.zeros((60,2)),rows,draws=9)
        self.assertEqual(null['block_length_months'],9)
        self.assertTrue(all(row['placebo_directional_p']==1 and row['reality_check_p']==1 for row in rows))


if __name__=='__main__':
    unittest.main()
