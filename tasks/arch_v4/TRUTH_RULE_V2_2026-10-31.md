# Truth rule v2 — the store-backed grader, 2026-10-31

The read grade (`tasks/arch_v4/TRUTH_READ_GRADE_2026-10-31.md`) read 127 answered panel
rows and found **0 RIGHT**. The old rule called 4 RIGHT, all false, because its RIGHT
branch never compared a value with a store. This change makes the rule grader agree with
that read by construction: a RIGHT now needs a separate store read of the same entity,
measure, period and value, plus every part of the question answered. It is stricter, not
higher. The read grade stays the authority until a read of later answers agrees with the
new rules.

## What changed

| # | change | file | direction on the number |
|---|---|---|---|
| 1 | **RIGHT compares a value.** Every measured part is re-read from `fact_v4_pilot.db` by entity / atom / period / dims; `|answer − store| <= max(0.005, 0.5% × |store|)`. A mismatch is `WRONG TRUTH_VALUE_WRONG`; a value the store cannot settle (text, estimate, ambiguous slice, rounded share count) is `PARTIAL TRUTH_VALUE_UNVERIFIED`. | `tasks/answer_bench/truth_grade.py` | **down**. All 4 old RIGHTs are not RIGHT; the 111-question replay has 0 RIGHT. |
| 2 | **ILL_POSED is a verdict** from the premise audit (`verdict=false`) and the entity-text mismatch check, reported in its own column, never RIGHT, **still in the denominator**. | `truth_grade.py` (`premise_verdict`), `gate_run.py` (`_panel_summary`, report) | **down** as RIGHT (never contributes); moves rows out of WRONG/PARTIAL into ILL_POSED. The denominator is unchanged. |
| 3 | **Lexical rubric retired as a verdict input.** `truth_verdict` no longer reads `required_steps` or `forbidden`. `ground_truth` votes only when it contains a number and the answer carries that number. `rubric_score` / `--rubric40` remain a diagnostic only. | `truth_grade.py` | **down**: 30 answered rows that the rubric could pass no longer get a verdict from it. |
| 4 | **`SHAPE_JUDGEMENT_NO_RULE` split.** A premise-false judgement row returns ILL_POSED first; the panel row drops the judgement shape failure and carries `premise` evidence. | `truth_grade.py` | no change to RIGHT; moves ~half of the check's rows to the ILL_POSED column. |
| 5 | **`SHAPE_COMPARE_ONE_SIDE`**: a one-entity "stored vs computed" / "P/B now vs stored" ask is two measures, not two companies. The check is skipped; the row still needs both sides (`measure_shortfall` → `PARTIAL TRUTH_MEASURE_MISSING` if only one value is shown). | `truth_grade.py` | **up** on shape-pass, **not** on RIGHT. This is the only change that could let a row through, and it does not: all three affected rows stay PARTIAL. |
| 6 | **Panel rows carry `answer_full`** beside the 400-character `answer`. | `truth_grade.py` (`_panel_row`) | display only; no verdict change. It removes the truncation that hid 82 of 127 later parts from a reader. |

### Rows affected by `SHAPE_COMPARE_ONE_SIDE`

The read-grade questions that contain a same-entity measure comparison are four:

| mid | question | read | old rule | new rule |
|---|---|---|---|---|
| `MB0004#L` | P/B now vs stored | PARTIAL | PARTIAL (`vs stored` was already exempt) | PARTIAL, no change |
| `MB0064#L` | IDEA pb ratio stored vs computed | PARTIAL | WRONG (`SHAPE_COMPARE_ONE_SIDE`) | PARTIAL (`TRUTH_MEASURE_MISSING`) |
| `MB0064#MI` | TIRUPATIFL pb ratio stored vs computed | PARTIAL | WRONG | PARTIAL |
| `MB0064#MS` | GMRAIRPORT pb ratio stored vs computed | PARTIAL | WRONG | PARTIAL |

