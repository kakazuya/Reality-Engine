# Progress — v4.2 (fold Shivam's answers, NID re-triage, GPU results)

`DSH_WORKER_PROGRESS_NOTES` was unset in this session, so the notes live here, in the session
workspace root.

## 2026-10-30 — milestone 1: inputs read, measurements taken
- Read the context pack, `QUERY_V4_DESIGN.md` (1,530 lines), `bench_screen.py`, `bench_gpu.md`,
  `NID_TRIAGE.md` and `nid_triage.json` (150 cases, 74 with `verdict=b`).
- Verified the §B.6 archive claim: `D:\RealityEngine\raw\index_constituents` holds exactly 3
  files, all `*_current.csv`, written 2026-10-20. No history. The v4.1 claim was false.
- Measured worker effort from `plugins/dsh-worker/runtime/jobs/*/status.json`: 202 finished
  jobs, median 0.31 h, p90 1.33 h, 113.9 worker-hours total; arch_v4 anchors via `brief.md`
  matching — v4 design 0.65 h, v4.1 revision 0.74 h, NID triage 0.31 h, GPU bench 1.58 h.
- Next: fix `bench_screen.py`, write `nid_retriage.py`, then revise the design.

## 2026-10-30 — milestone 2: code fixes done
- `bench_screen.py`: drivers standardised (they were raw levels up to 55,385, so the "screen"
  was a cross-product); `screen_corr` returns a true Pearson correlation and asserts
  `|r| <= 1`; residualisation now uses market + index-group columns as the declared factors
  (it used the leading commodity columns, which are drivers); three FDR nulls measured
  (block / per-pair / self-membership dropped) and the block null adopted.
- `nid_retriage.py` written and run: 74 logs in `nid_search_logs/`, 32 of 74 tickets show
  candidate real evidence (30 structured + 2 own-document), 42 corpus-only.
- Next: the design revision (v4.2 changes table + every section the six decisions touch).

## 2026-10-30 — milestone 3: design revised, checks green
- `QUERY_V4_DESIGN.md` revised: v4.2 changes section, per-atom in-line band, proxy as last
  resort + four-step triage, §B.6 rewritten with the own-PIT label and the pilot AR backfill,
  §E.5 marked PENDING with four proposals, `broker_charges` + seeded rate cards, §F.8 rewritten
  from a thesis to a measured result, §H.11 worker-hours, open questions reduced to §E.5 only.
- `build_concept_registry.py --check` PASS (897/150/26, byte-identical rebuild).
  `bench_screen.py` exit 0 with all three acceptance targets PASS. `nid_retriage.py --check`
  PASS. No blockers.
