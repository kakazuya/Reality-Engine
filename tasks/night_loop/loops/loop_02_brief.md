# Loop 2 brief: build pilot10, baseline answerability, first gap fixes (Phase 2)

1. **Generalisation (T-056) is merged** (2b152da). Skip the review; read HANDOFF for its findings.
   `python -m reality_engine.scripts.job_watch wait` in the background). When it ends, review it against the accept
   list in `loops/loop_01_worker_generalise.md` (read the branch's file list first: `git diff --stat main...<branch>`).
   If it fails, write a fix brief and restart it (DeepSeek off-peak; Sonnet `sonnet_worker.py` in peak hours).
2. **Build pilot10** from main (T-056 merged; resume loop 2 partial work in `loops/loop_02_report.md`):
   `docs_collect --profile tasks/night_loop/pilot10_profile.json --out D:\RealityEngine\pilot10\pages.db`, then
   `build --profile ... --part <part> --out D:\RealityEngine\pilot10\pilot10.db` part by part (registry, pages,
   stores, ratios, kpi, transcripts, guidance), timing each. This first build is the only full one; after it,
   rebuild only the parts and companies a fix touches. Record build seconds per part and pages needing OCR (no OCR
   runs this loop: list them).
3. **Store gaps** (from loop 1): Sep 2026 shareholding for HINDUNILVR, INFY, MARUTI, HINDALCO; prices, delivery and
   deals to date; SHP XBRL for all 10. Fetch with the existing fetchers into the stores' normal places, then rebuild
   only `--part stores`.
4. **Baseline A1** on the dev set: `python -m reality_engine.night_eval.answerable --db D:\RealityEngine\pilot10\pilot10.db
   --qset tasks/night_loop/questions/dev.jsonl --out D:\RealityEngine\pilot10\scores\a1_loop02_base.json` (with
   `REALITY_PILOT3_DB` pointing at pilot10.db for text needs if the tool needs it). Also `guards.py` for A3/A4 counts.
   Write per company: answerable / partly / none, and the unmet work list (largest groups first).
5. **First fixes.** Take the largest unmet groups that a script can fill (a missing metric in kpi rows, a table
   the stores do not copy yet, a sector KPI the deck prints). For each: evidence (dev questions it unlocks, doc keys
   and pages where the number sits, the table and columns), one brief, one worker (2 slots total). After a fix,
   rebuild only its part and companies on a copy, rerun A1, keep the change only if A1 dev rises and guards hold.
6. Report: A1 before/after per company, build timings, unmet list, worker verdicts; hand-off updated.
