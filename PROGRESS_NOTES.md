# Progress notes — pilot ADD3 raw fetch + NSDL + Vahan (2026-11-01)

- 01:38 CONTEXT pack read. Edits: `fetch_pilot60_history.py` gained `--universe` and
  `--window-start/--window-end` (defaults unchanged); `fetch_nsdl_raw.py` now retries the
  fortnight listing and each file with backoff.
- 01:39 Created `tasks/pilot60/UNIVERSE_ADD3.csv` (APOLLOHOSP, KIMS, OLAELEC) — the file
  named in the brief did not exist in the repo or the main checkout.
- 01:45–01:53 ADD3 history fetch, two windows: 1,270 PDFs ok, 41 text-only announcements,
  0 fetch errors (window 1: 631 ok/33 text-only; window 2: 639 ok/8 text-only).
- 01:36 NSDL: only one fortnight is listed after 30 Sep 2026 —
  `FIIInvestSector_Oct152026.html` (328,945 B); loaded 2,901 cells with
  `load_market_raw --sources nsdl_fpi_fortnight`. The 31 Oct file is not published yet.
- 02:05 Vahan: the legacy JSF dashboard (`vahan4dashboard`) refuses every "Month Wise"
  refresh with a server-side `javax.faces.el.EvaluationException: Not supported yet.`
  and exposes only 4W category codes. The public analytics dashboard serves the same
  VAHAN data as JSON; new `fetch_vahan_raw.py` pulled monthly EV 2W registrations for the
  dashboard's top-5 makers (2,008 months, 1982-09..2026-10), all matching the dashboard
  top-5 totals.
- Next: coverage matrices for both windows, the ADD3 document coverage report, the Vahan
  coverage note, DATA_JOBS_AUDIT row, diagnostics + final counts.
- 02:20 Done: both matrices + `DOC_COVERAGE_ADD3_2026-11-01.md`, `VAHAN_COVERAGE_2026-11-01.md`,
  DATA_JOBS_AUDIT §8, NSDL loaded into the live DB (stray worktree DB from the first load
  removed), tests 17/17 OK + Vahan `--check` 5/5, diagnostics clean on changed lines.

