"""Hermetic synthetic H01 tests. Never open the snapshot or any database."""
import math
import random
import unittest
from datetime import date, datetime, timedelta

from reality_engine.harness.data import Calendar, price_asof
from reality_engine.harness.universe import eligible, liquidity
from reality_engine.harness.execution import trade_window, position_cap
from reality_engine.harness.costs_tax import TaxRules, sale, tax_on_gains
from reality_engine.harness.book import run_book
from reality_engine.harness.coverage import coverage_report
from reality_engine.harness.benchmark import INDEX_NAMES, select_month
from reality_engine.harness.stats import bh_fdr, student_p, summarize, shuffled_dates
from reality_engine.harness.cards.h01_pead import (
    VARIANTS, parse_period_end, pit_trigger, quarter_back, select_basis, surprise,
    descriptive_quintiles)


def rules():
    rows = []
    for start, end, st, lt, exempt in [
        ("2019-01-01", "2024-07-22", .15, .10, 100000),
        ("2024-07-23", None, .20, .125, 125000)]:
        for name, value in [("stcg_rate", st), ("ltcg_rate", lt), ("ltcg_exempt", exempt)]:
            rows.append({"rule": name, "start": start, "end": end, "value": value})
    return TaxRules(rows)


class TriggerTests(unittest.TestCase):
    def test_parse_period_not_meeting_date(self):
        self.assertEqual(parse_period_end(
            "Board meeting 13/02/2025: Financial Results for quarter ended 31st December 2024"),
            date(2024, 12, 31))
        self.assertEqual(parse_period_end("Results ended 31.03.2024"), date(2024, 3, 31))

    def test_ambiguous_or_incomplete_subject(self):
        for text in ["meeting 13 February 2025", "ended December 2024",
                     "ended 31 March 2024 and ended 30 September 2024"]:
            self.assertIsNone(parse_period_end(text))

    def test_earliest_dissemination_not_period_end_or_xbrl(self):
        a = [{"subcategory": "Financial Results", "subject": "ended 31st December 2024",
              "disseminated_at": datetime(2025, 2, 13, 20, 32)},
             {"subcategory": "Financial Results", "subject": "ended 31st December 2024",
              "disseminated_at": datetime(2025, 2, 14, 15, 10)}]
        stamp, basis = pit_trigger(date(2024, 12, 31), a)
        self.assertEqual(stamp, datetime(2025, 2, 13, 20, 32))
        self.assertEqual(basis, "period_parsed")
        cal = Calendar([date(2025, 2, 13), date(2025, 2, 14), date(2025, 2, 17)])
        self.assertEqual(cal.next_session(stamp), date(2025, 2, 14))

    def test_no_dissemination_no_trigger(self):
        a = [{"subcategory": "Financial Results", "subject": "ended 31 December 2024",
              "disseminated_at": None}]
        self.assertEqual(pit_trigger(date(2024, 12, 31), a), (None, "missing"))

    def test_fallback_rejects_other_explicit_quarter(self):
        a = [{"subcategory": "Financial Results", "subject": "ended 30 September 2024",
              "disseminated_at": datetime(2025, 1, 1)},
             {"subcategory": "Financial Results", "subject": "financial results",
              "disseminated_at": datetime(2025, 2, 1)}]
        stamp, basis = pit_trigger(date(2024, 12, 31), a)
        self.assertEqual(stamp, datetime(2025, 2, 1))
        self.assertEqual(basis, "within_100_days_unparsed")


