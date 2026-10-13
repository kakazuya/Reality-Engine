# Admission-test probe results (2026-10-12, OpenCode CLI session, model Muse Spark 1.3)

Goal: run the 880-piece admission test (8 models x 110 pieces) for Zen free readers.
Handbook: `tasks/OPENCODE_AR_HANDBOOK.md`. Test runs pre-exported under `reality_engine/data/ar_queue/t-<short>/`.

## 1. Custom `ar-reader-*` subagents do NOT work in this CLI session

- `ar-reader` (LongCat) on `t-longcat/0001`: failed with
  `OpenCode's free tier can only be used from within OpenCode`.
- The 8 pinned agents in `.opencode/agents/` (plural dir, not `agent/`) were never tried individually after
  that, but they use the same free-tier routing, so they are expected to fail the same way.
- Handbook fallback (built-in `general` subagent + inline reader instructions) works:
  `t-longcat/0001.out.txt` = 35 facts.

## 2. `model` parameter on the subagent call DOES route to free models (mode 2 works)

Trivial "reply ok" probes via `general` + `model: opencode/<id>`:

| model id | trivial probe |
|---|---|
| `mimo-v2.6-flash-free` | ok |
| `step-5-preview-free` | ok |
| `muse-spark-1.3-contributor-free` | ok |
| `ling-3.1-flash-free` | ok |
| `nemotron-3.5-lightning-free` | ok |
| `space-bunny-free` | ok |
| `muse-spark-1.2-contributor-free` | **ID not available** ("use the models tool") |
| `jev-1.13-free` | **ID not available** ("use the models tool") |

Models-tool lookup confirms: provider `opencode` (OpenCode Zen) lists only
`muse-spark-1.3-contributor-free` for query "muse-spark"/"spark"; query "jev" returns zero models.
So **muse12 and jev have no such Zen IDs (anymore?)**. Their agent files
(`ar-reader-muse12.md`, `ar-reader-jev.md`) and test runs (`t-muse12`, `t-jev`) point at dead IDs.
Action for Shivam: find the correct current IDs or drop these two models (leaving 6).

## 3. Real reader probes (piece 0002 of each model's own test run)

Same inline reader instructions as the smoke test, one piece each:

| run | model | result |
|---|---|---|
| `t-mimo/0002` | mimo-v2.6-flash | **100 facts written**, all lines self-validated as JSON |
| `t-step/0002` | step-5-preview | **NO output file.** Subagent narrated ("I've read the entire prompt file (1408 lines...)") instead of using the write tool |
| `t-muse13/0002` | muse-spark-1.3 | **54 facts written** |
| `t-ling/0002` | ling-3.1-flash | **NO output file.** "completed without a text response" |
| `t-nemotron/0002` | nemotron-3.5-lightning | **35 facts written** |
| `t-bunny/0002` | space-bunny | **92 facts written**, self-validated JSON |

`ar_queue status` after the probes: t-mimo/t-muse13/t-nemotron/t-bunny 1/110 answered (+ t-longcat 0001
from the smoke test = 5 files total); t-step/t-ling/t-jev/t-muse12 0/110.

Fact-count spread on the SAME piece (0002 is the same source text in every run: Cochin Shipyard FY23-24,
prompt pages 11-21): mimo 100, bunny 92, muse13 54, nemotron 35. Same order of magnitude as LongCat's 35
on piece 0001 (different piece, not comparable). The spread itself is worth scoring, not judging by eye.

## 4. Concerns for Claude to check

1. **Attribution honesty.** `ar_queue import` tags facts with the manifest's model (`zen:<id>`). Pieces read
   via `general` + `model:` param really ran on that model (the probe replies came back per-model), so
   attribution holds IF every task message pins the model. Any batch run without the pin silently
   misattributes to the manifest model. Recommend a guard: after import, sample-check nothing was written
   by the wrong model (can't tell from content — process discipline only).
2. **Step and Ling failures are instruction-following failures, not routing failures.** Step read the file
   but chatted instead of writing; Ling returned nothing. Retry once each with a sterner "no other text"
   instruction before judging. If Step keeps narrating, it fails admission on "every piece answered".
3. **Piece 0001 was never read for the 6 probed models** (probes used 0002; only t-longcat has 0001).
   Full admission still needs 0001 + 0003-0110 per model.
4. **No scoring done yet.** `test-score` was deliberately not run on partial (1/110) runs. Run it per model
   only at 110/110.
5. **Throughput math.** 6 subagents at a time, ~2-4 min per piece per model: 110 pieces x 6 models / 6 lanes
   ~= 110 waves minimum, plus retries. This exceeds one session's context; handbook says fresh session after
   ~4 batches. The run needs a session-rotation plan, or GUI-side execution.
6. **Mode 1 (GUI batch messages) and mode 3 (zen01 production via general) NOT started.** Note mode 3 as
   designed misattributes: zen01's manifest says `longcat-2.5-preview-free` but `general` in this session
   is Muse Spark 1.3. Honest options: (a) export a new run with `--model muse-spark-1.3-contributor-free`
   (passed? only 25/25 Go-route LongCat and Gemma 4 31B have passed; Zen-route Muse 1.3 has NOT passed
   admission), or (b) hold production until a Zen model passes.

## 5. Proposed next steps (needs Shivam's decision)

- [ ] Resolve muse12/jev IDs (fix agent files + manifests, or drop to 6 models).
- [ ] Retry t-step/0002 and t-ling/0002 once with strict no-narration instruction.
- [ ] Then bulk-run the 6 routable models x 110 pieces, 6 subagents at a time, across rotated sessions.
- [ ] `test-score` each at 110/110; record pass/fail lines in `tasks/ar_study/free_test/FINDINGS.md`.
- [ ] Decide mode 3 (production) only after a Zen model passes.