Only the three `MB0064` rows change verdict, and they move **toward** the read, not to
RIGHT. No row in this class can be RIGHT while it shows one side.

## Tolerance and the store read

- Tolerance: `|answer − store| <= max(0.005, 0.005 × |store|)` (0.5%), stated once at
  `VALUE_TOLERANCE_ABS` / `VALUE_TOLERANCE_REL` in `truth_grade.py`.
- The store is opened `mode=ro&immutable=1`, by `entity_id` / `atom` / `period_end`, with
  the result's named dims applied only where the stored rows actually carry that dim.
  The answer's `source_ref` is never used as the value.
- Operators covered: `value_at`, `series`, `last_visible`, `first_visible`, `change`,
  `pct_change`, `growth`, `max_with_date`, `min_with_date`, and `f.cagr` (recomputed from
  the store's closes at the question's stated end date and `N` years back).
- Deliberately **unverified** (→ PARTIAL, never RIGHT): `claim.claim` / `text.passage`
  (no numeric value), estimates, unknown formulas, `price.shares_out` (the fact store
  holds the XBRL-rounded count, not the exact filing count), and multi-entity operators
  (`rank`, `compare`, `count`, `aggregate`, `list_distinct`, …).
- `f.cagr` is the MB0106 fix: the old answer started at the 3 Oct 2023 close (250.90);
  the store's last close on or before 30 Sep 2023 is 242.80, which gives **17.03%**, not
  the answer's 15.80%.

## Validation

### Tests

```
python -m pytest reality_engine/tests/test_v4_truth_grade.py -q
# 59 passed, 1 skipped (the skipped test needs the gitignored raw run in the worktree)
```

The acceptance checks are in the file: a wrong value is not RIGHT (`MB0106#MI` class), a
half answer is not RIGHT (`MB0031#MS` class), a matching value with every part met is
RIGHT, and an ILL_POSED row stays in the denominator and is never RIGHT.

### The 111 read-graded questions

The raw panel run (`GATE_RESULTS_v4_strict.jsonl`) is **not in this job**, so the full
read × new table cannot be produced here. Two honest partial runs were done on the same
111 `TRUTH_PANEL_READ` mids:

**(a) Premise + coverage projection** — the blind panel rows (question, entity, contract
status), no `results` column, so the store check cannot run. This is what the rules can
settle from the row record alone:

| read \ new | RIGHT | PARTIAL | WRONG | ILL_POSED | total |
|---|---:|---:|---:|---:|---:|
| RIGHT | 0 | 0 | 0 | 0 | **0** |
| PARTIAL | 0 | 7 | 0 | 0 | 7 |
| WRONG | 0 | 60 | 6 | 0 | 66 |
| ILL_POSED | 0 | 13 | 0 | 25 | 38 |
| total | **0** | 80 | 6 | 25 | 111 |

- **0 false RIGHT** (the target).
- **25 of the 38 read ILL_POSED rows are caught** by the premise audit (23) plus the
  entity-text check (2 more: `MB1027#L`, `MB1027#MS`, via the parent-name acronym SBI).
- 13 read ILL_POSED rows are not caught: the premise audit says `cannot_check` for them
  (bonus date, filing timestamp, circuit history, 52-week-high claim, a company rename)
  and no deterministic rule reads that evidence yet. They are reported as WRONG/PARTIAL,
  never RIGHT. This is the main remaining gap.

**(b) Replay on the current store and executor** — the same 111 questions run through
`reality_engine/query/v4/run.py` now, then graded with the new rules and the real pilot
store. This is **not** the panel's raw run; it is a sanity check that the new rules
certify nothing on current answers, consistent with the read's 0/127:

| read \ new | RIGHT | PARTIAL | WRONG | ILL_POSED | total |
|---|---:|---:|---:|---:|---:|
| RIGHT | 0 | 0 | 0 | 0 | **0** |
| PARTIAL | 0 | 7 | 0 | 0 | 7 |
| WRONG | 0 | 14 | 52 | 0 | 66 |
| ILL_POSED | 0 | 4 | 13 | 21 | 38 |
| total | **0** | 25 | 65 | 21 | 111 |

