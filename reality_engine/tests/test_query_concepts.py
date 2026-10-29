"""Ask-concept routing: the gate's alias table, the row that must carry it, and the
computations the bank asks for by name (sessions near the high, drawdown recovery,
RSI divergence, volume/delivery).

The rule the task fixes: a row carries a concept only when the ask really names it,
and a row of the right concept passes while a row of another concept still fails.
"""
import unittest

from reality_engine.query import compute, gate
from reality_engine.query.planners import facts


def _hop(rows, hop="SERIES", detail=""):
    return {"hop": hop, "rows": rows, "detail": detail}


class TestAskConceptsAreTheAsk(unittest.TestCase):
    def test_short_alias_does_not_match_inside_a_word(self):
        # "pe" inside "complete"/"per", "pat" inside "Data Patterns", "rsi"
        # inside "diversification", "eps" inside "steps" are not asks.
        for question in ("what does the file complete say",
                         "Data Patterns capacity and licence",
                         "diversification of the portfolio"):
            self.assertNotIn("valuation", gate.asked_concepts(question), question)
            self.assertNotIn("pat", gate.asked_concepts(question), question)
        self.assertNotIn("rsi", gate.asked_concepts("diversification"))

    def test_real_synonyms_still_name_the_concept(self):
        self.assertIn("valuation", gate.asked_concepts("MSUMI P/B versus the stored ratio"))
        self.assertIn("valuation", gate.asked_concepts("what is its P/E now"))
        self.assertIn("range", gate.asked_concepts("the 52-week high and the higher highs"))
        self.assertIn("cagr", gate.asked_concepts("3-year adjusted price CAGR"))
        self.assertIn("capex", gate.asked_concepts("capex per store"))
        self.assertIn("segment", gate.asked_concepts("segment revenue for Q1FY27"))

    def test_adjustment_basis_is_not_the_ask(self):
        # "split- and dividend-adjusted closes" asks for the CAGR.
        self.assertEqual(gate.asked_concepts(
            "3-year price CAGR using split- and dividend-adjusted closes"), ["cagr"])

    def test_entity_reference_is_not_an_identity_ask(self):
        self.assertNotIn("isin_identity", gate.asked_concepts(
            "What did ISIN INE864I01014 say about capacity?"))
        self.assertIn("isin_identity", gate.asked_concepts("the name change after the demerger"))


class TestRowMustCarryTheConcept(unittest.TestCase):
    def test_right_concept_row_passes(self):
        concepts = gate.asked_concepts("HAL 52-week high")
        hop = _hop([{"ref": "HAL", "item": "close, return, high, low"}])
        ok, missing = gate.ask_coverage([hop], concepts, [])
        self.assertTrue(ok, missing)

    def test_wrong_concept_row_still_fails(self):
        concepts = gate.asked_concepts("HAL 52-week high")
        hop = _hop([{"ref": "HAL", "item": "close"}])
        ok, missing = gate.ask_coverage([hop], concepts, [])
        self.assertFalse(ok)
        self.assertTrue(missing and "range" in missing[0])

    def test_two_part_ask_needs_both_parts(self):
        concepts = gate.asked_concepts("capacity expansion timeline with capex and quote")
        only_capacity = _hop([{"ref": "X", "item": "bed capacity 73%"}], hop="FACTS")
        self.assertFalse(gate.ask_coverage([only_capacity], concepts, [])[0])
        both = _hop([{"ref": "X", "item": "bed capacity 73%"}, {"ref": "X", "item": "capex 1,200"}],
                    hop="FACTS")
        self.assertTrue(gate.ask_coverage([both], concepts, [])[0])


