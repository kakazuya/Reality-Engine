"""Ask-concept routing: the gate's alias table, the row that must carry it, and the
computations the bank asks for by name (sessions near the high, drawdown recovery,
RSI divergence, volume/delivery, holdings, price bands, narrative concepts).

The rule the task fixes: a row carries a concept only when the ask really names it,
and a row of the right concept passes while a row of another concept still fails.
"""
import unittest

from reality_engine.query import compute, gate
from reality_engine.query.decompose import decompose
from reality_engine.query.planners import evidence, facts, screen, series


def _hop(rows, hop="SERIES", detail=""):
    return {"hop": hop, "rows": rows, "detail": detail}


def _coverage(question, hop):
    ok, _missing = gate.ask_coverage([hop], gate.asked_concepts(question), [])
    return bool(ok)


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

    def test_ranking_language_is_not_a_range_ask(self):
        # "ranked from highest to lowest" is the ranking, not the 52-week high.
        concepts = gate.asked_concepts("promoter holding ranked from highest to lowest")
        self.assertIn("promoter", concepts)
        self.assertNotIn("range", concepts)
        self.assertNotIn("range", gate.asked_concepts("which name is higher than its peer"))
        self.assertNotIn("range", gate.asked_concepts("does the crude move support a recovery"))

    def test_food_delivery_is_not_exchange_delivery(self):
        self.assertNotIn("delivery", gate.asked_concepts("food-delivery fees and take rate"))
        self.assertIn("delivery", gate.asked_concepts("delivery percentage on 16 Oct 2026"))

    def test_business_volume_is_not_the_traded_quantity(self):
        self.assertNotIn("volume", gate.asked_concepts("cement volume growth in Q1FY27"))
        self.assertNotIn("volume", gate.asked_concepts(
            "is the growth from volume or from price and mix"))
        self.assertIn("volume", gate.asked_concepts("BHEL 4 Jun 2024 volume and delivery"))

    def test_single_entity_band_is_not_a_market_screen(self):
        from reality_engine.query.planners import screen
        slots = {"question": "Suzlon: which band applies now", "symbol": "SUZLON",
                 "isin": "INE155A01022", "entity_level": "stock",
                 "needs": {"screen": True}}
        hop = screen.plan(slots, "2026-10-19", None)
        self.assertTrue(hop["na"])
        self.assertIn("SERIES", hop["detail"])

    def test_sector_name_is_not_a_products_ask(self):
        self.assertNotIn("products", gate.asked_concepts(
            "For all listed companies in Petroleum Products, which swung to a loss"))
        self.assertIn("products", gate.asked_concepts(
            "What are the key products of Chemcon Speciality Chemicals"))

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

    def test_wrong_concept_row_still_fails_for_narrative(self):
        close_only = _hop([{"ref": "IRISDOREME", "item": "close"}], hop="EVIDENCE")
        self.assertFalse(_coverage("IRISDOREME manufacturing facilities", close_only))
        facility = _hop([{"ref": "IRISDOREME",
                          "quote": "Manufacturing facilities expanded to 13 units"},
                         ], hop="EVIDENCE")
        self.assertTrue(_coverage("IRISDOREME manufacturing facilities", facility))

    def test_volume_and_delivery_rows_carry_the_fields(self):
        self.assertTrue(_coverage("BHEL 4 Jun 2024 volume",
                                  _hop([{"ref": "BHEL", "item": "close, volume"}])))
        self.assertFalse(_coverage("BHEL 4 Jun 2024 volume",
                                   _hop([{"ref": "BHEL", "item": "close"}])))
        self.assertTrue(_coverage("BHEL 4 Jun 2024 delivery",
                                  _hop([{"ref": "BHEL", "item": "close, delivery"}])))

    def test_band_row_carries_the_band(self):
        concepts = gate.asked_concepts("GTL Infra upper price band on 23 Oct 2026")
        self.assertIn("band", concepts)
        band_row = _hop([{"ref": "price_bands:GTLINFRA", "item": "price band 20%"}])
        self.assertTrue(_coverage("GTL Infra upper price band on 23 Oct 2026", band_row))
        close_row = _hop([{"ref": "GTLINFRA", "item": "close"}])
        self.assertFalse(_coverage("GTL Infra upper price band on 23 Oct 2026", close_row))

    def test_holding_rows_name_the_promoter_public_and_pledge_fields(self):
        class Ctx:
            def cache_get(self, key):
                return None

            def cache_put(self, key, value):
                pass

            def rows(self, db, sql, params=()):
                return []

        ctx = Ctx()
        quarter = [{"isin": "INE214T01019", "quarter_end": "2026-09-30",
                    "known_at": "2026-10-14", "promoter_pct": 68.49,
                    "public_pct": 31.46, "pledge_pct": 1.2}]
        import unittest.mock as mock
        with mock.patch.object(screen, "_t1_rows", return_value=quarter):
            promoter = screen._holding_rows(ctx, ["INE214T01019"], "LTM", "2026-10-19",
                                            False, False)
            public = screen._holding_rows(ctx, ["INE214T01019"], "LTM", "2026-10-19",
                                          True, False)
            pledge = screen._holding_rows(ctx, ["INE214T01019"], "LTM", "2026-10-19",
                                          False, True)
        self.assertIn("Promoter holding", promoter[0]["item"])
        self.assertIn("Public holding", public[0]["item"])
        self.assertTrue(any("pledge" in row["item"].lower() for row in pledge))

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

    def test_narrative_concept_is_recognised_and_ranked_first(self):
        concept = evidence._narrative_of("which company did the deck mention as acquired")
        self.assertIsNotNone(concept)
        name, terms, doc_types = concept
        self.assertEqual(name, "acquisition")
        self.assertIn("announcement", doc_types)
        title = {"doc_type": "deck", "quote": "Investor Presentation – May 2026"}
        body = {"doc_type": "deck", "quote": "Inorganic Growth – Acquired Shivam Petrochem"}
        self.assertEqual(evidence._concept_hits(str(title["quote"]), terms), 0)
        self.assertGreater(evidence._concept_hits(str(body["quote"]), terms), 0)
        preferred = evidence._prefer_doc_type([title, dict(body, doc_type="announcement")],
                                              doc_types)
        self.assertEqual(preferred[0]["doc_type"], "announcement")

    def test_narrative_concept_absent_means_no_ask(self):
        self.assertIsNone(evidence._narrative_of("what did the management say"))
        self.assertIsNone(evidence._narrative_of("what was the close on 16 Oct"))

    def test_decomposer_carries_the_whole_ask_into_every_sub(self):
        case = {"question": "AEROFLEX products; what was the close on 16 Oct 2026?",
                "family": [2], "period": "16 Oct 2026",
                "entities": [{"symbol": "AEROFLEX"}]}
        subs = decompose(case)
        self.assertEqual(len(subs), 2)
        self.assertIn("products", subs[0]["text"])
        self.assertIn("price return", subs[0]["text"])  # the other half of the ask
        self.assertIn("products", gate.asked_concepts(subs[0]["text"]))
        self.assertIn("return", gate.asked_concepts(subs[0]["text"]))
        self.assertIn("products", subs[1]["text"])
        self.assertIn("products", gate.asked_concepts(subs[1]["text"]))

    def test_decomposer_adds_the_parent_concept_to_a_short_sub(self):
        case = {"question": "How many manufacturing facilities does IRISDOREME report, "
                            "and where are they?", "family": [5],
                "entities": [{"symbol": "IRISDOREME"}]}
        subs = decompose(case)
        self.assertEqual(len(subs), 2)
        self.assertIn("facilities", subs[1]["text"])
        self.assertIn("facilities", gate.asked_concepts(subs[1]["text"]))


