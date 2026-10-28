# Master question bank - one deduplicated bank from every source

Built by `tasks/master_bank/build_master_bank.py`. Re-run: `python tasks/master_bank/build_master_bank.py --check`.

Sources: Shivam's 30 fixed regressions (kept as written, `regression: true`), the 300 variations, the 300 open questions, the 200 ripple questions, and the Reddit bank.

## 1. Counts per source bank

| bank | rows in | representatives | merged as duplicate | cases with >=1 row from the bank |
| --- | --- | --- | --- | --- |
| shivam30 | 30 | 30 | 0 | 30 |
| variations300 | 300 | 300 | 0 | 300 |
| open300 | 300 | 300 | 0 | 300 |
| ripple200 | 200 | 200 | 0 | 200 |
| reddit200 | 200 | 200 | 0 | 200 |
| **total** | 1030 | 1030 | 0 | 1030 |

Unique cases: **1030**. Originals kept: **30**. Duplicate rows merged: **0**. No two rows are the same case once the naming / style / edge / period-label separations are applied: no two source banks share an entity+period at all, and inside a bank the ten variations deliberately change the entity, the wording dimension or the period label. The dedupe still runs on every build; the fake Reddit check proves it merges when a real duplicate appears.

## 2. How the merge works

- One common schema: `mid`, `source_bank`, `source_qid`, `question`, `entities`, `entity_level`, `entity_level_source`, `family` (list of 1-20, primary first), `family_source`, `variation`, `archetype`, `template`, `period`, `as_of`, `answer_kind`, `rubric` (evidence / steps / forbidden / ground truth), `coverage` (verdict / note / gap), `chain` (ripple only), `style`, `naming_variant`, `edge_case`, `regression`, `duplicates`.
- Missing fields stay null. Shivam's 30 originals keep their text as written: QA1-QA10 from `QA10_BRIEF.md`; DBQ1-DBQ5 and Q11-Q25 use the documented short form in `QUERY_TEMPLATES` §5 because no fuller copy exists in the repo (`eval25_key.md` is absent).
- `family` is a list. A source row that declares `"2,11"` counts in family 2 and family 11 in the matrix; its first entry is the primary family. The per-family tables in §4 list each case once, under its primary family, with the other families cross-referenced.
- `entity_level` is derived deterministically (`derive_entity_level`) and its source is recorded: `given` (the bank declared it), `variation` (V7 scope -> industry/sector, V8 screen -> index/theme), `keywords` (entity type + question scope), `entities` (entity type only) or `fallback` (no signal; counted in `--check`, must stay under 10% of the open + ripple rows).
- Layer 1, near-duplicate text: case-folding, punctuation and numbers removed, token Jaccard >= 0.80, and only between rows with the same entity, period, primary family, style and naming/edge dimension. A templated question on a different company is a different case and is never merged.
- Layer 2, same case: same template + entity level + evidence shape + entity + period, even with different wording. Banks without an explicit template id (open, ripple) also need 0.50 wording similarity to confirm it is the same case; the archetype alone (A01, R01) is a family, not a template.
- Kept separate by design: naming variants (ISIN / BSE code / old symbol), style variants (terse / Hinglish / as-of), edge cases that ask for a refusal (`NOT IN DATA`), and period-label variants (V6), because each tests a different robustness dimension. One representative per case, chosen as the richest rubric with a ground truth, with originals first.
- `style` is classified by rule: bank Hinglish flag or >=2 Hindi function words -> Hinglish; `as of` / point-in-time wording or a V9 variation -> point-in-time; <=10 words or a V4 variation -> terse; else natural.
- Ripple rows carry no family in their bank; the family is mapped from the archetype (R01->16, R02->18, R03->16, R04->16+19, R05->19, R06->3, R07->12, R08->16, R09->11, R10->9) and recorded as `family_source="archetype"`. The ripple entity level is derived from the question and the chain's entities; R02/R06/R09 fix the scope by construction (policy cascade, capital-markets loop, leading-indicator series), and R10 is the specific company event.

## 3. Coverage matrix

### 3.1 family x entity level x style

Each cell is `cases (terse/natural/Hinglish/point-in-time)`.

| family | stock | industry | sector | theme | index | market-cap bucket | price band | policy | macro | market-wide | total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 111 (17/66/12/16) | 11 (0/11/0/0) | . | . | 11 (0/11/0/0) | . | . | . | . | 3 (0/2/1/0) | 136 |
| 2 | 145 (21/83/13/28) | 12 (0/9/1/2) | 1 (0/1/0/0) | . | 14 (0/11/1/2) | 3 (0/3/0/0) | . | . | . | 7 (1/5/1/0) | 182 |
| 3 | 50 (4/39/4/3) | 12 (2/8/1/1) | . | . | 3 (0/3/0/0) | . | . | . | . | 23 (0/22/1/0) | 88 |
| 4 | 11 (0/11/0/0) | 11 (2/7/1/1) | 1 (0/1/0/0) | 10 (2/6/1/1) | 2 (0/1/1/0) | 3 (0/3/0/0) | . | . | . | 9 (1/7/1/0) | 47 |
| 5 | 9 (1/1/1/6) | 1 (0/1/0/0) | . | . | 1 (0/1/0/0) | . | . | . | . | . | 11 |
| 6 | 18 (4/10/2/2) | 26 (4/14/2/6) | . | 19 (4/11/2/2) | 7 (0/6/0/1) | . | . | 18 (4/10/2/2) | . | . | 88 |
| 7 | . | 3 (0/3/0/0) | . | 9 (2/5/1/1) | 3 (0/3/0/0) | . | . | 18 (4/10/2/2) | . | . | 33 |
| 8 | 22 (4/14/2/2) | 13 (2/9/1/1) | . | . | 3 (0/3/0/0) | . | . | . | . | . | 38 |
| 9 | 66 (7/52/4/3) | 12 (2/4/1/5) | . | . | 5 (0/4/0/1) | . | . | . | . | 1 (0/1/0/0) | 84 |
| 10 | . | . | . | . | . | . | . | . | . | . | 0 |
| 11 | 27 (5/5/3/14) | 13 (2/3/1/7) | . | . | 4 (0/1/0/3) | . | . | . | 20 (0/12/0/8) | . | 64 |
| 12 | 65 (4/55/5/1) | 11 (0/10/1/0) | . | . | . | . | . | 4 (0/4/0/0) | . | . | 80 |
| 13 | . | 1 (1/0/0/0) | . | . | . | 1 (0/0/1/0) | . | . | . | 13 (0/10/3/0) | 15 |
| 14 | 31 (1/28/2/0) | . | . | . | . | 3 (0/3/0/0) | 1 (0/1/0/0) | . | . | 25 (3/20/2/0) | 60 |
| 15 | 18 (1/16/1/0) | 2 (0/2/0/0) | . | . | . | . | . | . | . | 15 (1/12/2/0) | 35 |
| 16 | 23 (2/20/1/0) | 73 (0/70/3/0) | 8 (1/6/1/0) | 3 (0/3/0/0) | . | 3 (0/3/0/0) | . | 25 (0/24/1/0) | . | . | 135 |
| 17 | 34 (1/32/1/0) | 5 (0/5/0/0) | . | 1 (0/1/0/0) | . | . | . | . | . | . | 40 |
| 18 | 4 (0/4/0/0) | 1 (0/1/0/0) | 7 (1/5/1/0) | 2 (0/2/0/0) | . | . | . | 41 (1/38/2/0) | . | . | 55 |
| 19 | 6 (0/6/0/0) | 40 (1/38/1/0) | . | 2 (0/1/1/0) | . | 2 (0/2/0/0) | . | 10 (0/10/0/0) | . | . | 60 |
| 20 | 13 (4/9/0/0) | 1 (0/1/0/0) | . | . | 1 (0/1/0/0) | 1 (1/0/0/0) | . | 2 (0/2/0/0) | . | 2 (1/1/0/0) | 20 |
| none | 77 (0/75/1/1) | 2 (0/2/0/0) | 1 (0/1/0/0) | . | . | 1 (0/1/0/0) | . | 1 (0/1/0/0) | . | 3 (0/3/0/0) | 85 |
| **total (case x family)** | 730 | 250 | 18 | 46 | 54 | 17 | 1 | 119 | 20 | 101 | 1356 |

A case with more than one family counts in every family it lists, so the totals are (case x family) pairs and exceed the number of cases (1030). Family 10 has zero source rows in every bank; the per-family table in §4 shows the empty family explicitly.

### 3.2 family x style

| family | terse | natural | Hinglish | point-in-time | total |
| --- | --- | --- | --- | --- | --- |
| 1 | 17 | 90 | 13 | 16 | 136 |
| 2 | 22 | 112 | 16 | 32 | 182 |
| 3 | 6 | 72 | 6 | 4 | 88 |
| 4 | 5 | 36 | 4 | 2 | 47 |
| 5 | 1 | 3 | 1 | 6 | 11 |
| 6 | 16 | 51 | 8 | 13 | 88 |
| 7 | 6 | 21 | 3 | 3 | 33 |
| 8 | 6 | 26 | 3 | 3 | 38 |
| 9 | 9 | 61 | 5 | 9 | 84 |
| 10 | . | . | . | . | 0 |
| 11 | 7 | 21 | 4 | 32 | 64 |
| 12 | 4 | 69 | 6 | 1 | 80 |
| 13 | 1 | 10 | 4 | . | 15 |
| 14 | 4 | 52 | 4 | . | 60 |
| 15 | 2 | 30 | 3 | . | 35 |
| 16 | 3 | 126 | 6 | . | 135 |
| 17 | 1 | 38 | 1 | . | 40 |
| 18 | 2 | 50 | 3 | . | 55 |
| 19 | 1 | 57 | 2 | . | 60 |
| 20 | 6 | 14 | . | . | 20 |
| none | . | 83 | 1 | 1 | 85 |
| **total** | 119 | 1022 | 93 | 122 | 1356 |

### 3.3 Empty and thin cells (fewer than 3 cases)

| family | level | cases | status |
| --- | --- | --- | --- |
| 2 | theme | 0 | empty |
| 2 | price band | 0 | empty |
| 2 | policy | 0 | empty |
| 2 | macro | 0 | empty |
| 2 | sector | 1 | thin |
| 1 | sector | 0 | empty |
| 1 | theme | 0 | empty |
| 1 | market-cap bucket | 0 | empty |
| 1 | price band | 0 | empty |
| 1 | policy | 0 | empty |
| 1 | macro | 0 | empty |
| 16 | index | 0 | empty |
| 16 | price band | 0 | empty |
| 16 | macro | 0 | empty |
| 16 | market-wide | 0 | empty |
| 3 | sector | 0 | empty |
| 6 | sector | 0 | empty |
| 3 | theme | 0 | empty |
| 3 | market-cap bucket | 0 | empty |
| 6 | market-cap bucket | 0 | empty |
| 3 | price band | 0 | empty |
| 6 | price band | 0 | empty |
| 3 | policy | 0 | empty |
| 3 | macro | 0 | empty |
| 6 | macro | 0 | empty |
| 6 | market-wide | 0 | empty |
| none | theme | 0 | empty |
| none | index | 0 | empty |
| none | price band | 0 | empty |
| none | macro | 0 | empty |
| none | sector | 1 | thin |
| none | market-cap bucket | 1 | thin |
| none | policy | 1 | thin |
| none | industry | 2 | thin |
| 9 | sector | 0 | empty |
| 9 | theme | 0 | empty |
| 9 | market-cap bucket | 0 | empty |
| 9 | price band | 0 | empty |
| 9 | policy | 0 | empty |
| 9 | macro | 0 | empty |
| 9 | market-wide | 1 | thin |
| 12 | sector | 0 | empty |
| 12 | theme | 0 | empty |
| 12 | index | 0 | empty |
| 12 | market-cap bucket | 0 | empty |
| 12 | price band | 0 | empty |
| 12 | macro | 0 | empty |
| 12 | market-wide | 0 | empty |
| 11 | sector | 0 | empty |
| 11 | theme | 0 | empty |
| 11 | market-cap bucket | 0 | empty |
| 11 | price band | 0 | empty |
| 11 | policy | 0 | empty |
| 11 | market-wide | 0 | empty |
| 14 | industry | 0 | empty |
| 14 | sector | 0 | empty |
| 19 | sector | 0 | empty |
| 14 | theme | 0 | empty |
| 14 | index | 0 | empty |
| 19 | index | 0 | empty |
| 19 | price band | 0 | empty |
| 14 | policy | 0 | empty |
| 14 | macro | 0 | empty |
| 19 | macro | 0 | empty |
| 19 | market-wide | 0 | empty |
| 14 | price band | 1 | thin |
| 19 | theme | 2 | thin |
| 19 | market-cap bucket | 2 | thin |
| 18 | index | 0 | empty |
| 18 | market-cap bucket | 0 | empty |
| 18 | price band | 0 | empty |
| 18 | macro | 0 | empty |
| 18 | market-wide | 0 | empty |
| 18 | industry | 1 | thin |
| 18 | theme | 2 | thin |
| 4 | price band | 0 | empty |
| 4 | policy | 0 | empty |
| 4 | macro | 0 | empty |
| 4 | sector | 1 | thin |
| 4 | index | 2 | thin |
| 17 | sector | 0 | empty |
| 17 | index | 0 | empty |
| 17 | market-cap bucket | 0 | empty |
| 17 | price band | 0 | empty |
| 17 | policy | 0 | empty |
| 17 | macro | 0 | empty |
| 17 | market-wide | 0 | empty |
| 17 | theme | 1 | thin |
| 8 | sector | 0 | empty |
| 8 | theme | 0 | empty |
| 8 | market-cap bucket | 0 | empty |
| 8 | price band | 0 | empty |
| 8 | policy | 0 | empty |
| 8 | macro | 0 | empty |
| 8 | market-wide | 0 | empty |
| 15 | sector | 0 | empty |
| 15 | theme | 0 | empty |
| 15 | index | 0 | empty |
| 15 | market-cap bucket | 0 | empty |
| 15 | price band | 0 | empty |
| 15 | policy | 0 | empty |
| 15 | macro | 0 | empty |
| 15 | industry | 2 | thin |
| 7 | stock | 0 | empty |
| 7 | sector | 0 | empty |
| 7 | market-cap bucket | 0 | empty |
| 7 | price band | 0 | empty |
| 7 | macro | 0 | empty |
| 7 | market-wide | 0 | empty |
| 20 | sector | 0 | empty |
| 20 | theme | 0 | empty |
| 20 | price band | 0 | empty |
| 20 | macro | 0 | empty |
| 20 | industry | 1 | thin |
| 20 | index | 1 | thin |
| 20 | market-cap bucket | 1 | thin |
| 20 | policy | 2 | thin |
| 20 | market-wide | 2 | thin |
| 13 | stock | 0 | empty |
| 13 | sector | 0 | empty |
| 13 | theme | 0 | empty |
| 13 | index | 0 | empty |
| 13 | price band | 0 | empty |
| 13 | policy | 0 | empty |
| 13 | macro | 0 | empty |
| 13 | industry | 1 | thin |
| 13 | market-cap bucket | 1 | thin |
| 5 | sector | 0 | empty |
| 5 | theme | 0 | empty |
| 5 | market-cap bucket | 0 | empty |
| 5 | price band | 0 | empty |
| 5 | policy | 0 | empty |
| 5 | macro | 0 | empty |
| 5 | market-wide | 0 | empty |
| 5 | industry | 1 | thin |
| 5 | index | 1 | thin |
| 10 | stock | 0 | empty |
| 10 | industry | 0 | empty |
| 10 | sector | 0 | empty |
| 10 | theme | 0 | empty |
| 10 | index | 0 | empty |
| 10 | market-cap bucket | 0 | empty |
| 10 | price band | 0 | empty |
| 10 | policy | 0 | empty |
| 10 | macro | 0 | empty |
| 10 | market-wide | 0 | empty |
### 3.4 The full 3D grid

The full 3D grid has **840** cells (21 families x 10 levels x 4 styles): **648** empty, **98** thin (1-2 cases), **94** with 3 or more cases.

### 3.5 Style gaps inside a family

| family | missing style |
| --- | --- |
| 13 | point-in-time |
| 14 | point-in-time |
| 15 | point-in-time |
| 16 | point-in-time |
| 17 | point-in-time |
| 18 | point-in-time |
| 19 | point-in-time |
| 20 | Hinglish, point-in-time |
| none | terse |

## 4. One table per family

Each case appears once, under its primary family; `also` lists its other families. §3 counts a multi-family case in every family it lists.

### Family 1 - Lookup (136 primary cases)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0001 | shivam30:DBQ1 | stock | terse | - | 2 | AEROFLEX products + close on a date |
| MB0002 | shivam30:DBQ2 | stock | terse | - | 9 | 532627 latest AR: control change |
| MB0003 | shivam30:DBQ3 | stock | terse | - | - | 544161 business + segments |
| MB0005 | shivam30:DBQ5 | stock | terse | - | - | DEEDEV Aug-2026 concall remark |
| MB0009 | shivam30:Q14 | stock | terse | - | 2 | VISHNU Note 5 of latest results + geo split |
| MB0023 | shivam30:QA3 | stock | natural | - | - | How many manufacturing facilities does Ganesha Ecosphere have, per its investor presentation of 5 August 2026? |
| MB0024 | shivam30:QA4 | stock | natural | - | - | What are the key products of Chemcon Speciality Chemicals per its investor presentation of 22 May 2026, and whom did it mention as acquired for inorganic growth? |
| MB0026 | shivam30:QA6 | stock | natural | - | - | What did BSE: 540879 show on page 21 (of 79) of its investor presentation dated 24 October 2026 regarding a licence to manufacture? |
| MB0027 | shivam30:QA7 | stock | natural | - | 3 | What did ISIN INE864I01014 say about its fuel-cell capacity expansion due to complete by the end of this year, per its transcript of 6 August 2026? |
| MB0029 | shivam30:QA9 | stock | point-in-time | - | 5 | What did NSE: SAILIFE say about its newly commissioned facilities, as of the latest data? |
| MB0030 | shivam30:QA10 | stock | natural | - | 3 | Per the transcript of 18 September 2026 of 540678 / COCHINSHIP: what did it say about the MOU with HD KSOE, and how will EBITDA margins progress from electric tug boats, ... |
| MB0031 | variations300:DBQ1-V1 | stock | natural | yes | 2 | What does Hariom Pipe Industries (NSE: HARIOMPIPE) make, and what was its NSE close on 16 October 2026? |
| MB0032 | variations300:DBQ1-V2 | stock | natural | yes | 2 | What does RTS Power Corporation (NSE: RTSPOWR) make, and what was its NSE close on 16 October 2026? |
| MB0033 | variations300:DBQ1-V3 | stock | natural | yes | 2 | What does NSE: AMIORG (now ACUTAAS) make, and what was its NSE close on 16 October 2026? |
| MB0034 | variations300:DBQ1-V4 | stock | terse | yes | 2 | RELIANCE products + close 16 Oct 2026 |
| MB0035 | variations300:DBQ1-V5 | stock | Hinglish | yes | 2 | Bhai, KRBL (NSE: KRBL) kya banati hai, aur 16 October 2026 ko NSE par kitne pe close hui? Products aur close dono batao, short mein. |
| MB0036 | variations300:DBQ1-V6 | stock | natural | yes | 2 | What does SETUINFRA (BSE: 533605) make, and what was its BSE close on 30 September 2026? |
| MB0037 | variations300:DBQ1-V7 | industry | natural | yes | 2 | For all listed companies in Industrial Products, list what each company makes and its NSE close on 16 October 2026. |
| MB0038 | variations300:DBQ1-V8 | index | natural | partial | 2 | For the NIFTY TOTAL MARKET constituents, list what each company makes and its NSE close on 16 October 2026. |
| MB0039 | variations300:DBQ1-V9 | stock | point-in-time | yes | 2 | As of 30 June 2026, what did Protean eGov Technologies (NSE: PROTEAN)'s latest annual report say it makes, and what was its close that day? |
| MB0040 | variations300:DBQ1-V10 | stock | natural | yes | 2 | What does Life Insurance Corporation Of India (NSE: LICI) make, and what was its NSE close on 16 October 2026? If either is not in our data, answer NOT IN DATA and say wh... |
| MB0041 | variations300:DBQ2-V1 | stock | natural | yes | 9 | What did CESC (NSE: CESC)'s latest annual report (FY2026) disclose about a change in ownership or control, and where in the report? |
| MB0042 | variations300:DBQ2-V2 | stock | natural | yes | 9 | What did Reliance Infrastructure (NSE: RELINFRA)'s latest annual report (FY2026) disclose about a change in ownership or control, and where in the report? |
| MB0043 | variations300:DBQ2-V3 | stock | natural | yes | 9 | What did NSE: SHIL (now HINDWAREAP)'s latest annual report (FY2026) disclose about a change in ownership or control, and where in the report? |
| MB0044 | variations300:DBQ2-V4 | stock | terse | partial | 9 | 570002 latest annual report control change |
| MB0045 | variations300:DBQ2-V5 | stock | Hinglish | yes | 9 | JSW Steel (NSE: JSWSTEEL) ke latest annual report mein ownership ya control change ke baare mein kya likha hai? Kaunsa saal, kaunsa page, aur exactly kya disclosure hai? |
| MB0046 | variations300:DBQ2-V6 | stock | natural | yes | 9 | What did Craftsman Automation (NSE: CRAFTSMAN)'s latest annual report (FY2025) disclose about a change in ownership or control, and where in the report? |
| MB0047 | variations300:DBQ2-V7 | industry | natural | yes | 9 | For all listed companies in Power, which companies disclosed a change in control or ownership in their latest annual report, and what changed? |
| MB0048 | variations300:DBQ2-V8 | index | natural | partial | 9 | For the NIFTY 500 constituents, which companies disclosed a change in control or ownership in their latest annual report, and what changed? |
| MB0049 | variations300:DBQ2-V9 | stock | point-in-time | yes | 9 | As of 30 June 2026, what did Prism Johnson (NSE: PRSMJOHNSN)'s latest filed annual report say about a change in control or ownership? |
| MB0050 | variations300:DBQ2-V10 | stock | natural | no | 9 | What did Aakash Exploration Services (NSE: AAKASH)'s latest annual report disclose about a change in control? If no annual report is held for it, answer NOT IN DATA and n... |
| MB0051 | variations300:DBQ3-V1 | stock | natural | partial | - | What is Asian Granito India (NSE: ASIANTILES)'s business, and what segments and segment revenue did it report for the latest quarter? |
| MB0052 | variations300:DBQ3-V2 | stock | natural | no | - | What is Asian Paints (NSE: ASIANPAINT)'s business, and what segments and segment revenue did it report for the latest quarter? |
| MB0053 | variations300:DBQ3-V3 | stock | natural | partial | - | What is NSE: PVR (now PVRINOX)'s business, and what segments and segment revenue did it report for the latest quarter? |
| MB0054 | variations300:DBQ3-V4 | stock | terse | no | - | DHARMAJ business segments FY26 |
| MB0055 | variations300:DBQ3-V5 | stock | Hinglish | partial | - | Highway Infrastructure (NSE: HILINFRA) ka business kya hai aur segments kaunse hain? Annual report aur latest results ke hisaab se segment revenue bhi batao. |
| MB0056 | variations300:DBQ3-V6 | stock | natural | no | - | What is Antony Waste Handling Cell (NSE: AWHCL)'s business, and what segments and segment revenue did it report for the latest quarter? |
| MB0057 | variations300:DBQ3-V7 | industry | natural | partial | - | For all listed companies in Consumer Durables, what are the reported business segments and their latest segment revenue? |
| MB0058 | variations300:DBQ3-V8 | index | natural | partial | - | For the NIFTY500 EQUAL WEIGHT constituents, what are the reported business segments and their latest segment revenue? |
| MB0059 | variations300:DBQ3-V9 | stock | point-in-time | yes | - | As of 30 June 2026, what did Arvind (NSE: ARVIND)'s latest results and annual report disclose about its business and segments? |
| MB0060 | variations300:DBQ3-V10 | stock | natural | no | - | For 20 Microns (NSE: 20MICRONS), what are its business segments and segment revenue for Q1FY27? If segment disclosure is not in the data, answer NOT IN DATA and say which... |
| MB0071 | variations300:DBQ5-V1 | stock | natural | yes | - | What did Jash Engineering (NSE: JASH)'s management say about demand and margins on its 18 August 2026 earnings call, and who said it? |
| MB0072 | variations300:DBQ5-V2 | stock | natural | partial | - | What did CG Power and Industrial Solutions (NSE: CGPOWER)'s management say about demand and margins on its 12 May 2025 earnings call, and who said it? |
| MB0073 | variations300:DBQ5-V3 | stock | natural | partial | - | What did NSE: SUVENPHAR (now COHANCE)'s management say about demand and margins on its 15 May 2026 earnings call, and who said it? |
| MB0074 | variations300:DBQ5-V4 | stock | terse | partial | - | DABUR call 2025-02-04 management outlook |
| MB0075 | variations300:DBQ5-V5 | stock | Hinglish | partial | - | Mahanagar Gas (NSE: MGL) ki 16 February 2026 wali earnings call mein management ne business aur margin outlook ke baare mein kya kaha? Speaker ka naam aur quote batao. |
| MB0076 | variations300:DBQ5-V6 | stock | natural | partial | - | What did LEAP India (NSE: LEAPIND)'s management say about demand and margins on its 4 September 2026 earnings call, and who said it? |
| MB0077 | variations300:DBQ5-V7 | industry | natural | no | - | For all listed companies in Industrial Manufacturing, what did management say about demand and margins on their latest earnings calls, with quoted evidence? |
| MB0078 | variations300:DBQ5-V8 | index | natural | partial | - | For the NIFTY500 MULTICAP 50:25:25 constituents, what did management say about demand and margins on their latest earnings calls, with quoted evidence? |
| MB0079 | variations300:DBQ5-V9 | stock | point-in-time | yes | - | As of 31 July 2026, what had Concord Enviro Systems (NSE: CEWATER)'s management last said on an earnings call about demand and margins? |
| MB0080 | variations300:DBQ5-V10 | stock | natural | no | - | What did 21st Century Management Services (NSE: 21STCENMGM) say about demand and margins on its 13 August 2026 earnings call? If the transcript is held but not chunked, a... |
| MB0111 | variations300:Q14-V1 | stock | natural | partial | 2 | Note 5 of Diligent Media Corporation (NSE: DNAMEDIA)'s Q1FY27 results — what does it say, and what is the geographic revenue split, consolidated? |
| MB0112 | variations300:Q14-V2 | stock | natural | partial | 2 | Note 5 of GTL (NSE: GTL)'s Q1FY27 results — what does it say, and what is the geographic revenue split, consolidated? |
| MB0113 | variations300:Q14-V3 | stock | natural | yes | 2 | Note 5 of NSE: ADANIGAS (now ATGL)'s Q1FY27 results — what does it say, and what is the geographic revenue split, consolidated? |
| MB0114 | variations300:Q14-V4 | stock | terse | partial | 2 | RACE results note 5 geo split Q1FY27 |
| MB0115 | variations300:Q14-V5 | stock | Hinglish | partial | 2 | Balmer Lawrie & Company (NSE: BALMLAWRIE) ke Q1FY27 results ki note 5 mein kya likha hai, aur geographic revenue split kya hai? Consolidated basis, quote ke saath. |
| MB0116 | variations300:Q14-V6 | stock | natural | partial | 2 | Note 5 of Gloster (NSE: GLOSTERLTD)'s Q4FY26 (January-March 2026) results — what does it say, and what is the geographic revenue split, consolidated? |
| MB0117 | variations300:Q14-V7 | industry | natural | yes | 2 | For all listed companies in the industry, which companies disclose a geographic revenue split in their results notes for Q1FY27, and what is it? |
| MB0118 | variations300:Q14-V8 | index | natural | partial | 2 | For the NIFTY IPO constituents, which companies disclose a geographic revenue split in their results notes for Q1FY27, and what is it? |
| MB0119 | variations300:Q14-V9 | stock | point-in-time | partial | 2 | As of 30 June 2026, what did note 5 of Oil Country Tubular (NSE: OILCOUNTUB)'s as of 30 June 2026 results say, and what was its geographic split? |
| MB0120 | variations300:Q14-V10 | stock | natural | no | 2 | What does note 5 of NMDC (NSE: NMDC)'s results for Q2FY25 (July-September 2024) say, and what is the geographic split? If that quarter's results notes are not stored, ans... |
| MB0251 | variations300:QA3-V1 | stock | natural | yes | - | How many manufacturing facilities does Iris Clothings (NSE: IRISDOREME) report in its investor presentation dated 27 July 2026, and where are they? |
| MB0252 | variations300:QA3-V2 | stock | natural | yes | - | How many manufacturing facilities does K.P.R. Mill (NSE: KPRMILL) report in its investor presentation dated 13 August 2026, and where are they? |
| MB0253 | variations300:QA3-V3 | stock | natural | yes | - | How many manufacturing facilities does NSE: ARISINFRA (now ARIS) report in its investor presentation dated 5 August 2026, and where are they? |
| MB0254 | variations300:QA3-V4 | stock | terse | yes | - | BSE facilities deck 2026-08-04 |
| MB0255 | variations300:QA3-V5 | stock | Hinglish | yes | - | Prime Focus (NSE: PFOCUS) ke 29 September 2026 wale investor presentation ke hisaab se kitni manufacturing facilities hain, aur kahan? Slide ka reference bhi do. |
| MB0256 | variations300:QA3-V6 | stock | natural | yes | - | How many manufacturing facilities does Vodafone Idea (NSE: IDEA) report in its investor presentation dated 30 June 2026, and where are they? |
| MB0257 | variations300:QA3-V7 | industry | natural | partial | - | For all listed companies in Textiles & Apparels, how many manufacturing facilities does each company report in its latest investor presentation? |
| MB0258 | variations300:QA3-V8 | index | natural | partial | - | For the NIFTY MIDSMALLCAP400 50:50 constituents, how many manufacturing facilities does each company report in its latest investor presentation? |
| MB0259 | variations300:QA3-V9 | stock | point-in-time | yes | - | As of 31 July 2026, how many manufacturing facilities did 3M India (NSE: 3MINDIA) report in its latest deck filed by that date? |
| MB0260 | variations300:QA3-V10 | stock | natural | no | - | How many manufacturing facilities does 21st Century Management Services (NSE: 21STCENMGM) report in its investor presentation dated 25 February 2022? If no deck is stored... |
| MB0261 | variations300:QA4-V1 | stock | natural | yes | - | Per POCL Enterprises (NSE: POEL)'s deck of 14 August 2026, what are its key products, and which company did it mention as acquired for inorganic growth? |
| MB0262 | variations300:QA4-V2 | stock | natural | yes | - | Per Gujarat Fluorochemicals (NSE: FLUOROCHEM)'s deck of 12 August 2026, what are its key products, and which company did it mention as acquired for inorganic growth? |
| MB0263 | variations300:QA4-V3 | stock | natural | yes | - | Per NSE: GLS (now ALIVUS)'s deck of 30 July 2026, what are its key products, and which company did it mention as acquired for inorganic growth? |
| MB0264 | variations300:QA4-V4 | stock | terse | partial | - | ANDHRAPAP products acquisitions deck 2025-02-08 |
| MB0265 | variations300:QA4-V5 | stock | Hinglish | yes | - | Bharat Petroleum Corporation (NSE: BPCL) ke 22 July 2026 wale deck mein main products kya hain, aur inorganic growth ke liye kis company ka acquisition mention kiya gaya ... |
| MB0266 | variations300:QA4-V6 | stock | natural | yes | - | Per Bikaji Foods International (NSE: BIKAJI)'s deck of 21 May 2026, what are its key products, and which company did it mention as acquired for inorganic growth? |
| MB0267 | variations300:QA4-V7 | industry | natural | yes | - | For all listed companies in Chemicals & Petrochemicals, what products and acquisitions does each company report in its latest investor presentation? |
| MB0268 | variations300:QA4-V8 | index | natural | partial | - | For the NIFTY500 AHIMSA constituents, what products and acquisitions does each company report in its latest investor presentation? |
| MB0269 | variations300:QA4-V9 | stock | point-in-time | yes | - | As of 30 June 2026, what did Jaro Institute of Technology Management and Research (NSE: JARO)'s latest deck disclose about its products and acquisitions? |
| MB0270 | variations300:QA4-V10 | stock | natural | no | - | What are 21st Century Management Services (NSE: 21STCENMGM)'s key products and its latest acquisition? If the deck is held but the page text is not extracted, answer NOT ... |
| MB0281 | variations300:QA6-V1 | stock | natural | yes | - | What does page 10 of Data Patterns (India) (NSE: DATAPATTNS)'s investor presentation dated 30 July 2026 say about its manufacturing licence or capacity? |
| MB0282 | variations300:QA6-V2 | stock | natural | no | - | What does page 3 of Hitachi Energy India (NSE: POWERINDIA)'s investor presentation dated 16 September 2026 say about its manufacturing licence or capacity? |
| MB0283 | variations300:QA6-V3 | stock | natural | yes | - | What does page 24 of NSE: AMIRCHAND (now AEROPLANE)'s investor presentation dated 7 August 2026 say about its manufacturing licence or capacity? |
| MB0284 | variations300:QA6-V4 | stock | terse | yes | - | REFEX deck page 31 2026-07-29 |
| MB0285 | variations300:QA6-V5 | stock | Hinglish | yes | - | Bodhi Tree Multimedia (NSE: BTML) ke 14 August 2026 wale investor presentation ke page 5 par kya dikhaya gaya hai? Text ya quote ke saath batao. |
| MB0286 | variations300:QA6-V6 | stock | natural | yes | - | What does page 18 of DCM Shriram (NSE: DCMSHRIRAM)'s investor presentation dated 13 May 2026 say about its manufacturing licence or capacity? |
| MB0287 | variations300:QA6-V7 | industry | natural | yes | - | For all listed companies in Aerospace & Defense, what do the latest decks say on their capacity or licensing slides? |
| MB0288 | variations300:QA6-V8 | index | natural | partial | - | For the NIFTY SMALLCAP 250 constituents, what do the latest decks say on their capacity or licensing slides? |
| MB0289 | variations300:QA6-V9 | stock | point-in-time | yes | - | As of 30 September 2026, what did page 27 of Magnum Ventures (NSE: MAGNUM)'s latest deck filed by that date say? |
| MB0290 | variations300:QA6-V10 | stock | natural | no | - | What does page 41 of Capital Trust (NSE: CAPTRUST)'s investor presentation dated 18 August 2026 say? If the deck has fewer pages, answer NOT IN DATA and give the page cou... |
| MB0291 | variations300:QA7-V1 | stock | natural | yes | 3 | What did Azad Engineering (NSE: AZAD) say about its capacity expansion, and the completion timeline, on its 14 August 2026 earnings call? |
| MB0292 | variations300:QA7-V2 | stock | natural | partial | 3 | What did ABB India (NSE: ABB) say about its capacity expansion, and the completion timeline, on its 16 May 2025 earnings call? |
| MB0293 | variations300:QA7-V3 | stock | natural | yes | 3 | What did NSE: IDFCBANK (now IDFCFIRSTB) say about its capacity expansion, and the completion timeline, on its 31 July 2026 earnings call? |
| MB0294 | variations300:QA7-V4 | stock | terse | yes | 3 | ENTERO capacity timeline call 2026-08-17 |
| MB0295 | variations300:QA7-V5 | stock | Hinglish | yes | 3 | Max Healthcare Institute (NSE: MAXHEALTH) ne apni 20 August 2026 wali call mein capacity expansion ka kya timeline bataya? Completion date aur capex ke saath quote do. |
| MB0296 | variations300:QA7-V6 | stock | natural | yes | 3 | What did Affle 3i (NSE: AFFLE) say about its capacity expansion, and the completion timeline, on its 18 May 2026 earnings call? |
| MB0297 | variations300:QA7-V7 | industry | natural | yes | 3 | For all listed companies in Electrical Equipment, what capacity-expansion timelines did management give on their latest earnings calls? |
| MB0298 | variations300:QA7-V8 | index | natural | no | 3 | For the NIFTY MICROCAP 250 constituents, what capacity-expansion timelines did management give on their latest earnings calls? |
| MB0299 | variations300:QA7-V9 | stock | point-in-time | yes | 3 | As of 31 July 2026, what had Arvind SmartSpaces (NSE: ARVSMART) said about its capacity expansion timeline by that date? |
| MB0300 | variations300:QA7-V10 | stock | natural | no | 3 | What did 21st Century Management Services (NSE: 21STCENMGM) say about its capacity expansion timeline on 6 August 2025? If the transcript exists but is not chunked, answe... |
| MB0311 | variations300:QA9-V1 | stock | point-in-time | yes | 5 | What did Onesource Specialty Pharma (NSE: ONESOURCE) say about its newly commissioned facilities, as of the latest data, and in which document type? |
| MB0312 | variations300:QA9-V2 | stock | point-in-time | yes | 5 | What did Cipla (NSE: CIPLA) say about its newly commissioned facilities, as of the latest data, and in which document type? |
| MB0313 | variations300:QA9-V3 | stock | point-in-time | yes | 5 | What did NSE: MFL (now EPIGRAL) say about its newly commissioned facilities, as of the latest data, and in which document type? |
| MB0314 | variations300:QA9-V4 | stock | terse | yes | 5 | RAILTEL newly commissioned facilities latest |
| MB0315 | variations300:QA9-V5 | stock | Hinglish | yes | 5 | R K Swamy (NSE: RKSWAMY) ne apni nayi commissioned facilities ke baare mein sabse latest kya kaha hai? Deck, concall aur annual report teeno check karke source do. |
| MB0316 | variations300:QA9-V6 | stock | point-in-time | yes | 5 | What did Enviro Infra Engineers (NSE: EIEL) say about its newly commissioned facilities, as of the latest data, and in which document type? |
| MB0317 | variations300:QA9-V7 | industry | natural | yes | 5 | For all listed companies in Pharmaceuticals & Biotechnology, what have the companies said about newly commissioned facilities across decks, calls and annual reports? |
| MB0318 | variations300:QA9-V8 | index | natural | partial | 5 | For the NIFTY500 SHARIAH constituents, what have the companies said about newly commissioned facilities across decks, calls and annual reports? |
| MB0319 | variations300:QA9-V9 | stock | point-in-time | yes | 5 | As of 30 June 2026, what had Kuantum Papers (NSE: KUANTUM) said about its newly commissioned facilities, using only documents known by that date? |
| MB0320 | variations300:QA9-V10 | stock | natural | no | 5 | What has 21st Century Management Services (NSE: 21STCENMGM) said about its newly commissioned facilities? If no document after since Jan 2026 is held, answer NOT IN DATA ... |
| MB0321 | variations300:QA10-V1 | stock | natural | yes | 3 | Per Jupiter Wagons (NSE: JWL)'s 21 August 2026 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? |
| MB0322 | variations300:QA10-V2 | stock | natural | yes | 3 | Per Ashok Leyland (NSE: ASHOKLEY)'s 21 August 2026 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? |
| MB0323 | variations300:QA10-V3 | stock | natural | yes | 3 | Per NSE: CENTURYTEX (now ABREL)'s 20 August 2026 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? |
| MB0324 | variations300:QA10-V4 | stock | terse | yes | 3 | HINDPETRO mou margin path call 2026-07-29 |
| MB0325 | variations300:QA10-V5 | stock | Hinglish | partial | 3 | L&T Technology Services (NSE: LTTS) ki 24 October 2025 wali call mein MOU partner kaun hai, aur EBITDA margin ka path kya bataya gaya? Plan aur numbers quote karo. |
| MB0326 | variations300:QA10-V6 | stock | natural | partial | 3 | Per Raymond Lifestyle (NSE: RAYMONDLSL)'s 4 November 2025 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? |
| MB0327 | variations300:QA10-V7 | industry | natural | no | 3 | For all listed companies in Industrial Manufacturing, what MOUs or partnerships and margin paths did management disclose on their latest calls? |
| MB0328 | variations300:QA10-V8 | index | natural | partial | 3 | For the NIFTY MIDCAP 150 constituents, what MOUs or partnerships and margin paths did management disclose on their latest calls? |
| MB0329 | variations300:QA10-V9 | stock | point-in-time | yes | 3 | As of 30 September 2026, what had Ecos (India) Mobility & Hospitality (NSE: ECOSMOBLTY) disclosed about its MOU and margin path? |
| MB0330 | variations300:QA10-V10 | stock | natural | no | 3 | What did 21st Century Management Services (NSE: 21STCENMGM) say about its MOU and EBITDA margin path on 1 August 2026? If the call is not held for that date, answer NOT I... |
| MB0556 | open300:A16-01 | market-wide | natural | partial | 3 | Which companies raised a QIP in FY26, and did the actual use of proceeds match the stated objects? |
| MB0557 | open300:A16-02 | stock | natural | partial | 3 | Is Polycab's capex funded by debt or internal accruals, and how does the disclosure show it? |
| MB0558 | open300:A16-03 | stock | natural | yes | 3 | Trent did a 1:2 bonus with ex-date 4 June 2026. What does that do to the EPS series, and how should a price chart treat it? |
| MB0559 | open300:A16-04 | stock | natural | partial | 3 | Suzlon has been cutting debt while spending on capacity. Which came first in the cash flow, and is the deleveraging real? |
| MB0560 | open300:A16-05 | stock | natural | partial | 3 | RVNL and NBCC are asset-light but cash-hungry. How do they fund working capital, and what does that do to return on capital? |
| MB0561 | open300:A16-06 | market-wide | natural | partial | 3 | Which companies put money into a subsidiary or JV last year, and was it disclosed as a related-party transaction? |
| MB0562 | open300:A16-07 | stock | natural | partial | 3 | ITC and Colgate pay out most of their earnings. Is the payout covered by free cash flow, and what is left for growth? |
| MB0563 | open300:A16-08 | stock | terse | partial | 3 | buyback vs dividend choices FY26 |
| MB0564 | open300:A16-09 | stock | natural | partial | 3 | UltraTech bought India Cements and Kesoram. How was the acquisition funded, and what did it do to net debt/EBITDA? |
| MB0565 | open300:A16-10 | stock | natural | partial | 3 | Cochin Shipyard's ISRF JV needs capital. What is the committed amount, and who funds it? |
| MB0566 | open300:A16-11 | stock | Hinglish | partial | 3 | Tata Power ka renewable capex debt se fund ho raha hai ya internal accruals se? (Hinglish) |
| MB0567 | open300:A16-12 | stock | natural | partial | 3 | JSW Steel's acquisitions added debt. Did the leverage ratio stay within the stated ceiling, and what did management say? |
| MB0568 | open300:A16-13 | stock | natural | partial | 3 | Angel One earns float income on client funds. How does it deploy that float, and what is the risk if rates fall? |
| MB0569 | open300:A16-14 | stock | natural | partial | 3 | A company issues fresh equity to fund capex. How does that change ROCE and EPS, and what should an investor check first? |
| MB0570 | open300:A16-15 | market-wide | Hinglish | partial | 3 | Which company converted its capex into the best incremental ROCE over three years? Kaun sa company? (Hinglish) |

