# Progress notes - T-049 G embedding retrieval test

- 2026-11-04: read the context pack, `lookups_pilot3.py` search SQL, pilot3 registry/schema/build, `tasks/STATE.md`. Corpus probe: 100 docs / 4,606 pages, all 100 source PDFs present (32/32 decks), PyMuPDF 1.28.2 installed.
- 2026-11-04: wrote `reality_engine/pilot3/embed_test.py` (plan / embed / eval) and `reality_engine/tests/test_pilot3_embed_test.py` (15 tests). `plan` prints 3,662,936 text tokens, $0.1416 (1B) / $0.3015 (8B) with images.
- 2026-11-04: full offline `embed --dry-run` embedded all 4,606 pages (fake $0.0549); `eval --dry-run` on a 3-question real-corpus gold fixture wrote `.tmp/embed_dry/EVAL.xlsx` (bm25 hit@1 33%, MRR 0.461; dense random). No paid call.
- 2026-11-04: docs updated (guide O7, STATE line). Next: run the test file once more, doc_gate, report.
