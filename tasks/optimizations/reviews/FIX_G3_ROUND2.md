# Fix task — G3 round 2 (re-review verdict PASS-WITH-NOTES)

## Goal
Fix defects N1–N10 from the re-review, and add a reconciled segment-sum denominator so that current-year refiner
weights can be computed. Then G3 merges.

Worktree: `C:\Users\warri\Downloads\IDM-worktrees\20261025T123302Z-e856c1b1` (HEAD `16c827c`).
Read the re-review in full, including its section 5 rule:
`C:\Users\warri\Downloads\Info_Diffusion_Model\plugins\dsh-worker\runtime\jobs\20261025T151433Z-2a0b16b1\result.md`.

## Manager decisions
- **N1 (wrong-file AR):** accept a weight only if the document names the company (its name or symbol appears in the
  doc text or in the `ar_docs` company field). Also honour `substrate_quarantine` keys for `ar_facts`. LAKESHORE's
  weight from doc 127534 must disappear.
- **N2:** `server.py` `universe` tool: `min_weight` default 0.01, passed through. Add a test that calls the
  registered function.
- **N3:** a theme in `universes.yaml` with 0 rows returns `found:false`, `error.code="not_built"` and the hint.
  Change the test to expect this.
- **N4:** fill gaps between weighted intervals with an unweighted industry/curated row when one applies, so there
  are 0 gaps and 0 overlaps. Report the counts.
- **N5:** add `lubricant`, `blended oil`, `biodiesel`, `oleochemical` to `omc_refining.exclude_keywords`.
  - For omc_refining, segment-weight membership also needs a `company_industry` row in the oil/refining family.
  - SOTL must not be a member.
  - KOTYARK may stay, because NSE classes it as Refineries & Marketing; note it in the report.
- **N6 (pivot guard):** use one segment table, at least 3 distinct siblings, and sum(siblings) within ±1% of the
  total. Reject sibling labels containing total, less, inter-segment, elimination or unallocated.
- **N7:** drop weighted rows that have no disclosure date. Never fall back to the fiscal-year end.
- **N8:** delete the unused `results_xbrl.db` open and close.
- **N9:** the denominator is "revenue from operations", then "total revenue", then "total income", in that order.
  Never take `max` across bases.
- **N10:** accept "principal business activity … % of turnover / contribution" and "<product> turnover %" as revenue
  mix. Allow `loan`/`aum`/`portfolio` words only when the row is the company's own revenue/turnover mix (for
  example "interest income from housing loans % of revenue"). Keep the market-share and customer-concentration
  blocks. HATSUN 93.59% and HERITGFOOD 65.47%/32.44% should become weights; DCBBANK, ARIHANTSUP, MRPL and
  KALYANKJIL must stay rejected.
- **segment_sum:** implement the re-review's section 5 rules 1–6 exactly.
  - It applies only when no stated total exists for the same doc/period/basis/unit, and the sum must reconcile
    within ±1% to an independently stated revenue figure in the same document.
  - Use `weight_source='segment_sum'`.
  - IOC FY2026 should come out at about 0.9166, with the reconciliation figure in the evidence. Report what
    BPCL, HINDPETRO, MRPL and CHENNPETRO get.
- **N11:** generate every report table from the final commit's build. Report weighted rows and weighted members
  separately.

## Files to touch
Only the G3 files: `reality_engine/scripts/build_universe_membership.py`, `plugins/reality-data/server/universe.py`,
`plugins/reality-data/server/universes.yaml`, `plugins/reality-data/server/server.py` (the universe tool only), and
the two test files. Add a fixture case for segment_sum: one that reconciles, and one with a parent+child double
count that must be rejected.

## Acceptance checks
1. Dry run on a temp DB under `.tmp/`. Print the per-theme tables for omc_refining, housing_finance, dairy and
   data_centres: member, weight, weight_source, evidence quote, TRUE/FALSE label. Precision must be ≥ 85% per theme.
   - SOTL and LAKESHORE must not be members.
   - DCBBANK, ARIHANTSUP, NESTLEIND, VBL and TCS must still be absent.
2. Report gaps = 0 and overlaps = 0 over every (theme, ISIN) chain.
3. Report IOC's FY2026 segment_sum weight, plus the other OMCs'.
4. Tests: `python -m unittest reality_engine.tests.test_universe_builder` and
   `python -m unittest discover -s plugins/reality-data/tests -p "test_universe*.py"`. Use a fresh temp dir name
   (for example `.tmp/g3r2-<pid>`), because `.tmp/universe-tests` is ACL-locked. If anything is still blocked, say
   exactly what.
5. `git diff --stat` touches only the listed files.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_universe_builder
```

## Budget
≤ 12 tool calls before the first edit; ≤ 100 total; $0 paid. No live DB writes. Do not commit (Claude commits).

## Report
1. Per defect: change (file:line)  2. Per-theme tables + precision + weighted rows/members  3. Gaps/overlaps
4. segment_sum results  5. Tests  6. Open problems  7. Tool calls.