### Family 2 - Number (160 primary cases; 22 cross-referenced)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0004 | shivam30:DBQ4 | stock | terse | - | 11 | P/B now vs stored |
| MB0006 | shivam30:Q11 | stock | terse | - | 8 | KRISHNADEF segment revenue, latest quarter |
| MB0007 | shivam30:Q12 | stock | terse | - | - | Bank of Maharashtra net NPA % |
| MB0008 | shivam30:Q13 | stock | terse | - | - | ZENTEC 3-yr price CAGR |
| MB0010 | shivam30:Q15 | stock | terse | - | 11 | VINCOFE public shareholding Sep 2026 |
| MB0014 | shivam30:Q19 | stock | terse | - | 9 | MONQ50 ETF jump/fall + tracking error |
| MB0021 | shivam30:QA1 | stock | natural | - | - | What was the delivery volume (delivered quantity, not total traded quantity which includes intraday) of Ather Energy Ltd on 13 April 2026 and 14 April 2026, NSE + BSE com... |
| MB0022 | shivam30:QA2 | stock | point-in-time | - | 11 | What is the promoter holding of NSE: BLACKBUCK as of September 2026? |
| MB0025 | shivam30:QA5 | stock | point-in-time | - | - | How many equity shares does Lumax Auto Technologies have, and what is the promoter holding, as of the latest data? |
| MB0028 | shivam30:QA8 | stock | natural | - | - | What was the YTD high price of BSE: 532810 in 2026 (value and date)? |
| MB0061 | variations300:DBQ4-V1 | stock | natural | partial | 11 | What is Goldiam International (NSE: GOLDIAM)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. |
| MB0062 | variations300:DBQ4-V2 | stock | natural | partial | 11 | What is Ahlada Engineers (NSE: AHLADA)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. |
| MB0063 | variations300:DBQ4-V3 | stock | natural | partial | 11 | What is NSE: INFRATEL (now INDUSTOWER)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. |
| MB0064 | variations300:DBQ4-V4 | stock | terse | partial | 11 | GODREJIND pb ratio stored vs computed |
| MB0065 | variations300:DBQ4-V5 | stock | Hinglish | partial | 11 | Flexituff Ventures International (NSE: FLEXITUFF) ka P/B ratio kitna hai? Database mein stored ratio aur aaj ke price se nikaala hua ratio dono batao, aur farq kyun hai. |
| MB0066 | variations300:DBQ4-V6 | stock | natural | partial | 11 | What is Kovai Medical Center & Hospital (NSE: KOVAI)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. |
| MB0067 | variations300:DBQ4-V7 | industry | natural | partial | 11 | For all listed companies in Consumer Durables, rank the companies by P/B computed from the close on 19 October 2026 and the latest annual-report book value. |
| MB0068 | variations300:DBQ4-V8 | index | natural | partial | 11 | For the NIFTY500 LARGEMIDSMALL EQUAL-CAP WEIGHTED constituents, rank the companies by P/B computed from the close on 19 October 2026 and the latest annual-report book val... |
| MB0069 | variations300:DBQ4-V9 | stock | point-in-time | partial | 11 | As of 31 March 2026, what was Satia Industries (NSE: SATIA)'s P/B using the price and book value known by that date? Compare it with the stored ratio. |
| MB0070 | variations300:DBQ4-V10 | stock | natural | partial | 11 | What is Motherson Sumi Wiring India (NSE: MSUMI)'s P/B now versus the stored ratio, after adjusting for its corporate action? If book value per share is not held, say NOT... |
| MB0081 | variations300:Q11-V1 | stock | natural | yes | 8 | What was Avantel (NSE: AVANTEL)'s segment revenue for Q1FY27, with the absolute number for each reported segment? |
| MB0082 | variations300:Q11-V2 | stock | natural | yes | 8 | What was Astral (NSE: ASTRAL)'s segment revenue for Q1FY27, with the absolute number for each reported segment? |
| MB0083 | variations300:Q11-V3 | stock | natural | no | 8 | What was NSE: TIKONA (now GFSTEELS)'s segment revenue for Q1FY27, with the absolute number for each reported segment? |
| MB0084 | variations300:Q11-V4 | stock | terse | yes | 8 | GILLANDERS segment revenue Q1FY27 |
| MB0085 | variations300:Q11-V5 | stock | Hinglish | no | 8 | NTPC Green Energy (NSE: NTPCGREEN) ka Q1FY27 segment revenue kitna tha, segment-wise absolute numbers ke saath? XBRL context ka source bhi do. |
| MB0086 | variations300:Q11-V6 | stock | natural | yes | 8 | What was ACC (NSE: ACC)'s segment revenue for April-June 2026 (Q1 FY2026-27), with the absolute number for each reported segment? |
| MB0087 | variations300:Q11-V7 | industry | natural | yes | 8 | For all listed companies in Aerospace & Defense, rank the companies by reported segment revenue for Q1FY27. |
| MB0088 | variations300:Q11-V8 | index | natural | no | 8 | For the niftymidcap150 constituents, rank the companies by reported segment revenue for Q1FY27. |
| MB0089 | variations300:Q11-V9 | stock | point-in-time | yes | 8 | As of 30 June 2026, what segment revenue had Brainbees Solutions (NSE: FIRSTCRY) reported for Q1FY27? |
| MB0090 | variations300:Q11-V10 | stock | natural | no | 8 | What was 20 Microns (NSE: 20MICRONS)'s segment revenue for Q1FY27? If the filing has no segment context, answer NOT IN DATA and say which taxonomy is missing. |
| MB0091 | variations300:Q12-V1 | stock | natural | yes | - | What was Bank of Baroda (NSE: BANKBARODA)'s net NPA % for Q1FY27, and which XBRL concept and filing carry it? |
| MB0092 | variations300:Q12-V2 | stock | natural | yes | - | What was Fino Payments Bank (NSE: FINOPB)'s net NPA % for Q1FY27, and which XBRL concept and filing carry it? |
| MB0093 | variations300:Q12-V3 | stock | natural | yes | - | What was BSE scrip code 590003's net NPA % for Q1FY27, and which XBRL concept and filing carry it? |
| MB0094 | variations300:Q12-V4 | stock | terse | yes | - | BANKINDIA net npa Q1FY27 |
| MB0095 | variations300:Q12-V5 | stock | Hinglish | yes | - | Equitas Small Finance Bank (NSE: EQUITASBNK) ka net NPA percentage Q1FY27 mein kitna tha? Gross NPA aur net NPA dono, XBRL filing se batao. |
| MB0096 | variations300:Q12-V6 | stock | natural | yes | - | What was IndusInd Bank (NSE: INDUSINDBK)'s net NPA % for April-June 2026 (Q1 FY2026-27), and which XBRL concept and filing carry it? |
| MB0097 | variations300:Q12-V7 | industry | natural | yes | - | For all listed companies in Banks, rank the banks by net NPA % for Q1FY27, and state the source for each. |
| MB0098 | variations300:Q12-V8 | index | natural | partial | - | For the NIFTY HOUSING constituents, rank the banks by net NPA % for Q1FY27, and state the source for each. |
| MB0099 | variations300:Q12-V9 | stock | point-in-time | yes | - | As of 30 June 2026, what net NPA % had The Jammu & Kashmir Bank (NSE: J&KBANK) last reported for Q1FY27? |
| MB0100 | variations300:Q12-V10 | stock | natural | no | - | What was AU Small Finance Bank (NSE: AUBANK)'s net NPA % for Q2FY27? If that quarter's filing is not held, or the bank's XBRL uses a taxonomy without that concept, answer... |
| MB0101 | variations300:Q13-V1 | stock | natural | yes | - | What was Laxmi Goldorna House (NSE: LGHL)'s 3-year price CAGR to 19 October 2026, using split- and dividend-adjusted closes? State both endpoint dates. |
| MB0102 | variations300:Q13-V2 | stock | natural | partial | - | What was Orient Technologies (NSE: ORIENTTECH)'s 3-year price CAGR to 19 October 2026, using split- and dividend-adjusted closes? State both endpoint dates. |
| MB0103 | variations300:Q13-V3 | stock | natural | yes | - | What was NSE: RUCHI (now PATANJALI)'s 3-year price CAGR to 19 October 2026, using split- and dividend-adjusted closes? State both endpoint dates. |
| MB0104 | variations300:Q13-V4 | stock | terse | partial | - | AASTHA 3y cagr adjusted |
| MB0105 | variations300:Q13-V5 | stock | Hinglish | yes | - | eClerx Services (NSE: ECLERX) ka pichle 3 saal ka adjusted price CAGR kya raha? Start aur end date saaf-saaf likho, dividends aur splits adjust karke. |
| MB0106 | variations300:Q13-V6 | stock | natural | yes | - | What was Brigade Enterprises (NSE: BRIGADE)'s 3-year price CAGR to 30 September 2026, using split- and dividend-adjusted closes? State both endpoint dates. |
| MB0107 | variations300:Q13-V7 | industry | natural | no | - | For all listed companies in the industry, what was the 3-year adjusted price CAGR to 19 October 2026, ranked? |
| MB0108 | variations300:Q13-V8 | index | natural | no | - | For the NIFTY INDIA FPI 150 constituents, what was the 3-year adjusted price CAGR to 19 October 2026, ranked? |
| MB0109 | variations300:Q13-V9 | stock | point-in-time | yes | - | As of 30 June 2026, what was GRM Overseas (NSE: GRMOVER)'s 3-year adjusted price CAGR? |
| MB0110 | variations300:Q13-V10 | stock | natural | yes | - | What was InfoBeans Technologies (NSE: INFOBEAN)'s 3-year adjusted price CAGR across its corporate action? If adjusted prices are missing, answer NOT IN DATA. |
| MB0121 | variations300:Q15-V1 | stock | point-in-time | yes | 11 | What is Fertilizers and Chemicals Travancore (NSE: FACT)'s public shareholding as of Sep 2026? |
| MB0122 | variations300:Q15-V2 | stock | point-in-time | yes | 11 | What is NHPC (NSE: NHPC)'s public shareholding as of Sep 2026? |
| MB0123 | variations300:Q15-V3 | stock | point-in-time | yes | 11 | What is NSE: ADLABS (now IMAGICAA)'s public shareholding as of Sep 2026? |
| MB0124 | variations300:Q15-V4 | stock | terse | yes | 11 | ITI public shareholding Sep 2026 |
| MB0125 | variations300:Q15-V5 | stock | Hinglish | yes | 11 | M & B Engineering (NSE: MBEL) mein public shareholding Sep 2026 tak kitni hai? Promoter aur public dono ka percentage filing se batao. |
| MB0126 | variations300:Q15-V6 | stock | point-in-time | yes | 11 | What is JK Cement (NSE: JKCEMENT)'s public shareholding as of 30 September 2026? |
| MB0127 | variations300:Q15-V7 | industry | point-in-time | yes | 11 | For all listed companies in the industry, rank the companies by public shareholding as of Sep 2026. |
| MB0128 | variations300:Q15-V8 | index | point-in-time | no | 11 | For the NIFTY MIDCAP 100 constituents, rank the companies by public shareholding as of Sep 2026. |
| MB0129 | variations300:Q15-V9 | stock | point-in-time | yes | 11 | As of 30 June 2026, what was Digicontent (NSE: DGCONTENT)'s public shareholding per the latest filing on or before that date? |
| MB0130 | variations300:Q15-V10 | stock | point-in-time | no | 11 | What is 360 One Wam (NSE: 360ONE)'s public shareholding as of Sep 2026? If that quarter's shareholding filing is not held, answer NOT IN DATA. |
| MB0161 | variations300:Q19-V1 | stock | natural | partial | 9 | For Motilal Oswal Nasdaq 100 ETF (MOFN100) (MON100, ISIN INF247L01AP3), explain the jump in 10-18 Sep 2026 and 18-28 Sep 2026 using the underlying index and FX, and give ... |
| MB0162 | variations300:Q19-V2 | stock | natural | partial | 9 | For QGOLDHALF (QGOLDHALF, ISIN INF082J01010), a different ETF category from the original, what was the move in 10-18 Sep 2026 and 18-28 Sep 2026, and how did NAV track iN... |
| MB0163 | variations300:Q19-V3 | stock | natural | partial | 9 | For ISIN INF247L01AU3, what was the move in 10-18 Sep 2026 and 18-28 Sep 2026 and the tracking error against its underlying index and the rupee? |
| MB0164 | variations300:Q19-V4 | stock | terse | partial | 9 | QNIFTY jump tracking error Sep 2026 |
| MB0165 | variations300:Q19-V5 | stock | Hinglish | partial | 9 | Bajaj Finserv Nifty Bank ETF (BANKBETF, ISIN INF0QA701714) 10-18 September 2026 ke beech kyun jump hua aur 18-28 September mein kyun gira? Underlying index, FX aur NAV tr... |
| MB0166 | variations300:Q19-V6 | stock | natural | partial | 9 | For Bajaj Finserv Nifty 50 ETF (NIFTYBETF, ISIN INF0QA701722), explain the jump in September 2026 using the underlying index and FX, and give the NAV tracking error. |
| MB0167 | variations300:Q19-V7 | index | natural | partial | 9 | For the India-listed ETF universe, what explains the move in 10-18 Sep 2026 and 18-28 Sep 2026, and what is the NAV tracking error? |
| MB0168 | variations300:Q19-V8 | index | natural | partial | 9 | For the India-listed gold ETFs, which ETF moved most in 10-18 Sep 2026 and 18-28 Sep 2026, and what was its tracking error against the underlying index and FX? |
| MB0169 | variations300:Q19-V9 | stock | point-in-time | partial | 9 | As of 17 September 2026, what was the move in Quantum Gold ETF (QGOLDHALF, ISIN INF082J01408) up to that date, and what tracking error was visible by then? |
| MB0170 | variations300:Q19-V10 | stock | natural | no | 9 | For NIF100IETF (NIF100IETF, ISIN INF109KA1962), what was the move and NAV tracking error in 10-18 Sep 2026 and 18-28 Sep 2026? If the ETF has no NAV or iNAV rows, answer ... |
| MB0231 | variations300:QA1-V1 | stock | natural | yes | - | What was Eicher Motors (NSE: EICHERMOT)'s delivered quantity (not total traded quantity) on 15 September 2026 and 16 September 2026, NSE and BSE, with the combined total ... |
| MB0232 | variations300:QA1-V2 | stock | natural | yes | - | What was SEDEMAC Mechatronics (NSE: SEDEMAC)'s delivered quantity (not total traded quantity) on 15 September 2026 and 16 September 2026, NSE and BSE, with the combined t... |
| MB0233 | variations300:QA1-V3 | stock | natural | yes | - | What was NSE: DALALSTCOM (now KEEPLEARN)'s delivered quantity (not total traded quantity) on 10 June 2026 and 11 June 2026, NSE and BSE, with the combined total per day? |
| MB0234 | variations300:QA1-V4 | stock | terse | yes | - | ARIHANT delivery 11-12 Aug nse bse |
| MB0235 | variations300:QA1-V5 | stock | Hinglish | no | - | Sambandam Spinning Mills (NSE: SAMBANDAM) ka delivered quantity 11 August 2026 aur 12 August 2026 ko kitna tha? NSE, BSE aur dono ka total alag-alag batao. |
| MB0236 | variations300:QA1-V6 | stock | natural | yes | - | What was Sayaji Hotels (NSE: SAYAJIHOTL)'s delivered quantity (not total traded quantity) on 13 October 2026 and 14 October 2026, NSE and BSE, with the combined total per... |
| MB0237 | variations300:QA1-V7 | industry | natural | yes | - | For all listed companies in Automobiles, what was the delivered quantity on NSE and BSE on 10 February 2026 and 11 February 2026, ranked? |
| MB0238 | variations300:QA1-V8 | index | natural | partial | - | For the NIFTY SMALLCAP 500 constituents, what was the delivered quantity on NSE and BSE on 14 July 2026 and 15 July 2026, ranked? |
| MB0239 | variations300:QA1-V9 | stock | point-in-time | yes | - | As of 31 March 2026, what delivered quantity had Bimetal Bearings (NSE: BIMETAL) recorded on 15 September 2026 and 16 September 2026 on NSE and BSE? |
| MB0240 | variations300:QA1-V10 | stock | natural | no | - | What was Aakash Exploration Services (NSE: AAKASH)'s delivered quantity on 13 October 2026 and 14 October 2026 on NSE and BSE? If one exchange has no row, say which and a... |
| MB0241 | variations300:QA2-V1 | stock | point-in-time | yes | 11 | What is The Great Eastern Shipping Company (NSE: GESHIP)'s promoter holding as of Sep 2026, per the latest filing? |
| MB0242 | variations300:QA2-V2 | stock | point-in-time | yes | 11 | What is Indiqube Spaces (NSE: INDIQUBE)'s promoter holding as of Sep 2026, per the latest filing? |
| MB0243 | variations300:QA2-V3 | stock | point-in-time | partial | 11 | What is NSE: LTI (now LTM)'s promoter holding as of Sep 2026, per the latest filing? |
| MB0244 | variations300:QA2-V4 | stock | terse | yes | 11 | INTERARCH promoter holding Sep 2026 |
| MB0245 | variations300:QA2-V5 | stock | Hinglish | yes | 11 | Himadri Speciality Chemical (NSE: HSCL) mein promoter ki holding Sep 2026 tak kitni hai? Latest shareholding filing se number aur date batao. |
| MB0246 | variations300:QA2-V6 | stock | point-in-time | yes | 11 | What is Precot (NSE: PRECOT)'s promoter holding as of 30 September 2026, per the latest filing? |
| MB0247 | variations300:QA2-V7 | industry | point-in-time | partial | 11 | For all listed companies in Transport Services, what is the promoter holding as of Sep 2026, ranked from highest to lowest? |
| MB0248 | variations300:QA2-V8 | index | point-in-time | no | 11 | For the NIFTY MIDSMALLCAP 400 constituents, what is the promoter holding as of Sep 2026, ranked from highest to lowest? |
| MB0249 | variations300:QA2-V9 | stock | point-in-time | yes | 11 | As of 30 June 2026, what was The Phoenix Mills (NSE: PHOENIXLTD)'s promoter holding per the latest shareholding filing on or before that date? |
| MB0250 | variations300:QA2-V10 | stock | point-in-time | no | 11 | What is 360 One Wam (NSE: 360ONE)'s promoter holding as of Sep 2026? If the September 2026 shareholding filing is not held, answer NOT IN DATA and say why. |
| MB0271 | variations300:QA5-V1 | stock | point-in-time | yes | - | How many equity shares does CEAT (NSE: CEATLTD) have, and what is its promoter holding, as of the latest data? Say which filing each number comes from. |
| MB0272 | variations300:QA5-V2 | stock | point-in-time | yes | - | How many equity shares does Jamna Auto Industries (NSE: JAMNAAUTO) have, and what is its promoter holding, as of the latest data? Say which filing each number comes from. |
| MB0273 | variations300:QA5-V3 | stock | point-in-time | yes | - | How many equity shares does NSE: PROZONINTU (now PROZONER) have, and what is its promoter holding, as of the latest data? Say which filing each number comes from. |
| MB0274 | variations300:QA5-V4 | stock | terse | yes | - | BHARTIHEXA share count promoter holding |
| MB0275 | variations300:QA5-V5 | stock | Hinglish | yes | - | Dalmia Bharat (NSE: DALBHARAT) ke kitne equity shares hain aur promoter holding kitni hai? Dono numbers latest filing se, date ke saath batao. |
| MB0276 | variations300:QA5-V6 | stock | point-in-time | yes | - | How many equity shares does BCPL Railway Infrastructure (NSE: BCPL) have, and what is its promoter holding, as of the latest data? Say which filing each number comes from... |
| MB0277 | variations300:QA5-V7 | industry | natural | no | - | For all listed companies in Auto Components, give the latest exact share count and promoter holding for each company, with the filing date. |
| MB0278 | variations300:QA5-V8 | index | natural | no | - | For the NIFTY LARGEMIDCAP 250 constituents, give the latest exact share count and promoter holding for each company, with the filing date. |
| MB0279 | variations300:QA5-V9 | stock | point-in-time | yes | - | As of 30 June 2026, what were Ceinsys Tech (NSE: CEINSYS)'s exact share count and promoter holding? |
| MB0280 | variations300:QA5-V10 | stock | natural | yes | - | What are Kotyark Industries (NSE: KOTYARK)'s exact share count and promoter holding now, after its corporate action? If the post-action count is not held, answer NOT IN D... |
| MB0301 | variations300:QA8-V1 | stock | natural | yes | - | What was SBI Cards and Payment Services (NSE: SBICARD)'s YTD high price in 2026, with the value and the date, and on which exchange? |
| MB0302 | variations300:QA8-V2 | stock | natural | yes | - | What was Crisil (NSE: CRISIL)'s YTD high price in 2026, with the value and the date, and on which exchange? |
| MB0303 | variations300:QA8-V3 | stock | natural | yes | - | What was NSE: OMMETALS (now OMINFRAL)'s YTD high price in 2026, with the value and the date, and on which exchange? |
| MB0304 | variations300:QA8-V4 | stock | terse | yes | - | IPRINGLTD ytd high 2026 |
| MB0305 | variations300:QA8-V5 | stock | Hinglish | yes | - | Lakshmi Mills Company (NSE: LAKSHMIMIL) ka 2026 ka YTD high price kya tha, aur kis date ko? NSE ya BSE, exchange bhi batao. |
| MB0306 | variations300:QA8-V6 | stock | natural | yes | - | What was MMP Industries (NSE: MMP)'s YTD high price in 1 January-30 September 2026, with the value and the date, and on which exchange? |
| MB0307 | variations300:QA8-V7 | industry | natural | yes | - | For all listed companies in Finance, which companies made a new YTD high in 2026, with the value and date? |
| MB0308 | variations300:QA8-V8 | index | natural | partial | - | For the NIFTY 200 constituents, which companies made a new YTD high in 2026, with the value and date? |
| MB0309 | variations300:QA8-V9 | stock | point-in-time | yes | - | As of 30 June 2026, what was GMR Power and Urban Infra (NSE: GMRP&UI)'s YTD high in 2026 up to that date, and on which day? |
| MB0310 | variations300:QA8-V10 | stock | natural | yes | - | What was Metropolis Healthcare (NSE: METROPOLIS)'s YTD high for 2026, raw and adjusted for its corporate action? If adjusted prices are missing, say NOT IN DATA. |
| MB0541 | open300:A15-01 | stock | natural | partial | 12 | RVNL's order inflow in Q1 FY27 was Rs 5,417 crore. What is its order book cover in years, and how much of the book is slow-moving? |
| MB0542 | open300:A15-02 | stock | natural | partial | 12 | Inside HAL's Rs 2.54 lakh-crore book: which platforms dominate, and how many years of revenue does the mix imply? |
| MB0543 | open300:A15-03 | stock | natural | partial | 12 | Texrail's order book is Rs 9,923 crore. How much is wagons versus leasing, and which part is recurring? |
| MB0544 | open300:A15-04 | stock | natural | partial | 12 | BEL is waiting for CCS approval on QRSAM. Is that order already in the order book, and what happens to cover when it lands? |
| MB0545 | open300:A15-05 | stock | natural | partial | 12 | Mazagon Dock's order book: how much is shipbuilding versus repairs, and which is more stable? |
| MB0546 | open300:A15-06 | stock | natural | partial | 12 | Cochin Shipyard has an ISRF JV pipeline alongside its order book. How do you separate firm orders from JV optionality? |
| MB0547 | open300:A15-07 | stock | natural | partial | 12 | Ircon's order book: how much is the new dedicated-freight-corridor work, and has any of it been awarded? |
| MB0548 | open300:A15-08 | stock | natural | partial | 12 | Rites' order book has been falling. Why, and what does management say about the pipeline? |
| MB0549 | open300:A15-09 | stock | terse | partial | 12 | KEC T&D book-to-bill FY27 |
| MB0550 | open300:A15-10 | industry | Hinglish | partial | 12 | HG Infra ke order book mein EPC vs HAM kitna hai? (Hinglish) |
| MB0551 | open300:A15-11 | stock | natural | partial | 12 | Titagarh's wagon order book versus its 1,200/month capacity: at current orders, how many months of work is booked? |
| MB0552 | open300:A15-12 | stock | natural | partial | 12 | Afcons' order book includes the MAHSR C2 package. What share is under execution, and what does the TBM status say about it? |
| MB0553 | open300:A15-13 | stock | natural | partial | 12 | NBCC's PMC order book is large but its receivables are old. How do you judge whether the book is worth its face value? |
| MB0554 | open300:A15-14 | stock | natural | partial | 12 | GR Infra's order book and margin guidance: does the book mix support the guided margin? |
| MB0555 | open300:A15-15 | stock | Hinglish | partial | 12 | PNC Infratech's HAM assets are up for monetisation. Kaise order book se asset sale alag hai? (Hinglish) |
| MB0571 | open300:A17-01 | market-cap bucket | natural | yes | 4 | Which large caps saw the highest delivery percentage on 4 June 2024, and what does that say about who was selling? |
| MB0572 | open300:A17-02 | market-wide | natural | yes | 4 | Which stocks traded above 50% delivery on 24 September 2026, and were they the biggest movers? |
| MB0573 | open300:A17-03 | market-wide | terse | yes | 4 | delivery-spike ratio leaders this week |
| MB0574 | open300:A17-04 | stock | natural | yes | 4 | On 23 October 2026 Bonfiglioli saw several bulk deals. Who bought, at what price, and was it above or below the close? |
| MB0575 | open300:A17-05 | market-wide | natural | yes | 4 | Which side was bigger on 23 October 2026, FII or DII, and what does the ratio say about the marginal buyer? |
| MB0576 | open300:A17-06 | market-wide | natural | yes | 4 | Is there a same-day relationship between FII net flow and the Nifty move in 2026? Show the worst divergence day. |
| MB0577 | open300:A17-07 | stock | natural | no | 4 | What was the promoter holding in Titagarh last quarter? terse: TITAGARH promoter % |
| MB0578 | open300:A17-08 | market-cap bucket | natural | no | 4 | Which small caps saw the biggest mutual-fund accumulation last quarter? terse: MF buying small caps |
| MB0579 | open300:A17-09 | sector | natural | no | 4 | Which sectors did FIIs sell most in September 2026? terse: FII sector selling Sep 2026 |
| MB0580 | open300:A17-10 | index | Hinglish | partial | 4 | Index inclusion se kisi stock mein move aaya kya? Ek case batao. (Hinglish) |
| MB0581 | open300:A17-11 | market-wide | natural | partial | 4 | Which stocks had the highest turnover on 4 June 2024, and was it concentrated in PSU financials? |
| MB0582 | open300:A17-12 | market-wide | natural | yes | 4 | How many sessions in 2026 had FIIs selling and DIIs buying, and what did the Nifty do on those days on average? |
| MB0583 | open300:A17-13 | stock | natural | partial | 4 | Delivery percentage around results: does a high-delivery reaction day predict the next week? Test it on KEI and Titagarh. |
| MB0584 | open300:A17-14 | market-cap bucket | natural | yes | 4 | Which large caps saw delivery percentage fall the most in the week after 4 June 2024, and what does that signal? |
| MB0585 | open300:A17-15 | market-wide | Hinglish | yes | 4 | September 2026 mein FIIs ne kitna becha aur DIIs ne kitna kharida? (Hinglish) |
| MB0896 | reddit200:RD-I-066 | stock | natural | partial | - | DMart still trades at a high PE. What growth rate is the market assuming, and what has the company actually delivered? |
| MB0897 | reddit200:RD-I-067 | stock | natural | partial | - | Trent at this multiple: is the store-add run-rate enough to grow into it, or does the market need margin expansion too? |
| MB0898 | reddit200:RD-I-068 | stock | natural | partial | - | Eternal (ex-Zomato) on EV/sales: what does the multiple imply about the path to durable profit, and which segment has to carry it? |
| MB0899 | reddit200:RD-I-069 | stock | natural | partial | - | IRFC trades on P/B rather than PE. What ROE would justify its current multiple, and how does it compare with REC and PFC? |
| MB0900 | reddit200:RD-I-070 | stock | natural | partial | - | Paytm after the turnaround: is it still a loss-making story, and what metric should the valuation be judged on now? |
| MB0956 | reddit200:RD-N-051 | stock | natural | yes | - | TCS: does CFO track PAT, and are receivables days creeping as deal terms lengthen? |
| MB0957 | reddit200:RD-N-052 | stock | natural | partial | - | Infosys: has unbilled revenue grown faster than revenue, and what does that say about revenue recognition? |
| MB0958 | reddit200:RD-N-053 | stock | natural | partial | - | Mphasis: direct-client mix has risen. Did DSO and CFO/PAT improve with it, or did the mix just move revenue? |
| MB0959 | reddit200:RD-N-054 | stock | natural | partial | - | Coforge: how much of the growth is acquisition versus organic, and what did the acquisitions do to goodwill and cash conversion? |
| MB0960 | reddit200:RD-N-055 | stock | natural | partial | - | Persistent: is the margin expansion real, or is it capitalised development cost catching up with revenue? |
| MB0961 | reddit200:RD-N-056 | stock | natural | partial | - | Bajaj Holdings: what is the holdco discount to the sum of its listed stakes, and has it widened over five years? |
| MB0962 | reddit200:RD-N-057 | stock | natural | partial | - | Tata Investment: is the market cap above or below the value of its listed portfolio, and how has that gap behaved? |
| MB0963 | reddit200:RD-N-058 | stock | natural | partial | - | Godrej Industries holds several listed companies. What is the per-share value of the stakes versus the market price? |
| MB0964 | reddit200:RD-N-059 | stock | natural | partial | - | Bajaj Finserv: what are the insurance and lending pieces worth separately, and how much of the value is the holding company? |
| MB0965 | reddit200:RD-N-060 | stock | natural | partial | - | Tata Power: do the subsidiaries and the renewables book justify a market cap above the standalone utility? |
| MB0966 | reddit200:RD-N-061 | stock | natural | yes | - | Coal India: is the dividend covered by free cash flow after the capex plan, or is it borrowing from the future? |
| MB0967 | reddit200:RD-N-062 | stock | natural | partial | - | Power Grid: the regulated return sets the dividend. What happens to the payout if the capex cycle slows? |
| MB0968 | reddit200:RD-N-063 | stock | natural | partial | - | ITC: how much of the dividend is covered by the cigarette cash flow once the FMCG reinvestment is funded? |
| MB0969 | reddit200:RD-N-064 | stock | natural | partial | - | Hindustan Zinc: the payout is very high. Is it sustainable at current metal prices, and what does the capex plan need? |
| MB0970 | reddit200:RD-N-065 | stock | natural | partial | - | NMDC: at the bottom of the iron-ore cycle, would the dividend be cut, and what did the last downturn show? |
| MB0001 | shivam30:DBQ1 | stock | terse | - | primary 1 | AEROFLEX products + close on a date |
| MB0009 | shivam30:Q14 | stock | terse | - | primary 1 | VISHNU Note 5 of latest results + geo split |
| MB0031 | variations300:DBQ1-V1 | stock | natural | yes | primary 1 | What does Hariom Pipe Industries (NSE: HARIOMPIPE) make, and what was its NSE close on 16 October 2026? |
| MB0032 | variations300:DBQ1-V2 | stock | natural | yes | primary 1 | What does RTS Power Corporation (NSE: RTSPOWR) make, and what was its NSE close on 16 October 2026? |
| MB0033 | variations300:DBQ1-V3 | stock | natural | yes | primary 1 | What does NSE: AMIORG (now ACUTAAS) make, and what was its NSE close on 16 October 2026? |
| MB0034 | variations300:DBQ1-V4 | stock | terse | yes | primary 1 | RELIANCE products + close 16 Oct 2026 |
| MB0035 | variations300:DBQ1-V5 | stock | Hinglish | yes | primary 1 | Bhai, KRBL (NSE: KRBL) kya banati hai, aur 16 October 2026 ko NSE par kitne pe close hui? Products aur close dono batao, short mein. |
| MB0036 | variations300:DBQ1-V6 | stock | natural | yes | primary 1 | What does SETUINFRA (BSE: 533605) make, and what was its BSE close on 30 September 2026? |
| MB0037 | variations300:DBQ1-V7 | industry | natural | yes | primary 1 | For all listed companies in Industrial Products, list what each company makes and its NSE close on 16 October 2026. |
| MB0038 | variations300:DBQ1-V8 | index | natural | partial | primary 1 | For the NIFTY TOTAL MARKET constituents, list what each company makes and its NSE close on 16 October 2026. |
| MB0039 | variations300:DBQ1-V9 | stock | point-in-time | yes | primary 1 | As of 30 June 2026, what did Protean eGov Technologies (NSE: PROTEAN)'s latest annual report say it makes, and what was its close that day? |
| MB0040 | variations300:DBQ1-V10 | stock | natural | yes | primary 1 | What does Life Insurance Corporation Of India (NSE: LICI) make, and what was its NSE close on 16 October 2026? If either is not in our data, answer NOT IN DATA and say wh... |
| MB0111 | variations300:Q14-V1 | stock | natural | partial | primary 1 | Note 5 of Diligent Media Corporation (NSE: DNAMEDIA)'s Q1FY27 results — what does it say, and what is the geographic revenue split, consolidated? |
| MB0112 | variations300:Q14-V2 | stock | natural | partial | primary 1 | Note 5 of GTL (NSE: GTL)'s Q1FY27 results — what does it say, and what is the geographic revenue split, consolidated? |
| MB0113 | variations300:Q14-V3 | stock | natural | yes | primary 1 | Note 5 of NSE: ADANIGAS (now ATGL)'s Q1FY27 results — what does it say, and what is the geographic revenue split, consolidated? |
| MB0114 | variations300:Q14-V4 | stock | terse | partial | primary 1 | RACE results note 5 geo split Q1FY27 |
| MB0115 | variations300:Q14-V5 | stock | Hinglish | partial | primary 1 | Balmer Lawrie & Company (NSE: BALMLAWRIE) ke Q1FY27 results ki note 5 mein kya likha hai, aur geographic revenue split kya hai? Consolidated basis, quote ke saath. |
| MB0116 | variations300:Q14-V6 | stock | natural | partial | primary 1 | Note 5 of Gloster (NSE: GLOSTERLTD)'s Q4FY26 (January-March 2026) results — what does it say, and what is the geographic revenue split, consolidated? |
| MB0117 | variations300:Q14-V7 | industry | natural | yes | primary 1 | For all listed companies in the industry, which companies disclose a geographic revenue split in their results notes for Q1FY27, and what is it? |
| MB0118 | variations300:Q14-V8 | index | natural | partial | primary 1 | For the NIFTY IPO constituents, which companies disclose a geographic revenue split in their results notes for Q1FY27, and what is it? |
| MB0119 | variations300:Q14-V9 | stock | point-in-time | partial | primary 1 | As of 30 June 2026, what did note 5 of Oil Country Tubular (NSE: OILCOUNTUB)'s as of 30 June 2026 results say, and what was its geographic split? |
| MB0120 | variations300:Q14-V10 | stock | natural | no | primary 1 | What does note 5 of NMDC (NSE: NMDC)'s results for Q2FY25 (July-September 2024) say, and what is the geographic split? If that quarter's results notes are not stored, ans... |

