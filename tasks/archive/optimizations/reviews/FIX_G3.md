# Fix task — G3 universes review (verdict FAIL)

## Goal
Make the theme universes usable for cause-and-effect tests. Each member must have a correct revenue-share weight,
or be explicitly marked as unweighted. Precision must be at least 85% on housing_finance, dairy, data_centres and
omc_refining. Keep the ETF/MF resolve part, which passed.

Worktree: `C:\Users\warri\Downloads\IDM-worktrees\20261025T123302Z-e856c1b1` (branch `dsh/20261025T123302Z-e856c1b1`).

## Read first
The full reviewer report is at
`C:\Users\warri\Downloads\Info_Diffusion_Model\plugins\dsh-worker\runtime\jobs\20261025T135133Z-c01c539c\result.md`.
Read all of it, including the PROPOSED-RULES section. It has the traced rows: IOC .257 vs correct .948,
RELIANCE .028 vs .638, MRPL .640 coming from customer concentration, BPCL 0 from a volume row, and the per-theme
TRUE/FALSE labels. Fix defects 1–10 from that report.

## Manager decisions
- **Membership** follows the reviewer's proposed rule 1. A company is a member only with a usable weight
  (`segment` weight > 0 from a real company revenue-mix row), **or** an NSE industry match, **or** a curated seed.
  `subsidiary` and `stated_pivot` hits go to a separate `universe_candidates` table with their evidence. They never
  enter `universe_membership` and never get a weight.
- **Weight:**
  - Numerator: the theme segment's revenue.
  - Denominator: the company's total revenue from operations for the **same document, period and normalised
    unit** (crore).
  - A percent row counts only if it is a company revenue-mix row. Reject market share, customer concentration,
    AUM/loan mix, targets and guidance.
  - Take the latest fiscal year available as of each date.
  - A weight older than 2 fiscal years with no newer evidence expires (`valid_to`).
- **Industry/curated members:**
  - Weight is null, with `weight_source` = `industry` or `curated`; never 0.
  - `valid_from` = listing date, or `2019-01-01` if the listing date is unknown; never the crawl date.
  - A curated seed with no ISIN is reported in the run diff, not dropped silently.
- **Pivot:** the XBRL `facts.context` is only `OneD`/`FourD`, so XBRL segment names cannot be read.
  - Remove the XBRL segment path.
  - Compute `pivot` from AR/deck revenue mix across consecutive fiscal years: the theme segment becomes the
    company's largest segment.
  - Replace the fixture that uses a fake XBRL context with one in the real AR/deck shape.
- **`universe()` tool:**
  - Default `min_weight` = 0.01 for weighted members.
  - Return unweighted (industry/curated) members in a separate list.
  - Apply `substrate_quarantine` exclusions.
  - A theme that is known but not yet built returns `found:false` with a build hint.
- **resolve:** only query `fund_nav` when there is no equity/BSE match (the reviewer's `want_nav = not out`).
- **Clean-up:** remove the stray `PROGRESS_NOTES.md` and the unneeded `.gitignore` lines. Tests use `.tmp/`.

## Files to touch
Only the G3 files: `plugins/reality-data/server/core.py`, `universe.py`, `universes.yaml`,
`reality_engine/scripts/build_universe_membership.py`, and the two test files. Revert `.gitignore`.

## Acceptance checks
1. Dry run on a temp copy (`--db` under `.tmp/`). Print for omc_refining, housing_finance, dairy and data_centres
   every member with its weight, weight_source and evidence quote. Hand-label each TRUE/FALSE and report precision;
   it must be ≥ 85% per theme.
   - IOC, BPCL, HINDPETRO, MRPL and CHENNPETRO must all be members, each with weight ≥ 0.8 or weight_source
     industry.
   - DCBBANK, ARIHANTSUP, NESTLEIND, VBL and TCS must not be members.
2. Report the share of members with a numeric weight, per theme.
3. Tests pass: `python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"` and
   `python -m unittest reality_engine.tests.test_universe_builder`. Use `.tmp/` for temp dirs; if the sandbox still
   blocks, say exactly what was blocked.
4. `resolve("543437")` returns kind etf in under 1 s warm; equity resolves are unchanged.
5. `git diff --stat` touches only the files listed.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_universe_builder
```

## Budget
≤ 15 tool calls before the first edit; ≤ 120 total; $0 paid. No live DB writes. Do not commit (Claude commits).

## Report format
1. Per defect: change (file:line)  2. Per-theme member tables (trimmed) with precision and weighted share
3. Open problems  4. Tool calls.
