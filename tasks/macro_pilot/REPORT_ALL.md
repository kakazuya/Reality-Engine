# macro_claim_target — full run over all policy events, independent check, trigger fix

Built 2026-10-29 from held data only (`equity_intelligence.db`, read-only), no network,
no paid model, no commits.  Deliverables: `.tmp/pilot_all/macro_all.db` (full run) and
this report.  The 300-claim stratified pilot (`.tmp/pilot/macro_pilot.db`) is unchanged
in scope; its reported numbers moved only where the recall fixes below add targets
(649 -> 668 targets).

**Headline.** 21,552 policy claims -> 21,552 `macro_claim` rows and 44,742
`macro_claim_target` rows, built in **10.1 s**.  Independent 80-claim check (new seed
20261029, pilot claims excluded, stratified by source): **precision 0.9940
(Wilson LB 0.9669), recall 0.9379 (Wilson LB 0.8922)** over 167 mappings.  After fixing
the defect classes the check found (same sample, in-sample): precision 0.9944
(LB 0.9689), recall 1.000 (LB 0.9788).  RIPPLE on the 58 policy-rooted ripple200 cases:
**28 -> 48 answered** versus the prior 300-claim pilot, 0 regressions; 33/33 cases whose
own template declares a `policy_events.id` now match a declared id, up from a free-text
pick that took unrelated policies.

---

## 1. Full run

Command: `python -m reality_engine.pilot.macro_claims --all`
-> `.tmp/pilot_all/macro_all.db` (+ `macro_all_meta.json`).

| measure | value |
|---|---|
| source rows (`policy_events`) | 21,552 |
| `macro_claim` rows | 21,552 (same ids, so every row diffs back to the source) |
| source documents (`macro_doc`) | 456 |
| `macro_claim_target` rows | 44,742 |
| targets per claim | 2.08 |
| claims with >= 1 target | 18,082 (83.9%) |
| claims with no target | 3,470 (generic sector list: "all sectors", "MSME", "exports", "public finance", or no held industry) |
| runtime (read + extract + SQLite write) | **10.06 s** |

Targets per type:

| kind | rows |
|---|---|
| basic_industry | 24,420 |
| sector | 11,971 |
| state | 7,520 |
| theme | 545 |
| isin | 286 |

By source stratum: state budget 7,520; Union Budget 5,822; other 5,713; RBI 2,120;
PIB 319; standalone tariff 58.

`quote_ok`: **20,970** rows clean, **582** flagged `quote_ok=0`.  The flagged rows are
kept (the brief says prefer, not drop) and travel with `macro_claim.quote_ok`;
their `confidence` is 0.7 with targets / 0.2 without, against 1.0 / 0.3 for clean rows.

Same DDL as the pilot: tables created from `tasks/arch_v3/SCHEMA_V3.sql` via
`build_t1.create_schema`, plus the six pilot columns (`paraphrase`, `known_at`,
`stratum`, `conditions`, `quote_ok`, `effective_pit_conf`).  21,552 rows were
deterministically identical on a second build.

## 2. Independent check

**Sample.** Seed **20261029**, 80 claims, the 300 pilot-claim ids excluded first,
stratified by source class (state budget 25 across 20 states, Union Budget 20,
Economic Survey 18, RBI 12 = 4 annual report / 4 policy / 4 minutes, PIB 5).
The sample and its emitted targets are in `review_all.json`; the hand judgement is
`labels_all.json`; reproduce with `sample_all.py` + `score_all.py`.

**Standard used.** Judged from the claim text, its declared sectors/products/companies
and the source document (PIB body where the store holds it, else the doc title):
a mapping is correct when the claim plausibly moves demand, cost or regulation for that
held sector / basic industry / ISIN / theme, including the second-order input demand the
claim itself declares.  A generic term (all sectors, exports, MSME, trade, public
finance) is not a miss.  Neither the old labels nor the alias lists were used as truth:
the labels below were written from the 80 claims first, then compared with the
extractor's output.

**First pass — the extractor as it stood before any fix: 167 mappings.**

| | TP | FP | FN | precision (95% Wilson LB) | recall (95% Wilson LB) |
|---|---|---|---|---|---|
| all 80 claims | 166 | 1 | 11 | **0.9940 (0.9669)** | **0.9379 (0.8922)** |

10 of the 80 claims emitted no target; 5 of those correctly (employment/recruitment,
cross-sector deregulation, an income-tax simplification, a police allocation, a revenue
deficit grant line with no held industry).

**Every miss, with its reason** (11 mappings over 9 claims — all one defect class,
sector-term alias coverage, plus one compound-string defect):

