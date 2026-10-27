# Task — 300-question test bank: 10 variations of each of Shivam's 30 questions

## Goal
Shivam's 30 test questions are listed in §5 of `tasks/QUERY_TEMPLATES_2026-10-27.md`. The full texts are in:
- `tasks/DB_QUALITY_TEST_2026-10-24.md` (5);
- `tasks/optimizations/measure/QA10_BRIEF.md` (10);
- `tasks/optimizations/measure/EVAL25.md` (Q11–Q25).

Write **10 variations of each, 300 questions in total**. Shivam approves the bank, and it then becomes the pass/fail threshold for every database. The 30 originals stay as separate fixed regressions; they are not counted in the 300.

## The 10 variation slots (use them in this order for every question)
| V | Variation | Rule |
|---|---|---|
| V1 | Same question, **different stock at the same level** | Same kind of company. For example, another listed bank for Q12, another HFC for Q17. |
| V2 | **Different stock, different market-cap bucket** | If the original is a micro-cap, use a large-cap, and vice versa. Use buckets as of the question date. |
| V3 | **Naming** | Ask by ISIN, BSE code, old symbol after a rename, or a common misspelling. At least 5 of the 30 must use a company whose ISIN or symbol changed (split, merger, demerger, rename). |
| V4 | **Terse keyword query** | 3–8 words, for example "zentec 3y cagr adjusted". |
| V5 | **Long natural or Hinglish phrasing** | At least 10 of the 30 in Hinglish (Roman script). |
| V6 | **Different period and label style** | Q2FY26 vs "Jul–Sep 2025" vs "September quarter", "as of <date>", "last 4 quarters". It must stay inside the data window: company data from 2024-04-01, prices from 2019. |
| V7 | **Scope up to industry or sector** | The same question over the company's whole industry or sector. For example: "net NPA of all listed PSU banks, Q1FY27, ranked". |
| V8 | **Screen by theme, index or market-cap bucket** | For example, Nifty Smallcap 250 members with the same feature, or the defence theme. Membership is as of the question date. |
| V9 | **Policy or point-in-time angle** | Either tie the question to a real policy or macro event in our data (PIB, Budget, RBI, tariff), or ask it "as of `<date>`" so that later documents must not count. |
| V10 | **Hard edge case** | Either a case that should come back **NOT IN DATA** (a real company or period we don't hold, and say why), or a stock with a corporate action inside the period (split or bonus, so adjusted prices and share counts matter). |

For macro or policy originals (Q16, Q18, Q21, Q22, Q23, Q25), V1 and V2 become a **different policy or macro event** of the same type, and a different issuer or ministry. Note that in the row.

## Every question must be real and checkable
- Every named company must resolve in `master_companies` (or, for ETFs, in the ETF tables). Use `reality_engine.db.readonly.connect_ro` and keep queries bounded. Use real policies and events found in `pib_releases`, `policy_events` and `raw_documents` (RBI/Budget).
- For each question, record the stores a correct answer needs, and a **coverage check**: do those stores hold data for that entity and period today? The values are:
  - `yes`;
  - `partial` (say what is missing);
  - `no` (then the expected answer is NOT IN DATA).
  - Do this with a cheap bounded query. Don't answer the question.
- No duplicate entities within one original's 10 variations.
- Across the 300, spread the companies across 25 or more sectors and all four market-cap buckets, and include BSE-only and NSE-only names.

## Output (in this worktree)
1. `tasks/QUESTION_BANK_300_2026-10-27.jsonl`: one row per question with these fields:
   - `qid` (e.g. `Q14-V3`), `orig_qid`, `variation`, `question`;
   - `entities` (resolved: symbol, ISIN, bse_code, name), `entity_level`, `period`, `as_of`;
   - `family` (1–11 from the templates doc), `needs` (stores), `coverage` (yes/partial/no plus a note), `expected_answer_type` (number / text+quote / list / ranking / NOT IN DATA);
   - `why`: one line on what this variation tests.
2. `tasks/QUESTION_BANK_300_2026-10-27.md`: a readable version for Shivam. One section per original: the original question, then a table of V1–V10 with the question, entity, period, coverage and what it tests.
3. A summary at the top:
   - counts by family, entity level, variation, market-cap bucket, sector and exchange;
   - the coverage split (yes / partial / no);
   - the questions expected to fail today, grouped by the gap they hit.

## Rules
- Read-only everywhere except this worktree.
- No network, no paid APIs, no commits.
- Do not open `reality_engine/data/results_notes.db` for writing. A job owns it; open it read-only only.

## Acceptance checks
1. Exactly 300 rows: 30 originals × V1–V10, each slot following its rule above.
2. All entities resolve. 0 invented companies, policies or dates; every one traces to a query.
3. The spread targets are met (25+ sectors, all 4 buckets, BSE-only and NSE-only names, at least 5 ISIN or symbol changes, at least 10 Hinglish).
4. A coverage check is recorded for every row.

## Test command(s)
```bash
python -c "import json;r=[json.loads(l) for l in open('tasks/QUESTION_BANK_300_2026-10-27.jsonl',encoding='utf-8')];assert len(r)==300 and len({x['qid'] for x in r})==300;print('ok',len(r))"
```

## Report
Give the summary block, any slot you could not fill and why, and the tool-call count.
