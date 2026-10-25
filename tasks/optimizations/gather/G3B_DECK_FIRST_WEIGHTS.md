# Task G3b — theme weights from investor decks first, annual reports second

## Goal
Theme universe weights (`universe_membership.weight`) come first from investor-presentation revenue-mix data,
wherever a deck has it, and from the annual report only when no usable deck figure exists. Decks are quarterly and
show the segment revenue split directly, so weights stay current and catch pivots within a quarter rather than a
year. Shivam, 2026-10-25: "Picking a theme from Investor PPTs wherever present is actually smarter as it includes
mostly revenue segment data too."

## Context
- The builder is `reality_engine/scripts/build_universe_membership.py`; G3 is merged on `main`.
  - Read its module docstring and the G3 round-2 report:
    `C:\Users\warri\Downloads\Info_Diffusion_Model\plugins\dsh-worker\runtime\jobs\20261025T153116Z-48dc1df6\result.md`.
  - The rules from G3 still hold: in-document company check, `segment_industry_keywords` gate, gap-free chains,
    `segment_sum` reconciliation, pivot guard, `MIX_PATTERNS`/`BLOCKED`.
- Deck figures live in `deck_figures.db` (table `facts`, FTS `facts_metric_fts`; see `catalog()` via the reality-data
  tools or `plugins/reality-data/catalog_descriptions.yaml`). HERITGFOOD's 0.63 "Milk Product Mix: 63%" already
  comes from there; the current deck path is a single % row.
- Today the AR sweep stops at `LIMIT 20000` of 120,856 FTS rows, so many real AR rows never reach the build.
  Decks are smaller and higher signal, so read every deck row that matches a theme keyword.

## Do
1. **Deck evidence path.**
   - For each company and deck, take the segment revenue rows:
     - absolute segment revenue divided by the same deck's total revenue, for the same period and unit; or
     - an explicit "% of revenue / revenue mix / segment share" row.
   - Use the same rejections as the AR path: market share, customer concentration, AUM/loan/order-book mix
     (unless it is revenue), targets, guidance and capacity.
   - Each weight is valid from the deck's filing date (the BSE/NSE filed date, never the crawl date).
   - It expires after 4 quarters with no newer deck evidence.
2. **Priority.**
   - On any date, a deck weight disclosed within the last 4 quarters beats an AR weight.
   - Otherwise the AR weight applies, then industry/curated as today.
   - Record `weight_source` = `deck` | `deck_sum` | `segment` | `segment_sum` | `industry` | `curated`.
   - Keep the chains gap-free and overlap-free.
3. **Pivots from decks.** Fire `pivot=1` when the theme segment becomes the company's largest revenue segment
   between consecutive decks. Apply the G3 pivot guard: ≥3 distinct siblings, and the sum within ±1% of the
   deck's total when a total exists.
4. **AR sweep cap.** Do not raise it blindly; round 2 showed lubricant makers flooding in. Raise it only if, with
   decks first, precision stays ≥85% in every theme. Report what you tried.
5. Add tests in `reality_engine/tests/test_universe_builder.py`:
   - a deck beats an older AR row;
   - an expired deck falls back to the AR row;
   - a deck guidance or market-share row is rejected;
   - a deck pivot fires.

## Acceptance checks
1. Dry run on a temp DB copy under `.tmp/g3b-<pid>/`. Never write the live DB.
   - Print per-theme tables for omc_refining, housing_finance, dairy, data_centres and any other theme in
     `universes.yaml`: member, weight, weight_source, evidence quote, valid_from.
   - Hand-label each member TRUE/FALSE. Precision must be ≥85% per theme.
   - SOTL, LAKESHORE, DCBBANK, ARIHANTSUP, NESTLEIND, VBL and TCS must still be absent.
2. Report weighted members per theme before and after, split by source (deck vs AR).
   - Name the refiners (BPCL, HINDPETRO, MRPL, CHENNPETRO, IOC) and dairy companies that gain a deck weight, with
     the quote.
3. Gaps = 0 and overlaps = 0 across all chains.
4. Tests pass: `python -m unittest reality_engine.tests.test_universe_builder` and
   `python -m unittest discover -s plugins/reality-data/tests -p "test_universe*.py"`.
   - Use fresh temp dirs `.tmp/g3b-<pid>`; `.tmp/universe-tests` is ACL-locked.
5. `git diff --stat` touches only the builder, `universes.yaml`, `universe.py` (only if needed), and the two test
   files.

## Rules
Local data only: no internet, no paid APIs, no live DB writes. Open source DBs `mode=ro` / `connect_ro`.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_universe_builder
```

## Budget
≤ 15 tool calls before the first edit; ≤ 110 total; $0 paid.

## Report
1. Changes (file:line)  2. Per-theme tables, precision, weighted members by source  3. Gaps/overlaps
4. AR cap experiment  5. Tests  6. Open problems  7. Tool calls.
