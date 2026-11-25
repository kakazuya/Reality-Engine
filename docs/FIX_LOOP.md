# Fast fix loop (T-233, 21 Nov 2026)

Shivam: *"we waste too much time rebuilding stores and re-running everything per fix; build only the parts that
broke and test that nothing else broke."* A fix round used to re-run all 91 stores and Wolf re-sampled 50 random rows.
Now a round is: **write a selector → run the scoped pass into a copy of the baseline → run the golden gate → read only
the changed rows → merge only at zero newly broken.** No model call for the gate; seconds, not hours.

## The loop, five lines

```bash
# 1. selector: the stores / documents / pages (or a SQL row predicate) the fix touches
echo '{"stores":["c32.db"],"pages":[14,28]}' > .tmp/sel.json
# 2. scoped run into a copy of the baseline (the baseline is never written)
python -m reality_engine.v2.observations --recheck --out .tmp/obs_fix.db \
  --baseline D:/RealityEngine/t230/obs_91.db --only .tmp/sel.json --stores <store dirs/files>
# 3. gate: golden regression + the global diff against the baseline (exit 1 on any newly broken RIGHT row)
python -m reality_engine.scripts.regress observations --db .tmp/obs_fix.db \
  --baseline D:/RealityEngine/t230/obs_91.db
# 4. review: regress lists every changed / newly broken / ambiguous row with its Wolf source; read only those
# 5. merge only when regress prints "GATE: pass" (newly broken 0) and every changed row is the fix intended
```

The other two pipelines use the same selector file:

```bash
# filing events (T-231): re-read the selected announcements, replace just their rows in the baseline copy
python -m reality_engine.research.filing_events --out .tmp/events_fix.db \
  --baseline D:/RealityEngine/t231/events.db --only .tmp/sel.json --workers 4
python -m reality_engine.scripts.regress events --db .tmp/events_fix.db --baseline D:/RealityEngine/t231/events.db

# driver claims (T-228 stage-2c repair, model-free): re-repair the selected claims and their event fold
python -m reality_engine.research.driver_claims --repair --repair-from D:/RealityEngine/t228/claims_91_s2.db \
  --out .tmp/claims_fix.db --only .tmp/sel.json
python -m reality_engine.scripts.regress claims --db .tmp/claims_fix.db \
  --baseline D:/RealityEngine/t228/claims_91_s2.db
```

