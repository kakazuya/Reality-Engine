"""
Wave A1 — Macro PDF -> Pydantic lens -> dense substrate (macro_events + ripple_effects).

Tests :meth:`DistillationEngine.distill_macro_document` end-to-end against a fresh
temp SQLite DB (no dependency on the 1GB production DB, no live LLM calls). A
deterministic extraction-override fixture stands in for the LLM, and a regex
extractor path is exercised offline.

Acceptance gates (from plan §2 Wave A):
  * For each macro doc, SELECT count(*) FROM macro_events WHERE doc_id=? >= 1
  * ripple_effects has 1st-order rows with probability>0 and lag_time_months not null
  * Event nuance (conditional / exception / effective-date / % reduction) is quantized
    into transmission_channel / affected_nodes_json, not left as raw prose.
"""

from __future__ import annotations

import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing.distillation_engine import DistillationEngine
from reality_engine.agent.schemas import MacroEventExtraction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
# Steel customs-duty-hike case. The second-order ripple encodes a CONDITIONAL
# US-plant nuance that must be quantized into transmission_channel.
STEEL_OVERRIDE = {
    "event_name": "Customs Duty Hike Steel",
    "event_category": "Trade",
    "primary_effects": [
        {
            "target_type": "Sector",
            "target_name": "Steel",
            "transmission_channel": "customs duty increase on steel imports",
            "raw_magnitude": 3.8,      # 3.8% ad-valorem hike
            "probability": 1.0,
            "lag_time_months": 0,
            "second_order_effects": [
                {
                    "order_level": 2,
                    "target_type": "Sector",
                    "target_name": "Automobile",
                    "transmission_channel": "conditional US plant tariff relief passthrough; effective 2026-04-01; exceptions for EV kits",
                    "transmission_elasticity": 0.8,
                    "raw_magnitude": -1.0,
                    "probability": 0.9,
                    "lag_time_months": 3,
                    "downstream_ripples": [
                        {
                            "order_level": 3,
                            "target_type": "Company",
                            "target_name": "TITAGARH",
                            "transmission_channel": "passenger vehicle margin compression",
                            "transmission_elasticity": 0.5,
                            "raw_magnitude": -0.4,
                            "probability": 0.7,
                            "lag_time_months": 2,
                            "downstream_ripples": [],
                        }
                    ],
                }
            ],
        }
    ],
}


