"""Hermetic tests for the bge-small vs bge-base embedding prototype.

Contract: temp data + tiny synthetic vectors only — no model download, no
live DB, no network, deterministic, fast. Covers:
  * recall math on synthetic vectors (perfect, partial, cosine-vs-dot
    precedence proving the shared code path normalises like
    ``ChunkVectorIndex.search``);
  * Q/A artifact schema (counts per doc, required keys, violation detection);
  * sampler determinism (even spacing, endpoints, repeatability) incl. a
    read-only sample pass over a temp SQLite DB.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

_TEMP_DIR = tempfile.mkdtemp(prefix="reality_embed_proto_test_")
os.environ.setdefault(
    "REALITY_ENGINE_DB_PATH", str(Path(_TEMP_DIR) / "prototype_isolated.db")
)

import numpy as np  # noqa: E402

from reality_engine.scripts import embed_prototype_compare as epc  # noqa: E402


def _rows(n, doc_id=6490, base=1000):
    return [
        {
            "chunk_id": base + i,
            "doc_id": doc_id,
            "chunk_index": i,
            "content": f"[Metadata: Symbol: SAIL] disclosure {i} with figure {100 + i} crore",
        }
        for i in range(n)
    ]


class SamplerDeterminismTest(unittest.TestCase):
    def test_even_spacing_with_endpoints(self):
        rows = _rows(10)
        got = epc.deterministic_sample(rows, 3)
        self.assertEqual([r["chunk_index"] for r in got], [0, 4, 9])

    def test_repeatable(self):
        rows = _rows(443, doc_id=6490) + _rows(329, doc_id=6491, base=9000)
        first = epc.deterministic_sample(rows, 200)
        second = epc.deterministic_sample(rows, 200)
        self.assertEqual(first, second)

    def test_order_preserved(self):
        rows = _rows(50)
        got = epc.deterministic_sample(rows, 7)
        idx = [r["chunk_index"] for r in got]
        self.assertEqual(idx, sorted(idx))
        self.assertEqual(len(set(idx)), 7)

    def test_limit_covers_all_when_small(self):
        rows = _rows(5)
        self.assertEqual(epc.deterministic_sample(rows, 200), rows)

    def test_limit_one_returns_first(self):
        rows = _rows(10)
        self.assertEqual(epc.deterministic_sample(rows, 1), [rows[0]])

    def test_limit_zero_empty(self):
        self.assertEqual(epc.deterministic_sample(_rows(10), 0), [])

    def test_load_samples_reads_temp_db_only(self):
        db = Path(tempfile.mkdtemp()) / "chunks.db"
        con = sqlite3.connect(str(db))
        con.execute(
            "CREATE TABLE document_chunks (chunk_id INTEGER PRIMARY KEY, doc_id INTEGER, "
            "chunk_index INTEGER, content TEXT)"
        )
        for doc in (6490, 6491):
            for i in range(30):
                con.execute(
                    "INSERT INTO document_chunks VALUES (?, ?, ?, ?)",
                    (doc * 1000 + i, doc, i, f"chunk text {doc}-{i}"),
                )
        con.commit()
        con.close()
        before = db.stat().st_mtime_ns
        got = epc.load_samples(db, (6490, 6491), limit=10)
        self.assertEqual(db.stat().st_mtime_ns, before)  # read-only: file untouched
        self.assertEqual(len(got), 20)
        for doc in (6490, 6491):
            idx = [r["chunk_index"] for r in got if r["doc_id"] == doc]
            self.assertEqual(len(idx), 10)
            self.assertEqual(idx, sorted(idx))
            self.assertEqual(idx[0], 0)
            self.assertEqual(idx[-1], 29)
        again = epc.load_samples(db, (6490, 6491), limit=10)
        self.assertEqual(got, again)


class RecallMathTest(unittest.TestCase):
    def test_perfect_recall(self):
        mat = np.eye(4, dtype=np.float32)
        ids = [11, 12, 13, 14]
        queries = [mat[i].tolist() for i in range(4)]
        qa = [{"answer_chunk_id": cid} for cid in ids]
        out = epc.score_model(queries, mat, ids, qa)
        self.assertEqual(out["r1"], 1.0)
        self.assertEqual(out["r5"], 1.0)

    def test_partial_recall(self):
        mat = np.eye(3, dtype=np.float32)
        ids = [21, 22, 23]
        queries = [
            mat[0].tolist(),  # answer 21 ranks 1st
            (0.9 * mat[0] + 0.1 * mat[1]).tolist(),  # answer 22 ranks 2nd
        ]
        qa = [{"answer_chunk_id": 21}, {"answer_chunk_id": 22}]
        out = epc.score_model(queries, mat, ids, qa)
        self.assertEqual(out["r1"], 0.5)
        self.assertEqual(out["r5"], 1.0)

    def test_cosine_not_raw_dot(self):
        # q . p0 = 1.0 beats q . p1 = 0.9, but cosine prefers p1 — the
        # ChunkVectorIndex.search pattern (L2-normalise, then dot).
        mat = np.array([[2.0, 0.0], [0.0, 1.0]], dtype=np.float32)
        order = epc.rank_passages([0.5, 0.9], mat)
        self.assertEqual(list(order), [1, 0])

    def test_queries_must_align_with_qa(self):
        mat = np.eye(2, dtype=np.float32)
        ids = [31, 32]
        qa = [{"answer_chunk_id": 31}]
        out = epc.score_model([mat[0].tolist()], mat, ids, qa)
        self.assertEqual(out["r1"], 1.0)


class QaArtifactSchemaTest(unittest.TestCase):
    def _artifact(self, per_doc=10):
        sampled = _rows(12, doc_id=6490, base=1000) + _rows(15, doc_id=6491, base=2000)
        questions = epc.build_qa_set(sampled, per_doc=per_doc)
        return {
            "generated_at": "2026-09-23T00:00:00+00:00",
            "doc_ids": [6490, 6491],
            "sampled_chunk_ids": [r["chunk_id"] for r in sampled],
            "questions": questions,
        }

    def test_twenty_entries_ten_per_doc(self):
        art = self._artifact()
        self.assertEqual(len(art["questions"]), 20)
        self.assertEqual(
            sum(1 for q in art["questions"] if q["doc_id"] == 6490), 10
        )
        self.assertEqual(
            sum(1 for q in art["questions"] if q["doc_id"] == 6491), 10
        )
        self.assertEqual(epc.validate_qa_artifact(art), [])

    def test_required_keys_and_unique_answers(self):
        art = self._artifact()
        seen = set()
        for q in art["questions"]:
            for key in ("question", "answer_chunk_id", "doc_id"):
                self.assertIn(key, q)
            self.assertTrue(q["question"].strip())
            self.assertIsInstance(q["answer_chunk_id"], int)
            self.assertNotIn(q["answer_chunk_id"], seen)
            seen.add(q["answer_chunk_id"])

    def test_questions_quote_chunk_content(self):
        art = self._artifact()
        self.assertTrue(all(q.get("anchor") for q in art["questions"]))
        self.assertTrue(all(q["anchor"] in q["question"] for q in art["questions"]))

    def test_rejects_wrong_count(self):
        art = self._artifact()
        art["questions"] = art["questions"][:19]
        self.assertTrue(epc.validate_qa_artifact(art))

    def test_rejects_missing_key(self):
        art = self._artifact()
        del art["questions"][0]["answer_chunk_id"]
        errors = epc.validate_qa_artifact(art)
        self.assertTrue(any("answer_chunk_id" in e for e in errors))

    def test_rejects_duplicate_answer(self):
        art = self._artifact()
        art["questions"][1]["answer_chunk_id"] = art["questions"][0]["answer_chunk_id"]
        errors = epc.validate_qa_artifact(art)
        self.assertTrue(any("duplicated" in e for e in errors))

    def test_rejects_empty_question_and_bad_doc(self):
        art = self._artifact()
        art["questions"][0]["question"] = "   "
        art["questions"][1]["doc_id"] = 1234
        errors = epc.validate_qa_artifact(art)
        self.assertEqual(len([e for e in errors if "non-empty" in e]), 1)
        self.assertTrue(any("doc_id" in e for e in errors))

    def test_anchor_prefers_figures(self):
        text = (
            "[Metadata: Symbol: SAIL] general opening remarks on the business. "
            "Revenue from operations grew 12 percent to 5000 crore rupees."
        )
        anchor = epc.pick_anchor_sentence(text)
        self.assertIn("5000", anchor)
        self.assertNotIn("Metadata", anchor)


if __name__ == "__main__":
    unittest.main()
