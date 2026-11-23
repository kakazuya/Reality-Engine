"""The compute layer: one worked example per formula on fixture databases (§A.3).

Every number below is hand arithmetic over the fixture rows, not a re-run of the
same expression.  The extraction tables are prototypes, so the fixture is a small
real SQLite file; it is opened ``mode=ro`` and a separate test proves no write.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import unittest
from pathlib import Path

from reality_engine.query.v4 import formulas
from reality_engine.query.v4.formulas import (
    REFUSAL_CODES,
    FormulaEngine,
    FormulaRefusal,
    FormulaResult,
    Refusal,
    extraction_formulas,
    registry_formulas,
)

BASE = "INE000A01001"
GROWTH = "INE000A01003"
CAGR = "INE000A01004"
LATE = "INE000A01002"
NO_INTEREST = "INE000A01005"
FY26, FY25 = "2026-03-31", "2025-03-31"
AS_OF = "2026-09-30"

SCHEMA = """
CREATE TABLE balance_sheet_lines(
  isin TEXT, period_end TEXT, line_item TEXT, part TEXT, value REAL,
  unit TEXT, source TEXT, known_at TEXT, period_kind TEXT);
CREATE TABLE cash_flow_lines(
  isin TEXT, period_end TEXT, line_item TEXT, part TEXT, value REAL,
  unit TEXT, source TEXT, known_at TEXT, period_kind TEXT);
CREATE TABLE lender_metrics(
  isin TEXT, period_end TEXT, metric TEXT, part TEXT, value REAL,
  unit TEXT, source TEXT, known_at TEXT, period_kind TEXT);
CREATE TABLE tax_reconciliation(
  isin TEXT, period_end TEXT, item TEXT, item_kind TEXT, value REAL,
  unit TEXT, source TEXT, known_at TEXT, period_kind TEXT);
CREATE TABLE unit_volume(
  isin TEXT, period_end TEXT, metric TEXT, part TEXT, value REAL,
  unit TEXT, source TEXT, known_at TEXT, period_kind TEXT);
CREATE TABLE market_lines(
  isin TEXT, as_of TEXT, metric TEXT, value REAL, unit TEXT,
  source TEXT, known_at TEXT);
CREATE TABLE nsdl_fortnight_cells(
  sector TEXT, period_start TEXT, period_end TEXT, value REAL,
  unit TEXT, source TEXT, known_at TEXT);