class SurpriseTests(unittest.TestCase):
    def setUp(self):
        self.current = {"period_end": date(2024, 12, 31), "trigger": datetime(2025, 2, 13),
                        "basis": "Consolidated", "PAT": 1000}
        self.history = [{"period_end": quarter_back(self.current["period_end"], i),
                         "trigger": datetime.combine(quarter_back(self.current["period_end"], i)
                                                     + timedelta(days=40), datetime.min.time()),
                         "basis": "Consolidated", "PAT": float((14-i)**2)}
                        for i in range(1, 13)]

    def test_prior_eight_yoy_sample_sd(self):
        from statistics import stdev
        result = surprise(self.current, self.history)
        deltas = [(14-i)**2 - (14-i-4)**2 for i in range(1, 9)]
        self.assertAlmostEqual(result["surprise"], (1000-100)/stdev(deltas))
        self.assertEqual(result["prior_yoy_count"], 8)

    def test_future_restatement_does_not_rewrite_history(self):
        before = surprise(self.current, self.history)
        future = {**self.history[0], "PAT": 1e12, "trigger": datetime(2025, 2, 14)}
        self.assertEqual(surprise(self.current, self.history + [future]), before)

    def test_missing_or_late_comparator_refuses_signal(self):
        self.assertIsNone(surprise(self.current, self.history[:-1]))
        self.history[3]["trigger"] = self.current["trigger"]
        self.assertIsNone(surprise(self.current, self.history))

    def test_consolidated_null_does_not_select_standalone(self):
        rows = [{"basis": "Consolidated", "PAT": None}, {"basis": "Standalone", "PAT": 99}]
        self.assertEqual(select_basis(rows), rows[:1])

    def test_full_grid_includes_avoid_cohorts(self):
        self.assertEqual(len(VARIANTS), 16)
        self.assertEqual(sum(p["sign"] == "negative" for p in VARIANTS), 8)
        self.assertEqual({p['entry_timing'] for p in VARIANTS}, {'bse_next_open','both_known_next_open'})

    def test_descriptive_quintiles_keep_ties_together(self):
        rows = [{"PAT_surprise": 1.0, "net_excess": .02} for _ in range(10)]
        table = descriptive_quintiles(rows, "PAT")
        self.assertEqual(sum(r["n_events"] > 0 for r in table), 1)
        self.assertEqual(sum(r["n_events"] for r in table), 10)


class BenchmarkTests(unittest.TestCase):
    def test_selection_cannot_see_month_or_future(self):
        base, end, future = date(2023, 12, 29), date(2024, 12, 31), date(2025, 1, 2)
        series = {name: {base: (100, "test"), end: (110+i, "test"),
                         future: (1000000 if i == 0 else 1, "future")}
                  for i, name in enumerate(INDEX_NAMES)}
        chosen = select_month(series, date(2025, 1, 1))
        self.assertEqual(chosen["index"], INDEX_NAMES[-1])
        self.assertLess(chosen["asof_date"], date(2025, 1, 1))
        del series[INDEX_NAMES[0]]
        self.assertIsNone(select_month(series, date(2025, 1, 1)))


class StatsTests(unittest.TestCase):
    def test_known_bh_example_full_grid(self):
        expected = [.04, .05333333333333334, .05333333333333334, .2]
        for got, want in zip(bh_fdr([.01, .04, .03, .2]), expected):
            self.assertAlmostEqual(got, want)
        self.assertEqual(bh_fdr([.01, None]), [.02, 1.0])

    def test_student_distribution_known_values(self):
        self.assertAlmostEqual(student_p(0, 10), 1)
        self.assertAlmostEqual(student_p(1, 1), .5)
        self.assertAlmostEqual(student_p(2.2281388519649385, 10), .05, places=8)

    def test_shuffle_stays_inside_month(self):
        stamps = [datetime(2024, 1, 10), datetime(2024, 1, 20), datetime(2024, 2, 3)]
        events = [{"trigger": d, "id": i} for i, d in enumerate(stamps)]
        result = shuffled_dates(events, random.Random(7))
        self.assertEqual(sorted(e["trigger"] for e in result), stamps)
        self.assertTrue(all(a["trigger"].month == b["trigger"].month for a,b in zip(events,result)))
        self.assertEqual([e["trigger"] for e in events], stamps)

    def test_year_and_regime_splits_keep_absent_years(self):
        result = summarize([{"entry": date(2021, 1, 4), "net_excess": .02, "regime": "up"},
                            {"entry": date(2022, 2, 4), "net_excess": -.01, "regime": "down"}])
        self.assertEqual(result["per_year_signs"]["2021"], "+")
        self.assertIsNone(result["per_year_signs"]["2025"])
        self.assertEqual(result["regimes"]["down"]["n"], 1)


