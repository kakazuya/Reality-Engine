# Task C2-wide — bigger test: old chunks vs chunker_v2 vs LLM-extracted facts (decks + concalls)

## Goal
Round 3 used 40 deck and 90 concall questions — too few to commit the whole corpus. Build a wide, trustworthy test on
**300 real decks and 300 concalls**, and compare three arms: old chunks, chunker_v2 (Q&A cap 2,200, with headers),
and the facts LLM readers already extracted (`deck_figures.db:facts`, `concall_facts.db`).

## Inputs
- 288 real decks: `D:\RealityEngine\raw\deck_real_test300\manifest.json` (skip `path: null`), 2021–2026.
- 300 concalls: sample from `raw_documents` (`CONCALL_TRANSCRIPT`, 2021+), stratified by year and by market-cap
  bucket (large/mid/small from `master_companies` or price×shares), text from the existing chunks/raw text.
- Code on main: `chunker_v2.py` (Q&A cap), `eval_retrieval.py` (budget metric), round-3 builders in history.

## Phase A — questions (400 rows → `quality_set_wide.jsonl`)
- 200 deck + 200 concall. Same rules as round 2/3: you read the passage, then write the question as an equity analyst
  would; no templates or scripted generation; paraphrase; answerable from the span alone; spans in normalised doc text.
- Mix: ≥60 table/chart deck rows; ≥60 concall Q&A rows; ≥60 guidance/forward-looking rows; ≥40 cross-document rows
  (question names company + fact, not the doc). Tag sector, mcap bucket, year.
- Print 20 random rows for the manager's audit.

## Phase B — corpora
Pilot DB under `.tmp/c2w/` with old chunks and v2 chunks for the same 588 docs, plus an "LLM facts" arm: one text
unit per extracted fact (metric, value, period, the reader's quote/context) with the doc id and page/offset when
stored. Export `.tmp/c2w/dense_input/{old,v2,facts}.jsonl` with fields
`chunk_id, doc_id, doc_type, norm_start, norm_end, text` where **text = header + "\n" + body** (round 3's export left
headers out and handicapped v2 — do not repeat that).

## Phase C — FTS eval
R@1/5/10, MRR, B@5k/B@10k for the three arms: overall, per doc type, per question type, per sector and mcap bucket.
For the facts arm, a hit is a fact whose source span overlaps the gold span; report how many gold spans have no fact
at all (facts coverage).

## Rules
- **No network.** No paid APIs (the manager runs the dense pass on your export). Live DBs via `connect_ro` only.
  Raw data read-only. Work in this worktree and `.tmp/`. Do not commit.

## Acceptance checks
1. 400 rows, 20 printed, mix counts shown.
2. Three dense_input files with headers; token counts.
3. FTS tables as above; facts-coverage number.
4. Tests for any new code.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_chunker_v2 reality_engine.tests.test_eval_budget
```

## Report
Phase summaries, audit rows, tables, open problems, tool calls. One line per phase to `.tmp/PROGRESS_NOTES.md`.
