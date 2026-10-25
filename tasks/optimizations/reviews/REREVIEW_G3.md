# Re-review — G3 theme universes after the fix (read-only)

## Goal
Independently check that the G3 fix commit `16c827c` resolves defects 1–10 from the first review and does not add new
ones. Verdict: PASS, PASS-WITH-NOTES or FAIL.

Worktree: `C:\Users\warri\Downloads\IDM-worktrees\20261025T123302Z-e856c1b1` (branch `dsh/20261025T123302Z-e856c1b1`).
- Diff to review: `git diff 5877b16..16c827c`.
- First review, with defects and per-theme labels:
  `C:\Users\warri\Downloads\Info_Diffusion_Model\plugins\dsh-worker\runtime\jobs\20261025T135133Z-c01c539c\result.md`.
- Fix brief with the manager decisions: `C:\Users\warri\Downloads\Info_Diffusion_Model\tasks\optimizations\reviews\FIX_G3.md`.
- The fixer's report: `C:\Users\warri\Downloads\Info_Diffusion_Model\plugins\dsh-worker\runtime\jobs\20261025T141901Z-c870a878\result.md`.

## Check
1. **Trace three weights yourself from `ar_facts.db`** (read-only, `connect_ro` or `mode=ro`):
   - IOC 0.95076 (FY ≤ 2021);
   - RELIANCE 0.676376;
   - HUDCO 0.9959.

   For each, confirm that the numerator and denominator come from the same document, period, basis and unit, and
   that the denominator is a real total-revenue row.
2. **Precision.** Spot-check 5 members per theme (omc_refining, housing_finance, dairy, data_centres) against their
   evidence. Also check that DCBBANK, ARIHANTSUP, NESTLEIND, VBL and TCS are absent.
3. **The `_pct_weight` filter.** Do `MIX_PATTERNS` and `BLOCKED` reject market share, customer concentration and
   AUM/loan mix? Name any genuine revenue-mix row it wrongly rejects.
4. **Time correctness:**
   - Each weight is valid from its disclosure date, never from the fiscal-year end.
   - Hand-overs from a weighted row to an industry row have no gaps and no overlaps.
   - `valid_from` for industry members is the listing date.
   - Nothing uses the crawl date.
5. **Pivot logic.** Is "segment value ≥ max(sibling segments)" sound? Could it fire on a row that is really a
   total or a sub-total?
6. **`universe()` tool:**
   - The `min_weight` default is 0.01.
   - The `unweighted` list is separate.
   - The quarantine filter is applied.
   - An unbuilt theme returns `not_built`.

   Also check `core.py` `want_nav = not out`.
7. **Fixer's open problem 1.** IOC's FY2026 AR has 4 segment rows but no total. Say whether a `segment_sum`
   denominator is safe, i.e. whether the segments are exhaustive and don't overlap. If it is, give a rule that keeps
   double counts out (inter-segment eliminations, "Others").
8. Run `python -m unittest reality_engine.tests.test_universe_builder` and
   `python -m unittest discover -s plugins/reality-data/tests -p "test_universe*.py"`. If the sandbox blocks temp
   dirs, say what was blocked.

## Rules
Read-only. No edits, no commits, no live DB writes, no internet. Write temp files only under the worktree `.tmp/`.

## Budget
≤ 60 tool calls; $0 paid.

## Report
1. Verdict  2. Defects (severity, file:line, evidence, fix)  3. Weight traces  4. Spot-check table
5. segment_sum recommendation  6. Tests  7. Tool calls.
