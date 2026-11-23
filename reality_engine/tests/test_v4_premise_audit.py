"""Offline checks for the premise audit (Gate 95% review, ideas 3 and 6).

No live DB, no network: a fake lookup feeds :func:`audit_row` the same values the
store layer returns.  The three cases the brief names are the first three tests:
a false move premise is flagged, a true one is not, an uncheckable one is
``cannot_check``.
"""
import unittest

from reality_engine.pilot.premise_audit import (
    audit_row,
    business_class,
    class_applicable,
    company_aliases,
    judge_move,
    parse_move_premise,
    select_sheet_a,
)


class FakeLookups:
    """The store layer's contract, filled from dicts."""

    def __init__(self, moves=None, identities=None, sessions=None, order_book=None,
                 parent_alias=None):
        self.moves = moves or {}
        self.identities = identities or {}
        self.sessions = sessions or {}
        self.order_book = order_book or {}
        self.parent_alias = parent_alias or {}

    def identity(self, isin):
        return self.identities.get(isin) or {"name": "", "symbol": "", "sector": "",
                                             "industry": "", "basic_industry": ""}

    def move(self, isin, date):
        return self.moves.get((isin, date))

    def sessions_around(self, isin, date):
        return self.sessions.get(isin)

    def first_session(self, isin):
        return self.sessions.get(isin + ":first")

    def order_book_count(self, isin):
        return self.order_book.get(isin, 0), "fake store"

    def names_in(self, question, isin):
        for alias in self.parent_alias.get(isin, []):
            if alias.lower() in question.lower():
                return alias
        return None


def move(date="2026-05-14", prev_date="2026-05-13", prev_close=2945.60, close=2938.70):
    return {"date": date, "close": close, "prev_date": prev_date, "prev_close": prev_close,
            "pct": round((close / prev_close - 1) * 100, 4), "basis": "raw close-to-close",
            "source": "equity_intelligence.daily_price_delivery[isin=X,date=%s]" % date}


def stock_row(question, **overrides):
    row = {
        "mid": "MB0438#L", "parent_mid": "MB0438", "kind": "stock", "bucket": "LARGE",
        "family": [12], "sector": "Construction Materials",
        "entities": [{"isin": "INE047A01021", "symbol": "GRASIM"}],
        "substituted_from": [{"isin": "INE918Z01012", "sector": "Capital Goods"}],
        "question": question,
        "as_of": "2026-05-14", "period": "2026-05-13 to 2026-05-14",
    }
    row.update(overrides)
    return row


PARENT = {"mid": "MB0438", "question": "Kaynes fell 20.15% on 14 May 2026. What did it file?"}


class PricePremiseTest(unittest.TestCase):
    def test_false_price_premise_is_flagged(self):
        rows = {"INE047A01021": {"symbol": "GRASIM", "sector": "Construction Materials",
                                 "industry": "Cement", "basic_industry": "Cement"}}
        record = audit_row(stock_row("GRASIM fell 20.15% on 14 May 2026. What did it file?"),
                           PARENT, FakeLookups(moves={("INE047A01021", "2026-05-14"): move()},
                                               identities=rows))
        self.assertEqual(record["verdict"], "false")
        self.assertEqual(record["reason"], "price_move_contradicted")
        self.assertIn("stored -0.23%", record["evidence"][0]["value"])
        self.assertIn("daily_price_delivery", record["source"])

    def test_true_price_premise_is_not_flagged(self):
        rows = {"INE114A01011": {"symbol": "SAIL", "sector": "Metals & Mining",
                                 "industry": "Iron & Steel", "basic_industry": "Iron & Steel"}}
        row = stock_row("SAIL fell 20.02% on 2024-06-04 and Nifty Metal fell 10.63%.",
                        entities=[{"isin": "INE114A01011", "symbol": "SAIL"}],
                        substituted_from=[{"isin": "INE114A01011"}],
                        as_of="2024-06-04", period="2024-06-04")
        record = audit_row(row, PARENT, FakeLookups(
            moves={("INE114A01011", "2024-06-04"): move("2024-06-04", "2024-06-03", 166.36, 133.05)},
            identities=rows))
        self.assertEqual(record["verdict"], "holds")
        self.assertEqual(record["reason"], "price_move_confirmed")

    def test_uncheckable_price_premise_is_cannot_check(self):
        record = audit_row(
            stock_row("GRASIM fell 20.15% on 2026-05-14. What did it file?"), PARENT,
            FakeLookups(moves={}, identities={"INE047A01021": {"symbol": "GRASIM"}},
                        sessions={"INE047A01021": "first session 2021-06-01"}))
        self.assertEqual(record["verdict"], "cannot_check")
        self.assertEqual(record["reason"], "price_move_not_stored")
        self.assertIn("first session 2021-06-01", record["evidence"][0]["value"])