class TestSeriesFieldLabels(unittest.TestCase):
    def test_range_study_window_reads_the_asks_own_span(self):
        span = series._study_window("YTD high in 1 January-30 September 2026", "2026-09-30")
        self.assertEqual(span, ("2026-01-01", "2026-09-30", "asked span"))
        self.assertEqual(series._study_window("the 52-week high", "2026-10-19")[2], "52 weeks")

    def test_ytd_with_an_as_of_date_uses_the_year_not_the_day(self):
        # "As of 30 June 2026 ... YTD high in 2026 up to that date" is a 1 Jan-30 Jun
        # window, not the single 30 June session.
        window = series._study_window(
            "As of 30 June 2026, what was its YTD high in 2026 up to that date?",
            "2026-10-19")
        self.assertEqual(window, ("2026-01-01", "2026-06-30", "YTD"))
        self.assertEqual(series._study_window("high on 16 Oct 2026", "2026-10-19"),
                         ("2026-10-16", "2026-10-16", "asked date"))

    def test_valuation_follow_up_with_a_hyphen_is_still_the_valuation_ask(self):
        self.assertTrue(series.VALUATION_ASK.search("the book-value date".replace("-", " ")))
        concepts = gate.asked_concepts("state the price date and the book-value date")
        self.assertIn("valuation", concepts)
        row = _hop([{"ref": "GOLDIAM", "item": "P/E, P/B, book value per share, market cap"}])
        self.assertTrue(_coverage("state the price date and the book-value date", row))
        close = _hop([{"ref": "GOLDIAM", "item": "close"}])
        self.assertFalse(_coverage("state the price date and the book-value date", close))



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


if __name__ == "__main__":
    unittest.main()
