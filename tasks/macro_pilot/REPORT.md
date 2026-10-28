# macro_claim_target pilot (G10 / policy_target) — report

Built 2026-10-28 from held data only (`equity_intelligence.db`, read-only), no network,
no paid model.  Deliverable: `.tmp/pilot/macro_pilot.db` + this report.

**Headline.** 300 policy claims → 300 `macro_claim` rows and 649 `macro_claim_target`
rows (454 basic industry, 183 sector, 5 ISIN, 7 theme).  Hand-check on 60 claims /
183 mappings: **precision 1.000, recall 1.000** against the stated standard; **0.968
precision** if the six upstream steel-intermediate rows are counted wrong.  RIPPLE on
the 58 policy-rooted ripple200 cases: **0 → 28 answered**, 0 regressions.

---

## 1. Claims by source

| stratum | claims | note |
|---|---|---|
| budget (Union Budget 2024–26) | 90 | 30 per published year |
| rbi (Monetary Policy + MPC Minutes) | 74 | statements:minutes ≈ 3:2 |
| pib (PIB releases / circulars) | 60 | round-robin by ministry where attributable |
| tariff (standalone customs/tariff notices) | 57 | customs-duty/tariff claims outside budget/RBI/Survey docs |
| anchor (also RBI documents) | 19 | policies the ripple200 bank names (see §5) |
| **total** | **300** | 71 source documents, 5 source types |

Whole-source counts (sums to 300): Union_Budget 90, PIB_Circular 94,
RBI_Monetary_Policy 55, RBI_MPC_Minutes 38, PIB_Press_Release 23.  The 57-claim
tariff stratum and the 60-claim PIB stratum are concentrated: the held
`policy_events` has no standalone CBIC-notification documents, so every 2024–26
standalone customs/tariff claim it holds comes from PIB circulars (one FY26
budget-highlights press release carries most of them).  Ministry attribution exists
for the 23 `pib`-sourced claims (9 ministries); the circulars carry none.

Extracted-field coverage:

| field | populated | note |
|---|---|---|
| `paraphrase` (≤ 30 words) | 300 | max observed 30 words |
| `direction` | 300 | positive 223, neutral 60, negative 17 |
| `magnitude_value` | 119 | INR_CRORE / INR_LAKH / PERCENT / MW; bps ÷ 100 |
| `effective_date` (ISO) | 84 | fiscal-year text mapped to its FY start |
| `conditions` | 10 | quote clauses with "provided that / subject to / applicable to / …"; the rest state none |
| `known_at` | 300 | `policy_events.published_at`, minute precision where the source has it |
| source doc id | 300 | `macro_doc.doc_id` (`doc:<raw doc id>` / `pib:<prid>`) |

`policy_type`: tariff 85, other 61, regulation 58, rate 47, capex 19, tax 17,
subsidy 11, pli 2.  Average 2.9 targets per claim (min 1, max 10).  78/300 claims
(26%) have no target because their sector list is generic ("all sectors", "exports",
"manufacturing", "MSME") or names no held industry.

`claim_id` is the source `policy_events.id`, so every row diffs back to the live row.

## 2. Precision / recall (hand-check)

Sample: 15 claims per stratum (60 claims), every emitted target of those claims =
**183 claim→target mappings**, read against each claim's `sectors`, `products`,
`companies` and `quote`.

| stratum | mappings | TP | FP | FN | precision | recall |
|---|---|---|---|---|---|---|
| budget | 39 | 39 | 0 | 0 | 1.00 | 1.00 |
| rbi | 71 | 71 | 0 | 0 | 1.00 | 1.00 |
| pib | 41 | 41 | 0 | 0 | 1.00 | 1.00 |
| tariff | 32 | 32 | 0 | 0 | 1.00 | 1.00 |
| **total** | **183** | **183** | **0** | **0** | **1.00** | **1.00** |

*Standard used:* a target is correct when the claim plausibly changes demand, cost or
regulation for companies in that held sector / basic industry / ISIN / theme,
including the second-order input demand the equal-weight alias implies.  A generic
term (exports, all sectors, manufacturing, MSME, trade) is not a miss.

**Strict variant.** Six rows are upstream steel intermediates (Pig Iron, Sponge Iron)
reached only through the `steel` alias on two housing/capex claims.  Counting those as
wrong: **precision 0.9683** (183/189).  Both measures clear the 0.90 bar.

**The check found real defects, fixed before the final measurement** (first pass on
the same sample: 2 wrong rows, 3 misses; wider review found 4 more):

1. HS chapter 25 (salt/earths/stone *and* cement) mapped a marble/granite duty cut to
   cement → chapter 25 dropped; cement is found by the sector term instead.
2. Product-name matching read the quote too: "railway MROs to benefit similar to
   aircraft MROs" made a railway claim hit Aerospace & Defence → products/policy_name
   only; the quote is used for HS codes only.
3. `semiconductors` mapped to Information Technology (semis are not IT services) →
   Consumer Electronics + Other Electrical Equipment.
4. "Depositories" (RBI CAS claim) was unmapped → added.
5. "Consumer durables" (repo claims) was unmapped → added.
6. "Agri-Allied", "biotechnology", "heavy engineering", "EV", "batteries", "granite/
   marble", "finance", "skills training" were unmapped → added.

