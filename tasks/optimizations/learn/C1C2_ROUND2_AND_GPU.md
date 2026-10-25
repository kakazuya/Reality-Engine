# Task C1/C2 round 2 + C1b GPU layout — real questions, chunker fixes, GPU pilot

## Goal
Find out, with a trustworthy test, whether chunker_v2 (with or without GPU layout detection) retrieves better than
today's chunks.

## Where things stand
Worktree `C:\Users\warri\Downloads\IDM-worktrees\20261025T161216Z-02376206`, HEAD = the WIP commit. It contains
`reality_engine/processing/chunker_v2.py`, `reality_engine/scripts/eval_retrieval.py`,
`reality_engine/tests/test_chunker_v2.py` (8 tests OK) and `tasks/optimizations/learn/quality_set_v1.jsonl`. The
pilot DB, stats and eval JSONs are under `.tmp/c1/`. Read the original brief and the GPU brief from the main checkout (they are not in this
worktree):
- `C:\Users\warri\Downloads\Info_Diffusion_Model\tasks\optimizations\learn\C1C2_CHUNKER_AND_QUALITY_SET.md`
- `C:\Users\warri\Downloads\Info_Diffusion_Model\tasks\optimizations\learn\C1B_LAYOUT_GPU.md`
- `C:\Users\warri\Downloads\Info_Diffusion_Model\tasks\optimizations\learn\venv_layout_requirements.txt`

**Manager review of round 1.** The quality set is not usable. Its questions came from templates:
- "what figure is reported in the passage?" was answered by a company-secretary signature block;
- "what was its not constant currency?";
- "what did BLSINFOTE disclose about signed anirudh rathi?".

So the FTS numbers measure nothing. The pilot stats show:
- **Good:** concall Q&A cuts fell from 166 to 66, and AR table cuts from 177 to 49.
- **Bad:**
  - AR chunks have p10 = 160 chars, so tiny fragments are not being merged.
  - The AR chunker took 513 s for 50 docs, about 10 s each.
  - Deck recall@1 dropped against the old chunks (one small slide per chunk).

## Phase A — rewrite the quality set (`quality_set_v2.jsonl`, 200 rows, same fields + `source_chunking`)
- **Pick substantive passages only:** numbers with context, guidance, segment commentary, policy clauses with
  amounts, Q&A answers, table rows with labels.
- **Exclude boilerplate:** signatures, cover letters, "Thanking you / Yours faithfully", safe-harbour text, lists of
  related-party names, CIN/DIN lines, addresses, page headers, tables of contents.
- **You write each question yourself** after reading the passage, the way an equity analyst would ask it. For
  example: "What EBITDA margin guidance did ALICON give for FY27?" or "How much did the PIB release say the coal
  gasification scheme will spend?".
  - No templates or scripted question generation.
  - Don't reuse the passage's rare phrases verbatim; paraphrase.
  - The question must be answerable from the span alone.
- **Mix:** 60 concall, 40 deck, 40 AR/results, 30 circular, 30 cross-document (question names a company or theme
  and a fact, not the doc). Keep 20 hard ones where the answer is in a table or a Q&A pair.
- **Spans:** pick passages from the raw document text (independent of either chunking). The span is the answer's
  character range in the document.
- **Self-check:** print 15 random rows (question, answer text, why) in your report so the manager can audit them.

## Phase B — chunker fixes (`chunker_v2.py`)
1. **Merge undersized units.** Anything under ~300 chars merges into the next unit in the same section, so the AR
   p10 should be above 300. Headings alone never form a chunk.
2. **Deck slides.** Prefix each slide chunk's header with the deck title and section, taken from the nearest
   section-divider slide. Merge a slide under ~250 chars of body with the next slide in the same section.
3. **Speed.**
   - Parse documents in a `multiprocessing.Pool` with 7 workers.
   - One writer commits every 500 docs. Build the FTS once at the end.
   - Report docs/s on the 50-AR pilot, before and after.
4. Add tests for 1 and 2.

## Phase C — GPU layout (follow `C1B_LAYOUT_GPU.md`)
The environment is ready: `.venv-layout` in the **main checkout**
(`C:\Users\warri\Downloads\Info_Diffusion_Model\.venv-layout`).
- **Installed:** torch 2.14.1+cu126 (GTX 1050 Ti, sm_61 OK), doclayout-yolo 0.0.4, onnxruntime-gpu 1.25.1 (CUDA
  12), rapid-table, rapidocr, pymupdf 2.0. Versions are in `tasks/optimizations/learn/venv_layout_requirements.txt`.
- **Gotchas:**
  - `import torch` before `onnxruntime`, so the CUDA 12 / cuDNN 9 DLLs load. Then `CUDAExecutionProvider` works.
  - Set `YOLO_CONFIG_DIR` and `MPLCONFIGDIR` to folders under `.tmp/`, or doclayout-yolo fails writing to AppData.
  - Download the DocLayout-YOLO DocStructBench weights from Hugging Face into `.tmp/c1b/models/`. That and PyPI are
    the only allowed network calls.
- **Run** the triage → layout → tables → text → chunk pipeline as `reality_engine/processing/layout_gpu.py`, behind
  a `--layout` flag of the pilot builder, on the same 50 ARs and 50 decks. Report:
  - pages/s;
  - share of pages routed to the GPU;
  - VRAM peak (`torch.cuda.max_memory_allocated`, must stay under 3.5 GB);
  - CPU %;
  - hand-check of 30 routed pages (table whole and correct, reading order, headings).

## Phase D — evaluation (`eval_retrieval.py`, FTS)
Score on quality_set_v2: old chunks, v2 (after the phase B fixes), and v2 + layout (ARs and decks). Report overall,
per type, the hard-20 split, and body-only vs header+body for v2.
- Also print the token count for the v2 pilot chunks and project it to the full corpus (the C0 cost input).
- No paid embedding.

## Rules
- Local data only, plus the two allowed downloads (PyPI is already done; HF weights).
- No paid APIs, no live DB writes. Use `connect_ro`. Raw PDFs on `D:\RealityEngine\pdfs` / `raw` are read-only.
- Outputs go to `.tmp/c1/`, `.tmp/c1b/`, plus the tracked files: `chunker_v2.py`, `layout_gpu.py`,
  `eval_retrieval.py`, tests, `quality_set_v2.jsonl`.
- Do not commit; the manager commits.
- Write a one-line progress note to `.tmp/PROGRESS_NOTES.md` after each phase.

## Acceptance checks
1. `python -m unittest reality_engine.tests.test_chunker_v2` passes, with the new tests.
2. `quality_set_v2.jsonl` has 200 rows written by you; 15 printed for audit.
3. The results table: old vs v2 vs v2+layout, overall / per type / hard-20.
4. The GPU pilot numbers above.
5. AR pilot docs/s before and after phase B.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_chunker_v2
```

## Budget
≤ 10 tool calls before the first edit; ≤ 260 total; $0 paid.

## Report
1. Phase A summary + 15 audit rows  2. Phase B changes + speed  3. Phase C GPU numbers + hand-check
4. Phase D results table  5. Token projection  6. Open problems  7. Tool calls.