class CostExecutionTests(unittest.TestCase):
    def test_normal_calendar_omits_special_weekends_consistently(self):
        cal = Calendar.normal_sessions([date(2024,3,1),date(2024,3,2),date(2024,3,4),date(2024,3,5)])
        self.assertEqual(cal.next_session(datetime(2024,3,1,20)),date(2024,3,4))
        self.assertEqual(cal.offset(date(2024,3,1),1),date(2024,3,4))
        self.assertNotIn(date(2024,3,2),cal.days)

    def test_exit_waits_for_next_actual_close(self):
        days = [date(2025,1,2),date(2025,1,3),date(2025,1,6),date(2025,1,7)]
        quotes = {d:{'open':100.,'close':110.} for d in days}
        quotes[days[2]]['close'] = float('nan')
        result = trade_window(Calendar(days), days[0], 1, quotes)
        self.assertEqual(result['scheduled_exit'],days[2])
        self.assertEqual(result['exit'],days[3])
        self.assertAlmostEqual(result['gross_return'],.1)

    def test_cost_and_sell_date_tax(self):
        a = sale(.10, "2024-07-01", "2024-07-22", rules())
        b = sale(.10, "2024-07-01", "2024-07-23", rules())
        self.assertAlmostEqual(a["net_return"], .082)
        self.assertAlmostEqual(b["net_return"], .077)
        self.assertAlmostEqual(sale(-.10, "2024-07-01", "2024-07-23", rules())["net_return"], -.103)

    def test_long_term_boundary_and_fy_allowance_once(self):
        used = {}
        first = sale(.20, "2023-01-01", "2025-01-02", rules(), principal=1e6, exemption_used=used)
        second = sale(.20, "2023-01-01", "2025-01-02", rules(), principal=1e6, exemption_used=used)
        self.assertAlmostEqual(first["tax_inr"], 75000*.125)
        self.assertAlmostEqual(second["tax_inr"], 200000*.125)
        self.assertFalse(sale(.2, "2023-01-01", "2024-01-01", rules())["long_term"])

    def test_tax_nets_fifo_gains_within_sale(self):
        gains = [{"gain": 100, "holding_days": 20}, {"gain": -40, "holding_days": 30}]
        self.assertAlmostEqual(tax_on_gains(gains, "2025-01-01", rules()), 12)

    def test_next_session_open_and_exit_offset(self):
        days = [date(2025, 2, 13), date(2025, 2, 14), date(2025, 2, 17), date(2025, 2, 18)]
        quotes = {d: {"open": 10+i, "close": 11+i} for i,d in enumerate(days)}
        trade = trade_window(Calendar(days), datetime(2025, 2, 13, 20, 32), 2, quotes)
        self.assertEqual(trade["entry"], days[1])
        self.assertEqual(trade["exit"], days[3])
        self.assertEqual(trade["entry_price"], 11)
        self.assertEqual(trade["exit_price"], 14)
        self.assertEqual(Calendar(days).next_session(datetime(2025, 2, 15)), days[2])

    def test_absent_open_schema_flag_and_missing_quote_reject(self):
        days = [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)]
        quotes = {d: {"close": 10.0} for d in days}
        self.assertIsNone(trade_window(Calendar(days), days[0], 1, quotes))
        self.assertTrue(trade_window(Calendar(days), days[0], 1, quotes, has_open=False)["entry_close_fallback"])

    def test_never_uses_2026_exit(self):
        days = [date(2025, 12, 30), date(2025, 12, 31), date(2026, 1, 1)]
        quotes = {d: {"open": 10, "close": 11} for d in days}
        self.assertIsNone(trade_window(Calendar(days), days[0], 1, quotes))

    def test_u1_delisted_not_removed_and_raw_penny_rule(self):
        self.assertTrue(eligible(10, [5e6]*20, in_security_master=True)["eligible"])
        self.assertFalse(eligible(9.99, [5e6]*20, in_security_master=True)["eligible"])
        self.assertFalse(eligible(10, [5e6]*20, in_security_master=True, quarantined=True)["eligible"])
        self.assertFalse(liquidity([5e6]*19)["eligible"])
        self.assertEqual(position_cap(5e6), 500000)

    def test_asof_never_reads_future(self):
        quotes = {date(2025, 1, 1): 10, date(2025, 1, 3): 999}
        self.assertEqual(price_asof(quotes, date(2025, 1, 2)), (date(2025, 1, 1), 10))


