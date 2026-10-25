# Fix task — G3c: deck weight accuracy

## Goal
Deck-sourced theme weights must be a true share of the **company's** revenue. Membership is already correct
(G3b merged as `fef4278`); this round fixes the weights the manager review found wrong.

## Read first
- The G3b report, especially section 6 (open problems):
  `C:\Users\warri\Downloads\Info_Diffusion_Model\plugins\dsh-worker\runtime\jobs\20261025T161212Z-f74b42d5\result.md`.
- `reality_engine/scripts/build_universe_membership.py`: `_deck_evidence`, `_deck_tables`, `_deck_labels`,
  `_prefer_deck`, `_clip`.

## Defects (verbatim from the manager review)
1. **EDELWEISS housing_finance 0.6415 is wrong.**
   - `deck_figures.db` facts sha `ab4e6d44…f8a3`, page 8, is a per-business table. Each business has its own
     `Revenue` row per period (100/119/106, 205/154/81, 57/52/…).
   - The builder divided `Housing Finance Revenue: 68 $ Mn` by another business's `Revenue` 106.
   - A slide with several same-period `Revenue` rows is a business-unit table. A numerator from it may only be
     divided by a stated company total (`Total`, `Consolidated`, the group's own row), never by a sibling business's
     revenue.
2. **Cross-check every absolute deck denominator** against the company's reported revenue for the same period,
   from `results_xbrl.db` or the quarterly financials.
   - Match on the period type (quarter, nine months, FY), converting units ($ Mn, ₹ Cr, ₹ Mn, lakhs).
   - Accept within ±15%; otherwise there is no weight. Report how many deck weights this check rejects.
3. **Geographic mixes are not segment shares.**
   - Reject: NAVINFLUOR `Specialty Chemicals revenue mix - India: 59%`, and any % row whose label names a
     geography (India, domestic, export, overseas, international, region or country names).
4. **Within-segment product mixes are not company shares.**
   - Reject: TITAN `Product Mix % of Domestic Jewellery … 72%` and GRASIM
     `Specialty Chemicals & Chlorine Derivatives (% of Revenue share for FY22)`. The latter is a mix inside the
     chemicals business.
   - Accept a % row only when its label refers to the company's total revenue, or when it reconciles with the
     deck's own segment table, i.e. the segment rows' % sum to ~100% at company level.
5. **Company-name rows are totals, not segments.** `Dodla Dairy (Standalone) Revenue: 3,421.7` is DODLA's own
   total.
   - A row whose label is the company's name or "standalone/consolidated revenue" is a denominator, never a theme
     numerator.
   - A pure play gets weight 1.0 only when the deck's segment table shows a single segment, or when no other segment
     exists. Otherwise it stays an unweighted industry member.
6. **Recency (manager decision).** The most recent disclosure wins, whatever its source. Only within the same
   fiscal quarter does a deck beat an AR row. An older deck must not shadow a newer AR weight.
   - Example: PREMEXPLN, deck 2025-11-13 (86%) vs AR (81.22%). Check the AR filing date and apply the rule.

## Acceptance checks
1. Dry run on a temp DB under `.tmp/g3c-<pid>/`, never the live DB.
   - Print every deck and deck_sum weight across all themes: member, weight, quote, the cross-check figure from
     step 2, pass/fail.
   - Hand-label each weight correct/incorrect. Weight accuracy must be ≥ 90%, and membership precision ≥ 85% per
     theme.
2. EDELWEISS: its weight must be the true share, or it drops out if that share is below the 0.5 floor.
   NAVINFLUOR's 0.59 and the TITAN 72% / GRASIM 52–60% rows are gone. DODLA follows rule 5.
3. Gaps = 0, overlaps = 0. The required absences still hold: SOTL, LAKESHORE, DCBBANK, ARIHANTSUP, NESTLEIND, VBL,
   TCS.
4. Tests:
   - `python -m unittest reality_engine.tests.test_universe_builder` passes, with new cases for rules 1, 3, 4, 5
     and 6.
   - `python -m unittest discover -s plugins/reality-data/tests -p "test_universe*.py"` passes.
   - Use fresh temp dirs.
5. `git diff --stat` touches only the builder, `universes.yaml` and the builder test file.

## Rules
Local data only: no internet, no paid APIs, no live DB writes. Use `mode=ro` / `connect_ro`.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_universe_builder
```

## Budget
≤ 12 tool calls before the first edit; ≤ 100 total; $0 paid.

## Report
1. Per defect: change (file:line)  2. The deck-weight table with cross-checks and labels  3. Per-theme
precision + weighted members by source  4. Gaps/overlaps  5. Tests  6. Open problems  7. Tool calls.
