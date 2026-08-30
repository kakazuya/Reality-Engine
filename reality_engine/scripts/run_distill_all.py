"""
Wave 0 — Substrate promotion runner for ALL macro raw_documents.

One-shot batch distiller owned by Wave 0 (parallel substrate promotion).

Flow:
  raw_documents (Union/State budget, Economic Survey, PIB, RBI)  ->  dense substrate
  (macro_events + ripple_effects) via DistillationEngine.distill_all_macro_documents.

Idempotent: each raw doc is upserted as one macro_event with its ripple DAG.
Gracefully reports when there are no macro docs to distill.
"""

from __future__ import annotations

import sys
from datetime import date

from reality_engine.db.repository import repo
from reality_engine.processing.distillation_engine import distillation_engine


def _counts_before():
    with repo.db.session() as conn:
        raw_by_type = [
            dict(r) for r in conn.execute(
                "SELECT source_type, COUNT(*) AS c FROM raw_documents GROUP BY source_type ORDER BY c DESC"
            ).fetchall()
        ]
        try:
            chunks = conn.execute("SELECT COUNT(*) AS c FROM document_chunks").fetchone()["c"]
        except Exception:
            chunks = 0
        try:
            macro_before = conn.execute("SELECT COUNT(*) AS c FROM macro_events").fetchone()["c"]
        except Exception:
            macro_before = 0
    return raw_by_type, chunks, macro_before


def _counts_after():
    with repo.db.session() as conn:
        macro_after = conn.execute("SELECT COUNT(*) AS c FROM macro_events").fetchone()["c"]
        ripples = conn.execute("SELECT COUNT(*) AS c FROM ripple_effects").fetchone()["c"]
        # Distinct doc_ids that now have a macro_event (acceptance signal).
        docs_linked = conn.execute(
            "SELECT COUNT(DISTINCT doc_id) AS c FROM macro_events WHERE doc_id IS NOT NULL"
        ).fetchone()["c"]
    return macro_after, ripples, docs_linked


def main() -> int:
    print("=" * 64)
    print("WAVE 0 :: Distill ALL macro raw_documents -> dense substrate")
    print("=" * 64)

    # 1. Ensure dense-substrate tables exist (idempotent, additive only).
    repo.ensure_ripple_effects_schema()
    repo.ensure_macro_event_doc_id()

    raw_by_type, chunks, macro_before = _counts_before()
    print("\n[before] raw_documents by source_type:")
    if raw_by_type:
        for row in raw_by_type:
            print(f"   - {row['source_type']:<28} {row['c']}")
    else:
        print("   (none)")
    print(f"[before] document_chunks count : {chunks}")
    print(f"[before] macro_events count    : {macro_before}")

    # 2. Identify the macro-policy doc set (the engine filters by prefix).
    macro_docs = repo.list_macro_raw_documents()
    if not macro_docs:
        print("\nWARNING: no macro-policy raw_documents found to distill. "
              "Run macro ingest (pipeline.macro_runner.run_macro) first.")
        return 0

    print(f"\n[target] macro-policy raw_documents to distill: {len(macro_docs)}")

    # 3. Distill ALL macro docs (no filter, no limit).
    result = distillation_engine.distill_all_macro_documents()
    distilled = result.get("distilled", 0)
    details = result.get("details", [])

    # 4. Report per-doc detail.
    print(f"\n[result] documents processed : {distilled}")
    for d in details:
        status = d.get("status", "?")
        if status == "error":
            print(f"   doc_id={d.get('doc_id')} STATUS={status} ERROR={d.get('error')}")
        else:
            print(f"   doc_id={d.get('doc_id')} event_id={d.get('event_id')} "
                  f"events={d.get('events_created')} ripples={d.get('ripples_created')} "
                  f"status={status}")

    macro_after, ripples, docs_linked = _counts_after()
    print(f"\n[after] macro_events count    : {macro_after}")
    print(f"[after] ripple_effects count  : {ripples}")
    print(f"[after] macro_events w/ doc_id: {docs_linked}")

    # 5. Acceptance check: every macro raw doc should yield >=1 macro_event.
    if docs_linked >= len(macro_docs):
        print("\nACCEPTANCE: all macro raw_documents promoted to dense substrate. OK")
        return 0

    print(f"\nWARN: linked doc_ids ({docs_linked}) < macro docs ({len(macro_docs)}); "
          "some docs may have failed extraction (see errors above).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
