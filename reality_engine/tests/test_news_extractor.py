"""News extractor tests: pure fixtures, zero network, no live DB."""
import unittest
from datetime import date

from reality_engine.processing import news_explainer, news_extractor
from reality_engine.processing.news_explainer import _severity_for_title
from reality_engine.processing.news_extractor import (
    CATEGORIES,
    build_brief,
    classify_category,
    extract_item,
    extract_numbers,
    rank_importance,
    score_item,
)


def _rec(title, text="", **kw):
    """NewsRss-normalized record shape (news_feed_client.normalize)."""
    row = {
        "title": title,
        "text": text or title,
        "published_date": "2026-09-19",
        "source_type": "News_livemint",
        "symbols": [],
    }
    row.update(kw)
    return row


class TestCategoryClassification(unittest.TestCase):
    def test_one_fixture_per_category(self):
        fixtures = [
            (_rec("Company Q2 profit rises 20%"), "results"),
            (_rec("Firm bags order worth big money"), "orders_deals"),
            (_rec("Brokerage upgrades stock, hikes target price"), "ratings"),
            (_rec("Board appoints new CEO"), "management"),
            (_rec("SEBI imposes penalty on broker"), "legal_regulatory"),
            (_rec("RBI keeps repo rate unchanged"), "policy_macro"),
            (_rec("Sensex, Nifty end higher on FII buying"), "markets"),
            (_rec("Monsoon rains above normal this week"), "other"),
        ]
        for record, expected in fixtures:
            with self.subTest(expected=expected):
                self.assertEqual(extract_item(record)["category"], expected)
                self.assertIn(expected, CATEGORIES)

    def test_first_match_wins_order(self):
        # 'q3' (results) precedes 'order' (orders_deals) in the ordered map.
        self.assertEqual(
            classify_category("Q3 order book strongest ever"), "results")

    def test_empty_text_is_other(self):
        self.assertEqual(classify_category(""), "other")
        self.assertEqual(classify_category(None), "other")


class TestSeverityDelegation(unittest.TestCase):
    def test_single_severity_map_reused(self):
        # Identity, not a copy: extractor defines no second keyword map.
        self.assertIs(news_extractor.KEYWORD_SEVERITY, news_explainer.KEYWORD_SEVERITY)

    def test_severity_matches_explainer(self):
        titles = [
            "CFO resignation with immediate effect",
            "SEBI raid at premises",
            "Company clarifies on news report",
            "Board approves appointment of director",
            "Monsoon rains above normal",
        ]
        for title in titles:
            with self.subTest(title=title):
                item = extract_item(_rec(title))
                self.assertEqual(item["severity"], _severity_for_title(title))

    def test_high_keyword_beats_medium(self):
        item = extract_item(_rec("Buyback order after fraud probe"))
        self.assertEqual(item["severity"], "HIGH")


class TestNumberExtraction(unittest.TestCase):
    def test_percentage_rupee_and_price_level(self):
        item = extract_item(_rec(
            "Q2 profit jumps",
            "Net profit ₹1,234 crore, up 12.5% YoY; index level 1450 eyed.",
        ))
        numbers = item["numbers"]
        self.assertEqual(numbers["percentages"], ["12.5%"])
        self.assertEqual(numbers["rupee_amounts"], ["₹1,234 crore"])
        self.assertEqual(numbers["price_levels"], ["1450"])

    def test_rupee_and_percent_not_reported_as_price_levels(self):
        numbers = extract_numbers("Rs. 500 cr revenue, margin 8.2%")
        self.assertEqual(numbers["rupee_amounts"], ["₹500 cr"])
        self.assertEqual(numbers["percentages"], ["8.2%"])
        self.assertEqual(numbers["price_levels"], [])

    def test_lists_capped_at_five_and_deduped(self):
        numbers = extract_numbers(
            "1% 2% 3% 4% 5% 6% 7% and 1% again plus Rs. 10 Rs. 20")
        self.assertEqual(len(numbers["percentages"]), 5)
        self.assertEqual(numbers["percentages"], ["1%", "2%", "3%", "4%", "5%"])
        self.assertEqual(numbers["rupee_amounts"], ["₹10", "₹20"])

    def test_currency_symbol_inside_words_is_not_a_match(self):
        # Regression: case-insensitive 'Rs.' used to match the tail of
        # "investors," / "Traders," and emit junk amounts.
        numbers = extract_numbers(
            "investors, Traders, and years, later; concerns, resolutions")
        self.assertEqual(numbers["rupee_amounts"], [])

    def test_grouped_numbers_do_not_fragment_into_price_levels(self):
        numbers = extract_numbers("Volume 1,000 units, index level 24500")
        self.assertEqual(numbers["price_levels"], ["24500"])

    def test_no_numbers_is_empty_lists(self):
        numbers = extract_numbers("Monsoon rains above normal")
        self.assertEqual(
            numbers,
            {"percentages": [], "rupee_amounts": [], "price_levels": []})

    def test_every_list_shape_present(self):
        numbers = extract_item(_rec("Monsoon normal"))["numbers"]
        self.assertEqual(
            sorted(numbers), ["percentages", "price_levels", "rupee_amounts"])


