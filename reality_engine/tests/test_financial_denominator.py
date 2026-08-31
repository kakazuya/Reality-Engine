"""Financial denominator — operating vs synthetic instrument filter."""
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing.instrument_classifier import classify_instrument_type, is_operating_equity
from reality_engine.processing import financial_validator


def _make_annual(isin, symbol, fy="FY26"):
    return {
        "isin": isin,
        "symbol": symbol,
        "fiscal_year": fy,
        "revenue_inr_cr": 1000.0,
        "ebitda_inr_cr": 200.0,
        "net_profit_inr_cr": 100.0,
        "eps_inr": 10.0,
        "opm_pct": 20.0,
        "npm_pct": 10.0,
        "roce_pct": 15.0,
        "roe_pct": 12.0,
        "debt_inr_cr": 500.0,
        "equity_inr_cr": 1000.0,
        "debt_to_equity": 0.5,
        "interest_coverage": 5.0,
        "operating_cash_flow_inr_cr": 150.0,
        "free_cash_flow_inr_cr": 80.0,
        "source": "yfinance",
    }


CORE_SYNTHETICS = [
    {"isin": None, "nse_symbol": "NIFTYBEES", "bse_code": None, "company_name": "NIPPON INDIA ETF NIFTY BEES", "is_active": 1},
    {"isin": "INE_AUTO_456", "nse_symbol": "LIQUIDBEES", "bse_code": None, "company_name": "NIPPON INDIA ETF LIQUID BEES", "is_active": 1},
    {"isin": "INE_AUTO_789", "nse_symbol": "GOLDBEES", "bse_code": None, "company_name": "NIPPON INDIA ETF GOLD BEES", "is_active": 1},
    {"isin": "INE_AUTO_999", "nse_symbol": "ABSLBANETF", "bse_code": None, "company_name": "ADITYA BIRLA SUN LIFE BANKING ETF", "is_active": 1},
    {"isin": "INE123B01001", "nse_symbol": "GANGAFO-RE", "bse_code": "543999", "company_name": "GANGA FORGING RIGHTS ENTITLEMENT", "is_active": 1},
]

CORE_OPERATING = [
    {"isin": "INE002A01018", "nse_symbol": "RELIANCE", "bse_code": "500325", "company_name": "RELIANCE INDUSTRIES LTD", "is_active": 1},
    {"isin": "INE467B01029", "nse_symbol": "TCS", "bse_code": "532540", "company_name": "TATA CONSULTANCY SERVICES LTD", "is_active": 1},
    {"isin": "INE066F01020", "nse_symbol": "HAL", "bse_code": "541154", "company_name": "HINDUSTAN AERONAUTICS LTD", "is_active": 1},
    {"isin": "INE144J01027", "nse_symbol": "20MICRONS", "bse_code": "533022", "company_name": "20 MICRONS LTD", "is_active": 1},
]

TRICKY = [
    {"isin": "INE040H01013", "nse_symbol": "JETFREIGHT", "bse_code": "543420", "company_name": "JET FREIGHT LOGISTICS LTD", "is_active": 1},
    {"isin": "INE010B01016", "nse_symbol": "FIRSTCRY", "bse_code": "544122", "company_name": "BRAINBEES SOLUTIONS LTD", "is_active": 1},
    {"isin": "INE002B01023", "nse_symbol": "BAJAJ-AUTO", "bse_code": "532977", "company_name": "BAJAJ AUTO LTD", "is_active": 1},
]