| claim | missing target | why |
|---|---|---|
| 11439 | `basic_industry:Other Bank` | "Co-operative Banking" has no alias |
| 21494 | `sector:Automobile and Auto Components` | "auto" is not a key (only automobile/automotive/ev) |
| 4093 | `sector:Information Technology` | "IT / AI": slash compounds were split only inside parentheses |
| 4815 | `basic_industry:Seafood` | "fisheries" has no alias |
| 15844 | `basic_industry:Aerospace & Defense` | "Drones" has no alias |
| 17310 | `basic_industry:Aerospace & Defense` | "drone" (singular) has no alias |
| 5510 | `basic_industry:Gems Jewellery And Watches` | "jewellery" existed only as a tariff product term |
| 5890 | `basic_industry:Logistics Solution Provider` | "Transportation" has no alias |
| 8174 | `basic_industry:Other Bank` | "Banking & Financial Services" resolved through a whole-string key to Financial Services only; the banking half was dropped |
| 8174 | `basic_industry:Private Sector Bank` | same |
| 8174 | `basic_industry:Public Sector Bank` | same |

**The one false positive:** claim 19524 (an RBI circular that extends a regulation
*to* regional rural banks and small finance banks, i.e. `Other Bank` and
`Private Sector Bank`).  The generic sector term "Banking" also emits
`Public Sector Bank`, which the quote excludes.  Not fixed: narrowing a generic sector
term by the quote needs a semantics step this deterministic pass does not have; it is
one mapping in 167 and is the deliberate ceiling noted in §7.

**After the fixes — same 80 claims re-extracted (in-sample, not a fresh holdout):**
178 mappings; 177 TP, 1 FP, 0 FN -> **precision 0.9944 (Wilson LB 0.9689), recall
1.000 (Wilson LB 0.9788)**.  The diff is exactly the 11 missing mappings above; no
previously emitted target was removed, so the recall fix added nothing wrong on this
sample.  `review_all_after.json` holds that pass.

## 3. RIPPLE on the 58 policy-rooted ripple200 cases

Set: the same 58 cases the prior report measured (chain root, template or question names
a policy/budget/RBI/tariff/PLI/FDI instrument).  Only the RIPPLE hop is run; the other
hops are blocked by stage-3 tables this pilot does not build.

| configuration | RIPPLE ok | cases with target ISINs | target ISINs | gaps |
|---|---|---|---|---|
| held planner (free text, no claim-target table) | 0 / 58 | 0 | 0 | `company_sector_pit` 58 |
| old trigger + 300-claim pilot (prior report) | 28 / 58 | 24 | 240 | none 28, `company_sector_pit` 30 |
| new trigger + 300-claim pilot | 36 / 58 | 36 | 336 | none 40, `company_sector_pit` 18, no match 4 |
| **new trigger + full table** | **48 / 58** | **45** | **426** | none 52, `company_sector_pit` 3, `macro_claim_target` 3, no match 4 |

Regressions: **0**.  By archetype (before -> after, full table): R01 0->2, R02 0->11,
R03 0->7, R04 0->6, R05 0->4, R06 0->0, R07 0->4, R08 0->8, R09 0->3, R10 0->3.
Artifacts: `ripple_before_after.json` (old trigger), `ripple_before_after_pilot_newtrigger.json`,
`ripple_before_after_all.json`.

**Trigger accuracy.** 33 of the 58 templates name a `policy_events.id=...`; the new
trigger matches a declared id in **33/33**.  The old free-text match took an unrelated
policy in most of them: the coal/freight case MB0642 matched the Tamil Nadu budget; the
repo case MB0655 matched the WACR claim instead of the repo claim; MB0651 (Union Budget
data centres) matched the February MPC minutes.  The 25 cases with no declared id are
matched on issuer + date + topic only.

**10 still blocked, and why:**

| case | matched | why blocked |
|---|---|---|
| MB0734, MB0780, MB0823, MB0824 | none | corporate-action / scheme scenarios (stock split, demerger, PLI approval) whose root is not a policy claim; refusing beats a wrong policy |
| MB0668 (16th FC grants), MB0762 (PLI application), MB0819 (Budget speech) | a Union Budget claim | claim matched but its sector list is generic -> no held industry |
| MB0686 (rupee/DAP), MB0711 (PLI module price), MB0800 (cement/GST) | a state-budget claim | undated, issuer-less questions still match a topically adjacent state budget; these are the remaining trigger defect (§7) |

**Prose effective dates.** `iso_effective` now handles prose and returns a date plus a
confidence: exact ISO 1.0, dotted/`YYYY-MM` 0.95, fiscal year or FY span 0.9,
month+year 0.85, "end of 2026" 0.6, lone month / lone year / "next financial year" 0.55.
8,215 claims have a parsed effective date (7,870 at >= 0.9, 345 prose at < 0.9); the
other 13,337 source rows carry no effective date at all.  `macro_claim.effective_pit_conf`
stores the confidence; the RIPPLE market window anchors on the effective date only when
it is <= as_of and pit_conf >= 0.7, otherwise on publication (the day the market learns of
the policy), and the hop detail prints the `pit_conf` it used.

