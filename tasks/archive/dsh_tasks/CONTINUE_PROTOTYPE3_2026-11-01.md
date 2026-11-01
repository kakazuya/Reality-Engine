# CONTINUE: prototype extraction on BAJFINANCE, HINDALCO, KEC

The earlier run stopped at 03:50 IST because its controller lease expired, not because of a fault. This worktree holds all its work, uncommitted: `reality_engine/pilot/proto3.py`, `reality_engine/data/extract_proto3.db`, `.tmp/proto3/PROGRESS_NOTES.md`, `tasks/pilot60/PROTOTYPE3_*`. Read the notes and `git status` first. Do not rerun finished steps or commit: the reviewer commits.

Done: Arm A, Arm B, Arm C and its hand-check, a first `PROTOTYPE3_ANSWERS` file. The effort comparison was running when it stopped; check `extract_call` and rerun only what is missing.

Budget still applies, counted from what `extract_call` already holds: stop at $1.50 at Go rates or 3M input tokens.

Also investigate one defect: `rating_action` holds rows for 37 companies in a 3-company prototype. State whether those rows are in scope, whether any used model tokens, and exclude other companies from all counts and forecasts.

Finish, per `tasks/dsh_tasks/PROTOTYPE3_EXTRACTION_2026-11-01.md` in the main checkout at `C:\Users\warri\Downloads\Info_Diffusion_Model`, which is the full brief: effort comparison, accuracy (30 rows per arm), recall (3 documents per company and type), answers file for all bank questions naming only these 3 companies, and `tasks/pilot60/PROTOTYPE3_REPORT_2026-11-01.md` with tokens as a percent of whole-document tokens, cost, wall time, and a low and high forecast for 60 names and the whole universe. Do not grade answers: Claude does.

Test command(s): python -m pytest reality_engine/tests -q -k extract60
End with `Docs updated:`. No docs, no merge.
