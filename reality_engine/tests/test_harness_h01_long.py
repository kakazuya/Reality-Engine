"""Hermetic longer-horizon/cohort regressions; no source database access."""
from datetime import datetime, timedelta
import unittest

import numpy as np

from reality_engine.harness.run_h01_long import (
    VARIANTS, ALL_HORIZONS, LongEvaluator, cohort_mask, horizon_hac)
from reality_engine.tests import test_harness_h01 as base_fixtures
from reality_engine.tests.test_harness_h01 import rules


class LongGridTests(unittest.TestCase):
    def setUp(self):
        fixture = base_fixtures.VectorEvaluatorTests('test_vector_real_path_has_one_event_per_positive_variant')
        fixture.setUp()
        self.panel, self.records, self.benchmark = fixture.panel, fixture.records, fixture.benchmark

    def test_declared_grid_includes_every_test_and_matched_curve(self):
        self.assertEqual(len(VARIANTS),174)
        self.assertEqual(sum(p['sample']=='available_horizon' for p in VARIANTS),160)
        self.assertEqual(sum(p['sample']=='common_504' for p in VARIANTS),14)
        self.assertEqual({p['horizon'] for p in VARIANTS},set(ALL_HORIZONS))

    def test_strength_thresholds_are_absolute_and_inclusive(self):
        scores = np.array([.5,1.,2.,-1.,-2.,np.nan])
        trends = np.array([1,1,1,-1,-1,1])
        p = {'sign':'positive','cohort':'abs_ge_2_trend200'}
        self.assertEqual(cohort_mask(scores,trends,p).tolist(),[False,False,True,False,False,False])
        p['sign']='negative'
        self.assertEqual(cohort_mask(scores,trends,p).tolist(),[False,False,False,False,True,False])
        p['cohort']='abs_ge_1'
        self.assertEqual(int(cohort_mask(scores,trends,p).sum()),2)

    def test_long_calendar_day_tax_matches_actual_holding(self):
        self.panel.close[:]=110.
        e = LongEvaluator(self.records,self.panel,self.benchmark,rules())
        entry = self.panel.entry_indices([self.records[-1]['trigger']])[0]
        short = e.returns(np.array([entry]),np.array([0]),20)
        long = e.returns(np.array([entry]),np.array([0]),504)
        self.assertAlmostEqual(short['net'][0],.082)
        self.assertAlmostEqual(long['net'][0],.087)

    def test_trend_cannot_read_entry_day_close(self):
        entry = self.panel.entry_indices([self.records[-1]['trigger']])[0]
        self.panel.close[entry,0]=10000.
        e = LongEvaluator(self.records,self.panel,self.benchmark,rules())
        rows=e.evaluate()
        self.assertTrue(all(row['n_events']==0 for row in rows if row['params']['cohort']=='abs_ge_2_trend200'))
        signal = self.panel.signal_indices([self.records[-1]['trigger']])[0]
        self.panel.close[signal,0]=110.
        e = LongEvaluator(self.records,self.panel,self.benchmark,rules())
        rows=e.evaluate()
        self.assertTrue(any(row['n_events']==1 for row in rows if row['params']['cohort']=='abs_ge_2_trend200'))

    def test_matched_curve_has_identical_entry_sample(self):
        e = LongEvaluator(self.records,self.panel,self.benchmark,rules())
        rows,selections,_,_=e.evaluate(detailed=True)
        sets = [set(data['ids'][keep]) for params,data,keep in selections
                if params['sample']=='common_504' and params['cohort']=='any']
        self.assertEqual(len(sets),7)
        self.assertTrue(all(ids==sets[0] for ids in sets))
        self.assertEqual(len(sets[0]),1)

    def test_no_2026_outcome_is_used_to_fill_long_window(self):
        current=self.records[-1]
        current['trigger']=current['trade_trigger']=datetime(2024,12,20,20)
        current['xbrl_at']=current['trigger']-timedelta(hours=1)
        e = LongEvaluator(self.records,self.panel,self.benchmark,rules())
        rows=e.evaluate()
        self.assertTrue(all(row['n_events']==0 for row in rows if row['params']['sample']=='common_504'))
        self.assertTrue(any(row['n_events']==1 for row in rows if row['params']['horizon']==90))

    def test_hac_refuses_short_support_for_two_year_overlap(self):
        months=np.arange(np.datetime64('2022-01'),np.datetime64('2025-01'),dtype='datetime64[M]')
        days=months.astype('datetime64[D]')
        values=.01+np.sin(np.arange(len(days)))*.02
        short=horizon_hac(values,np.arange(len(days)),days,90)
        long=horizon_hac(values,np.arange(len(days)),days,504)
        self.assertTrue(short['sufficient_support'])
        self.assertFalse(long['sufficient_support'])
        self.assertEqual(long['p'],1.)
        self.assertEqual(long['bandwidth_months'],24)


if __name__=='__main__':
    unittest.main()
