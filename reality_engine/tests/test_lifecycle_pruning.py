"""
Wave C — Lifecycle Pruning & Structural-Milestone Survival tests.

Deterministic unit tests against a fresh temp-file SQLite DB (NOT the live 1GB
production DB). Verifies the Wave C changes to ``pruning_engine.py`` and
``distillation_pruner.py``:

  1. HALF_LIVES constants (State Budget 12m, PIB Circular 3m, RBI Report 6m,
     Economic Survey 12m, Union Budget 12m).
  2. macro_source_type_to_category() prefix handling (State_Budget_UP /
     State_Budget_Maharashtra / PIB_Circular / RBI_* / Economic_Survey / Union_Budget).
  3. is_structural_milestone = 1 (and the legacy 'Structural Milestone' source_type
     marker) is NEVER pruned: dry-run must not count it, and a real prune must keep
     its embedding while a same-age non-structural row is purged.
  4. Exponential decay S(t) = S0 * e^{-lambda*t}: non-structural decays, structural
     (T½ = INF, lambda 0) stays at S0 — via decayed_significance() and
     get_decayed_significance_rows() (v_ripple_decayed emulation).
  5. Distill-before-delete: synthesize_and_update() over 24 mock chunks updates
     moat_evaluations, purges 24 vectors, and logs distillation_runs.
  6. Structural milestones are excluded from distillation candidates.
"""

from __future__ import annotations

import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reality_engine.db.database import DatabaseManager
from reality_engine.processing.pruning_engine import (
    HALF_LIVES,
    macro_source_type_to_category,
    is_structural_milestone,
    effective_lambda,
    decayed_significance,
    prune_decayed_signals,
    get_decayed_significance_rows,
    ensure_pruning_schema,
)
from reality_engine.processing.distillation_pruner import (
    synthesize_and_update,
    run_monthly_batch_with_prune_check,
    fetch_distillation_candidates,
)


OLD_DATE = "2024-01-01"  # > 12 months before the (2026) test run


def _make_env(tmp: Path):
    """Build a fresh temp DB, ensure pruning schema, and create document_chunks."""
    db_path = tmp / "lifecycle_pruning_test.db"
    mgr = DatabaseManager(db_path=db_path)
    ensure_pruning_schema(mgr)
    with mgr.session() as conn:
        # document_chunks is normally created by the PDF ingestor; create for the test.
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
    return mgr


def _insert_raw_doc(conn, title, source_type, published, structural=False):
    """Insert a raw_documents row (optionally a structural milestone) and return doc_id."""
    if structural:
        conn.execute(
            "INSERT INTO raw_documents (title, source_type, published_date, is_structural_milestone) "
            "VALUES (?, ?, ?, 1)",
            (title, source_type, published),
        )
    else:
        conn.execute(
            "INSERT INTO raw_documents (title, source_type, published_date) VALUES (?, ?, ?)",
            (title, source_type, published),
        )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _insert_chunk(conn, doc_id, idx, embedding, published=OLD_DATE):
    conn.execute(
        "INSERT INTO document_chunks (doc_id, chunk_index, content, embedding, published_date) "
        "VALUES (?, ?, ?, ?, ?)",
        (doc_id, idx, f"chunk {idx} of {doc_id}", embedding, published),
    )


def _fake_embedding():
    return json.dumps([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])