### Family 3 - Change over time (40 primary cases; 48 cross-referenced)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0526 | open300:A14-01 | stock | natural | partial | 12 | BEL guided 15% revenue growth for FY27. What did Q1 FY27 actually deliver, and is the guidance still credible? |
| MB0527 | open300:A14-02 | stock | natural | partial | 12 | Suzlon guided a 17-18% EBITDA margin for FY27. What has it actually reported, and what is the gap? |
| MB0528 | open300:A14-03 | stock | natural | partial | 12 | Tatapower said 200 MW was commissioned and another 500 MW would follow in weeks. Did the later disclosure confirm the 500 MW? |
| MB0529 | open300:A14-04 | stock | natural | partial | 12 | SRF guided the Dahej second pharma plant in eight months with Rs 180 crore. Has it commissioned, and how would you check? |
| MB0530 | open300:A14-05 | stock | natural | yes | 12 | KEI's Sanand phase 1 was late by about six months and commissioned in December 2025. Did the company meet its own revised date? |
| MB0531 | open300:A14-06 | stock | Hinglish | partial | 12 | Polycab ne Q1FY27 mein 3.2 billion capex kiya — annual plan se aage ya peeche? (Hinglish) |
| MB0532 | open300:A14-07 | stock | natural | partial | 12 | HAL's order book is about Rs 2.54 lakh crore. What revenue cover is that, and did management guide to converting it faster? |
| MB0533 | open300:A14-08 | stock | natural | partial | 12 | RVNL's Q1 FY27 order inflow was Rs 5,417 crore. How does that compare with its annual revenue, and what does it imply for FY27? |
| MB0534 | open300:A14-09 | stock | point-in-time | partial | 12 | Texrail's order book is Rs 9,923 crore as of 30 June 2026. What is the execution period, and is it enough to meet guidance? |
| MB0535 | open300:A14-10 | stock | natural | partial | 12 | UltraTech's volume growth and capacity additions: did the FY26 additions land on the guided date? |
| MB0536 | open300:A14-11 | stock | terse | partial | 12 | IRCTC payment aggregator licence status Oct 2026 |
| MB0537 | open300:A14-12 | stock | natural | partial | 12 | Cochin Shipyard targeted the ISRF JV before the end of the financial year. Has the JV been signed, and what would confirm it? |
| MB0538 | open300:A14-13 | stock | natural | partial | 12 | Adani Green claimed a 20 GW renewable milestone in Q1 FY27. What was the previous milestone, and how long did the last 5 GW take? |
| MB0539 | open300:A14-14 | stock | natural | partial | 12 | Jubilant FoodWorks has about 3,600 stores. Did store additions hit the number it guided last year? |
| MB0540 | open300:A14-15 | stock | natural | partial | 12 | SAIL advanced capital repairs into Q1 FY27 to free up later quarters. Did the later quarters show the output recovery it implied? |
| MB0731 | ripple200:R06-01 | market-wide | natural | no | - | A mid-cap rallies 60% and raises equity. Trace the dilution, then the objects of the issue, then the capex, then the industry's capacity two years later. When does the re... |
| MB0732 | ripple200:R06-02 | market-wide | natural | no | - | A promoter releases a pledge after a rally. Trace it to the cost of the promoter's funding, then to another round of refinancing, then to the share count and the EPS. Wha... |
| MB0733 | ripple200:R06-03 | market-wide | natural | no | - | A small-cap re-rates from a 2,000 crore to a 12,000 crore market cap and enters an index. Trace it to the passive flow, then to the float, then to the price. Does the ind... |
| MB0734 | ripple200:R06-04 | market-wide | natural | partial | - | A company splits its shares. Trace it to the tick size and the retail participation, then to the delivery percentage, then to the stock's liquidity. Does a split change a... |
| MB0735 | ripple200:R06-05 | market-wide | natural | no | - | A company with surplus cash announces a buyback instead of a capex. Trace it to the EPS, then to the return on capital, then to the capacity it did not build, then to its... |
| MB0736 | ripple200:R06-06 | market-wide | natural | no | - | A company raises equity and repays debt. Trace the interest saving, then the PAT, then the rating, then the cost of the next borrowing. Is the equity cheaper than the deb... |
| MB0737 | ripple200:R06-07 | market-wide | natural | no | - | Four IPOs in one industry price in a quarter. Trace the supply of paper to the listed peers' valuation, then to their fund-raise plans, then to their capex. Who is dilute... |
| MB0738 | ripple200:R06-08 | market-wide | natural | partial | - | A promoter sells 8% through an offer for sale. Trace it to the free float, then to the index weight, then to the stock's reaction to flows. Does a higher float help or hu... |
| MB0739 | ripple200:R06-09 | market-wide | natural | no | - | A company funds a large capex with debt. Trace it to the D/E, then to the rating, then to the cost of debt, then to the capex the company can still afford. Where is the b... |
| MB0740 | ripple200:R06-10 | market-wide | natural | partial | - | A stock doubles on a narrative and then raises guidance. Trace it to the fund flow, then to the delivery volume, then to the promoter's stake, then to the next guidance. ... |
| MB0741 | ripple200:R06-11 | market-wide | natural | partial | - | A stock is removed from an index. Trace it to the passive selling, then to the delivery percentage, then to the price recovery. How long does the flow effect last? |
| MB0742 | ripple200:R06-12 | market-wide | natural | partial | - | A stock enters the F&O ban. Trace it to the volatility, then to the delivery percentage, then to the stock's behaviour after the ban lifts. What is measurable and what is... |
| MB0743 | ripple200:R06-13 | market-wide | natural | partial | - | Insiders buy before a result. Trace it to the delivery spike, then to the price move, then to the result itself. Is the insider trade evidence of the result or of the pri... |
| MB0744 | ripple200:R06-14 | market-wide | natural | partial | - | Promoters raise their stake through creeping acquisition. Trace it to the free float, then to the delivery percentage, then to the price impact of a future sale. Which li... |
| MB0745 | ripple200:R06-15 | market-wide | natural | no | - | A promoter pledge is invoked. Trace it to the forced sale, then to the price, then to the company's borrowing cost. What does the disclosure actually contain? |
| MB0746 | ripple200:R06-16 | market-wide | natural | partial | - | A company announces a rights issue at a discount. Trace it to the share count, then to the EPS, then to the ex-rights price. Which number does a naive EPS series get wron... |
| MB0747 | ripple200:R06-17 | market-wide | natural | no | - | A conglomerate demerges a division. Trace it to the sum-of-the-parts, then to the index treatment, then to the two entities' borrowing costs. Who gets a better rating aft... |
| MB0748 | ripple200:R06-18 | market-wide | natural | partial | - | A company issues warrants to promoters at a premium to the market. Trace it to the dilution, then to the promoter's stake, then to the market's read of the price. What is... |
| MB0749 | ripple200:R06-19 | market-wide | natural | partial | - | A company announces a tender buyback at a premium. Trace it to the acceptance ratio, then to the EPS, then to the promoter's stake. What does the premium tell you? |
| MB0750 | ripple200:R06-20 | market-wide | natural | partial | - | The discount rate rises and a company's project IRR no longer clears it. Trace it to the capex decision, then to the order book, then to the capacity that is never built.... |
| MB0926 | reddit200:RD-N-021 | stock | natural | partial | - | Tata Motors: JLR margin guidance has moved every year. What was promised, what was delivered, and what is the current gap? |
| MB0927 | reddit200:RD-N-022 | stock | natural | partial | - | Dixon: the margin guidance has been repeatedly cut. Which call first lowered it, and what did the market do after? |
| MB0928 | reddit200:RD-N-023 | stock | natural | partial | - | IREDA: loan-growth guidance versus actual book growth. Has the company consistently beaten its own number? |
| MB0929 | reddit200:RD-N-024 | stock | natural | partial | - | Vedanta: management has promised deleveraging several times. What was the net-debt target each time, and where is net debt now? |
| MB0930 | reddit200:RD-N-025 | stock | natural | partial | - | Paytm: management gave a profitability timeline. Did the company hit it, and what did it cost in revenue growth? |
| MB0018 | shivam30:Q23 | industry | terse | - | primary 6 | Coal gasification drafts vs the earlier scheme |
| MB0027 | shivam30:QA7 | stock | natural | - | primary 1 | What did ISIN INE864I01014 say about its fuel-cell capacity expansion due to complete by the end of this year, per its transcript of 6 August 2026? |
| MB0030 | shivam30:QA10 | stock | natural | - | primary 1 | Per the transcript of 18 September 2026 of 540678 / COCHINSHIP: what did it say about the MOU with HD KSOE, and how will EBITDA margins progress from electric tug boats, ... |
| MB0201 | variations300:Q23-V1 | industry | natural | yes | primary 6 | For the Scheme for promotion of coal/lignite gasification (2026-02-01), how does it differ from the earlier coal-gasification scheme, and which industries does it hit? |
| MB0202 | variations300:Q23-V2 | industry | natural | partial | primary 6 | For the National Green Hydrogen Mission progress (2025-12-16), how does it differ from the coal-gasification scheme, and which industries does it hit? |
| MB0203 | variations300:Q23-V3 | industry | natural | yes | primary 6 | Using the document reference Union_Budget: Union Budget FY2026-27 - Budget at a Glance (2026-02-01), how does the coal-gasification policy differ from the earlier scheme,... |
| MB0204 | variations300:Q23-V4 | industry | terse | yes | primary 6 | coal gasification policy draft vs earlier scheme |
| MB0205 | variations300:Q23-V5 | industry | Hinglish | yes | primary 6 | Coal gasification ke naye draft aur pehle wale scheme mein kya farq hai? Kaunse ministries aur industries affected hain, aur PIB/Budget se evidence do. |
| MB0206 | variations300:Q23-V6 | industry | natural | yes | primary 6 | How do India's coal-gasification policy drafts differ from the earlier scheme, and which industries do they hit? |
| MB0207 | variations300:Q23-V7 | industry | natural | yes | primary 6 | For all listed companies in coal, how does the coal-gasification policy differ from the earlier scheme, and which industries does it hit? |
| MB0208 | variations300:Q23-V8 | index | natural | partial | primary 6 | For the NIFTY TOTAL MARKET constituents, what does the coal-gasification policy change mean for the members, and which ones are named in policy_events? |
| MB0209 | variations300:Q23-V9 | industry | point-in-time | no | primary 6 | As of 31 December 2025, how did the coal-gasification drafts differ from the earlier scheme? Use only documents known by that date. |
| MB0210 | variations300:Q23-V10 | industry | natural | no | primary 6 | How does the coal-gasification policy change affect coal-price-sensitive companies? If the coal price series ends before 2024-2026, answer NOT IN DATA. |
| MB0291 | variations300:QA7-V1 | stock | natural | yes | primary 1 | What did Azad Engineering (NSE: AZAD) say about its capacity expansion, and the completion timeline, on its 14 August 2026 earnings call? |
| MB0292 | variations300:QA7-V2 | stock | natural | partial | primary 1 | What did ABB India (NSE: ABB) say about its capacity expansion, and the completion timeline, on its 16 May 2025 earnings call? |
| MB0293 | variations300:QA7-V3 | stock | natural | yes | primary 1 | What did NSE: IDFCBANK (now IDFCFIRSTB) say about its capacity expansion, and the completion timeline, on its 31 July 2026 earnings call? |
| MB0294 | variations300:QA7-V4 | stock | terse | yes | primary 1 | ENTERO capacity timeline call 2026-08-17 |
| MB0295 | variations300:QA7-V5 | stock | Hinglish | yes | primary 1 | Max Healthcare Institute (NSE: MAXHEALTH) ne apni 20 August 2026 wali call mein capacity expansion ka kya timeline bataya? Completion date aur capex ke saath quote do. |
| MB0296 | variations300:QA7-V6 | stock | natural | yes | primary 1 | What did Affle 3i (NSE: AFFLE) say about its capacity expansion, and the completion timeline, on its 18 May 2026 earnings call? |
| MB0297 | variations300:QA7-V7 | industry | natural | yes | primary 1 | For all listed companies in Electrical Equipment, what capacity-expansion timelines did management give on their latest earnings calls? |
| MB0298 | variations300:QA7-V8 | index | natural | no | primary 1 | For the NIFTY MICROCAP 250 constituents, what capacity-expansion timelines did management give on their latest earnings calls? |
| MB0299 | variations300:QA7-V9 | stock | point-in-time | yes | primary 1 | As of 31 July 2026, what had Arvind SmartSpaces (NSE: ARVSMART) said about its capacity expansion timeline by that date? |
| MB0300 | variations300:QA7-V10 | stock | natural | no | primary 1 | What did 21st Century Management Services (NSE: 21STCENMGM) say about its capacity expansion timeline on 6 August 2025? If the transcript exists but is not chunked, answe... |
| MB0321 | variations300:QA10-V1 | stock | natural | yes | primary 1 | Per Jupiter Wagons (NSE: JWL)'s 21 August 2026 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? |
| MB0322 | variations300:QA10-V2 | stock | natural | yes | primary 1 | Per Ashok Leyland (NSE: ASHOKLEY)'s 21 August 2026 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? |
| MB0323 | variations300:QA10-V3 | stock | natural | yes | primary 1 | Per NSE: CENTURYTEX (now ABREL)'s 20 August 2026 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? |
| MB0324 | variations300:QA10-V4 | stock | terse | yes | primary 1 | HINDPETRO mou margin path call 2026-07-29 |
| MB0325 | variations300:QA10-V5 | stock | Hinglish | partial | primary 1 | L&T Technology Services (NSE: LTTS) ki 24 October 2025 wali call mein MOU partner kaun hai, aur EBITDA margin ka path kya bataya gaya? Plan aur numbers quote karo. |
| MB0326 | variations300:QA10-V6 | stock | natural | partial | primary 1 | Per Raymond Lifestyle (NSE: RAYMONDLSL)'s 4 November 2025 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? |
| MB0327 | variations300:QA10-V7 | industry | natural | no | primary 1 | For all listed companies in Industrial Manufacturing, what MOUs or partnerships and margin paths did management disclose on their latest calls? |
| MB0328 | variations300:QA10-V8 | index | natural | partial | primary 1 | For the NIFTY MIDCAP 150 constituents, what MOUs or partnerships and margin paths did management disclose on their latest calls? |
| MB0329 | variations300:QA10-V9 | stock | point-in-time | yes | primary 1 | As of 30 September 2026, what had Ecos (India) Mobility & Hospitality (NSE: ECOSMOBLTY) disclosed about its MOU and margin path? |
| MB0330 | variations300:QA10-V10 | stock | natural | no | primary 1 | What did 21st Century Management Services (NSE: 21STCENMGM) say about its MOU and EBITDA margin path on 1 August 2026? If the call is not held for that date, answer NOT I... |
| MB0556 | open300:A16-01 | market-wide | natural | partial | primary 1 | Which companies raised a QIP in FY26, and did the actual use of proceeds match the stated objects? |
| MB0557 | open300:A16-02 | stock | natural | partial | primary 1 | Is Polycab's capex funded by debt or internal accruals, and how does the disclosure show it? |
| MB0558 | open300:A16-03 | stock | natural | yes | primary 1 | Trent did a 1:2 bonus with ex-date 4 June 2026. What does that do to the EPS series, and how should a price chart treat it? |
| MB0559 | open300:A16-04 | stock | natural | partial | primary 1 | Suzlon has been cutting debt while spending on capacity. Which came first in the cash flow, and is the deleveraging real? |
| MB0560 | open300:A16-05 | stock | natural | partial | primary 1 | RVNL and NBCC are asset-light but cash-hungry. How do they fund working capital, and what does that do to return on capital? |
| MB0561 | open300:A16-06 | market-wide | natural | partial | primary 1 | Which companies put money into a subsidiary or JV last year, and was it disclosed as a related-party transaction? |
| MB0562 | open300:A16-07 | stock | natural | partial | primary 1 | ITC and Colgate pay out most of their earnings. Is the payout covered by free cash flow, and what is left for growth? |
| MB0563 | open300:A16-08 | stock | terse | partial | primary 1 | buyback vs dividend choices FY26 |
| MB0564 | open300:A16-09 | stock | natural | partial | primary 1 | UltraTech bought India Cements and Kesoram. How was the acquisition funded, and what did it do to net debt/EBITDA? |
| MB0565 | open300:A16-10 | stock | natural | partial | primary 1 | Cochin Shipyard's ISRF JV needs capital. What is the committed amount, and who funds it? |
| MB0566 | open300:A16-11 | stock | Hinglish | partial | primary 1 | Tata Power ka renewable capex debt se fund ho raha hai ya internal accruals se? (Hinglish) |
| MB0567 | open300:A16-12 | stock | natural | partial | primary 1 | JSW Steel's acquisitions added debt. Did the leverage ratio stay within the stated ceiling, and what did management say? |
| MB0568 | open300:A16-13 | stock | natural | partial | primary 1 | Angel One earns float income on client funds. How does it deploy that float, and what is the risk if rates fall? |
| MB0569 | open300:A16-14 | stock | natural | partial | primary 1 | A company issues fresh equity to fund capex. How does that change ROCE and EPS, and what should an investor check first? |
| MB0570 | open300:A16-15 | market-wide | Hinglish | partial | primary 1 | Which company converted its capex into the best incremental ROCE over three years? Kaun sa company? (Hinglish) |

### Family 4 - Screen (21 primary cases; 26 cross-referenced)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0012 | shivam30:Q17 | industry | terse | - | 8 | HFC securitisation leader, QoQ/YoY with NPA guard |
| MB0141 | variations300:Q17-V1 | industry | natural | yes | 8 | Is Can Fin Homes (NSE: CANFINHOME) the leader in securitised disbursement among listed HFCs for Q1FY27, with net NPA up no more than 2 pp? Show the comparison. |
| MB0142 | variations300:Q17-V2 | industry | natural | partial | 8 | Among large-cap HFCs, who leads securitised disbursement for Q1FY27 with net NPA up no more than 2 pp? |
| MB0143 | variations300:Q17-V3 | industry | natural | partial | 8 | For NSE: IBULHSGFIN (now SAMMAANCAP), is it the leader in securitised disbursement among listed HFCs for Q1FY27, with net NPA up no more than 2 pp? Show the naming histor... |
| MB0144 | variations300:Q17-V4 | industry | terse | partial | 8 | hfc securitisation leader q1fy27 net npa |
| MB0145 | variations300:Q17-V5 | industry | Hinglish | partial | 8 | Listed HFCs mein securitised disbursement ka leader kaun hai Q1FY27 mein? QoQ aur YoY winner batao, lekin net NPA 2 percentage point se zyada na badhe. |
| MB0146 | variations300:Q17-V6 | industry | natural | yes | 8 | Which listed HFC is the leader in securitised disbursement for January-March 2026 (Q4FY26), QoQ and YoY, with net NPA rising no more than 2 pp? |
| MB0147 | variations300:Q17-V7 | industry | natural | yes | 8 | For all listed companies in Housing Finance, which listed financial company is the securitisation leader for Q1FY27 with the net-NPA guard, and what is the evidence? |
| MB0148 | variations300:Q17-V8 | index | natural | partial | 8 | For the NIFTY HOUSING FINANCE constituents, rank the financial companies on securitised disbursement for Q1FY27, with the net-NPA guard. |
| MB0149 | variations300:Q17-V9 | industry | point-in-time | yes | 8 | As of 30 June 2026, which HFC looked like the securitisation leader for Q1FY27, and on what evidence? |
| MB0150 | variations300:Q17-V10 | industry | natural | no | 8 | Which listed HFC led securitised disbursement in Q1FY27? If the securitisation figure is not in any structured store for GIC Housing Finance (NSE: GICHSGFIN), answer NOT ... |
| MB0871 | reddit200:RD-I-041 | market-wide | natural | partial | - | HDFC Bank fell through a month of heavy FII selling. How much of the fall lines up with market-wide FII outflow, and how much is stock-specific? |
| MB0872 | reddit200:RD-I-042 | market-wide | natural | yes | - | Reliance: did DII buying offset FII selling last quarter, and what did the shareholding pattern show? |
| MB0873 | reddit200:RD-I-043 | stock | natural | partial | - | SBI: is the recent DII accumulation visible in the shareholding pattern, or only in the daily flow prints? |
| MB0874 | reddit200:RD-I-044 | stock | natural | partial | - | Larsen & Toubro: did the order inflow announcements or the institutional flows better explain the last two quarters of returns? |
| MB0875 | reddit200:RD-I-045 | stock | natural | partial | - | ICICI Bank versus HDFC Bank: which one saw the bigger FII ownership change last year, and did the price gap follow it? |
| MB0901 | reddit200:RD-I-071 | stock | natural | partial | - | When Eternal entered the Nifty 50, how much passive buying did that imply, and did the stock move before or after the effective date? |
| MB0902 | reddit200:RD-I-072 | stock | natural | partial | - | Jio Financial was added to the Nifty 50 soon after listing. Did the index flow arrive before the stock's first big move? |
| MB0903 | reddit200:RD-I-073 | stock | natural | partial | - | HAL's weight in the Nifty 50 has changed with the stock. How much of the trading volume on rebalance days is index-driven? |
| MB0904 | reddit200:RD-I-074 | stock | natural | partial | - | If DMart drops out of the Nifty 50, what would the forced selling be, and how has the stock behaved around past exclusion scares? |
| MB0905 | reddit200:RD-I-075 | stock | natural | no | - | Trent versus the Nifty consumption index: did the stock's weight increase come from price or from index reconstitution? |
| MB0011 | shivam30:Q16 | theme | terse | - | primary 6 | Why gold stocks fell Jun–Jul 2026 |
| MB0131 | variations300:Q16-V1 | theme | natural | partial | primary 6 | Why did gold-jewellery stocks move in June-July 2026? Give the macro move, the PIB or RBI evidence, and what the companies themselves said. |
| MB0132 | variations300:Q16-V2 | theme | natural | partial | primary 6 | Why did oil and gas stocks move in April-May 2026? Give the macro move, the PIB or RBI evidence, and what the companies themselves said. |
| MB0133 | variations300:Q16-V3 | theme | natural | partial | primary 6 | Why did the companies in the gold-jewellery theme move in Jun-Jul 2026? The event is referenced by the gold price series (USD/oz); name the PIB release or macro series yo... |
| MB0134 | variations300:Q16-V4 | theme | terse | partial | primary 6 | gold-jewellery stocks move Jun-Jul 2026 why |
| MB0135 | variations300:Q16-V5 | theme | Hinglish | partial | primary 6 | Gold-Jewellery stocks Jun-Jul 2026 mein kya hua aur kyun? PIB, RBI ya company documents se evidence do, aur batao kaun sabse zyada affected hua. |
| MB0136 | variations300:Q16-V6 | theme | natural | partial | primary 6 | What caused the gold-jewellery move in June-July 2026 (FY27 first half)? Use the commodity series, PIB and company evidence from that window only. |
| MB0137 | variations300:Q16-V7 | industry | natural | partial | primary 6 | For all listed companies in gold-jewellery, what moved in Jun-Jul 2026, and what do the macro, PIB and company evidence say caused it? |
| MB0138 | variations300:Q16-V8 | theme | natural | partial | primary 6 | For the gold-jewellery theme members, how did the gold price move in Jun-Jul 2026 hit the members differently, and which one was worst? |
| MB0139 | variations300:Q16-V9 | theme | point-in-time | yes | primary 6 | By 31 July 2026, why had gold-jewellery stocks moved? Use only evidence known by that date. |
| MB0140 | variations300:Q16-V10 | theme | natural | no | primary 6 | Why did PNGS Reva Diamond Jewellery (NSE: PNGSREVA) move in 7-19 Oct 2026? If the macro series for that window is missing, answer NOT IN DATA and name the series. |
| MB0571 | open300:A17-01 | market-cap bucket | natural | yes | primary 2 | Which large caps saw the highest delivery percentage on 4 June 2024, and what does that say about who was selling? |
| MB0572 | open300:A17-02 | market-wide | natural | yes | primary 2 | Which stocks traded above 50% delivery on 24 September 2026, and were they the biggest movers? |
| MB0573 | open300:A17-03 | market-wide | terse | yes | primary 2 | delivery-spike ratio leaders this week |
| MB0574 | open300:A17-04 | stock | natural | yes | primary 2 | On 23 October 2026 Bonfiglioli saw several bulk deals. Who bought, at what price, and was it above or below the close? |
| MB0575 | open300:A17-05 | market-wide | natural | yes | primary 2 | Which side was bigger on 23 October 2026, FII or DII, and what does the ratio say about the marginal buyer? |
| MB0576 | open300:A17-06 | market-wide | natural | yes | primary 2 | Is there a same-day relationship between FII net flow and the Nifty move in 2026? Show the worst divergence day. |
| MB0577 | open300:A17-07 | stock | natural | no | primary 2 | What was the promoter holding in Titagarh last quarter? terse: TITAGARH promoter % |
| MB0578 | open300:A17-08 | market-cap bucket | natural | no | primary 2 | Which small caps saw the biggest mutual-fund accumulation last quarter? terse: MF buying small caps |
| MB0579 | open300:A17-09 | sector | natural | no | primary 2 | Which sectors did FIIs sell most in September 2026? terse: FII sector selling Sep 2026 |
| MB0580 | open300:A17-10 | index | Hinglish | partial | primary 2 | Index inclusion se kisi stock mein move aaya kya? Ek case batao. (Hinglish) |
| MB0581 | open300:A17-11 | market-wide | natural | partial | primary 2 | Which stocks had the highest turnover on 4 June 2024, and was it concentrated in PSU financials? |
| MB0582 | open300:A17-12 | market-wide | natural | yes | primary 2 | How many sessions in 2026 had FIIs selling and DIIs buying, and what did the Nifty do on those days on average? |
| MB0583 | open300:A17-13 | stock | natural | partial | primary 2 | Delivery percentage around results: does a high-delivery reaction day predict the next week? Test it on KEI and Titagarh. |
| MB0584 | open300:A17-14 | market-cap bucket | natural | yes | primary 2 | Which large caps saw delivery percentage fall the most in the week after 4 June 2024, and what does that signal? |
| MB0585 | open300:A17-15 | market-wide | Hinglish | yes | primary 2 | September 2026 mein FIIs ne kitna becha aur DIIs ne kitna kharida? (Hinglish) |

### Family 5 - Cross-document (0 primary cases; 11 cross-referenced)