class TestConceptWordsReachTheStores(unittest.TestCase):
    def test_asked_words_unions_every_named_concept(self):
        words = facts.asked_words("capacity expansion and capex", "capacity")
        self.assertIn("capacity", words)
        self.assertIn("capex", words)

    def test_segment_rows_name_the_segment(self):
        class Ctx:
            def rows(self, name, sql, params=()):
                return [{"segment": "Aerospace", "period_end": "2026-06-30", "metric": "revenue",
                         "basis": "consolidated", "value_cr": 1234.5,
                         "share_of_total_pct": 61.2, "doc_id": "d1", "page": 7,
                         "known_at": "2026-08-01T10:00:00"}]

        rows, _ = facts._segment_pnl(Ctx(), "INE000000000", "2026-10-19", (None, None))
        self.assertEqual(len(rows), 1)
        self.assertIn("segment", rows[0]["item"])
        self.assertIn("revenue", rows[0]["item"])
        self.assertEqual(rows[0]["unit"], "Rs crore")


class TestNamedStudies(unittest.TestCase):
    points = [("2026-01-01", 100.0), ("2026-01-02", 99.0), ("2026-01-03", 101.0),
              ("2026-01-04", 100.5), ("2026-01-05", 101.0)]

    def test_days_within_counts_sessions_near_the_high(self):
        near = compute.days_within(self.points, 2.0)
        self.assertEqual(near["sessions"], 5)
        self.assertEqual(near["near"], 5)  # 99 is within 2% of 101 (>= 98.98)
        tight = compute.days_within(self.points, 0.6)
        self.assertEqual(tight["near"], 3)  # 101, 100.5, 101
        self.assertAlmostEqual(near["share_pct"], 100.0)

    def test_drawdown_recovery_reports_sessions_to_regain_the_peak(self):
        points = [("2026-01-01", 100.0), ("2026-01-02", 80.0), ("2026-01-03", 90.0),
                  ("2026-01-04", 100.0), ("2026-01-05", 70.0), ("2026-01-06", 100.0),
                  ("2026-01-07", 100.0), ("2026-01-08", 100.0)] * 3
        falls = compute.drawdown_recoveries(points, 15.0)
        self.assertTrue(falls)
        self.assertLessEqual(falls[-1]["fall_pct"], -15.0)
        self.assertIsNotNone(falls[-1]["recovered"])

    def test_rsi_divergence_is_price_low_with_rsi_high(self):
        prices = [90.0 + i * 0.1 for i in range(20)] + [
            95.0, 90.0, 93.0, 96.0, 94.0, 92.0, 88.0, 85.0, 88.0, 92.0]
        rsis = [50.0] * 20 + [50.0, 40.0, 42.0, 46.0, 45.0, 44.0, 44.0, 45.0, 46.0, 48.0]
        dated = [(f"2026-01-{i + 1:02d}", p, r) for i, (p, r) in enumerate(zip(prices, rsis))]
        found = compute.rsi_divergence(dated)
        self.assertIsNotNone(found)
        self.assertTrue(found["price_lower_low"])
        self.assertTrue(found["rsi_higher_low"])
        self.assertTrue(found["divergence"])

    def test_flow_stats_reports_volume_and_delivery(self):
        stats = compute.flow_stats([{"volume": 10, "delivery_pct": 40.0},
                                    {"volume": 30, "delivery_pct": 60.0}])
        self.assertEqual(stats["volume_last"], 30)
        self.assertEqual(stats["volume_avg"], 20)
        self.assertEqual(stats["delivery_avg"], 50.0)


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Con:
    """A facts_pilot connection that answers with fixed ``company_metric_series`` rows."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def execute(self, sql, params=()):
        self.queries.append((sql, tuple(params)))
        return _Cursor(self.rows)

    def close(self):
        pass


class _Ctx:
    def __init__(self, rows):
        self.con = _Con(rows)
        self.read = []

    def sqlite(self, name):
        self.read.append(name)
        if name != "facts_pilot":
            raise AssertionError(f"unexpected store {name}")
        return self.con


def _series_row(key, value, period_end="2026-06-30", kind="quarter", basis="consolidated"):
    return {"metric_key": key, "period_end": period_end, "period_kind": kind,
            "basis": basis, "value": value, "unit": "INR_CRORE", "source": "xbrl",
            "doc_id": "F1", "known_at": "2026-08-01T10:00:00"}


class TestFinancialConceptsReachTheFactsRows(unittest.TestCase):
    """Every company-financial concept names itself in the row it answers with."""

    def _rows(self, metric, extra=()):
        from reality_engine.query import metrics
        held = [_series_row("revenue", 1000.0), _series_row("pbt", 100.0),
                _series_row("finance_costs", 20.0), _series_row("depreciation", 30.0),
                _series_row("pat", 70.0), _series_row("eps", 7.0),
                _series_row("inventory", 200.0, kind="instant"),
                _series_row("receivables", 300.0, kind="instant"),
                _series_row("payables", 150.0, kind="instant"),
                _series_row("net_worth", 500.0, kind="instant"),
                _series_row("borrowings_current", 50.0, kind="instant"),
                _series_row("borrowings_noncurrent", 100.0, kind="instant"),
                _series_row("cash", 50.0, kind="instant")]
        ctx = _Ctx(held + list(extra))
        return ctx, metrics.pilot_rows(ctx, "INE000000000", "2026-10-19", metric,
                                       ("2026-06-30", "2026-06-30"), "quarter")

    def test_roic_is_derived_and_names_the_concept(self):
        _ctx, rows = self._rows("roic")
        self.assertEqual(len(rows), 1)
        # (100 + 20) / (500 + 50 + 100 - 50) = 20 %
        self.assertAlmostEqual(rows[0]["value"], 20.0)
        self.assertIn("roic", rows[0]["item"].lower())
        self.assertIn("return on invested capital", rows[0]["item"].lower())
        self.assertEqual(rows[0]["unit"], "%")

    def test_margin_is_ebitda_and_pat_over_revenue(self):
        _ctx, rows = self._rows("margin")
        labels = {row["item"]: row["value"] for row in rows}
        ebitda = [v for k, v in labels.items() if k.startswith("EBITDA margin")][0]
        pat = [v for k, v in labels.items() if k.startswith("PAT margin")][0]
        self.assertAlmostEqual(ebitda, 15.0)  # (100 + 20 + 30) / 1000
        self.assertAlmostEqual(pat, 7.0)
        for row in rows:
            self.assertIn("margin", row["item"].lower())
            self.assertEqual(row["unit"], "%")

    def test_working_capital_sums_the_held_components(self):
        _ctx, rows = self._rows("working_capital")
        total = [row for row in rows if row["item"].lower().startswith("working capital")]
        self.assertEqual(len(total), 1)
        self.assertAlmostEqual(total[0]["value"], 350.0)  # 200 + 300 - 150
        self.assertIn("receivables", total[0]["item"].lower())

    def test_missing_component_is_no_row_not_a_guess(self):
        from reality_engine.query import metrics
        ctx = _Ctx([_series_row("pbt", 100.0), _series_row("finance_costs", 20.0)])
        rows = metrics.pilot_rows(ctx, "INE000000000", "2026-10-19", "roic")
        self.assertEqual(rows, [])

    def test_every_row_respects_the_as_of_filter(self):
        _ctx, rows = self._rows("revenue")
        self.assertTrue(rows)
        for row in rows:
            self.assertLessEqual(str(row["known_at"])[:10], "2026-10-19")
            self.assertEqual(row["store"], "facts_pilot")


class TestRightConceptRowPassesWrongOneFails(unittest.TestCase):
    """The gate is what decides: a right-concept row passes, another concept does not."""

    def test_derived_rows_carry_the_asked_concept_and_others_do_not(self):
        from reality_engine.query import metrics
        ctx = _Ctx([_series_row("revenue", 1000.0), _series_row("pbt", 100.0),
                    _series_row("finance_costs", 20.0), _series_row("net_worth", 500.0),
                    _series_row("borrowings_current", 50.0, kind="instant"),
                    _series_row("borrowings_noncurrent", 100.0, kind="instant")])
        roic = metrics.pilot_rows(ctx, "INE000000000", "2026-10-19", "roic")
        revenue = metrics.pilot_rows(ctx, "INE000000000", "2026-10-19", "revenue")
        concepts = gate.asked_concepts("Hindalco ROIC through the cycle")
        self.assertIn("roic", concepts)
        ok, _missing = gate.ask_coverage([_hop(roic, hop="FACTS")], concepts, [])
        self.assertTrue(ok)
        ok, missing = gate.ask_coverage([_hop(revenue, hop="FACTS")], concepts, [])
        self.assertFalse(ok)
        self.assertTrue(missing and "roic" in missing[0])


class TestConceptRouting(unittest.TestCase):
    def test_an_extracted_text_value_states_its_number(self):
        self.assertEqual(compute.first_number("1,801"), 1801.0)
        self.assertEqual(compute.first_number("INR1,860 crores"), 1860.0)
        self.assertEqual(compute.first_number("350 to 400"), 350.0)
        self.assertEqual(compute.first_number("more than 25%"), 25.0)
        self.assertEqual(compute.first_number("-1192.62"), -1192.62)
        self.assertIsNone(compute.first_number("ramped up through the year"))
        self.assertIsNone(compute.first_number(None))

    def test_a_concall_value_that_states_a_number_becomes_a_fact(self):
        class Ctx:
            def rows(self, name, sql, params=()):
                if name != "concall_facts":
                    raise AssertionError(f"unexpected store {name}")
                return [{"doc_id": "D1", "metric": "Order book", "value": "1,801",
                         "unit": "INR crores", "period": "Q1FY27",
                         "quote": "order book 1,801", "filed_at": "2026-08-10T10:00:00"}]

            def one(self, *a, **k):
                return None

        rows, _ = facts._concall(Ctx(), "INE000000000", "2026-10-19", "order_book")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], 1801.0)
        self.assertEqual(rows[0]["unit"], "INR crores")

    def test_a_financial_concept_names_its_metric_when_the_router_names_none(self):
        self.assertEqual(facts.asked_metric("what does that do to return on capital"), "roic")
        self.assertEqual(facts.asked_metric("working capital cycle"), "working_capital")
        self.assertIsNone(facts.asked_metric("the 52-week high"))

    def test_named_date_reads_the_quarter_the_call_reports_on(self):
        self.assertEqual(facts._quarter_of("2025-11-04")[0], "2025-09-30")
        self.assertEqual(facts._quarter_of("2026-08-21")[0], "2026-06-30")
        self.assertEqual(facts._quarter_of("2026-01-05")[0], "2025-12-31")

    def test_bank_ratio_concepts_are_labelled_and_scaled(self):
        class Ctx:
            def rows(self, name, sql, params=()):
                if name != "results_xbrl":
                    raise AssertionError(f"unexpected store {name}")
                if "FROM filings" in sql:
                    return [{"file": "F1", "period_end": "2026-06-30", "xbrl_url": None,
                             "known_at": "2026-07-24T07:05:16"}]
                return [{"file": "F1", "concept": "PercentageOfNpa", "context": "OneD",
                         "period_start": "2026-04-01", "period_end": "2026-06-30",
                         "value": 0.005, "unit": "pure"}]

            def one(self, *a, **k):
                return None

        rows, _ = facts._results(Ctx(), "INE028A01039", "2026-10-19",
                                 ("2026-06-30", "2026-06-30"), "net_npa")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["item"], "Net NPA %")
        self.assertAlmostEqual(rows[0]["value"], 0.5)
        self.assertEqual(rows[0]["unit"], "%")

    def test_a_named_metric_without_a_schedule_returns_no_unrelated_rows(self):
        class Ctx:
            def rows(self, name, sql, params=()):
                if name != "results_xbrl":
                    raise AssertionError(f"unexpected store {name}")
                if "FROM filings" in sql:
                    return [{"file": "F1", "period_end": "2026-06-30", "xbrl_url": None,
                             "known_at": "2026-07-24T07:05:16"}]
                raise AssertionError("the schedule must not be read for this metric")

            def one(self, *a, **k):
                return None

        rows, _ = facts._results(Ctx(), "INE000000000", "2026-10-19", (None, None),
                                 "loan_growth")
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