class TestLifecyclePruning(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lifecycle_pruning_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ #
    def test_01_half_lives_constants(self):
        """HALF_LIVES must carry the canonical Wave C categories & half-lives."""
        self.assertEqual(HALF_LIVES["State Budget"], 12.0)
        self.assertEqual(HALF_LIVES["PIB Circular"], 3.0)
        self.assertEqual(HALF_LIVES["RBI Report / Economic Survey"], 6.0)
        self.assertEqual(HALF_LIVES["Economic Survey"], 12.0)
        self.assertEqual(HALF_LIVES["Union Budget / Tax Reform"], 12.0)
        # Lambda sanity: ln(2)/12 for a 12-month half-life.
        self.assertAlmostEqual(HALF_LIVES["Union Budget / Tax Reform"] and
                               (math.log(2) / HALF_LIVES["Union Budget / Tax Reform"]),
                               math.log(2) / 12.0, places=6)

    # ------------------------------------------------------------------ #
    def test_02_macro_source_type_to_category_prefix(self):
        """Free-form source_type variants must map via prefix to canonical categories."""
        self.assertEqual(macro_source_type_to_category("State_Budget_UP"), "State Budget")
        self.assertEqual(macro_source_type_to_category("State_Budget_Maharashtra"), "State Budget")
        self.assertEqual(macro_source_type_to_category("State_Budget_Tamil_Nadu"), "State Budget")
        self.assertEqual(macro_source_type_to_category("PIB_Circular"), "PIB Circular")
        self.assertEqual(macro_source_type_to_category("PIB_Circular_2026"), "PIB Circular")
        self.assertEqual(macro_source_type_to_category("RBI_Annual_Report"), "RBI Report / Economic Survey")
        self.assertEqual(macro_source_type_to_category("RBI_Financial_Stability_Report"), "RBI Report / Economic Survey")
        self.assertEqual(macro_source_type_to_category("Economic_Survey"), "Economic Survey")
        self.assertEqual(macro_source_type_to_category("Union_Budget"), "Union Budget / Tax Reform")
        self.assertEqual(macro_source_type_to_category("Union_Budget_2026"), "Union Budget / Tax Reform")
        # Concall / YouTube fallbacks still resolve.
        self.assertEqual(macro_source_type_to_category("Earnings_Concall"), "Quarterly Concall / MPC Stance")
        self.assertEqual(macro_source_type_to_category("YouTube_Analysis"), "Analyst Commentary / YouTube")

    # ------------------------------------------------------------------ #
    def test_03_structural_milestone_never_pruned(self):
        """A structural-milestone doc (old, embedded) is excluded from pruning; a
        same-age non-structural doc IS pruned (both dry-run count and real purge)."""
        mgr = _make_env(self.tmp)
        with mgr.session() as conn:
            # Non-structural old doc (should be counted / purged).
            doc_ns = _insert_raw_doc(conn, "Old Union Budget", "Union_Budget", OLD_DATE, structural=False)
            _insert_chunk(conn, doc_ns, 0, _fake_embedding())
            # Structural old doc (must survive pruning) — flagged via BOTH the legacy
            # 'Structural Milestone' source_type marker AND the explicit column flag.
            doc_s = _insert_raw_doc(
                conn, "Structural Milestone Test Doc",
                "Structural Milestone Test", OLD_DATE, structural=True,
            )
            _insert_chunk(conn, doc_s, 0, _fake_embedding())

        # Dry run: structural must NOT be counted; non-structural must be.
        dry = prune_decayed_signals(mgr, dry_run=True)
        self.assertEqual(dry["backend"], "sqlite")
        self.assertEqual(dry["vectors_purged"], 1,
                         "dry-run must count only the non-structural old row")

        # Real prune.
        res = prune_decayed_signals(mgr, dry_run=False)
        self.assertEqual(res["vectors_purged"], 1)

        with mgr.session() as conn:
            ns_emb = conn.execute(
                "SELECT embedding FROM document_chunks WHERE doc_id=?", (doc_ns,)
            ).fetchone()[0]
            s_emb = conn.execute(
                "SELECT embedding FROM document_chunks WHERE doc_id=?", (doc_s,)
            ).fetchone()[0]
        self.assertIsNone(ns_emb, "non-structural old embedding must be purged")
        self.assertIsNotNone(s_emb, "structural milestone embedding must survive pruning")

    # ------------------------------------------------------------------ #
    def test_04_decayed_significance_formula(self):
        """S(t) = S0 * e^{-lambda*t}; structural (lambda=0) stays at S0."""
        S0 = 10.0
        cat = "Union Budget / Tax Reform"
        # 12 months at half-life 12 -> exactly half the significance.
        expected = S0 * math.exp(-(math.log(2) / HALF_LIVES[cat]) * 12.0)
        self.assertAlmostEqual(expected, 5.0, places=6)
        self.assertAlmostEqual(decayed_significance(S0, cat, 12.0), 5.0, places=6)

        # Structural milestone -> lambda 0 -> S(t) == S0 regardless of elapsed time.
        self.assertEqual(
            decayed_significance(S0, cat, 12.0, source_type="Structural Milestone Test"),
            S0,
        )
        self.assertEqual(
            decayed_significance(S0, cat, 100.0, source_type="Structural Milestone Test"),
            S0,
        )
        # effective_lambda also collapses to 0 for structural source types.
        self.assertEqual(effective_lambda(cat, "Structural Milestone Test"), 0.0)
        self.assertGreater(effective_lambda(cat, None), 0.0)
        # Marker helper.
        self.assertTrue(is_structural_milestone("Structural Milestone Test"))
        self.assertFalse(is_structural_milestone("Union_Budget"))

    # ------------------------------------------------------------------ #
    def test_05_v_ripple_decayed_emulation(self):
        """Emulated v_ripple_decayed: non-structural decays (< S0), structural == S0."""
        mgr = _make_env(self.tmp)
        S0 = 10.0
        with mgr.session() as conn:
            # Non-structural Union Budget doc/event/ripple.
            doc_ns = _insert_raw_doc(conn, "Old Union Budget NS", "Union_Budget", OLD_DATE)
            conn.execute(
                "INSERT INTO macro_events (event_id, event_name, category, event_date, summary) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(doc_ns), "NS event", "Union Budget / Tax Reform", OLD_DATE, "ns"),
            )
            conn.execute(
                "INSERT INTO ripple_effects (event_id, order_level, raw_magnitude, probability, "
                "lag_time_months, significance_rank) VALUES (?, 1, 1.0, 1.0, 0, ?)",
                (str(doc_ns), S0),
            )
            # Structural doc/event/ripple.
            doc_s = _insert_raw_doc(
                conn, "Structural Milestone Rip", "Structural Milestone Rip", OLD_DATE, structural=True,
            )
            conn.execute(
                "INSERT INTO macro_events (event_id, event_name, category, event_date, summary) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(doc_s), "S event", "Union Budget / Tax Reform", OLD_DATE, "s"),
            )
            conn.execute(
                "INSERT INTO ripple_effects (event_id, order_level, raw_magnitude, probability, "
                "lag_time_months, significance_rank) VALUES (?, 1, 1.0, 1.0, 0, ?)",
                (str(doc_s), S0),
            )

        rows = get_decayed_significance_rows(mgr, limit=20)
        self.assertGreaterEqual(len(rows), 2)
        ns_row = next(r for r in rows if str(r["event_id"]) == str(doc_ns))
        s_row = next(r for r in rows if str(r["event_id"]) == str(doc_s))

        # Non-structural decayed below S0.
        self.assertLess(ns_row["decayed_significance"], S0,
                        "non-structural ripple must decay below S0")
        self.assertAlmostEqual(ns_row["lambda"], math.log(2) / 12.0, places=4)
        # Structural milestone: lambda 0 -> decayed == S0.
        self.assertEqual(s_row["lambda"], 0.0)
        self.assertAlmostEqual(s_row["decayed_significance"], S0, places=2,
                               msg="structural milestone must NOT decay (== S0)")

    # ------------------------------------------------------------------ #
    def test_06_distill_before_delete_24_chunks(self):
        """synthesize_and_update over 24 mock chunks updates moat, purges 24 vectors,
        and logs distillation_runs."""
        mgr = _make_env(self.tmp)
        chunks = [
            f"Mock chunk {i} for HAL mentioning pricing power and network effect signal"
            for i in range(24)
        ]
        res = synthesize_and_update("HAL", chunks, manager=mgr)

        self.assertEqual(res["symbol"], "HAL")
        self.assertEqual(res["chunks_distilled"], 24)
        self.assertEqual(res["vectors_purged"], 24,
                         "24 vectors must be reclaimed (mock-counted) before delete")
        self.assertTrue(res["moat_updated"], "moat_evaluations must be updated")

        with mgr.session() as conn:
            # distillation_runs logged with the 24-row contract.
            runs = conn.execute("SELECT * FROM distillation_runs").fetchall()
            self.assertEqual(len(runs), 1, "exactly one distillation_runs row expected")
            run = runs[0]
            self.assertEqual(run["chunks_distilled"], 24)
            self.assertEqual(run["vectors_purged"], 24)
            self.assertEqual(run["source_type"], "HAL:20YouTube+4Concall")

            # moat_evaluations has a HAL row derived from the synthesized deltas.
            moat = conn.execute(
                "SELECT ticker, total_moat_score, moat_trajectory FROM moat_evaluations WHERE ticker=?",
                ("HAL",),
            ).fetchone()
            self.assertIsNotNone(moat, "HAL moat row must exist after distillation")
            # Baseline 3/3/3/3/3 + delta_sc=1 (pricing power) + delta_ne=1 (network) -> 3.5.
            self.assertAlmostEqual(moat["total_moat_score"], 3.5, places=2)

    # ------------------------------------------------------------------ #
    def test_07_monthly_batch_prune_verified(self):
        """run_monthly_batch_with_prune_check flags prune_verified when vectors reclaimed."""
        mgr = _make_env(self.tmp)
        res = run_monthly_batch_with_prune_check("POLYPLEX", manager=mgr)
        self.assertEqual(res["chunks_distilled"], 24)
        self.assertEqual(res["vectors_purged"], 24)
        self.assertTrue(res["prune_verified"],
                        "prune_verified must be True when vectors_purged == chunks_distilled > 0")
        with mgr.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM distillation_runs").fetchone()[0], 1)

    # ------------------------------------------------------------------ #
    def test_08_structural_excluded_from_distillation_candidates(self):
        """Distillation candidates must exclude structural-milestone vectors."""
        mgr = _make_env(self.tmp)
        with mgr.session() as conn:
            # Normal YouTube doc with 2 embedded chunks.
            doc_y = _insert_raw_doc(conn, "HAL YouTube", "YouTube_Analysis", OLD_DATE)
            _insert_chunk(conn, doc_y, 0, _fake_embedding())
            _insert_chunk(conn, doc_y, 1, _fake_embedding())
            # Structural milestone doc with 2 embedded chunks (must be excluded).
            doc_s = _insert_raw_doc(
                conn, "Structural Milestone Clips", "Structural Milestone Clips", OLD_DATE, structural=True,
            )
            _insert_chunk(conn, doc_s, 0, _fake_embedding())
            _insert_chunk(conn, doc_s, 1, _fake_embedding())

        cands = fetch_distillation_candidates(mgr, symbol=None, youtube_n=20, concall_n=4)
        cand_doc_ids = {c["doc_id"] for c in cands}
        self.assertIn(doc_y, cand_doc_ids, "normal YouTube chunks should be candidates")
        self.assertNotIn(doc_s, cand_doc_ids, "structural milestone chunks must be excluded")


if __name__ == "__main__":
    unittest.main(verbosity=2)
