# PROGRESS_NOTES — T-178 (Wolf)

- Done: `reality_engine/scripts/t178_salvage.py` (four arms on the 30 deck reference pages, 200-report fiscal-year check, queue coverage, xlsx) + `reality_engine/tests/test_t178_salvage.py` (3 passed), typecheck 0 errors.
- Result: verdict audit-only — (c) recall 47.4% vs script (a) 26.9%, frozen precision 78.3% (bar 95%); xlsx `.tmp/t178/t178_first_build_rekey.xlsx`.
- Blocker: AR PDFs are not local and rclone cannot run in this sandbox, so the fy check used `ar_facts` quotes (127/200 derivable) — rerun on an unsandboxed host for the PDF text layer. The ticket accept file must be copied to `D:/RealityEngine/reports/2026-11-11_t178_first_build_rekey.xlsx` (outside the workspace).