"""


def _build_fixture(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)

    bs = [
        # isin, period, line_item, part, value, unit, source, known_at
        (BASE, FY26, "receivables", None, 150, "INR crore", "AR FY26 note 12", "2026-05-15"),
        (BASE, FY26, "inventory", None, 100, "INR crore", "AR FY26 note 13", "2026-05-15"),
        (BASE, FY26, "payables", None, 80, "INR crore", "AR FY26 note 14", "2026-05-15"),
        (BASE, FY26, "total_debt", None, 800, "INR crore", "AR FY26 note 20", "2026-05-15"),
        (BASE, FY26, "cash", None, 200, "INR crore", "AR FY26 note 6", "2026-05-15"),
        (BASE, FY26, "book_equity", None, 450, "INR crore", "AR FY26 BS", "2026-05-15"),
        (BASE, FY26, "total_assets", None, 1100, "INR crore", "AR FY26 BS", "2026-05-15"),
        (BASE, FY26, "investments", "Listed stake A", 500, "INR crore", "AR FY26 note 8", "2026-05-15"),
        (BASE, FY26, "investments", "Listed stake B", 300, "INR crore", "AR FY26 note 8", "2026-05-15"),
        (BASE, FY25, "book_equity", None, 400, "INR crore", "AR FY25 BS", "2025-05-15"),
        (BASE, FY25, "total_debt", None, 700, "INR crore", "AR FY25 note 20", "2025-05-15"),
        (BASE, FY25, "cash", None, 150, "INR crore", "AR FY25 note 6", "2025-05-15"),
        (BASE, FY25, "total_assets", None, 900, "INR crore", "AR FY25 BS", "2025-05-15"),
        (BASE, FY25, "investments", "Listed stake A", 480, "INR crore", "AR FY25 note 8", "2025-05-15"),
        (BASE, FY25, "investments", "Listed stake B", 280, "INR crore", "AR FY25 note 8", "2025-05-15"),
        (LATE, FY26, "total_debt", None, 500, "INR crore", "AR FY26 note 20", "2026-10-20"),
        (LATE, FY26, "book_equity", None, 250, "INR crore", "AR FY26 BS", "2026-05-15"),
        (NO_INTEREST, FY26, "total_debt", None, 500, "INR crore", "AR FY26 note 20", "2026-05-15"),
        (NO_INTEREST, FY26, "book_equity", None, 250, "INR crore", "AR FY26 BS", "2026-05-15"),
    ]
    con.executemany(
        "INSERT INTO balance_sheet_lines VALUES (?,?,?,?,?,?,?,?,?)",
        [(*row, "FY") for row in bs])

    cf = [
        (BASE, FY26, "cfo", None, 480, "INR crore", "AR FY26 cash flow", "2026-05-15"),
        (BASE, FY26, "capex", None, 150, "INR crore", "AR FY26 cash flow", "2026-05-15"),
    ]
    con.executemany(
        "INSERT INTO cash_flow_lines VALUES (?,?,?,?,?,?,?,?,?)",
        [(*row, "FY") for row in cf])

    lm = [
        (BASE, FY26, "revenue", None, 1000, "INR crore", "AR FY26 P&L", "2026-05-15"),
        (BASE, FY26, "pat", None, 240, "INR crore", "AR FY26 P&L", "2026-05-15"),
        (BASE, FY26, "ebitda", None, 300, "INR crore", "AR FY26 P&L", "2026-05-15"),
        (BASE, FY26, "interest_expense", None, 50, "INR crore", "AR FY26 note 25", "2026-05-15"),
        (BASE, FY26, "order_book", None, 2400, "INR crore", "AR FY26 MD&A", "2026-05-15"),
        (BASE, FY26, "order_intake", None, 1100, "INR crore", "AR FY26 MD&A", "2026-05-15"),
        (BASE, FY26, "segment_value", "Cables", 250, "INR crore", "AR FY26 segment note", "2026-05-15"),
        (NO_INTEREST, FY26, "ebitda", None, 100, "INR crore", "AR FY26 P&L", "2026-05-15"),
    ]
    con.executemany(
        "INSERT INTO lender_metrics VALUES (?,?,?,?,?,?,?,?,?)",
        [(*row, "FY") for row in lm])

    tax = [
        (BASE, FY26, "profit_before_tax", "profit", 1000, "INR crore", "AR FY26 tax note", "2026-05-15"),
        (BASE, FY26, "tax_expense", "expense", 240, "INR crore", "AR FY26 tax note", "2026-05-15"),
        (BASE, FY26, "statutory_rate", "rate", 25, "%", "AR FY26 tax note", "2026-05-15"),
        (BASE, FY26, "deduction_80ia", "deduction", 40, "INR crore", "AR FY26 tax note", "2026-05-15"),
    ]
    con.executemany(
        "INSERT INTO tax_reconciliation VALUES (?,?,?,?,?,?,?,?,?)",
        [(*row, "FY") for row in tax])

    volumes = [
        (BASE, FY26, "volume", "Cables", 200000, "units", "AR FY26 MD&A", "2026-05-15"),
    ]
    con.executemany(
        "INSERT INTO unit_volume VALUES (?,?,?,?,?,?,?,?,?)",
        [(*row, "FY") for row in volumes])

    market = [
        (BASE, "2026-03-31", "mcap", 600, "INR crore", "NSE bhavcopy", "2026-03-31"),
        (BASE, "2026-09-30", "mcap", 600, "INR crore", "NSE bhavcopy", "2026-09-30"),
        (BASE, "2026-10-15", "mcap", 900, "INR crore", "NSE bhavcopy", "2026-10-15"),
        (BASE, "2026-09-30", "close", 100, "INR", "NSE bhavcopy", "2026-09-30"),
    ]
    con.executemany("INSERT INTO market_lines VALUES (?,?,?,?,?,?,?)", market)

    nsdl = [
        ("IT", "2026-09-01", "2026-09-15", 1200, "INR crore", "NSDL fortnight 15 Sep", "2026-09-16"),
        ("IT", "2026-09-16", "2026-09-30", 800, "INR crore", "NSDL fortnight 30 Sep", "2026-10-01"),
        ("Banks", "2026-08-01", "2026-08-15", 500, "INR crore", "NSDL fortnight 15 Aug", "2026-08-16"),
    ]
    con.executemany("INSERT INTO nsdl_fortnight_cells VALUES (?,?,?,?,?,?,?)", nsdl)

    # A quarterly revenue series for the yoy/qoq pair (no annual row: one value
    # per period, so the lag arithmetic is unambiguous).
    quarters = [
        ("2025-03-31", 80), ("2025-06-30", 90), ("2025-09-30", 100),
        ("2025-12-31", 100), ("2026-03-31", 110), ("2026-06-30", 120),
    ]
    con.executemany(
        "INSERT INTO lender_metrics VALUES (?,?,?,?,?,?,?,?,?)",
        [(GROWTH, period, "revenue", None, value, "INR crore",
          f"results {period}", period, "Q") for period, value in quarters])

    # Four years exactly (1461 days), 100 -> 146.41 = 10% CAGR.
    con.executemany(
        "INSERT INTO lender_metrics VALUES (?,?,?,?,?,?,?,?,?)",
        [(CAGR, "2022-03-31", "revenue", None, 100, "INR crore", "AR FY22",
          "2022-05-15", "FY"),
         (CAGR, "2026-03-31", "revenue", None, 146.41, "INR crore", "AR FY26",
          "2026-05-15", "FY")])

    con.commit()
    con.close()


class FormulaFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # tempfile.mkdtemp() gives SQLite an unopenable directory under the
        # sandbox, so the fixture uses a plain directory under the repo's .tmp/.
        scratch = Path(__file__).resolve().parents[2] / ".tmp"
        cls._tmp = scratch / f"formula_fixture_{os.getpid()}"
        cls._tmp.mkdir(parents=True, exist_ok=True)
        cls.path = cls._tmp / "extraction.db"
        if cls.path.exists():
            cls.path.unlink()
        _build_fixture(cls.path)
        cls.uri = f"file:{cls.path.as_posix()}?mode=ro"
        cls.con = sqlite3.connect(cls.uri, uri=True)
        cls.engine = FormulaEngine(cls.con)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def value(self, formula_id: str, isin: str = BASE, as_of: str = AS_OF, **dims):
        result = self.engine.compute(formula_id, isin, as_of, dims)
        self.assertIsInstance(result, FormulaResult,
                              getattr(result, "to_dict", lambda: result)())
        return result

    # -- the registry is the existing one ---------------------------------
    def test_formula_registry_is_the_one_registry(self):
        registry = formulas.load_registry()
        rows = registry_formulas(registry)
        self.assertEqual(len(rows), len(set(rows)))
        extraction = extraction_formulas(registry)
        self.assertEqual(len(extraction), 21)
        self.assertTrue(set(extraction) <= set(formulas._COMPUTE))
        for fid, row in extraction.items():
            self.assertEqual(row.get("executor"), "extraction", fid)
            self.assertTrue(row.get("inputs"), fid)
            self.assertTrue(row.get("period_rule"), fid)
            self.assertTrue(row.get("unit"), fid)
            self.assertIn(row.get("refusal"), REFUSAL_CODES, fid)
            for binding in row["inputs"]:
                self.assertIn(binding["table"], formulas.EXTRACTION_TABLES)
                self.assertIn(binding["atom"], row["over"] or [binding["atom"]], fid)
        self.assertEqual(set(formulas._COMPUTE), set(extraction))

    def test_formula_no_answer_uses_a_later_known_at(self):
        dims = {"ratio_kind": "pb", "segment": "Cables", "sector": "IT",
                "month": "2026-09", "atom": "fin.revenue", "lag": "yoy"}
        computed = 0
        for fid in formulas._COMPUTE:
            result = self.engine.compute(fid, BASE, AS_OF, dict(dims))
            if isinstance(result, FormulaResult):
                computed += 1
                for reading in result.inputs:
                    self.assertLessEqual(reading.known_at, AS_OF,
                                         f"{fid} used {reading.atom} known {reading.known_at}")
        self.assertGreaterEqual(computed, 18)

    def test_formula_every_answer_carries_source_and_known_at(self):
        result = self.value("f.net_debt")
        self.assertGreaterEqual(len(result.inputs), 2)
        for reading in result.inputs:
            self.assertTrue(reading.source)
            self.assertLessEqual(reading.known_at, AS_OF)
        self.assertTrue(result.source_ref.startswith("derived:f.net_debt"))
        self.assertEqual(result.details["known_at"], max(r.known_at for r in result.inputs))

    # -- one worked example per formula -----------------------------------
    def test_formula_effective_tax_rate(self):
        result = self.value("f.effective_tax_rate")
        self.assertAlmostEqual(result.value, 24.0)          # 240 / 1000
        self.assertEqual(result.unit, "%")
        self.assertEqual(result.period_end, FY26)

    def test_formula_tax_gap_and_named_attribution(self):
        result = self.value("f.tax_gap")
        self.assertAlmostEqual(result.value, 10.0)          # 25% * 1000 - 240
        self.assertEqual(result.unit, "INR crore")
        self.assertAlmostEqual(result.details["tax_at_statutory"], 250.0)
        self.assertAlmostEqual(result.details["attributed"], 10.0)   # 40 * 25%
        self.assertAlmostEqual(result.details["unattributed"], 0.0)
        self.assertEqual(len(result.details["attributions"]), 1)
        line = result.details["attributions"][0]
        self.assertEqual(line["item"], "deduction_80ia")
        self.assertEqual(line["kind"], "deduction")
        self.assertAlmostEqual(line["tax_effect"], 10.0)
        self.assertTrue(line["source"])

    def test_formula_cfo_to_profit(self):
        result = self.value("f.cfo_to_profit")
        self.assertAlmostEqual(result.value, 2.0)           # 480 / 240
        self.assertEqual(result.unit, "x")

    def test_formula_working_capital_days_and_cycle(self):
        self.assertAlmostEqual(self.value("f.dso").value, 54.75)    # 150/1000*365
        self.assertAlmostEqual(self.value("f.dio").value, 36.5)     # 100/1000*365
        self.assertAlmostEqual(self.value("f.dpo").value, 29.2)     # 80/1000*365
        cycle = self.value("f.working_capital_cycle")
        self.assertAlmostEqual(cycle.value, 62.05)                  # 54.75+36.5-29.2
        self.assertEqual(cycle.unit, "days")

    def test_formula_net_debt_and_leverage(self):
        net = self.value("f.net_debt")
        self.assertAlmostEqual(net.value, 600.0)            # 800 - 200
        self.assertEqual(net.unit, "INR crore")
        leverage = self.value("f.net_debt_to_ebitda")
        self.assertAlmostEqual(leverage.value, 2.0)         # 600 / 300
        self.assertEqual(leverage.unit, "x")

    def test_formula_interest_cover(self):
        result = self.value("f.ratio", ratio_kind="icr")
        self.assertAlmostEqual(result.value, 6.0)           # 300 / 50
        self.assertEqual(result.unit, "x")
        self.assertEqual(result.period_rule, "same_period")

    def test_formula_capex_to_sales(self):
        result = self.value("f.capex_to_sales")
        self.assertAlmostEqual(result.value, 15.0)          # 150 / 1000
        self.assertEqual(result.unit, "%")

    def test_formula_asset_turnover(self):
        result = self.value("f.asset_turnover")
        self.assertAlmostEqual(result.value, 1.0)           # 1000 / avg(1100, 900)
        self.assertEqual(result.period_rule, "average_balance")
        self.assertEqual(result.details["opening_period"], FY25)

    def test_formula_roe_and_roce(self):
        roe = self.value("f.ratio", ratio_kind="roe")
        self.assertAlmostEqual(roe.value, 240 / 425 * 100)  # avg(450, 400)
        self.assertEqual(roe.unit, "%")
        roce = self.value("f.ratio", ratio_kind="roce")
        # avg capital employed = ((450+800-200) + (400+700-150)) / 2 = 1000
        self.assertAlmostEqual(roce.value, 30.0)
        self.assertEqual(roce.unit, "%")

    def test_formula_pb_and_pe_at_date(self):
        pb = self.value("f.ratio", ratio_kind="pb")
        self.assertAlmostEqual(pb.value, 600 / 450)         # 2026-09-30 mcap, not 900
        self.assertEqual(pb.details["valuation_date"], "2026-09-30")
        pe = self.value("f.ratio", ratio_kind="pe")
        self.assertAlmostEqual(pe.value, 600 / 240)
        self.assertEqual(pe.period_rule, "market_at_date")

    def test_formula_ratio_de_uses_one_period(self):
        result = self.value("f.ratio", ratio_kind="de")
        self.assertAlmostEqual(result.value, 800 / 450)

    def test_formula_order_book_to_revenue_and_book_to_bill(self):
        cover = self.value("f.order_book_to_revenue")
        self.assertAlmostEqual(cover.value, 2.4)            # 2400 / 1000
        self.assertEqual(cover.unit, "x")
        btb = self.value("f.book_to_bill")
        self.assertAlmostEqual(btb.value, 1.1)              # 1100 / 1000

    def test_formula_sotp_gap(self):
        result = self.value("f.sotp_gap")
        self.assertAlmostEqual(result.value, 200.0)         # (500+300) - 600
        self.assertAlmostEqual(result.details["parts_value"], 800.0)
        self.assertAlmostEqual(result.details["gap_pct"], 200 / 600 * 100)
        self.assertEqual(len(result.details["parts"]), 2)

    def test_formula_revenue_per_unit(self):
        result = self.value("f.revenue_per_unit")
        # 1,000 crore = 1e10 INR; / 200,000 units = 50,000 INR/unit
        self.assertAlmostEqual(result.value, 50000.0)
        self.assertEqual(result.unit, "INR/unit")

    def test_formula_share_of_one_segment(self):
        result = self.value("f.share_of", segment="Cables")
        self.assertAlmostEqual(result.value, 25.0)          # 250 / 1000
        self.assertEqual(result.unit, "%")
        self.assertEqual(result.details["segment"], "Cables")
        refused = self.engine.compute("f.share_of", BASE, AS_OF, {})
        self.assertIsInstance(refused, Refusal)
        self.assertEqual(refused.code, "missing_dim")

    def test_formula_yoy_and_qoq_change(self):
        yoy = self.value("f.change", GROWTH, AS_OF, atom="fin.revenue", lag="yoy")
        self.assertAlmostEqual(yoy.value, 120 / 90 * 100 - 100)   # 33.333%
        self.assertEqual(yoy.details["prior_period"], "2025-06-30")
        qoq = self.value("f.change", GROWTH, AS_OF, atom="fin.revenue", lag="qoq")
        self.assertAlmostEqual(qoq.value, 120 / 110 * 100 - 100)  # 9.0909%
        self.assertEqual(qoq.details["prior_period"], "2026-03-31")

    def test_formula_cagr(self):
        result = self.value("f.cagr", CAGR, AS_OF, atom="fin.revenue")
        self.assertAlmostEqual(result.details["years"], 4.0)
        self.assertAlmostEqual(result.value, 10.0)          # 100 -> 146.41 in 4y
        self.assertEqual(result.unit, "%")

    # -- NSDL fortnight cells ---------------------------------------------
    def test_formula_fii_fortnight_net_flow(self):
        result = self.value("f.nsdl_fortnight_net_flow", BASE, "2026-10-02", sector="IT")
        self.assertAlmostEqual(result.value, 800.0)          # the 30 Sep cell only
        self.assertEqual(result.period_end, "2026-09-30")
        self.assertEqual(len(result.details["cells"]), 1)

    def test_formula_fii_month_net_flow(self):
        result = self.value("f.nsdl_month_net_flow", BASE, "2026-10-02",
                            sector="IT", month="2026-09")
        self.assertAlmostEqual(result.value, 2000.0)         # 1,200 + 800
        self.assertEqual(result.period_end, "2026-09-30")
        self.assertEqual(len(result.details["cells"]), 2)

    def test_formula_fii_month_refuses_an_incomplete_month(self):
        result = self.engine.compute("f.nsdl_month_net_flow", BASE, "2026-10-02",
                                     {"sector": "Banks", "month": "2026-08"})
        self.assertIsInstance(result, Refusal)
        self.assertEqual(result.code, "incomplete_month")
        self.assertEqual(result.atoms, ("macro.fii_sector_net",))

    # -- the two required refusals ----------------------------------------
    def test_formula_refuses_input_known_after_as_of(self):
        result = self.engine.compute("f.ratio", LATE, AS_OF, {"ratio_kind": "de"})
        self.assertIsInstance(result, Refusal)
        self.assertEqual(result.code, "input_after_as_of")
        self.assertEqual(result.atoms, ("fin.total_debt",))
        self.assertIn("2026-10-20", result.message)
        self.assertIn(result.code, REFUSAL_CODES)

    def test_formula_refuses_a_missing_input(self):
        result = self.engine.compute("f.ratio", NO_INTEREST, AS_OF, {"ratio_kind": "icr"})
        self.assertIsInstance(result, Refusal)
        self.assertEqual(result.code, "input_missing")
        self.assertIn("fin.interest_expense", result.atoms)
        self.assertIn("fin.interest_expense", result.message)

    def test_formula_refusals_are_typed_and_raised(self):
        with self.assertRaises(FormulaRefusal):
            self.engine.evaluate("f.dso", "INE_DOES_NOT_EXIST", AS_OF)
        with self.assertRaises(FormulaRefusal):
            self.engine.evaluate("f.not_a_formula", BASE, AS_OF)
        for code in ("input_missing", "input_after_as_of", "incomplete_month",
                     "missing_dim", "unknown_formula"):
            self.assertIn(code, REFUSAL_CODES)

    # -- no writes --------------------------------------------------------
    def test_formula_never_writes_to_the_store(self):
        before = sqlite3.connect(str(self.path))
        counts = {table: before.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in formulas.EXTRACTION_TABLES}
        before.close()
        for fid in formulas._COMPUTE:
            self.engine.compute(fid, BASE, AS_OF,
                                {"ratio_kind": "pb", "segment": "Cables",
                                 "sector": "IT", "month": "2026-09",
                                 "atom": "fin.revenue", "lag": "yoy"})
        after = sqlite3.connect(str(self.path))
        for table, count in counts.items():
            self.assertEqual(after.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                             count, f"{table} changed")
        after.close()


if __name__ == "__main__":
    unittest.main()