class ParseTest(unittest.TestCase):
    def test_relative_session_uses_the_period_end(self):
        premise = parse_move_premise(
            "Hindalco filed at 19:56 on 30 July 2026 and rose 1.48% the next session.",
            "2026-07-30 to 2026-07-31")
        self.assertEqual(premise["date"], "2026-07-31")
        self.assertEqual(premise["signed_pct"], 1.48)

    def test_verb_nearest_the_percentage_wins(self):
        premise = parse_move_premise("HEG Advanced Materials Limited fell 42.93% on 7 April 2025.")
        self.assertEqual(premise["verb"], "fell")
        self.assertEqual(premise["signed_pct"], -42.93)
        self.assertEqual(premise["date"], "2025-04-07")

    def test_floor_phrase_is_a_floor(self):
        premise = parse_move_premise("REC and PFC both fell more than 23% on 4 June 2024.")
        self.assertTrue(premise["floor"])
        self.assertEqual(judge_move(premise, -25.19)[0], "holds")
        self.assertEqual(judge_move(premise, -2.0)[0], "false")

    def test_plain_sentence_has_no_move_premise(self):
        self.assertIsNone(parse_move_premise("What did the company file on 14 May 2026?"))


class OtherReasonsTest(unittest.TestCase):
    def test_leftover_parent_name_is_flagged(self):
        row = stock_row("Tata Power's RSI dipped below 30 in an uptrend.",
                        entities=[{"isin": "INE589A01014", "symbol": "NLCINDIA"}],
                        substituted_from=[{"isin": "INE245A01021", "sector": "Power"}])
        record = audit_row(row, {"question": "Tata Power's RSI dipped below 30."},
                           FakeLookups(identities={"INE589A01014": {"symbol": "NLCINDIA"}},
                                       parent_alias={"INE245A01021": ["Tata Power"]}))
        self.assertEqual(record["verdict"], "false")
        self.assertIn("names_other_company", record["reasons"])
        self.assertIn("INE245A01021", record["evidence"][0]["value"])

    def test_order_book_does_not_fit_a_lender(self):
        row = stock_row("BAJFINANCE's order book is Rs 9,923 crore as of 30 June 2026.",
                        entities=[{"isin": "INE296A01032", "symbol": "BAJFINANCE"}])
        identities = {"INE296A01032": {"symbol": "BAJFINANCE", "sector": "Financial Services",
                                       "industry": "Financial Services",
                                       "basic_industry": "Consumer Finance"}}
        record = audit_row(row, {"question": "x"}, FakeLookups(identities=identities))
        self.assertEqual(record["verdict"], "false")
        self.assertEqual(record["reason"], "business_type_mismatch")
        self.assertIn("Financial Services", record["evidence"][0]["value"])

    def test_order_book_fits_an_industrial_name(self):
        row = stock_row("KEC's order book is Rs 9,923 crore.",
                        entities=[{"isin": "INE389H01022", "symbol": "KEC"}])
        identities = {"INE389H01022": {"symbol": "KEC", "sector": "Capital Goods",
                                       "industry": "Construction", "basic_industry": "EPC"}}
        record = audit_row(row, {"question": "x"}, FakeLookups(identities=identities,
                                                              order_book={"INE389H01022": 12}))
        self.assertEqual(record["verdict"], "cannot_check")
        self.assertEqual(record["reason"], "business_type_plausible")
        self.assertIn("12", record["evidence"][0]["value"])

    def test_listing_premise_before_the_window_is_flagged(self):
        row = stock_row("Hindalco: was the listing-day move justified by the prospectus?",
                        entities=[{"isin": "INE038A01020", "symbol": "HINDALCO"}],
                        bucket="LARGE", as_of="2026-10-19", period="2026")
        record = audit_row(row, {"question": "x"}, FakeLookups(
            identities={"INE038A01020": {"symbol": "HINDALCO"}},
            sessions={"INE038A01020:first": "2019-01-01"}))
        self.assertEqual(record["verdict"], "false")
        self.assertEqual(record["reason"], "listing_premise_outside_store")

    def test_as_is_row_has_no_substitution(self):
        row = {"mid": "MB0421", "parent_mid": "MB0421", "kind": "as_is", "bucket": None,
               "family": [14], "entities": [{"type": "index", "name": "Nifty 50"}],
               "question": "On 4 June 2024 the Nifty 50 fell 5.93%.", "as_of": None,
               "period": None}
        record = audit_row(row, {"question": row["question"]}, FakeLookups())
        self.assertEqual(record["verdict"], "cannot_check")
        self.assertEqual(record["reason"], "no_substitution")


class HelpersTest(unittest.TestCase):
    def test_business_class_and_applicability(self):
        self.assertEqual(business_class("Fuel is the largest variable cost for an airline."),
                         "airline")
        self.assertTrue(class_applicable("airline", [{"basic_industry": "Airline"}]))
        self.assertFalse(class_applicable("airline", [{"sector": "Healthcare"}]))

    def test_aliases_keep_a_short_informal_name(self):
        aliases = company_aliases("Adani Ports and Special Economic Zone Limited",
                                  "ADANIPORTS", "532921")
        self.assertIn("adani ports", aliases)
        self.assertIn("adaniports", aliases)

    def test_sheet_a_selection_is_seeded_and_covers_reasons(self):
        records = []
        for reason in ("price_move_contradicted", "names_other_company",
                       "business_type_mismatch"):
            for index in range(20):
                records.append({"mid": "%s#%d" % (reason, index), "reason": reason,
                                "verdict": "false"})
        first = [record["mid"] for record in select_sheet_a(records, count=30)]
        second = [record["mid"] for record in select_sheet_a(records, count=30)]
        self.assertEqual(first, second)
        self.assertEqual(len(first), 30)
        self.assertEqual(len({mid.split("#")[0] for mid in first}), 3)


if __name__ == "__main__":
    unittest.main()