class TestRanking(unittest.TestCase):
    def _items(self):
        high = extract_item(_rec(
            "Q3 results: fraud probe hits profit", symbols=["AAA"]))
        medium = extract_item(_rec("Firm bags order", symbols=["BBB"]))
        low = extract_item(_rec("Monsoon rains above normal"))
        return high, medium, low

    def test_high_symbols_results_item_first(self):
        high, medium, low = self._items()
        ranked = rank_importance([low, medium, high])
        self.assertEqual(ranked[0]["title"], high["title"])
        self.assertEqual(ranked[0]["severity"], "HIGH")
        self.assertEqual(ranked[0]["category"], "results")
        self.assertEqual(ranked[-1]["title"], low["title"])

    def test_score_components(self):
        high, medium, low = self._items()
        # HIGH(3)*2 + symbols(1) + no numbers + results bonus(1)
        self.assertEqual(score_item(high), 8)
        # MEDIUM(2)*2 + symbols(1) + orders_deals bonus(1)
        self.assertEqual(score_item(medium), 6)
        # LOW(1)*2 + nothing
        self.assertEqual(score_item(low), 2)

    def test_numbers_contribute_at_most_three(self):
        base = extract_item(_rec("Monsoon rains above normal"))
        rich = dict(base, numbers={
            "percentages": ["1%", "2%", "3%", "4%", "5%"],
            "rupee_amounts": ["₹1"], "price_levels": []})
        self.assertEqual(score_item(rich) - score_item(base), 3)

    def test_scores_descending_and_stable_for_ties(self):
        high, medium, low = self._items()
        tie_a = extract_item(_rec("Monsoon rains above normal in north"))
        tie_b = extract_item(_rec("Monsoon rains above normal in south"))
        ranked = rank_importance([low, tie_a, tie_b, medium, high])
        scores = [score_item(it) for it in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual([it["title"] for it in ranked][-2:],
                         [tie_a["title"], tie_b["title"]])

    def test_empty_input_and_non_dict_entries(self):
        self.assertEqual(rank_importance([]), [])
        self.assertEqual(rank_importance(None), [])
        kept = rank_importance([None, "junk", extract_item(_rec("Monsoon"))])
        self.assertEqual(len(kept), 1)


class TestBuildBrief(unittest.TestCase):
    def _items(self):
        return [
            extract_item(_rec(
                "Q3 results: fraud probe hits profit",
                symbols=["AAA", "BBB"])),
            extract_item(_rec("Firm bags order", symbols=["CCC"])),
            extract_item(_rec("Monsoon rains above normal")),
        ]

    def test_sections_and_top_item_present(self):
        brief = build_brief(self._items())
        self.assertIn("# Market News Brief — 2026-09-19", brief)
        self.assertIn("## results", brief)
        self.assertIn("## orders_deals", brief)
        self.assertIn("## other", brief)
        self.assertNotIn("## markets", brief)  # empty sections omitted
        self.assertIn(
            "- [AAA, BBB] Q3 results: fraud probe hits profit (HIGH) "
            "— News_livemint 2026-09-19", brief)
        self.assertIn("Symbols tagged: 3", brief)
        # Top-ranked (HIGH + symbols + results) line precedes the others.
        self.assertLess(brief.index("fraud probe"),
                        brief.index("Firm bags order"))
        self.assertLess(brief.index("## results"), brief.index("## orders_deals"))

    def test_top_n_truncates(self):
        brief = build_brief(self._items(), top_n=1)
        self.assertIn("Q3 results: fraud probe", brief)
        self.assertNotIn("Firm bags order", brief)
        self.assertNotIn("## orders_deals", brief)
        self.assertIn("Items: 1", brief)
        self.assertIn("Symbols tagged: 2", brief)

    def test_empty_input_header_only(self):
        brief = build_brief([])
        self.assertEqual(brief.count("\n"), 2)
        self.assertTrue(
            brief.startswith(f"# Market News Brief — {date.today().isoformat()}"))
        self.assertIn("no items", brief)
        self.assertIn("Symbols tagged: 0", brief)
        self.assertNotIn("## ", brief)
        self.assertNotIn("- [", brief)

    def test_none_input_header_only(self):
        self.assertNotIn("## ", build_brief(None))


class TestFailClosed(unittest.TestCase):
    def test_non_dict_or_empty_record_returns_empty_item(self):
        for record in (None, {}, "junk", [], {"title": "  "}):
            with self.subTest(record=record):
                item = extract_item(record)
                self.assertEqual(item["symbols"], [])
                self.assertEqual(item["category"], "other")
                self.assertEqual(item["severity"], "LOW")
                self.assertEqual(item["title"], "")
                self.assertIsNone(item["published_date"])
                self.assertEqual(
                    item["numbers"],
                    {"percentages": [], "rupee_amounts": [], "price_levels": []})

    def test_tolerant_record_keys(self):
        item = extract_item({
            "headline": "RBI keeps repo rate",
            "summary": "Policy unchanged",
            "pubDate": "Sat, 19 Sep 2026 17:50:00 +0530",
            "source": "News_bs",
            "symbol": "reliance, infy",
        })
        self.assertEqual(item["title"], "RBI keeps repo rate")
        self.assertEqual(item["category"], "policy_macro")
        self.assertEqual(item["published_date"], "2026-09-19")
        self.assertEqual(item["source_type"], "News_bs")
        self.assertEqual(item["symbols"], ["RELIANCE", "INFY"])

    def test_text_already_containing_title_is_not_doubled(self):
        item = extract_item({
            "title": "Margins slip 4.5%",
            "text": "Margins slip 4.5% :: Operating margin down",
            "symbols": [],
        })
        self.assertEqual(item["numbers"]["percentages"], ["4.5%"])


if __name__ == "__main__":
    unittest.main()