The replay's 7 rows that the first draft of the rule called RIGHT were all measure
failures the old checks missed (one-day volume for a three-retest judgement, a 20-day SMA
for a 50/200-day cross, a delivery change for a "did the price hold" question). The
judgement regex now covers "did … hold / break / retest" and "is … driven / accumulation
/ intraday", and a named `N`-day average must be named by the answer's SMA result. After
those two fixes the replay has **0 RIGHT**.

### Controller command for the full table

Run this on a checkout that has the raw v4 run (it is gitignored, ~180 MB):

```bash
python tasks/answer_bench/truth_grade.py --read-check --markdown \
  --graded tasks/answer_bench/GATE_RESULTS_v4_strict.jsonl \
  --read-panel tasks/arch_v4/TRUTH_PANEL_READ_2026-10-31.jsonl
# add --store-root /path/to/pilot/v4 if REALITY_DATA_ROOT does not point at the data root
# if the raw run sits outside the checkout (the read used
# C:\Users\warri\Downloads\Info_Diffusion_Model\tasks\answer_bench\GATE_RESULTS_v4_strict.jsonl),
# pass that path to --graded instead.
```

It prints the 4×4 read × new table and JSON with `false_right`, `missed_ill_posed`,
`by_reason` and `store_available`. The same path is exercised by
`test_read_confusion_on_a_fixture` and by the CLI fixture run below.

The CLI was tested end to end on a fixture (two rows: one matching close, one ILL_POSED
premise). With the audit row supplied, as the unit test does:

```
| read \ new | RIGHT | PARTIAL | WRONG | ILL_POSED | total |
| RIGHT | 1 | 0 | 0 | 0 | 1 |
| ILL_POSED | 0 | 0 | 0 | 1 | 1 |
```

The bare CLI fixture (no audit file for the second row) reports that row as RIGHT. That
is the 13-row ILL_POSED-recall gap in section (a): the deterministic rules cannot see a
premise the audit marks `cannot_check`, and the grader must not invent one. It is never a
false RIGHT on a row the audit settles.

## What this means

- The old rule's 0.6% (6/127 answered rows in its own panel; the read's later 127-row set
  had 4 rule-RIGHTs, all overturned) is **retired**. Its RIGHT branch did not compare a
  value; the read's 0/127 stands.
- The new rules produce **0 RIGHT on all 111 read questions** in both partial runs, and
  **0 false RIGHT** against the read. They cannot raise the number: only a store-matched,
  fully answered numeric row can be RIGHT.
- The honest gap is ILL_POSED recall: 25/38. Closing the other 13 needs store rules for
  bonus dates, filing timestamps, circuit history and 52-week-high claims. Until then
  those rows are WRONG/PARTIAL, never RIGHT.

## Files

- `tasks/answer_bench/truth_grade.py` — store-backed RIGHT, ILL_POSED, rubric retired,
  judgement split, measure-vs comparison, `answer_full`, `read_confusion` + `--read-check`.
- `tasks/pilot60/gate_run.py` — panel built with the store; ILL_POSED printed in its own
  column and kept in the denominator; generated report text updated.
- `reality_engine/tests/test_v4_truth_grade.py` — the four acceptance checks plus the
  read-confusion fixture.
- `tasks/arch_v4/TRUTH_GRADE_2026-10-31.md` — banner: pre-v2 record, number retired.
- `tasks/STATE.md` — current fact.

## Docs updated

- `tasks/arch_v4/TRUTH_RULE_V2_2026-10-31.md` (new; this report).
- `tasks/arch_v4/TRUTH_GRADE_2026-10-31.md` (banner + retired numbers + rubric wording).
- `tasks/STATE.md` (gate table and findings).
- `tasks/arch_v4/GATE_V4_2026-10-31.md` (pointer to the v2 rules).
