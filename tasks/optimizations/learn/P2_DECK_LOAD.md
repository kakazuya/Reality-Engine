# Task P2 — load all real investor decks into chunks (full access)

## Goal
The 26,387 real investor decks in `deck_figures.db:deck_sources` (status ok, sha256 known, PDFs in the Google Drive
`decks` folder) were read for figures but never chunked. The "INVESTOR_PRESENTATION" rows in `raw_documents` are
mostly one-page cover letters. Put every real deck's text into a new chunk store so search can use it.

## How
1. Download: `reality_engine.toolbelt.drive_fetch.fetch(shas, dest=..., folder="decks", verify=True, transfers=8)`
   in batches of 500 into `D:\RealityEngine\raw\decks_full\<sha[:2]>\<sha>.pdf` (resumable: skip files present).
   Skip anything already at `D:\RealityEngine\raw\deck_real_pilot*` (copy or hard-link instead). Log misses.
2. Text: PyMuPDF per page; pages under 40 chars are `empty` (image-only, OCR later). Parse in a
   `multiprocessing.Pool(7)` (full access should allow it; report if not).
3. Chunk with **today's production deck chunking** (the "old" chunker — round 3 showed it beats chunker_v2 on decks,
   R@1 .625 vs .550) and store each chunk with a header: company · "Investor presentation" · deck title · date.
4. Write to a **new** DB `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\chunks_v2.db`, table
   `deck_chunks(chunk_id, sha256, symbol, isin, known_at, title, page_from, page_to, header, body, char_len)` +
   FTS5, plus `deck_docs(sha256, symbol, isin, known_at, title, pages, empty_pages, status)`. One writer, commit every
   500 decks, FTS built at the end.
5. Point-in-time: `known_at` is the filing date; keep it on every chunk.

## Write scope (full access — this is the fence)
- Network: Google Drive via `drive_fetch` only.
- Writes: `D:\RealityEngine\raw\decks_full\`, the new `chunks_v2.db`, this worktree. Nothing else: no
  `equity_intelligence.db`, no `deck_figures.db`, no vector indexes, no `.git/config`, `plugins/dsh-worker/`, `~/.dsh`.
- No paid APIs. Do not commit; the manager does.

## Acceptance checks
1. Coverage: decks in `deck_sources` (ok) vs downloaded vs chunked, per year 2019–2026; misses listed with reason.
2. Chunk stats (p10/p50/p90 chars, chunks/deck), empty-page share, total tokens (chars/4) for the embed estimate.
3. 10 random chunks printed with headers.
4. Speed: decks/s download, pages/s parse.
5. Tests for the new builder.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_deck_chunk_load
```

## Report
Coverage table, stats, misses, timings, full-access notes, tool calls. One line per phase to `.tmp/PROGRESS_NOTES.md`.