`reality_engine/research/selector.py` is the one selector. A JSON object with any of `stores` (name or path,
`c32` and `c32.db` are the same store), `doc_keys` (value or prefix: an 8-character prefix from a Wolf read is
enough), `pages` (page numbers) and `where` (one SQL predicate over the output table's own columns). Every field
is optional, a row must satisfy all that are present, and an **empty selector is refused**: a scoped run that is
not scoped is the waste this exists to remove. `--baseline` copies that DB to `--out` first (`copy_db`; the copy is
byte-identical outside the selection) and a scoped re-read replaces only its own pages/documents, so nothing else
moves. The observations `--recheck` path filters both pages and rows (the `where` goes into the row query); a re-read
re-processes exactly the selection (no seeded sampling, no `--limit` cap) and deletes those pages' old rows before
reading. At the end of a `--recheck`, `observations.dedupe_repeats` (T-242) keeps one row per exact repeat, preferring
the `verified` row and then the lowest `observation_id`; the key is the row's whole printed content, so two distinct
statements of one speaker or two differently labelled figures on a page (`Total 0`, `North 0`) are not repeats. It is
scoped to the selected pages when `--only` is given and reports its count in `stats["repeats_dropped"]`.

## The golden sets

`reality_engine/tests/golden/{observations,claims,events}.jsonl` — one JSON line per hand-graded row or page, parsed
from every Wolf read and keyed by **what the document prints, never by a database id** (a rebuild renumbers ids):

| pipeline | golden lines | RIGHT | MINOR | WRONG | sources |
|---|---|---|---|---|---|
| observations | 265 (254 rows + 11 pages) | 170 | 53 | 31 rows + 11 page lines | `t230/wolf_read_b.md`, `wolf_read_c.md` (incl. its 10 `no_period` rows), `wolf_read_d.md` (both tables), `wolf_visual_audit.md` (11 page predicates), `t232/wolf_read_decks394_a.md` (60 new-company rows), `t230/stageK_read/grade{1,2,3}.md` (24 annual-report rows, stage L) |
| claims | 146 | 50 | 48 | 48 | `t228/wolf_read_91_s2.md`, `wolf_read_91_s2c.md`, `t228/s2a/wolf_read_s2a.md` |
| events | 69 | 60 | 8 | 1 | `t231/t231_wolf_read_a.md`, `wolf_read_b.md` |

One golden file now serves several DBs: `regress` grades only the lines about documents the DB actually holds (the
symbol set comes from the DB's own `symbol` column and the document set from its `doc_key` column) and reports the
rest as `skipped_other_db`. The per-document skip (stage L) keeps the deck and annual-report gates green when both
reads cover the same 91 symbols but different documents. An empty DB keeps every line, so a vanished row is still
caught.

A row line carries `key` (the strict content key: symbol/store, full `doc_key`, page, measure/label/printed value or
normalised quote, `known_at`), `identity` (the same without the fields a fix changes, so a corrected row is still
found), `grade`, `status` at grading time, `defect`, `source` (read and row number) and `note`. A RIGHT line has
`expect` — the fields the read verified (measure, unit, scale, period, kind, scope; for claims node/segment/value/unit;
for events the amount). A MINOR/WRONG line has `wrong` (the graded row's fields, so movement is visible) and, where the
read states the fix, `expect` with the corrected value (`<nonempty>`, a list of allowed values, `null`, or the exact
number). A page line (`kind:"page"`) forbids a defect row on one page with a `max`: the known defect may shrink to
zero, never grow past the graded count.

**91.0 % of the graded rows (445 of 489) key back to a row in the evidence DBs.** What does not: 13 stage-2a claims
(their pilot DB was a superseded extraction; the same quote was re-extracted in stage 2 with different ids and 27 of
40 matched, the rest are excluded rather than guessed), and 31 event rows (Wolf read the stage-A `events.db` with 440
events; the current file is stage C with 604, so event ids and rows moved — 69 unique rows matched by content, 11 were
ambiguous on symbol/kind/amount and 20 were absent or changed between stages). The observations read key 100 % because
their ids and content survived in `obs_91.db`; 10 rows whose id did not were found by printed content (`symbol`,
`doc_key` prefix, page, printed value), and the 60 new-company rows were keyed from the post-stage-I copy by the same
printed content.

`regress.py` classifies every line: **still_right** (RIGHT, every expected field holds), **newly_broken** (RIGHT row
gone, a graded field changed, or it lost `verified`), **fixed** (WRONG/MINOR now meets the stated fix), **still_wrong**
(unchanged), **changed** (moved, but not to the stated fix — review it), **gone** (a WRONG/MINOR row no longer
emitted: often the fix, read its note), **ambiguous** (the identity matched several rows and none meets the
expectation). The exit code is 1 only for a newly broken row; `--baseline` adds rows added / removed / status changed
by measure (observations), node (claims) or kind (events), and `--json` dumps the whole report.

Baseline runs on 21 Nov 2026 (read-only, no model):

| command | result |
|---|---|
| `python -m reality_engine.scripts.regress observations --db .tmp/t230i/obs_91_i.db` | still right 118, fixed 18, still wrong 34, changed 11, **newly broken 0**, 2 s (60 lines skipped: companies not in this DB) |
| `python -m reality_engine.scripts.regress observations --db .tmp/t238/obs_ocr_read.db --baseline D:/RealityEngine/t230/obs_91_i.db` | T-238 scoped OCR read (372 pages added to a copy of `obs_91_i.db`): **newly broken 0**, added 7,174, removed 0, status changed 0, 5 s |
| `python -m reality_engine.scripts.regress observations --db .tmp/t230i/obs_decks394_i.db` | still right 40, fixed 14, still wrong 6, **newly broken 0**, 0.5 s (181 lines skipped) |
| `python -m reality_engine.scripts.regress claims --db D:/RealityEngine/t228/claims_91_s2c.db` | still right 50, fixed 14, still wrong 82, newly broken 0, 0.2 s |
| `python -m reality_engine.scripts.regress events --db D:/RealityEngine/t231/events.db` | still right 60, fixed 1, still wrong 8, newly broken 0, 0.01 s |

The one newly broken row was the first real catch, not a tool error: Wolf graded RSYSTEMS "EBITDA for Year 2024 is
Rs. 2,611 mn" RIGHT as `ebitda` (read B #35, id 39223); `obs_91.db` stored it as `ebitda.delta` (row 118618), the same
level-as-delta defect the visual audit flags on POLYPLEX. **T-230 stage H fixed it** (the bridge cue must be printed on
that series, and only a waterfall's middle bars are steps): the scoped recheck
`.tmp/t230h/obs_91_h.db` against `D:/RealityEngine/t230/obs_91_g.db` gates at still right 118, newly broken 0, fixed 18,
still wrong 37, changed 8 (details: `docs/V2_SCHEMA_CONTRACT.md` section 17, stage H). `test_regress.py` keeps the gate
honest with a synthetic DB: a RIGHT row changed or vanished exits 1, a stated fix prints `fixed`, a defect that grows
past its page count exits 1.

Stage L (22 Nov) added the per-document skip and a golden line for the annual-report read: a line about a document
the DB does not hold is `skipped_other_db`, not newly broken (the deck and annual-report reads share the 91 symbols).
The annual-report gate therefore grades exactly its 24 hand-read rows (`docs/V2_SCHEMA_CONTRACT.md` section 17.z):
still right 10, fixed 10 (all four WRONG rows), still wrong 2, changed 1, newly broken 1 -- NELCAST, whose RIGHT value
was verified only by an all-zero parts sum the stage-L rule removes (the row is still stored; see 17.z).

## Costs and tests

- The gate is model-free and reads one SQLite file: 0.03–0.2 s per pipeline on the 91-store outputs; adding
  `--baseline` diffs every row (102,074 observations on the 91 base and 27,801 on the decks394 base, 10,102 claims,
  604 events) and takes about 2–3 s on observations.
- A scoped observations re-read still calls the reader once per selected page; a `--recheck` round calls no model,
  fetches each document's PDF once (`raw_store.keep()`), and exits 2 when it reads 0 pages, so an empty `--out` can
  never look like a clean pass (T-238 N2).
- Tests: `python -m pytest reality_engine/tests/test_regress.py -q` → 19 passed (content-key match after an id change,
  newly-broken detection, fixed/still-wrong/changed, page growth, baseline diff, selector filtering, empty-selector
  refusal, copy protection, a golden line about another company skipped, the scoped observations recheck and event
  merge hooks, and that the shipped golden files parse). The untouched pipeline suites also pass:
  `test_observations.py`, `test_filing_events.py`, `test_driver_claims.py` → 276 passed (stage I added 10 observation
  tests, stage J 3 more and 1 regress test, stage K 10 observation tests, stage L 8 observation tests).
- A new hand read is added by appending its lines to the matching JSONL with the same fields; do not re-key a line
  because a fix changed a field — that change is exactly what the gate reports.
