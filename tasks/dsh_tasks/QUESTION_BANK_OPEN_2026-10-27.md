# Task — open question bank: 300 original investor questions with grading rubrics

## Why this exists
The first bank (`tasks/QUESTION_BANK_300_2026-10-27.jsonl`) is 10 rewordings of each of Shivam's 30 questions. It tests naming and wording robustness only.

Shivam's verdict: the questions are too similar. The database's end goal is to answer **any** question an investor might ask, including:
- inverse questions;
- timing questions;
- governance questions;
- causal-reasoning questions;
- odd questions.

This bank is **original questions**. Do not rephrase the 30. Read families 12–20 in `tasks/QUERY_TEMPLATES_2026-10-27.md` §2 first.

## Shivam's own examples (the bar to match or beat)
- When is the demand going live? When is the factory going live? When will operating capacity scale?
- What is the auditor's opinion on the latest quarterly report? What did the auditor say? Was it going-concern? Did the auditor resign after this?
- A policy came out: which companies will it impact?
- When the general-election results came out on 4 June 2024, the market fell. Why?
- What is the impact of rising copper prices on the shipping sector, or on cable companies?
- How do food-delivery fees affect the profitability of quick commerce?

## 20 archetypes, 15 questions each = 300
Each archetype needs its own different questions: different companies, industries, events and angles. A question must not be an earlier one with only the name swapped.

| # | Archetype | Family | Seeds (write new ones in this spirit) |
|---|---|---|---|
| A1 | Commissioning / go-live dates | 12 | When does X's new plant start commercial production? Has the date slipped across calls? |
| A2 | Demand and ramp timing | 12 | When does management expect demand to recover? When will utilisation reach target? |
| A3 | Inverse topic screen | 13 | Which mid-caps guided a margin recovery in H2 FY26? Who announced price hikes in Q1? |
| A4 | Auditor opinion | 14 | Opinion type and emphasis-of-matter on the latest results; going-concern doubt |
| A5 | Auditor and KMP exits | 14 | Did the auditor resign, and what reason was filed? CFO churn in the last 2 years |
| A6 | Red flags | 14 | Rising pledge, promoter selling before results, SEBI/GST/tax orders, related-party jumps |
| A7 | Market move → why | 15 | 4 Jun 2024 results day, Budget days, tariff announcements, RBI surprises, crash days. Index and sector level. |
| A8 | Single-stock move → why | 15 | Why did X fall 15% on date D? Was there a disclosure before it? |
| A9 | Commodity transmission | 16 | Copper → cables / transformers / shipping; crude → paints / airlines / tyres; coal → power / cement; gold → jewellers / gold-loan NBFCs |
| A10 | FX / rates transmission | 16 | Weaker rupee → IT / pharma / importers; repo moves → NBFCs / HFCs / real estate |
| A11 | Business economics | 17 | Delivery fees → quick-commerce margins; discounting → EV makers; float income → brokers |
| A12 | Forward policy impact | 18 | PLI, anti-dumping duty, GST rate change, budget capex line, export ban: who, direction, how much |
| A13 | Supply chain / second order | 19 | Who supplies railway wagons? Who gains second-hand from defence indigenisation? |
| A14 | Guidance vs delivery | 3, 12 | Did X hit its FY25 revenue guidance? Management credibility over 4 quarters |
| A15 | Order book and execution | 2, 12 | Order book / revenue cover; large orders won and their execution period |
| A16 | Capital allocation | 1, 3 | Use of QIP/IPO money vs the stated objects; capex funded by debt or internal accruals |
| A17 | Flows and ownership | 2, 4 | Sectors FIIs sold in a month; MF accumulation in small caps; insider buying clusters |
| A18 | Event study | 9 | Price reaction around results, block deals, index inclusion |
| A19 | Cross-sector "what if" | 16, 18 | If monsoon fails / crude hits $100 / US tariffs rise 25%, which listed sectors are most exposed? |
| A20 | Bizarre / out-of-scope | 20 | Questions the data can only partly answer. The rubric must say which part is NOT IN DATA. |

Spread:
- Across the 300, cover 30+ industries and all four market-cap buckets.
- Use at least 40 questions with an explicit "as of `<date>`" point-in-time constraint.
- Write at least 30 in Hinglish (Roman script).
- Include at least 30 terse keyword-style questions.
- Use real companies, events and dates only. Find them with `connect_ro` bounded queries over:
  - `master_companies`;
  - `results_xbrl.db`;
  - `results_notes.db` (READ-ONLY; a job is writing to it);
  - `concall_facts.db`, `deck_figures.db`, `ar_facts.db`, `bse_announcements.db`;
  - `macro_events`, `pib_releases`, `policy_events`;
  - `mkt_commodity_daily`/`monthly`, `mkt_nse_index_daily`.
- Use the `reality-data` tools if they are available to you.
- Market-wide events such as 4 Jun 2024 must be confirmed from the index price tables.

## Each row (`tasks/QUESTION_BANK_OPEN_2026-10-27.jsonl`)
- `qid` (`A07-03`), `archetype`, `family`, `question`, `entities` (resolved: symbol, ISIN, BSE code, name, or industry / index / policy id), `period`, `as_of` (or null).
- `answer_kind`: one of `fact`, `date`, `list`, `ranking`, `explanation`, `NOT IN DATA`.
- `rubric`:
  - `required_evidence`: the stores, tables, doc types and series a good answer must cite;
  - `required_steps`: the reasoning chain, e.g. "copper share of cable COGS from AR → copper move from series → past pass-through from margins → management comment";
  - `forbidden`: e.g. using documents after `as_of`, inventing a cost share, presenting analyst opinion as fact;
  - `ground_truth`: an exact value or date where one exists (checked with a query), else null.
- `coverage`:
  - `yes`, `partial` or `no`;
  - a one-line note on what is missing (e.g. "no copper series after 2025-12", "auditor opinion not tagged in results_notes");
  - the gap ID from `tasks/BACKWARD_REQUIREMENTS_AUDIT_2026-10-27_REPORT.md` §10 if one applies, or "NEW GAP: …" if none does.
- `why`: one line on what ability this tests.

Also write `tasks/QUESTION_BANK_OPEN_2026-10-27.md`, a readable version for Shivam:
- a summary at the top: counts by archetype, industry, bucket and coverage;
- a **"New gaps found"** list, each gap with the questions it blocks;
- then one table per archetype.

## Rules
- Read-only everywhere except this worktree.
- No network, no paid APIs, no commits.
- Never open `results_notes.db` for writing.
- Never invent a company, policy, date or number. Every `ground_truth` comes from a query; list each query in an appendix at the end of the md.
- Don't answer the questions beyond a bounded coverage or ground-truth check.

## Acceptance checks
1. 300 rows, 15 per archetype, all qids unique.
2. No two questions are the same template with only the entity swapped. Within an archetype, each question differs in angle, not just name.
3. Every entity resolves, and every `ground_truth` value traces to a listed query.
4. The spread targets above are met.
5. Every row has a rubric and a coverage value.

## Test command(s)
```bash
python -c "import json,collections as C;r=[json.loads(l) for l in open('tasks/QUESTION_BANK_OPEN_2026-10-27.jsonl',encoding='utf-8')];assert len(r)==300 and len({x['qid'] for x in r})==300;c=C.Counter(x['archetype'] for x in r);assert len(c)==20 and set(c.values())=={15},c;assert all(x.get('rubric',{}).get('required_evidence') and x.get('coverage') for x in r);print('ok')"
```

## Report
Give:
- the summary block;
- the new gaps found;
- any archetype you struggled to fill with real entities, and why;
- your tool-call count.
