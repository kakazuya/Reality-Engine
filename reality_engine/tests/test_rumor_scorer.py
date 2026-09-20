"""Rumor corroboration scorer tests: temp-DB fixtures, zero network."""
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing.rumor_scorer import corroborate, score_rumor


def _mk_repo(td):
    mgr = DatabaseManager(db_path=Path(td) / "t.db")
    return Repository(manager=mgr), mgr


_SYM = "RELIANCE"
_ISIN = "INE002A01018"

_T1 = "2026-09-08"
_T2 = "2026-09-09"
_T3 = "2026-09-10"


def _seed_master(repo, sym=_SYM, isin=_ISIN):
    repo.upsert_master_companies([{
        "isin": isin, "nse_symbol": sym,
        "company_name": f"{sym} Test Co", "is_active": 1}])


def _seed_confirmed(repo):
    # Two tg posts, same symbol, sharing 2+ claim keywords + Tier-0 hit.
    _seed_master(repo)
    repo.insert_fts_chunks([
        {"chunk_id": "tg:101", "symbol": _SYM, "isin": _ISIN,
         "source_type": "TELEGRAM_POST", "document_date": _T1,
         "document_text": "Reliance confidential refinery expansion approval expected soon"},
        {"chunk_id": "tg:102", "symbol": _SYM, "isin": _ISIN,
         "source_type": "TELEGRAM_POST", "document_date": _T2,
         "document_text": "Reliance confidential refinery expansion deal buzz on street"},
    ])
    repo.upsert_corporate_documents([{
        "isin": _ISIN, "symbol": _SYM, "doc_type": "ANNOUNCEMENT",
        "title": "Refinery expansion approved",
        "doc_date": _T2, "source_url": "https://nse.example/ann/rumor-1",
        "source": "nse_official"}])


def _seed_lone(repo):
    repo.insert_fts_chunks([
        {"chunk_id": "tg:201", "symbol": "TCS", "isin": "",
         "source_type": "TELEGRAM_POST", "document_date": _T3,
         "document_text": "Whisper of quantum photonic moonshot venture fundraising round"},
    ])


def _seed_multisource(repo):
    # Same claim keywords, distinct source_types (TELEGRAM_POST / YOUTUBE_TRANSCRIPT)
    # -> CONFIRMED via n_sources >= min_confirm, no Tier-0 row.
    repo.insert_fts_chunks([
        {"chunk_id": "tg:301", "symbol": "INFY", "isin": "",
         "source_type": "TELEGRAM_POST", "document_date": _T1,
         "document_text": "Infosys confidential cobalt acquisition talks advance rapidly"},
        {"chunk_id": "tg:302", "symbol": "INFY", "isin": "",
         "source_type": "YOUTUBE_TRANSCRIPT", "document_date": _T2,
         "document_text": "Infosys confidential cobalt acquisition chatter gains momentum"},
    ])


class TestCorroborate(unittest.TestCase):
    def test_confirmed_via_tier0(self):
        with tempfile.TemporaryDirectory() as td:
            repo, mgr = _mk_repo(td)
            _seed_confirmed(repo)
            out = corroborate(symbol=_SYM, db=mgr)
            self.assertEqual(len(out), 1)
            c = out[0]
            self.assertEqual(c["symbol"], _SYM)
            self.assertTrue(c["claim"])
            self.assertEqual(c["first_seen"], _T1)
            self.assertTrue(c["tier0_hit"])
            self.assertEqual(c["status"], "CONFIRMED")

    def test_lone_post_unconfirmed(self):
        with tempfile.TemporaryDirectory() as td:
            repo, mgr = _mk_repo(td)
            _seed_lone(repo)
            out = corroborate(symbol="TCS", db=mgr)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["status"], "UNCONFIRMED")
            self.assertFalse(out[0]["tier0_hit"])
            self.assertEqual(out[0]["n_sources"], 1)

    def test_multisource_confirmed_via_n_sources(self):
        with tempfile.TemporaryDirectory() as td:
            repo, mgr = _mk_repo(td)
            _seed_multisource(repo)
            out = corroborate(symbol="INFY", db=mgr)
            self.assertEqual(len(out), 1)
            c = out[0]
            self.assertFalse(c["tier0_hit"])
            self.assertEqual(c["n_sources"], 2)
            self.assertEqual(c["sources"], ["TELEGRAM_POST", "YOUTUBE_TRANSCRIPT"])
            self.assertEqual(c["status"], "CONFIRMED")

    def test_empty_db_no_crash(self):
        with tempfile.TemporaryDirectory() as td:
            _, mgr = _mk_repo(td)
            self.assertEqual(corroborate(db=mgr), [])
            scored = score_rumor("NOBODY", _T3, db=mgr)
            self.assertEqual(scored["rumors"], [])
            self.assertEqual(scored["n_confirmed"], 0)
            self.assertEqual(scored["n_unconfirmed"], 0)


class TestScoreRumor(unittest.TestCase):
    def test_score_rumor_confirmed(self):
        with tempfile.TemporaryDirectory() as td:
            repo, mgr = _mk_repo(td)
            _seed_confirmed(repo)
            out = score_rumor(_SYM, _T3, db=mgr)
            self.assertEqual(out["symbol"], _SYM)
            self.assertEqual(out["target_date"], _T3)
            self.assertEqual(len(out["rumors"]), 1)
            self.assertEqual(out["n_confirmed"], 1)
            self.assertEqual(out["n_unconfirmed"], 0)

    def test_score_rumor_empty(self):
        with tempfile.TemporaryDirectory() as td:
            _, mgr = _mk_repo(td)
            out = score_rumor("NOBODY", _T3, db=mgr)
            self.assertEqual(out["rumors"], [])
            self.assertEqual(out["n_confirmed"], 0)
            self.assertEqual(out["n_unconfirmed"], 0)


if __name__ == "__main__":
    unittest.main()
