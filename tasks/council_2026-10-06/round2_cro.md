# Round 2 — CRO / Independent Skeptic (2026-10-06)

Read all five round-1 files. No DB queries.

## 1. Answers to questions put to me

**Quant: "Will you hold the key to the holdout? Has the drift hypothesis already seen 2025–26? What test count makes you distrust any pass?"**
- **Holdout (settled).** A sealed 2025-10→2026-09 period works only for families **nobody has looked at by year** (guidance raises, promoter buying). The **results family** (reaction, drift, late-filer gradient) has been examined by year through 2026, so it is forward-only. The ledger keeps a per-family "years already seen" list.
- **Key.** No agent can hold it; agents can read any file. The holdout is a separate snapshot off the default path, and opening it needs a ledger entry naming the frozen card, approved by Shivam.
- **Test count.** There are already about 20+ strategy-level tries with zero real passes (T1–T12, F1/F2, P1 grid, diffusion families). A t-stat near 2 now means nothing: require t ≥ 3 plus ledger-wide BH. Past about 50 entries, forward confirmation is mandatory.

**Data Steward: "Should 'unchanged after data correction' be a promotion requirement? Void or provisional?"**
- **Yes, make it formal.** Re-running on a corrected panel counts as a new ledger entry, and promotion requires the sign and rough size to survive.
- **Provisional, not void.** The ±30% guard catches big splits and bonus days are a small share of 19k events, but no diffusion CAR may be quoted or used to rank Q14 until re-run on adjusted prices. Your ISIN finding also falsifies AGENTS.md's "ISINs never change" rule; record that in FRAMEWORK.md, not another closeout.

**Trading: "Accept high/low spread estimators until pilot fills exist?"**
- **Yes.** The bar says "net of *modelled* costs at 1× and 2×"; "measured" is reserved for real pilot fills. That removes the round-1 contradiction without lowering the bar.

**Macro PM: "What confirmatory test would you accept for the late-filer pattern? Does the 2025–26 sign flip kill #1?"**
- **Forward only, and the clock is running.** The Q2 FY27 results season starts in about two weeks. Freeze the card **this week**: after-15:30 filers trail matched non-announcers by ≥30 bp on CAR(0,1), t < −2, adjusted prices, fixed matching rule, tradable share (open-to-close vs overnight gap) reported. Score over the Oct–Nov 2026 and Jan–Feb 2027 seasons. Missing this season costs a quarter.
- **The flip does not kill #1**: it is in the sign-free, unconditioned drift, a different statistic. But #1's card must pre-state: conditioned drift ≤ 0 in 2025–26 = killed. "The regime changed" is not an allowed excuse afterwards.

## 2. Where I change my position

| Q | From | To | Why |
|---|---|---|---|
| Q2 | One book | Two books, but the fundamental book gets **zero hours** until PIT fundamentals exist | All four others agree; costless at zero budget. |
| Q8/Q15/Q17 | "No holdout exists" | Partial holdout (2025-10→2026-09) for untouched families only. Forward-only for the results family. | Quant's own Q15 caveat. |
| Q10 | Pause the scheduled writers | Snapshots plus continued ingestion, on two conditions: no *new* feed types, and writers quiet when a snapshot is cut | Forward paper needs fresh data (Trading). |
| Q14 | Surprise first; "avoid before results" card second | Macro's order: #1 surprise-conditioned drift with the late-filer gradient as its first diagnostic. Trading's overlay version of the avoid card, frozen now and tested forward | Overlay costs nothing to trade. |
| Q20 | ≤5% starter | Trading's ladder: paper for ≥2 results seasons and ≥30 events → ₹10–20 lakh pilot to *measure fills* → steps of 10/25/50/100% | Only route to measured costs. |
| Q21 | No exemptions | Truth-layer carve-out (Data Steward/Macro), but as a **closed, named list with an hour budget** | Otherwise the freeze blocks #1. |
| Q5 | My three fixes | Plus Trading's cost break-even ≥2× and Macro's per-year rule (no more than one losing year in five; the latest year must not be the worst) | Stricter; kills today's drift. Good. |

