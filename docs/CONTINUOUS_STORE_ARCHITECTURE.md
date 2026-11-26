# Continuous store architecture (Shivam, 26 Nov 2026)

The database is never finished. New models arrive every few weeks on OpenCode Go and other gateways, prompts and
gates improve, filings keep arriving, and tools and analysis methods change. Every part below can be re-run,
replaced, added to or deleted at any time without a rebuild. Reading never stops for a grade; quality is measured
and improved alongside (ruling in `tasks/RULINGS.md`).

## Layers (each one append-or-replace, none overwrites the layer below)

| # | Layer | Where | Changes by |
|---|---|---|---|
| 0 | Raw documents | Drive `gdrive:InfoDiffusion_archive` (raw_store) | new filings only; never edited |
| 1 | Page text | store `doc_page` (text layer, OCR) | re-OCR a page = new row version, old kept until checked |
| 2 | Reads | one hy4-style output DB per reader + prompt fingerprint (`D:/RealityEngine/hy4_out/*.db`), `page_reply` raw | a new model or prompt writes a NEW output DB beside the old; nothing is re-read in place |
| 3 | Checks | verdict files keyed by (output DB, observation_id): `row_checks`, `D:/RealityEngine/checks/xbrl/*.jsonl` (`reality_engine/v2/xbrl_crosscheck.py`), Sonnet/model settles, grade packs | any checker can be added, re-run or dropped; a verdict never edits the read |
| 4 | Election + load | `reality_engine/scripts/load_observations.py`: per symbol and source, which output DB serves, status after the >10% cap and the check verdicts | change the priority list or a rule, reload touched symbols only (`.tmp/load_symbols.py`) |
| 5 | Serving | store `obs_fact` + structured tables, `reality-data` MCP tools | tool versions change; the retrieval audit compares old vs new before a swap |
| 6 | Analysis | factor runs, forecasts | re-run on any as-of date; every input row carries provenance |

## Rules that keep it changeable

1. **Provenance on every row**: source doc + page, reader id, prompt fingerprint (`read_gate.fingerprint`), read_at,
   check verdicts with checker name. A row can always be traced, re-checked or withdrawn.
2. **New reads go beside, not over**: a new model/prompt reads into its own output DB; the loader's priority list
   decides which serves, per company, so a better reader replaces the old one company by company.
3. **Verdicts are separate from reads**: status = read gate x checks. Promotion (e.g. a filed-XBRL match) and demotion
   (contradiction, >10% graded sample) happen at load, so a wrong checker is fixed by fixing the checker.
4. **Soft delete**: withdrawing a source or a check = remove it from the priority list or verdict set and reload the
   touched symbols. Nothing is destroyed; backups `*_before_<change>_<date>.db` beside each swap.
5. **Golden rows are permanent**: every hand- or model-graded row (all `C:/RealityEngine/t242/*/pack.jsonl` +
   grades) is a regression test: a change may not flip a graded-R row. Frozen bank and s20 exam set stay frozen.
6. **Measure, don't gate**: rolling 60-row graded samples per output DB every 2,000 pages; W+J share per doc type
   on one sheet; >10% loads that output unverified; block only when >10% of the database is corrupt.

## Model churn (a new model on a gateway)

1. Free-model bake-off (skill `free-model-bakeoff`) on the same seeded page set + golden rows: quality first,
   then speed, then quota.
2. If it beats the current reader for a doc type: register it (`extract_deck_figures.MODELS`), read a pilot of
   2,000 pages into a new output DB, grade 60 rows, add it to the loader priority list for the companies read.
3. Models also serve as checkers: two different models agreeing on a cell is evidence; disagreement goes to the
   settle queue.

## Continuous improvement loop (Claude's job)

- Script checks over all stored rows: filed XBRL (done for results quarters, 26 Nov), component sums vs printed
  totals, item-under-heading vs total, sign of loss lines, 100x jumps vs neighbouring periods.
- Defects ranked by companies hit x severity (wrong number > wrong line > wrong tag); fix = structural rule,
  recheck on a copy, swap, reload touched symbols.
- Retrieval: fresh-question audits per round; a tool change is A/B'd against live on the frozen sets.
- Unverified rows settled by the cheapest model that passes a graded sample; verdicts in the checks layer.
