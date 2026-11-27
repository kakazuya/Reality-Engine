---
name: checkpoint-grade
description: Strict 60-row non-author grade of an hy4 (or any model) reading checkpoint, recorded in read_gate so bulk reading may continue or stops. Use when ops_gate says "audit checkpoint ... needs a passing grade", before any bulk run of a new reader/prompt, or for a surprise audit.
---

# Checkpoint grade (maker-checker-verifier)

Bar: >= 70% R and <= 5% W+J of 60 rows. Which checkpoints (Shivam 27 Nov, T-246): an output whose last 2 grades passed is graded every 5th checkpoint only; after any fail, every checkpoint until 2 pass in a row (`read_gate.grade_needed`; ops_gate lists only the ones needed). The author of the prompt/gates never grades or records their own work:
Eagle wrote transcript v3 + obs_speaker -> Wolf records transcript grades; Wolf owns deck + AR prompts -> Eagle or a non-author records those.

## 1. Build the pack
```
python -m reality_engine.scripts.grade_pack --db <hy4 out db> --ckpt <db>.audit/ckpt_NNNN.jsonl \
  --stores-glob "C:/RealityEngine/tg_build/universe_fy27/c*/c*.db" --record-type number|statement \
  --seed <new seed> --out <dir>/pack.jsonl          # writes pack_part00/_part01 (2 x 30)
```
Checkpoint rows first, then a seeded fill (one company per row where possible, <= 2 rows per doc). Touch `ckpt_NNNN.grading.md` to mark a grade in progress.

## 2. Grade
- Grader, best first (Shivam 26 Nov): agy `gemini-4-hydrogen-high` (smarter than DeepSeek max and Sonnet medium; use for new doc types, re-grades after a fail, jumbled/OCR pages); a read-only dsh worker off-peak for routine checkpoints; or two Sonnet subagents (`model: sonnet`), 30 rows each, < 100k context. Rubric `docs/grading/number_rubric.md` or `statement_rubric.md`.
- An agy grader brief must contain the line `permission: read-only` (ops_gate then does not count it as a code worker); Hydrogen reads absolute C:/RealityEngine pack paths with read_file.
- Graders recompute every figure (totals, growth %, QoQ/YoY columns) and read the previous page for headers. Lenient reads overstate (89% vs 80% strict).
- Output per row: R / P / W / J + one-line reason; CSVs `grades_part00.csv`, `grades_part01.csv`.

## 3. Record
```
python -m reality_engine.v2.read_gate grade --ckpt <ckpt> --verdict pass|fail --reviewer <name> --counts R/P/W/J
```
The author of the FIX that a re-grade tests also counts as author: a pass after Wolf's fix is recorded by Eagle (and vice versa). A fail needs `ckpt_NNNN.fix.md` first: each W/J kind with one example row, the structural cause, the gate or prompt fix. Delete the `.grading.md` marker after recording.

## 4. After a fail
Fix = structural rule (never per company), measured on a COPY: count changed verified rows, 20 random changed rows (seed 7), 0 graded R rows may change, stop if a rule changes > 3% of verified rows. Then `--recheck` a copy, fresh grade by a non-author, then swap + load (skill `hy4-store-load`).

Write the grade to `D:/RealityEngine/t242/grades/<set>_ckptNNNN_<grader>.md` (counts, W/J rows, P kinds) and a worker_reviews.jsonl row.
