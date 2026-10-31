# Answer labels: a change is not a level, a derived value names its inputs (31 Oct 2026)

Task: `tasks/dsh_tasks/V4_ANSWER_LABELS_2026-10-31.md`. Code: `reality_engine/query/v4/`
(`execute.py`, `render.py`, `fact_view.sql`), `build_membership.py`, `build_t1.py`,
`tasks/arch_v3/SCHEMA_V3.sql`. Grader, bank and stores untouched.

## The five defects and what the code now does

1. **A change printed as a level.** `render._measured` printed every scalar under its
   atom's name, so a `change`/`pct_change` result read as a level (MB1033#L:
   `price.close: 359.1` for a close of 3,166.50). A change is now
   `<atom> change: <delta> (from X on d1 to Y on d2); window ...`. `_delta` also
   refuses a difference over rows of more than one entity (MB0634 compared wb_coal and
   wb_zinc; 46 parts became typed NIDs).
2. **Wrong source on a ratio.** `f.ratio` took the source of the registry's first
   `over` atom, which for a P/B was the debt source. The formula now declares the
   atoms its own body reads (`FORMULA_INPUTS`), keeps only those in `inputs`, and
   writes `derived:f.ratio(pb):price.mcap+fin.book_equity` (kind named too). The block
   prints `f.ratio (pb)` and each input with its period. Period and `known_at` are
   now the arithmetic's own inputs, not a possibly unrelated atom's.
3. **A stale value offered as current.** Already typed NID by merge `c0123f4`; this
   change adds the age in days to the fresh-latest assumption and keeps the typed
   sentence for an over-limit row (MB0997#MS: capex 2021-03-31, 2,028 days, 400-day
   limit).
4. **Impossible or unstatable values.** `f.share_of` over 100% is now a typed NID
   naming part, whole and periods (MB0974#MI: 4,357.91%). `list_distinct` of value
   over 50 distinct items is a typed NID (MB0525: 4,357 distinct values on 7,062
   rows); an empty value becomes a typed NID instead of `—`.
5. **Close, open, high and low on different bases.** The T1 build computed
   `raw_close` only to derive `mcap_cr` and then dropped it; the pilot store had no
   raw close. Fix: `build_t1.py` now persists `company_state_daily.raw_close`
   (`tasks/arch_v3/SCHEMA_V3.sql` declares it), `fact_view.sql` loads
   `price.close` from it with `basis=raw`, and `price_basis` uses the held
   share-count steps to adjust a return at query time. A level names its basis; an
   old store's `price.close` is named **adjusted**, never raw. `near_high` uses one
   basis for the high and the close (on the old store: the adjusted close; after the
   rebuild: the raw high and raw close). `gap_type` refuses a raw open against an
   adjusted previous close when a held action moved it.

## Counts

Condition of the gate file when the ticket was written (13:08 strict file, before
the staleness and price-basis merges): rows with each symptom —

| class | results | rows |
|---|---:|---:|
| change printed as a level | 218 | 181 |
| ratio with the wrong source | 55 | 49 |
| stale latest offered as current | 97 | 89 |
| share > 100% | 8 | 8 |
| no stateable value | 13 | 13 |
| `price.close` level on the adjusted basis | 236 | 229 |

Union 461 rows.

Gate rerun, same code at HEAD (`17234a4`) vs this branch, 2,681 rows:

| | HEAD | this branch |
|---|---:|---:|
| contract strict (`covered`) | 341/2,681 = 12.7% | **327/2,681 = 12.2%** |
| real_answered parts | 1,523 | 1,468 |
| PIT breaches | 0 | **0** |

The published `GATE_RESULTS_v4_strict.jsonl` was regenerated from main at 14:36 with
the same result as the HEAD run (341), so the comparison is like-for-like. The
contract count falls by 14 cases because 64 parts that printed a false or
unstatable value are now typed failures: 46 a change over several entities, 10 an
unstatable list, 4 a share over 100%, 4 an empty value. Four `near_high` studies
changed value because the study now uses one basis (the adjusted close) on the old
store; the number of qualifying sessions is not comparable to the old mixed-basis
count.

Changed rows: **937** (answer or result fields). Overlapping tags: 209 change now
labelled, 182 close basis named, 176 formula selector named, 67 ratio kind and
inputs, 25 stale-latest typed, 10 unstatable list, 8 impossible share, 4 empty
value.

Seeded read-back (`tasks/pilot60/v4_changed_rows.py --before <HEAD run> --after
<branch run>`, seed 20261031): 20 changed rows, 57 claims re-derived with direct SQL
on `fact_v4_pilot.db` (never through `execute.py`), all PASS, PIT breaches 0. The
seed-20261031 sample: MB0330#L, MB0272#MS, MB0999#MS, MB0978#MI, MB0457#P,
MB0064#MI, MB0768#P, MB0033#MI, MB0243#L, MB0274#MS, MB0634, MB0249#MS, MB0923#P,
MB0124#L, MB0102#L, MB1072#MS, MB1004#P, MB0890#MS, MB1051#MI, MB0996#MS. The full
changed list is in the branch report (`--json .tmp/changed_vs_head.json`).

## Controller steps: the one store build still required

A level can only be the traded close after the T1 pilot file carries `raw_close`.
The v4 fact store cannot be fixed in place (read-only, and the source column is
missing). On a machine with the pilot stores:

```bash
# 1. T1 rebuild IN PLACE (back up market_state_pilot.db first). company_state_daily
#    gains raw_close; the schema is additive and the rows are the same.
python -m reality_engine.pilot.build_t1 --universe pilot \
    --out reality_engine/data/pilot/pilot60
# expect: company_state_daily 7,258,000 rows; raw_close filled wherever the source
#   px_daily.close was

# 2. v4 fact view rebuild from the rebuilt T1 file, written to .tmp then installed.
python -m reality_engine.query.v4.build_membership \
    --root reality_engine/data --out .tmp/fact_v4_pilot.db \
    --oi-out .tmp/fact_v4_pilot_oi.db
# expect: 103,313 price.close fact rows (one per pilot ISIN/session) on the raw
#   basis; the hand check re-reads raw_close from company_state_daily.
# copy .tmp/fact_v4_pilot.db (and, if rebuilt, _oi.db) into
#   reality_engine/data/pilot/v4/

# 3. Re-run the gate on the rebuilt store; price.close levels must say
#    "raw close: price.close is the traded close", never "adjusted".
```

Affected row count: **103,313** `price.close` fact rows (60 ISINs; the same count
as `price.mcap`), plus the 7,258,000 T1 `company_state_daily` rows rebuilt with one
added column. Rows whose adjusted value differed from the traded close change
value; the rest change only their label. Do this before reading any price level as
truth.

## Open problems

- The v1 query planners still read `company_state_daily.close` as a level
  (`reality_engine/query/planners/series.py`, `screen.py`). They are outside this
  task and unfixed.
- No PIT corporate-action atom: a demerger does not change `shares_out`, so an
  unexplained fall stays a typed NID and cannot be adjusted.
- The old store's `price.close` remains adjusted until the rebuild; every affected
  answer now says so, but a level before an action is still not a traded price.
