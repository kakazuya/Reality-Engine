---
name: free-model-bakeoff
description: Pick the best FREE model for a reading job (OCR of slide images, page reading, grading) by quality then speed, without ever calling a paid model. Use when a free model stops being free, a new free model appears, or a job needs a model chosen (e.g. "Kilo stopped serving Dots free, choose another").
---

# Free-model bake-off

Inputs: the job (what the model reads and returns), N pages (default 15, >= 8 companies), candidate list.

## 1. List candidates (free only)
- `opencode models | grep -iE ":free|-free|/free"` — Kilo (`kilo/...:free`), OpenRouter (`openrouter/...:free`), Zen (`opencode/*-free`), Go (`opencode-go/*-free`).
- Zen ids ending `-free` can still be BILLED: `opencode/mimo-v2.6-flash-free` and `opencode/hy4-flash-free` are paid on Zen (Shivam 25 Nov). hy4 is free only on the Go endpoint (`https://opencode.ai/zen/go/v1`, our reader's BASE).
- Check the Zen pricing table: `python -m reality_engine.scripts.free_model_check` (add the model to `WATCHED` if absent). A model is free only when all price cells say Free.
- The `rule_guard` PreToolUse hook blocks known paid ids; it is a backstop, not the check.

## 2. Gate each candidate with ONE call
- One call on one page. Drop it if: it refuses images (for OCR jobs), errors 3 times in a row, or the call reports a non-zero cost (`opencode run --format json` / session stats). Record why it was dropped.
- Never print or copy a key; use the key OpenCode is configured with. Go key 1 only (key 2 gone 14 Nov) unless Shivam says otherwise.

## 3. Ground truth first
- Pick pages with a fixed seed (`random.Random(<seed>)`), render at 150 dpi with PyMuPDF if images are needed.
- Write truth yourself (or a non-author) BEFORE seeing model output: every printed figure with label, unit, period header.

## 4. Run and score
Same prompt for all, e.g. OCR: "Transcribe all text on this slide exactly, in reading order. Keep every number with its label, unit and column or period header. Output plain text only."
Per model: figure recall (right figure with right label / truth), precision (output figures that are on the page / output figures), invented numbers (count, separately), median s/page, errors, observed caps (rate-limit after how many calls).

## 5. Decide
Winner = highest recall with precision >= 0.95 and zero invented numbers; speed breaks ties. Name a runner-up for when the winner's cap trips.
Write `results.md` (table + recommendation) beside the pages, log the run in the run ledger (DEVELOPER_GUIDE s7), and before bulk use run the 60-row maker-checker-verifier grade (skill `checkpoint-grade`).
