# T-102 fetch on demand, CONTINUE (round 2)

Ticket: T-102
Goal: finish the work of job 20261107T075408Z-e12606d2, which stopped on a Go quota error (429), not on a fault.
Your branch starts from its WIP commit 7d28862. Read the original brief first:
`tasks/handoff/T-102_fetch_on_demand_brief.md` (in the main checkout C:\Users\warri\Downloads\Info_Diffusion_Model);
every field there (Files, steps, limits, pitfalls, Accept, Stop if) still binds.

Evidence (Opus review of 7d28862, 7 Nov):
- Done: `reality_engine/raw_store.py` has `RawStore` (exists, walk, glob, subdirs, local, prefetch, default_store) and
  `reality_engine/tests/test_raw_store.py` passes 8 of 8. Keep this design; do not rewrite it.
- About half done: `reality_engine/pilot3/docs_collect.py` (61+/56-). Check `git diff 1d09c20 -- reality_engine/pilot3/docs_collect.py`
  first and finish it: discover(), the profile manifest path check, `_extract` under one `prefetch` per company.
- Not started: `comparatives.py` `_open_pdf`, `kpi.py` `_open_pdf_path` + hard-coded `RAW_ROOT`, `hp_ocr.py` `_resolve_pdf`,
  `ocr.py`, `doc_identity.py` ~L549, `plugins/reality-data/server/lookups_docs.py` ~L587. Note a context-manager
  `local()` must stay open while the PDF is open: hold the fitz document inside the `with`, or prefetch around the loop.
- Also not started: docs (`docs/DEVELOPER_GUIDE.md` O18 T-102 paragraph; one line in `docs/DB_BUILD_GUIDELINES.md`) and
  the step 4 KEC accept run.
- The upload is still running (about 22,000 of 56,800 files sent); a KEC file without `drive_path` is listed, not waited for.

Files: as in the original brief.

Accept:
- `python -m pytest reality_engine/tests/test_raw_store.py reality_engine/tests/test_raw_to_drive.py -q`
- the pilot3 docs_collect / comparatives / kpi test files, one per process, `-m "not slow"`
- step 4 KEC comparison table (or the exact commands for Opus to run it unsandboxed if your sandbox blocks rclone).

Stop if: as in the original brief.

Budget: 2.5 hours, about 120 tool calls.
