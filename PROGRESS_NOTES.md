# Progress notes — v4 truth grade (worker 20261031T002846Z-a3be41ad)

- 06:10 — Read the context pack, the gate review (idea 1), the sample-40 doc and the
  common rules. Confirmed the raw v4 output was absent and the v4 pilot stores exist in
  the main data root (`reality_engine/data/pilot/v4`), so a fresh run is required.
- 06:20 — `gate_run.py v4 --fresh` completed: 2,681 cases, 279 s, **273 strict (10.2%)**
  on the current checkout (the write-up quotes 221 / 8.2% for the same grader — store/
  executor drift, to be reported).
- 06:25 — Rubric cheap test built (`tasks/answer_bench/truth_grade.py --rubric40`):
  exact agreement 8/40, it certifies 0/3 hand-RIGHT rows, cannot judge 8/40. Rubric
  scoring is NOT usable as the truth metric.
- 06:35 — New grader `tasks/answer_bench/truth_grade.py`: eight named answer-shape
  checks (question text only), rubric scorer, truth verdict, stratified panel, Wilson.
  `gate_run.py v4truth` prints contract / contract+shape / truth and writes
  `tasks/arch_v4/TRUTH_GRADE_2026-10-31.md` + `tasks/arch_v4/TRUTH_PANEL_2026-10-31.jsonl`.
- 06:45 — Panel hand evidence: 3/3 hand-RIGHT rows pass every shape check; two false
  RIGHTs found by the panel and now failed by new checks (MB0275#MS: part answers for
  another ISIN, share count 20,000 vs 18.75 cr; MB0306#L: "YTD high" taken over one row,
  1,863.6 vs the held 2,046.9 on 2026-07-31 — verified against the live store with
  `price_extreme` and `holding`).
- 06:50 — Docs corrected: row #4's Vi PAT is a real stored row (not a store defect), and
  the sample's own counts (8 PARTIAL / 29 WRONG, not 7/30) in `GATE_V4_SAMPLE40.md` and
  in the `v4report` generator.
- 07:00 — Final run (fresh seed 20261032, written into every fresh row): contract 273
  (10.2%), contract+shape 169 (6.3%), truth 0.16% [0.04, 0.57] (2 of 127 answered rows
  RIGHT); re-ran the same seed and got the same numbers, so the panel is reproducible.
  Panel RIGHT rows this run are MB0303#L and MB0005#MI (the two hand-RIGHT shapes).
  Tests: 55 passed (`test_v4_truth_grade.py` + `test_v4_run.py`).
- Done. Blocker remains only the free-Beam judge (no key); nothing else is blocked.

