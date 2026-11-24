# T-241 brief: make_profile fallback for companies not in master_companies (Eagle codes, Wolf reviews)

## Evidence (24 Nov 2026)
- Universe FY27 build (`C:/RealityEngine/tg_build/universe_fy27`): 38 of ~970 finished stores failed at the first
  part, `make_profile(rc=1)`, so no store at all was built. Example: `c11/b_make_profile.log`
  `KeyError: "'4THGEN' is not in master_companies"` (`reality_engine/pilot3/make_profile.py:167`); also c20
  AADHAARVEN, c23, c71 ACEEDU, c85 ACME.
- Measured over `universe_fy27.csv` (columns isin,symbol,bse_code): 300 of 4,652 symbols miss
  `master_companies` (`nse_symbol=? OR isin=?` with the symbol); looking up by the row's ISIN or bse_code finds only
  23 of them; 277 are absent from master entirely (BSE-only / SME / new listings). 4THGEN = INE739B01039, 532403.
- `tg_measure_build.py:497` passes the universe symbol as `key` (ISIN only for `--doc-types` builds);
  `build_company` runs `python -m reality_engine.pilot3.make_profile <key> --name cNN --root ...` (line ~402).

## Steps
1. Worktree `Eagle-make-profile-fallback` off main. Do not touch running jobs or `C:/RealityEngine/tg_build/*`.
2. `make_profile.company_row(conn, key, table, results_conn=None, fallback=None)`: `fallback` is
   `{"isin":..., "bse_code":...}` from the universe row. Order: master by key (unchanged) -> master by
   fallback isin or bse_code -> a synthesized row: symbol = key, isin = fallback isin, bse_code = fallback
   bse_code, name = a filed company name for that ISIN if any table holds one (look in corporate_documents /
   results filings; check columns first), else the symbol; isins via `issuer_isins(...)`; sector and lender via
   the same `label_of` / `family_of` / `bse_family` path. Mark it: `"master": false` in the company dict.
   No fallback and no master row -> the same KeyError as today.
3. `make_profile` CLI: `--isin` and `--bse-code` (valid only with one company), passed through `make_profile()`.
4. `tg_measure_build.build_company`: when the universe entry has an isin/bse_code, append `--isin/--bse-code` to
   `profile_cmd` (all builds, not only doc-type builds). Read how `entry` reaches build_company first.
5. Tests (new file `reality_engine/tests/test_make_profile_fallback.py`, temp sqlite, no real data): master row
   still wins; ISIN lookup recovers; synthesized row has symbol/isin/bse_code and `master: false`; no fallback ->
   KeyError. Run with the existing `test_pilot3_no_company_literals.py` and `test_tg_measure_build.py`.
6. One real check: `python -m reality_engine.pilot3.make_profile 4THGEN --isin INE739B01039 --bse-code 532403
   --name x --root <scratch dir> --out <scratch>/x.json` succeeds; paste the company dict.
7. Docs: `docs/DEVELOPER_GUIDE.md` make_profile paragraph (no docs, no merge). Commit naming T-241.

## Limits / pitfalls
- Never guess a sector from the symbol text; unknown stays `UNKNOWN`.
- Don't change the master path's output for companies that are in master (golden: re-run make_profile for
  1STCUS and TATACONSUM before/after and diff the JSON: must be identical).
- No push. Don't edit tasks/STATE.md. Max effort on correctness, not breadth.

## Stop rule / report
Stop when tests pass and step 6 works. Send Wolf (neo-...) the branch name, head, test output and the step-6 dict.
Wolf reviews and merges; Wolf rebuilds the 38+ failed stores.
