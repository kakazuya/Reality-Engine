# T-090 progress notes

- Done: schema columns + `fin_quarter_current` view + shared election in `reality_engine/pilot3/preferred.py`;
  build part `preferred`; lookups/tool text read coverage from the company table; tests updated.
- Verified on `.tmp/pilot10_w.db`: (a) 19,992.38 / 20,180.76 crore by date, (b) 3,295 quarterly keys,
  0 differences vs `pilot3_fin`, old-vs-new 0 changed, (e) 0.1 s for ten companies; checkpages 146 on its
  default pilot3.db (0 on the pilot10 copy: fixture doc_keys differ, live db same).
- Next: final test/typecheck, report. Blockers: sandbox `tmp_path` ACL and synthetic-PDF KPI extraction
  make a few unrelated pilot3 tests error (documented).
