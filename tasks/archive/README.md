# tasks/archive — moved docs, why, and what replaces them

Moved on 2026-10-31 by the stale-docs audit (`tasks/dsh_tasks/DOCS_STALE_AUDIT_2026-10-31.md`). Nothing here is deleted; every file was moved with `git mv`. The live state is `tasks/STATE.md`; the live work queue is `tasks/handoff/QUEUE_2026-10-31.md`.

| Moved file | Why it moved | What replaces it |
|---|---|---|
| `tasks/archive/HANDOFF_2026-10-29.md` | Old hand-off: told the next session to adopt workers whose leases had expired, restart an old F&O fetch and read the 1.0% gate. | `tasks/STATE.md`, `tasks/handoff/QUEUE_2026-10-31.md` |
| `tasks/archive/STATE_FOR_ANY_AI_2026-10-29.md` | Old state snapshot that called 1.0% "the true number". | `tasks/STATE.md` (13.5% contract strict, 0.00% read grade) |
| `tasks/archive/LOCAL_HAIKU_SESSION.md` | 15 Oct session brief for the deck Haiku batches; batch 7 was done and imported. | `tasks/STATE.md` |
| `tasks/archive/HARD_AR_HAIKU_SESSION.md` | 16 Oct session brief for hard annual-report pages; the work finished and the queue lives in code. | `reality_engine/scripts/ar_queue.py`, `tasks/STATE.md` |
| `tasks/archive/handoff/HANDOFF_2026-10-31.md` | 00:20/05:05 takeover hand-off ("read this first"): the workers it said to adopt, the label-promotion fix and its next steps are done. | `tasks/handoff/QUEUE_2026-10-31.md`, `tasks/STATE.md` |
| `tasks/archive/handoff/OVERNIGHT_2026-10-30.md` | 30 Oct overnight hand-off carrying the obsolete 2.3% gate and a "check if section 3 is empty" order. | `tasks/STATE.md`, `tasks/handoff/QUEUE_2026-10-31.md` |
| `tasks/archive/handoff/CHART_PASS_2026-10-24.md` | Hand-off for the chart/vision pass; the gate finished, the bulk run never started and is not queued. | `tasks/STATE.md` |
| `tasks/archive/handoff/CONCALL_RUNNER_2026-10-24.md` | Hand-off for the concall-runner patch on `wip/concall-runner-2026-10-24`; the patch is in the live runner. | `reality_engine/scripts/concall_deepseek.py`, `tasks/STATE.md` |
| `tasks/archive/handoff/LOCAL_OCR_PILOT_2026-10-24.md` | Hand-off for a stopped 24 Oct OCR pilot with no verdict; the later HP OCR benchmark decides this. | `tasks/efficiency/HP_ACCEL_BENCH_2026-10-31.md`, `tasks/STATE.md` |
| `tasks/archive/optimizations/HANDOFF_2026-10-25.md` | 25 Oct hand-off for the retrieval/learning session; its G0–G5 and C1–C4 decisions are historical. | `tasks/optimizations/MORNING_REPORT.md`, `tasks/worker_context/CONTEXT.md` |
| `tasks/archive/optimizations/HANDOFF_2026-10-26.md` | 26 Oct overnight hand-off telling the next session to renew workers and run a wide test that never ran. | `tasks/STATE.md` |
| `tasks/archive/dsh_tasks/CODE_INTEL_FRESH_CLI_2026-10-30.md` | Brief for finished work: fresh code-intel lookups and the CLI merged (`42bf8cb`). | `plugins/code-intel/ci.py`, `tasks/STATE.md` |
| `tasks/archive/dsh_tasks/CONTINUE_V4_SHP_XBRL_2026-10-31.md` | Continuation brief; the fetch and install finished (2,577 rows). | `tasks/arch_v4/SHP_XBRL_PILOT_REPORT_2026-10-31.md` |
| `tasks/archive/dsh_tasks/CONTINUE_V4_STUDY_OPERATOR_2026-10-31.md` | Continuation brief; the `near_high` operator merged (`dddc52a`). | `tasks/arch_v4/STUDY_OPERATOR_TEST_2026-10-31.md` |
| `tasks/archive/dsh_tasks/EFFICIENCY_FIXES_2_2026-10-31.md` | Brief for finished work: efficiency rounds 1–2 merged (`2287fff`, `3126d2c`). | `tasks/efficiency/FIX_TRACKER_2026-10-31.md` |
| `tasks/archive/dsh_tasks/GPU_BENCH_2026-10-30.md` | Brief for finished work: the GPU/CPU benchmark merged. | `tasks/arch_v4/bench_gpu.md` |
| `tasks/archive/dsh_tasks/HP_OCR_ENGINES_2026-10-31.md` | Brief for finished work: OCR engines tested and merged (`09b242d`). | `tasks/efficiency/HP_ACCEL_BENCH_2026-10-31.md` |
| `tasks/archive/dsh_tasks/HP_RUNNER_AND_ACCEL_2026-10-31.md` | Brief for finished work: the HP runner is live and the accelerator bench is written. | `reality_engine/scripts/hp_worker.py`, `tasks/efficiency/HP_ACCEL_BENCH_2026-10-31.md` |
| `tasks/archive/dsh_tasks/HP_WORKERS_IN_MCP_2026-10-31.md` | Brief for finished work: HP workers show and run from the MCP; only the controller-side restart remains. | `tasks/handoff/QUEUE_2026-10-31.md` |
| `tasks/archive/dsh_tasks/HP_WORKER_HOST_2026-10-31.md` | Brief for finished work: the HP hosted real workers end to end (§10 of the bench). | `tasks/efficiency/HP_ACCEL_BENCH_2026-10-31.md` |
| `tasks/archive/dsh_tasks/NID_TRIAGE_2026-10-30.md` | Brief for finished work: NID triage merged (`d1ad769`). | `tasks/arch_v4/NID_TRIAGE.md` |
| `tasks/archive/dsh_tasks/V4_1_REVISION_2026-10-30.md` | Brief for finished work: the v4.1 revision merged (`f2a0c04`). | `tasks/arch_v4/QUERY_V4_DESIGN.md` |
| `tasks/archive/dsh_tasks/V4_INSTANCE_TEXT_AND_ANSWER_SHAPE_2026-10-31.md` | Brief for finished work: the shape checks are in the truth grade. | `tasks/answer_bench/truth_grade.py`, `tasks/arch_v4/TRUTH_GRADE_2026-10-31.md` |
| `tasks/archive/dsh_tasks/V4_INTEGRATE_GATE_2026-10-31.md` | Brief for finished work: the first v4 gate run is reported. | `tasks/arch_v4/GATE_V4_2026-10-31.md` |
| `tasks/archive/dsh_tasks/V4_LABEL_PROMOTION_2026-10-31.md` | Brief for finished work: label promotion merged (`3329bfa`). | `tasks/arch_v4/VOCAB_PASS2.md` |
| `tasks/archive/dsh_tasks/V4_LEXICON_GROWTH_2026-10-31.md` | Brief for finished work: WP1b lexicon growth measured (77.6% recall, 84.8% precision). | `tasks/arch_v4/QUERY_V4_DESIGN.md` |
| `tasks/archive/dsh_tasks/V4_LOOKUP_REPAIR_2026-10-31.md` | Brief for finished work: lookup repair merged (`8f380d3`). | `tasks/STATE.md` |
| `tasks/archive/dsh_tasks/V4_PANEL_READ_GRADE_2026-10-31.md` | Brief for finished work: the read grade was produced. | `tasks/arch_v4/TRUTH_READ_GRADE_2026-10-31.md` |
| `tasks/archive/dsh_tasks/V4_PILOT60_HISTORY_CHUNKS_2026-10-31.md` | Brief for finished work: pilot-60 history chunks merged (`ee35098`). | `tasks/STATE.md` |
| `tasks/archive/dsh_tasks/V4_PREMISE_AUDIT_2026-10-31.md` | Brief for finished work: premise audit merged (`41ccdf3`). | `tasks/pilot60/PREMISE_AUDIT_2026-10-31.jsonl` |
| `tasks/archive/dsh_tasks/V4_QUERY_DESIGN_2026-10-29.md` | Brief for finished work: the v4 design merged (`6ec90e8`). | `tasks/arch_v4/QUERY_V4_DESIGN.md` |
| `tasks/archive/dsh_tasks/V4_READER_TEST_2026-10-31.md` | Brief for finished work: the reader test merged (`e943d4c`). | `tasks/arch_v4/READER_TEST_2026-10-31.md` |
| `tasks/archive/dsh_tasks/V4_REVAMPED_PLAN_2026-10-31.md` | Brief for finished work: the revamped plan merged (`785d519`). | `tasks/arch_v4/REVAMPED_PLAN_2026-10-31.md` |
| `tasks/archive/dsh_tasks/V4_SHP_XBRL_PILOT_2026-10-31.md` | Brief for finished work: shareholding XBRL merged (`4516a7c`) and installed (`d2914d3`). | `tasks/arch_v4/SHP_XBRL_PILOT_REPORT_2026-10-31.md` |
| `tasks/archive/dsh_tasks/V4_STUDY_OPERATOR_TEST_2026-10-31.md` | Brief for finished work: the `near_high` operator merged (`dddc52a`). | `tasks/arch_v4/STUDY_OPERATOR_TEST_2026-10-31.md` |
| `tasks/archive/dsh_tasks/V4_TRUTH_GRADER_2026-10-31.md` | Brief for finished work: the truth grade merged (`b30175e`). | `tasks/arch_v4/TRUTH_GRADE_2026-10-31.md` |
| `tasks/archive/dsh_tasks/V4_WP2A_FACT_VIEW_2026-10-31.md` | Brief for finished work: the fact view and entity sets are on main. | `reality_engine/query/v4/build_membership.py` |
| `tasks/archive/dsh_tasks/V4_WP2B_VOCAB_CLAIM_2026-10-31.md` | Brief for finished work: vocabulary, claim and own estimates are on main. | `reality_engine/query/v4/build_vocab.py` |
| `tasks/archive/dsh_tasks/V4_WP2C_MISSING_ATOMS_2026-10-31.md` | Brief for finished work: missing atoms merged (`dc693c8`). | `tasks/STATE.md` |
| `tasks/archive/dsh_tasks/V4_WP3_DECOMPOSER_2026-10-31.md` | Brief for finished work: the decomposer is on main. | `reality_engine/query/v4/decompose.py` |
| `tasks/archive/dsh_tasks/V4_WP4_EXECUTOR_2026-10-31.md` | Brief for finished work: the executor, renderer and grader are on main. | `reality_engine/query/v4/execute.py` |

Pre-existing in this folder (not moved by this audit): `tasks/archive/STATE_until_2026-10-27.md` is the replaced 2026-10-24→27 state log; `tasks/STATE.md` is the live state.