def _make_env(tmp_path: Path):
    """Return (DatabaseManager, Repository, DistillationEngine) on a fresh temp DB."""
    db_path = tmp_path / "distill_macro_test.db"
    mgr = DatabaseManager(db_path=db_path)
    # document_chunks is normally created by PDFIngestor; ensure it for the unit test.
    with mgr.session() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_chunks (
                chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT,
                published_date TEXT,
                timestamp_start_sec INTEGER,
                timestamp_end_sec INTEGER,
                sector_id INTEGER,
                industry_id INTEGER,
                symbol TEXT,
                isin TEXT,
                UNIQUE(doc_id, chunk_index)
            )
            """
        )
    repo = Repository(manager=mgr)
    engine = DistillationEngine(manager=mgr)
    return mgr, repo, engine


def _insert_macro_doc(repo: Repository, doc_id_holder: dict, source_type: str,
                      title: str, published: str, chunks: list[str]) -> int:
    """Insert a raw_documents row + document_chunks, return doc_id."""
    doc_id = repo.upsert_raw_document({
        "title": title,
        "source_type": source_type,
        "published_date": published,
        "fiscal_period": "FY2025-26",
        "source_url": f"http://example.com/{title.replace(' ', '_')}.pdf",
        "creator_or_ministry": "Ministry of Finance (GoI)",
        "sha256_hash": None,
        "local_file_path": f"/tmp/{title.replace(' ', '_')}.pdf",
        "file_size_bytes": 1234,
    })
    mgr = repo.db
    with mgr.session() as conn:
        for idx, text in enumerate(chunks):
            conn.execute(
                "INSERT INTO document_chunks (doc_id, chunk_index, content, published_date) "
                "VALUES (?, ?, ?, ?)",
                (doc_id, idx, text, published),
            )
    doc_id_holder["last"] = doc_id
    return doc_id


class TestDistillMacro(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="distill_macro_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    def test_01_distill_creates_macro_event_and_ripples(self):
        mgr, repo, engine = _make_env(self.tmp)
        holder = {}
        doc_id = _insert_macro_doc(
            repo, holder, "Union_Budget", "Union Budget 2025-26",
            "2025-02-01",
            ["Union Budget 2025-26 proposes a 3.8% customs duty hike on steel imports."],
        )

        res = engine.distill_macro_document(doc_id, extraction_override=STEEL_OVERRIDE)

        # Acceptance: macro_events WHERE doc_id >= 1
        with mgr.session() as conn:
            n_events = conn.execute(
                "SELECT COUNT(*) FROM macro_events WHERE doc_id = ?", (doc_id,)
            ).fetchone()[0]
            n_ripples = conn.execute(
                "SELECT COUNT(*) FROM ripple_effects", ()
            ).fetchone()[0]
            # 1st-order rows: probability>0 and lag_time_months NOT NULL
            l1 = conn.execute(
                "SELECT COUNT(*) FROM ripple_effects "
                "WHERE order_level = 1 AND probability > 0 AND lag_time_months IS NOT NULL"
            ).fetchone()[0]
        self.assertEqual(res["status"], "distilled")
        self.assertGreaterEqual(n_events, 1, "macro_events must link the doc via doc_id")
        self.assertGreaterEqual(n_ripples, 1, "ripples must be persisted")
        self.assertGreaterEqual(l1, 1, "at least one 1st-order ripple required")

    # ------------------------------------------------------------------
    def test_02_significance_flat_primary(self):
        """Flat single-level S = |raw*prob*elastic|*20/(1+ln(1+lag)).

        raw=3.8, prob=1.0, elastic=1.0, lag=0 -> 76.0 exactly.
        """
        mgr, repo, engine = _make_env(self.tmp)
        holder = {}
        doc_id = _insert_macro_doc(
            repo, holder, "Union_Budget", "Steel Duty Doc", "2025-02-01",
            ["customs duty hike on steel"],
        )
        engine.distill_macro_document(doc_id, extraction_override=STEEL_OVERRIDE)

        with mgr.session() as conn:
            sig = conn.execute(
                "SELECT significance_rank FROM ripple_effects WHERE order_level = 1"
            ).fetchone()[0]
        self.assertAlmostEqual(sig, 76.0, places=2)

    # ------------------------------------------------------------------
    def test_03_conditional_nuance_quantized(self):
        """Conditional US-plant nuance must appear in transmission_channel (no prose leak)."""
        mgr, repo, engine = _make_env(self.tmp)
        holder = {}
        doc_id = _insert_macro_doc(
            repo, holder, "Union_Budget", "Conditional Relief Doc", "2025-02-01",
            ["conditional us plant tariff relief"],
        )
        engine.distill_macro_document(doc_id, extraction_override=STEEL_OVERRIDE)

        with mgr.session() as conn:
            chans = [r[0] for r in conn.execute(
                "SELECT transmission_channel FROM ripple_effects").fetchall()]
        joined = " | ".join(chans)
        self.assertIn("conditional", joined, "conditional nuance must be quantized into transmission_channel")
        self.assertIn("target=Automobile", joined, "target name must be quantized")
        self.assertIn("effective", joined, "effective-date nuance must be quantized")
        self.assertIn("exception", joined, "exception nuance must be quantized")

    # ------------------------------------------------------------------
    def test_04_idempotent_upsert(self):
        """Re-distilling the same doc must not duplicate the macro_event or ripples."""
        mgr, repo, engine = _make_env(self.tmp)
        holder = {}
        doc_id = _insert_macro_doc(
            repo, holder, "Union_Budget", "Idempotent Doc", "2025-02-01",
            ["steel duty"],
        )
        r1 = engine.distill_macro_document(doc_id, extraction_override=STEEL_OVERRIDE)
        r2 = engine.distill_macro_document(doc_id, extraction_override=STEEL_OVERRIDE)

        with mgr.session() as conn:
            n_events = conn.execute(
                "SELECT COUNT(*) FROM macro_events WHERE doc_id = ?", (doc_id,)
            ).fetchone()[0]
            n_ripples = conn.execute("SELECT COUNT(*) FROM ripple_effects").fetchone()[0]
        self.assertEqual(r1["events_created"], 1)
        self.assertEqual(n_events, 1, "macro_event must not be duplicated")
        self.assertEqual(n_ripples, r1["ripples_created"], "ripple set must be stable on re-distill")
        self.assertEqual(r2["status"], "distilled")

    # ------------------------------------------------------------------
    def test_05_missing_doc_returns_zero(self):
        mgr, repo, engine = _make_env(self.tmp)
        engine.repo.ensure_macro_event_doc_id(mgr)  # ensure doc_id column exists
        res = engine.distill_macro_document(99999)
        self.assertEqual(res["status"], "no_document")
        self.assertEqual(res["events_created"], 0)
        self.assertEqual(res["ripples_created"], 0)
        with mgr.session() as conn:
            n = conn.execute("SELECT COUNT(*) FROM macro_events WHERE doc_id = 99999").fetchone()[0]
        self.assertEqual(n, 0)

    # ------------------------------------------------------------------
    def test_06_batch_distill_all(self):
        mgr, repo, engine = _make_env(self.tmp)
        _insert_macro_doc(repo, {}, "Union_Budget", "Doc A", "2025-02-01", ["steel duty"])
        _insert_macro_doc(repo, {}, "State_Budget_UP", "Doc B", "2025-03-01", ["state capex"])

        summary = engine.distill_all_macro_documents()
        self.assertEqual(summary["distilled"], 2)
        for d in summary["details"]:
            self.assertEqual(d["status"], "distilled")
            self.assertEqual(d["events_created"], 1)

    # ------------------------------------------------------------------
    def test_07_regex_extractor_offline(self):
        """No-LLM path: deterministic regex extraction produces a valid lens + substrate."""
        mgr, repo, engine = _make_env(self.tmp)
        holder = {}
        doc_id = _insert_macro_doc(
            repo, holder, "Union_Budget", "Regex Budget", "2025-02-01",
            ["The budget raises steel import duty by 3.8% and is effective 2025-04-01 "
             "with conditional relief for a US plant."],
        )
        res = engine.distill_macro_document(doc_id)  # no override, no llm -> regex path
        self.assertEqual(res["status"], "distilled")

        with mgr.session() as conn:
            n = conn.execute("SELECT COUNT(*) FROM macro_events WHERE doc_id = ?", (doc_id,)).fetchone()[0]
            an = conn.execute("SELECT affected_nodes_json FROM macro_events WHERE doc_id = ?", (doc_id,)).fetchone()[0]
        self.assertGreaterEqual(n, 1)
        # Structured (not prose) substrate: the lens JSON must contain the parsed magnitude.
        self.assertIn("3.8", an, "parsed % must be quantized into affected_nodes_json")

    # ------------------------------------------------------------------
    def test_08_llm_client_contract(self):
        """A provided llm_client must be callable as extract_macro(context, raw_doc)."""
        mgr, repo, engine = _make_env(self.tmp)
        holder = {}
        doc_id = _insert_macro_doc(repo, holder, "PIB_Circular", "PIB Doc", "2025-05-01", ["pib text"])
        fake_llm = mock.MagicMock()
        fake_llm.extract_macro.return_value = STEEL_OVERRIDE
        res = engine.distill_macro_document(doc_id, llm_client=fake_llm)
        self.assertEqual(res["status"], "distilled")
        fake_llm.extract_macro.assert_called_once()
        # Validate the lens contract was honored (Pydantic-validated by engine).
        self.assertTrue(MacroEventExtraction.model_validate(STEEL_OVERRIDE))


if __name__ == "__main__":
    unittest.main(verbosity=2)
