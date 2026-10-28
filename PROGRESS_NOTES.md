# Progress notes — macro claim → target full run (worker 2026-10-29)

- 2026-10-29 01:20 IST — read context pack + `macro_claims.py`, `ripple.py`, tests, prior REPORT. Full-run mode added (`--all`), prose effective dates with `pit_conf`, `quote_ok` column. Full build: 21,552 claims / 43,486 targets / 9.3 s (pre-fix). Next: independent 80-claim check.
- 2026-10-29 01:55 IST — seed-20261029 stratified 80-claim sample drawn (pilot 300 excluded); hand-judged 80 claims: first pass precision 0.9940 (LB 0.9669), recall 0.9379 (LB 0.8922), 11 FN over 9 claims (alias gaps), 1 FP (segment over-broadening). Next: fix aliases.
- 2026-10-29 02:20 IST — alias + compound-string fixes; full rebuild 44,742 targets / 10.1 s; same-sample re-extract: 0 FN, +11 targets, 0 removed; precision 0.9944 / recall 1.000 (in-sample). Next: trigger matching.
- 2026-10-29 02:45 IST — trigger now honours the case's declared `policy_events.id`, else issuer + date window + topic overlap with scoring and generic-term floor. 58 cases: 48/58 (was 28/58 on the 300-claim pilot), 33/33 declared-id accuracy, 0 regressions. Next: tests + REPORT_ALL.
- 2026-10-29 03:00 IST — 35 tests pass; REPORT_ALL.md written. Remaining: final verification, report to controller.
