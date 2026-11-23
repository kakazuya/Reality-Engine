"""Tests for reality_engine.search.intel_search (news-feed v1, slice D)."""
import contextlib
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.search.intel_search import search_intel, tier_of

TOKEN = "monsoonxyz"


def _make_repo(tmpdir):
    mgr = DatabaseManager(db_path=Path(tmpdir) / "test.db")
    return mgr, Repository(manager=mgr)


def _seed(repo):
    repo.insert_fts_chunks([
        {"chunk_id": "announcement:1:0", "symbol": "RELIANCE", "isin": "",
         "source_type": "announcement", "document_date": "2026-01-10",
         "document_text": f"Reliance board approves capex {TOKEN} guidance"},
        {"chunk_id": "rbi:2:0", "symbol": "", "isin": "",
         "source_type": "RBI_Press_Release", "document_date": "2026-02-15",
         "document_text": f"RBI holds repo rate steady {TOKEN} inflation"},
        {"chunk_id": "telegram:3:0", "symbol": "TCS", "isin": "",
         "source_type": "telegram", "document_date": "2026-03-20",
         "document_text": f"Unverified rumor of TCS buyback {TOKEN} chatter"},
        {"chunk_id": "concall:4:0", "symbol": "TCS", "isin": "",
         "source_type": "Concall_Transcript_Q3", "document_date": "2024-05-01",
         "document_text": f"TCS management discusses margins {TOKEN} outlook"},
        {"chunk_id": "mystery:5:0", "symbol": "INFY", "isin": "",
         "source_type": "mystery_wire", "document_date": "2026-04-01",
         "document_text": f"Infosys deal win commentary {TOKEN} pipeline"},
    ])


@contextlib.contextmanager
def _temp_repo_ctx():
    """Temp-DB Repository wired in as intel_search's default Repository.

    search_intel's signature is fixed (no db param), so tests patch the
    Repository symbol it resolves at call time. Zero network, temp DB only.
    """
    with tempfile.TemporaryDirectory() as td:
        _mgr, repo = _make_repo(td)
        _seed(repo)
        with mock.patch("reality_engine.db.repository.Repository",
                        return_value=repo):
            yield repo


class TestTierOf(unittest.TestCase):
    def test_tier0_prefixes(self):
        for s in ("announcement", "ANNOUNCEMENT", "Concall_Transcript_Q3",
                  "transcript", "presentation", "financial_result",
                  "annual_report", "earnings_call"):
            self.assertEqual(tier_of(s), 0, s)

    def test_tier1_prefixes(self):
        for s in ("union_budget", "state_budget", "economic_survey",
                  "pib", "PIB_Press_Release", "rbi", "RBI_Press_Release", "mpc"):
            self.assertEqual(tier_of(s), 1, s)

    def test_tier2_prefixes(self):
        for s in ("telegram", "Telegram_Channel", "youtube", "YouTube_Video"):
            self.assertEqual(tier_of(s), 2, s)

    def test_unknown_and_empty_map_to_tier1(self):
        self.assertEqual(tier_of("mystery_wire"), 1)
        self.assertEqual(tier_of(""), 1)
        self.assertEqual(tier_of(None), 1)


class TestSearchIntel(unittest.TestCase):
    def test_signature(self):
        sig = inspect.signature(search_intel)
        params = list(sig.parameters.values())
        self.assertEqual([p.name for p in params],
                         ["query", "symbol", "since", "tiers", "top_k"])
        self.assertEqual(sig.parameters["symbol"].default, None)
        self.assertEqual(sig.parameters["since"].default, None)
        self.assertEqual(tuple(sig.parameters["tiers"].default), (0, 1, 2))
        self.assertEqual(sig.parameters["top_k"].default, 10)

    def test_tier_filtering(self):
        with _temp_repo_ctx():
            only0 = search_intel(TOKEN, tiers=(0,))
            self.assertTrue(only0)
            self.assertTrue(all(r["tier"] == 0 for r in only0))
            self.assertEqual({r["chunk_id"] for r in only0},
                             {"announcement:1:0", "concall:4:0"})
            only2 = search_intel(TOKEN, tiers=(2,))
            self.assertEqual([r["chunk_id"] for r in only2], ["telegram:3:0"])

    def test_symbol_filtering(self):
        with _temp_repo_ctx():
            hits = search_intel(TOKEN, symbol="TCS")
            self.assertTrue(hits)
            self.assertTrue(all(r["symbol"] == "TCS" for r in hits))
            self.assertEqual({r["chunk_id"] for r in hits},
                             {"telegram:3:0", "concall:4:0"})

    def test_since_filtering(self):
        with _temp_repo_ctx():
            hits = search_intel(TOKEN, since="2026-01-01")
            dates = {r["chunk_id"]: r["document_date"] for r in hits}
            self.assertTrue(hits)
            self.assertTrue(all(d >= "2026-01-01" for d in dates.values()))
            self.assertNotIn("concall:4:0", dates)

    def test_unknown_source_is_tier1(self):
        with _temp_repo_ctx():
            in_t1 = search_intel(TOKEN, tiers=(1,))
            self.assertIn("mystery:5:0", {r["chunk_id"] for r in in_t1})
            self.assertTrue(all(r["tier"] == 1 for r in in_t1))
            not_t1 = search_intel(TOKEN, tiers=(0, 2))
            self.assertNotIn("mystery:5:0", {r["chunk_id"] for r in not_t1})

    def test_empty_and_nomatch_query(self):
        with _temp_repo_ctx():
            self.assertEqual(search_intel(""), [])
            self.assertEqual(search_intel("   "), [])
            self.assertEqual(search_intel("qqqzzzznomatch"), [])

    def test_result_shape_and_score_order(self):
        with _temp_repo_ctx():
            hits = search_intel(TOKEN, top_k=10)
            self.assertEqual(len(hits), 5)
            for h in hits:
                self.assertEqual(
                    set(h), {"chunk_id", "symbol", "source_type", "tier",
                             "document_date", "text", "score"})
                self.assertIn(h["tier"], (0, 1, 2))
            scores = [h["score"] for h in hits]
            self.assertTrue(all(0.0 < s <= 1.0 for s in scores))
            self.assertEqual(scores, sorted(scores, reverse=True))
            limited = search_intel(TOKEN, top_k=2)
            self.assertEqual(len(limited), 2)
            self.assertEqual(limited, hits[:2])


if __name__ == "__main__":
    unittest.main()