class BookCoverageTests(unittest.TestCase):
    def setUp(self):
        self.days = [date(2021, 1, 1), date(2021, 1, 4), date(2021, 1, 5), date(2021, 1, 6)]
        self.event = {"isin": "A", "entry": self.days[1], "exit": self.days[3], "sign": "positive"}
        self.quotes = {("A", d): {"open": 100., "close": 100.} for d in self.days}
        self.adtv = {("A", d): 50_000_000. for d in self.days}

    def run_fixture(self, events=None):
        return run_book([self.event] if events is None else events, Calendar(self.days),
                        self.quotes, self.adtv, rules(), {d: 1. for d in self.days})

    def test_book_cost_tax_and_no_borrowing(self):
        self.quotes[("A", self.days[3])]["close"] = 110.
        result = self.run_fixture()
        principal = 1_000_000 / 1.0015
        self.assertAlmostEqual(result["final_allocation_inr"], 1_000_000 + .082 * principal)
        self.assertAlmostEqual(result["costs_inr"], .003 * principal)
        self.assertAlmostEqual(result["taxes_inr"], .015 * principal)
        self.assertTrue(all(p["cash"] >= -1e-6 for p in result["nav"]))

    def test_kill_uses_next_session_and_capacity_cap(self):
        self.quotes[("A", self.days[1])]["close"] = 90.
        self.quotes[("A", self.days[2])]["open"] = 85.
        result = self.run_fixture()
        self.assertEqual(result["kill_date"], self.days[1])
        liquidation = [f for f in result["fills"] if f["reason"] == "kill"]
        self.assertEqual(liquidation[0]["date"], self.days[2])
        self.assertEqual(liquidation[0]["price"], 85.)
        self.adtv = {("A", d): 5_000_000. for d in self.days}
        result = self.run_fixture()
        buy = next(f for f in result["fills"] if f["side"] == "buy")
        self.assertLessEqual(buy["qty"] * buy["price"], 500_000.)

    def test_avoid_cohort_cannot_enter_book(self):
        with self.assertRaises(ValueError):
            self.run_fixture([{**self.event, "sign": "negative"}])

    def test_book_missing_scheduled_close_exits_at_next_real_close(self):
        self.event['exit'] = self.days[2]
        self.quotes[('A',self.days[2])]['close'] = float('nan')
        result = self.run_fixture()
        sells = [f for f in result['fills'] if f['reason']=='scheduled_exit']
        self.assertEqual([f['date'] for f in sells],[self.days[3]])
        self.assertFalse(result['unresolved_holdings'])
        self.assertEqual(result['skipped']['delayed_exit_missing_close'],1)

    def test_coverage_denominator_and_trigger_year(self):
        result = coverage_report([(date(2021, 1, 1), "A"), (date(2021, 1, 4), "B")],
                                 [(date(2021, 2, 1), "A"), (date(2021, 2, 1), "OUTSIDE")], [])
        self.assertEqual(result[0]["u1_isins"], 2)
        self.assertEqual(result[0]["financial_covered_isins"], 1)
        self.assertEqual(result[0]["financial_coverage"], .5)
        self.assertFalse(result[0]["full_data_completeness_gate_met"])


