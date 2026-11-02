# T-048: gap loop for any pilot company (BAJFINANCE, HINDALCO, KEC). Brief, 2 Nov 2026 (Wolf)

Goal: `python -m reality_engine.gap_loop --sandbox <dir> --company <SYMBOL>` runs the existing one-company
gap loop for BAJFINANCE, HINDALCO or KEC. Today every company fact is hardcoded to KEC. KEC must keep
working unchanged on its existing sandbox `D:\RealityEngine\sandbox\kec_loop` (its db stays `kec.db`).

Work only in this worktree. Do not call any model, do not run the loop itself, no network, never read
`D:\Shivam_Private` or any key file. Read-only access to `D:\RealityEngine` is fine; you may create
`D:\RealityEngine\sandbox\bajfinance_loop\raw` and `...\hindalco_loop\raw` and copy PDFs into them.

## 1. Company config (`reality_engine/gap_loop/company.py`, new)
A frozen dataclass `Company(symbol, name, isins: tuple, bse_code, db_name, questions, raw_sources)` and
`COMPANIES` dict:
- KEC: name "KEC International Ltd", isins ("INE389H01022",), bse 532714, db `kec.db`,
  questions `questions/KEC_QUESTIONS.jsonl`.
- BAJFINANCE: name "Bajaj Finance Ltd", isins ("INE296A01032", "INE296A01024") (the ISIN changed on
  2025-06-16 at the split; copy rows for BOTH), bse 500034, db `bajfinance.db`,
  questions `questions/BAJFINANCE_QUESTIONS.jsonl`.
- HINDALCO: name "Hindalco Industries Ltd", isins ("INE038A01020",), bse 500440, db `hindalco.db`,
  questions `questions/HINDALCO_QUESTIONS.jsonl`.
`--company` defaults to KEC. The chosen Company is passed (or set once on a module-level current
company) so that prepare, store, tiers, checks, remote, loop and keeper use it.

## 2. Replace every KEC hardcode
`grep -n "KEC\|kec" reality_engine/gap_loop/*.py` lists them (about 85). Each becomes the company's
value: ISIN filters become `isin IN (...)` over all its ISINs; symbol and BSE code from config; the db
file name from `db_name` (store.DB_NAME, checks, remote snapshot name, HP sandbox path
`C:\RE\sandbox\<symbol lower>_loop`); prompts in `tiers.py` say the company name and db name; the
`job_watch` name becomes `<symbol lower>_gap_loop`; env `KEC_GAP_LOOP` stays as is (the session-title
hook looks for it). Example qid in prompts uses the company's first qid prefix (`BAJFINANCE001`).
KEC's own site-transcript manifest code must stay KEC-only (skip when files are absent).

## 3. Raw folders for the two new sandboxes
Copy (do not move) `D:\RealityEngine\raw\pilot60_history\<SYMBOL>\**` into
`D:\RealityEngine\sandbox\<symbol lower>_loop\raw\history\` keeping subfolders, exactly as KEC's
sandbox has `raw\history\annual_report`, `...\investor_presentation`, etc. Create `questions\`, `logs\`,
`reports\`, `state\` empty. Do NOT write question files: Opus writes them.

## 4. Tests and proof
- Existing tests must pass: `python -m pytest reality_engine/tests/test_gap_loop.py reality_engine/tests/test_doc_review_loop.py -q`.
- Add tests: config lookup; a BAJFINANCE prepare SQL carries both ISINs; prompts name the company and db.
- Run `python -m reality_engine.gap_loop --sandbox D:\RealityEngine\sandbox\kec_loop --company KEC --dry-run`
  and confirm it prints the same plan as before your change (run it on main first to compare).
- Run `--prepare-only` for BAJFINANCE and HINDALCO on their new sandboxes (code only, no model; it
  needs no question file — if it does, make prepare not need one). Report counts per table and the
  undated share under `raw\history`.

## 5. Docs (no docs, no merge)
Update `docs/DEVELOPER_GUIDE.md` section N (the gap loop): `--company`, the config, sandbox per
company. Commit on this branch with message `T-048 gap loop takes --company: BAJFINANCE, HINDALCO, KEC`.

## Report (last message)
Files changed, test result lines, the KEC dry-run comparison, the two prepare counts, anything you
could not do, and `Docs updated: <files>`.