## 3. Where I still disagree

- **Quant and Macro PM (Q15): "unlimited exploration".** The binding constraint is Shivam's hours, not statistics. Unlimited exploration is how 40 task files appeared in two weeks. **Cap it at about 30% of hours**, logged and labelled.
- **Trading Lead (Q21): "unfreeze when the harness exists".** That rewards building, not finding: the old pattern again. The freeze lifts only on promotion or at the review date.
- **Quant (Q21): review on 2027-01-31.** Use **2026-12-31** (Macro agrees). At review, "nothing promoted" triggers a *rescope or stop* decision, not a reset of the clock.
- **Macro PM (Q14): promoter buying "in parallel".** No. One study at a time until harness and ledger exist; "a day of parsing" is how threads multiply. It goes second, not parallel.
- **Quant/Macro (Q13): "CRO freezes the card".** A Claude role cannot be the gatekeeper; agents produced the 46/46 promotion. **Shivam freezes by git commit**; the CRO role only checks completeness.
- **Q3 floors** (Quant ₹1 cr, Macro ₹2 cr, Trading ₹5 cr): I back **₹5 cr for scoring**, lower floors as sensitivity. Replace ₹10 cr with the capital Shivam would actually deploy; nobody has asked him.

## 4. Final stances

- **Q1** Keep; add size, drawdown cap, "data the market had", named counterparty, "beat the index fund or stop".
- **Q2** Two books; only the event book gets hours now.
- **Q3** A point-in-time turnover floor (₹5 cr for scoring), a participation cap, and Shivam's real capital figure.
- **Q4** Long-only; avoid lists scored as an overlay or underweight book.
- **Q5** Horizon-annualised IR, t ≥ 3, cost break-even ≥2×, per-year rule, max drawdown, forward confirmation. Frozen.
- **Q6** Matched peers primary; index always reported; factor model as a check.
- **Q7** Modelled, tiered costs at 1×/2×; pre-tax to promote, post-tax for the book.
- **Q8** Append-only ledger with snapshot IDs and variants counted; BH correction ledger-wide.
- **Q9** Six checks: adjusted prices, ISIN map, delistings, PIT dates, quarantine, snapshot. Results are provisional until they pass.
- **Q10** Frozen snapshots; ingestion continues; no new feed types.
- **Q11** `first_public_at` on every feature. Order: adjusted prices/ISIN → results filing dates → universe.
- **Q12** Set aside; revived only via a card.
- **Q13** Full card including execution fields and counterparty. Shivam freezes via git. A change creates a new ledger entry.
- **Q14** #1 surprise-conditioned drift, with the late-filer gradient as diagnostic; overlay card frozen now. Promoter buying next; guidance after that.
- **Q15** Exploration ≤30% of hours, labelled; confirmation forward or on a per-family holdout.
- **Q16** Thin harness from diffusion code: truth-checked loader, known-answer tests, invariants, costed portfolio sim.
- **Q17** Per-family split; forward-only for the results family; every year reported.
- **Q18** No ensemble before 3 promoted signals each with ≥6 months forward; equal weight until then.
- **Q19** LLM for extraction (audited and versioned) and logged hypothesis ideas; never decisions.
- **Q20** Trading's ladder plus pre-registered demotion rules.
- **Q21** Freeze until promotion or 2026-12-31; closed truth-layer carve-out list.
- **Q22** FRAMEWORK.md, an overwritten STATE (plus a data-state section), the ledger and registry. Archive the closeouts.

**Missing questions — final stances:**
- (a) Project kill switch: stop or rescope at 2026-12-31 with no promotion.
- (b) Amend the top of `AGENTS.md` to defer to FRAMEWORK.md, and correct the ISIN claim.
- (c) No number enters a tracker without a script re-run on a pinned snapshot.
- (d) Bug-class invariants live in the harness.
- (e) Formally bury or card the old threads: T4 +790 bps, F3, T6, the video backlog, the 100-hour study, and the unwritten tariff results.
- (f) Concentration limits per results week.
- (g) Council capped at these rounds; same-model agreement is weak evidence. Shivam decides.