class SnapshotAdapterTests(unittest.TestCase):
    """In-memory synthetic tables only. Never open another source database."""
    def setUp(self):
        import duckdb
        self.conn = duckdb.connect(':memory:')
        for sql in [
            'create table security_master(isin varchar,issuer varchar,bse_code varchar)',
            'create table bse_ann(SCRIP_CD varchar,NEWSSUB varchar,DissemDT varchar,SUBCATNAME varchar)',
            '''create table results_key(file varchar,symbol varchar,taxonomy varchar,consolidated varchar,
               period_start varchar,period_end varchar,ProfitLossForPeriod double,
               RevenueFromOperations double,InterestEarned double)''',
            '''create table results_filings(file varchar,trading_isin varchar,isin varchar,
               known_at_utc timestamp,same_issuer integer,status varchar)''',
            '''create table results_facts(file varchar,concept varchar,context varchar,
               period_kind varchar,unit varchar,value double)''']:
            self.conn.execute(sql)
        self.conn.execute("insert into security_master values ('INE000A01010','INE000A','500000')")
        self.conn.execute("""insert into bse_ann values
          ('500000','Results quarter ended 31st December 2024','2025-02-13T20:32:16.483','Financial Results')""")

    def tearDown(self):
        self.conn.close()

    def add(self,file='first',basis='Consolidated',pat=100.,known='2025-02-13 14:00:00',
            taxonomy='INDAS',revenue=200.,interest=None):
        self.conn.execute('insert into results_key values (?,?,?,?,?,?,?,?,?)',
                          [file,'A',taxonomy,basis,'2024-10-01','2024-12-31',pat,revenue,interest])
        self.conn.execute('insert into results_filings values (?,?,?,?,?,?)',
                          [file,'INE000A01010','WRONG_STALE_ISIN',known,1,'ok'])
        for concept,value in [('ProfitLossForPeriod',pat),('RevenueFromOperations',revenue),
                              ('InterestEarned',interest)]:
            if value is not None:
                self.conn.execute("insert into results_facts values (?,?,'OneD','quarter','INR',?)",
                                  [file,concept,value])

    def test_file_join_uses_trading_isin_and_ist_dissemination(self):
        from reality_engine.harness.adapter import load_filings
        self.add()
        rows,_ = load_filings(self.conn)
        self.assertEqual(rows[0]['trading_isin'],'INE000A01010')
        self.assertEqual(rows[0]['entity'],'INE000A')
        self.assertEqual(rows[0]['trigger'],datetime(2025,2,13,20,32,16,483000))
        self.assertEqual(rows[0]['xbrl_at'],datetime(2025,2,13,19,30))

    def test_latest_revision_never_rewrites_first_filing(self):
        from reality_engine.harness.adapter import load_filings
        self.add()
        self.add(file='revision',pat=99999.,known='2025-02-14 08:00:00')
        rows,audit = load_filings(self.conn)
        self.assertEqual(rows[0]['PAT'],100.)
        self.assertEqual(audit['later_duplicate_or_revision_discarded'],1)

    def test_null_consolidated_pat_cannot_use_standalone(self):
        from reality_engine.harness.adapter import load_filings
        self.add(pat=None)
        self.add(file='standalone',basis='Standalone')
        rows,_ = load_filings(self.conn)
        self.assertEqual(rows[0]['basis'],'Consolidated')
        self.assertIsNone(rows[0]['PAT'])

    def test_bank_uses_interest_earned(self):
        from reality_engine.harness.adapter import load_filings
        self.add(taxonomy='BANKING',revenue=None,interest=270.)
        rows,_ = load_filings(self.conn)
        self.assertEqual(rows[0]['revenue_metric'],'InterestEarned')
        self.assertEqual(rows[0]['revenue'],270.)

    def test_ambiguous_bse_code_refuses_trade_trigger(self):
        from reality_engine.harness.adapter import load_filings
        self.add()
        self.conn.execute("insert into security_master values ('INE000B01010','INE000B','500000')")
        rows,audit = load_filings(self.conn)
        self.assertIsNone(rows[0]['trade_trigger'])
        self.assertEqual(audit['ann_ambiguous_or_unmapped_code'],1)

    def test_bank_classification_survives_integrated_taxonomy_without_future_label(self):
        from reality_engine.harness.adapter import load_filings
        self.add(file='bank',taxonomy='BANKING',revenue=None,interest=200.,known='2025-01-01 10:00:00')
        self.conn.execute("update results_key set period_start='2024-07-01',period_end='2024-09-30' where file='bank'")
        self.add(file='integrated',taxonomy='INTEGRATED',revenue=None,interest=270.)
        rows,audit=load_filings(self.conn)
        current=next(r for r in rows if r['period_end']==date(2024,12,31))
        self.assertEqual(current['revenue'],270.)
        self.assertEqual(current['revenue_metric'],'InterestEarned')
        self.assertEqual(audit['bank_classification_carried_from_prior_filing'],1)

    def test_future_bank_taxonomy_cannot_reclassify_earlier_filing(self):
        from reality_engine.harness.adapter import load_filings
        self.add(file='earlier',taxonomy='INTEGRATED',revenue=None,interest=270.)
        self.add(file='future',taxonomy='BANKING',revenue=None,interest=270.,known='2025-03-01 10:00:00')
        rows,_=load_filings(self.conn)
        self.assertEqual(rows[0]['revenue_metric'],'RevenueFromOperations')
        self.assertIsNone(rows[0]['revenue'])


class VectorEvaluatorTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        import pandas as pd
        from reality_engine.harness.adapter import Panel
        from reality_engine.harness.run_h01 import Evaluator
        self.np=np
        self.panel=Panel.__new__(Panel)
        self.panel.calendar=Calendar(pd.bdate_range('2019-01-01','2025-12-31').date)
        self.panel.days=np.array(self.panel.calendar.days,dtype='datetime64[D]')
        self.panel.col={'INE000A':0}
        t=len(self.panel.days)
        self.panel.u1=np.ones((t,1),dtype=bool)
        self.panel.open=np.full((t,1),100.)
        self.panel.close=np.full((t,1),100.)
        self.panel.jump_prefix=np.zeros((t+1,1),dtype=int)
        class Benchmark:
            regime_up=np.ones(t,dtype=bool)
            def event_return(self,entry,exit):
                return 0.
        self.benchmark=Benchmark()
        self.records=[]
        for k in range(13):
            q=quarter_back(date(2022,3,31),12-k)
            stamp=datetime.combine(q+timedelta(days=40),datetime.min.time())+timedelta(hours=20)
            self.records.append({'entity':'INE000A','period_end':q,'trigger':stamp,
                                 'trade_trigger':stamp,'xbrl_at':stamp-timedelta(hours=1),
                                 'basis_family':'Consolidated','PAT':10.+(k+1)**2,
                                 'revenue':20.+(k+1)**3,'revenue_metric':'RevenueFromOperations',
                                 'trigger_method':'period_parsed'})
        self.Evaluator=Evaluator

    def test_vector_real_path_has_one_event_per_positive_variant(self):
        e=self.Evaluator(self.records,self.panel,self.benchmark,rules())
        rows=e.evaluate()
        self.assertEqual([r['n_events'] for r in rows],[1,0,1,0,1,0,1,0]*2)

    def test_current_xbrl_after_next_open_rejected(self):
        current=self.records[-1]
        entry=self.panel.calendar.next_session(current['trigger'])
        current['xbrl_at']=datetime.combine(entry,datetime.min.time())+timedelta(hours=10)
        e=self.Evaluator(self.records,self.panel,self.benchmark,rules())
        rows,sets,meta=e.evaluate(detailed=True)
        self.assertEqual(sum(r['n_events'] for r in rows[:8]),0)
        self.assertEqual(sum(r['n_events'] for r in rows[8:]),4)
        self.assertEqual(meta['audit']['current_values_after_next_open'],1)
        self.assertEqual(self.panel.calendar.days[sets[8]['entry_indices'][0]],
                         self.panel.calendar.next_session(current['xbrl_at']))
        self.assertEqual(meta['by_timing']['both_known_next_open']['audit']['current_values_after_next_open'],0)

    def test_historical_numbers_must_precede_trigger_not_just_entry(self):
        self.records[-2]['xbrl_at']=self.records[-1]['trigger']+timedelta(minutes=1)
        e=self.Evaluator(self.records,self.panel,self.benchmark,rules())
        self.assertEqual(sum(r['n_events'] for r in e.evaluate()),0)

    def test_missing_exit_with_later_quote_is_not_total_loss(self):
        en=self.panel.entry_indices([self.records[-1]['trigger']])[0]
        self.panel.close[en+20,0]=self.np.nan
        e=self.Evaluator(self.records,self.panel,self.benchmark,rules())
        rows,sets,_=e.evaluate(detailed=True)
        self.assertEqual(rows[0]['n_events'],1)
        self.assertEqual(rows[0]['missing_exit_total_loss_bounds'],0)
        self.assertEqual(rows[0]['delayed_exits_with_quote'],1)
        self.assertEqual(sets[0]['exit_indices'][0],en+21)
        self.assertAlmostEqual(sets[0]['gross'][0],0.)

    def test_unresolved_exit_keeps_explicit_terminal_recovery_bound(self):
        en=self.panel.entry_indices([self.records[-1]['trigger']])[0]
        self.panel.close[en+20:,0]=self.np.nan
        e=self.Evaluator(self.records,self.panel,self.benchmark,rules())
        rows,sets,_=e.evaluate(detailed=True)
        self.assertEqual(rows[0]['missing_exit_total_loss_bounds'],1)
        self.assertEqual(sets[0]['exit_indices'][0],len(self.panel.days)-1)
        self.assertAlmostEqual(sets[0]['gross'][0],-1.)

    def test_delayed_exit_matches_benchmark_and_actual_sell_date_tax(self):
        en=self.panel.entry_indices([self.records[-1]['trigger']])[0]
        self.panel.close[en+20:en+300,0]=self.np.nan
        self.panel.close[en+300,0]=110.
        self.benchmark.event_return=lambda entry,exit: (exit-entry)*.0001
        e=self.Evaluator(self.records,self.panel,self.benchmark,rules())
        _,sets,_=e.evaluate(detailed=True)
        self.assertEqual(sets[0]['exit_indices'][0],en+300)
        self.assertAlmostEqual(sets[0]['net'][0],.087)
        self.assertAlmostEqual(sets[0]['b5_net'][0],.03)
        self.assertAlmostEqual(sets[0]['excess'][0],.057)

    def test_directional_placebo_cannot_pass_for_wrong_sign(self):
        e=self.Evaluator(self.records,self.panel,self.benchmark,rules())
        observed=e.evaluate()
        for row in observed:
            row['mean_net_excess']=-.10
            row['t_stat']=-1.
        e.evaluate=lambda stamps: [{'mean_net_excess':-.05,'n_events':1,'t_stat':-.5} for _ in VARIANTS]
        e.placebos(observed,draws=3)
        self.assertEqual(observed[0]['placebo_p'],.25)
        self.assertEqual(observed[0]['placebo_directional_p'],1.)
        self.assertEqual(observed[1]['placebo_directional_p'],.25)

    def test_intraday_trigger_does_not_use_unpublished_close(self):
        current=self.records[-1]
        current['trigger']=current['trade_trigger']=current['trigger'].replace(hour=10)
        current['xbrl_at']=current['trigger']-timedelta(minutes=1)
        i=self.np.searchsorted(self.panel.days,self.np.datetime64(current['trigger'].date()))
        self.panel.u1[i,0]=False
        e=self.Evaluator(self.records,self.panel,self.benchmark,rules())
        self.assertEqual(e.evaluate()[0]['n_events'],1)

    def test_placebo_same_evaluator_rechecks_history_availability(self):
        current=self.records[-1]
        self.records[-2]['xbrl_at']=current['trigger']-timedelta(hours=1)
        e=self.Evaluator(self.records,self.panel,self.benchmark,rules())
        self.assertEqual(e.evaluate()[0]['n_events'],1)
        shuffled=e.original.copy()
        shuffled[-1]-=self.np.timedelta64(2,'h')
        self.assertEqual(e.evaluate(shuffled)[0]['n_events'],0)

    def test_descriptive_quintiles_include_zero_surprises(self):
        self.records[-1]['PAT']=self.records[-5]['PAT']
        e=self.Evaluator(self.records,self.panel,self.benchmark,rules())
        rows,_,meta=e.evaluate(detailed=True)
        self.assertEqual(rows[0]['n_events'],0)
        self.assertEqual(rows[1]['n_events'],0)
        self.assertEqual(sum(r['n_events'] for r in e.quintiles(meta,20,'PAT')),1)


class B5ChainTests(unittest.TestCase):
    def test_levels_are_not_spliced_and_same_index_has_no_roll_cost(self):
        from reality_engine.harness.benchmark import B5Path
        from reality_engine.harness.costs_tax import sale
        import pandas as pd
        days=list(pd.bdate_range('2019-01-01','2025-12-31').date)
        series={name:{d:(100.*(j+1),'synthetic') for d in days}
                for j,name in enumerate(INDEX_NAMES)}
        b=B5Path(series,Calendar(days),rules())
        self.assertTrue(all(abs(x-1)<1e-12 for x in b.factors))
        start=days.index(date(2024,1,2))
        self.assertAlmostEqual(b.event_return(start,start+60),-.003)
        self.assertEqual(len(b.choices),60)
        self.assertTrue(all(c['asof_date']<c['month'] for c in b.choices))


if __name__ == "__main__":
    unittest.main()
