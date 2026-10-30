# Task — v4 WP8: label the head surfaces with free Beam

## Goal
The deterministic mapper labels 37,204 of 62,601 head surfaces (59.43%); the gate is at least 95% with hand-checked precision of 95% or better (§H.8, §A.9). Write a resumable driver that sends the remaining 25,397 to free Beam, machine-checks the answers, and builds the map. First read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`.

## Inputs
- `reality_engine/query/v4/build_vocab.py`; its `surface`, `label`, `map` tables in `reality_engine/data/pilot/v4/v4_vocab.db` (open read-only); `reality_engine/data/pilot/v4/unmapped_head.json`.
- `tasks/arch_v4/VOCAB_PASS1.md` is out of date: true occurrences 1,815,581, head 62,601. Correct it.

## Model call
Model `beam-free` at `https://opencode.ai/zen/go/v1/chat/completions` with `OPENCODE_GO_API_KEY_2`, stable `x-opencode-session` from `go_session.session_id`, and `cost_ledger.record_usage` for every call. Free model only; if it stops being free or returns a billing error, stop and report. This task may use the network for these calls only.

## Method
- Batches of about 50 surfaces with the closed label list plus each surface's top 2 contexts. The answer must be a declared label id or `other`; anything else is rejected and retried once, then `other`.
- Measure throughput first, then use the highest concurrency that does not produce 429s; no fixed cap.
- Agreement check: 500 random head surfaces mapped twice in different batches; report agreement. Ambiguous surfaces get `other:<raw>`, because a wrong label is worse than none.
- Output `.tmp/v4_vocab_pass2.db`, keeping `source` (deterministic or beam) per row, plus a report in `tasks/arch_v4/VOCAB_PASS2.md`.

## Acceptance checks
- At least 95% of head surfaces carry an exact label, or the true number with the reason.
- A stratified sample of 100 Beam mappings written to `tasks/arch_v4/vocab_pass2_sample.md` for the controller's hand check. Do not mark precision as passed yourself; give your own reading separately.
- Interrupted and resumed once without redoing finished batches.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_vocab_claim.py -q
```
