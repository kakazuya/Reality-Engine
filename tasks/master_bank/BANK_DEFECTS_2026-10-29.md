# Master bank — defects found by the strict-grader audit (2026-10-29)

Read-only audit of `tasks/master_bank/MASTER_BANK.jsonl` (1073 cases) and `tasks/pilot60/INSTANCES.jsonl` (2098 rows). The approved bank is **not** edited: Shivam approves bank changes. The defect that only concerns the *instance* text is fixed in `tasks/pilot60/instantiate.py` instead (`--rename-only`), which regenerates the instance questions.

## 1. `period` / `as_of` contradicts the dates the question text names

**9 contradiction(s)** — *no* date in the question falls in the case's own period window; **4 ambiguity(ies)** — some dates in the text fall outside it (a reference date and the asked period share one sentence).

### Contradictions (the answer follows the wrong field)

| mid | question | period | as_of | period window | dates in the text outside it |
|---|---|---|---|---|---|
| MB0222 | For the Tax holiday for affordable housing projects extended to March  | 2025-2026 | 2026-10-19 | named date 2022-01-31..2022-01-31 | 2022-03 |
| MB0231 | What was Eicher Motors (NSE: EICHERMOT)'s delivered quantity (not tota | 13-14 Apr 2026 | 2026-10-19 | named dates 2026-04-13..2026-04-14 | 2026-09, 2026-09-15, 2026-09-16 |
| MB0232 | What was SEDEMAC Mechatronics (NSE: SEDEMAC)'s delivered quantity (not | 13-14 Apr 2026 | 2026-10-19 | named dates 2026-04-13..2026-04-14 | 2026-09, 2026-09-15, 2026-09-16 |
| MB0233 | What was NSE: DALALSTCOM (now KEEPLEARN)'s delivered quantity (not tot | 13-14 Apr 2026 | 2026-10-19 | named dates 2026-04-13..2026-04-14 | 2026-06, 2026-06-10, 2026-06-11 |
| MB0234 | ARIHANT delivery 11-12 Aug nse bse | 13-14 Apr 2026 | 2026-10-19 | named dates 2026-04-13..2026-04-14 | 2026-08-11, 2026-08-12 |
| MB0235 | Sambandam Spinning Mills (NSE: SAMBANDAM) ka delivered quantity 11 Aug | 13-14 Apr 2026 | 2026-10-19 | named dates 2026-04-13..2026-04-14 | 2026-08, 2026-08-11, 2026-08-12 |
| MB0237 | For all listed companies in Automobiles, what was the delivered quanti | 13-14 Apr 2026 | 2026-10-19 | named dates 2026-04-13..2026-04-14 | 2026-02, 2026-02-10, 2026-02-11 |
| MB0238 | For the NIFTY SMALLCAP 500 constituents, what was the delivered quanti | 13-14 Apr 2026 | 2026-10-19 | named dates 2026-04-13..2026-04-14 | 2026-07, 2026-07-14, 2026-07-15 |
| MB0240 | What was Aakash Exploration Services (NSE: AAKASH)'s delivered quantit | 13-14 Apr 2026 | 2026-10-19 | named dates 2026-04-13..2026-04-14 | 2026-10, 2026-10-13, 2026-10-14 |

### Ambiguities (reference date outside the window)

| mid | question | period | as_of | period window | dates in the text outside it |
|---|---|---|---|---|---|
| MB0176 | How did JSW Energy (NSE: JSWENERGY)'s rolling correlation with Customs | the 12 months after March  | 2026-10-19 | named date 2025-02-01..2025-02-01 | 2025-03 |
| MB0179 | As of 31 March 2026, what did the rolling correlation of National Alum | as of 31 March 2026 | 2026-03-31 | named date 2026-03-31..2026-03-31 | 2025-02, 2025-02-01 |
| MB0239 | As of 31 March 2026, what delivered quantity had Bimetal Bearings (NSE | as of 31 March 2026 | 2026-03-31 | named date 2026-03-31..2026-03-31 | 2026-09, 2026-09-15, 2026-09-16 |
| MB0306 | What was MMP Industries (NSE: MMP)'s YTD high price in 1 January-30 Se | 1 January-30 September 202 | 2026-09-30 | named date 2026-09-30..2026-09-30 | 2026-01-01 |

Proposed fix, contradictions: the question text is the ask, so the case's `period` becomes the window the text names (11–12 Aug 2026 → `period` `11-12 Aug 2026`, `as_of` >= 2026-08-12), and the delivery planner must take the window from the text when the two disagree. The MB0231–MB0240 delivery cluster is one bad template: all ten carry `period` `13-14 Apr 2026` while their text names another day.


## 2. Instance questions that name a different company than the instance

Measured on `INSTANCES.jsonl` **before** the fix: **1,191 of 2,098** rows named the parent case's company while the instance entity was another company (a further ~200 spelled it without the legal suffix, which the rename also catches). `python tasks/pilot60/instantiate.py --rename-only` rebuilds each question from the parent bank case and rewrites the parent's name / name-without-suffix / symbol / BSE code with the instance company's (a peer-set instance is renamed company by company to its peer set): **1,408** rows, deterministic — a second run reports the same 1,408 and writes identical text. **0** rows still name a parent token.



## 3. MB0234 (the case named in the task)

`MB0234` — question `ARIHANT delivery 11-12 Aug nse bse`, `period` `13-14 Apr 2026`, `as_of` `2026-10-19`, single exchange in the answer. Three defects in one case:

1. the `period` field names April days the question never mentions;
2. the text asks for **two** dates (11 and 12 Aug) — a `named dates` window, not a single day;
3. the text asks for **NSE and BSE** delivery; the answer reports one exchange, and the ask-coverage rule now makes that PARTIAL (exchange is not a concept the gate can see, so the row-level check is the answer's `delivery` hop carrying both).

Proposed fix: `period` → `11-12 Aug 2026`; keep the text; make the delivery planner read the period window from the text when the two disagree, and return one row per exchange. Instance rows inherit the corrected period.


## 4. Applied 29 Oct 2026, Shivam approved
- **Period fixed** to the dates each question names. Each changed row keeps `period_before_fix`; backups are `*.bak-20261029-bankfix`.

  | case | new period |
  |---|---|
  | MB0231, MB0232 | 15-16 Sep 2026 |
  | MB0233 | 10-11 Jun 2026 |
  | MB0234, MB0235 | 11-12 Aug 2026 |
  | MB0237 | 10-11 Feb 2026 |
  | MB0238 | 14-15 Jul 2026 |
  | MB0240 | 13-14 Oct 2026 |

  The 20 instance rows of these cases are updated too.
- **Not changed:**
  - MB0239 is a deliberate future-date trap: as of 31 Mar it asks for September data, so the answer is NOT IN DATA.
  - MB0222: the 2022 date is the policy's reference date, not the asked period.
  - The 4 ambiguities: their reference dates are legitimate.
- **Parent–child naming:** already fixed by `instantiate.py --rename-only` (merged in `c3206b9`). 0 instance questions name the parent company.
- **Exchange clarity:** the questions already say "NSE and BSE". The fix belongs to the planners, which must return one row per exchange plus the combined total. That is in the next design round.
