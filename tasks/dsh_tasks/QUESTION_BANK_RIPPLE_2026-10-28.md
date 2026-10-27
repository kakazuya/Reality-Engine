# Task — ripple question bank: 200 second- and third-order questions that find schema gaps

## Goal
Shivam, 2026-10-28: "if we question harder, we will find more gaps." The open bank (`IDM-worktrees/20261027T173433Z-6b857b5a/tasks/QUESTION_BANK_OPEN_2026-10-27.*`) found 29 new gaps with mostly first-order questions.

This bank goes **two and three steps down the causal chain**. A move in X changes Y, which changes Z, which changes which listed companies win or lose, and when.

The deliverable has two parts:
- the questions;
- **the schema requirements they expose, hop by hop**.

The schema is being finalised now; no chunking happens until it is. Every question should either be answerable or show exactly which table or field is missing.

Read before writing:
- families 12–20 in `tasks/QUERY_TEMPLATES_2026-10-27.md` §2;
- the open bank's md;
- its "New gaps found" list. Don't repeat those questions; go deeper.

## What "hard" means here
Each question must need a chain of **at least 3 hops**. Write the chain out hop by hop in the row. Examples of the depth wanted (write your own; don't copy these):
- Copper +20% → cable makers' raw-material cost → price hikes lag 1–2 quarters → power-transmission EPC margins squeezed on fixed-price contracts → which listed EPC names carry the largest fixed-price order book?
- Red Sea shipping disruption → freight rates and transit days up → importers hold more inventory → working capital and short-term debt rise → which mid-caps with high import content and thin interest cover are most exposed?
- Monsoon deficit → rural income → two-wheeler and tractor volumes → auto-ancillary and tyre volumes, then their steel and rubber suppliers. What is the lag at each stage, from past cycles in our data?
- Repo cut → bank deposit rates follow with a lag, but MCLR/EBLR loans reprice faster → NIM squeeze for banks with more EBLR loans → which banks, and does the HFC/NBFC funding-cost benefit offset it for their lenders?
- A stock rallies → promoter raises a QIP → dilution, and the use of funds → capex leads to a capacity glut in that industry two years later.
- A competitor's response: a large player cuts prices after a PLI subsidy. What happens to the non-PLI small-cap peers?
- Effects pulling in opposite directions: a weaker rupee helps IT exports but raises imported-input costs for the same company. Net it out by revenue and cost geography.

## Archetypes (20 questions each = 200)
| # | Archetype |
|---|---|
| R1 | Commodity → input cost → pricing power → downstream demand (3+ hops) |
| R2 | Policy cascade: the policy, then the direct target, its suppliers, its customers, and substitutes |
| R3 | Rates, FX and liquidity transmission through balance sheets (NIM, debt cost, working capital) |
| R4 | Global or geopolitical shock → trade routes → Indian sectors (tariffs, wars, sanctions, shipping) |
| R5 | Competitive response and market-structure change (price war, capacity glut, consolidation) |
| R6 | Reflexive and capital-markets loops (price → fund-raise → dilution or capex → returns) |
| R7 | Timing and lags: when does hop 3 show up in results, and what does the data say the lag was last time? |
| R8 | Effects pulling both ways in one company or sector; net the effect and say where the figures for each side come from |
| R9 | Leading indicators: which hop-1 data series signals a hop-3 effect first, and is it point-in-time? (Uses the 3:30 / 4-session rule in `tasks/NEXT_SESSIONS_PLAN_2026-10-27.md`) |
| R10 | Information leakage: a delivery spike or position build in the 4 sessions before day 0 of a ripple-triggering event. Who moved first? |

## Each row (`tasks/QUESTION_BANK_RIPPLE_2026-10-28.jsonl`)
- `qid` (`R03-07`), `archetype`, `question`, `entities` (resolved via `master_companies`; real policies and events only), `as_of`.
- `chain`: a list of hops. Each hop has:
  - `from`, `to`, `mechanism`, `direction`, `expected_lag`;
  - `evidence_needed`: table.column or doc type;
  - `exists_today`: yes / partial / no, checked with a bounded `connect_ro` query;
  - `gap`: the missing table or field, named as a **schema proposal**, e.g. `company_cost_structure(isin, fy, input, share_of_cogs, source_doc, known_at)`.
- `rubric`: `required_steps`, `forbidden` (hindsight, invented elasticities, opinion presented as fact, unsourced or seeded events), `ground_truth` (only from a query, else null).
- `coverage`: the weakest hop decides it.

**Never use** `macro_events` rows without a `doc_id` (NUCLEAR_MISSION, RAIL_CAPEX_PUSH, STEEL_SAFEGUARD_DUTY, US_TARIFF_TEXTILE_RELIEF, PHASE5_*). They are unsourced seed data. Use sourced `policy_events` (`quote_ok=1`), PIB, MEV_* rows that have a `doc_id`, and the market series.

## The second deliverable: schema requirements (`tasks/RIPPLE_SCHEMA_REQUIREMENTS_2026-10-28.md`)
Merge every hop-level gap into one deduplicated list of proposed tables and fields. For each, give:
- the columns, keys and point-in-time field (`known_at` / `valid_from`);
- its source: XBRL tag, AR note, concall, deck, an exchange file, or an external series, saying which are fetched already and which are new;
- how many questions it unblocks, and which hop numbers;
- whether a deterministic parser could fill it, or a reader model is needed;
- its priority, ranked by questions unblocked per unit of build effort.

Also mark which requirements overlap the open bank's gaps and the audit's G0–G12.

## Rules
- Read-only everywhere except this worktree. Use `reality_engine.db.readonly.connect_ro` and keep queries bounded.
- No network, no paid APIs, no commits.
- Never open `results_notes.db` for writing.
- No invented companies, policies, dates or numbers.
- Elasticities and lags must come from our own data (past cycles) or be labelled "assumption, needs X".

## Acceptance checks
1. 200 rows, 20 per archetype, all qids unique, and every chain has at least 3 hops.
2. Every hop has `evidence_needed` and `exists_today`. Every `no` or `partial` hop names a schema proposal.
3. No unsourced macro event appears.
4. The schema requirements file is deduplicated and ranked, and each item lists the qids it unblocks.

## Test command(s)
```bash
python -c "import json,collections as C;r=[json.loads(l) for l in open('tasks/QUESTION_BANK_RIPPLE_2026-10-28.jsonl',encoding='utf-8')];assert len(r)==200 and len({x['qid'] for x in r})==200;c=C.Counter(x['archetype'] for x in r);assert len(c)==10 and set(c.values())=={20},c;assert all(len(x['chain'])>=3 and all(h.get('evidence_needed') and h.get('exists_today') for h in x['chain']) for x in r);s=open('tasks/QUESTION_BANK_RIPPLE_2026-10-28.jsonl',encoding='utf-8').read();assert not any(k in s for k in ['NUCLEAR_MISSION','RAIL_CAPEX_PUSH','STEEL_SAFEGUARD_DUTY','US_TARIFF_TEXTILE_RELIEF','PHASE5_']);print('ok')"
```

## Report
Give:
- the top 15 schema requirements, with qids unblocked and effort;
- the share of hops answerable today, split as hop 1, hop 2 and hop 3+;
- the archetypes where real entities were hardest to find;
- your tool-call count.
