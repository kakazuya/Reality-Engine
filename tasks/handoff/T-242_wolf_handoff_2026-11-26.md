# Wolf -> Eagle handoff, 26 Nov 12:30 IST (Wolf CLI restart for an app update)

## Running (dsh supervisors survive the CLI close; review each with skill worker-brief-merge)
1. dsh 20261126T041452Z-097adfea - results gates r3b (brief tasks/handoff/T-242_results_gates_r3b_brief.md). Accept: 0 graded-R changed in C:/RealityEngine/t242/results_ckpt1 (40 R) and results_grade_r2 (28 R), measured on a fresh recheck copy. Then fresh 60-row grade (Hydrogen, `permission: read-only`). Wolf authored the results gates -> a pass is recorded by Eagle; then swap into D:/RealityEngine/hy4_out/obs_results_fy27.db (backup, carry-over check, load_symbols) and delete obs_results_fy27.db.hold.
2. dsh 20261126T042902Z-f55b8be7 - transcript statements r3 (brief T-242_tx_statement_r3_brief.md). When merged: --reparse a copy of obs_transcripts_394_v3 (as C:/RealityEngine/t242/tx394_reparse/reparse_r2.log), 2 Sonnet graders x 30, Eagle records tx394 ckpt_0014 (Wolf authored the fix). Last reparse grades: r1 30/26/1/3, r2 36/20/4/0 (FAIL; notes in C:/RealityEngine/t242/tx394_grade_r1|r2/fix.md).
3. dsh 20261126T054953Z-8f44a0c4 - free OpenCode Go reader bake-off vs hy4 (brief T-242_go_reader_bakeoff_brief.md): beam-free, hungerg-free, iceman-contributor-free vs hy4-flash-free on 40 pages. Grade its 30-row packs per model with non-author graders; report table to Shivam.
4. Stores Drive snapshot (bash task, may die with the CLI): .tmp/stores_snapshot_to_drive.py -> gdrive:InfoDiffusion_archive/db_backups/2026-11-26_stores/ (universe_fy27 then full394), then t242 evidence -> .../2026-11-26_t242_evidence. Log C:/RealityEngine/stores_snapshot.log. If it stopped, rerun the same command (rclone copy is idempotent).
5. Deck recheck copy C:/RealityEngine/t242/deck_recheck_r8/decks_r8.db (r7+r8 + not_company) finished: measure graded-R changes (audit_deck1, decks_wide_ckpt4, deckfy27_surprise1) before any swap into obs_decks_fy27.db.

## Done today (merged, all By: Wolf)
Retrieval fixes 5-9 (live after /mcp); gate_not_company; AR gates r4 + swap (AR reading open); results r2/r3; deck r5-r8; junk r6; transcript filter + r2; guidance/KPI extractor fixes (next build); run_ledger incremental; OCR AIMD + Zen rotation + slide-type classifier (`ocr_fill --classify`, needs a free vision bake-off); loader SUPPLEMENTS (deck-wide 39,941 rows loaded; OCR rows quarantined). OCR backlog finished with the new Kilo key (159/159).
## New tool
gemini-worker MCP (plugins/gemini-worker/gemini_worker.py, project .mcp.json): 37 AI Studio keys, per-key pacing, default gemini-4-hydrogen (~3-10 s, free tier). Use it for grading to save agy weekly quota. gemini-web (browser) parked: Google blocks automated sign-in.
## Rules learned today
Fix author does not record the re-grade pass; agy grader briefs carry `permission: read-only`; compare every retrieval fix against LIVE main; empty period beats wrong period; never spawn PowerShell in polling loops (pop-ups) - use .tmp/wait_pid.py.