## 4. Defects fixed

Extractor (`reality_engine/pilot/macro_claims.py`):

1. **Alias gaps** from the independent check: `auto`, `ai`, `fisheries`/`fishing`/
   `aquaculture`, `drone`/`drones`, `jewellery`/`jewelry`, `transport`/`transportation`,
   `co-operative banking` / `regional rural banks` / `small finance banks`.
2. **Compound strings**: `/`-separated sector terms are split outside parentheses
   ("IT / AI"); "Banking & Financial Services" keeps the banking half (3 bank basic
   industries + Financial Services) instead of dropping it.
3. **Prose effective dates** parsed with `pit_conf` (see §3) and stored.
4. **quote_ok** carried on every claim; flagged rows kept, down-weighted.
5. Full-run mode (`--all`) over every row, same DDL, deterministic and re-runnable.

Trigger (`reality_engine/query/planners/ripple.py`):

6. The case's own declared `policy_events.id=` (template) is matched first, PIT-checked.
7. Free-text candidates must pass **issuer** (RBI / Union Budget / state budget /
   Economic Survey / tariff / PIB, inferred only when the ask names one), **date window**
   (a named window plus its lookback; one-year recency when the ask only has a decision
   date) and **topic overlap** (at least one non-generic term; macro fillers such as
   budget/order/scheme/shares cannot trigger a match alone).
8. Candidates are scored: 3 per title/policy-name hit + 2 per declared-field hit
   + 2 for issuer match + 2 for the exact decision day; ranked in SQL by hits so a
   generic term cannot push the topical claim past the row limit.
9. Market window anchor uses the parsed effective date + `pit_conf` (see §3).

## 5. Files

| file | what |
|---|---|
| `reality_engine/pilot/macro_claims.py` | all-claims mode, prose effective dates + `pit_conf`, `quote_ok`, alias fixes, compound splitting |
| `reality_engine/query/planners/ripple.py` | mocked-free trigger: declared id, issuer + date + topic gates, scoring, `pit_conf`-aware market anchor |
| `reality_engine/tests/test_macro_claim_target.py` | 35 tests (was 21): prose dates, alias fixes, all-mode + quote_ok flag, trigger gates |
| `tasks/macro_pilot/sample_all.py` | seed-20261029 stratified 80-claim sample; `--ids-from` re-extracts the same ids |
| `tasks/macro_pilot/score_all.py` | precision/recall + Wilson lower bounds from the labels |
| `tasks/macro_pilot/labels_all.json`, `review_all.json`, `review_all_after.json` | independent sample, hand labels, post-fix pass |
| `tasks/macro_pilot/run_before_after.py` | 58-case runner (`--db`, `--out`) |
| `tasks/macro_pilot/ripple_before_after{,_pilot_newtrigger,_all}.json` | the three measured configurations |

Verification:

```
python -m unittest reality_engine.tests.test_macro_claim_target   # 35 tests, OK
python -m reality_engine.pilot.macro_claims --all                 # 21,552 claims, 44,742 targets, 10.06 s
python tasks/macro_pilot/sample_all.py                            # seed 20261029, 80 claims
python tasks/macro_pilot/score_all.py                             # 0.9940 / 0.9379 + Wilson LB
python tasks/macro_pilot/run_before_after.py --db .tmp/pilot_all/macro_all.db \
    --out tasks/macro_pilot/ripple_before_after_all.json          # 48/58
```

No live database was written; every write is under `.tmp/` and `tasks/macro_pilot/`.

## 6. What this does not fix

- The stage-3 chain tables (`company_cost_structure`, `company_segment_pnl`,
  `company_price_revision`) are still not held, so an answered RIPPLE hop is still a
  partial chain answer; the hop names the missing stage.
- `universe_membership` is still not built, so theme targets are emitted but resolve to
  "membership table not held".
- State targets resolve only where a state has listed companies in the held industry
  tables; the planner reports "state target '<state>' has no held ISIN map" otherwise.
- One mapping in the independent check is still over-broad (generic "Banking" ->
  Public Sector Bank when the quote narrows the segment).  Narrowing generic terms from
  the quote needs a semantics step this deterministic pass does not have.
- Undated, issuer-less scenario questions (7 of the 58) can still take a topically
  adjacent policy, and 3 of those were already blocked on mapping; the hop detail names
  the trigger so the wrong pick is visible.  A declared evidence id removes this.
- Direction is inherited from the claim; a safeguard duty *cut* matched to a case about
  a duty *imposed* keeps the right industries but the claim's direction, not the
  scenario's.
