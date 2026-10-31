# Revamped plan to the 95% gate — 31 Oct 2026

> **Later result:** the baseline numbers and every "running" label below predate the 31 Oct 13:00 run. Current gate: 361/2,681 = 13.5% contract strict, 246/2,681 = 9.2% with shape checks, 0.00% read (`tasks/STATE.md`). The P0–P8 plan is unchanged.

**Labels.** M = measured in the named file. E = estimate from it, at the confidence stated; no estimate has been upgraded. "Reviewer-measured" means the independent reviewer's measurement in `GATE95_REVIEW_2026-10-31.md`, not mine. Numbers are inline-labelled or named in the Provenance footer. Worker-hours are finished-worker hours (`QUERY_V4_DESIGN.md` §H.11), excluding hand grading and controller review. §1–§7 are the plan; §8 is the audit of the review and can be read last.

## 1. The situation in six lines

1. The gate is 221/2,681 strict = **8.2%** (M: `GATE_V4_2026-10-31.md` §1); the hand check is 3/40 RIGHT = **7.5%** of answered rows, about **0.6% of the bank** (M: `GATE_V4_SAMPLE40.md`; E: 0.2–1.6%).
2. 30 of those 40 answered rows are wrong; the contract count measures shape, not truth (M: `GATE_V4_SAMPLE40.md`).
3. **34.6%** of rows name a company outside the pilot or do not resolve (927; reviewer-measured); **23–28%** are instances whose premise is false (E); the buckets may overlap, so the review's 57–62% is not a precise ceiling.
4. No grader reads `required_steps` (743), `forbidden` (743), `ground_truth` (203) or `required_evidence` (M: grep in this checkout; counts M: `MASTER_BANK.jsonl`), so the bank's gold cannot correct the contract count.
5. The rest is lookup loss and unread data: **15.3%** unbuilt atom or coverage hole, **14.8%** text only, **7.7%** both missing, **5.8%** blank `as_of` (M: reviewer's row classification).
6. **95% on the bank as it stands is not reachable**: at least 34.6% is outside the pilot by construction (M) and the false-premise class is large (E); the golden rule forbids full chunking or re-embedding before the gate (`AGENTS.md`), so 60 pilot names bind the scope.

## 2. Old plan vs new plan

| Move | Area | Old plan | New plan | Why |
|---|---|---|---|---|
| Stays | Golden rule; pilot/PIT/typed NID/proxy; WP2c; WP7/WP9/WP10 behind the gate; HP infra | As written | Unchanged; WP2c finishes, HP finishes and stops | Binding or not the blocker |
| Changes | Gate measure | 30% strict checkpoint (`tasks/archive/handoff/HANDOFF_2026-10-31.md:16`), then 95% | Truth panel (150 + 40), contract and shape counts beside it; 30% retired (D1); decomposer recall/precision and `--regress` become diagnostics | 3/40 RIGHT; 75% of answered rows wrong; the old measures see concept names, not truth |
| Changes | Order | WP2c → WP3/WP4 → blind split/WP6 → gate | Truth grade + lookup repair first; reader test; scalar study; instance/scope; WP6/WP8/backtest delayed | 31% of failed rows lose held data; contract is blind to operator and window |
| Changes | Lookup | Inside executor work | Own running package (P1) | 262 blank `as_of`; 87–93 dim rows; 21/60 names with no holdings |
| Changes | Reader | Later design/build | Kill-or-keep test now (P2); build only if D5 | 97/1,116 text parts pass even the contract; 108,078 pilot chunks unread |
| Changes | Scalar collapse | On the WP list | Next after P1, one-operator test first (P4) | `value_at` is 2,771/3,778 parts; `rule` 0/81 |
| Changes | Instances | Not a package | Text fix running; premise repair and `premise_false` need D2 (P5) | 180/1,551 stock instances identical to their parent (M); 34/38 checkable premises false |
| Stops | WP6 (24–28 h), WP8 (6–8 h), blind split/Beam lexicon, proxy pre-read, OCR 1,073 | Next/queued | WP6 delay; WP8 finish then stop; blind split and proxy delay; OCR stops for the gate | Edge table 0 rows and 46 `walk`/set parts; labels do not fix a missing topic; 73/101 vs 7.5%; proxy 0 direct and ≤2.8 points; OCR is pre-2024 scans |
| Rejected | Vi sanity rule; near-duplicate merge | Proposed | Rejected | Vi +34,552 cr matches the filing; near-duplicates merge only 31/1,073 parents |

## 3. Work packages, in order

P0–P3 run now. P4 starts when P1 merges. P5–P7 wait for the decision named. P8 runs after every merge. Truth-point ranges are E, overlap, and are **not additive**.

| # | Package (status) | Goal and dependency | Worker-hours (E) | Machine | Truth points (E) | Kill check | Measure of done |
|---|---|---|---|---|---|---|---|
| P0 | Truth instrument, `V4_TRUTH_GRADER` (running) | Truth grade, 150 + 40 panel, shape checks; no dependency | 3–5 | MSI | 0 direct; it measures | Rubric agrees with hand check on <30/40 → panel only | 3 numbers, panel, named failures, RIGHT wrongly failed 0/listed |
| P1 | Lookup repair, `V4_LOOKUP_REPAIR` (running) | `as_of`, dims, dates, YTD, CAGR, holdings via ISIN history; P0 to measure, D5 item 1 | 6–9 | MSI | +6–12 | 20-row hand grade after items 1–2 <8 RIGHT → stop after item 2; test holdings separately | Before/after per item, PIT 0, tests |
| P2 | Reader test, `V4_READER_TEST` (running) | 40 passage questions, FTS + Beam, verbatim quote; P0 grading | 1–4 | MSI (HP if pilot stores are synced) | 0 now; enables +8–15 in P7 | <50% RIGHT → kill the model reader | 40 graded, list pre-committed, retrieval/reading split, tests |
| P3 | WP2c missing atoms (in flight) | Banking, corp action, CWIP/CFO and quarterly fix; no dependency | 0 new | MSI | +0–3, not separately sized | <1 truth point after merge → stop the remaining atom build | Atoms built, panel re-run, PIT 0 |
| P4 | Scalar collapse + study operators | Judgement → typed unmapped; 5 studies; P1 merged | 6–10 | MSI | +3–6 | One operator answers <half of MB1044/MB1047 → stop (proposed) | Typed asks, operators, more rules (3 of 14 today); contract may fall |
| P5 | Instance repair + `premise_false` | Rule-check premises, withdraw with reason, own column; D2 + running text fix | 4–6 | MSI | +5–12; ceiling +23–28 | Shivam calls <20 of 30 flagged rows ill-posed → drop | Every row listed; old count visible; `premise_false` outside `real_answered` |
| P6 | Scope and set answers | Full denominator, parent column, set queries, scope stated; D3 + D4 | 6–12 | MSI | +6–15; ceiling +34 | 20 set questions by hand; if a scoped pilot answer is not acceptable, only widening remains | 2,681 unchanged; parent column; scope named; no silent exclusion |
| P7 | Reader build (conditional) | Quote-verified reader; numbers from quote; D5 + P2 pass | 4–6 | MSI/HP | +8–15 (overlaps P2) | 40-question audit <50% RIGHT → kill | Verbatim quote; no model number; hand audit each run |
| P8 | Re-runs and final panel | Re-measure after merges; weights, bank hash, confidence rule; P0–P7 | 1–2 per run | MSI | — | Panel misses M1/M2 after two merged WPs → re-plan, never lower the target | 3 numbers, weights, bank hash, Wilson interval |

## 4. Milestones as truth-panel numbers

Replace the 30% strict checkpoint (M: `tasks/archive/handoff/HANDOFF_2026-10-31.md:16`; `GATE_V4_SAMPLE40.md:98–101`) with the truth panel: 150 fixed rows, stratified by bucket, family and answer shape and weighted to the bank, plus 40 fresh rows per run from a pre-registered seed. The headline is the **full 2,681-row truth rate**; a second column gives the in-scope rate with exclusions listed; contract strict stays printed. The panel steers but cannot alone certify 95%: 143/150 RIGHT gives a Wilson 95% lower bound of about 91% (calculated), so the final gate must pre-declare a point estimate or a lower bound and use a larger sample or a validated judge.

| Milestone | Trigger | Proposed full-bank truth | Confidence | If missed |
|---|---|---|---|---|
| M0 Baseline | P0 lands | 0.2–1.6% (E, from 3/40) | High that the range holds | >2% → panel suspect |
| M1 Lookup | P1 + P3 merge | ≥5% (E 5–12) | Medium-low | <3% → stop P1's remainder |
| M2 Studies | P4 merge | ≥8% (E 8–18) | Low | <5% → stop P4 |
| M3 Instances and reader | P5 + P2/P7 | ≥15% (E 15–35) | Very low | <10% → kill the reader, revisit D2; 10–15% → continue only if P2 passed |
| M4 Scope | P6 | ≥30% (E 25–50) | Very low | <25% → D3/D4 ruling before more work; 25–30% → finish P6, then decide |
| Final 95% | Full build, D3/D4 ruled | 95% on the full bank; if the unanswerable class cannot be repaired, only Shivam can rule on a different denominator (he has said no re-scope) | Not promised | If the panel plateaus, return to D3/D4; do not re-label rows to pass |

These are proposed for approval (D1). They are not additive; each is measured after the named packages merge. A missed milestone triggers its kill rule, not a lower target.

## 5. Shivam's decisions

| # | Decision question | Options | Recommendation | Cost of waiting | Blocks |
|---|---|---|---|---|---|
| D1 | Do you approve replacing the 30% strict checkpoint with a truth-panel target (150 fixed + 40 fresh), with contract and shape counts printed beside it? | (a) Truth gates, contract is diagnostic; (b) keep 30% strict; (c) both must pass | (a), with M1–M4 and a pre-declared final confidence rule | Work stays steered by a 7.5%-precision number | P0/P8 acceptance and every milestone |
| D2 | Do you approve repairing instance premises and adding a typed `premise_false` answer counted in its own column, never in `real_answered`? | (a) Repair + withdraw + own column; (b) text fix and withdrawal only (running); (c) no change | (a); every changed row listed, old count and denominator kept | 23–28% of rows stay unanswerable; the running text fix only fixes names | P5 |
| D3 | Do we keep the full 2,681-row denominator and report parent-level truth apart, or count parents through their instances? | (a) Full denominator + parent column; (b) parent-through-instance count; (c) parent-only for set asks | (a). This is **not** a re-scope: no row leaves the denominator. He has said no re-scope (`DECISION_LOG.md:329`, as cited in the brief; the log is not in this checkout) | 489 non-stock parents (M) are not stock lookups; set queries cover some, the rest stay visible; the 95% ceiling stays | P6 and the final gate definition |
| D4 | Do we widen the structured pilot beyond 60 names, and if so to which companies and at what cost? | (a) Keep 60 until the pilot gate passes; (b) widen structured data only; (c) widen structured + documents | (a) now; (b) only after D3 and a sized cost; no full chunking or embedding before the gate | 34.6% of rows stay outside the pilot; if 95% must be on the full bank, widening is unavoidable eventually | P6 and the 95% ceiling |
| D5 | Should a blank `as_of` default to the latest complete market date in the pilot store, printed as an assumption, or stay NID? | Latest complete session / a fixed snapshot date (for example 2026-10-19) / NID | Latest complete date, one named constant, printed in every affected answer | 262 rows stay at 0 answered (142 parents + 114 stock + 6 peer-set, M) | P1 item 1 (running with a provisional default) |
| D6 | If the reader test reaches ≥50% RIGHT, do we allow a quote-verified reader to select passages and return quotes, with numbers only from the quote? | (a) Yes, quote-verified and hand-audited; (b) retrieval with quotes only; (c) kill | (a) only if the test passes and the verbatim check holds; otherwise (b) | 14.8% text-only and 7.7% both-missing rows stay unanswered; 97/1,116 text parts pass even the contract | P7 |

The review's scope counts do not reproduce from the bank files (see §8). Re-derive them before D3/D4: measured here are 517 stock parents × 3 = 1,551 stock instances, 57 peer-set instances, 574 parents with any instance, 499 with none, 489 non-stock parents, and 338 distinct entity names (M: `MASTER_BANK.jsonl`, `INSTANCES.jsonl`).

## 6. Risks

| Risk | How it would show up | How the number stays honest |
|---|---|---|
| Denominator or scope looks shrunk | A row leaves the gate, or a theme answer covers 60 names | Full-bank truth is the headline; the in-scope rate is a second column; every changed/withdrawn row is listed; the old count stays visible; Shivam approves each class; buckets stay balanced; the scope is printed in the answer |
| Contract rises faster than truth | Lookup repair lifts strict with little truth gain | Truth panel first; contract is diagnostic; no package is "done" on contract alone |
| Panel overfits, or the judge is lenient | Rows used to build also grade, or the judge passes what the panel fails | 150 fixed + 40 fresh, pre-registered seeds; panel rows not used in development; bank hash frozen; judge only after ≥90% agreement on unseen rows; hand panel is the authority |
| A wrong reading with a real quote | A passage is real but answers another question | Verbatim quote check; numbers only from the quote; hand audit each run; kill rule |
| PIT leak in lookup repair | A post-`as_of` filing enters an answer | `known_at` from the filing record, never the crawl date; PIT breaches must stay 0; holdings checked on filing date |
| Baseline moves under the plan | WP2c or the running instance-text job changes the bank before a measurement | Freeze a bank version; re-baseline after each merge; report withdrawals and additions separately |
| Rubric coverage is partial | 330 parents have no `required_steps`; 870 have no `ground_truth` (derived: 1,073 − 743 and 1,073 − 203) | Hand-grade those rows; if the rubric agrees with the hand check on <30/40, use the panel only |
| Hand-grading capacity | 150 + 40 rows are not graded, so the gate stalls | Name the grader and weekly hours before P0 finishes; the panel is the critical path |

## 7. What this plan cannot promise

- **95% on the bank as it stands.** At least 34.6% is outside the pilot (M); the false-premise class is large (E); the two may overlap.
- **A date for 95%.** It depends on D2–D4 and on a reader result that does not exist yet.
- **The top of the ranges.** The review's trajectory is low confidence and its package points overlap.
- **That the reader works at scale,** or that the free Beam tier holds.
- **That widening is affordable.** Chunking for the named companies is unsized.
- **That 150 rows certify 95%.** The final gate needs a pre-declared confidence rule and a larger sample or a validated judge.
- **That the rubric covers the bank.** 743/1,073 parents have `required_steps` and 203 have `ground_truth` (M); the rest need hand grading.
- **Any full chunking or re-embedding before the gate.** The golden rule is unchanged.

## 8. What the review got wrong or missed

I checked the file-level claims: the 743/743/203 counts and the no-grader grep (M); the 262 blank `as_of` composition (142 parents + 114 stock + 6 peer-set, M); `instantiate.py:162–214` rewrites only names and symbols; `execute.py:431/626` cut on `as_of` and `:672` logs `chunks_v3` as unread; `run.py:216–233` takes the case entity; `build_claim.py` reads only `cc_items`; and the bank/instance counts below. I did **not** check store values, Beam/reader results, or the 370 MB run: no DB is mounted for this job.

1. **The scope counts do not reproduce.** The review says 529 parents with instances, 371 without, about 394 distinct names. From `MASTER_BANK.jsonl` and `INSTANCES.jsonl` (M): 517 stock parents × 3 = 1,551 stock instances; 57 peer-set instances; 574 parents with any instance (517 stock + 57 peer-only); 499 with none; 489 non-stock parents; 338 distinct entity names. Re-derive before D3/D4.
2. **The lookup numbers do not close.** The review's table says 87 rows were removed by a dim or window filter; its traces say 80 exchange-only + 13 `basis=adjusted` = 93 (reviewer-measured), with 87 possible if six rows carry both. And the kill test at item 3 stops before named dates, YTD, CAGR and the 21/60 holdings gap (items 4–7) — the fixes that carry much of the 6–12 point estimate. Split the test: items 1–2 in one, holdings in another.
3. **The 57–62% headline may double count.** The review adds 34.6% outside-pilot (reviewer-measured) to 23–28% false premise (E). Its own hand sample mixes "clearly false" with "naming another company" (`GATE95...:132`), which overlaps the outside-pilot bucket, and the cross-tab is not shown. Treat 34.6% as measured and the rest as a large unquantified class.
4. **A 150-row panel cannot certify 95% alone.** At 143/150 RIGHT the Wilson 95% lower bound is about 91% (calculated). The final gate needs about 148/150 or a larger sample, or a judge validated at the required precision. The review's 150 + 40 is a steering instrument, not a certificate.
5. **Running jobs move the baseline before the plan's measurements.** `QUEUE_2026-10-31.md:8` is fixing instance text and may withdraw non-instantiable rows; line 9 has WP2c continuing missing atoms. The review's numbers pre-date both jobs; it says it did not inspect WP2c's DB (`GATE95...:220`). Freeze a bank hash, re-baseline after each merge, and do not attribute WP2c's gains to lookup repair.
6. **The 57 peer-set instances are unlabelled in the gate breakdown.** `GATE_V4_2026-10-31.md` §3 calls them "instances, no label" (57); `INSTANCES.jsonl` has `kind=peer_set` for exactly 57. They are set/peer questions, not stock questions; track them as their own shape.

The review's Vi correction is right, but the fix target is `GATE_V4_SAMPLE40.md:28` ("sign/concept error"), not `GATE_V4_2026-10-31.md`, which never mentions Vi. The truth-grader brief's instruction to fix "that claim in `GATE_V4`" is stale; fix SAMPLE40 #4 and the brief.

---

**Provenance.** M: `GATE_V4_2026-10-31.md` §1–§3, §8; `GATE_V4_SAMPLE40.md` counts; `MASTER_BANK.jsonl` (1,073 parents, 743 `required_steps`, 743 `forbidden`, 203 `ground_truth`, 142 blank `as_of`, 584 stock / 489 non-stock); `INSTANCES.jsonl` (2,098 rows: 1,551 stock, 490 as-is, 57 peer-set; 610 blank `as_of`; 180 identical; 574 parents, 517 stock, 499 with no instance, 338 names); grep in `reality_engine/query/v4/` and `grade_v1.py`/`grade_v2.py`; `instantiate.py:162–214`; `execute.py:431,626,672`; `run.py:216–233`; `build_claim.py:3,162`. E: `GATE95_REVIEW_2026-10-31.md` (150/40, 34.6%, 23–28%, 34/38, 87, 80+13, 262, 21/60, 97/1,116, 108,078, 73/101, 2,771/3,778, 0/81, 31/1,073, 46, 2.8, 6–12, 5–12, 8–15, 3–6, 6–15, 4–6, 6–10, 5–8, 3–5); `QUERY_V4_DESIGN.md` §H.11 (24–28, 6–8). Not checked: stores, Beam/reader, the 370 MB run, `DECISION_LOG.md` (not in this checkout).