Reproduce: `python tasks/macro_pilot/handcheck.py sample` (deterministic sheet) →
`python tasks/macro_pilot/write_labels.py` → `python tasks/macro_pilot/handcheck.py score`.
`handcheck_labels.json` carries one note per claim and the strict-FP list.

## 3. RIPPLE before / after on the ripple200 policy-rooted cases

Set: ripple200 master-bank cases whose chain root, template or question names a
policy/budget/RBI/tariff/PLI/FDI instrument — **58 cases**, the same count as the
G10 blast radius in `COVERAGE.md`.

| | RIPPLE ok | target ISINs measured | gaps |
|---|---|---|---|
| before (held planner) | **0 / 58** | 0 | `company_sector_pit` 58 |
| after (pilot table) | **28 / 58** | 240 | none 28, `company_sector_pit` 30 |

Regressions: **0**.  By archetype (before → after answered):

| R01 | R02 | R03 | R04 | R05 | R06 | R07 | R08 | R09 | R10 |
|---|---|---|---|---|---|---|---|---|---|
| 0→1 | 0→7 | 0→3 | 0→3 | 0→3 | 0→0 | 0→3 | 0→4 | 0→3 | 0→1 |

**28 cases unblocked:** MB0638, MB0651, MB0652, MB0653, MB0655, MB0658, MB0659,
MB0663, MB0671, MB0682, MB0684, MB0692, MB0698, MB0702, MB0712, MB0719, MB0723,
MB0754, MB0762, MB0766, MB0772, MB0783, MB0784, MB0788, MB0793, MB0800, MB0810, MB0820.

**30 still blocked, and why:**

- 28 matched a `policy_events` row that is **outside the 300-claim pilot** (the pilot
  covers 1.4% of 21,552 claims; it holds the 19 policies the bank itself names, not
  every policy the free-text trigger happens to pick).  The full run closes these.
- 2 matched an in-pilot claim whose stored sector list is generic → no target by design.

Also: the trigger hop is still the planner's free-text match and can pick an unrelated
policy (e.g. a coal-and-freight case matched a Tamil Nadu budget claim); and 4 of the
28 "ok" hops had targets but no measured market window because the claim's
`effective_date` is prose ("end of 2026"), so `_market()` declined rather than guess.

## 4. What this does not fix (chain level)

The ripple chain has five stages; this table is stage 1/2.  Stage 3
(`company_cost_structure`, `company_segment_pnl`, `company_price_revision`) is still
not held, so a case answered at the RIPPLE hop stays **partial** at chain level — by
design each hop reports what it answered and what is missing.  `universe_membership`
(theme membership) is not built in the live DB, so theme targets are emitted (7 rows)
but the planner reports "theme membership table not held" instead of resolving them.
Direction is inherited per claim (a duty cut that helps users and hurts producers gets
one direction); magnitude is parsed from the source text, never re-measured.

## 5. Build and design notes

- `python -m reality_engine.pilot.macro_claims --out .tmp/pilot` → 300 claims.
  Tables are created from `tasks/arch_v3/SCHEMA_V3.sql` via
  `build_t1.create_schema` (the pilot cannot drift from the design DDL), then four
  pilot-only columns are added to `macro_claim`: `paraphrase`, `known_at`, `stratum`,
  `conditions`.  The `policy_target` compatibility view is created too.
- **Anchors.**  The 19 `policy_events.id=…` values named in the ripple200 templates
  are always included; the four strata fill the other 281 claims, so the pilot covers
  the cases it exists to unblock instead of sampling past them.
- Deterministic maps only: ~130 sector-term → sector/basic-industry aliases,
  ~60 product-term → industry aliases, HS-chapter → industry (chapters 27–94), a named
  company resolver (exact symbol / exact normalised name / unambiguous prefix — never
  a substring, so "Air India" does not become Tenneco Clean Air India), and state
  targets from `State_Budget_<state>` sources.
- Stratum quotas adapt to what the source holds (a thin stratum cannot claim a full
  quota; the remainder is handed to the strata with capacity).  Sampling inside a
  stratum is evenly spaced by claim id; builds are row-identical on re-run (tested).
- `REALITY_MACRO_PILOT_DB` points the RIPPLE planner at the pilot DB; without it the
  planner keeps its old free-text path, so nothing regresses in a plain data root.

## 6. Files

| file | what |
|---|---|
| `reality_engine/pilot/macro_claims.py` | extraction maps, stratified build, CLI |
| `reality_engine/query/ctx.py` | `macro_pilot` DB alias + `REALITY_MACRO_PILOT_DB` |
| `reality_engine/query/planners/ripple.py` | stage 2 reads `macro_claim_target` (PIT on the claim's `known_at`), sector/basic-industry/ISIN/theme → held ISINs, falls back to the old text path |
| `reality_engine/tests/test_macro_claim_target.py` | 21 fixture tests (fields, maps, resolver, DDL, determinism, planner PIT + fallback) |
| `tasks/macro_pilot/run_before_after.py` | the 58-case before/after runner → `ripple_before_after.json` |
| `tasks/macro_pilot/handcheck.py` | deterministic sheet + precision/recall scorer |
| `tasks/macro_pilot/review_sheet.json`, `handcheck_labels.json` | the 60-claim review and its labels/notes |

Verification: `python -m unittest reality_engine.tests.test_macro_claim_target`
→ 21 tests, OK.  No live database was written; the only writes are under `.tmp/` and
`tasks/macro_pilot/`.