No case has this as its primary family; the 11 cases below cross-reference it.

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0029 | shivam30:QA9 | stock | point-in-time | - | primary 1 | What did NSE: SAILIFE say about its newly commissioned facilities, as of the latest data? |
| MB0311 | variations300:QA9-V1 | stock | point-in-time | yes | primary 1 | What did Onesource Specialty Pharma (NSE: ONESOURCE) say about its newly commissioned facilities, as of the latest data, and in which document type? |
| MB0312 | variations300:QA9-V2 | stock | point-in-time | yes | primary 1 | What did Cipla (NSE: CIPLA) say about its newly commissioned facilities, as of the latest data, and in which document type? |
| MB0313 | variations300:QA9-V3 | stock | point-in-time | yes | primary 1 | What did NSE: MFL (now EPIGRAL) say about its newly commissioned facilities, as of the latest data, and in which document type? |
| MB0314 | variations300:QA9-V4 | stock | terse | yes | primary 1 | RAILTEL newly commissioned facilities latest |
| MB0315 | variations300:QA9-V5 | stock | Hinglish | yes | primary 1 | R K Swamy (NSE: RKSWAMY) ne apni nayi commissioned facilities ke baare mein sabse latest kya kaha hai? Deck, concall aur annual report teeno check karke source do. |
| MB0316 | variations300:QA9-V6 | stock | point-in-time | yes | primary 1 | What did Enviro Infra Engineers (NSE: EIEL) say about its newly commissioned facilities, as of the latest data, and in which document type? |
| MB0317 | variations300:QA9-V7 | industry | natural | yes | primary 1 | For all listed companies in Pharmaceuticals & Biotechnology, what have the companies said about newly commissioned facilities across decks, calls and annual reports? |
| MB0318 | variations300:QA9-V8 | index | natural | partial | primary 1 | For the NIFTY500 SHARIAH constituents, what have the companies said about newly commissioned facilities across decks, calls and annual reports? |
| MB0319 | variations300:QA9-V9 | stock | point-in-time | yes | primary 1 | As of 30 June 2026, what had Kuantum Papers (NSE: KUANTUM) said about its newly commissioned facilities, using only documents known by that date? |
| MB0320 | variations300:QA9-V10 | stock | natural | no | primary 1 | What has 21st Century Management Services (NSE: 21STCENMGM) said about its newly commissioned facilities? If no document after since Jan 2026 is held, answer NOT IN DATA ... |

