# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-09 02:00 IST (Wolf, overnight run)
History `docs/state_history/`; method `docs/PILOT3_BLUEPRINT.md`; v2 contract `docs/V2_SCHEMA_CONTRACT.md`.

## Now (overnight 9 Nov, Shivam asleep, report due 09:00 in `D:/RealityEngine/reports/2026-11-09_overnight_report.html`)
- Live store `D:\RealityEngine\pilot10\pilot10.db` (10 companies); pilot set 558/600 = 93.0% after re-ask2.
- Fixed: undated XBRL quarters (ULTRACEMCO Q2FY27) take the file-name stamp (`prepare.xbrl_file_ts`); ratios skip undated inputs. u8 rebuilt, at `D:/RealityEngine/u8/u8.db` (shp_pledge/shp_holder empty: SHP raw not fetched for u8).
- T-130 u8 answers running: G on MSI dsh `20261108T202256Z-7b279bee` (key 1), H on HP `hp-20261109T015347-16ef71` (key 1, brief with questions inlined, `--pilot-db`). Go key 2 hit 429 at 01:52.
- T-135 calc catalog: dsh `20261108T202242Z-b0e7be26` (key 1), brief `tasks/handoff/T-135_calc_catalog_brief.md`.
- T-131 contract DRAFT committed (DDL `reality_engine/v2/schema_v2.sql`, test `test_v2_schema.py`); waits for Shivam's OK. T-132 prototype `tasks/v2/T-132_proto_cells.py`, findings in contract section 8.
- T-143 pilot20: build running (`<Wolf 82841833 scratch>/p20/build.sh`, docs_collect since 01:43); 202 reframed questions in `D:/RealityEngine/p20/answers/questions_{P,Q}.json` (P 111: BHARTIARTL ASIANPAINT TITAN ADANIPORTS INDHOTEL; Q 91: PIDILITIND COALINDIA HDFCAMC HAVELLS); briefs `tasks/handoff/T-143_p20_{P,Q}_brief.md`; Apollo harvest agy `20261108T201344Z-62b4f9ea`.
- q12 rebuild (`<bea35aad scratch>/q12/build5.sh`) on comparatives since 01:44.
- T-154: embedding prices done (`D:/RealityEngine/reports/2026-11-09_t154_embedding_*`): Nemotron-3-Embed-8B on DeepInfra $0.035/M cheapest; Qwen3-8B Fireworks 2.9x, voyage-finance-2 3.4x.
- Waiting Shivam: T-131 OK, T-116, T-118, T-121, T-122. Ticket board `D:\RealityEngine\reports\ticket_board.{xlsx,html}`.

## Next action
1. q12 done -> checkpoint, copy to `D:/RealityEngine/q12/q12.db`, start C and D answer briefs (HP via `<this scratch>/hp_brief.py` + `hp_worker start --pilot-db`, or MSI when a code slot frees). No dsh starts 06:30-09:30.
2. p20 done -> checkpoint, copy to `D:/RealityEngine/p20/p20new.db`, start P and Q the same way.
3. Grade finished answer runs by hand (redo every sum), `answer_run_report --name t130_u8` etc.
4. Review + merge T-135 (review row first); wire MCP tool `pilot3_calc_catalog`.
5. Apollo harvest -> reframe -> questions_R.json.
6. Sweep new raw (u8 + p20 symbols) to Drive with raw_to_drive after builds.

## Merge recipe
Review row in `worker_reviews.jsonl` first (gate). `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, run changed test files one per process, update this file and docs, commit `By: <identity>`; remove the worktree; log to the decision log.