class TestFinancialDenominator(unittest.TestCase):
    def test_etf_classification_excludes_bees_liquid_rights(self):
        for rec in CORE_SYNTHETICS:
            self.assertEqual(classify_instrument_type(rec), "synthetic", f"{rec['nse_symbol']} should be synthetic")
            self.assertFalse(is_operating_equity(rec))
        for rec in CORE_OPERATING:
            self.assertEqual(classify_instrument_type(rec), "operating_equity", f"{rec['nse_symbol']} should be operating")
            self.assertTrue(is_operating_equity(rec))
        # tricky negatives must stay operating
        for rec in TRICKY:
            self.assertEqual(classify_instrument_type(rec), "operating_equity", f"{rec['nse_symbol']} should be operating not synthetic")
        # direct dict checks
        self.assertEqual(classify_instrument_type({"isin": "INE002A01018", "nse_symbol": "RELIANCE", "company_name": "RELIANCE INDUSTRIES LTD"}), "operating_equity")
        self.assertEqual(classify_instrument_type({"isin": "INE_AUTO_1", "nse_symbol": "FOO", "company_name": "FOO LTD"}), "synthetic")
        self.assertEqual(classify_instrument_type({"isin": "INE123A01011", "nse_symbol": "NIFTYBEES", "company_name": "SOMETHING"}), "synthetic")

    def test_operating_universe_excludes_synthetic(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.db"
            mgr = DatabaseManager(db_path=db_path)
            repo = Repository(manager=mgr)
            # seed all: 5 synthetic + 4 operating + 3 tricky(operating) =12
            all_recs = CORE_SYNTHETICS + CORE_OPERATING + TRICKY
            repo.upsert_master_companies(all_recs)
            operating = repo.get_operating_equity_universe(active_only=True)
            synthetic = repo.get_synthetic_instrument_list(active_only=True)
            op_syms = {r["nse_symbol"] for r in operating}
            syn_syms = {r["nse_symbol"] for r in synthetic}
            # operating should include HAL etc but not BEES
            for rec in CORE_OPERATING:
                self.assertIn(rec["nse_symbol"], op_syms)
            for rec in TRICKY:
                self.assertIn(rec["nse_symbol"], op_syms)
            for rec in CORE_SYNTHETICS:
                self.assertIn(rec["nse_symbol"], syn_syms)
                self.assertNotIn(rec["nse_symbol"], op_syms)
            # complement
            self.assertEqual(len(operating) + len(synthetic), len(all_recs))
            self.assertEqual(len(operating), 7)  # 4 core operating +3 tricky
            self.assertEqual(len(synthetic), 5)

    def test_denominator_counts_respects_operating_filter(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.db"
            mgr = DatabaseManager(db_path=db_path)
            repo = Repository(manager=mgr)
            # only core 5+4 for exact counts
            repo.upsert_master_companies(CORE_SYNTHETICS + CORE_OPERATING)
            # annual for RELIANCE + TCS only
            repo.upsert_annual_financials([_make_annual("INE002A01018", "RELIANCE"), _make_annual("INE467B01029", "TCS")])
            counts = repo.get_annual_financial_denominator_counts()
            self.assertEqual(counts["operating_total"], 4)
            self.assertEqual(counts["synthetic_total"], 5)
            self.assertEqual(counts["covered"], 2)
            self.assertEqual(counts["missing"], 2)
            self.assertEqual(counts["coverage_pct_operating"], 50.0)
            self.assertEqual(counts["synthetic_excluded"], 5)
            # validator same via raw conn
            with mgr.session() as conn:
                v = financial_validator.validate_annual_financial_denominator(conn)
                self.assertEqual(v["operating_total"], 4)
                self.assertEqual(v["synthetic_total"], 5)
                self.assertEqual(v["covered"], 2)
                self.assertEqual(v["missing"], 2)

    def test_microcap_candidates_are_operating_and_missing_financials(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.db"
            mgr = DatabaseManager(db_path=db_path)
            repo = Repository(manager=mgr)
            repo.upsert_master_companies(CORE_SYNTHETICS + CORE_OPERATING)
            repo.upsert_annual_financials([_make_annual("INE002A01018", "RELIANCE"), _make_annual("INE467B01029", "TCS")])
            cands = repo.discover_microcap_official_filing_candidates(limit=12)
            cand_syms = [c["nse_symbol"] for c in cands]
            # should be HAL and 20MICRONS (operating missing), not synthetics
            self.assertIn("HAL", cand_syms)
            self.assertIn("20MICRONS", cand_syms)
            for syn in ["NIFTYBEES", "LIQUIDBEES", "GOLDBEES", "ABSLBANETF", "GANGAFO-RE"]:
                self.assertNotIn(syn, cand_syms)
            # check suggested_source present
            for c in cands:
                self.assertIn("suggested_source", c)
                self.assertIn(c["suggested_source"], ("bse_official", "nse_official"))
                self.assertEqual(c["reason_missing"], "no_annual_row")
            # limit
            limited = repo.discover_microcap_official_filing_candidates(limit=1)
            self.assertEqual(len(limited), 1)
            # validator direct
            with mgr.session() as conn:
                v = financial_validator.discover_microcap_official_filing_candidates(conn, limit=12)
                v_syms = [x["nse_symbol"] for x in v]
                self.assertEqual(set(v_syms), set(cand_syms))


if __name__ == "__main__":
    unittest.main()
