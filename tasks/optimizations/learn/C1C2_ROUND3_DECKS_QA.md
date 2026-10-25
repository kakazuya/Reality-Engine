# Task C1/C2 round 3 — real decks, Q&A cap, fair metric, layout triage (full-access trial)

## Goal
Settle the three open questions from round 2 with a fair test:
1. Does chunker_v2 (± GPU layout) beat today's chunks on **real investor presentations**?
2. Does capping concall Q&A units recover the R@1 loss?
3. Is "old wins on FTS" just because old chunks are 2× bigger?

## Run mode
This worker runs with **write_scope='full'** as a trial Shivam asked for: we want to see whether you work faster
without the sandbox (round 2 lost time to the denied `multiprocessing.Pool` and to CUDA instability). Full access
removes the OS sandbox, so the rules below are the real fence. Keep them exactly.

- **No network at all.** Every input is already on disk. No pip, HF, Drive, BSE, or API calls.
- **No live DB writes.** Live DBs (`reality_engine/data/*.db`, `REALITY_DATA_ROOT`) are read through `connect_ro`
  only.
- **Raw data under `D:\RealityEngine` is read-only.**
- Work only inside this worktree and its `.tmp/`. Do not touch the main checkout, `.git/config`,
  `plugins/dsh-worker/`, `~/.dsh`, or any other job's files.
- Do not commit; the manager commits.
- Write one line to `.tmp/PROGRESS_NOTES.md` after each phase, and at the end record: wall time, tool calls, and
  every point where full access helped or did not matter (e.g. Pool now works? CUDA long-lived context now works?).

## Inputs
- Round-2 code, merged on main: `chunker_v2.py`, `layout_gpu.py`, `eval_retrieval.py`, `test_chunker_v2.py`,
  `quality_set_v2.jsonl`. Pilot DBs from round 2 are in the round-2 worktree
  `C:\Users\warri\Downloads\IDM-worktrees\20261025T161216Z-02376206\.tmp\c1\` (read; copy what you need).
- **48 real investor decks:** `D:\RealityEngine\raw\deck_real_pilot\manifest.json` lists symbol, isin, known_at,
  title, sha256 and local `path`. Skip rows with `path: null`. Note: round 2's 50 "decks" were one-page
  announcements and must not be used as decks.
- `.venv-layout` in the main checkout (`C:\Users\warri\Downloads\Info_Diffusion_Model\.venv-layout`), weights already
  under the round-2 worktree's `.tmp/c1b/models/` (copy them). Gotchas: `import torch` before `onnxruntime`;
  set `YOLO_CONFIG_DIR`/`MPLCONFIGDIR` under `.tmp/`.

## Phase A — real deck questions
- Build deck docs from the 48 PDFs (text layer per page, like `build_deck_page_text.py`, but into a pilot DB under
  `.tmp/c1/`, never `deck_figures.db`). Build both old-style chunks (today's production chunker on the same text)
  and v2 chunks, so they're comparable.
- Replace the 40 deck rows in `quality_set_v2.jsonl` with 40 new rows on these decks → write
  `quality_set_v3.jsonl` (all other 160 rows copied unchanged). Same rules as round 2: you write each question
  after reading the slide, as an analyst would; no templates; paraphrase; answerable from the span alone; spans in
  normalised doc text. Include ≥10 where the answer is in a chart or table slide.
- Also drop/fix the round-2 rows whose span is the analyst's question rather than the answer (e.g. q019 Arvind) —
  list every row you change.
- Print 15 random new deck rows for audit.

## Phase B — concall Q&A cap
Cap Q&A units at ~2,000–2,500 chars, splitting only at speaker-turn boundaries (an answer that is itself longer is
split at sentence boundaries, with the question repeated in the header). Add a test.

## Phase C — layout triage and tables
- Tighten triage: today 63% of AR pages route to the GPU, mostly two-column false positives. Target ≤35% without
  losing real tables (check on the round-2 hand-check pages).
- Cut table over-detection (1,190 boxes / 1,838 pages): require a cell grid or ≥3 aligned numeric columns.
- Run layout on the 48 decks and the same 9 ARs. Report pages/s, routed %, VRAM peak, and whether a **single
  long-lived CUDA process** now works with full access (try it first; fall back to one process per doc).
- Hand-check 20 deck slides (tables, chart labels, reading order).

## Phase D — fair evaluation
Add to `eval_retrieval.py` a **character-budget metric**: recall when each retriever may return at most N
characters (N = 5,000 and 10,000), so bigger chunks get no free overlap advantage. Report on quality_set_v3, FTS:
old, v2, v2+Q&A-cap, v2+layout — overall, per type, hard-20 — with both R@k and budget-recall.
Write the chunk sets the manager will embed to `.tmp/c1/dense_input/<variant>.jsonl`
(`chunk_id, doc_id, doc_type, norm_start, norm_end, text`) so the manager can run the paid dense pass. No paid calls.

## Acceptance checks
1. `python -m unittest reality_engine.tests.test_chunker_v2` passes with the new tests.
2. `quality_set_v3.jsonl`: 200 rows, 40 on real decks, 15 printed; changed rows listed.
3. Results table with R@k and budget-recall for the four variants.
4. Layout numbers on decks + ARs, routed % ≤35% or an explanation.
5. Full-access notes (what changed vs the sandbox).

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_chunker_v2
```

## Budget
≤ 10 tool calls before the first edit; ≤ 260 total; $0 paid.

## Report
1. Phase A + 15 audit rows + changed rows  2. Q&A cap  3. Layout numbers + hand-check  4. Results tables
5. Full-access notes (time, tool calls, what the sandbox had blocked)  6. Open problems  7. Tool calls.
