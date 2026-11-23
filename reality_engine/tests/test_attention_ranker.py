"""Tests for reality_engine.processing.attention_ranker (Tier-3 slice)."""
import sys
import tempfile
import types
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing.attention_ranker import (
    morning_digest,
    rank_attention,
)

_SPIKY = "SPIKY"
_FLAT = "FLAT"
_DATE = "2026-09-10"
_ISIN_S = "INE000000001"
_ISIN_F = "INE000000002"


def _mk_repo(td):
    mgr = DatabaseManager(db_path=Path(td) / "t.db")
    return Repository(manager=mgr), mgr


def _price(symbol, isin, chg, dsr):
    return {
        "date": _DATE, "symbol": symbol, "isin": isin, "series": "EQ",
        "open": 100.0, "high": 110.0, "low": 99.0, "close": 100.0 + chg,
        "prev_close": 100.0, "change_pct": chg, "total_volume": 1000,
        "deliverable_volume": 500, "delivery_pct": 50.0,
        "delivery_spike_ratio": dsr,
    }


def _seed(repo):
    repo.upsert_master_companies([
        {"isin": _ISIN_S, "nse_symbol": _SPIKY,
         "company_name": "Spiky Ltd", "is_active": 1},
        {"isin": _ISIN_F, "nse_symbol": _FLAT,
         "company_name": "Flat Ltd", "is_active": 1},
    ])
    repo.upsert_daily_price_delivery([
        _price(_SPIKY, _ISIN_S, 20.0, 5.0),
        _price(_FLAT, _ISIN_F, 0.5, 1.0),
    ])
    repo.upsert_corporate_documents([
        {"isin": _ISIN_S, "symbol": _SPIKY, "doc_type": "ANNOUNCEMENT",
         "title": f"Spiky update {i}", "doc_date": _DATE,
         "source_url": f"https://nse.example/spiky/{i}",
         "sha256_hash": f"spiky-{i}", "is_processed": 0}
        for i in range(3)
    ])
    repo.insert_fts_chunks([
        {"chunk_id": f"tg:post{i}", "symbol": _SPIKY, "isin": _ISIN_S,
         "source_type": "TELEGRAM_POST", "document_date": _DATE,
         "document_text": f"spiky rumor buzz {i} alpha"}
        for i in range(3)
    ])
    repo.upsert_bulk_block_deals([
        {"id": f"deal-spiky-{i}".ljust(32, "x")[:32], "deal_date": _DATE,
         "symbol": _SPIKY, "client_name": f"FUND {i}",
         "deal_type": "BLOCK", "buy_sell": "BUY", "quantity": 1000,
         "trade_price": 120.0, "is_marquee_institution": 1}
        for i in range(2)
    ])
    repo.upsert_raw_document({
        "title": "PIB Release on Markets", "source_type": "PIB_Press_Release",
        "published_date": "2026-09-08", "fiscal_period": None,
        "source_url": "https://pib.example/1",
        "creator_or_ministry": "Press Information Bureau (GoI)",
        "sha256_hash": "pib-1", "local_file_path": None,
        "file_size_bytes": 0,
    })


def _stub_corroborate():
    """Fake rumor_scorer: CONFIRMED for SPIKY only. Returns restore fn."""
    key = "reality_engine.processing.rumor_scorer"
    prev = sys.modules.get(key)
    fake = types.ModuleType(key)

    def corroborate(*args, **kwargs):
        sym = ""
        if args:
            sym = str(args[0] or "").upper()
        elif "symbol" in kwargs:
            sym = str(kwargs["symbol"] or "").upper()
        if sym == _SPIKY:
            return {"verdict": "CONFIRMED", "symbol": sym}
        return {"verdict": "NONE", "symbol": sym}

    fake.corroborate = corroborate
    sys.modules[key] = fake

    def _restore():
        if prev is not None:
            sys.modules[key] = prev
        else:
            sys.modules.pop(key, None)

    return _restore


class TestRankAttention(unittest.TestCase):
    def test_spiky_first_exact_math(self):
        with tempfile.TemporaryDirectory() as td:
            repo, mgr = _mk_repo(td)
            _seed(repo)
            restore = _stub_corroborate()
            try:
                rows = rank_attention(_DATE, top_n=10, db=mgr)
            finally:
                restore()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["symbol"], _SPIKY)
            self.assertEqual(rows[1]["symbol"], _FLAT)
            c = rows[0]["components"]
            self.assertAlmostEqual(c["price_move"], 2.0)
            self.assertAlmostEqual(c["delivery"], 2.0)
            self.assertEqual(c["news_t0"], 3)
            self.assertAlmostEqual(c["rumor_t2"], 2.0)  # 3*0.5 + 0.5 bonus
            self.assertEqual(c["deals"], 2)
            self.assertAlmostEqual(rows[0]["score"], 11.0)
            f = rows[1]["components"]
            self.assertAlmostEqual(f["price_move"], 0.05)
            self.assertAlmostEqual(f["delivery"], 0.4)
            self.assertEqual(f["news_t0"], 0)
            self.assertAlmostEqual(f["rumor_t2"], 0.0)
            self.assertEqual(f["deals"], 0)
            self.assertAlmostEqual(rows[1]["score"], 0.45)

    def test_no_rumor_module_still_ranks(self):
        with tempfile.TemporaryDirectory() as td:
            repo, mgr = _mk_repo(td)
            _seed(repo)
            key = "reality_engine.processing.rumor_scorer"
            prev = sys.modules.get(key)
            # Simulate absence WITHOUT resurrecting the real module on
            # import: sys.modules[key] = None is the supported convention.
            sys.modules[key] = None
            try:
                rows = rank_attention(_DATE, db=mgr)
            finally:
                if prev is not None:
                    sys.modules[key] = prev
                else:
                    sys.modules.pop(key, None)
            # No corroborate -> rumor_t2 = 1.5, score 10.5, still first.
            self.assertEqual(rows[0]["symbol"], _SPIKY)
            self.assertAlmostEqual(rows[0]["components"]["rumor_t2"], 1.5)
            self.assertAlmostEqual(rows[0]["score"], 10.5)

    def test_empty_db(self):
        with tempfile.TemporaryDirectory() as td:
            _, mgr = _mk_repo(td)
            self.assertEqual(rank_attention(_DATE, db=mgr), [])
            self.assertEqual(rank_attention("bad-date", db=mgr), [])


class TestMorningDigest(unittest.TestCase):
    def test_digest_symbols_and_policy(self):
        with tempfile.TemporaryDirectory() as td:
            repo, mgr = _mk_repo(td)
            _seed(repo)
            restore = _stub_corroborate()
            try:
                text = morning_digest(_DATE, db=mgr)
            finally:
                restore()
            self.assertIn(_DATE, text)
            self.assertIn(_SPIKY, text)
            self.assertIn(_FLAT, text)
            self.assertIn("Policy watch", text)
            self.assertIn("PIB Release on Markets", text)

    def test_empty_db_header_only(self):
        with tempfile.TemporaryDirectory() as td:
            _, mgr = _mk_repo(td)
            text = morning_digest(_DATE, db=mgr)
            self.assertIn(_DATE, text)
            self.assertIn("No price data", text)
            self.assertIn("No new policy releases", text)


if __name__ == "__main__":
    unittest.main()