### Family 6 - Policy -> companies (88 primary cases)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0011 | shivam30:Q16 | theme | terse | - | 4 | Why gold stocks fell Jun–Jul 2026 |
| MB0013 | shivam30:Q18 | industry | terse | - | 9, 11 | OMCs: record Q4 then loss Q1; earliest PIT signal |
| MB0015 | shivam30:Q20 | stock | terse | - | 9 | Garware: tariff hit, then negative correlation |
| MB0016 | shivam30:Q21 | policy | terse | - | 7 | RBI repo hike causes; PIB or RBI only |
| MB0017 | shivam30:Q22 | theme | terse | - | 7 | Second-hand electronics boom CY2026: who benefits |
| MB0018 | shivam30:Q23 | industry | terse | - | 3 | Coal gasification drafts vs the earlier scheme |
| MB0019 | shivam30:Q24 | stock | terse | - | 8 | PARAGMILK on El Niño; dairy peers |
| MB0020 | shivam30:Q25 | policy | terse | - | 7 | Data-centre tax holiday outcome so far |
| MB0131 | variations300:Q16-V1 | theme | natural | partial | 4 | Why did gold-jewellery stocks move in June-July 2026? Give the macro move, the PIB or RBI evidence, and what the companies themselves said. |
| MB0132 | variations300:Q16-V2 | theme | natural | partial | 4 | Why did oil and gas stocks move in April-May 2026? Give the macro move, the PIB or RBI evidence, and what the companies themselves said. |
| MB0133 | variations300:Q16-V3 | theme | natural | partial | 4 | Why did the companies in the gold-jewellery theme move in Jun-Jul 2026? The event is referenced by the gold price series (USD/oz); name the PIB release or macro series yo... |
| MB0134 | variations300:Q16-V4 | theme | terse | partial | 4 | gold-jewellery stocks move Jun-Jul 2026 why |
| MB0135 | variations300:Q16-V5 | theme | Hinglish | partial | 4 | Gold-Jewellery stocks Jun-Jul 2026 mein kya hua aur kyun? PIB, RBI ya company documents se evidence do, aur batao kaun sabse zyada affected hua. |
| MB0136 | variations300:Q16-V6 | theme | natural | partial | 4 | What caused the gold-jewellery move in June-July 2026 (FY27 first half)? Use the commodity series, PIB and company evidence from that window only. |
| MB0137 | variations300:Q16-V7 | industry | natural | partial | 4 | For all listed companies in gold-jewellery, what moved in Jun-Jul 2026, and what do the macro, PIB and company evidence say caused it? |
| MB0138 | variations300:Q16-V8 | theme | natural | partial | 4 | For the gold-jewellery theme members, how did the gold price move in Jun-Jul 2026 hit the members differently, and which one was worst? |
| MB0139 | variations300:Q16-V9 | theme | point-in-time | yes | 4 | By 31 July 2026, why had gold-jewellery stocks moved? Use only evidence known by that date. |
| MB0140 | variations300:Q16-V10 | theme | natural | no | 4 | Why did PNGS Reva Diamond Jewellery (NSE: PNGSREVA) move in 7-19 Oct 2026? If the macro series for that window is missing, answer NOT IN DATA and name the series. |
| MB0151 | variations300:Q18-V1 | industry | point-in-time | yes | 9, 11 | Sugar Q4FY26-to-Q1FY27 profit swing — which companies in Sugar swung from profit in Q4FY26 to a loss in Q1FY27, and when was that first visible point-in-time? |
| MB0152 | variations300:Q18-V2 | industry | point-in-time | yes | 9, 11 | Media & Entertainment Q4FY26-to-Q1FY27 profit swing — which companies in Media & Entertainment swung from profit in Q4FY26 to a loss in Q1FY27, and when was that first vi... |
| MB0153 | variations300:Q18-V3 | industry | point-in-time | yes | 9, 11 | For BSE scrip code 532543, when did the Q4FY26-to-Q1FY27 profit swing become visible point-in-time, and from which filing? |
| MB0154 | variations300:Q18-V4 | industry | terse | yes | 9, 11 | omc q4fy26 profit q1fy27 loss earliest pit |
| MB0155 | variations300:Q18-V5 | industry | Hinglish | yes | 9, 11 | OMCs ne Q4FY26 mein record profit aur Q1FY27 mein bada loss kaise kiya? Sabse pehle kaunsa data point point-in-time visible tha, date ke saath batao. |
| MB0156 | variations300:Q18-V6 | industry | natural | yes | 9, 11 | For the January-March 2026 and April-June 2026 quarters, which OMCs went from record profit to a loss, and when did that first become visible? |
| MB0157 | variations300:Q18-V7 | industry | point-in-time | yes | 9, 11 | For all listed companies in Petroleum Products, which companies swung from profit in Q4FY26 to a loss in Q1FY27, and what was the earliest point-in-time evidence? |
| MB0158 | variations300:Q18-V8 | index | point-in-time | partial | 9, 11 | For the NIFTY OIL & GAS constituents, which companies swung from profit in Q4FY26 to a loss in Q1FY27, and what was the earliest point-in-time evidence? |
| MB0159 | variations300:Q18-V9 | industry | point-in-time | yes | 9, 11 | As of 30 June 2026, what did the data already show about the OMC profit swing from Q4FY26 to Q1FY27? |
| MB0160 | variations300:Q18-V10 | industry | natural | no | 9, 11 | Using the coal price series, when did the OMC Q4FY26-to-Q1FY27 trend first become visible? If the series ends before that window, answer NOT IN DATA. |
| MB0171 | variations300:Q20-V1 | stock | natural | partial | 9 | How sensitive was KRN Heat Exchanger and Refrigeration (NSE: KRN) to Customs tariff rationalization - remove 7 tariff rates (1 February 2025) in the 60 days after it, and... |
| MB0172 | variations300:Q20-V2 | stock | natural | partial | 9 | How sensitive was APL Apollo Tubes (NSE: APLAPOLLO) to Customs tariff rationalization - remove 7 tariff rates (1 February 2025) in the 60 days after it, and did its 60-da... |
| MB0173 | variations300:Q20-V3 | stock | natural | partial | 9 | How sensitive was NSE: DHARAMSI (now DMCC) to Customs tariff rationalization - remove 7 tariff rates (1 February 2025) in the 60 days after it, and did its 60-day return ... |
| MB0174 | variations300:Q20-V4 | stock | terse | partial | 9 | PAKKA tariff sensitivity rolling correlation |
| MB0175 | variations300:Q20-V5 | stock | Hinglish | partial | 9 | Eco Recycling (NSE: ECORECO) par Customs tariff rationalization - remove 7 tariff rates (1 February 2025) ka kitna asar pada, aur agle 12 mahine mein tariff news se corre... |
| MB0176 | variations300:Q20-V6 | stock | natural | partial | 9 | How did JSW Energy (NSE: JSWENERGY)'s rolling correlation with Customs tariff rationalization - remove 7 tariff rates (1 February 2025) change over the 12 months after Ma... |
| MB0177 | variations300:Q20-V7 | industry | natural | partial | 9 | For all listed companies in Industrial Products, how sensitive were the members to Customs tariff rationalization - remove 7 tariff rates (1 February 2025), and did the 6... |
| MB0178 | variations300:Q20-V8 | index | natural | partial | 9 | For the NIFTY MIDSMALLCAP400 MOMENTUM QUALITY 100 constituents, how sensitive were the members to Customs tariff rationalization - remove 7 tariff rates (1 February 2025)... |
| MB0179 | variations300:Q20-V9 | stock | point-in-time | partial | 9 | As of 31 March 2026, what did the rolling correlation of National Aluminium Company (NSE: NATIONALUM) with Customs tariff rationalization - remove 7 tariff rates (1 Febru... |
| MB0180 | variations300:Q20-V10 | stock | natural | no | 9 | For 20 Microns (NSE: 20MICRONS), did the tariff impact and any later negative correlation survive its corporate action on adjusted prices? If not, answer NOT IN DATA. |
| MB0181 | variations300:Q21-V1 | policy | natural | yes | 7 | For the Repo rate hiked 25 bps to 5.50% (2026-10-07), what were the causes, and which source published it first? |
| MB0182 | variations300:Q21-V2 | policy | natural | partial | 7 | For the Devolution of states' share in taxes increased (2026-02-01), what were the causes, and which source published it first? |
| MB0183 | variations300:Q21-V3 | policy | natural | yes | 7 | For the RBI Governor's Statement of 7 October 2026 (2026-10-07), what were the causes, and which source published it first? |
| MB0184 | variations300:Q21-V4 | policy | terse | yes | 7 | rbi repo hike 2026-10-07 causes pib or rbi |
| MB0185 | variations300:Q21-V5 | policy | Hinglish | yes | 7 | RBI ne 2026-10-07 ko repo rate kyun badhaya? Causes batao, aur ye news PIB ne publish kiya ya sirf RBI ne? Provenance ke saath. |
| MB0186 | variations300:Q21-V6 | policy | natural | yes | 7 | For the Repo rate hiked 25 bps to 5.50% of 2026-10-07, what were the causes, and was it published by PIB or only by the RBI? |
| MB0187 | variations300:Q21-V7 | industry | natural | yes | 7 | For all listed companies in banking, how does the 2026-10-07 RBI action transmit, and which sectors are named in the policy document? |
| MB0188 | variations300:Q21-V8 | index | natural | partial | 7 | For the NIFTY TOTAL MARKET constituents, how did the members react to the RBI action of 2026-10-07, and what does the PIB/RBI record show? |
| MB0189 | variations300:Q21-V9 | policy | point-in-time | no | 7 | As of 6 October 2026, what did the record show about the causes of the RBI action of 2026-10-07, and who published it first? |
| MB0190 | variations300:Q21-V10 | policy | natural | no | 7 | What were the causes of the RBI action of 2026-10-07, and was it published by PIB or only by RBI? If the policy document is not held, answer NOT IN DATA. |
| MB0191 | variations300:Q22-V1 | theme | natural | partial | 7 | For the Electronics Component Manufacturing Scheme approvals (2025-11-17), why does it matter for demand, and which sectors and listed companies does it touch? |
| MB0192 | variations300:Q22-V2 | theme | natural | partial | 7 | For the R&D in IT/Electronics/CCBT (2026-02-01), why does it matter for demand, and which sectors and listed companies does it touch? |
| MB0193 | variations300:Q22-V3 | theme | natural | partial | 7 | Using the document reference PIB PRID 2190872 on 2025-11-17, what does the policy record say about electronics demand in CY2026, and which companies does it touch? |
| MB0194 | variations300:Q22-V4 | theme | terse | partial | 7 | second hand electronics boom cy2026 who benefits |
| MB0195 | variations300:Q22-V5 | theme | Hinglish | partial | 7 | CY2026 mein second-hand aur refurbished electronics/laptops ki demand kyun badhi? Kaun listed companies ko fayda hoga, aur ye structural hai ya cyclical? Data gap bhi bat... |
| MB0196 | variations300:Q22-V6 | theme | natural | partial | 7 | Why did second-hand electronics and laptop sales rise in CY2026? Who benefits, and is the trend structural or cyclical? State any part that is NOT IN DATA. |
| MB0197 | variations300:Q22-V7 | industry | natural | partial | 7 | For all listed companies in electronics, what does the policy record say about demand in CY2026, and which companies does it touch? |
| MB0198 | variations300:Q22-V8 | index | natural | partial | 7 | For the NIFTY WAVES constituents, what does the policy and company evidence say about demand in CY2026, and who benefits? |
| MB0199 | variations300:Q22-V9 | theme | point-in-time | yes | 7 | As of 30 June 2026, what was known about the as of 30 June 2026 electronics demand trend, and which companies were named? |
| MB0200 | variations300:Q22-V10 | theme | natural | no | 7 | What do our stores say about refurbished/second-hand electronics sales in CY2026, and who benefits? If no sales series exists, answer NOT IN DATA and say which store is m... |
| MB0201 | variations300:Q23-V1 | industry | natural | yes | 3 | For the Scheme for promotion of coal/lignite gasification (2026-02-01), how does it differ from the earlier coal-gasification scheme, and which industries does it hit? |
| MB0202 | variations300:Q23-V2 | industry | natural | partial | 3 | For the National Green Hydrogen Mission progress (2025-12-16), how does it differ from the coal-gasification scheme, and which industries does it hit? |
| MB0203 | variations300:Q23-V3 | industry | natural | yes | 3 | Using the document reference Union_Budget: Union Budget FY2026-27 - Budget at a Glance (2026-02-01), how does the coal-gasification policy differ from the earlier scheme,... |
| MB0204 | variations300:Q23-V4 | industry | terse | yes | 3 | coal gasification policy draft vs earlier scheme |
| MB0205 | variations300:Q23-V5 | industry | Hinglish | yes | 3 | Coal gasification ke naye draft aur pehle wale scheme mein kya farq hai? Kaunse ministries aur industries affected hain, aur PIB/Budget se evidence do. |
| MB0206 | variations300:Q23-V6 | industry | natural | yes | 3 | How do India's coal-gasification policy drafts differ from the earlier scheme, and which industries do they hit? |
| MB0207 | variations300:Q23-V7 | industry | natural | yes | 3 | For all listed companies in coal, how does the coal-gasification policy differ from the earlier scheme, and which industries does it hit? |
| MB0208 | variations300:Q23-V8 | index | natural | partial | 3 | For the NIFTY TOTAL MARKET constituents, what does the coal-gasification policy change mean for the members, and which ones are named in policy_events? |
| MB0209 | variations300:Q23-V9 | industry | point-in-time | no | 3 | As of 31 December 2025, how did the coal-gasification drafts differ from the earlier scheme? Use only documents known by that date. |
| MB0210 | variations300:Q23-V10 | industry | natural | no | 3 | How does the coal-gasification policy change affect coal-price-sensitive companies? If the coal price series ends before 2024-2026, answer NOT IN DATA. |
| MB0211 | variations300:Q24-V1 | stock | natural | yes | 8 | What did Dodla Dairy (NSE: DODLA) say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? |
| MB0212 | variations300:Q24-V2 | stock | natural | yes | 8 | What did Milky Mist Dairy Food (NSE: MILKYMIST) say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? |
| MB0213 | variations300:Q24-V3 | stock | natural | yes | 8 | What did BSE scrip code 531531 say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? |
| MB0214 | variations300:Q24-V4 | stock | terse | yes | 8 | PARAGMILK el nino dairy margins |
| MB0215 | variations300:Q24-V5 | stock | Hinglish | yes | 8 | Heritage Foods (NSE: HERITGFOOD) ne El Nino 2026 ke asar par calls mein kya kaha? Dairy peers ka bhi comparison do, aur management ne kaise handle karne ko kaha. |
| MB0216 | variations300:Q24-V6 | stock | natural | no | 8 | What did Kwality Wall's (India) (NSE: KWIL) say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? |
| MB0217 | variations300:Q24-V7 | industry | natural | yes | 8 | For all listed companies in Fast Moving Consumer Goods, what did managements say about El Nino 2026, and how are they handling it? |
| MB0218 | variations300:Q24-V8 | index | natural | no | 8 | For the NIFTY SMALLCAP 100 constituents, how exposed are the members to El Nino 2026, and what did they say about handling it? |
| MB0219 | variations300:Q24-V9 | stock | point-in-time | no | 8 | As of 30 June 2026, what had Milkfood (NSE: MLKFOOD) said about El Nino 2026 and its dairy margins? |
| MB0220 | variations300:Q24-V10 | stock | natural | no | 8 | What did Knack Packaging (NSE: KNACK) say about El Nino 2026 on its calls? If no transcript is held for it, answer NOT IN DATA and name the store checked. |
| MB0221 | variations300:Q25-V1 | policy | natural | partial | 7 | For the startup tax holiday extension (2025-02-01), how has it played out so far for the affected industry, and what do companies say? |
| MB0222 | variations300:Q25-V2 | policy | natural | partial | 7 | For the Tax holiday for affordable housing projects extended to March 2022 (2022-01-31), how has it played out so far for the affected industry, and what do companies say... |
| MB0223 | variations300:Q25-V3 | policy | natural | partial | 7 | Using the document reference PIB PRID 2323840 on 2026-10-15, how has the data-centre tax holiday played out so far, and what do the companies in the theme say? |
| MB0224 | variations300:Q25-V4 | policy | terse | partial | 7 | data centre tax holiday outcome 2025-2026 |
| MB0225 | variations300:Q25-V5 | policy | Hinglish | partial | 7 | Data-centre operations ke liye tax holiday ka kya outcome raha? Budget, PIB, policy_events aur data-centre companies ke comments se evidence do. |
| MB0226 | variations300:Q25-V6 | policy | natural | partial | 7 | How has the tax holiday for data-centre operations in India played out so far, and what do the companies in the data-centre theme say? |
| MB0227 | variations300:Q25-V7 | industry | natural | partial | 7 | For all listed companies in data-centre, how has the tax holiday played out, and what do the companies and policy documents say? |
| MB0228 | variations300:Q25-V8 | index | natural | partial | 7 | For the NIFTY SMALLCAP 500 constituents, what has the tax holiday meant so far, and which members are named in the policy record? |
| MB0229 | variations300:Q25-V9 | policy | point-in-time | no | 7 | As of 1 February 2026, how had the data-centre tax holiday played out, using only evidence known by that date? |
| MB0230 | variations300:Q25-V10 | policy | natural | no | 7 | How has the data-centre tax holiday played out so far? If no data-centre tax holiday exists in policy_events, or the PIB starts too late, answer NOT IN DATA. |

### Family 7 - Company -> policy (0 primary cases; 33 cross-referenced)

No case has this as its primary family; the 33 cases below cross-reference it.

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0016 | shivam30:Q21 | policy | terse | - | primary 6 | RBI repo hike causes; PIB or RBI only |
| MB0017 | shivam30:Q22 | theme | terse | - | primary 6 | Second-hand electronics boom CY2026: who benefits |
| MB0020 | shivam30:Q25 | policy | terse | - | primary 6 | Data-centre tax holiday outcome so far |
| MB0181 | variations300:Q21-V1 | policy | natural | yes | primary 6 | For the Repo rate hiked 25 bps to 5.50% (2026-10-07), what were the causes, and which source published it first? |
| MB0182 | variations300:Q21-V2 | policy | natural | partial | primary 6 | For the Devolution of states' share in taxes increased (2026-02-01), what were the causes, and which source published it first? |
| MB0183 | variations300:Q21-V3 | policy | natural | yes | primary 6 | For the RBI Governor's Statement of 7 October 2026 (2026-10-07), what were the causes, and which source published it first? |
| MB0184 | variations300:Q21-V4 | policy | terse | yes | primary 6 | rbi repo hike 2026-10-07 causes pib or rbi |
| MB0185 | variations300:Q21-V5 | policy | Hinglish | yes | primary 6 | RBI ne 2026-10-07 ko repo rate kyun badhaya? Causes batao, aur ye news PIB ne publish kiya ya sirf RBI ne? Provenance ke saath. |
| MB0186 | variations300:Q21-V6 | policy | natural | yes | primary 6 | For the Repo rate hiked 25 bps to 5.50% of 2026-10-07, what were the causes, and was it published by PIB or only by the RBI? |
| MB0187 | variations300:Q21-V7 | industry | natural | yes | primary 6 | For all listed companies in banking, how does the 2026-10-07 RBI action transmit, and which sectors are named in the policy document? |
| MB0188 | variations300:Q21-V8 | index | natural | partial | primary 6 | For the NIFTY TOTAL MARKET constituents, how did the members react to the RBI action of 2026-10-07, and what does the PIB/RBI record show? |
| MB0189 | variations300:Q21-V9 | policy | point-in-time | no | primary 6 | As of 6 October 2026, what did the record show about the causes of the RBI action of 2026-10-07, and who published it first? |
| MB0190 | variations300:Q21-V10 | policy | natural | no | primary 6 | What were the causes of the RBI action of 2026-10-07, and was it published by PIB or only by RBI? If the policy document is not held, answer NOT IN DATA. |
| MB0191 | variations300:Q22-V1 | theme | natural | partial | primary 6 | For the Electronics Component Manufacturing Scheme approvals (2025-11-17), why does it matter for demand, and which sectors and listed companies does it touch? |
| MB0192 | variations300:Q22-V2 | theme | natural | partial | primary 6 | For the R&D in IT/Electronics/CCBT (2026-02-01), why does it matter for demand, and which sectors and listed companies does it touch? |
| MB0193 | variations300:Q22-V3 | theme | natural | partial | primary 6 | Using the document reference PIB PRID 2190872 on 2025-11-17, what does the policy record say about electronics demand in CY2026, and which companies does it touch? |
| MB0194 | variations300:Q22-V4 | theme | terse | partial | primary 6 | second hand electronics boom cy2026 who benefits |
| MB0195 | variations300:Q22-V5 | theme | Hinglish | partial | primary 6 | CY2026 mein second-hand aur refurbished electronics/laptops ki demand kyun badhi? Kaun listed companies ko fayda hoga, aur ye structural hai ya cyclical? Data gap bhi bat... |
| MB0196 | variations300:Q22-V6 | theme | natural | partial | primary 6 | Why did second-hand electronics and laptop sales rise in CY2026? Who benefits, and is the trend structural or cyclical? State any part that is NOT IN DATA. |
| MB0197 | variations300:Q22-V7 | industry | natural | partial | primary 6 | For all listed companies in electronics, what does the policy record say about demand in CY2026, and which companies does it touch? |
| MB0198 | variations300:Q22-V8 | index | natural | partial | primary 6 | For the NIFTY WAVES constituents, what does the policy and company evidence say about demand in CY2026, and who benefits? |
| MB0199 | variations300:Q22-V9 | theme | point-in-time | yes | primary 6 | As of 30 June 2026, what was known about the as of 30 June 2026 electronics demand trend, and which companies were named? |
| MB0200 | variations300:Q22-V10 | theme | natural | no | primary 6 | What do our stores say about refurbished/second-hand electronics sales in CY2026, and who benefits? If no sales series exists, answer NOT IN DATA and say which store is m... |
| MB0221 | variations300:Q25-V1 | policy | natural | partial | primary 6 | For the startup tax holiday extension (2025-02-01), how has it played out so far for the affected industry, and what do companies say? |
| MB0222 | variations300:Q25-V2 | policy | natural | partial | primary 6 | For the Tax holiday for affordable housing projects extended to March 2022 (2022-01-31), how has it played out so far for the affected industry, and what do companies say... |
| MB0223 | variations300:Q25-V3 | policy | natural | partial | primary 6 | Using the document reference PIB PRID 2323840 on 2026-10-15, how has the data-centre tax holiday played out so far, and what do the companies in the theme say? |
| MB0224 | variations300:Q25-V4 | policy | terse | partial | primary 6 | data centre tax holiday outcome 2025-2026 |
| MB0225 | variations300:Q25-V5 | policy | Hinglish | partial | primary 6 | Data-centre operations ke liye tax holiday ka kya outcome raha? Budget, PIB, policy_events aur data-centre companies ke comments se evidence do. |
| MB0226 | variations300:Q25-V6 | policy | natural | partial | primary 6 | How has the tax holiday for data-centre operations in India played out so far, and what do the companies in the data-centre theme say? |
| MB0227 | variations300:Q25-V7 | industry | natural | partial | primary 6 | For all listed companies in data-centre, how has the tax holiday played out, and what do the companies and policy documents say? |
| MB0228 | variations300:Q25-V8 | index | natural | partial | primary 6 | For the NIFTY SMALLCAP 500 constituents, what has the tax holiday meant so far, and which members are named in the policy record? |
| MB0229 | variations300:Q25-V9 | policy | point-in-time | no | primary 6 | As of 1 February 2026, how had the data-centre tax holiday played out, using only evidence known by that date? |
| MB0230 | variations300:Q25-V10 | policy | natural | no | primary 6 | How has the data-centre tax holiday played out so far? If no data-centre tax holiday exists in policy_events, or the PIB starts too late, answer NOT IN DATA. |

### Family 8 - Peers (5 primary cases; 33 cross-referenced)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0891 | reddit200:RD-I-061 | stock | natural | partial | - | Tata Motors PV versus Mahindra: which has the better EV mix and margin, and does the market already pay for it? |
| MB0892 | reddit200:RD-I-062 | stock | natural | partial | - | HDFC Bank versus ICICI Bank on NIM, ROA and credit cost: which is the cleaner compounder from here? |
| MB0893 | reddit200:RD-I-063 | stock | natural | partial | - | DMart versus Trent: which is growing revenue per store faster, and is the data even comparable? |
| MB0894 | reddit200:RD-I-064 | stock | natural | partial | - | Polycab versus KEI: which has the better working-capital cycle, and does the margin gap justify the valuation gap? |
| MB0895 | reddit200:RD-I-065 | industry | natural | partial | - | Sun Pharma versus Cipla: how much of the revenue is US, and which one is more exposed to a price-erosion shock? |
| MB0006 | shivam30:Q11 | stock | terse | - | primary 2 | KRISHNADEF segment revenue, latest quarter |
| MB0012 | shivam30:Q17 | industry | terse | - | primary 4 | HFC securitisation leader, QoQ/YoY with NPA guard |
| MB0019 | shivam30:Q24 | stock | terse | - | primary 6 | PARAGMILK on El Niño; dairy peers |
| MB0081 | variations300:Q11-V1 | stock | natural | yes | primary 2 | What was Avantel (NSE: AVANTEL)'s segment revenue for Q1FY27, with the absolute number for each reported segment? |
| MB0082 | variations300:Q11-V2 | stock | natural | yes | primary 2 | What was Astral (NSE: ASTRAL)'s segment revenue for Q1FY27, with the absolute number for each reported segment? |
| MB0083 | variations300:Q11-V3 | stock | natural | no | primary 2 | What was NSE: TIKONA (now GFSTEELS)'s segment revenue for Q1FY27, with the absolute number for each reported segment? |
| MB0084 | variations300:Q11-V4 | stock | terse | yes | primary 2 | GILLANDERS segment revenue Q1FY27 |
| MB0085 | variations300:Q11-V5 | stock | Hinglish | no | primary 2 | NTPC Green Energy (NSE: NTPCGREEN) ka Q1FY27 segment revenue kitna tha, segment-wise absolute numbers ke saath? XBRL context ka source bhi do. |
| MB0086 | variations300:Q11-V6 | stock | natural | yes | primary 2 | What was ACC (NSE: ACC)'s segment revenue for April-June 2026 (Q1 FY2026-27), with the absolute number for each reported segment? |
| MB0087 | variations300:Q11-V7 | industry | natural | yes | primary 2 | For all listed companies in Aerospace & Defense, rank the companies by reported segment revenue for Q1FY27. |
| MB0088 | variations300:Q11-V8 | index | natural | no | primary 2 | For the niftymidcap150 constituents, rank the companies by reported segment revenue for Q1FY27. |
| MB0089 | variations300:Q11-V9 | stock | point-in-time | yes | primary 2 | As of 30 June 2026, what segment revenue had Brainbees Solutions (NSE: FIRSTCRY) reported for Q1FY27? |
| MB0090 | variations300:Q11-V10 | stock | natural | no | primary 2 | What was 20 Microns (NSE: 20MICRONS)'s segment revenue for Q1FY27? If the filing has no segment context, answer NOT IN DATA and say which taxonomy is missing. |
| MB0141 | variations300:Q17-V1 | industry | natural | yes | primary 4 | Is Can Fin Homes (NSE: CANFINHOME) the leader in securitised disbursement among listed HFCs for Q1FY27, with net NPA up no more than 2 pp? Show the comparison. |
| MB0142 | variations300:Q17-V2 | industry | natural | partial | primary 4 | Among large-cap HFCs, who leads securitised disbursement for Q1FY27 with net NPA up no more than 2 pp? |
| MB0143 | variations300:Q17-V3 | industry | natural | partial | primary 4 | For NSE: IBULHSGFIN (now SAMMAANCAP), is it the leader in securitised disbursement among listed HFCs for Q1FY27, with net NPA up no more than 2 pp? Show the naming histor... |
| MB0144 | variations300:Q17-V4 | industry | terse | partial | primary 4 | hfc securitisation leader q1fy27 net npa |
| MB0145 | variations300:Q17-V5 | industry | Hinglish | partial | primary 4 | Listed HFCs mein securitised disbursement ka leader kaun hai Q1FY27 mein? QoQ aur YoY winner batao, lekin net NPA 2 percentage point se zyada na badhe. |
| MB0146 | variations300:Q17-V6 | industry | natural | yes | primary 4 | Which listed HFC is the leader in securitised disbursement for January-March 2026 (Q4FY26), QoQ and YoY, with net NPA rising no more than 2 pp? |
| MB0147 | variations300:Q17-V7 | industry | natural | yes | primary 4 | For all listed companies in Housing Finance, which listed financial company is the securitisation leader for Q1FY27 with the net-NPA guard, and what is the evidence? |
| MB0148 | variations300:Q17-V8 | index | natural | partial | primary 4 | For the NIFTY HOUSING FINANCE constituents, rank the financial companies on securitised disbursement for Q1FY27, with the net-NPA guard. |
| MB0149 | variations300:Q17-V9 | industry | point-in-time | yes | primary 4 | As of 30 June 2026, which HFC looked like the securitisation leader for Q1FY27, and on what evidence? |
| MB0150 | variations300:Q17-V10 | industry | natural | no | primary 4 | Which listed HFC led securitised disbursement in Q1FY27? If the securitisation figure is not in any structured store for GIC Housing Finance (NSE: GICHSGFIN), answer NOT ... |
| MB0211 | variations300:Q24-V1 | stock | natural | yes | primary 6 | What did Dodla Dairy (NSE: DODLA) say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? |
| MB0212 | variations300:Q24-V2 | stock | natural | yes | primary 6 | What did Milky Mist Dairy Food (NSE: MILKYMIST) say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? |
| MB0213 | variations300:Q24-V3 | stock | natural | yes | primary 6 | What did BSE scrip code 531531 say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? |
| MB0214 | variations300:Q24-V4 | stock | terse | yes | primary 6 | PARAGMILK el nino dairy margins |
| MB0215 | variations300:Q24-V5 | stock | Hinglish | yes | primary 6 | Heritage Foods (NSE: HERITGFOOD) ne El Nino 2026 ke asar par calls mein kya kaha? Dairy peers ka bhi comparison do, aur management ne kaise handle karne ko kaha. |
| MB0216 | variations300:Q24-V6 | stock | natural | no | primary 6 | What did Kwality Wall's (India) (NSE: KWIL) say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? |
| MB0217 | variations300:Q24-V7 | industry | natural | yes | primary 6 | For all listed companies in Fast Moving Consumer Goods, what did managements say about El Nino 2026, and how are they handling it? |
| MB0218 | variations300:Q24-V8 | index | natural | no | primary 6 | For the NIFTY SMALLCAP 100 constituents, how exposed are the members to El Nino 2026, and what did they say about handling it? |
| MB0219 | variations300:Q24-V9 | stock | point-in-time | no | primary 6 | As of 30 June 2026, what had Milkfood (NSE: MLKFOOD) said about El Nino 2026 and its dairy margins? |
| MB0220 | variations300:Q24-V10 | stock | natural | no | primary 6 | What did Knack Packaging (NSE: KNACK) say about El Nino 2026 on its calls? If no transcript is held for it, answer NOT IN DATA and name the store checked. |

### Family 9 - Event window (40 primary cases; 44 cross-referenced)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0586 | open300:A18-01 | stock | natural | yes | - | Titagarh filed Q1 FY27 results at 19:56 on 12 August 2026. What is the correct reaction window, and what was the return? |
| MB0587 | open300:A18-02 | stock | natural | yes | - | KEI filed Q1 FY27 results at 20:52 on 3 August 2026. What was the day-after return, and does it match the margin narrative? |
| MB0588 | open300:A18-03 | stock | natural | yes | - | BEL filed at 16:38 on 27 July 2026. The next session fell 4.46%. Was that a post-close or intraday filing? |
| MB0589 | open300:A18-04 | stock | Hinglish | partial | - | HAL ne 14:19 par file kiya aur 1.75% chadha — kya yeh clean reaction hai? (Hinglish) |
| MB0590 | open300:A18-05 | stock | natural | yes | - | RVNL filed at 17:19 on 11 August 2026 and the stock closed flat the next day. What does a zero return tell you? |
| MB0591 | open300:A18-06 | stock | natural | yes | - | Tata Steel filed at 19:56 on 30 July 2026 and rose 1.48% the next session. How large is that versus its own typical daily move? |
| MB0592 | open300:A18-07 | stock | natural | yes | - | IRCTC filed at 20:43 on 12 August 2026 and fell 1.77% the next day. What two alternatives should be ruled out first? |
| MB0593 | open300:A18-08 | stock | natural | yes | - | Jubilant FoodWorks filed at 16:30 on 13 August 2026. Why is the 14 August move the right window, and what was it? |
| MB0594 | open300:A18-09 | stock | natural | partial | - | Suzlon filed at 15:11 on 28 July 2026, during the session, and fell 9.65% that day. What can and cannot be concluded? |
| MB0595 | open300:A18-10 | stock | natural | partial | - | Mankind filed at 20:15 on 30 July 2026 and fell 4.13% on 31 July. What was the market doing that day? |
| MB0596 | open300:A18-11 | stock | natural | partial | - | PB Fintech filed a clarification on price movement on Sunday 27 September 2026. What is the first session that can react, and what did it do? |
| MB0597 | open300:A18-12 | stock | natural | yes | - | Trent's 1:2 bonus had an ex-date of 4 June 2026. How should an event study treat that day? |
| MB0598 | open300:A18-13 | stock | terse | partial | - | KAYNES 14 May 2026 — results or management change? |
| MB0599 | open300:A18-14 | stock | natural | yes | - | Cyient saw a bulk deal on 23 October 2026 and rose 7.81%. What does the deal data say about the direction of pressure? |
| MB0600 | open300:A18-15 | market-wide | natural | partial | - | Across the twelve Q1 FY27 result reactions here, which stock's move was largest relative to its own volatility, and what is the caveat? |
| MB0811 | ripple200:R10-01 | stock | natural | partial | - | A bulk deal printed on POLYCAB on 14 Jan 2026 — the same session as its largest delivery spike of the year. Take day 0 as the deal session, look at the 4 sessions before ... |
| MB0812 | ripple200:R10-02 | stock | natural | partial | - | KEI held its earnings call on 4 Aug 2026. Apply the 3:30 rule to the call intimation and to the results filing separately, then compare the 4 sessions before each day 0 w... |
| MB0813 | ripple200:R10-03 | stock | natural | partial | - | Take BEL's most recent order-win filing. If it was stamped after 15:30 IST, day 0 is the next session; if before, it is the same session. Which of the 4 sessions before d... |
| MB0814 | ripple200:R10-04 | stock | natural | partial | - | Take FIVESTAR's most recent rating action. Both the agency release and the company disclosure have a timestamp; use the earlier one for day 0, then test whether the 4 ses... |
| MB0815 | ripple200:R10-05 | stock | natural | partial | - | DIVISLAB announced a capex programme on its earnings call. The transcript is usable only when it is published, not when the call happened. Build day 0 from the publicatio... |
| MB0816 | ripple200:R10-06 | stock | natural | partial | - | A large steel group announces an acquisition outside trading hours. Work out which session is day 0 when the announcement is not on a trading day, then build the 4-sessio... |
| MB0817 | ripple200:R10-07 | stock | natural | partial | - | Take HAL's most recent management-change filing. Build day 0 from its dissemination timestamp and check the 4 sessions before it. What does the filing actually name — the... |
| MB0818 | ripple200:R10-08 | stock | natural | partial | - | The US tariff on shrimp-class exports is in policy_events with its own published_at. Build day 0 for the Indian exporter from that timestamp and ask whether a 4-session w... |
| MB0819 | ripple200:R10-09 | stock | natural | partial | - | The Union Budget speech is delivered inside the session, so day 0 is the speech session. Build the 4 sessions before it for the textile names and say whether positioning ... |
| MB0820 | ripple200:R10-10 | stock | natural | partial | - | The MPC statement is published before the close. Build day 0 for a bank from its timestamp, then check whether the 4 sessions before it contain anything a rule could call... |
| MB0821 | ripple200:R10-11 | stock | natural | partial | - | An index provider announces an inclusion and an effective date. That is two day-0s. Build both 4-session windows and say which one can show leakage and which one can only... |
| MB0822 | ripple200:R10-12 | stock | natural | partial | - | A PLI approval appears in a ministry release and later in the company's own disclosure. Take the earlier known_at for day 0 and ask whether the 4 sessions before it show ... |
| MB0823 | ripple200:R10-13 | stock | natural | partial | - | A demerger scheme is filed with the exchanges. The board approval and the filing are two candidate day-0s. Build both windows and say which one a leaker would have acted ... |
| MB0824 | ripple200:R10-14 | stock | natural | partial | - | A company announces a stock split, which has no cash effect. Build day 0 and check the 4 sessions before it. This is the negative control: how often does a delivery spike... |
| MB0825 | ripple200:R10-15 | stock | natural | partial | - | Take APLAPOLLO's most recent pledge disclosure. Build day 0 from the dissemination timestamp and check the 4 sessions before it for distribution rather than accumulation. |
| MB0826 | ripple200:R10-16 | stock | natural | partial | - | A tax or regulatory demand order is uploaded to the exchange. Build day 0, check the 4 sessions before it, and say which document in the store actually contains the order... |
| MB0827 | ripple200:R10-17 | stock | natural | partial | - | Take ORIENTPPR's most recent auditor change. Build day 0 and check the 4 sessions before it. An auditor resignation should not leak, which makes it a second control. |
| MB0828 | ripple200:R10-18 | stock | natural | partial | - | Take APARINDS' largest insider sale in insider_trades_v2. The intimation date gives day 0; check the 4 sessions before it and say whether the sale itself was the informat... |
| MB0829 | ripple200:R10-19 | stock | natural | partial | - | A company cuts its guidance on the call and the transcript is published later. Build day 0 from the publication, then check the 4 sessions before it. Which document carri... |
| MB0830 | ripple200:R10-20 | stock | natural | partial | - | A buyback is announced after the close, so day 0 is the next session. Check the 4 sessions before it: is the pre-window evidence of a leak, or of price support before a t... |
| MB0886 | reddit200:RD-I-056 | stock | natural | yes | - | Infosys Q2FY26: what should I watch in the print, and which line item explained the market's reaction? |
| MB0887 | reddit200:RD-I-057 | stock | natural | yes | - | TCS: did the deal-win total convert into revenue this quarter, or is the book still growing faster than billing? |
| MB0888 | reddit200:RD-I-058 | stock | natural | partial | - | HDFC Bank Q2FY26: was the NIM expansion real or a one-off treasury gain, and what did management guide? |
| MB0889 | reddit200:RD-I-059 | stock | natural | partial | - | Maruti: did the quarter's volume growth come from mix or discounts, and what does that say about the margin? |
| MB0890 | reddit200:RD-I-060 | stock | natural | partial | - | Reliance: which segment actually drove the quarter, and did the market react to the consolidated or the segment story? |
| MB0002 | shivam30:DBQ2 | stock | terse | - | primary 1 | 532627 latest AR: control change |
| MB0013 | shivam30:Q18 | industry | terse | - | primary 6 | OMCs: record Q4 then loss Q1; earliest PIT signal |
| MB0014 | shivam30:Q19 | stock | terse | - | primary 2 | MONQ50 ETF jump/fall + tracking error |
| MB0015 | shivam30:Q20 | stock | terse | - | primary 6 | Garware: tariff hit, then negative correlation |
| MB0041 | variations300:DBQ2-V1 | stock | natural | yes | primary 1 | What did CESC (NSE: CESC)'s latest annual report (FY2026) disclose about a change in ownership or control, and where in the report? |
| MB0042 | variations300:DBQ2-V2 | stock | natural | yes | primary 1 | What did Reliance Infrastructure (NSE: RELINFRA)'s latest annual report (FY2026) disclose about a change in ownership or control, and where in the report? |
| MB0043 | variations300:DBQ2-V3 | stock | natural | yes | primary 1 | What did NSE: SHIL (now HINDWAREAP)'s latest annual report (FY2026) disclose about a change in ownership or control, and where in the report? |
| MB0044 | variations300:DBQ2-V4 | stock | terse | partial | primary 1 | 570002 latest annual report control change |
| MB0045 | variations300:DBQ2-V5 | stock | Hinglish | yes | primary 1 | JSW Steel (NSE: JSWSTEEL) ke latest annual report mein ownership ya control change ke baare mein kya likha hai? Kaunsa saal, kaunsa page, aur exactly kya disclosure hai? |
| MB0046 | variations300:DBQ2-V6 | stock | natural | yes | primary 1 | What did Craftsman Automation (NSE: CRAFTSMAN)'s latest annual report (FY2025) disclose about a change in ownership or control, and where in the report? |
| MB0047 | variations300:DBQ2-V7 | industry | natural | yes | primary 1 | For all listed companies in Power, which companies disclosed a change in control or ownership in their latest annual report, and what changed? |
| MB0048 | variations300:DBQ2-V8 | index | natural | partial | primary 1 | For the NIFTY 500 constituents, which companies disclosed a change in control or ownership in their latest annual report, and what changed? |
| MB0049 | variations300:DBQ2-V9 | stock | point-in-time | yes | primary 1 | As of 30 June 2026, what did Prism Johnson (NSE: PRSMJOHNSN)'s latest filed annual report say about a change in control or ownership? |
| MB0050 | variations300:DBQ2-V10 | stock | natural | no | primary 1 | What did Aakash Exploration Services (NSE: AAKASH)'s latest annual report disclose about a change in control? If no annual report is held for it, answer NOT IN DATA and n... |
| MB0151 | variations300:Q18-V1 | industry | point-in-time | yes | primary 6 | Sugar Q4FY26-to-Q1FY27 profit swing — which companies in Sugar swung from profit in Q4FY26 to a loss in Q1FY27, and when was that first visible point-in-time? |
| MB0152 | variations300:Q18-V2 | industry | point-in-time | yes | primary 6 | Media & Entertainment Q4FY26-to-Q1FY27 profit swing — which companies in Media & Entertainment swung from profit in Q4FY26 to a loss in Q1FY27, and when was that first vi... |
| MB0153 | variations300:Q18-V3 | industry | point-in-time | yes | primary 6 | For BSE scrip code 532543, when did the Q4FY26-to-Q1FY27 profit swing become visible point-in-time, and from which filing? |
| MB0154 | variations300:Q18-V4 | industry | terse | yes | primary 6 | omc q4fy26 profit q1fy27 loss earliest pit |
| MB0155 | variations300:Q18-V5 | industry | Hinglish | yes | primary 6 | OMCs ne Q4FY26 mein record profit aur Q1FY27 mein bada loss kaise kiya? Sabse pehle kaunsa data point point-in-time visible tha, date ke saath batao. |
| MB0156 | variations300:Q18-V6 | industry | natural | yes | primary 6 | For the January-March 2026 and April-June 2026 quarters, which OMCs went from record profit to a loss, and when did that first become visible? |
| MB0157 | variations300:Q18-V7 | industry | point-in-time | yes | primary 6 | For all listed companies in Petroleum Products, which companies swung from profit in Q4FY26 to a loss in Q1FY27, and what was the earliest point-in-time evidence? |
| MB0158 | variations300:Q18-V8 | index | point-in-time | partial | primary 6 | For the NIFTY OIL & GAS constituents, which companies swung from profit in Q4FY26 to a loss in Q1FY27, and what was the earliest point-in-time evidence? |
| MB0159 | variations300:Q18-V9 | industry | point-in-time | yes | primary 6 | As of 30 June 2026, what did the data already show about the OMC profit swing from Q4FY26 to Q1FY27? |
| MB0160 | variations300:Q18-V10 | industry | natural | no | primary 6 | Using the coal price series, when did the OMC Q4FY26-to-Q1FY27 trend first become visible? If the series ends before that window, answer NOT IN DATA. |
| MB0161 | variations300:Q19-V1 | stock | natural | partial | primary 2 | For Motilal Oswal Nasdaq 100 ETF (MOFN100) (MON100, ISIN INF247L01AP3), explain the jump in 10-18 Sep 2026 and 18-28 Sep 2026 using the underlying index and FX, and give ... |
| MB0162 | variations300:Q19-V2 | stock | natural | partial | primary 2 | For QGOLDHALF (QGOLDHALF, ISIN INF082J01010), a different ETF category from the original, what was the move in 10-18 Sep 2026 and 18-28 Sep 2026, and how did NAV track iN... |
| MB0163 | variations300:Q19-V3 | stock | natural | partial | primary 2 | For ISIN INF247L01AU3, what was the move in 10-18 Sep 2026 and 18-28 Sep 2026 and the tracking error against its underlying index and the rupee? |
| MB0164 | variations300:Q19-V4 | stock | terse | partial | primary 2 | QNIFTY jump tracking error Sep 2026 |
| MB0165 | variations300:Q19-V5 | stock | Hinglish | partial | primary 2 | Bajaj Finserv Nifty Bank ETF (BANKBETF, ISIN INF0QA701714) 10-18 September 2026 ke beech kyun jump hua aur 18-28 September mein kyun gira? Underlying index, FX aur NAV tr... |
| MB0166 | variations300:Q19-V6 | stock | natural | partial | primary 2 | For Bajaj Finserv Nifty 50 ETF (NIFTYBETF, ISIN INF0QA701722), explain the jump in September 2026 using the underlying index and FX, and give the NAV tracking error. |
| MB0167 | variations300:Q19-V7 | index | natural | partial | primary 2 | For the India-listed ETF universe, what explains the move in 10-18 Sep 2026 and 18-28 Sep 2026, and what is the NAV tracking error? |
| MB0168 | variations300:Q19-V8 | index | natural | partial | primary 2 | For the India-listed gold ETFs, which ETF moved most in 10-18 Sep 2026 and 18-28 Sep 2026, and what was its tracking error against the underlying index and FX? |
| MB0169 | variations300:Q19-V9 | stock | point-in-time | partial | primary 2 | As of 17 September 2026, what was the move in Quantum Gold ETF (QGOLDHALF, ISIN INF082J01408) up to that date, and what tracking error was visible by then? |
| MB0170 | variations300:Q19-V10 | stock | natural | no | primary 2 | For NIF100IETF (NIF100IETF, ISIN INF109KA1962), what was the move and NAV tracking error in 10-18 Sep 2026 and 18-28 Sep 2026? If the ETF has no NAV or iNAV rows, answer ... |
| MB0171 | variations300:Q20-V1 | stock | natural | partial | primary 6 | How sensitive was KRN Heat Exchanger and Refrigeration (NSE: KRN) to Customs tariff rationalization - remove 7 tariff rates (1 February 2025) in the 60 days after it, and... |
| MB0172 | variations300:Q20-V2 | stock | natural | partial | primary 6 | How sensitive was APL Apollo Tubes (NSE: APLAPOLLO) to Customs tariff rationalization - remove 7 tariff rates (1 February 2025) in the 60 days after it, and did its 60-da... |
| MB0173 | variations300:Q20-V3 | stock | natural | partial | primary 6 | How sensitive was NSE: DHARAMSI (now DMCC) to Customs tariff rationalization - remove 7 tariff rates (1 February 2025) in the 60 days after it, and did its 60-day return ... |
| MB0174 | variations300:Q20-V4 | stock | terse | partial | primary 6 | PAKKA tariff sensitivity rolling correlation |
| MB0175 | variations300:Q20-V5 | stock | Hinglish | partial | primary 6 | Eco Recycling (NSE: ECORECO) par Customs tariff rationalization - remove 7 tariff rates (1 February 2025) ka kitna asar pada, aur agle 12 mahine mein tariff news se corre... |
| MB0176 | variations300:Q20-V6 | stock | natural | partial | primary 6 | How did JSW Energy (NSE: JSWENERGY)'s rolling correlation with Customs tariff rationalization - remove 7 tariff rates (1 February 2025) change over the 12 months after Ma... |
| MB0177 | variations300:Q20-V7 | industry | natural | partial | primary 6 | For all listed companies in Industrial Products, how sensitive were the members to Customs tariff rationalization - remove 7 tariff rates (1 February 2025), and did the 6... |
| MB0178 | variations300:Q20-V8 | index | natural | partial | primary 6 | For the NIFTY MIDSMALLCAP400 MOMENTUM QUALITY 100 constituents, how sensitive were the members to Customs tariff rationalization - remove 7 tariff rates (1 February 2025)... |
| MB0179 | variations300:Q20-V9 | stock | point-in-time | partial | primary 6 | As of 31 March 2026, what did the rolling correlation of National Aluminium Company (NSE: NATIONALUM) with Customs tariff rationalization - remove 7 tariff rates (1 Febru... |
| MB0180 | variations300:Q20-V10 | stock | natural | no | primary 6 | For 20 Microns (NSE: 20MICRONS), did the tariff impact and any later negative correlation survive its corporate action on adjusted prices? If not, answer NOT IN DATA. |

### Family 10 - Opinion vs truth (0 primary cases)

No case declares this family in any source bank.

### Family 11 - Point in time (20 primary cases; 44 cross-referenced)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0791 | ripple200:R09-01 | macro | point-in-time | no | - | For a cable maker's margin trough, three hop-1 series compete: the metal price, the price-hike statement, and the delivery spike. Which one turns first, and is each of th... |
| MB0792 | ripple200:R09-02 | macro | point-in-time | no | - | Entry-segment two-wheeler demand: does the rural wage series, the scheme allocation, or the dealer inventory turn first? Which of them is point-in-time today? |
| MB0793 | ripple200:R09-03 | macro | point-in-time | partial | - | Bank NIM: does the weighted average call rate, the deposit rate, or credit growth turn first? And is the deposit rate a point-in-time series at all? |
| MB0794 | ripple200:R09-04 | macro | natural | no | - | EPC margin: which signals first — the order book, the steel index, or the award pipeline? And which of the three is in our data with a known_at? |
| MB0795 | ripple200:R09-05 | macro | point-in-time | no | - | An export order is being lost. Does container freight, port throughput, or the company's delivery spike turn first? Which of them can be read point-in-time? |
| MB0796 | ripple200:R09-06 | macro | natural | no | - | Capex revival: order inflow, capital-goods production, or credit growth — which turns first, and which is usable without look-ahead? |
| MB0797 | ripple200:R09-07 | macro | natural | no | - | Power demand: plant load factor, coal stock days, or the exchange price first? Which one is a leading indicator for the aluminium smelter's cost? |
| MB0798 | ripple200:R09-08 | macro | point-in-time | no | - | Steel price: the HRC index, mill inventory days, or import volume first? Which is point-in-time in our data today? |
| MB0799 | ripple200:R09-09 | macro | natural | partial | - | US generic drug erosion: ANDA approvals, price erosion commentary, or distributor inventory first? Which one can be dated from a filing? |
| MB0800 | ripple200:R09-10 | macro | natural | no | - | Cement demand: dispatches, GST collection, or pet coke first? Which turns before the other two? |
| MB0801 | ripple200:R09-11 | macro | natural | no | - | Freight: the Baltic index, the container rate, or the charter rate first? Which one is published with a date usable in a backtest? |
| MB0802 | ripple200:R09-12 | macro | point-in-time | partial | - | Foreign flow: FPI limit headroom, index membership changes, or the delivery spike first? Which is point-in-time and which is a revision risk? |
| MB0803 | ripple200:R09-13 | macro | natural | no | - | The rupee: forward premium, spot, or exporter commentary first? Which of them is a usable leading series and which is interpretation? |
| MB0804 | ripple200:R09-14 | macro | point-in-time | no | - | NBFC credit cost: bounce rates, disbursement growth, or GNPA first? Which one is point-in-time in a filing, and which is not published at all? |
| MB0805 | ripple200:R09-15 | macro | natural | partial | - | Hospital revenue per bed: bed count, occupancy, or pricing first? Which is dated in a filing? |
| MB0806 | ripple200:R09-16 | macro | natural | no | - | Dairy procurement: rainfall, fodder price, or the cooperative's procurement price first? Which of them is a published series? |
| MB0807 | ripple200:R09-17 | macro | natural | no | - | Tyre replacement: freight movement, kilometres run, or dealer stock first? Which one is available in our data with a date? |
| MB0808 | ripple200:R09-18 | macro | natural | no | - | Capital-goods activity: order inflow, GST on capital goods, or the credit-to-industry series first? Which one is a revision risk? |
| MB0809 | ripple200:R09-19 | macro | natural | partial | - | Insurance: commission paid, annual premium equivalent, or the partner bank's fee income first? Which one is dated in a filing? |
| MB0810 | ripple200:R09-20 | macro | point-in-time | partial | - | A defence order: the budget allocation, the award, or the delivery first? Which of the three is usable in a point-in-time test? |
| MB0004 | shivam30:DBQ4 | stock | terse | - | primary 2 | P/B now vs stored |
| MB0010 | shivam30:Q15 | stock | terse | - | primary 2 | VINCOFE public shareholding Sep 2026 |
| MB0013 | shivam30:Q18 | industry | terse | - | primary 6 | OMCs: record Q4 then loss Q1; earliest PIT signal |
| MB0022 | shivam30:QA2 | stock | point-in-time | - | primary 2 | What is the promoter holding of NSE: BLACKBUCK as of September 2026? |
| MB0061 | variations300:DBQ4-V1 | stock | natural | partial | primary 2 | What is Goldiam International (NSE: GOLDIAM)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. |
| MB0062 | variations300:DBQ4-V2 | stock | natural | partial | primary 2 | What is Ahlada Engineers (NSE: AHLADA)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. |
| MB0063 | variations300:DBQ4-V3 | stock | natural | partial | primary 2 | What is NSE: INFRATEL (now INDUSTOWER)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. |
| MB0064 | variations300:DBQ4-V4 | stock | terse | partial | primary 2 | GODREJIND pb ratio stored vs computed |
| MB0065 | variations300:DBQ4-V5 | stock | Hinglish | partial | primary 2 | Flexituff Ventures International (NSE: FLEXITUFF) ka P/B ratio kitna hai? Database mein stored ratio aur aaj ke price se nikaala hua ratio dono batao, aur farq kyun hai. |
| MB0066 | variations300:DBQ4-V6 | stock | natural | partial | primary 2 | What is Kovai Medical Center & Hospital (NSE: KOVAI)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. |
| MB0067 | variations300:DBQ4-V7 | industry | natural | partial | primary 2 | For all listed companies in Consumer Durables, rank the companies by P/B computed from the close on 19 October 2026 and the latest annual-report book value. |
| MB0068 | variations300:DBQ4-V8 | index | natural | partial | primary 2 | For the NIFTY500 LARGEMIDSMALL EQUAL-CAP WEIGHTED constituents, rank the companies by P/B computed from the close on 19 October 2026 and the latest annual-report book val... |
| MB0069 | variations300:DBQ4-V9 | stock | point-in-time | partial | primary 2 | As of 31 March 2026, what was Satia Industries (NSE: SATIA)'s P/B using the price and book value known by that date? Compare it with the stored ratio. |
| MB0070 | variations300:DBQ4-V10 | stock | natural | partial | primary 2 | What is Motherson Sumi Wiring India (NSE: MSUMI)'s P/B now versus the stored ratio, after adjusting for its corporate action? If book value per share is not held, say NOT... |
| MB0121 | variations300:Q15-V1 | stock | point-in-time | yes | primary 2 | What is Fertilizers and Chemicals Travancore (NSE: FACT)'s public shareholding as of Sep 2026? |
| MB0122 | variations300:Q15-V2 | stock | point-in-time | yes | primary 2 | What is NHPC (NSE: NHPC)'s public shareholding as of Sep 2026? |
| MB0123 | variations300:Q15-V3 | stock | point-in-time | yes | primary 2 | What is NSE: ADLABS (now IMAGICAA)'s public shareholding as of Sep 2026? |
| MB0124 | variations300:Q15-V4 | stock | terse | yes | primary 2 | ITI public shareholding Sep 2026 |
| MB0125 | variations300:Q15-V5 | stock | Hinglish | yes | primary 2 | M & B Engineering (NSE: MBEL) mein public shareholding Sep 2026 tak kitni hai? Promoter aur public dono ka percentage filing se batao. |
| MB0126 | variations300:Q15-V6 | stock | point-in-time | yes | primary 2 | What is JK Cement (NSE: JKCEMENT)'s public shareholding as of 30 September 2026? |
| MB0127 | variations300:Q15-V7 | industry | point-in-time | yes | primary 2 | For all listed companies in the industry, rank the companies by public shareholding as of Sep 2026. |
| MB0128 | variations300:Q15-V8 | index | point-in-time | no | primary 2 | For the NIFTY MIDCAP 100 constituents, rank the companies by public shareholding as of Sep 2026. |
| MB0129 | variations300:Q15-V9 | stock | point-in-time | yes | primary 2 | As of 30 June 2026, what was Digicontent (NSE: DGCONTENT)'s public shareholding per the latest filing on or before that date? |
| MB0130 | variations300:Q15-V10 | stock | point-in-time | no | primary 2 | What is 360 One Wam (NSE: 360ONE)'s public shareholding as of Sep 2026? If that quarter's shareholding filing is not held, answer NOT IN DATA. |
| MB0151 | variations300:Q18-V1 | industry | point-in-time | yes | primary 6 | Sugar Q4FY26-to-Q1FY27 profit swing — which companies in Sugar swung from profit in Q4FY26 to a loss in Q1FY27, and when was that first visible point-in-time? |
| MB0152 | variations300:Q18-V2 | industry | point-in-time | yes | primary 6 | Media & Entertainment Q4FY26-to-Q1FY27 profit swing — which companies in Media & Entertainment swung from profit in Q4FY26 to a loss in Q1FY27, and when was that first vi... |
| MB0153 | variations300:Q18-V3 | industry | point-in-time | yes | primary 6 | For BSE scrip code 532543, when did the Q4FY26-to-Q1FY27 profit swing become visible point-in-time, and from which filing? |
| MB0154 | variations300:Q18-V4 | industry | terse | yes | primary 6 | omc q4fy26 profit q1fy27 loss earliest pit |
| MB0155 | variations300:Q18-V5 | industry | Hinglish | yes | primary 6 | OMCs ne Q4FY26 mein record profit aur Q1FY27 mein bada loss kaise kiya? Sabse pehle kaunsa data point point-in-time visible tha, date ke saath batao. |
| MB0156 | variations300:Q18-V6 | industry | natural | yes | primary 6 | For the January-March 2026 and April-June 2026 quarters, which OMCs went from record profit to a loss, and when did that first become visible? |
| MB0157 | variations300:Q18-V7 | industry | point-in-time | yes | primary 6 | For all listed companies in Petroleum Products, which companies swung from profit in Q4FY26 to a loss in Q1FY27, and what was the earliest point-in-time evidence? |
| MB0158 | variations300:Q18-V8 | index | point-in-time | partial | primary 6 | For the NIFTY OIL & GAS constituents, which companies swung from profit in Q4FY26 to a loss in Q1FY27, and what was the earliest point-in-time evidence? |
| MB0159 | variations300:Q18-V9 | industry | point-in-time | yes | primary 6 | As of 30 June 2026, what did the data already show about the OMC profit swing from Q4FY26 to Q1FY27? |
| MB0160 | variations300:Q18-V10 | industry | natural | no | primary 6 | Using the coal price series, when did the OMC Q4FY26-to-Q1FY27 trend first become visible? If the series ends before that window, answer NOT IN DATA. |
| MB0241 | variations300:QA2-V1 | stock | point-in-time | yes | primary 2 | What is The Great Eastern Shipping Company (NSE: GESHIP)'s promoter holding as of Sep 2026, per the latest filing? |
| MB0242 | variations300:QA2-V2 | stock | point-in-time | yes | primary 2 | What is Indiqube Spaces (NSE: INDIQUBE)'s promoter holding as of Sep 2026, per the latest filing? |
| MB0243 | variations300:QA2-V3 | stock | point-in-time | partial | primary 2 | What is NSE: LTI (now LTM)'s promoter holding as of Sep 2026, per the latest filing? |
| MB0244 | variations300:QA2-V4 | stock | terse | yes | primary 2 | INTERARCH promoter holding Sep 2026 |
| MB0245 | variations300:QA2-V5 | stock | Hinglish | yes | primary 2 | Himadri Speciality Chemical (NSE: HSCL) mein promoter ki holding Sep 2026 tak kitni hai? Latest shareholding filing se number aur date batao. |
| MB0246 | variations300:QA2-V6 | stock | point-in-time | yes | primary 2 | What is Precot (NSE: PRECOT)'s promoter holding as of 30 September 2026, per the latest filing? |
| MB0247 | variations300:QA2-V7 | industry | point-in-time | partial | primary 2 | For all listed companies in Transport Services, what is the promoter holding as of Sep 2026, ranked from highest to lowest? |
| MB0248 | variations300:QA2-V8 | index | point-in-time | no | primary 2 | For the NIFTY MIDSMALLCAP 400 constituents, what is the promoter holding as of Sep 2026, ranked from highest to lowest? |
| MB0249 | variations300:QA2-V9 | stock | point-in-time | yes | primary 2 | As of 30 June 2026, what was The Phoenix Mills (NSE: PHOENIXLTD)'s promoter holding per the latest shareholding filing on or before that date? |
| MB0250 | variations300:QA2-V10 | stock | point-in-time | no | primary 2 | What is 360 One Wam (NSE: 360ONE)'s promoter holding as of Sep 2026? If the September 2026 shareholding filing is not held, answer NOT IN DATA and say why. |

### Family 12 - When / timeline (50 primary cases; 30 cross-referenced)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0331 | open300:A01-01 | stock | natural | yes | - | KEI Industries' first phase at Sanand: what month did it actually get commissioned, and how far behind the original plan was that? |
| MB0332 | open300:A01-02 | stock | natural | yes | - | Dixon's Vivo joint venture: from which quarter does management expect it to start showing up in revenue? |
| MB0333 | open300:A01-03 | stock | natural | yes | - | Tata Power's renewables arm: how much capacity was already commissioned when management spoke, and how much was due 'in the next few weeks'? |
| MB0334 | open300:A01-04 | stock | natural | yes | - | SRF is putting up a second pharma-intermediate plant at Dahej. How much is the capex and over what commissioning window did management guide? |
| MB0335 | open300:A01-05 | stock | natural | yes | - | Cochin Shipyard's ISRF joint venture with Drydocks World, Dubai: by when is it targeted to be in place, and what is it conditional on? |
| MB0336 | open300:A01-06 | stock | natural | partial | - | IRCTC's payment-aggregator application: what did RBI extend the deadline to, and has the licence actually come through since? |
| MB0337 | open300:A01-07 | stock | terse | partial | - | APLAPOLLO 8 MT by FY28 — slipped or on track? |
| MB0338 | open300:A01-08 | stock | natural | yes | - | Titagarh Rail Systems is 'ready to ramp up' wagon output. To what monthly run-rate, and what single condition does management put on doing it? |
| MB0339 | open300:A01-09 | stock | natural | yes | - | Adani Green: what renewable-capacity milestone did management claim in Q1 FY27, and how does it split between this quarter and earlier years? |
| MB0340 | open300:A01-10 | stock | natural | yes | - | NTPC has over 33 GW under construction. What is the coal/hydro/renewable split, and which of those is the largest single block? |
| MB0341 | open300:A01-11 | stock | natural | yes | - | RVNL's BharatNet work: what execution timeline did management give, and what happens after the build phase? |
| MB0342 | open300:A01-12 | stock | natural | yes | - | Afcons' Mumbai-Ahmedabad high-speed-rail C2 package: what is the current status of the two tunnel-boring machines? |
| MB0343 | open300:A01-13 | stock | Hinglish | yes | - | BEL ka QRSAM order kis approval ka wait kar raha hai, aur kab tak? (Hinglish) |
| MB0344 | open300:A01-14 | stock | natural | partial | - | UltraTech's capacity is 184 million tonnes including India Cements and Kesoram. What is the target it is being expanded to, and over what period? |
| MB0345 | open300:A01-15 | stock | natural | partial | - | Hindalco's renewable-energy capacity: how much does it have, of what mix, and what did management say it does to cost? |
| MB0346 | open300:A02-01 | stock | natural | yes | - | Titagarh says it will only ramp wagons once demand is 'sustainable'. What did management say the current network run-rate is, and what is it below? |
| MB0347 | open300:A02-02 | stock | natural | partial | - | Dixon's operating margin compressed because the mobile-PLI benefit expired. When does management expect the margin to normalise, and on what? |
| MB0348 | open300:A02-03 | stock | natural | yes | - | KEI's operating margin improved in FY26. By how much, and what does that say about the pricing environment for cables? |
| MB0349 | open300:A02-04 | stock | natural | partial | - | UltraTech says cement demand for the country grew about 4% in the quarter. What did management give as the reason the market is not stronger? |
| MB0350 | open300:A02-05 | stock | natural | partial | - | IndiGo reported revenue ahead of its own expectation. What did management say about the demand environment and when it expected to add capacity? |
| MB0351 | open300:A02-06 | stock | natural | yes | - | Polycab has started BharatNet execution. Over how many years does that run, and from when? |
| MB0352 | open300:A02-07 | stock | natural | partial | - | Suzlon says 4.5 GW of manufacturing capacity is fully operational. When does that capacity convert into revenue, and what gates it? |
| MB0353 | open300:A02-08 | stock | natural | partial | - | Amber Enterprises signed a manufacturing collaboration covering Oppo, OnePlus and Realme. When was it executed, and when does management expect it to matter? |
| MB0354 | open300:A02-09 | stock | natural | partial | - | Jubilant FoodWorks has close to 3,600 stores, about 2,530 in India. When does management expect store additions to return to guidance, and why the pause? |
| MB0355 | open300:A02-10 | stock | Hinglish | partial | - | SAIL ne Q1FY27 mein capital repairs aage khiske kyun, aur output kab recover hoga? (Hinglish) |
| MB0356 | open300:A02-11 | stock | natural | partial | - | Muthoot Finance opened 177 branches in a year. When does gold-loan demand seasonally peak, and what did management say about branch-level demand? |
| MB0357 | open300:A02-12 | stock | terse | yes | - | TEXRAIL 100 leasing rakes — when? |
| MB0358 | open300:A02-13 | stock | natural | partial | - | Ircon has a new dedicated-freight-corridor project in the pipeline. What is the status of the tender, and when does revenue start? |
| MB0359 | open300:A02-14 | industry | natural | partial | - | When does the cement industry get its next round of price increases, and what would have to change in demand for that? |
| MB0360 | open300:A02-15 | stock | Hinglish | partial | - | BEL ne FY27 ke liye 15% growth bola tha — kaunsa half-year usko uthana padega, aur management ne kya skew bataya? (Hinglish) |
| MB0751 | ripple200:R07-01 | industry | natural | partial | - | Copper moves 20% in a quarter. Using our own quarterly margin series for the cable makers, what was the last cycle's lag between the metal move and the margin trough, and... |
| MB0752 | ripple200:R07-02 | industry | natural | partial | - | Crude moves 20%. How many quarters pass before the paint makers' margin trough prints, and is the trough before or after the price hike is announced? |
| MB0753 | ripple200:R07-03 | policy | natural | partial | - | The repo is cut. Using the last easing cycle, how many quarters before the bank's NIM troughs, and does the trough arrive before or after the deposit repricing is complet... |
| MB0754 | ripple200:R07-04 | policy | natural | partial | - | The repo is raised. How long before an NBFC's cost of funds actually rises, given its borrowing maturities? Compute the lag from the debt schedule rather than assuming it... |
| MB0755 | ripple200:R07-05 | industry | natural | partial | - | The rupee falls 5%. How many quarters before the IT exporter's margin shows it, and which quarter does the hedge book shift the gain into? |
| MB0756 | ripple200:R07-06 | industry | natural | partial | - | Steel rises 15%. How many quarters before the forging and stamping names' margin troughs, and is the lag shorter or longer than the OEM's? |
| MB0757 | ripple200:R07-07 | industry | natural | no | - | A monsoon deficit of 20% hits two districts. How many quarters before tractor volume falls, and what does our own history say about the lag between rainfall and volume? |
| MB0758 | ripple200:R07-08 | industry | natural | no | - | MGNREGS spending rises. Trace it to rural wages, then to two-wheeler entry-segment volume, and state the lag you can actually verify versus the one you are assuming. |
| MB0759 | ripple200:R07-09 | industry | natural | partial | - | Central capex is released in April. How many quarters before the EPC contractor's revenue reflects it, and where does the money actually sit in the meantime? |
| MB0760 | ripple200:R07-10 | industry | natural | partial | - | A defence order is signed. How long before it appears in the prime's revenue, and how much of the order book is recognised in the first year? |
| MB0761 | ripple200:R07-11 | stock | natural | partial | - | A capacity is announced with a commissioning date. Across the last cycle, how much did the date slip, and what is the slippage measured against? |
| MB0762 | ripple200:R07-12 | policy | natural | no | - | A PLI application is approved. How long before the incentive cash reaches the company, and where does it appear in the P&L? |
| MB0763 | ripple200:R07-13 | stock | natural | no | - | A company raises equity for a plant. How many quarters from the raise to the first rupee of revenue, and what does the past cycle say about the gap between the stated and... |
| MB0764 | ripple200:R07-14 | industry | natural | no | - | Freight doubles. How many quarters before the importer's cash cycle lengthens, and what does the past cycle say it cost in interest? |
| MB0765 | ripple200:R07-15 | stock | natural | no | - | A rating is downgraded. How long before the company's incremental borrowing cost rises, and does the existing debt reprice? |
| MB0766 | ripple200:R07-16 | policy | natural | partial | - | A tariff is imposed on a product. How long before the exporter's order book shows the loss, and how long before the revenue does? |
| MB0767 | ripple200:R07-17 | stock | natural | partial | - | A price hike is announced. How many quarters before the volume loss shows, and does the margin peak before or after the volume trough? |
| MB0768 | ripple200:R07-18 | stock | natural | no | - | An inventory build precedes a margin recovery. How many quarters between the two in our own data, and is the build a signal or a coincidence? |
| MB0769 | ripple200:R07-19 | stock | natural | partial | - | A company repays debt from cash flow. How many quarters before the interest saving appears, and how much of the saving is already in the run-rate? |
| MB0770 | ripple200:R07-20 | stock | natural | no | - | A QIP is priced at a discount. How many quarters of EPS dilution follow, and when does the new capital start earning? |
| MB0526 | open300:A14-01 | stock | natural | partial | primary 3 | BEL guided 15% revenue growth for FY27. What did Q1 FY27 actually deliver, and is the guidance still credible? |
| MB0527 | open300:A14-02 | stock | natural | partial | primary 3 | Suzlon guided a 17-18% EBITDA margin for FY27. What has it actually reported, and what is the gap? |
| MB0528 | open300:A14-03 | stock | natural | partial | primary 3 | Tatapower said 200 MW was commissioned and another 500 MW would follow in weeks. Did the later disclosure confirm the 500 MW? |
| MB0529 | open300:A14-04 | stock | natural | partial | primary 3 | SRF guided the Dahej second pharma plant in eight months with Rs 180 crore. Has it commissioned, and how would you check? |
| MB0530 | open300:A14-05 | stock | natural | yes | primary 3 | KEI's Sanand phase 1 was late by about six months and commissioned in December 2025. Did the company meet its own revised date? |
| MB0531 | open300:A14-06 | stock | Hinglish | partial | primary 3 | Polycab ne Q1FY27 mein 3.2 billion capex kiya — annual plan se aage ya peeche? (Hinglish) |
| MB0532 | open300:A14-07 | stock | natural | partial | primary 3 | HAL's order book is about Rs 2.54 lakh crore. What revenue cover is that, and did management guide to converting it faster? |
| MB0533 | open300:A14-08 | stock | natural | partial | primary 3 | RVNL's Q1 FY27 order inflow was Rs 5,417 crore. How does that compare with its annual revenue, and what does it imply for FY27? |
| MB0534 | open300:A14-09 | stock | point-in-time | partial | primary 3 | Texrail's order book is Rs 9,923 crore as of 30 June 2026. What is the execution period, and is it enough to meet guidance? |
| MB0535 | open300:A14-10 | stock | natural | partial | primary 3 | UltraTech's volume growth and capacity additions: did the FY26 additions land on the guided date? |
| MB0536 | open300:A14-11 | stock | terse | partial | primary 3 | IRCTC payment aggregator licence status Oct 2026 |
| MB0537 | open300:A14-12 | stock | natural | partial | primary 3 | Cochin Shipyard targeted the ISRF JV before the end of the financial year. Has the JV been signed, and what would confirm it? |
| MB0538 | open300:A14-13 | stock | natural | partial | primary 3 | Adani Green claimed a 20 GW renewable milestone in Q1 FY27. What was the previous milestone, and how long did the last 5 GW take? |
| MB0539 | open300:A14-14 | stock | natural | partial | primary 3 | Jubilant FoodWorks has about 3,600 stores. Did store additions hit the number it guided last year? |
| MB0540 | open300:A14-15 | stock | natural | partial | primary 3 | SAIL advanced capital repairs into Q1 FY27 to free up later quarters. Did the later quarters show the output recovery it implied? |
| MB0541 | open300:A15-01 | stock | natural | partial | primary 2 | RVNL's order inflow in Q1 FY27 was Rs 5,417 crore. What is its order book cover in years, and how much of the book is slow-moving? |
| MB0542 | open300:A15-02 | stock | natural | partial | primary 2 | Inside HAL's Rs 2.54 lakh-crore book: which platforms dominate, and how many years of revenue does the mix imply? |
| MB0543 | open300:A15-03 | stock | natural | partial | primary 2 | Texrail's order book is Rs 9,923 crore. How much is wagons versus leasing, and which part is recurring? |
| MB0544 | open300:A15-04 | stock | natural | partial | primary 2 | BEL is waiting for CCS approval on QRSAM. Is that order already in the order book, and what happens to cover when it lands? |
| MB0545 | open300:A15-05 | stock | natural | partial | primary 2 | Mazagon Dock's order book: how much is shipbuilding versus repairs, and which is more stable? |
| MB0546 | open300:A15-06 | stock | natural | partial | primary 2 | Cochin Shipyard has an ISRF JV pipeline alongside its order book. How do you separate firm orders from JV optionality? |
| MB0547 | open300:A15-07 | stock | natural | partial | primary 2 | Ircon's order book: how much is the new dedicated-freight-corridor work, and has any of it been awarded? |
| MB0548 | open300:A15-08 | stock | natural | partial | primary 2 | Rites' order book has been falling. Why, and what does management say about the pipeline? |
| MB0549 | open300:A15-09 | stock | terse | partial | primary 2 | KEC T&D book-to-bill FY27 |
| MB0550 | open300:A15-10 | industry | Hinglish | partial | primary 2 | HG Infra ke order book mein EPC vs HAM kitna hai? (Hinglish) |
| MB0551 | open300:A15-11 | stock | natural | partial | primary 2 | Titagarh's wagon order book versus its 1,200/month capacity: at current orders, how many months of work is booked? |
| MB0552 | open300:A15-12 | stock | natural | partial | primary 2 | Afcons' order book includes the MAHSR C2 package. What share is under execution, and what does the TBM status say about it? |
| MB0553 | open300:A15-13 | stock | natural | partial | primary 2 | NBCC's PMC order book is large but its receivables are old. How do you judge whether the book is worth its face value? |
| MB0554 | open300:A15-14 | stock | natural | partial | primary 2 | GR Infra's order book and margin guidance: does the book mix support the guided margin? |
| MB0555 | open300:A15-15 | stock | Hinglish | partial | primary 2 | PNC Infratech's HAM assets are up for monetisation. Kaise order book se asset sale alag hai? (Hinglish) |

### Family 13 - Inverse screen (15 primary cases)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0361 | open300:A03-01 | market-wide | Hinglish | partial | - | Konsi companies ne FY27 ke liye EBITDA margin recovery ka guidance diya hai, aur har ek ka evidence kya hai? (Hinglish) |
| MB0362 | open300:A03-02 | industry | terse | partial | - | Q1FY27 price hikes — cables, paints, steel |
| MB0363 | open300:A03-03 | market-wide | natural | partial | - | Which managements said a plant or line goes live in H2 FY27? terse: H2FY27 commissioning list |
| MB0364 | open300:A03-04 | market-wide | natural | partial | - | Which companies described demand as weak or below plan in Q1 FY27, and which described it as strong? Give both lists. |
| MB0365 | open300:A03-05 | market-wide | natural | partial | - | Which managements said working capital or receivables from government clients worsened last quarter? |
| MB0366 | open300:A03-06 | market-wide | natural | partial | - | Which companies announced fresh orders above Rs 1,000 crore in Q1 FY27? Include the order value and the period of execution. |
| MB0367 | open300:A03-07 | market-cap bucket | Hinglish | partial | - | Kaunsi mid-caps ne FY27 ke liye 20% se zyada revenue growth guide kiya hai? (Hinglish) |
| MB0368 | open300:A03-08 | market-wide | natural | partial | - | Which managements said they are evaluating acquisitions or inorganic growth, and which have actually signed something? |
| MB0369 | open300:A03-09 | market-wide | natural | partial | - | Which companies flagged input-cost inflation in Q1 FY27, and which input did each name? |
| MB0370 | open300:A03-10 | market-wide | Hinglish | partial | - | Kaunsi company ne FY26 mein buyback ya special dividend announce kiya? Date aur amount ke saath batao. (Hinglish) |
| MB0371 | open300:A03-11 | market-wide | natural | partial | - | Which companies said their order book covers more than two years of revenue? Give the cover multiple you computed. |
| MB0372 | open300:A03-12 | market-wide | natural | partial | - | Which managements said they will reduce net debt this financial year, and by how much? |
| MB0373 | open300:A03-13 | market-wide | natural | partial | - | Which companies said export demand recovered in the last two quarters, and which markets did they name? |
| MB0374 | open300:A03-14 | market-wide | natural | partial | - | Which companies claimed capacity-utilisation improvement last quarter, and which gave the utilisation number? |
| MB0375 | open300:A03-15 | market-wide | Hinglish | partial | - | Which managements said margin has bottomed and expect recovery next quarter? Kaun si companies ne bottom bola? (Hinglish) |

### Family 14 - Governance and audit (60 primary cases)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0376 | open300:A04-01 | stock | natural | partial | - | What was the auditor's opinion on Reliance's latest quarterly results, and was it modified in any way? |
| MB0377 | open300:A04-02 | stock | natural | partial | - | Tata Steel's Q1 FY27 filing: did it carry an audit qualification, and what exactly does the stored field say? |
| MB0378 | open300:A04-03 | market-cap bucket | natural | partial | - | Which companies filed a 'Statement on impact of audit qualification' with their latest results? How many, and which large caps? |
| MB0379 | open300:A04-04 | stock | natural | yes | - | Yes Bank's latest quarter: what auditor opinion was filed, and is this an audited period? |
| MB0380 | open300:A04-05 | stock | Hinglish | yes | - | Mankind ki subsidiary mein auditor resignation kab hui, aur kya file hua? (Hinglish) |
| MB0381 | open300:A04-06 | stock | natural | partial | - | Milefur's statutory auditor resigned. When was it filed, and what reason was given? |
| MB0382 | open300:A04-07 | stock | natural | yes | - | Picturehouse's secretarial auditor resigned. Who was the firm and when did the filing land? |
| MB0383 | open300:A04-08 | market-cap bucket | natural | no | - | Is there any going-concern doubt flagged in the latest quarterly results of small caps? terse: going concern Q1FY27 |
| MB0384 | open300:A04-09 | market-wide | terse | no | - | emphasis-of-matter paragraphs in latest results filings |
| MB0385 | open300:A04-10 | stock | natural | partial | - | What were HDFC Bank's key audit matters in its latest annual report, and did any repeat? |
| MB0386 | open300:A04-11 | stock | terse | partial | - | Suzlon's latest results: what did the auditor's declaration say? |
| MB0387 | open300:A04-12 | stock | natural | partial | - | For Reliance and Tata Steel, do the standalone and consolidated filings carry the same auditor declaration in Q1 FY27? |
| MB0388 | open300:A04-13 | stock | natural | partial | - | What did the latest annual report say about auditor remuneration, and how fast is it rising? |
| MB0389 | open300:A04-14 | market-wide | natural | partial | - | Which companies have filed a 'Declaration of unmodified opinion' for every quarter in the last four quarters? |
| MB0390 | open300:A04-15 | stock | natural | partial | - | Titagarh's Q1 FY27 results: opinion declared, and does it match what the results notes say? |
| MB0391 | open300:A05-01 | market-wide | natural | partial | - | List the statutory auditor resignations filed in September 2026, with company and date. terse: auditor resignation Sep 2026 |
| MB0392 | open300:A05-02 | market-wide | natural | yes | - | How many auditor-resignation and auditor-appointment filings are in the announcement store, and what does the gap between them say? |
| MB0393 | open300:A05-03 | stock | natural | partial | - | Kaynes Technology filed a 'Change in Management' on 13 May 2026. Who changed, in what role, and when did it take effect? |
| MB0394 | open300:A05-04 | market-wide | terse | partial | - | CFO churn 2024-2026 listed companies |
| MB0395 | open300:A05-05 | stock | Hinglish | partial | - | TruAlt ke promoter ne kab pledge banaya, aur kitne shares ka? (Hinglish) |
| MB0396 | open300:A05-06 | market-wide | natural | partial | - | Which company appointed an auditor to a casual vacancy in the last quarter, and whose resignation created it? |
| MB0397 | open300:A05-07 | stock | natural | yes | - | Welcorp filed an intimation about its credit rating. Who took the action and when was the press release issued? |
| MB0398 | open300:A05-08 | market-wide | natural | partial | - | Which companies disclosed a SEBI penalty or show-cause notice in Q2 FY27, and what was the amount? |
| MB0399 | open300:A05-09 | market-wide | natural | partial | - | Which companies disclosed GST or income-tax demand notices in the last quarter, and were they material? |
| MB0400 | open300:A05-10 | market-wide | natural | partial | - | Which companies filed a director resignation in September 2026, and did any cite a reason? |
| MB0401 | open300:A05-11 | stock | natural | no | - | What is TruAlt's promoter pledge as a percentage of promoter holding in the latest quarter? terse: TRUALT pledge % |
| MB0402 | open300:A05-12 | market-wide | natural | no | - | Cluster of insider buying in Sep-Oct 2026: which promoters or KMPs bought, and how much? terse: insider buys Sep-Oct 2026 |
| MB0403 | open300:A05-13 | stock | natural | yes | - | On 23 October 2026 Cyient saw a large bulk deal. Who sold, at what price, and how did the stock react? |
| MB0404 | open300:A05-14 | market-wide | natural | partial | - | Did any company's auditor resign within a year of a qualified opinion? Name the company and the two dates. |
| MB0405 | open300:A05-15 | market-wide | Hinglish | partial | - | Did any auditor resign citing 'other commitments' or lack of time in the last year? Kaun sa auditor ne reason diya? (Hinglish) |
| MB0406 | open300:A06-01 | market-wide | natural | partial | - | Which promoters created a fresh pledge over their shares between August and September 2026, and which were top-ups on an existing pledge? |
| MB0407 | open300:A06-02 | market-wide | natural | partial | - | Which Q2 FY27 results notes disclose a related-party transaction that grew sharply year on year? |
| MB0408 | open300:A06-03 | market-wide | natural | partial | - | Which companies show receivables growing much faster than revenue in the last reported year? |
| MB0409 | open300:A06-04 | market-wide | natural | partial | - | Which companies disclosed a tax or regulatory demand in Q2 FY27 that is large relative to their profit? |
| MB0410 | open300:A06-05 | stock | natural | partial | - | Welcorp disclosed a credit-rating intimation in October 2026. Was it an upgrade, a downgrade or a review, and how would you tell? |
| MB0411 | open300:A06-06 | market-wide | natural | partial | - | Which companies wrote down inventory or took an impairment in Q1 FY27, and how large was it against EBITDA? |
| MB0412 | open300:A06-07 | market-wide | natural | partial | - | Which segment of which company swung from profit to loss last quarter, while the company reported a profit overall? |
| MB0413 | open300:A06-08 | market-wide | natural | partial | - | Which companies have operating cash flow persistently below reported profit, and for how many years? |
| MB0414 | open300:A06-09 | market-wide | Hinglish | partial | - | Kisi company ne debt covenant breach ya restructuring disclose kiya kya? (Hinglish) |
| MB0415 | open300:A06-10 | market-wide | natural | partial | - | Which companies disclosed a plant shutdown or force majeure in the last quarter, and what did they say the financial effect was? |
| MB0416 | open300:A06-11 | price band | natural | no | - | Which companies are in a 5% or lower price band on results day, and did the band change before the announcement? |
| MB0417 | open300:A06-12 | market-wide | terse | partial | - | Q1FY27 audit-qualification statements — how many |
| MB0418 | open300:A06-13 | market-wide | natural | partial | - | Which companies' results notes mention a related-party loan or advance to a promoter-group entity? |
| MB0419 | open300:A06-14 | market-wide | natural | partial | - | Which company changed its statutory auditor twice in three years, and is that a red flag here? |
| MB0420 | open300:A06-15 | market-wide | natural | no | - | Promoter selling before results: which companies show it in the last two quarters? terse: promoter sale before results |
| MB0881 | reddit200:RD-I-051 | stock | natural | partial | - | Vedanta: how has promoter pledge moved over the last four quarters, and does the dividend policy depend on it? |
| MB0882 | reddit200:RD-I-052 | stock | natural | partial | - | Jaiprakash Power: is the promoter pledge rising alongside the debt, and what did the auditor say about going concern? |
| MB0883 | reddit200:RD-I-053 | stock | natural | yes | - | Vodafone Idea: did the promoter group raise its stake through the preferential issue, and what did that do to the free float? |
| MB0884 | reddit200:RD-I-054 | stock | natural | partial | - | IRB Infrastructure: has promoter pledge fallen with the asset monetisation, and how much of the debt is now at the holdco? |
| MB0885 | reddit200:RD-I-055 | market-cap bucket | natural | partial | - | Which large-cap had the biggest promoter stake sale in the last year, and did the stock absorb it? |
| MB0921 | reddit200:RD-N-016 | stock | natural | partial | - | Adani Enterprises: do receivables and inventory growth run ahead of revenue, and what does the cash-conversion ratio say? |
| MB0922 | reddit200:RD-N-017 | stock | natural | partial | - | Vedanta: the parent pays dividends while carrying debt. Is the cash actually upstreamed from subsidiaries, and what do the related-party notes say? |
| MB0923 | reddit200:RD-N-018 | stock | natural | partial | - | Vodafone Idea: how are the spectrum liabilities accounted for, and do the interest and amortisation assumptions flatter the loss? |
| MB0924 | reddit200:RD-N-019 | stock | natural | partial | - | Reliance Power: how much of the balance sheet is CWIP and capitalised interest, and when does it start depreciating? |
| MB0925 | reddit200:RD-N-020 | stock | natural | partial | - | Yes Bank: are provisions keeping pace with the stressed book, and how much of the recovery is write-back rather than operating profit? |
| MB0951 | reddit200:RD-N-046 | stock | natural | partial | - | Vedanta: how much debt matures in the next two years, and can dividends plus cash cover it without asset sales? |
| MB0952 | reddit200:RD-N-047 | stock | natural | partial | - | Vodafone Idea: can operating cash flow cover interest and spectrum instalments, or is another capital raise certain? |
| MB0953 | reddit200:RD-N-048 | stock | natural | partial | - | Jaiprakash Power: has the debt actually fallen, or has it been moved into CWIP and JVs? |
| MB0954 | reddit200:RD-N-049 | stock | natural | partial | - | Adani Green: what is net debt to EBITDA, and how is the capex funded if the refinancing window narrows? |
| MB0955 | reddit200:RD-N-050 | stock | natural | partial | - | IRB Infrastructure: how much of the leverage sits at the holdco, and what did asset monetisation actually repay? |

### Family 15 - Market move -> why (35 primary cases)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0421 | open300:A07-01 | market-wide | natural | partial | - | On 4 June 2024 the Nifty 50 fell 5.93%. What was the sector dispersion that day, and what kind of market move was it? |
| MB0422 | open300:A07-02 | market-wide | Hinglish | yes | - | 4 June 2024 wale hafte mein Nifty ka move kya tha, aur ek din ka number kaafi hai? (Hinglish) |
| MB0423 | open300:A07-03 | market-wide | natural | partial | - | On 4 June 2024, Nifty PSU Bank fell 15.14% while Nifty FMCG rose 0.95%. What does that pair tell you about positioning? |
| MB0424 | open300:A07-04 | market-wide | terse | partial | - | 4 Jun 2024 top losers, turnover floor applied |
| MB0425 | open300:A07-05 | market-wide | natural | partial | - | The Union Budget 2026-27 was presented on Sunday 1 February 2026. What did the Nifty 50 do on the first trading session after it? |
| MB0426 | open300:A07-06 | market-wide | natural | yes | - | What did the Nifty 50 do on the first session after the 2025-26 Budget on Saturday 1 February 2025? |
| MB0427 | open300:A07-07 | market-wide | natural | partial | - | On 23 March 2020 the Nifty 50 fell 12.98%. What evidence in the store dates the cause, and what is NOT in the store? |
| MB0428 | open300:A07-08 | market-wide | natural | partial | - | On 1 February 2021 the Nifty 50 rose 4.74%. Which policy lines in the store were published around that date, and do they explain it? |
| MB0429 | open300:A07-09 | market-wide | natural | partial | - | On 24 February 2022 the Nifty 50 fell 4.78%. What was happening in crude, and does the crude move support a geopolitical read? |
| MB0430 | open300:A07-10 | market-wide | natural | partial | - | On 24 September 2026 the Nifty 50 fell 1.64% but PB Fintech fell 36%. Was this a market move or a stock event? |
| MB0431 | open300:A07-11 | market-wide | natural | partial | - | On 7 April 2025 the Nifty 50 fell 3.24%. Which stored policy event is closest, and does the date match? |
| MB0432 | open300:A07-12 | market-wide | natural | partial | - | The RBI hiked the repo rate 25 bps to 5.50% on 7 October 2026. Did the Nifty 50 or the rate-sensitive indices move that day, and can the day's move be separated from the ... |
| MB0433 | open300:A07-13 | market-wide | natural | yes | - | On 23 October 2026 FIIs bought and DIIs bought much more. Who absorbed the supply, and did the index fall anyway? |
| MB0434 | open300:A07-14 | market-wide | natural | yes | - | For September 2026, what were the aggregate FII and DII cash flows, and how many sessions are they based on? |
| MB0435 | open300:A07-15 | market-wide | Hinglish | partial | - | On 4 June 2024 the Nifty IT fell only 0.6% while Nifty Energy fell 12.47%. Kaun sa sector sabse zyada gira, aur kyun? (Hinglish) |
| MB0436 | open300:A08-01 | stock | natural | yes | - | Siemens fell 42.93% on 7 April 2025. Was that a real loss of value? Explain with the corporate-action record. |
| MB0437 | open300:A08-02 | stock | natural | partial | - | PB Fintech fell 36% on 24 September 2026. What was scheduled that day, and what did the exchange ask for afterwards? |
| MB0438 | open300:A08-03 | stock | natural | partial | - | Kaynes fell 20.15% on 14 May 2026. What did the company file the previous evening, and what else was in that filing batch? |
| MB0439 | open300:A08-04 | stock | natural | partial | - | Trent fell 14.77% on 7 April 2025. Was there a company disclosure before the open, and what kind of update was it? |
| MB0440 | open300:A08-05 | industry | natural | partial | - | REC Ltd and PFC both fell more than 23% on 4 June 2024 with no company filing that day. What explains a move of that size in a lender? |
| MB0441 | open300:A08-06 | stock | terse | yes | - | BHEL 4 Jun 2024 volume and delivery |
| MB0442 | open300:A08-07 | stock | natural | yes | - | Adani Ports fell 21.15% on 4 June 2024. How does that compare with the Nifty 50 and what does the delivery data add? |
| MB0443 | open300:A08-08 | stock | natural | yes | - | SAIL fell 20.02% on 4 June 2024 and Nifty Metal fell 10.63%. What share of the stock move is explained by the sector? |
| MB0444 | open300:A08-09 | stock | natural | partial | - | Suzlon fell 9.65% on 28 July 2026 and the results were filed at 15:11 that day. What is the correct event window? |
| MB0445 | open300:A08-10 | stock | natural | partial | - | Bharat Electronics fell 4.46% on 28 July 2026, the session after its results. Was the market reaction consistent with the numbers? |
| MB0446 | open300:A08-11 | stock | natural | yes | - | Mankind Pharma fell 4.13% on 31 July 2026 after results the previous evening. What two filings should you check before calling it a results reaction? |
| MB0447 | open300:A08-12 | stock | natural | partial | - | KEI rose 9.49% on 4 August 2026 after results filed at 20:52 on 3 August. What did the numbers say about margin? |
| MB0448 | open300:A08-13 | stock | natural | yes | - | Polycab fell 3.83% on 17 July 2026, the day after results filed at 15:59. What was the actual reaction window? |
| MB0449 | open300:A08-14 | stock | natural | yes | - | Titagarh rose 2.06% on 13 August 2026 after results the previous evening. Was the reaction large relative to its own volatility? |
| MB0450 | open300:A08-15 | stock | Hinglish | yes | - | Dixon fell 2.02% on 31 July 2026 but the results were filed at 18:12, after the close. Kaun sa din ka move actually the reaction hai? (Hinglish) |
| MB0861 | reddit200:RD-I-031 | stock | natural | partial | - | Why did Reliance fall on 4 June 2024, and which of that morning's inputs were actually known before the open? |
| MB0862 | reddit200:RD-I-032 | stock | natural | partial | - | HDFC Bank jumped after its Q2FY26 result. Was the move in the numbers, the guidance, or the pre-result positioning? |
| MB0863 | reddit200:RD-I-033 | industry | natural | partial | - | Why did Adani Power move 8% on a day when the power index was flat? |
| MB0864 | reddit200:RD-I-034 | stock | natural | partial | - | Infosys fell despite a revenue beat. Did the market react to margins, guidance, or the dollar-rupee assumption? |
| MB0865 | reddit200:RD-I-035 | stock | natural | yes | - | Tata Motors moved sharply around the demerger record date. How much of the move was the mechanical price adjustment? |

### Family 16 - Input-cost / commodity transmission (135 primary cases)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0451 | open300:A09-01 | stock | natural | partial | - | Copper went from 5.0875 on 20 May 2024 to 6.559 on 30 September 2026. How would that hit a cable maker's margin, and what has actually happened to KEI's margin? |
| MB0452 | open300:A09-02 | industry | natural | partial | - | What share of a cable maker's raw-material cost is copper, and where in the filing is it stated? |
| MB0453 | open300:A09-03 | industry | natural | partial | - | Copper is up about 29% from May 2024. Does that help Hindustan Copper more than it hurts the cable makers, and why? |
| MB0454 | open300:A09-04 | industry | Hinglish | partial | - | Brent was 99.08 on 24 February 2022 and 103.53 on 30 September 2026. Kaise crude ka asar paint companies ke margin par padta hai? (Hinglish) |
| MB0455 | open300:A09-05 | stock | natural | partial | - | How much of an airline's cost is fuel, and what does a $4 move in Brent do to IndiGo's EBITDA? |
| MB0456 | open300:A09-06 | industry | natural | partial | - | Crude at $103 should hurt tyre makers through carbon black and synthetic rubber. Which listed tyre company is most exposed, and what does the AR say? |
| MB0457 | open300:A09-07 | stock | natural | partial | - | Crude at $103: what happens to the oil marketing companies' marketing margin, and what did IOC or BPCL say about under-recovery? |
| MB0458 | open300:A09-08 | stock | natural | no | - | Coal is a fuel input for NTPC and Tata Power. The coal series ends in December 2025; can you still answer a 2026 coal-cost question? |
| MB0459 | open300:A09-09 | industry | Hinglish | partial | - | US HRC 1,275 hai — Indian tube maker ke liye kaun sa price matter karta hai? (Hinglish) |
| MB0460 | open300:A09-10 | industry | Hinglish | partial | - | Gold was 2,028 on 7 August 2020 and 4,186.7 on 30 September 2026. Kaun jeetta hai—jeweller ya gold-loan NBFC? (Hinglish) |
| MB0461 | open300:A09-11 | industry | natural | partial | - | Aluminium was 3,285 on 30 September 2026. Who gains and who loses among Hindalco, Vedanta and a downstream user? |
| MB0462 | open300:A09-12 | stock | terse | partial | - | iron ore series — SAIL and JINDALSTEL 2026 margin |
| MB0463 | open300:A09-13 | industry | natural | partial | - | Natural gas was 3.026 on 30 September 2026. What does that do to a urea maker's cost, given administered prices? |
| MB0464 | open300:A09-14 | industry | natural | partial | - | Copper is also an input for switchgear and transformers. Does the SIEMENS/ABB margin tell the same story as the cable makers'? |
| MB0465 | open300:A09-15 | industry | natural | partial | - | A copper spike hits cable makers, who sell to EPC contractors on fixed-price contracts. Who eats the loss, and how do you prove it? |
| MB0466 | open300:A10-01 | sector | natural | partial | - | The rupee went from 81.48 on 30 September 2022 to 96.05 on 30 September 2026. Which listed exporters gained most, and how do you measure it? |
| MB0467 | open300:A10-02 | industry | natural | partial | - | Rupee depreciation helps Infosys but hurts importers. For a pharma exporter, what are the two opposing channels? |
| MB0468 | open300:A10-03 | industry | natural | partial | - | Rupee at 96 puts pressure on a paint company that imports crude derivatives. How would you show it in the numbers? |
| MB0469 | open300:A10-04 | policy | natural | partial | - | RBI raised the repo by 50bp to 5.9% on 30 September 2022. What does that do to a vehicle-finance NBFC's spread, and how fast? |
| MB0470 | open300:A10-05 | policy | Hinglish | partial | - | RBI ne 1 Oct 2025 ko repo hold kiya — HFC margins par kya asar, aur market ne cut price kiya tha? (Hinglish) |
| MB0471 | open300:A10-06 | industry | natural | partial | - | Repo cuts are supposed to help realty. What is the actual channel from repo to a DLF or Prestige sale, and how many steps are there? |
| MB0472 | open300:A10-07 | stock | natural | partial | - | A rate cut compresses a bank's NIM but lifts loan growth. For HDFC Bank, which effect dominated last cycle, and what does the disclosure say? |
| MB0473 | open300:A10-08 | stock | natural | partial | - | Muthoot's cost of funds rises with the repo. How does that interact with the gold-loan yield cap, and who bears it? |
| MB0474 | open300:A10-09 | stock | natural | partial | - | A weaker rupee raises an airline's dollar costs. What are the two biggest USD cost lines for IndiGo, and how are they disclosed? |
| MB0475 | open300:A10-10 | stock | natural | partial | - | Shipping earns in dollars and spends partly in rupees. What does rupee depreciation do to SCI's margin? |
| MB0476 | open300:A10-11 | industry | natural | partial | - | For a life insurer, what do higher rates do to the embedded value, and does that show up in the disclosures? |
| MB0477 | open300:A10-12 | stock | natural | partial | - | Repo up 250bp over two years: how would an auto-finance NBFC's spread move, and what does Bajaj Finance's disclosure show? |
| MB0478 | open300:A10-13 | stock | natural | partial | - | Rupee at 96 for an electronics manufacturer that imports components: what does it do to Dixon's margin and what is the hedge? |
| MB0479 | open300:A10-14 | stock | Hinglish | partial | - | IRFC lends to Indian Railways at fixed spreads funded by bonds. Kaise rate cut se uski profitability badalti hai? (Hinglish) |
| MB0480 | open300:A10-15 | stock | terse | partial | - | KPITTECH rupee depreciation margin impact |
| MB0601 | open300:A19-01 | sector | natural | partial | 18 | If the monsoon fails, which listed sectors are most exposed, and in what order would the effect show up? |
| MB0602 | open300:A19-02 | sector | natural | partial | 18 | Crude is already at 103.53 on 30 September 2026. If it holds, which listed sectors lose most, and which gain? |
| MB0603 | open300:A19-03 | policy | natural | partial | 18 | If US tariffs rise another 25 points, which listed exporters are most exposed, and what would you check first? |
| MB0604 | open300:A19-04 | sector | natural | partial | 18 | If the rupee goes to 100, who wins and who loses among listed companies? Give both sides with a channel each. |
| MB0605 | open300:A19-05 | industry | natural | partial | 18 | Gold is 4,186.7. If it goes to 5,000, do jewellers or gold-loan NBFCs do better, and why is the answer not obvious? |
| MB0606 | open300:A19-06 | sector | terse | no | 18 | coal scarcity FY27 — which sectors, answerable? |
| MB0607 | open300:A19-07 | policy | natural | partial | 18 | If the FY27 public capex of Rs 12.2 lakh crore is spent as budgeted, which listed sectors see it first, which later, and who loses? |
| MB0608 | open300:A19-08 | policy | natural | partial | 18 | If the semiconductor incentive doubles, which listed companies benefit first and which only in the second round? |
| MB0609 | open300:A19-09 | policy | natural | partial | 18 | If the RBI cuts 100bp over a year, which listed sectors re-rate first, and what breaks the chain? |
| MB0610 | open300:A19-10 | theme | natural | partial | 18 | If data-centre capex doubles, which listed companies see it first, and is the exposure measurable? |
| MB0611 | open300:A19-11 | theme | natural | partial | 18 | If EV penetration hits 30%, which listed auto-component names lose and which gain? Give both sides. |
| MB0612 | open300:A19-12 | sector | natural | partial | 18 | If China+1 accelerates, which listed sectors win, and what is the first evidence you would look for? |
| MB0613 | open300:A19-13 | sector | natural | partial | 18 | If container freight rates spike, which listed exporters lose and does a shipping line gain? |
| MB0614 | open300:A19-14 | policy | natural | partial | 18 | If GST rates are cut on consumer durables, who gains more: a durables maker or an FMCG company? |
| MB0615 | open300:A19-15 | sector | Hinglish | partial | 18 | Agar crude $100 ho jaye to kaunse listed sectors sabse zyada peedit honge? (Hinglish) |
| MB0631 | ripple200:R01-01 | industry | natural | partial | - | Copper rises 20% in a quarter. Trace it through cable makers' COGS, the timing of the dealer price hike, and the fixed-price EPC contracts downstream. Which listed EPC na... |
| MB0632 | ripple200:R01-02 | industry | natural | no | - | Natural rubber and crude-based inputs rise together. How long before tyre makers' replacement-market price hikes reach the OEMs, and what does the OEM's own cost per vehi... |
| MB0633 | ripple200:R01-03 | industry | natural | no | - | Steel HRC rises 15%. Auto ancillaries have annual price agreements with OEMs and quarterly raw-material indexation. Where does the margin land for the forging and stampin... |
| MB0634 | ripple200:R01-04 | industry | natural | partial | - | Aluminium rises and the rupee weakens in the same quarter. Conductors and switchgear get dearer, the transmission capex programme is already sanctioned, and the discoms m... |
| MB0635 | ripple200:R01-05 | industry | natural | partial | - | Coking coal rises. Steel mills raise HRC, construction cost rises, and highway EPC contracts are awarded on a fixed-price basis with a steel escalation clause for bridges... |
| MB0636 | ripple200:R01-06 | industry | natural | partial | - | Crude rises 20%. Paints pass it on to dealers with a lag, dealers stop restocking, and the volume effect arrives after the margin effect. What is the sequence in the quar... |
| MB0637 | ripple200:R01-07 | stock | natural | no | - | Edible-oil and crude-linked packaging costs rise into a weak rural quarter. Hindustan Unilever and the personal-care names face a cost push and a demand pull in opposite ... |
| MB0638 | ripple200:R01-08 | industry | natural | no | - | Gas and ammonia prices rise. Urea makers' cost goes up but the retail price is controlled, so the subsidy bill rises instead. Trace that to farm income, then to tractor a... |
| MB0639 | ripple200:R01-09 | industry | natural | no | - | Cotton rises 25% while the rupee weakens. Spinners' yarn price rises, garment exporters' FOB price rises, and the EU buyer has an alternative in Bangladesh. Which hop bre... |
| MB0640 | ripple200:R01-10 | industry | natural | partial | - | Gold rises 20%. The jeweller's inventory gains in value, the customer delays purchase, and the working-capital line grows at the same time. Which of those three hits the ... |
| MB0641 | ripple200:R01-11 | industry | natural | partial | - | Iron-ore fines rise after a mining-lease disruption. Pellet and sponge-iron makers reprice first, the integrated mills later, and the downstream steel-products makers las... |
| MB0642 | ripple200:R01-12 | industry | natural | partial | - | Coal and freight rise while power demand peaks. The generator's tariff is regulated, the aluminium smelter's power cost is not. Which listed smelter's margin moves first,... |
| MB0643 | ripple200:R01-13 | industry | natural | partial | - | Soda ash and energy rise. Consumer-glass and industrial-glass makers face a cost push, and their customers are FMCG and construction. Which glass maker can pass it on and... |
| MB0644 | ripple200:R01-14 | industry | natural | partial | - | Pulp and waste-paper prices rise. Paper makers reprice, packaging converters absorb it, and the FMCG buyer renegotiates the carton contract. Who is squeezed in the middle... |
| MB0645 | ripple200:R01-15 | industry | natural | no | - | Chinese intermediate prices drop and then rebound. Indian specialty-chemical makers had cut output at the low. Trace the margin recovery, the restocking by agrochemical f... |
| MB0646 | ripple200:R01-16 | industry | natural | partial | - | Sugar and ethanol compete for the same cane. A higher ethanol blending price pulls cane into ethanol, sugar output falls, the sugar price rises, and the OMC's blending co... |
| MB0647 | ripple200:R01-17 | market-cap bucket | natural | no | - | Container freight doubles and transit time stretches. Importers of components hold more inventory, the cash cycle lengthens, and short-term debt rises. Which listed mid-c... |
| MB0648 | ripple200:R01-18 | industry | natural | no | - | Carbon black and rubber chemicals rise into a weak CV cycle. Tyre replacement demand tracks freight movement, and CV makers' volumes follow freight rates with a lag. Whic... |
| MB0649 | ripple200:R01-19 | industry | natural | partial | - | Pet coke and limestone rise while cement demand is soft. The large players hold price, the regional players cut. Which listed regional producer's margin breaks first, and... |
| MB0650 | ripple200:R01-20 | industry | natural | no | - | Copper, steel and freight all rise in one year. Transformer and switchgear makers sit between a metals index and a discom order book. Which listed equipment maker has ind... |
| MB0671 | ripple200:R03-01 | policy | natural | partial | - | The repo goes up 25 bps. Split the loan book into EBLR, MCLR and fixed, split the deposit book into savings and term, and compute which bank's NIM falls first. The answer... |
| MB0672 | ripple200:R03-02 | policy | natural | partial | - | The 2025 rate cuts reach the NBFC's cost of funds with a lag, but its AUM growth needs a credit cycle, not a rate cut. Trace the cost of funds, then the spread, then the ... |
| MB0673 | ripple200:R03-03 | industry | natural | partial | - | The rupee weakens 5% against the dollar. An IT services company earns in dollars and pays salaries in rupees, but also runs onsite staff paid in dollars and buys imported... |
| MB0674 | ripple200:R03-04 | industry | natural | partial | - | The rupee weakens. The pharma exporter earns more on the US business and pays more for imported APIs and intermediates. Which listed name is a net winner and which is a n... |
| MB0675 | ripple200:R03-05 | industry | natural | partial | - | The rupee weakens and a components importer sells to Indian OEMs in rupees. Trace the landed cost, then the price negotiation, then the OEM's own cost. Who absorbs the cu... |
| MB0676 | ripple200:R03-06 | market-cap bucket | natural | no | - | Build the screen: mid-caps with high import content, a long cash cycle and thin interest cover. Which names fail first if the rupee falls and working capital stretches at... |
| MB0677 | ripple200:R03-07 | industry | natural | partial | - | Household savings move from term deposits to mutual funds. Trace it to the bank's deposit mix, then to its NIM, then to the cost of the loan it can no longer fund cheaply... |
| MB0678 | ripple200:R03-08 | industry | natural | partial | - | Commercial paper rates spike. Trace it to the NBFC's borrowing mix, then to its spread, then to the borrower it has to turn away. Which lender funds itself most from the ... |
| MB0679 | ripple200:R03-09 | policy | natural | partial | - | Durable liquidity is injected on a large scale. Trace it to bank credit availability, then to corporate working-capital limits, then to the inventory a distributor can ca... |
| MB0680 | ripple200:R03-10 | policy | natural | partial | - | The central bank changes the CRR. Trace it to the bank's lendable resources, then to the marginal corporate loan price, then to the capex it enables. How much of a 50 bps... |
| MB0681 | ripple200:R03-11 | industry | natural | partial | - | Rates fall and the housing-finance company's spread compresses, but prepayments rise. Net the spread compression against the faster book turnover and say which listed HFC... |
| MB0682 | ripple200:R03-12 | policy | natural | partial | - | The repo goes up and car loans get dearer. Trace it to the EMI, then to the monthly payment at the entry price point, then to volumes for the entry segment versus the pre... |
| MB0683 | ripple200:R03-13 | industry | natural | partial | - | Rates fall and renewable developers bid lower tariffs. Trace it to the LCOE, then to the bid, then to the EPC margin and the module supplier. Which listed developer can b... |
| MB0684 | ripple200:R03-14 | industry | natural | no | - | A sugar mill's working capital is priced off a bank rate that just rose. Trace it to the cane payment schedule, then to the farmer's payment date, then to the next season... |
| MB0685 | ripple200:R03-15 | industry | natural | partial | - | The rupee weakens and a shipping line earns in dollars and pays charter hire in dollars. Does the weaker rupee help the reported profit at all, and what does the balance ... |
| MB0686 | ripple200:R03-16 | industry | natural | partial | - | The rupee weakens and DAP is imported. Trace it to the fertiliser subsidy, then to the fiscal cost, then to the subsidy payment delay and the company's receivables. Who c... |
| MB0687 | ripple200:R03-17 | industry | natural | partial | - | Gold is priced in dollars and the rupee weakens. Trace it to the jeweller's rupee cost, then to the retail price, then to the volume and the working capital. Which effect... |
| MB0688 | ripple200:R03-18 | industry | natural | partial | - | Long rates rise and the discount rate for a 20-year infrastructure asset moves. Trace it to the bid yield, then to the asset's book value, then to the developer's ability... |
| MB0689 | ripple200:R03-19 | industry | natural | partial | - | A steel distributor funds inventory with a bank line. Rates rise, prices fall, and the inventory is worth less than it cost. Trace the interest cost, then the inventory w... |
| MB0690 | ripple200:R03-20 | industry | natural | partial | - | The rupee weakens and an exporter with dollar receivables reports a translation gain. Trace it to the hedge book, then to the mark-to-market in other income, then to the ... |
| MB0691 | ripple200:R04-01 | industry | natural | no | 19 | A shipping route closes. Europe-bound Indian goods spend two extra weeks at sea, the buyer defers the programme, the exporter's finished stock piles up, and its export in... |
| MB0692 | ripple200:R04-02 | policy | natural | no | 19 | The US raises tariffs on steel and aluminium. Indian exporters lose the US premium, divert volume domestically, and the domestic HRC price falls. Trace it to the auto anc... |
| MB0693 | ripple200:R04-03 | industry | natural | no | 19 | Chinese producers dump surplus into India. Specialty-chemical ASPs fall, the domestic producer cuts output, and when the dumping stops the buyer has lost a qualified loca... |
| MB0694 | ripple200:R04-04 | policy | natural | partial | 19 | A tariff on generic drugs is announced for 2028. The US buyer front-loads inventory in 2027, the Indian exporter runs its plants flat out, and then the order stops. Trace... |
| MB0695 | ripple200:R04-05 | policy | natural | no | 19 | The EU brings in a carbon border adjustment on steel and aluminium. The Indian exporter's carbon cost enters the landed price, the EU buyer looks for a lower-carbon sourc... |
| MB0696 | ripple200:R04-06 | industry | natural | no | 19 | Edible-oil and fertiliser supply from the Black Sea is disrupted. Trace it to the packaged-food company's input, then to the price point, then to the rural consumer. Whic... |
| MB0697 | ripple200:R04-07 | industry | natural | no | 19 | A competitor country's garment industry is disrupted. EU and US buyers shift programmes to India, the exporter adds a shift, and cotton buying tightens. How far can the I... |
| MB0698 | ripple200:R04-08 | industry | natural | partial | 19 | Crude spikes and the retail price of petrol and diesel is not raised. Trace it to the refiner-marketer's under-recovery, then to the subsidy or the PSU's balance sheet, t... |
| MB0699 | ripple200:R04-09 | industry | natural | partial | 19 | Component export controls tighten. The Indian electronics assembler's BOM cost rises, the customer refuses a price rise, and the assembler has to localise faster than its... |
| MB0700 | ripple200:R04-10 | industry | natural | no | 19 | A trade partner opens an excess-capacity investigation. Trace it to the risk premium on Indian exports, then to the buyer's order timing, then to the exporter's capacity ... |
| MB0701 | ripple200:R04-11 | industry | natural | no | 19 | Two trade agreements pull in opposite directions: a US tariff raises the landed cost, an EU agreement lowers it. For the same exporter, which destination wins on margin, ... |
| MB0702 | ripple200:R04-12 | industry | natural | partial | 19 | Seaborne coal prices spike. The generator's fuel cost rises, the regulated tariff does not immediately, and the aluminium smelter buying from the exchange pays the mercha... |
| MB0703 | ripple200:R04-13 | industry | natural | no | 19 | LME copper jumps and a cable maker is holding inventory bought at the old price. The holding gain flatters the quarter, the dealer sees the new price list, and the order ... |
| MB0704 | ripple200:R04-14 | market-cap bucket | natural | no | 19 | Foreign investors sell. The mid-cap index falls, the planned QIP window closes, and a company that needed equity funds its capex with debt instead. Trace the sequence and... |
| MB0705 | ripple200:R04-15 | industry | natural | no | 19 | War-risk premia rise on a shipping route. Trace it to the charter rate, then to the importer's landed cost, then to the inventory decision. Which listed shipping name ben... |
| MB0706 | ripple200:R04-16 | industry | natural | no | 19 | Global rubber rises sharply. Traces it to the Indian tyre maker's cost, then to the replacement price, then to the truck operator's cost per km, then to the replacement i... |
| MB0707 | ripple200:R04-17 | industry | natural | partial | 19 | Gold rises in dollars and the rupee weakens in the same quarter. Trace it to the jeweller's landed cost, then to the wedding-season volume, then to the inventory the stor... |
| MB0708 | ripple200:R04-18 | stock | natural | no | 19 | A foreign strategic buyer takes a stake in an Indian listed company's competitor. Trace it to the competitor's capacity plan, then to the industry's price behaviour, then... |
| MB0709 | ripple200:R04-19 | industry | natural | no | 19 | A monsoon deficit hits fodder and water. Milk procurement falls, the dairy's procurement price rises, and the packaged-food buyer's cost follows. Trace it and say whether... |
| MB0710 | ripple200:R04-20 | policy | natural | no | 19 | The US raises the tariff on shrimp and the EU opens a quota. The Indian exporter's destination margin flips, the hatchery's order book follows, and the farmer decides the... |
| MB0771 | ripple200:R08-01 | industry | natural | partial | - | The rupee weakens. An aluminium producer exports metal priced in dollars and imports coal priced in dollars. Net the two legs by revenue and cost geography, and say which... |
| MB0772 | ripple200:R08-02 | policy | natural | partial | - | The repo is raised 25 bps. A bank's loan yield rises and its bond portfolio falls in value on the same day. Net the NIM gain against the treasury loss, and say which one ... |
| MB0773 | ripple200:R08-03 | industry | natural | partial | - | Copper rises. A cable maker's realisation rises with the metal, its working capital rises with the same metal, and its dealer may delay the order. Net the margin gain aga... |
| MB0774 | ripple200:R08-04 | industry | natural | partial | - | Crude rises. The refiner-marketer loses on the regulated retail sale and the upstream producer gains on the same barrel. If the two are the same group, is the group a net... |
| MB0775 | ripple200:R08-05 | policy | natural | partial | - | The US tariff goes up and the EU duty comes down. For one textile exporter, does the EU gain cover the US loss this year, or only next year? |
| MB0776 | ripple200:R08-06 | industry | natural | no | - | Freight rates double. A shipping line earns more on the voyage and pays more for the charter and the bunker. Net the two and say which share of the fleet is on a fixed ch... |
| MB0777 | ripple200:R08-07 | industry | natural | partial | - | Steel rises. The mill's revenue rises and its coking coal cost rises. Net the two and say which mill has captive coal or iron ore. |
| MB0778 | ripple200:R08-08 | policy | natural | partial | - | The repo is cut. A housing-finance company's spread narrows and its disbursements rise. Net the margin against the volume and say which HFC's return on equity actually im... |
| MB0779 | ripple200:R08-09 | industry | natural | partial | - | Gold rises. The jeweller's holding gain is real and its customer defers. Net the gain against the volume loss and say which one the auditor would let you book. |
| MB0780 | ripple200:R08-10 | policy | natural | no | - | An incentive scheme pays a subsidy per unit and the large player cuts the price by the same amount to win volume. Net the subsidy gain against the price cut and say who k... |
| MB0781 | ripple200:R08-11 | industry | natural | partial | - | The rupee weakens. An auto ancillary exports to Europe and imports components from China. Net the export gain against the import cost and say where the euro and the yuan ... |
| MB0782 | ripple200:R08-12 | industry | natural | no | - | Wage inflation rises. The consumer company's volume improves with the wage and its margin falls with the same wage. Net them and say which side is bigger for a labour-int... |
| MB0783 | ripple200:R08-13 | policy | natural | partial | - | A data-centre policy raises demand for the equipment maker and raises the power cost of its own factory. Net the order gain against the cost and say which one is bigger f... |
| MB0784 | ripple200:R08-14 | policy | natural | partial | - | A safeguard duty is imposed on steel. The mill's price rises and the auto ancillary's input rises. For a group that owns both a mill and an auto business, is the net posi... |
| MB0785 | ripple200:R08-15 | policy | natural | partial | - | Insurance FDI is opened. Capital and competition arrive together. Net the capital gain to the incumbent's stake against the compression of its underwriting margin. |
| MB0786 | ripple200:R08-16 | theme | natural | partial | - | Electric vehicles take share. The ancillary's engine-parts revenue falls and its EV-parts revenue rises. Net the two by product line and say which listed name has the wid... |
| MB0787 | ripple200:R08-17 | industry | natural | partial | - | Pet coke rises and cement demand rises at the same time. The producer's cost is up and its volume is up. Net the two and say which regional producer is best placed. |
| MB0788 | ripple200:R08-18 | policy | natural | partial | - | Coal gets dearer and the regulated tariff is revised at the same time. Net the fuel cost against the tariff order and say which generator gets the pass-through first. |
| MB0789 | ripple200:R08-19 | policy | natural | partial | - | A tariff on generic drugs raises the cost of the US business and lowers the relative cost of the Indian business. For a company with both, does the India margin rise or d... |
| MB0790 | ripple200:R08-20 | industry | natural | partial | - | An NBFC grows its AUM fast and its credit cost rises at the same time. Net growth against credit cost and say which listed lender's provisioning cycle is closest to turni... |
| MB0936 | reddit200:RD-N-031 | stock | natural | no | - | Hindalco: where are we in the aluminium cycle, and what is Novelis's cost position relative to the curve? |
| MB0937 | reddit200:RD-N-032 | stock | natural | partial | - | JSW Steel: what is capacity utilisation and steel spread now versus the last downcycle, and how fast does margin mean-revert? |
| MB0938 | reddit200:RD-N-033 | stock | natural | partial | - | Tata Chemicals: the soda ash cycle has turned. How much of the margin is cycle and how much is the company's cost advantage? |
| MB0939 | reddit200:RD-N-034 | stock | natural | partial | - | Deepak Nitrite: is the destocking over, and what do inventory days and realisation say about the next two quarters? |
| MB0940 | reddit200:RD-N-035 | stock | natural | partial | - | Ambuja Cements: is the cement cycle in a price war or a volume recovery, and what does cost per tonne say? |
| MB0941 | reddit200:RD-N-036 | stock | natural | partial | - | If the RBI cuts rates, what happens to HDFC Bank's NIM first and loan growth second, and how long is the lag? |
| MB0942 | reddit200:RD-N-037 | stock | natural | partial | - | Bajaj Finance: does a rate cut help or hurt the cost of funds before it helps AUM, and what does history say? |
| MB0943 | reddit200:RD-N-038 | industry | natural | partial | - | Crude fell sharply. How long before Asian Paints' raw-material cost falls, and what did it do last time? |
| MB0944 | reddit200:RD-N-039 | stock | natural | partial | - | The rupee weakened. How much of Infosys's margin gain is translation versus hedging, and when does it show? |
| MB0945 | reddit200:RD-N-040 | industry | natural | partial | - | Rubber and crude rose together. Which tyre maker has the fastest price pass-through, and how did the last spike play out? |

### Family 17 - Business economics (40 primary cases)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0481 | open300:A11-01 | industry | natural | partial | - | How do food-delivery fees affect a quick-commerce operator's profitability, and which line items move? |
| MB0482 | open300:A11-02 | theme | natural | partial | - | EV makers are discounting heavily. Which listed EV maker's margin is most exposed, and what does the disclosure say about discounting? |
| MB0483 | open300:A11-03 | stock | natural | partial | - | Brokers earn float income on client balances. How much of Angel One's revenue is float income, and what happens when rates fall? |
| MB0484 | open300:A11-04 | industry | natural | partial | - | A food-delivery platform raises its take rate by 100bp. Who pays, and how does that reach EBITDA? |
| MB0485 | open300:A11-05 | stock | natural | partial | - | Fuel is the largest variable cost for an airline. At what load factor does a marginal flight turn contribution-positive, and what does IndiGo disclose? |
| MB0486 | open300:A11-06 | stock | natural | partial | - | Maruti pays a royalty to Suzuki. How does a depreciation in the yen or rupee change that cost, and how much of revenue is it? |
| MB0487 | open300:A11-07 | stock | Hinglish | partial | - | Cement mein 80% vs 70% utilisation par UltraTech ka EBITDA kitna badalta hai? (Hinglish) |
| MB0488 | open300:A11-08 | stock | natural | partial | - | EPC contractors are paid late by government clients. How does that change RVNL's return on capital, and where is the working-capital disclosure? |
| MB0489 | open300:A11-09 | industry | natural | partial | - | Paint companies talk about premiumisation. What does that do to gross margin per litre, and can you measure it from the filings? |
| MB0490 | open300:A11-10 | stock | terse | partial | - | BHARTIARTL ARPU vs subscriber split FY26 |
| MB0491 | open300:A11-11 | stock | natural | partial | - | Gold-loan ticket sizes are rising. What does that do to Muthoot's loan-to-value and risk, and where is it disclosed? |
| MB0492 | open300:A11-12 | stock | natural | partial | - | A retailer's store payback depends on capex per store and store EBITDA. What payback does Trent's disclosure imply, and what is missing? |
| MB0493 | open300:A11-13 | industry | natural | partial | - | Semiconductor content per car is rising. Does that help Motherson more than a car-volume recovery would? |
| MB0494 | open300:A11-14 | industry | natural | partial | - | Data-centre capex is booming. Which listed power-equipment name has the clearest revenue link, and how would you size it? |
| MB0495 | open300:A11-15 | stock | natural | partial | - | Hospital ARPOB is the key unit metric. What drives it at Apollo, and how much is price versus occupancy? |
| MB0906 | reddit200:RD-N-001 | stock | natural | partial | - | Asian Paints: over ten years, has gross margin been stable enough to prove pricing power, or did it just track crude? |
| MB0907 | reddit200:RD-N-002 | stock | natural | partial | - | Pidilite: is the adhesives moat earning a premium through price, or is volume growth doing all the work? |
| MB0908 | reddit200:RD-N-003 | stock | natural | partial | - | Nestle India: is the last five years' growth from volume or from price and mix, and does that change the moat case? |
| MB0909 | reddit200:RD-N-004 | stock | natural | partial | - | Titan: is the jewellery segment's margin a brand premium or a gold-leasing artefact, and how would a gold spike change it? |
| MB0910 | reddit200:RD-N-005 | stock | natural | partial | - | Hindustan Unilever: has D2C competition actually taken detergent share, and what does the volume trend say? |
| MB0911 | reddit200:RD-N-006 | stock | natural | partial | - | Hindalco: what has ROIC been through the cycle versus cost of capital, and does the aluminium or the copper business carry it? |
| MB0912 | reddit200:RD-N-007 | stock | natural | partial | - | JSW Steel: the last capex round was large. What incremental ROIC has it earned so far, and how far is it from the cost of capital? |
| MB0913 | reddit200:RD-N-008 | stock | natural | partial | - | Polycab: does the ROIC still clear the cost of capital after the working-capital build, and what would a demand slowdown do to it? |
| MB0914 | reddit200:RD-N-009 | stock | natural | partial | - | ABB India: the margin is at a record. Is the ROIC being earned on new capacity or on a cyclical order book? |
| MB0915 | reddit200:RD-N-010 | stock | natural | partial | - | Cummins India: after the emission-norm change, did the pricing gain lift ROIC, or did it go into warranty and R&D? |
| MB0916 | reddit200:RD-N-011 | stock | natural | partial | - | ITC: between dividends and FMCG reinvestment, which one has earned the better return, and what does the last five years say? |
| MB0917 | reddit200:RD-N-012 | stock | natural | partial | - | Coal India: is the payout policy starving the business of capex, or is the capex not earning its keep? |
| MB0918 | reddit200:RD-N-013 | stock | natural | partial | - | HDFC Bank has never bought back stock. Is retained capital earning above the cost of equity, and should the payout change? |
| MB0919 | reddit200:RD-N-014 | stock | natural | partial | - | Bajaj Finance: how much dilution has funded the growth, and is per-share value growing as fast as the loan book? |
| MB0920 | reddit200:RD-N-015 | stock | natural | partial | - | Tata Motors PV: where exactly is the EV and JLR capex going, and what return has the last cycle produced? |
| MB0931 | reddit200:RD-N-026 | stock | natural | partial | - | Eternal: what is food-delivery contribution margin per order, and how much of the profit comes from the take rate versus ads? |
| MB0932 | reddit200:RD-N-027 | stock | natural | partial | - | Swiggy: is Instamart's contribution margin improving because of scale or because of a cut in discounts, and what does that mean for growth? |
| MB0933 | reddit200:RD-N-028 | stock | natural | partial | - | Nykaa: what does the BPC segment earn per order after fulfilment, and is the fashion segment diluting it? |
| MB0934 | reddit200:RD-N-029 | stock | natural | partial | - | DMart: what is revenue per square foot and inventory turns, and how have they moved as the store base aged? |
| MB0935 | reddit200:RD-N-030 | stock | natural | partial | - | Trent: what does a new store earn at maturity, and how long is the payback at the current capex per store? |
| MB0946 | reddit200:RD-N-041 | stock | natural | partial | - | CG Power: how much can it reinvest in transformer capacity, and what returns has the last expansion earned? |
| MB0947 | reddit200:RD-N-042 | stock | natural | partial | - | Polycab: the cable demand is strong. How much capex is left, and is the incremental ROIC above the last cycle? |
| MB0948 | reddit200:RD-N-043 | stock | natural | partial | - | Dixon: with PLI and new categories, what is the reinvestment need per rupee of new revenue, and does the return clear the hurdle? |
| MB0949 | reddit200:RD-N-044 | stock | natural | partial | - | Kaynes: what is the semiconductor/OSAT runway, and how much of the current order book depends on the new plant? |
| MB0950 | reddit200:RD-N-045 | stock | natural | partial | - | Astral: does the piping capacity addition still make sense if housing starts slow, and what is the utilisation today? |

### Family 18 - Forward policy impact (40 primary cases; 15 cross-referenced)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0496 | open300:A12-01 | policy | natural | partial | - | India Semiconductor Mission 2.0 was announced with a Rs 1,000 crore allocation. Which listed companies does it actually reach, and by what channel? |
| MB0497 | open300:A12-02 | policy | natural | partial | - | The US announced a 100% tariff on generic drug imports from 2028. Which listed Indian pharma exporters are most exposed, and how would you rank them? |
| MB0498 | open300:A12-03 | policy | natural | partial | - | A 200% tariff on generic drug imports from 2029 also exists in the policy store. How does that change the answer versus the 100% line from 2028? |
| MB0499 | open300:A12-04 | policy | Hinglish | partial | - | US ne Indian exports par extra 10% duty lagayi — kaunse textile exporters sabse zyada expose hain? (Hinglish) |
| MB0500 | open300:A12-05 | policy | natural | partial | - | The Samudra Manthan offshore-exploration scheme carries Rs 84,084 crore. Who benefits among listed oil and gas names, and over what horizon? |
| MB0501 | open300:A12-06 | policy | natural | partial | - | PMAY-U 2.0 approved another 1.93 lakh houses. Which sectors and listed names gain, and how big is that versus annual demand? |
| MB0502 | open300:A12-07 | policy | natural | partial | - | CAQM Direction 98 requires PTZ-camera monitoring for red-category industries in NCR. Which listed companies must spend, and roughly how much? |
| MB0503 | open300:A12-08 | policy | natural | partial | - | The FY26 Budget cut customs duty on flat-rolled steel products to 15%, effective 1 May 2025. Who gains and who loses among listed companies, and in what order? |
| MB0504 | open300:A12-09 | policy | natural | partial | - | Union Budget 2026-27 set the railway rolling-stock capex at Rs 52,109 crore. Which listed railway names does it reach first, and which only after the award cycle? |
| MB0505 | open300:A12-10 | policy | natural | partial | - | India signed the EU FTA on 27 January 2026, due in force at end-2026. Which listed textile exporters gain, and what did they do on the day? |
| MB0506 | open300:A12-11 | policy | natural | no | - | The FY26 Budget set up a Rs 20,000 crore Nuclear Energy Mission for SMR R&D, and the SHANTI Act opened plant operations to private firms. Which listed companies can actua... |
| MB0507 | open300:A12-12 | policy | natural | partial | - | GST process reforms were notified in October 2026. Which listed sectors gain most from simpler compliance, and does the store let you size it? |
| MB0508 | open300:A12-13 | policy | terse | partial | - | anti-dumping signal — which Indian makers gain |
| MB0509 | open300:A12-14 | policy | Hinglish | no | - | TDB-DST signed a Rs 130 crore RDI support agreement with BigEndian Semiconductors. Kaunsi listed company ko iska fayda? (Hinglish) |
| MB0510 | open300:A12-15 | policy | natural | partial | - | One Budget customs line cut duty on iron and steel articles from 25% to 15%. Which listed names sit on each side of that line, and why is the sign opposite? |
| MB0651 | ripple200:R02-01 | policy | natural | partial | - | The Union Budget 2026-27 adds a data-centres policy and an infrastructure capex thrust. Trace it from the policy to the equipment suppliers, then to their copper and CRGO... |
| MB0652 | ripple200:R02-02 | policy | natural | partial | - | The EU-India FTA is concluded in January 2026 and comes into force at the end of the year. Trace the duty cut to the EU-bound garment exporter, then to its cotton cost, t... |
| MB0653 | ripple200:R02-03 | policy | natural | no | - | US tariffs of 50% have hit Indian labour-intensive exports since August 2025. Trace the order loss to the exporter's utilisation, then to its contract workforce, then to ... |
| MB0654 | ripple200:R02-04 | policy | natural | no | - | The US has legislated a 100% tariff on generic drug imports from 2028 and 200% from 2029. Trace it back through the Indian exporter's US revenue, its front-loading decisi... |
| MB0655 | ripple200:R02-05 | policy | natural | partial | - | The RBI raised the repo 25 bps to 5.50% on 7 October 2026 and moved the stance to calibrated tightening. Trace it through the loan book that reprices first, the deposit b... |
| MB0656 | ripple200:R02-06 | policy | natural | partial | - | The 2025 easing cycle cut the repo by 50 bps in two instalments. Trace it to housing-finance affordability, then to housing sales, then to cement and steel demand, and sa... |
| MB0657 | ripple200:R02-07 | policy | natural | partial | - | The stance moved to accommodative in April 2025. Trace it through bank credit growth, then through the financing of corporate capex, then to the capital-goods order book.... |
| MB0658 | ripple200:R02-08 | policy | natural | no | - | The insurance sector is opened to 100% FDI. Trace it to the insurer's capital and competition, then to the bancassurance partner bank's fee income, then to the distributo... |
| MB0659 | ripple200:R02-09 | policy | natural | partial | - | The ECB framework is liberalised and a concessional forex swap is offered for PSU external borrowing. Trace it to the infra borrower's cost of debt, then to the capex dec... |
| MB0660 | ripple200:R02-10 | policy | natural | partial | - | FPI short-term and concentration limits are removed and the Fully Accessible Route is extended to longer G-secs. Trace it to foreign ownership of mid-caps, then to the fl... |
| MB0661 | ripple200:R02-11 | policy | natural | no | - | The export-proceeds realisation period is restored to nine months. Trace it to the exporter's FX conversion behaviour, then to forward premia, then to the importer's hedg... |
| MB0662 | ripple200:R02-12 | policy | natural | partial | - | Full hedging-cost support is offered to banks raising fresh 3-5 year FCNR(B) deposits. Trace it to the bank's swap cost, then to NIM, then to credit growth. Why would a b... |
| MB0663 | ripple200:R02-13 | policy | natural | partial | - | FDI restrictions are eased for land-bordering countries. Trace it to the defence and telecom JVs, then to localisation, then to the supplier base. Which listed defence na... |
| MB0664 | ripple200:R02-14 | policy | natural | partial | - | The collateral-free MSE loan limit is raised with effect from April 2026. Trace it to bank and NBFC credit to MSME suppliers, then to the supplier's terms with its large ... |
| MB0665 | ripple200:R02-15 | policy | natural | partial | - | Kisan Credit Card guidelines are revised. Trace it to agri-credit availability, then to the farmer's purchase of seed and crop-protection, then to the agrochem and seed c... |
| MB0666 | ripple200:R02-16 | policy | natural | partial | - | Roads-and-bridges capital outlay is raised again in the Budget. Trace it to the award of EPC contracts, then to cement and steel consumption at the site, then to the equi... |
| MB0667 | ripple200:R02-17 | policy | natural | partial | - | Jal Jeevan Mission allocations continue. Trace them to pipe demand, then to the steel and PVC input, then to the contractor's margin under a state tender. Where does the ... |
| MB0668 | ripple200:R02-18 | policy | natural | partial | - | The 16th Finance Commission discontinues revenue-deficit and sector-specific grants to states. Trace it to state capex spending, then to the contractors that depend on st... |
| MB0669 | ripple200:R02-19 | policy | natural | partial | - | Additional borrowing space is offered to states for power-sector reforms. Trace it to discom dues and payments, then to the generator's receivable days, then to the gener... |
| MB0670 | ripple200:R02-20 | policy | natural | no | - | A National Mission on High Yielding Seeds is announced. Trace it to seed replacement rates, then to agrochem and fertiliser use per acre, then to farm income, then to two... |
| MB0876 | reddit200:RD-I-046 | stock | natural | partial | - | If the budget raises tobacco duty again, how much of ITC's revenue and profit is actually exposed, and what did the last duty hike do to volumes? |
| MB0877 | reddit200:RD-I-047 | stock | natural | partial | - | The defence budget line grew again. Which of HAL, BEL and Mazagon Dock has the revenue visibility that matches its valuation? |
| MB0878 | reddit200:RD-I-048 | stock | natural | partial | - | Rail capex was front-loaded this year. Does that show up first in RVNL's revenue or in IRFC's loan book, and with what lag? |
| MB0879 | reddit200:RD-I-049 | policy | natural | partial | - | A higher import duty on solar modules: who benefits between Waaree and Premier Energies, and what happens to the project developers' cost? |
| MB0880 | reddit200:RD-I-050 | stock | natural | partial | - | Rubber prices and an import-duty change hit tyre makers differently. Which of Apollo, MRF and CEAT has the best pass-through history? |
| MB0601 | open300:A19-01 | sector | natural | partial | primary 16 | If the monsoon fails, which listed sectors are most exposed, and in what order would the effect show up? |
| MB0602 | open300:A19-02 | sector | natural | partial | primary 16 | Crude is already at 103.53 on 30 September 2026. If it holds, which listed sectors lose most, and which gain? |
| MB0603 | open300:A19-03 | policy | natural | partial | primary 16 | If US tariffs rise another 25 points, which listed exporters are most exposed, and what would you check first? |
| MB0604 | open300:A19-04 | sector | natural | partial | primary 16 | If the rupee goes to 100, who wins and who loses among listed companies? Give both sides with a channel each. |
| MB0605 | open300:A19-05 | industry | natural | partial | primary 16 | Gold is 4,186.7. If it goes to 5,000, do jewellers or gold-loan NBFCs do better, and why is the answer not obvious? |
| MB0606 | open300:A19-06 | sector | terse | no | primary 16 | coal scarcity FY27 — which sectors, answerable? |
| MB0607 | open300:A19-07 | policy | natural | partial | primary 16 | If the FY27 public capex of Rs 12.2 lakh crore is spent as budgeted, which listed sectors see it first, which later, and who loses? |
| MB0608 | open300:A19-08 | policy | natural | partial | primary 16 | If the semiconductor incentive doubles, which listed companies benefit first and which only in the second round? |
| MB0609 | open300:A19-09 | policy | natural | partial | primary 16 | If the RBI cuts 100bp over a year, which listed sectors re-rate first, and what breaks the chain? |
| MB0610 | open300:A19-10 | theme | natural | partial | primary 16 | If data-centre capex doubles, which listed companies see it first, and is the exposure measurable? |
| MB0611 | open300:A19-11 | theme | natural | partial | primary 16 | If EV penetration hits 30%, which listed auto-component names lose and which gain? Give both sides. |
| MB0612 | open300:A19-12 | sector | natural | partial | primary 16 | If China+1 accelerates, which listed sectors win, and what is the first evidence you would look for? |
| MB0613 | open300:A19-13 | sector | natural | partial | primary 16 | If container freight rates spike, which listed exporters lose and does a shipping line gain? |
| MB0614 | open300:A19-14 | policy | natural | partial | primary 16 | If GST rates are cut on consumer durables, who gains more: a durables maker or an FMCG company? |
| MB0615 | open300:A19-15 | sector | Hinglish | partial | primary 16 | Agar crude $100 ho jaye to kaunse listed sectors sabse zyada peedit honge? (Hinglish) |

### Family 19 - Second-order / supply chain (40 primary cases; 20 cross-referenced)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0511 | open300:A13-01 | industry | natural | partial | - | Who makes the wagons Indian Railways buys, and who supplies those wagon makers with steel? Name both layers. |
| MB0512 | open300:A13-02 | industry | natural | partial | - | Defence indigenisation gave BEL and HAL large orders. Which second-layer listed suppliers gain, and how do you establish the link? |
| MB0513 | open300:A13-03 | policy | natural | partial | - | The TCS on coal and iron-ore sales doubles to 2% from 1 April 2026. Who is hit first, who second, and does any listed layer gain? |
| MB0514 | open300:A13-04 | industry | natural | partial | - | Copper goes into cables, which go into EPC projects. Who bears the copper risk in that three-layer chain, and what contract feature decides it? |
| MB0515 | open300:A13-05 | policy | natural | partial | - | Semiconductor Mission 2.0 should lift EMS assembly. Which chemical and material suppliers sit under that, and is the link disclosed? |
| MB0516 | open300:A13-06 | industry | terse | partial | - | solar module chain — BORORENEW glass/EVA link |
| MB0517 | open300:A13-07 | industry | natural | partial | - | BharatNet needs optical fibre and telecom gear. Which listed suppliers gain, and how is the award flowing? |
| MB0518 | open300:A13-08 | stock | natural | partial | - | Cochin Shipyard's Drydocks World JV will need steel and marine equipment. Which listed companies are the plausible suppliers, and what is the evidence standard? |
| MB0519 | open300:A13-09 | industry | natural | partial | - | The Mumbai-Ahmedabad high-speed-rail packages use TBMs. Which listed companies supply the civil inputs, and what does Afcons' own disclosure say? |
| MB0520 | open300:A13-10 | theme | Hinglish | partial | - | EV adoption badhne se kaunse auto-component names jeetenge aur kaun harenge? (Hinglish) |
| MB0521 | open300:A13-11 | industry | natural | no | - | Airline fleet expansion means more MRO and leasing. Which listed names capture that, and which part is NOT IN DATA? |
| MB0522 | open300:A13-12 | industry | natural | no | - | Hospital capex needs imported medical equipment. Which listed suppliers gain, and can the store quantify it? |
| MB0523 | open300:A13-13 | policy | natural | partial | - | US tariffs on Indian textiles have been 50% since August 2025. Which listed dye and chemical suppliers are exposed second-hand, and what is the evidence bar? |
| MB0524 | open300:A13-14 | policy | natural | partial | - | Budget 2026-27 put Rs 7,500 crore into railway signalling and telecom. Beyond the wagon makers, who in the listed universe gains second-hand, and in what order? |
| MB0525 | open300:A13-15 | industry | Hinglish | partial | - | Railway wagon banane wale ko steel kaun deta hai, aur scrap/CRGO pe exemption extend hone se chain mein kaun jeetta hai, kaun peeche reh jaata hai? (Hinglish) |
| MB0711 | ripple200:R05-01 | market-cap bucket | natural | partial | - | A PLI-backed module maker cuts its price to fill a new line. Trace it to the non-PLI small-cap's ASP, then to its utilisation, then to its ability to keep the line runnin... |
| MB0712 | ripple200:R05-02 | industry | natural | no | - | Announced module and cell capacity exceeds the demand implied by the renewable bid pipeline. Trace the capacity announcements, then the utilisation, then the bid tariff, ... |
| MB0713 | ripple200:R05-03 | industry | natural | partial | - | A large cement group buys capacity in a region where a mid-size producer earns its best margin. Trace the acquisition to regional pricing, then to the mid-size producer's... |
| MB0714 | ripple200:R05-04 | industry | natural | partial | - | The largest cable maker cuts dealer price to defend share in wires. Trace it to the small cable maker's gross margin, then to its ability to hold inventory, then to its b... |
| MB0715 | ripple200:R05-05 | industry | natural | partial | - | A large diversified group enters decorative paints. Trace it to the incumbents' price response, then to the dealer count, then to the incumbent's ad spend and margin. How... |
| MB0716 | ripple200:R05-06 | industry | natural | no | - | Domestic steel capacity rises into a weak global market and imports gather. Trace the capacity, then the domestic price, then the mills' ask for protection, then the user... |
| MB0717 | ripple200:R05-07 | industry | natural | no | - | Tyre capacity is added by three players at once just as replacement demand softens. Trace the capacity, then the dealer price, then the margin, then the OEM contract for ... |
| MB0718 | ripple200:R05-08 | industry | natural | no | - | Three specialty-chemical makers raise equity for the same product family. Trace the fund raise, then the capex, then the commissioned capacity, then the product price two... |
| MB0719 | ripple200:R05-09 | industry | natural | partial | - | A large bank cuts its home-loan rate to win prime customers. Trace it to the HFC's spread, then to the HFC's disbursement mix, then to its cost of funds. Which listed HFC... |
| MB0720 | ripple200:R05-10 | policy | natural | partial | - | Insurance FDI is opened and two foreign groups announce Indian JVs. Trace them to the commission paid for distribution, then to the bancassurance partner's fee, then to t... |
| MB0721 | ripple200:R05-11 | industry | natural | no | - | Two CDMO players commission capacity in the same molecule class. Trace the capacity, then the pricing of the contract, then the API supplier's volume, then the innovator'... |
| MB0722 | ripple200:R05-12 | industry | natural | partial | - | Defence orders concentrate in two primes. Trace the order to the primes' capacity, then to the tier-2 suppliers' qualification, then to the small supplier's dependence on... |
| MB0723 | ripple200:R05-13 | policy | natural | partial | - | Electronics manufacturing scales on a PLI scheme. Trace the scheme to the assembler's scale, then to its component import bill, then to the domestic component supplier's ... |
| MB0724 | ripple200:R05-14 | industry | natural | partial | - | Two hospital chains add beds in the same metro. Trace the beds, then the occupancy, then the pricing per procedure, then the doctor's share. Which listed chain is most ex... |
| MB0725 | ripple200:R05-15 | industry | natural | partial | - | A food-delivery aggregator raises its commission and cuts discounts at the same time. Trace it to the restaurant's take rate, then to its menu price, then to its order vo... |
| MB0726 | ripple200:R05-16 | industry | natural | no | - | An airline inducts a large order of narrowbodies into a market with flat demand. Trace the capacity, then the fare, then the airport's aero revenue, then the lessor's lea... |
| MB0727 | ripple200:R05-17 | industry | natural | no | - | Two paper makers commission recycled-board capacity just as packaging demand slows. Trace the capacity, then the board price, then the converter's cost, then the FMCG con... |
| MB0728 | ripple200:R05-18 | industry | natural | no | - | The competing country's garment capacity comes back on line. Trace the order hand-back, then the Indian exporter's utilisation, then its yarn purchase, then the spinner's... |
| MB0729 | ripple200:R05-19 | industry | natural | partial | - | A bank decides to build a small-ticket personal-loan book. Trace it to the NBFC's borrower acquisition cost, then to its ticket size, then to its credit cost. Which liste... |
| MB0730 | ripple200:R05-20 | industry | natural | partial | - | A pharmacy chain buys a smaller chain. Trace it to store overlap, then to the merged store's footfall, then to the supplier's trade terms, then to the generic substitutio... |
| MB0971 | reddit200:RD-N-066 | stock | natural | partial | - | Dixon: how concentrated is the customer base, and what would losing the top account do to revenue and margin? |
| MB0972 | reddit200:RD-N-067 | stock | natural | partial | - | Kaynes: what share of revenue comes from the top five customers, and how does that compare with the order-book claims? |
| MB0973 | reddit200:RD-N-068 | stock | natural | partial | - | Syrma: how much revenue depends on the top client, and has that dependence fallen since the IPO? |
| MB0974 | reddit200:RD-N-069 | stock | natural | partial | - | Amber: the air-conditioner business is seasonal and concentrated. What does that do to quarterly revenue and working capital? |
| MB0975 | reddit200:RD-N-070 | theme | natural | partial | - | Sona Comstar: how much of the order book is EV, and how dependent is it on two customers? |
| MB0691 | ripple200:R04-01 | industry | natural | no | primary 16 | A shipping route closes. Europe-bound Indian goods spend two extra weeks at sea, the buyer defers the programme, the exporter's finished stock piles up, and its export in... |
| MB0692 | ripple200:R04-02 | policy | natural | no | primary 16 | The US raises tariffs on steel and aluminium. Indian exporters lose the US premium, divert volume domestically, and the domestic HRC price falls. Trace it to the auto anc... |
| MB0693 | ripple200:R04-03 | industry | natural | no | primary 16 | Chinese producers dump surplus into India. Specialty-chemical ASPs fall, the domestic producer cuts output, and when the dumping stops the buyer has lost a qualified loca... |
| MB0694 | ripple200:R04-04 | policy | natural | partial | primary 16 | A tariff on generic drugs is announced for 2028. The US buyer front-loads inventory in 2027, the Indian exporter runs its plants flat out, and then the order stops. Trace... |
| MB0695 | ripple200:R04-05 | policy | natural | no | primary 16 | The EU brings in a carbon border adjustment on steel and aluminium. The Indian exporter's carbon cost enters the landed price, the EU buyer looks for a lower-carbon sourc... |
| MB0696 | ripple200:R04-06 | industry | natural | no | primary 16 | Edible-oil and fertiliser supply from the Black Sea is disrupted. Trace it to the packaged-food company's input, then to the price point, then to the rural consumer. Whic... |
| MB0697 | ripple200:R04-07 | industry | natural | no | primary 16 | A competitor country's garment industry is disrupted. EU and US buyers shift programmes to India, the exporter adds a shift, and cotton buying tightens. How far can the I... |
| MB0698 | ripple200:R04-08 | industry | natural | partial | primary 16 | Crude spikes and the retail price of petrol and diesel is not raised. Trace it to the refiner-marketer's under-recovery, then to the subsidy or the PSU's balance sheet, t... |
| MB0699 | ripple200:R04-09 | industry | natural | partial | primary 16 | Component export controls tighten. The Indian electronics assembler's BOM cost rises, the customer refuses a price rise, and the assembler has to localise faster than its... |
| MB0700 | ripple200:R04-10 | industry | natural | no | primary 16 | A trade partner opens an excess-capacity investigation. Trace it to the risk premium on Indian exports, then to the buyer's order timing, then to the exporter's capacity ... |
| MB0701 | ripple200:R04-11 | industry | natural | no | primary 16 | Two trade agreements pull in opposite directions: a US tariff raises the landed cost, an EU agreement lowers it. For the same exporter, which destination wins on margin, ... |
| MB0702 | ripple200:R04-12 | industry | natural | partial | primary 16 | Seaborne coal prices spike. The generator's fuel cost rises, the regulated tariff does not immediately, and the aluminium smelter buying from the exchange pays the mercha... |
| MB0703 | ripple200:R04-13 | industry | natural | no | primary 16 | LME copper jumps and a cable maker is holding inventory bought at the old price. The holding gain flatters the quarter, the dealer sees the new price list, and the order ... |
| MB0704 | ripple200:R04-14 | market-cap bucket | natural | no | primary 16 | Foreign investors sell. The mid-cap index falls, the planned QIP window closes, and a company that needed equity funds its capex with debt instead. Trace the sequence and... |
| MB0705 | ripple200:R04-15 | industry | natural | no | primary 16 | War-risk premia rise on a shipping route. Trace it to the charter rate, then to the importer's landed cost, then to the inventory decision. Which listed shipping name ben... |
| MB0706 | ripple200:R04-16 | industry | natural | no | primary 16 | Global rubber rises sharply. Traces it to the Indian tyre maker's cost, then to the replacement price, then to the truck operator's cost per km, then to the replacement i... |
| MB0707 | ripple200:R04-17 | industry | natural | partial | primary 16 | Gold rises in dollars and the rupee weakens in the same quarter. Trace it to the jeweller's landed cost, then to the wedding-season volume, then to the inventory the stor... |
| MB0708 | ripple200:R04-18 | stock | natural | no | primary 16 | A foreign strategic buyer takes a stake in an Indian listed company's competitor. Trace it to the competitor's capacity plan, then to the industry's price behaviour, then... |
| MB0709 | ripple200:R04-19 | industry | natural | no | primary 16 | A monsoon deficit hits fodder and water. Milk procurement falls, the dairy's procurement price rises, and the packaged-food buyer's cost follows. Trace it and say whether... |
| MB0710 | ripple200:R04-20 | policy | natural | no | primary 16 | The US raises the tariff on shrimp and the EU opens a quota. The Indian exporter's destination margin flips, the hatchery's order book follows, and the farmer decides the... |

### Family 20 - Out-of-scope and bizarre (20 primary cases)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0616 | open300:A20-01 | stock | terse | no | - | What will Reliance's share price be on Diwali 2027? |
| MB0617 | open300:A20-02 | stock | natural | no | - | How many electric two-wheelers did Ola Electric deliver in September 2026? |
| MB0618 | open300:A20-03 | stock | natural | partial | - | What is Dixon's CEO paid, and how has that changed in three years? |
| MB0619 | open300:A20-04 | index | natural | no | - | Which company will be the next Nifty 50 inclusion, and when? |
| MB0620 | open300:A20-05 | policy | natural | partial | - | What exactly did the RBI governor say about the rupee at the last MPC, and does the store have his words? |
| MB0621 | open300:A20-06 | stock | terse | no | - | How much of Titagarh does FII money own right now? |
| MB0622 | open300:A20-07 | stock | natural | partial | - | How many shares did TruAlt's promoter actually pledge in September 2026? |
| MB0623 | open300:A20-08 | stock | natural | partial | - | Why exactly did Milefur's auditor resign? Give the auditor's own words. |
| MB0624 | open300:A20-09 | market-wide | terse | partial | - | Which listed company had the highest employee attrition in FY26? |
| MB0625 | open300:A20-10 | stock | terse | partial | - | How much did Suzlon pay its statutory auditor last year? |
| MB0626 | open300:A20-11 | industry | natural | no | - | What is the exact copper content per kilometre of a 33 kV cable? |
| MB0627 | open300:A20-12 | market-cap bucket | terse | no | - | Which mid-cap will double in 2027? |
| MB0628 | open300:A20-13 | stock | terse | partial | - | SRF FY26 patent count by chemistry |
| MB0629 | open300:A20-14 | market-wide | natural | partial | - | How much money did retail investors lose on 4 June 2024, in rupees? |
| MB0630 | open300:A20-15 | policy | natural | partial | - | What did the Finance Minister say about capital-gains tax in the 2026 Budget, and is the exact sentence stored? |
| MB0976 | reddit200:RD-N-071 | stock | natural | partial | - | For Asian Paints, what would actually break the moat thesis: a new entrant's share, a dealer shift, or a gross-margin floor? |
| MB0977 | reddit200:RD-N-072 | stock | natural | partial | - | For DMart, what evidence would prove quick commerce has permanently damaged the growth runway? |
| MB0978 | reddit200:RD-N-073 | stock | natural | partial | - | For Eternal, what would prove the profitability path is broken rather than delayed? |
| MB0979 | reddit200:RD-N-074 | stock | natural | partial | - | For Polycab, what would prove the power-capex cycle has peaked: order growth, utilisation, or receivable days? |
| MB0980 | reddit200:RD-N-075 | stock | natural | partial | - | For Titan, what would break the growth thesis: a gold-price spike, lab-grown diamonds, or a same-store slowdown? |

### Family not declared (85 primary cases)

| mid | source | level | style | coverage | also | question |
| --- | --- | --- | --- | --- | --- | --- |
| MB0831 | reddit200:RD-I-001 | stock | natural | partial | - | Reliance has just reported Q2FY26. Is this a good level to start a position, or should I wait for a retest of the pre-result range? |
| MB0832 | reddit200:RD-I-002 | stock | natural | partial | - | DMart is well below its 52-week high but still expensive on PE. For someone starting fresh, enter now or wait for a lower level? |
| MB0833 | reddit200:RD-I-003 | stock | natural | partial | - | Paytm has come off its lows. Is the risk-reward good enough to enter before the next results, or is waiting safer? |
| MB0834 | reddit200:RD-I-004 | stock | natural | partial | - | IREDA ran up a lot after listing. Is it too late to enter now, or does the loan-book growth still justify a fresh position? |
| MB0835 | reddit200:RD-I-005 | stock | Hinglish | partial | - | Titagarh Rail had a strong order-book run and then a sharp pullback. Kya abhi entry sahi hai, ya result ke baad dekhna chahiye? |
| MB0836 | reddit200:RD-I-006 | stock | natural | partial | - | Adani group has several listed arms. Which one carries the least balance-sheet risk relative to its cash generation right now? |
| MB0837 | reddit200:RD-I-007 | market-wide | natural | partial | - | Within the Tata group, which listed company is the cleanest proxy for the group's own capex plans, and which is mostly a holding-company discount story? |
| MB0838 | reddit200:RD-I-008 | sector | natural | partial | - | PSU banks: which of the large ones has the best combination of NIM and credit cost this quarter, and which is most exposed to a slippage cycle? |
| MB0839 | reddit200:RD-I-009 | stock | natural | partial | - | Defence pack: HAL, BEL, Mazagon Dock and BDL. Which has the order book to revenue cover that best protects it if capex slows? |
| MB0840 | reddit200:RD-I-010 | industry | natural | partial | - | Railway names RVNL, IRFC, IRCON and RITES all move with rail capex. Which one actually earns a spread on the capex, and which just holds the paper? |
| MB0841 | reddit200:RD-I-011 | stock | natural | no | - | Swiggy listed at a discount to the grey-market talk. What did the grey premium imply before listing, and how did the first-day close compare? |
| MB0842 | reddit200:RD-I-012 | stock | natural | yes | - | Ola Electric's listing pop faded quickly. What was the listing-day return, and how much of it was gone within a month? |
| MB0843 | reddit200:RD-I-013 | stock | natural | partial | - | Waaree Energies: was the listing-day move justified by the order book disclosed in the prospectus, or was it mostly scarcity? |
| MB0844 | reddit200:RD-I-014 | stock | natural | partial | - | Premier Energies versus the older solar names: did the IPO price already capture the order book that peers took years to build? |
| MB0845 | reddit200:RD-I-015 | stock | natural | partial | - | NTPC Green and the renewable IPP pack: after the listing, which one trades at the biggest premium to book, and what does the market expect from it? |
| MB0846 | reddit200:RD-I-016 | stock | natural | partial | - | After the Tata Motors demerger into TMPV and TMCV, which entity carries the auto-finance exposure, and how should the cost basis split? |
| MB0847 | reddit200:RD-I-017 | stock | natural | yes | - | Zomato is now Eternal. Does my old Zomato holding map to the same ISIN, and how does the price history handle the name change? |
| MB0848 | reddit200:RD-I-018 | stock | natural | partial | - | Vedanta's demerger: which listed entity will hold the aluminium business, and what happens to my shares between the record date and listing? |
| MB0849 | reddit200:RD-I-019 | stock | natural | yes | - | If a company announces a 1:1 bonus, what price should the stock open at on the ex-date, and does my average cost change? |
| MB0850 | reddit200:RD-I-020 | policy | natural | partial | - | Government OFS in IREDA: how is the floor price set, and does the stock usually trade at a discount to it before the issue closes? |
| MB0851 | reddit200:RD-I-021 | industry | natural | partial | - | Which regulator action hit Paytm Payments Bank, when was it disclosed, and how did the listed company's price react on the first trading day after? |
| MB0852 | reddit200:RD-I-022 | stock | natural | partial | - | Adani Enterprises: what has SEBI actually concluded, what is still open, and which disclosures since 2023 changed the risk? |
| MB0853 | reddit200:RD-I-023 | stock | natural | partial | - | Yes Bank's reconstruction scheme locked in shareholder shares. What is still subject to lock-in, and when does the restriction end? |
| MB0854 | reddit200:RD-I-024 | stock | natural | partial | - | Vodafone Idea's preferential allotment: which SEBI pricing rule set the floor, and did the issue dilute more than the announcement implied? |
| MB0855 | reddit200:RD-I-025 | market-cap bucket | natural | partial | - | For a small-cap like Titagarh, what does SEBI's LODR require to be disclosed within 24 hours, and which recent filings met or missed that clock? |
| MB0856 | reddit200:RD-I-026 | stock | natural | yes | - | Suzlon has been hitting upper circuits repeatedly. Which band applies now, what was the last base-price reset, and when did it last open normally? |
| MB0857 | reddit200:RD-I-027 | stock | natural | yes | - | Vodafone Idea trades in a narrow band. Is the 5% limit still on, and how does delivery behave on the days it touches the band? |
| MB0858 | reddit200:RD-I-028 | stock | natural | yes | - | Jaiprakash Power: did the band change after the last base-price reset, and did the change coincide with the volume spike? |
| MB0859 | reddit200:RD-I-029 | market-wide | natural | partial | - | Reliance Power has had long lower-circuit streaks. How many sessions did it stay locked, and what finally broke the streak? |
| MB0860 | reddit200:RD-I-030 | stock | natural | yes | - | Ola Electric after listing: did the price band widen, and how did the delivery percentage change when it did? |
| MB0866 | reddit200:RD-I-036 | stock | natural | partial | - | I am holding Paytm at a large loss. Is there a fundamental case to average down, or is averaging just doubling a mistake? |
| MB0867 | reddit200:RD-I-037 | stock | natural | partial | - | Nykaa has been flat for years. What has actually improved in the business, and what would make the wait worth it? |
| MB0868 | reddit200:RD-I-038 | stock | natural | partial | - | Ola Electric keeps making new lows. At what point does the loss of market share show up in the numbers, and is the cash runway the real risk? |
| MB0869 | reddit200:RD-I-039 | stock | natural | partial | - | IRFC has run up a lot. Should I book profit, or is the lender's spread still improving? |
| MB0870 | reddit200:RD-I-040 | stock | natural | partial | - | Swiggy's lock-in expiry is behind us. Did the supply actually hit the price, and what does the delivery business need to show next? |
| MB0981 | reddit200:RD-T-001 | stock | point-in-time | yes | - | Reliance has retested the same zone three times since August. As of 24 Sep 2026, did the third retest hold on lower volume? |
| MB0982 | reddit200:RD-T-002 | stock | natural | yes | - | HDFC Bank broke below its 50-day average and then reclaimed it. Which close confirmed the reclaim, and what did delivery do? |
| MB0983 | reddit200:RD-T-003 | stock | natural | yes | - | TCS has been range-bound for two months. What are the range edges, and how many times has each been tested on above-average volume? |
| MB0984 | reddit200:RD-T-004 | stock | natural | yes | - | SBI fell to a level that held in March. Is that level still valid after the June bounce, and how much volume sits at it? |
| MB0985 | reddit200:RD-T-005 | stock | natural | partial | - | Tata Motors PV: the post-demerger base is thin. What is the first real support level, and is there enough history to trust it? |
| MB0986 | reddit200:RD-T-006 | stock | natural | yes | - | BEL broke to a new high in September. Was the breakout confirmed by volume and delivery, or was it a thin move? |
| MB0987 | reddit200:RD-T-007 | stock | natural | yes | - | HAL cleared its previous swing high on a delivery spike. Did the delivery stay high for the next five sessions? |
| MB0988 | reddit200:RD-T-008 | stock | natural | yes | - | RVNL broke out but the volume was below average. How many failed breakouts has it had in the last year on similar volume? |
| MB0989 | reddit200:RD-T-009 | stock | natural | partial | - | IRFC's breakout came with high delivery %. Does high delivery at a breakout predict a better 20-day hold than low delivery? |
| MB0990 | reddit200:RD-T-010 | stock | natural | yes | - | Polycab is near its 52-week high but delivery has fallen. Is the move being driven by intraday traders rather than accumulation? |
| MB0991 | reddit200:RD-T-011 | stock | natural | yes | - | Infosys: did the 50-day cross above the 200-day this year, and how has the stock behaved in the 30 sessions after each cross? |
| MB0992 | reddit200:RD-T-012 | stock | natural | partial | - | HDFC Bank is above its 200-day but below its 50-day. What has that configuration meant for the next month historically? |
| MB0993 | reddit200:RD-T-013 | stock | natural | yes | - | TCS has been below its 200-day for months. How far below, and when did it last spend this long under the line? |
| MB0994 | reddit200:RD-T-014 | stock | natural | partial | - | ITC's 50-day is flattening into the 200-day. What would a death cross actually change for a long-term holder? |
| MB0995 | reddit200:RD-T-015 | stock | natural | partial | - | Larsen & Toubro is near all three averages at once. Which average has acted as the better entry line over the last three years? |
| MB0996 | reddit200:RD-T-016 | stock | natural | yes | - | Tata Power's RSI dipped below 30 in an uptrend. How did the stock perform over the next 20 sessions the last three times that happened? |
| MB0997 | reddit200:RD-T-017 | stock | natural | partial | - | Adani Power is overbought on RSI but still making higher highs. Does overbought in a strong trend mean sell here? |
| MB0998 | reddit200:RD-T-018 | stock | natural | yes | - | Suzlon's RSI stayed above 70 for weeks during the rally. How long can that persist before a 10% drawdown, historically? |
| MB0999 | reddit200:RD-T-019 | stock | natural | yes | - | Vodafone Idea is deeply oversold again. Has an oversold RSI ever marked a durable low in this stock? |
| MB1000 | reddit200:RD-T-020 | stock | natural | partial | - | Ola Electric's RSI made a higher low while price made a lower low. Is that divergence worth acting on, and how often has it worked? |
| MB1001 | reddit200:RD-T-021 | stock | natural | yes | - | HAL is within 2% of its 52-week high. How many prior sessions this year were this close, and what followed? |
| MB1002 | reddit200:RD-T-022 | stock | natural | partial | - | Mazagon Dock made a new 52-week high on declining volume. Is that a warning or noise? |
| MB1003 | reddit200:RD-T-023 | stock | natural | yes | - | Titan is 15% below its 52-week high. How long did the last three drawdowns of that size take to recover? |
| MB1004 | reddit200:RD-T-024 | stock | natural | yes | - | Trent at a new high: what share of the last year's trading days were within 5% of the then-current 52-week high? |
| MB1005 | reddit200:RD-T-025 | stock | natural | partial | - | BEL versus HAL: which has spent more of the last two years within 10% of its 52-week high, and does that predict anything? |
| MB1006 | reddit200:RD-T-026 | market-wide | natural | yes | - | Tata Motors PV gapped up after its first post-demerger result. Has the gap filled, and how many sessions did it take? |
| MB1007 | reddit200:RD-T-027 | stock | natural | yes | - | Infosys gapped down on results and then drifted. Did the gap act as resistance on the next two rallies? |
| MB1008 | reddit200:RD-T-028 | stock | natural | partial | - | HDFC Bank opened with a gap after the budget. Was it a breakaway gap or an exhaustion gap, and what did volume say? |
| MB1009 | reddit200:RD-T-029 | stock | natural | yes | - | Eternal gapped up on a big delivery day. How much of the gap held by the close, and did delivery confirm it? |
| MB1010 | reddit200:RD-T-030 | stock | natural | partial | - | Paytm has had several earnings gaps. Which ones filled within a month, and did the unfilled ones share a volume signature? |
| MB1011 | reddit200:RD-T-031 | stock | natural | partial | - | HDFC Bank has underperformed the Nifty for a quarter. Is the relative strength turning, and what would confirm it? |
| MB1012 | reddit200:RD-T-032 | stock | natural | partial | - | BEL versus the Nifty: how strong is the relative strength, and has it been led by earnings upgrades or by the defence theme? |
| MB1013 | reddit200:RD-T-033 | stock | natural | partial | - | ITC has been a relative laggard while defensives rallied. What does the RS line say about rotation into or out of the stock? |
| MB1014 | reddit200:RD-T-034 | stock | natural | partial | - | Tata Power has outperformed the Nifty for six months. Is the RS at an extreme that historically mean-reverts? |
| MB1015 | reddit200:RD-T-035 | stock | natural | partial | - | DMart versus Trent: which has the better six-month relative strength against the Nifty, and does it match the earnings trend? |
| MB1016 | reddit200:RD-T-036 | stock | natural | no | - | Reliance futures added open interest while price rose. Is that long build-up or short covering, and what does the rollover say? |
| MB1017 | reddit200:RD-T-037 | stock | natural | no | - | HDFC Bank futures are at a premium to spot into expiry. Is the basis widening, and what has that meant for the stock after expiry? |
| MB1018 | reddit200:RD-T-038 | stock | natural | no | - | SBI saw a large OI addition at a strike above spot. Is that a ceiling the market expects, or a hedge? |
| MB1019 | reddit200:RD-T-039 | stock | natural | no | - | Bajaj Finance: did shorts cover into the recent rally, and how much OI is left going into results? |
| MB1020 | reddit200:RD-T-040 | stock | natural | no | - | ICICI Bank's rollover was lower than last expiry. Does that mean traders are exiting, or just moving to the next series early? |
| MB1021 | reddit200:RD-T-041 | stock | natural | no | - | What is the Nifty's put-call ratio today, and is it at a level that has marked short-term bottoms? |
| MB1022 | reddit200:RD-T-042 | stock | natural | no | - | BANKNIFTY max pain is below spot into expiry. How often does the index actually drift to max pain? |
| MB1023 | reddit200:RD-T-043 | stock | natural | partial | - | Reliance has huge call OI at a round strike. Is that a real ceiling or just a hedge by institutions? |
| MB1024 | reddit200:RD-T-044 | stock | natural | yes | - | HDFC Bank expiry-day volume spikes every month. How much of the monthly volume is expiry-driven, and does the cash market see it too? |
| MB1025 | reddit200:RD-T-045 | stock | natural | partial | - | ICICI Bank's put-call ratio flipped two days before expiry. Did the cash market's delivery and price confirm the same direction? |
| MB1026 | reddit200:RD-T-046 | stock | natural | partial | - | Suzlon printed a delivery spike at a 52-week high. Was the spike genuine accumulation or a single block transfer? |
| MB1027 | reddit200:RD-T-047 | stock | natural | yes | - | Yes Bank's delivery % jumped above 60% for two days. What was the volume, and did the price hold the move? |
| MB1028 | reddit200:RD-T-048 | stock | natural | partial | - | Vodafone Idea's delivery percentage has been falling while volume rises. What does that pattern usually precede? |
| MB1029 | reddit200:RD-T-049 | stock | natural | yes | - | Jaiprakash Power's delivery spike came on a circuit day. Is delivery data even meaningful when the price is locked? |
| MB1030 | reddit200:RD-T-050 | stock | natural | partial | - | RVNL had three delivery spikes in a month with no price progress. Is that distribution or absorption? |

## 5. Files

- `MASTER_BANK.jsonl` - one JSON object per unique case (the representative), with `duplicates` listing every merged source row.
- `MASTER_BANK.md` - this file.
- `GAP_ROLLUP.md` - every named gap, deduplicated and ranked by unique cases blocked per unit of effort, with the held-data verdict.

## 6. Hand check (30 rows across the banks)

The expected level is the scope the question asks about, read from the question text (not copied from the derived value). Two deliberately ambiguous rows are counted as misses: A09-07 (OMC industry read as the stock IOC/BPCL pair) and A13-08 (supplier industry read as the named JV parent).

**28/30 = 93.3%** correct.

| mid | source | expected | derived | result |
| --- | --- | --- | --- | --- |
| MB0012 | shivam30:Q17 | industry | industry | ok |
| MB0016 | shivam30:Q21 | policy | policy | ok |
| MB0031 | variations300:DBQ1-V1 | stock | stock | ok |
| MB0037 | variations300:DBQ1-V7 | industry | industry | ok |
| MB0288 | variations300:QA6-V8 | index | index | ok |
| MB0138 | variations300:Q16-V8 | theme | theme | ok |
| MB0167 | variations300:Q19-V7 | index | index | ok |
| MB0267 | variations300:QA4-V7 | industry | industry | ok |
| MB0336 | open300:A01-06 | stock | stock | ok |
| MB0421 | open300:A07-01 | market-wide | market-wide | ok |
| MB0452 | open300:A09-02 | industry | industry | ok |
| MB0457 | open300:A09-07 | industry | stock | MISS |
| MB0472 | open300:A10-07 | stock | stock | ok |
| MB0482 | open300:A11-02 | theme | theme | ok |
| MB0496 | open300:A12-01 | policy | policy | ok |
| MB0512 | open300:A13-02 | industry | industry | ok |
| MB0518 | open300:A13-08 | industry | stock | MISS |
| MB0578 | open300:A17-08 | market-cap bucket | market-cap bucket | ok |
| MB0601 | open300:A19-01 | sector | sector | ok |
| MB0619 | open300:A20-04 | index | index | ok |
| MB0631 | ripple200:R01-01 | industry | industry | ok |
| MB0651 | ripple200:R02-01 | policy | policy | ok |
| MB0671 | ripple200:R03-01 | policy | policy | ok |
| MB0692 | ripple200:R04-02 | policy | policy | ok |
| MB0714 | ripple200:R05-04 | industry | industry | ok |
| MB0731 | ripple200:R06-01 | market-wide | market-wide | ok |
| MB0751 | ripple200:R07-01 | industry | industry | ok |
| MB0771 | ripple200:R08-01 | industry | industry | ok |
| MB0791 | ripple200:R09-01 | macro | macro | ok |
| MB0811 | ripple200:R10-01 | stock | stock | ok |

