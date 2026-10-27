# Master question bank - one deduplicated bank from every source

Built by `tasks/master_bank/build_master_bank.py`. Re-run: `python tasks/master_bank/build_master_bank.py --check`.

Sources: Shivam's 30 fixed regressions (kept as written, `regression: true`), the 300 variations, the 300 open questions, the 200 ripple questions (the Reddit bank is not present yet; the loader is ready for it).

## 1. Counts per source bank

| bank | rows in | representatives | merged as duplicate | cases with >=1 row from the bank |
| --- | --- | --- | --- | --- |
| shivam30 | 30 | 30 | 0 | 30 |
| variations300 | 300 | 300 | 0 | 300 |
| open300 | 300 | 300 | 0 | 300 |
| ripple200 | 200 | 200 | 0 | 200 |
| reddit200 | 0 | 0 | 0 | 0 |
| **total** | 830 | 830 | 0 | 830 |

Unique cases: **830**. Originals kept: **30**. Duplicate rows merged: **0**. No two rows are the same case once the naming / style / edge / period-label separations are applied: no two source banks share an entity+period at all, and inside a bank the ten variations deliberately change the entity, the wording dimension or the period label. The dedupe still runs on every build; the fake Reddit check proves it merges when a real duplicate appears.

## 2. How the merge works

- One common schema: `mid`, `source_bank`, `source_qid`, `question`, `entities`, `entity_level`, `family` (primary, 1-20) + `families`, `archetype`, `template`, `period`, `as_of`, `answer_kind`, `rubric` (evidence / steps / forbidden / ground truth), `coverage` (verdict / note / gap), `chain` (ripple only), `style`, `naming_variant`, `edge_case`, `regression`, `duplicates`.
- Missing fields stay null. Shivam's 30 originals keep their text as written: QA1-QA10 from `QA10_BRIEF.md`; DBQ1-DBQ5 and Q11-Q25 use the documented short form in `QUERY_TEMPLATES` §5 because no fuller copy exists in the repo (`eval25_key.md` is absent).
- Layer 1, near-duplicate text: case-folding, punctuation and numbers removed, token Jaccard >= 0.80, and only between rows with the same entity, period, family, style and naming/edge dimension. A templated question on a different company is a different case and is never merged.
- Layer 2, same case: same template + entity level + evidence shape + entity + period, even with different wording. Banks without an explicit template id (open, ripple) also need 0.50 wording similarity to confirm it is the same case; the archetype alone (A01, R01) is a family, not a template.
- Kept separate by design: naming variants (ISIN / BSE code / old symbol), style variants (terse / Hinglish / as-of), edge cases that ask for a refusal (`NOT IN DATA`), and period-label variants (V6), because each tests a different robustness dimension. One representative per case, chosen as the richest rubric with a ground truth, with originals first.
- `style` is classified by rule: bank Hinglish flag or >=2 Hindi function words -> Hinglish; `as of` / point-in-time wording or a V9 variation -> point-in-time; <=10 words or a V4 variation -> terse; else natural.
- Ripple rows carry no family in their bank. They are shown under `family_inferred` (R01->16, R02->18, R03->16, R04->18, R05->17, R06->17, R07->12, R08->20, R09->11, R10->9) and marked `(inferred)`. `family` itself stays null for those rows.

## 3. Coverage matrix

### 3.1 family x entity level x style

Each cell is `cases (terse/natural/Hinglish/point-in-time)`.

| family | stock | industry | sector | theme | index | market-cap bucket | price band | policy | macro | market-wide | total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 114 (17/68/13/16) | 11 (0/11/0/0) | . | . | 11 (0/11/0/0) | . | . | . | . | . | 136 |
| 2 | 116 (18/59/13/26) | 9 (0/7/0/2) | . | . | 15 (0/12/1/2) | . | . | . | . | . | 140 |
| 3 | 15 (1/12/1/1) | . | . | . | . | . | . | . | . | . | 15 |
| 4 | . | 10 (2/6/1/1) | . | . | 1 (0/1/0/0) | . | . | . | . | . | 11 |
| 5 | . | . | . | . | . | . | . | . | . | . | 0 |
| 6 | 18 (4/10/2/2) | 26 (4/14/2/6) | . | 19 (4/11/2/2) | 7 (0/6/0/1) | . | . | 18 (4/10/2/2) | . | . | 88 |
| 7 | . | . | . | . | . | . | . | . | . | . | 0 |
| 8 | . | . | . | . | . | . | . | . | . | . | 0 |
| 9* | 35 (1/33/1/0) | . | . | . | . | . | . | . | . | . | 35 |
| 10 | . | . | . | . | . | . | . | . | . | . | 0 |
| 11* | 20 (0/12/0/8) | . | . | . | . | . | . | . | . | . | 20 |
| 12* | 49 (2/44/3/0) | 1 (0/1/0/0) | . | . | . | . | . | . | . | . | 50 |
| 13 | 15 (1/10/4/0) | . | . | . | . | . | . | . | . | . | 15 |
| 14 | 45 (4/37/4/0) | . | . | . | . | . | . | . | . | . | 45 |
| 15 | 16 (2/13/1/0) | . | . | . | 13 (0/11/2/0) | . | . | 1 (0/1/0/0) | . | . | 30 |
| 16* | 85 (3/76/6/0) | . | . | . | . | . | . | . | . | . | 85 |
| 17* | 55 (1/53/1/0) | . | . | . | . | . | . | . | . | . | 55 |
| 18* | 55 (1/52/2/0) | . | . | . | . | . | . | . | . | . | 55 |
| 19 | 15 (1/12/2/0) | . | . | . | . | . | . | . | . | . | 15 |
| 20* | 31 (6/25/0/0) | . | . | . | 4 (0/4/0/0) | . | . | . | . | . | 35 |
| **total** | 684 | 57 | 0 | 19 | 51 | 0 | 0 | 19 | 0 | 0 | 830 |

`*` includes cases whose family is inferred from a ripple archetype.

### 3.2 family x style

| family | terse | natural | Hinglish | point-in-time | total |
| --- | --- | --- | --- | --- | --- |
| 1 | 17 | 90 | 13 | 16 | 136 |
| 2 | 18 | 78 | 14 | 30 | 140 |
| 3 | 1 | 12 | 1 | 1 | 15 |
| 4 | 2 | 7 | 1 | 1 | 11 |
| 5 | . | . | . | . | 0 |
| 6 | 16 | 51 | 8 | 13 | 88 |
| 7 | . | . | . | . | 0 |
| 8 | . | . | . | . | 0 |
| 9 | 1 | 33 | 1 | . | 35 |
| 10 | . | . | . | . | 0 |
| 11 | . | 12 | . | 8 | 20 |
| 12 | 2 | 45 | 3 | . | 50 |
| 13 | 1 | 10 | 4 | . | 15 |
| 14 | 4 | 37 | 4 | . | 45 |
| 15 | 2 | 25 | 3 | . | 30 |
| 16 | 3 | 76 | 6 | . | 85 |
| 17 | 1 | 53 | 1 | . | 55 |
| 18 | 1 | 52 | 2 | . | 55 |
| 19 | 1 | 12 | 2 | . | 15 |
| 20 | 6 | 29 | . | . | 35 |
| **total** | 76 | 622 | 63 | 69 | 830 |

### 3.3 Empty and thin cells (fewer than 3 cases)

| family | level | cases | status |
| --- | --- | --- | --- |
| 2 | sector | 0 | empty |
| 2 | theme | 0 | empty |
| 2 | market-cap bucket | 0 | empty |
| 2 | price band | 0 | empty |
| 2 | policy | 0 | empty |
| 2 | macro | 0 | empty |
| 2 | market-wide | 0 | empty |
| 1 | sector | 0 | empty |
| 1 | theme | 0 | empty |
| 1 | market-cap bucket | 0 | empty |
| 1 | price band | 0 | empty |
| 1 | policy | 0 | empty |
| 1 | macro | 0 | empty |
| 1 | market-wide | 0 | empty |
| 6 | sector | 0 | empty |
| 6 | market-cap bucket | 0 | empty |
| 6 | price band | 0 | empty |
| 6 | macro | 0 | empty |
| 6 | market-wide | 0 | empty |
| 16 | industry | 0 | empty |
| 16 | sector | 0 | empty |
| 16 | theme | 0 | empty |
| 16 | index | 0 | empty |
| 16 | market-cap bucket | 0 | empty |
| 16 | price band | 0 | empty |
| 16 | policy | 0 | empty |
| 16 | macro | 0 | empty |
| 16 | market-wide | 0 | empty |
| 17 | industry | 0 | empty |
| 18 | industry | 0 | empty |
| 17 | sector | 0 | empty |
| 18 | sector | 0 | empty |
| 17 | theme | 0 | empty |
| 18 | theme | 0 | empty |
| 17 | index | 0 | empty |
| 18 | index | 0 | empty |
| 17 | market-cap bucket | 0 | empty |
| 18 | market-cap bucket | 0 | empty |
| 17 | price band | 0 | empty |
| 18 | price band | 0 | empty |
| 17 | policy | 0 | empty |
| 18 | policy | 0 | empty |
| 17 | macro | 0 | empty |
| 18 | macro | 0 | empty |
| 17 | market-wide | 0 | empty |
| 18 | market-wide | 0 | empty |
| 12 | sector | 0 | empty |
| 12 | theme | 0 | empty |
| 12 | index | 0 | empty |
| 12 | market-cap bucket | 0 | empty |
| 12 | price band | 0 | empty |
| 12 | policy | 0 | empty |
| 12 | macro | 0 | empty |
| 12 | market-wide | 0 | empty |
| 12 | industry | 1 | thin |
| 14 | industry | 0 | empty |
| 14 | sector | 0 | empty |
| 14 | theme | 0 | empty |
| 14 | index | 0 | empty |
| 14 | market-cap bucket | 0 | empty |
| 14 | price band | 0 | empty |
| 14 | policy | 0 | empty |
| 14 | macro | 0 | empty |
| 14 | market-wide | 0 | empty |
| 9 | industry | 0 | empty |
| 20 | industry | 0 | empty |
| 9 | sector | 0 | empty |
| 20 | sector | 0 | empty |
| 9 | theme | 0 | empty |
| 20 | theme | 0 | empty |
| 9 | index | 0 | empty |
| 9 | market-cap bucket | 0 | empty |
| 20 | market-cap bucket | 0 | empty |
| 9 | price band | 0 | empty |
| 20 | price band | 0 | empty |
| 9 | policy | 0 | empty |
| 20 | policy | 0 | empty |
| 9 | macro | 0 | empty |
| 20 | macro | 0 | empty |
| 9 | market-wide | 0 | empty |
| 20 | market-wide | 0 | empty |
| 15 | industry | 0 | empty |
| 15 | sector | 0 | empty |
| 15 | theme | 0 | empty |
| 15 | market-cap bucket | 0 | empty |
| 15 | price band | 0 | empty |
| 15 | macro | 0 | empty |
| 15 | market-wide | 0 | empty |
| 15 | policy | 1 | thin |
| 11 | industry | 0 | empty |
| 11 | sector | 0 | empty |
| 11 | theme | 0 | empty |
| 11 | index | 0 | empty |
| 11 | market-cap bucket | 0 | empty |
| 11 | price band | 0 | empty |
| 11 | policy | 0 | empty |
| 11 | macro | 0 | empty |
| 11 | market-wide | 0 | empty |
| 3 | industry | 0 | empty |
| 13 | industry | 0 | empty |
| 19 | industry | 0 | empty |
| 3 | sector | 0 | empty |
| 13 | sector | 0 | empty |
| 19 | sector | 0 | empty |
| 3 | theme | 0 | empty |
| 13 | theme | 0 | empty |
| 19 | theme | 0 | empty |
| 3 | index | 0 | empty |
| 13 | index | 0 | empty |
| 19 | index | 0 | empty |
| 3 | market-cap bucket | 0 | empty |
| 13 | market-cap bucket | 0 | empty |
| 19 | market-cap bucket | 0 | empty |
| 3 | price band | 0 | empty |
| 13 | price band | 0 | empty |
| 19 | price band | 0 | empty |
| 3 | policy | 0 | empty |
| 13 | policy | 0 | empty |
| 19 | policy | 0 | empty |
| 3 | macro | 0 | empty |
| 13 | macro | 0 | empty |
| 19 | macro | 0 | empty |
| 3 | market-wide | 0 | empty |
| 13 | market-wide | 0 | empty |
| 19 | market-wide | 0 | empty |
| 4 | stock | 0 | empty |
| 4 | sector | 0 | empty |
| 4 | theme | 0 | empty |
| 4 | market-cap bucket | 0 | empty |
| 4 | price band | 0 | empty |
| 4 | policy | 0 | empty |
| 4 | macro | 0 | empty |
| 4 | market-wide | 0 | empty |
| 4 | index | 1 | thin |
| 5 | stock | 0 | empty |
| 7 | stock | 0 | empty |
| 8 | stock | 0 | empty |
| 10 | stock | 0 | empty |
| 5 | industry | 0 | empty |
| 7 | industry | 0 | empty |
| 8 | industry | 0 | empty |
| 10 | industry | 0 | empty |
| 5 | sector | 0 | empty |
| 7 | sector | 0 | empty |
| 8 | sector | 0 | empty |
| 10 | sector | 0 | empty |
| 5 | theme | 0 | empty |
| 7 | theme | 0 | empty |
| 8 | theme | 0 | empty |
| 10 | theme | 0 | empty |
| 5 | index | 0 | empty |
| 7 | index | 0 | empty |
| 8 | index | 0 | empty |
| 10 | index | 0 | empty |
| 5 | market-cap bucket | 0 | empty |
| 7 | market-cap bucket | 0 | empty |
| 8 | market-cap bucket | 0 | empty |
| 10 | market-cap bucket | 0 | empty |
| 5 | price band | 0 | empty |
| 7 | price band | 0 | empty |
| 8 | price band | 0 | empty |
| 10 | price band | 0 | empty |
| 5 | policy | 0 | empty |
| 7 | policy | 0 | empty |
| 8 | policy | 0 | empty |
| 10 | policy | 0 | empty |
| 5 | macro | 0 | empty |
| 7 | macro | 0 | empty |
| 8 | macro | 0 | empty |
| 10 | macro | 0 | empty |
| 5 | market-wide | 0 | empty |
| 7 | market-wide | 0 | empty |
| 8 | market-wide | 0 | empty |
| 10 | market-wide | 0 | empty |
### 3.4 The full 3D grid

The full 3D grid has **800** cells (20 families x 10 levels x 4 styles): **722** empty, **33** thin (1-2 cases), **45** with 3 or more cases.

### 3.5 Style gaps inside a family

| family | missing style |
| --- | --- |
| 9 | point-in-time |
| 11 | terse, Hinglish |
| 12 | point-in-time |
| 13 | point-in-time |
| 14 | point-in-time |
| 15 | point-in-time |
| 16 | point-in-time |
| 17 | point-in-time |
| 18 | point-in-time |
| 19 | point-in-time |
| 20 | Hinglish, point-in-time |

## 4. One table per family

### Family 1 - Lookup (136 cases)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0001 | shivam30:DBQ1 | stock | terse | - | AEROFLEX products + close on a date |
| MB0002 | shivam30:DBQ2 | stock | terse | - | 532627 latest AR: control change |
| MB0003 | shivam30:DBQ3 | stock | terse | - | 544161 business + segments |
| MB0005 | shivam30:DBQ5 | stock | terse | - | DEEDEV Aug-2026 concall remark |
| MB0009 | shivam30:Q14 | stock | terse | - | VISHNU Note 5 of latest results + geo split |
| MB0023 | shivam30:QA3 | stock | natural | - | How many manufacturing facilities does Ganesha Ecosphere have, per its investor presentation of 5 August 2026? |
| MB0024 | shivam30:QA4 | stock | natural | - | What are the key products of Chemcon Speciality Chemicals per its investor presentation of 22 May 2026, and whom did it mention as acquired for inorganic growth? |
| MB0026 | shivam30:QA6 | stock | natural | - | What did BSE: 540879 show on page 21 (of 79) of its investor presentation dated 24 October 2026 regarding a licence to manufacture? |
| MB0027 | shivam30:QA7 | stock | natural | - | What did ISIN INE864I01014 say about its fuel-cell capacity expansion due to complete by the end of this year, per its transcript of 6 August 2026? |
| MB0029 | shivam30:QA9 | stock | point-in-time | - | What did NSE: SAILIFE say about its newly commissioned facilities, as of the latest data? |
| MB0030 | shivam30:QA10 | stock | natural | - | Per the transcript of 18 September 2026 of 540678 / COCHINSHIP: what did it say about the MOU with HD KSOE, and how will EBITDA margins progress from electric tug boats, ... |
| MB0031 | variations300:DBQ1-V1 | stock | natural | yes | What does Hariom Pipe Industries (NSE: HARIOMPIPE) make, and what was its NSE close on 16 October 2026? |
| MB0032 | variations300:DBQ1-V2 | stock | natural | yes | What does RTS Power Corporation (NSE: RTSPOWR) make, and what was its NSE close on 16 October 2026? |
| MB0033 | variations300:DBQ1-V3 | stock | natural | yes | What does NSE: AMIORG (now ACUTAAS) make, and what was its NSE close on 16 October 2026? |
| MB0034 | variations300:DBQ1-V4 | stock | terse | yes | RELIANCE products + close 16 Oct 2026 |
| MB0035 | variations300:DBQ1-V5 | stock | Hinglish | yes | Bhai, KRBL (NSE: KRBL) kya banati hai, aur 16 October 2026 ko NSE par kitne pe close hui? Products aur close dono batao, short mein. |
| MB0036 | variations300:DBQ1-V6 | stock | natural | yes | What does SETUINFRA (BSE: 533605) make, and what was its BSE close on 30 September 2026? |
| MB0037 | variations300:DBQ1-V7 | industry | natural | yes | For all listed companies in Industrial Products, list what each company makes and its NSE close on 16 October 2026. |
| MB0038 | variations300:DBQ1-V8 | index | natural | partial | For the NIFTY TOTAL MARKET constituents, list what each company makes and its NSE close on 16 October 2026. |
| MB0039 | variations300:DBQ1-V9 | stock | point-in-time | yes | As of 30 June 2026, what did Protean eGov Technologies (NSE: PROTEAN)'s latest annual report say it makes, and what was its close that day? |
| MB0040 | variations300:DBQ1-V10 | stock | natural | yes | What does Life Insurance Corporation Of India (NSE: LICI) make, and what was its NSE close on 16 October 2026? If either is not in our data, answer NOT IN DATA and say wh... |
| MB0041 | variations300:DBQ2-V1 | stock | natural | yes | What did CESC (NSE: CESC)'s latest annual report (FY2026) disclose about a change in ownership or control, and where in the report? |
| MB0042 | variations300:DBQ2-V2 | stock | natural | yes | What did Reliance Infrastructure (NSE: RELINFRA)'s latest annual report (FY2026) disclose about a change in ownership or control, and where in the report? |
| MB0043 | variations300:DBQ2-V3 | stock | natural | yes | What did NSE: SHIL (now HINDWAREAP)'s latest annual report (FY2026) disclose about a change in ownership or control, and where in the report? |
| MB0044 | variations300:DBQ2-V4 | stock | terse | partial | 570002 latest annual report control change |
| MB0045 | variations300:DBQ2-V5 | stock | Hinglish | yes | JSW Steel (NSE: JSWSTEEL) ke latest annual report mein ownership ya control change ke baare mein kya likha hai? Kaunsa saal, kaunsa page, aur exactly kya disclosure hai? |
| MB0046 | variations300:DBQ2-V6 | stock | natural | yes | What did Craftsman Automation (NSE: CRAFTSMAN)'s latest annual report (FY2025) disclose about a change in ownership or control, and where in the report? |
| MB0047 | variations300:DBQ2-V7 | industry | natural | yes | For all listed companies in Power, which companies disclosed a change in control or ownership in their latest annual report, and what changed? |
| MB0048 | variations300:DBQ2-V8 | index | natural | partial | For the NIFTY 500 constituents, which companies disclosed a change in control or ownership in their latest annual report, and what changed? |
| MB0049 | variations300:DBQ2-V9 | stock | point-in-time | yes | As of 30 June 2026, what did Prism Johnson (NSE: PRSMJOHNSN)'s latest filed annual report say about a change in control or ownership? |
| MB0050 | variations300:DBQ2-V10 | stock | natural | no | What did Aakash Exploration Services (NSE: AAKASH)'s latest annual report disclose about a change in control? If no annual report is held for it, answer NOT IN DATA and n... |
| MB0051 | variations300:DBQ3-V1 | stock | natural | partial | What is Asian Granito India (NSE: ASIANTILES)'s business, and what segments and segment revenue did it report for the latest quarter? |
| MB0052 | variations300:DBQ3-V2 | stock | natural | no | What is Asian Paints (NSE: ASIANPAINT)'s business, and what segments and segment revenue did it report for the latest quarter? |
| MB0053 | variations300:DBQ3-V3 | stock | natural | partial | What is NSE: PVR (now PVRINOX)'s business, and what segments and segment revenue did it report for the latest quarter? |
| MB0054 | variations300:DBQ3-V4 | stock | terse | no | DHARMAJ business segments FY26 |
| MB0055 | variations300:DBQ3-V5 | stock | Hinglish | partial | Highway Infrastructure (NSE: HILINFRA) ka business kya hai aur segments kaunse hain? Annual report aur latest results ke hisaab se segment revenue bhi batao. |
| MB0056 | variations300:DBQ3-V6 | stock | natural | no | What is Antony Waste Handling Cell (NSE: AWHCL)'s business, and what segments and segment revenue did it report for the latest quarter? |
| MB0057 | variations300:DBQ3-V7 | industry | natural | partial | For all listed companies in Consumer Durables, what are the reported business segments and their latest segment revenue? |
| MB0058 | variations300:DBQ3-V8 | index | natural | partial | For the NIFTY500 EQUAL WEIGHT constituents, what are the reported business segments and their latest segment revenue? |
| MB0059 | variations300:DBQ3-V9 | stock | point-in-time | yes | As of 30 June 2026, what did Arvind (NSE: ARVIND)'s latest results and annual report disclose about its business and segments? |
| MB0060 | variations300:DBQ3-V10 | stock | natural | no | For 20 Microns (NSE: 20MICRONS), what are its business segments and segment revenue for Q1FY27? If segment disclosure is not in the data, answer NOT IN DATA and say which... |
| MB0071 | variations300:DBQ5-V1 | stock | natural | yes | What did Jash Engineering (NSE: JASH)'s management say about demand and margins on its 18 August 2026 earnings call, and who said it? |
| MB0072 | variations300:DBQ5-V2 | stock | natural | partial | What did CG Power and Industrial Solutions (NSE: CGPOWER)'s management say about demand and margins on its 12 May 2025 earnings call, and who said it? |
| MB0073 | variations300:DBQ5-V3 | stock | natural | partial | What did NSE: SUVENPHAR (now COHANCE)'s management say about demand and margins on its 15 May 2026 earnings call, and who said it? |
| MB0074 | variations300:DBQ5-V4 | stock | terse | partial | DABUR call 2025-02-04 management outlook |
| MB0075 | variations300:DBQ5-V5 | stock | Hinglish | partial | Mahanagar Gas (NSE: MGL) ki 16 February 2026 wali earnings call mein management ne business aur margin outlook ke baare mein kya kaha? Speaker ka naam aur quote batao. |
| MB0076 | variations300:DBQ5-V6 | stock | natural | partial | What did LEAP India (NSE: LEAPIND)'s management say about demand and margins on its 4 September 2026 earnings call, and who said it? |
| MB0077 | variations300:DBQ5-V7 | industry | natural | no | For all listed companies in Industrial Manufacturing, what did management say about demand and margins on their latest earnings calls, with quoted evidence? |
| MB0078 | variations300:DBQ5-V8 | index | natural | partial | For the NIFTY500 MULTICAP 50:25:25 constituents, what did management say about demand and margins on their latest earnings calls, with quoted evidence? |
| MB0079 | variations300:DBQ5-V9 | stock | point-in-time | yes | As of 31 July 2026, what had Concord Enviro Systems (NSE: CEWATER)'s management last said on an earnings call about demand and margins? |
| MB0080 | variations300:DBQ5-V10 | stock | natural | no | What did 21st Century Management Services (NSE: 21STCENMGM) say about demand and margins on its 13 August 2026 earnings call? If the transcript is held but not chunked, a... |
| MB0111 | variations300:Q14-V1 | stock | natural | partial | Note 5 of Diligent Media Corporation (NSE: DNAMEDIA)'s Q1FY27 results — what does it say, and what is the geographic revenue split, consolidated? |
| MB0112 | variations300:Q14-V2 | stock | natural | partial | Note 5 of GTL (NSE: GTL)'s Q1FY27 results — what does it say, and what is the geographic revenue split, consolidated? |
| MB0113 | variations300:Q14-V3 | stock | natural | yes | Note 5 of NSE: ADANIGAS (now ATGL)'s Q1FY27 results — what does it say, and what is the geographic revenue split, consolidated? |
| MB0114 | variations300:Q14-V4 | stock | terse | partial | RACE results note 5 geo split Q1FY27 |
| MB0115 | variations300:Q14-V5 | stock | Hinglish | partial | Balmer Lawrie & Company (NSE: BALMLAWRIE) ke Q1FY27 results ki note 5 mein kya likha hai, aur geographic revenue split kya hai? Consolidated basis, quote ke saath. |
| MB0116 | variations300:Q14-V6 | stock | natural | partial | Note 5 of Gloster (NSE: GLOSTERLTD)'s Q4FY26 (January-March 2026) results — what does it say, and what is the geographic revenue split, consolidated? |
| MB0117 | variations300:Q14-V7 | industry | natural | yes | For all listed companies in the industry, which companies disclose a geographic revenue split in their results notes for Q1FY27, and what is it? |
| MB0118 | variations300:Q14-V8 | index | natural | partial | For the NIFTY IPO constituents, which companies disclose a geographic revenue split in their results notes for Q1FY27, and what is it? |
| MB0119 | variations300:Q14-V9 | stock | point-in-time | partial | As of 30 June 2026, what did note 5 of Oil Country Tubular (NSE: OILCOUNTUB)'s as of 30 June 2026 results say, and what was its geographic split? |
| MB0120 | variations300:Q14-V10 | stock | natural | no | What does note 5 of NMDC (NSE: NMDC)'s results for Q2FY25 (July-September 2024) say, and what is the geographic split? If that quarter's results notes are not stored, ans... |
| MB0251 | variations300:QA3-V1 | stock | natural | yes | How many manufacturing facilities does Iris Clothings (NSE: IRISDOREME) report in its investor presentation dated 27 July 2026, and where are they? |
| MB0252 | variations300:QA3-V2 | stock | natural | yes | How many manufacturing facilities does K.P.R. Mill (NSE: KPRMILL) report in its investor presentation dated 13 August 2026, and where are they? |
| MB0253 | variations300:QA3-V3 | stock | natural | yes | How many manufacturing facilities does NSE: ARISINFRA (now ARIS) report in its investor presentation dated 5 August 2026, and where are they? |
| MB0254 | variations300:QA3-V4 | stock | terse | yes | BSE facilities deck 2026-08-04 |
| MB0255 | variations300:QA3-V5 | stock | Hinglish | yes | Prime Focus (NSE: PFOCUS) ke 29 September 2026 wale investor presentation ke hisaab se kitni manufacturing facilities hain, aur kahan? Slide ka reference bhi do. |
| MB0256 | variations300:QA3-V6 | stock | natural | yes | How many manufacturing facilities does Vodafone Idea (NSE: IDEA) report in its investor presentation dated 30 June 2026, and where are they? |
| MB0257 | variations300:QA3-V7 | industry | natural | partial | For all listed companies in Textiles & Apparels, how many manufacturing facilities does each company report in its latest investor presentation? |
| MB0258 | variations300:QA3-V8 | index | natural | partial | For the NIFTY MIDSMALLCAP400 50:50 constituents, how many manufacturing facilities does each company report in its latest investor presentation? |
| MB0259 | variations300:QA3-V9 | stock | point-in-time | yes | As of 31 July 2026, how many manufacturing facilities did 3M India (NSE: 3MINDIA) report in its latest deck filed by that date? |
| MB0260 | variations300:QA3-V10 | stock | natural | no | How many manufacturing facilities does 21st Century Management Services (NSE: 21STCENMGM) report in its investor presentation dated 25 February 2022? If no deck is stored... |
| MB0261 | variations300:QA4-V1 | stock | natural | yes | Per POCL Enterprises (NSE: POEL)'s deck of 14 August 2026, what are its key products, and which company did it mention as acquired for inorganic growth? |
| MB0262 | variations300:QA4-V2 | stock | natural | yes | Per Gujarat Fluorochemicals (NSE: FLUOROCHEM)'s deck of 12 August 2026, what are its key products, and which company did it mention as acquired for inorganic growth? |
| MB0263 | variations300:QA4-V3 | stock | natural | yes | Per NSE: GLS (now ALIVUS)'s deck of 30 July 2026, what are its key products, and which company did it mention as acquired for inorganic growth? |
| MB0264 | variations300:QA4-V4 | stock | terse | partial | ANDHRAPAP products acquisitions deck 2025-02-08 |
| MB0265 | variations300:QA4-V5 | stock | Hinglish | yes | Bharat Petroleum Corporation (NSE: BPCL) ke 22 July 2026 wale deck mein main products kya hain, aur inorganic growth ke liye kis company ka acquisition mention kiya gaya ... |
| MB0266 | variations300:QA4-V6 | stock | natural | yes | Per Bikaji Foods International (NSE: BIKAJI)'s deck of 21 May 2026, what are its key products, and which company did it mention as acquired for inorganic growth? |
| MB0267 | variations300:QA4-V7 | industry | natural | yes | For all listed companies in Chemicals & Petrochemicals, what products and acquisitions does each company report in its latest investor presentation? |
| MB0268 | variations300:QA4-V8 | index | natural | partial | For the NIFTY500 AHIMSA constituents, what products and acquisitions does each company report in its latest investor presentation? |
| MB0269 | variations300:QA4-V9 | stock | point-in-time | yes | As of 30 June 2026, what did Jaro Institute of Technology Management and Research (NSE: JARO)'s latest deck disclose about its products and acquisitions? |
| MB0270 | variations300:QA4-V10 | stock | natural | no | What are 21st Century Management Services (NSE: 21STCENMGM)'s key products and its latest acquisition? If the deck is held but the page text is not extracted, answer NOT ... |
| MB0281 | variations300:QA6-V1 | stock | natural | yes | What does page 10 of Data Patterns (India) (NSE: DATAPATTNS)'s investor presentation dated 30 July 2026 say about its manufacturing licence or capacity? |
| MB0282 | variations300:QA6-V2 | stock | natural | no | What does page 3 of Hitachi Energy India (NSE: POWERINDIA)'s investor presentation dated 16 September 2026 say about its manufacturing licence or capacity? |
| MB0283 | variations300:QA6-V3 | stock | natural | yes | What does page 24 of NSE: AMIRCHAND (now AEROPLANE)'s investor presentation dated 7 August 2026 say about its manufacturing licence or capacity? |
| MB0284 | variations300:QA6-V4 | stock | terse | yes | REFEX deck page 31 2026-07-29 |
| MB0285 | variations300:QA6-V5 | stock | Hinglish | yes | Bodhi Tree Multimedia (NSE: BTML) ke 14 August 2026 wale investor presentation ke page 5 par kya dikhaya gaya hai? Text ya quote ke saath batao. |
| MB0286 | variations300:QA6-V6 | stock | natural | yes | What does page 18 of DCM Shriram (NSE: DCMSHRIRAM)'s investor presentation dated 13 May 2026 say about its manufacturing licence or capacity? |
| MB0287 | variations300:QA6-V7 | industry | natural | yes | For all listed companies in Aerospace & Defense, what do the latest decks say on their capacity or licensing slides? |
| MB0288 | variations300:QA6-V8 | index | natural | partial | For the NIFTY SMALLCAP 250 constituents, what do the latest decks say on their capacity or licensing slides? |
| MB0289 | variations300:QA6-V9 | stock | point-in-time | yes | As of 30 September 2026, what did page 27 of Magnum Ventures (NSE: MAGNUM)'s latest deck filed by that date say? |
| MB0290 | variations300:QA6-V10 | stock | natural | no | What does page 41 of Capital Trust (NSE: CAPTRUST)'s investor presentation dated 18 August 2026 say? If the deck has fewer pages, answer NOT IN DATA and give the page cou... |
| MB0291 | variations300:QA7-V1 | stock | natural | yes | What did Azad Engineering (NSE: AZAD) say about its capacity expansion, and the completion timeline, on its 14 August 2026 earnings call? |
| MB0292 | variations300:QA7-V2 | stock | natural | partial | What did ABB India (NSE: ABB) say about its capacity expansion, and the completion timeline, on its 16 May 2025 earnings call? |
| MB0293 | variations300:QA7-V3 | stock | natural | yes | What did NSE: IDFCBANK (now IDFCFIRSTB) say about its capacity expansion, and the completion timeline, on its 31 July 2026 earnings call? |
| MB0294 | variations300:QA7-V4 | stock | terse | yes | ENTERO capacity timeline call 2026-08-17 |
| MB0295 | variations300:QA7-V5 | stock | Hinglish | yes | Max Healthcare Institute (NSE: MAXHEALTH) ne apni 20 August 2026 wali call mein capacity expansion ka kya timeline bataya? Completion date aur capex ke saath quote do. |
| MB0296 | variations300:QA7-V6 | stock | natural | yes | What did Affle 3i (NSE: AFFLE) say about its capacity expansion, and the completion timeline, on its 18 May 2026 earnings call? |
| MB0297 | variations300:QA7-V7 | industry | natural | yes | For all listed companies in Electrical Equipment, what capacity-expansion timelines did management give on their latest earnings calls? |
| MB0298 | variations300:QA7-V8 | index | natural | no | For the NIFTY MICROCAP 250 constituents, what capacity-expansion timelines did management give on their latest earnings calls? |
| MB0299 | variations300:QA7-V9 | stock | point-in-time | yes | As of 31 July 2026, what had Arvind SmartSpaces (NSE: ARVSMART) said about its capacity expansion timeline by that date? |
| MB0300 | variations300:QA7-V10 | stock | natural | no | What did 21st Century Management Services (NSE: 21STCENMGM) say about its capacity expansion timeline on 6 August 2025? If the transcript exists but is not chunked, answe... |
| MB0311 | variations300:QA9-V1 | stock | point-in-time | yes | What did Onesource Specialty Pharma (NSE: ONESOURCE) say about its newly commissioned facilities, as of the latest data, and in which document type? |
| MB0312 | variations300:QA9-V2 | stock | point-in-time | yes | What did Cipla (NSE: CIPLA) say about its newly commissioned facilities, as of the latest data, and in which document type? |
| MB0313 | variations300:QA9-V3 | stock | point-in-time | yes | What did NSE: MFL (now EPIGRAL) say about its newly commissioned facilities, as of the latest data, and in which document type? |
| MB0314 | variations300:QA9-V4 | stock | terse | yes | RAILTEL newly commissioned facilities latest |
| MB0315 | variations300:QA9-V5 | stock | Hinglish | yes | R K Swamy (NSE: RKSWAMY) ne apni nayi commissioned facilities ke baare mein sabse latest kya kaha hai? Deck, concall aur annual report teeno check karke source do. |
| MB0316 | variations300:QA9-V6 | stock | point-in-time | yes | What did Enviro Infra Engineers (NSE: EIEL) say about its newly commissioned facilities, as of the latest data, and in which document type? |
| MB0317 | variations300:QA9-V7 | industry | natural | yes | For all listed companies in Pharmaceuticals & Biotechnology, what have the companies said about newly commissioned facilities across decks, calls and annual reports? |
| MB0318 | variations300:QA9-V8 | index | natural | partial | For the NIFTY500 SHARIAH constituents, what have the companies said about newly commissioned facilities across decks, calls and annual reports? |
| MB0319 | variations300:QA9-V9 | stock | point-in-time | yes | As of 30 June 2026, what had Kuantum Papers (NSE: KUANTUM) said about its newly commissioned facilities, using only documents known by that date? |
| MB0320 | variations300:QA9-V10 | stock | natural | no | What has 21st Century Management Services (NSE: 21STCENMGM) said about its newly commissioned facilities? If no document after since Jan 2026 is held, answer NOT IN DATA ... |
| MB0321 | variations300:QA10-V1 | stock | natural | yes | Per Jupiter Wagons (NSE: JWL)'s 21 August 2026 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? |
| MB0322 | variations300:QA10-V2 | stock | natural | yes | Per Ashok Leyland (NSE: ASHOKLEY)'s 21 August 2026 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? |
| MB0323 | variations300:QA10-V3 | stock | natural | yes | Per NSE: CENTURYTEX (now ABREL)'s 20 August 2026 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? |
| MB0324 | variations300:QA10-V4 | stock | terse | yes | HINDPETRO mou margin path call 2026-07-29 |
| MB0325 | variations300:QA10-V5 | stock | Hinglish | partial | L&T Technology Services (NSE: LTTS) ki 24 October 2025 wali call mein MOU partner kaun hai, aur EBITDA margin ka path kya bataya gaya? Plan aur numbers quote karo. |
| MB0326 | variations300:QA10-V6 | stock | natural | partial | Per Raymond Lifestyle (NSE: RAYMONDLSL)'s 4 November 2025 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? |
| MB0327 | variations300:QA10-V7 | industry | natural | no | For all listed companies in Industrial Manufacturing, what MOUs or partnerships and margin paths did management disclose on their latest calls? |
| MB0328 | variations300:QA10-V8 | index | natural | partial | For the NIFTY MIDCAP 150 constituents, what MOUs or partnerships and margin paths did management disclose on their latest calls? |
| MB0329 | variations300:QA10-V9 | stock | point-in-time | yes | As of 30 September 2026, what had Ecos (India) Mobility & Hospitality (NSE: ECOSMOBLTY) disclosed about its MOU and margin path? |
| MB0330 | variations300:QA10-V10 | stock | natural | no | What did 21st Century Management Services (NSE: 21STCENMGM) say about its MOU and EBITDA margin path on 1 August 2026? If the call is not held for that date, answer NOT I... |
| MB0556 | open300:A16-01 | stock | natural | partial | Which companies raised a QIP in FY26, and did the actual use of proceeds match the stated objects? |
| MB0557 | open300:A16-02 | stock | natural | partial | Is Polycab's capex funded by debt or internal accruals, and how does the disclosure show it? |
| MB0558 | open300:A16-03 | stock | natural | yes | Trent did a 1:2 bonus with ex-date 4 June 2026. What does that do to the EPS series, and how should a price chart treat it? |
| MB0559 | open300:A16-04 | stock | natural | partial | Suzlon has been cutting debt while spending on capacity. Which came first in the cash flow, and is the deleveraging real? |
| MB0560 | open300:A16-05 | stock | natural | partial | RVNL and NBCC are asset-light but cash-hungry. How do they fund working capital, and what does that do to return on capital? |
| MB0561 | open300:A16-06 | stock | natural | partial | Which companies put money into a subsidiary or JV last year, and was it disclosed as a related-party transaction? |
| MB0562 | open300:A16-07 | stock | natural | partial | ITC and Colgate pay out most of their earnings. Is the payout covered by free cash flow, and what is left for growth? |
| MB0563 | open300:A16-08 | stock | terse | partial | buyback vs dividend choices FY26 |
| MB0564 | open300:A16-09 | stock | natural | partial | UltraTech bought India Cements and Kesoram. How was the acquisition funded, and what did it do to net debt/EBITDA? |
| MB0565 | open300:A16-10 | stock | natural | partial | Cochin Shipyard's ISRF JV needs capital. What is the committed amount, and who funds it? |
| MB0566 | open300:A16-11 | stock | Hinglish | partial | Tata Power ka renewable capex debt se fund ho raha hai ya internal accruals se? (Hinglish) |
| MB0567 | open300:A16-12 | stock | natural | partial | JSW Steel's acquisitions added debt. Did the leverage ratio stay within the stated ceiling, and what did management say? |
| MB0568 | open300:A16-13 | stock | natural | partial | Angel One earns float income on client funds. How does it deploy that float, and what is the risk if rates fall? |
| MB0569 | open300:A16-14 | stock | natural | partial | A company issues fresh equity to fund capex. How does that change ROCE and EPS, and what should an investor check first? |
| MB0570 | open300:A16-15 | stock | Hinglish | partial | Which company converted its capex into the best incremental ROCE over three years? Kaun sa company? (Hinglish) |

### Family 2 - Number (140 cases)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0004 | shivam30:DBQ4 | stock | terse | - | P/B now vs stored |
| MB0006 | shivam30:Q11 | stock | terse | - | KRISHNADEF segment revenue, latest quarter |
| MB0007 | shivam30:Q12 | stock | terse | - | Bank of Maharashtra net NPA % |
| MB0008 | shivam30:Q13 | stock | terse | - | ZENTEC 3-yr price CAGR |
| MB0010 | shivam30:Q15 | stock | terse | - | VINCOFE public shareholding Sep 2026 |
| MB0014 | shivam30:Q19 | stock | terse | - | MONQ50 ETF jump/fall + tracking error |
| MB0021 | shivam30:QA1 | stock | natural | - | What was the delivery volume (delivered quantity, not total traded quantity which includes intraday) of Ather Energy Ltd on 13 April 2026 and 14 April 2026, NSE + BSE com... |
| MB0022 | shivam30:QA2 | stock | point-in-time | - | What is the promoter holding of NSE: BLACKBUCK as of September 2026? |
| MB0025 | shivam30:QA5 | stock | point-in-time | - | How many equity shares does Lumax Auto Technologies have, and what is the promoter holding, as of the latest data? |
| MB0028 | shivam30:QA8 | stock | natural | - | What was the YTD high price of BSE: 532810 in 2026 (value and date)? |
| MB0061 | variations300:DBQ4-V1 | stock | natural | partial | What is Goldiam International (NSE: GOLDIAM)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. |
| MB0062 | variations300:DBQ4-V2 | stock | natural | partial | What is Ahlada Engineers (NSE: AHLADA)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. |
| MB0063 | variations300:DBQ4-V3 | stock | natural | partial | What is NSE: INFRATEL (now INDUSTOWER)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. |
| MB0064 | variations300:DBQ4-V4 | stock | terse | partial | GODREJIND pb ratio stored vs computed |
| MB0065 | variations300:DBQ4-V5 | stock | Hinglish | partial | Flexituff Ventures International (NSE: FLEXITUFF) ka P/B ratio kitna hai? Database mein stored ratio aur aaj ke price se nikaala hua ratio dono batao, aur farq kyun hai. |
| MB0066 | variations300:DBQ4-V6 | stock | natural | partial | What is Kovai Medical Center & Hospital (NSE: KOVAI)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. |
| MB0067 | variations300:DBQ4-V7 | industry | natural | partial | For all listed companies in Consumer Durables, rank the companies by P/B computed from the close on 19 October 2026 and the latest annual-report book value. |
| MB0068 | variations300:DBQ4-V8 | index | natural | partial | For the NIFTY500 LARGEMIDSMALL EQUAL-CAP WEIGHTED constituents, rank the companies by P/B computed from the close on 19 October 2026 and the latest annual-report book val... |
| MB0069 | variations300:DBQ4-V9 | stock | point-in-time | partial | As of 31 March 2026, what was Satia Industries (NSE: SATIA)'s P/B using the price and book value known by that date? Compare it with the stored ratio. |
| MB0070 | variations300:DBQ4-V10 | stock | natural | partial | What is Motherson Sumi Wiring India (NSE: MSUMI)'s P/B now versus the stored ratio, after adjusting for its corporate action? If book value per share is not held, say NOT... |
| MB0081 | variations300:Q11-V1 | stock | natural | yes | What was Avantel (NSE: AVANTEL)'s segment revenue for Q1FY27, with the absolute number for each reported segment? |
| MB0082 | variations300:Q11-V2 | stock | natural | yes | What was Astral (NSE: ASTRAL)'s segment revenue for Q1FY27, with the absolute number for each reported segment? |
| MB0083 | variations300:Q11-V3 | stock | natural | no | What was NSE: TIKONA (now GFSTEELS)'s segment revenue for Q1FY27, with the absolute number for each reported segment? |
| MB0084 | variations300:Q11-V4 | stock | terse | yes | GILLANDERS segment revenue Q1FY27 |
| MB0085 | variations300:Q11-V5 | stock | Hinglish | no | NTPC Green Energy (NSE: NTPCGREEN) ka Q1FY27 segment revenue kitna tha, segment-wise absolute numbers ke saath? XBRL context ka source bhi do. |
| MB0086 | variations300:Q11-V6 | stock | natural | yes | What was ACC (NSE: ACC)'s segment revenue for April-June 2026 (Q1 FY2026-27), with the absolute number for each reported segment? |
| MB0087 | variations300:Q11-V7 | industry | natural | yes | For all listed companies in Aerospace & Defense, rank the companies by reported segment revenue for Q1FY27. |
| MB0088 | variations300:Q11-V8 | index | natural | no | For the niftymidcap150 constituents, rank the companies by reported segment revenue for Q1FY27. |
| MB0089 | variations300:Q11-V9 | stock | point-in-time | yes | As of 30 June 2026, what segment revenue had Brainbees Solutions (NSE: FIRSTCRY) reported for Q1FY27? |
| MB0090 | variations300:Q11-V10 | stock | natural | no | What was 20 Microns (NSE: 20MICRONS)'s segment revenue for Q1FY27? If the filing has no segment context, answer NOT IN DATA and say which taxonomy is missing. |
| MB0091 | variations300:Q12-V1 | stock | natural | yes | What was Bank of Baroda (NSE: BANKBARODA)'s net NPA % for Q1FY27, and which XBRL concept and filing carry it? |
| MB0092 | variations300:Q12-V2 | stock | natural | yes | What was Fino Payments Bank (NSE: FINOPB)'s net NPA % for Q1FY27, and which XBRL concept and filing carry it? |
| MB0093 | variations300:Q12-V3 | stock | natural | yes | What was BSE scrip code 590003's net NPA % for Q1FY27, and which XBRL concept and filing carry it? |
| MB0094 | variations300:Q12-V4 | stock | terse | yes | BANKINDIA net npa Q1FY27 |
| MB0095 | variations300:Q12-V5 | stock | Hinglish | yes | Equitas Small Finance Bank (NSE: EQUITASBNK) ka net NPA percentage Q1FY27 mein kitna tha? Gross NPA aur net NPA dono, XBRL filing se batao. |
| MB0096 | variations300:Q12-V6 | stock | natural | yes | What was IndusInd Bank (NSE: INDUSINDBK)'s net NPA % for April-June 2026 (Q1 FY2026-27), and which XBRL concept and filing carry it? |
| MB0097 | variations300:Q12-V7 | industry | natural | yes | For all listed companies in Banks, rank the banks by net NPA % for Q1FY27, and state the source for each. |
| MB0098 | variations300:Q12-V8 | index | natural | partial | For the NIFTY HOUSING constituents, rank the banks by net NPA % for Q1FY27, and state the source for each. |
| MB0099 | variations300:Q12-V9 | stock | point-in-time | yes | As of 30 June 2026, what net NPA % had The Jammu & Kashmir Bank (NSE: J&KBANK) last reported for Q1FY27? |
| MB0100 | variations300:Q12-V10 | stock | natural | no | What was AU Small Finance Bank (NSE: AUBANK)'s net NPA % for Q2FY27? If that quarter's filing is not held, or the bank's XBRL uses a taxonomy without that concept, answer... |
| MB0101 | variations300:Q13-V1 | stock | natural | yes | What was Laxmi Goldorna House (NSE: LGHL)'s 3-year price CAGR to 19 October 2026, using split- and dividend-adjusted closes? State both endpoint dates. |
| MB0102 | variations300:Q13-V2 | stock | natural | partial | What was Orient Technologies (NSE: ORIENTTECH)'s 3-year price CAGR to 19 October 2026, using split- and dividend-adjusted closes? State both endpoint dates. |
| MB0103 | variations300:Q13-V3 | stock | natural | yes | What was NSE: RUCHI (now PATANJALI)'s 3-year price CAGR to 19 October 2026, using split- and dividend-adjusted closes? State both endpoint dates. |
| MB0104 | variations300:Q13-V4 | stock | terse | partial | AASTHA 3y cagr adjusted |
| MB0105 | variations300:Q13-V5 | stock | Hinglish | yes | eClerx Services (NSE: ECLERX) ka pichle 3 saal ka adjusted price CAGR kya raha? Start aur end date saaf-saaf likho, dividends aur splits adjust karke. |
| MB0106 | variations300:Q13-V6 | stock | natural | yes | What was Brigade Enterprises (NSE: BRIGADE)'s 3-year price CAGR to 30 September 2026, using split- and dividend-adjusted closes? State both endpoint dates. |
| MB0107 | variations300:Q13-V7 | industry | natural | no | For all listed companies in the industry, what was the 3-year adjusted price CAGR to 19 October 2026, ranked? |
| MB0108 | variations300:Q13-V8 | index | natural | no | For the NIFTY INDIA FPI 150 constituents, what was the 3-year adjusted price CAGR to 19 October 2026, ranked? |
| MB0109 | variations300:Q13-V9 | stock | point-in-time | yes | As of 30 June 2026, what was GRM Overseas (NSE: GRMOVER)'s 3-year adjusted price CAGR? |
| MB0110 | variations300:Q13-V10 | stock | natural | yes | What was InfoBeans Technologies (NSE: INFOBEAN)'s 3-year adjusted price CAGR across its corporate action? If adjusted prices are missing, answer NOT IN DATA. |
| MB0121 | variations300:Q15-V1 | stock | point-in-time | yes | What is Fertilizers and Chemicals Travancore (NSE: FACT)'s public shareholding as of Sep 2026? |
| MB0122 | variations300:Q15-V2 | stock | point-in-time | yes | What is NHPC (NSE: NHPC)'s public shareholding as of Sep 2026? |
| MB0123 | variations300:Q15-V3 | stock | point-in-time | yes | What is NSE: ADLABS (now IMAGICAA)'s public shareholding as of Sep 2026? |
| MB0124 | variations300:Q15-V4 | stock | terse | yes | ITI public shareholding Sep 2026 |
| MB0125 | variations300:Q15-V5 | stock | Hinglish | yes | M & B Engineering (NSE: MBEL) mein public shareholding Sep 2026 tak kitni hai? Promoter aur public dono ka percentage filing se batao. |
| MB0126 | variations300:Q15-V6 | stock | point-in-time | yes | What is JK Cement (NSE: JKCEMENT)'s public shareholding as of 30 September 2026? |
| MB0127 | variations300:Q15-V7 | industry | point-in-time | yes | For all listed companies in the industry, rank the companies by public shareholding as of Sep 2026. |
| MB0128 | variations300:Q15-V8 | index | point-in-time | no | For the NIFTY MIDCAP 100 constituents, rank the companies by public shareholding as of Sep 2026. |
| MB0129 | variations300:Q15-V9 | stock | point-in-time | yes | As of 30 June 2026, what was Digicontent (NSE: DGCONTENT)'s public shareholding per the latest filing on or before that date? |
| MB0130 | variations300:Q15-V10 | stock | point-in-time | no | What is 360 One Wam (NSE: 360ONE)'s public shareholding as of Sep 2026? If that quarter's shareholding filing is not held, answer NOT IN DATA. |
| MB0161 | variations300:Q19-V1 | stock | natural | partial | For Motilal Oswal Nasdaq 100 ETF (MOFN100) (MON100, ISIN INF247L01AP3), explain the jump in 10-18 Sep 2026 and 18-28 Sep 2026 using the underlying index and FX, and give ... |
| MB0162 | variations300:Q19-V2 | stock | natural | partial | For QGOLDHALF (QGOLDHALF, ISIN INF082J01010), a different ETF category from the original, what was the move in 10-18 Sep 2026 and 18-28 Sep 2026, and how did NAV track iN... |
| MB0163 | variations300:Q19-V3 | stock | natural | partial | For ISIN INF247L01AU3, what was the move in 10-18 Sep 2026 and 18-28 Sep 2026 and the tracking error against its underlying index and the rupee? |
| MB0164 | variations300:Q19-V4 | stock | terse | partial | QNIFTY jump tracking error Sep 2026 |
| MB0165 | variations300:Q19-V5 | stock | Hinglish | partial | Bajaj Finserv Nifty Bank ETF (BANKBETF, ISIN INF0QA701714) 10-18 September 2026 ke beech kyun jump hua aur 18-28 September mein kyun gira? Underlying index, FX aur NAV tr... |
| MB0166 | variations300:Q19-V6 | stock | natural | partial | For Bajaj Finserv Nifty 50 ETF (NIFTYBETF, ISIN INF0QA701722), explain the jump in September 2026 using the underlying index and FX, and give the NAV tracking error. |
| MB0167 | variations300:Q19-V7 | index | natural | partial | For the India-listed ETF universe, what explains the move in 10-18 Sep 2026 and 18-28 Sep 2026, and what is the NAV tracking error? |
| MB0168 | variations300:Q19-V8 | index | natural | partial | For the India-listed gold ETFs, which ETF moved most in 10-18 Sep 2026 and 18-28 Sep 2026, and what was its tracking error against the underlying index and FX? |
| MB0169 | variations300:Q19-V9 | stock | point-in-time | partial | As of 17 September 2026, what was the move in Quantum Gold ETF (QGOLDHALF, ISIN INF082J01408) up to that date, and what tracking error was visible by then? |
| MB0170 | variations300:Q19-V10 | stock | natural | no | For NIF100IETF (NIF100IETF, ISIN INF109KA1962), what was the move and NAV tracking error in 10-18 Sep 2026 and 18-28 Sep 2026? If the ETF has no NAV or iNAV rows, answer ... |
| MB0231 | variations300:QA1-V1 | stock | natural | yes | What was Eicher Motors (NSE: EICHERMOT)'s delivered quantity (not total traded quantity) on 15 September 2026 and 16 September 2026, NSE and BSE, with the combined total ... |
| MB0232 | variations300:QA1-V2 | stock | natural | yes | What was SEDEMAC Mechatronics (NSE: SEDEMAC)'s delivered quantity (not total traded quantity) on 15 September 2026 and 16 September 2026, NSE and BSE, with the combined t... |
| MB0233 | variations300:QA1-V3 | stock | natural | yes | What was NSE: DALALSTCOM (now KEEPLEARN)'s delivered quantity (not total traded quantity) on 10 June 2026 and 11 June 2026, NSE and BSE, with the combined total per day? |
| MB0234 | variations300:QA1-V4 | stock | terse | yes | ARIHANT delivery 11-12 Aug nse bse |
| MB0235 | variations300:QA1-V5 | stock | Hinglish | no | Sambandam Spinning Mills (NSE: SAMBANDAM) ka delivered quantity 11 August 2026 aur 12 August 2026 ko kitna tha? NSE, BSE aur dono ka total alag-alag batao. |
| MB0236 | variations300:QA1-V6 | stock | natural | yes | What was Sayaji Hotels (NSE: SAYAJIHOTL)'s delivered quantity (not total traded quantity) on 13 October 2026 and 14 October 2026, NSE and BSE, with the combined total per... |
| MB0237 | variations300:QA1-V7 | industry | natural | yes | For all listed companies in Automobiles, what was the delivered quantity on NSE and BSE on 10 February 2026 and 11 February 2026, ranked? |
| MB0238 | variations300:QA1-V8 | index | natural | partial | For the NIFTY SMALLCAP 500 constituents, what was the delivered quantity on NSE and BSE on 14 July 2026 and 15 July 2026, ranked? |
| MB0239 | variations300:QA1-V9 | stock | point-in-time | yes | As of 31 March 2026, what delivered quantity had Bimetal Bearings (NSE: BIMETAL) recorded on 15 September 2026 and 16 September 2026 on NSE and BSE? |
| MB0240 | variations300:QA1-V10 | stock | natural | no | What was Aakash Exploration Services (NSE: AAKASH)'s delivered quantity on 13 October 2026 and 14 October 2026 on NSE and BSE? If one exchange has no row, say which and a... |
| MB0241 | variations300:QA2-V1 | stock | point-in-time | yes | What is The Great Eastern Shipping Company (NSE: GESHIP)'s promoter holding as of Sep 2026, per the latest filing? |
| MB0242 | variations300:QA2-V2 | stock | point-in-time | yes | What is Indiqube Spaces (NSE: INDIQUBE)'s promoter holding as of Sep 2026, per the latest filing? |
| MB0243 | variations300:QA2-V3 | stock | point-in-time | partial | What is NSE: LTI (now LTM)'s promoter holding as of Sep 2026, per the latest filing? |
| MB0244 | variations300:QA2-V4 | stock | terse | yes | INTERARCH promoter holding Sep 2026 |
| MB0245 | variations300:QA2-V5 | stock | Hinglish | yes | Himadri Speciality Chemical (NSE: HSCL) mein promoter ki holding Sep 2026 tak kitni hai? Latest shareholding filing se number aur date batao. |
| MB0246 | variations300:QA2-V6 | stock | point-in-time | yes | What is Precot (NSE: PRECOT)'s promoter holding as of 30 September 2026, per the latest filing? |
| MB0247 | variations300:QA2-V7 | industry | point-in-time | partial | For all listed companies in Transport Services, what is the promoter holding as of Sep 2026, ranked from highest to lowest? |
| MB0248 | variations300:QA2-V8 | index | point-in-time | no | For the NIFTY MIDSMALLCAP 400 constituents, what is the promoter holding as of Sep 2026, ranked from highest to lowest? |
| MB0249 | variations300:QA2-V9 | stock | point-in-time | yes | As of 30 June 2026, what was The Phoenix Mills (NSE: PHOENIXLTD)'s promoter holding per the latest shareholding filing on or before that date? |
| MB0250 | variations300:QA2-V10 | stock | point-in-time | no | What is 360 One Wam (NSE: 360ONE)'s promoter holding as of Sep 2026? If the September 2026 shareholding filing is not held, answer NOT IN DATA and say why. |
| MB0271 | variations300:QA5-V1 | stock | point-in-time | yes | How many equity shares does CEAT (NSE: CEATLTD) have, and what is its promoter holding, as of the latest data? Say which filing each number comes from. |
| MB0272 | variations300:QA5-V2 | stock | point-in-time | yes | How many equity shares does Jamna Auto Industries (NSE: JAMNAAUTO) have, and what is its promoter holding, as of the latest data? Say which filing each number comes from. |
| MB0273 | variations300:QA5-V3 | stock | point-in-time | yes | How many equity shares does NSE: PROZONINTU (now PROZONER) have, and what is its promoter holding, as of the latest data? Say which filing each number comes from. |
| MB0274 | variations300:QA5-V4 | stock | terse | yes | BHARTIHEXA share count promoter holding |
| MB0275 | variations300:QA5-V5 | stock | Hinglish | yes | Dalmia Bharat (NSE: DALBHARAT) ke kitne equity shares hain aur promoter holding kitni hai? Dono numbers latest filing se, date ke saath batao. |
| MB0276 | variations300:QA5-V6 | stock | point-in-time | yes | How many equity shares does BCPL Railway Infrastructure (NSE: BCPL) have, and what is its promoter holding, as of the latest data? Say which filing each number comes from... |
| MB0277 | variations300:QA5-V7 | industry | natural | no | For all listed companies in Auto Components, give the latest exact share count and promoter holding for each company, with the filing date. |
| MB0278 | variations300:QA5-V8 | index | natural | no | For the NIFTY LARGEMIDCAP 250 constituents, give the latest exact share count and promoter holding for each company, with the filing date. |
| MB0279 | variations300:QA5-V9 | stock | point-in-time | yes | As of 30 June 2026, what were Ceinsys Tech (NSE: CEINSYS)'s exact share count and promoter holding? |
| MB0280 | variations300:QA5-V10 | stock | natural | yes | What are Kotyark Industries (NSE: KOTYARK)'s exact share count and promoter holding now, after its corporate action? If the post-action count is not held, answer NOT IN D... |
| MB0301 | variations300:QA8-V1 | stock | natural | yes | What was SBI Cards and Payment Services (NSE: SBICARD)'s YTD high price in 2026, with the value and the date, and on which exchange? |
| MB0302 | variations300:QA8-V2 | stock | natural | yes | What was Crisil (NSE: CRISIL)'s YTD high price in 2026, with the value and the date, and on which exchange? |
| MB0303 | variations300:QA8-V3 | stock | natural | yes | What was NSE: OMMETALS (now OMINFRAL)'s YTD high price in 2026, with the value and the date, and on which exchange? |
| MB0304 | variations300:QA8-V4 | stock | terse | yes | IPRINGLTD ytd high 2026 |
| MB0305 | variations300:QA8-V5 | stock | Hinglish | yes | Lakshmi Mills Company (NSE: LAKSHMIMIL) ka 2026 ka YTD high price kya tha, aur kis date ko? NSE ya BSE, exchange bhi batao. |
| MB0306 | variations300:QA8-V6 | stock | natural | yes | What was MMP Industries (NSE: MMP)'s YTD high price in 1 January-30 September 2026, with the value and the date, and on which exchange? |
| MB0307 | variations300:QA8-V7 | industry | natural | yes | For all listed companies in Finance, which companies made a new YTD high in 2026, with the value and date? |
| MB0308 | variations300:QA8-V8 | index | natural | partial | For the NIFTY 200 constituents, which companies made a new YTD high in 2026, with the value and date? |
| MB0309 | variations300:QA8-V9 | stock | point-in-time | yes | As of 30 June 2026, what was GMR Power and Urban Infra (NSE: GMRP&UI)'s YTD high in 2026 up to that date, and on which day? |
| MB0310 | variations300:QA8-V10 | stock | natural | yes | What was Metropolis Healthcare (NSE: METROPOLIS)'s YTD high for 2026, raw and adjusted for its corporate action? If adjusted prices are missing, say NOT IN DATA. |
| MB0541 | open300:A15-01 | stock | natural | partial | RVNL's order inflow in Q1 FY27 was Rs 5,417 crore. What is its order book cover in years, and how much of the book is slow-moving? |
| MB0542 | open300:A15-02 | stock | natural | partial | Inside HAL's Rs 2.54 lakh-crore book: which platforms dominate, and how many years of revenue does the mix imply? |
| MB0543 | open300:A15-03 | stock | natural | partial | Texrail's order book is Rs 9,923 crore. How much is wagons versus leasing, and which part is recurring? |
| MB0544 | open300:A15-04 | stock | natural | partial | BEL is waiting for CCS approval on QRSAM. Is that order already in the order book, and what happens to cover when it lands? |
| MB0545 | open300:A15-05 | stock | natural | partial | Mazagon Dock's order book: how much is shipbuilding versus repairs, and which is more stable? |
| MB0546 | open300:A15-06 | stock | natural | partial | Cochin Shipyard has an ISRF JV pipeline alongside its order book. How do you separate firm orders from JV optionality? |
| MB0547 | open300:A15-07 | stock | natural | partial | Ircon's order book: how much is the new dedicated-freight-corridor work, and has any of it been awarded? |
| MB0548 | open300:A15-08 | stock | natural | partial | Rites' order book has been falling. Why, and what does management say about the pipeline? |
| MB0549 | open300:A15-09 | stock | terse | partial | KEC T&D book-to-bill FY27 |
| MB0550 | open300:A15-10 | stock | Hinglish | partial | HG Infra ke order book mein EPC vs HAM kitna hai? (Hinglish) |
| MB0551 | open300:A15-11 | stock | natural | partial | Titagarh's wagon order book versus its 1,200/month capacity: at current orders, how many months of work is booked? |
| MB0552 | open300:A15-12 | stock | natural | partial | Afcons' order book includes the MAHSR C2 package. What share is under execution, and what does the TBM status say about it? |
| MB0553 | open300:A15-13 | stock | natural | partial | NBCC's PMC order book is large but its receivables are old. How do you judge whether the book is worth its face value? |
| MB0554 | open300:A15-14 | stock | natural | partial | GR Infra's order book and margin guidance: does the book mix support the guided margin? |
| MB0555 | open300:A15-15 | stock | Hinglish | partial | PNC Infratech's HAM assets are up for monetisation. Kaise order book se asset sale alag hai? (Hinglish) |
| MB0571 | open300:A17-01 | stock | natural | yes | Which large caps saw the highest delivery percentage on 4 June 2024, and what does that say about who was selling? |
| MB0572 | open300:A17-02 | stock | natural | yes | Which stocks traded above 50% delivery on 24 September 2026, and were they the biggest movers? |
| MB0573 | open300:A17-03 | stock | terse | yes | delivery-spike ratio leaders this week |
| MB0574 | open300:A17-04 | stock | natural | yes | On 23 October 2026 Bonfiglioli saw several bulk deals. Who bought, at what price, and was it above or below the close? |
| MB0575 | open300:A17-05 | index | natural | yes | Which side was bigger on 23 October 2026, FII or DII, and what does the ratio say about the marginal buyer? |
| MB0576 | open300:A17-06 | index | natural | yes | Is there a same-day relationship between FII net flow and the Nifty move in 2026? Show the worst divergence day. |
| MB0577 | open300:A17-07 | stock | natural | no | What was the promoter holding in Titagarh last quarter? terse: TITAGARH promoter % |
| MB0578 | open300:A17-08 | stock | natural | no | Which small caps saw the biggest mutual-fund accumulation last quarter? terse: MF buying small caps |
| MB0579 | open300:A17-09 | stock | natural | no | Which sectors did FIIs sell most in September 2026? terse: FII sector selling Sep 2026 |
| MB0580 | open300:A17-10 | stock | Hinglish | partial | Index inclusion se kisi stock mein move aaya kya? Ek case batao. (Hinglish) |
| MB0581 | open300:A17-11 | stock | natural | partial | Which stocks had the highest turnover on 4 June 2024, and was it concentrated in PSU financials? |
| MB0582 | open300:A17-12 | index | natural | yes | How many sessions in 2026 had FIIs selling and DIIs buying, and what did the Nifty do on those days on average? |
| MB0583 | open300:A17-13 | stock | natural | partial | Delivery percentage around results: does a high-delivery reaction day predict the next week? Test it on KEI and Titagarh. |
| MB0584 | open300:A17-14 | stock | natural | yes | Which large caps saw delivery percentage fall the most in the week after 4 June 2024, and what does that signal? |
| MB0585 | open300:A17-15 | index | Hinglish | yes | September 2026 mein FIIs ne kitna becha aur DIIs ne kitna kharida? (Hinglish) |

### Family 3 - Change over time (15 cases)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0526 | open300:A14-01 | stock | natural | partial | BEL guided 15% revenue growth for FY27. What did Q1 FY27 actually deliver, and is the guidance still credible? |
| MB0527 | open300:A14-02 | stock | natural | partial | Suzlon guided a 17-18% EBITDA margin for FY27. What has it actually reported, and what is the gap? |
| MB0528 | open300:A14-03 | stock | natural | partial | Tatapower said 200 MW was commissioned and another 500 MW would follow in weeks. Did the later disclosure confirm the 500 MW? |
| MB0529 | open300:A14-04 | stock | natural | partial | SRF guided the Dahej second pharma plant in eight months with Rs 180 crore. Has it commissioned, and how would you check? |
| MB0530 | open300:A14-05 | stock | natural | yes | KEI's Sanand phase 1 was late by about six months and commissioned in December 2025. Did the company meet its own revised date? |
| MB0531 | open300:A14-06 | stock | Hinglish | partial | Polycab ne Q1FY27 mein 3.2 billion capex kiya — annual plan se aage ya peeche? (Hinglish) |
| MB0532 | open300:A14-07 | stock | natural | partial | HAL's order book is about Rs 2.54 lakh crore. What revenue cover is that, and did management guide to converting it faster? |
| MB0533 | open300:A14-08 | stock | natural | partial | RVNL's Q1 FY27 order inflow was Rs 5,417 crore. How does that compare with its annual revenue, and what does it imply for FY27? |
| MB0534 | open300:A14-09 | stock | point-in-time | partial | Texrail's order book is Rs 9,923 crore as of 30 June 2026. What is the execution period, and is it enough to meet guidance? |
| MB0535 | open300:A14-10 | stock | natural | partial | UltraTech's volume growth and capacity additions: did the FY26 additions land on the guided date? |
| MB0536 | open300:A14-11 | stock | terse | partial | IRCTC payment aggregator licence status Oct 2026 |
| MB0537 | open300:A14-12 | stock | natural | partial | Cochin Shipyard targeted the ISRF JV before the end of the financial year. Has the JV been signed, and what would confirm it? |
| MB0538 | open300:A14-13 | stock | natural | partial | Adani Green claimed a 20 GW renewable milestone in Q1 FY27. What was the previous milestone, and how long did the last 5 GW take? |
| MB0539 | open300:A14-14 | stock | natural | partial | Jubilant FoodWorks has about 3,600 stores. Did store additions hit the number it guided last year? |
| MB0540 | open300:A14-15 | stock | natural | partial | SAIL advanced capital repairs into Q1 FY27 to free up later quarters. Did the later quarters show the output recovery it implied? |

### Family 4 - Screen (11 cases)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0012 | shivam30:Q17 | industry | terse | - | HFC securitisation leader, QoQ/YoY with NPA guard |
| MB0141 | variations300:Q17-V1 | industry | natural | yes | Is Can Fin Homes (NSE: CANFINHOME) the leader in securitised disbursement among listed HFCs for Q1FY27, with net NPA up no more than 2 pp? Show the comparison. |
| MB0142 | variations300:Q17-V2 | industry | natural | partial | Among large-cap HFCs, who leads securitised disbursement for Q1FY27 with net NPA up no more than 2 pp? |
| MB0143 | variations300:Q17-V3 | industry | natural | partial | For NSE: IBULHSGFIN (now SAMMAANCAP), is it the leader in securitised disbursement among listed HFCs for Q1FY27, with net NPA up no more than 2 pp? Show the naming histor... |
| MB0144 | variations300:Q17-V4 | industry | terse | partial | hfc securitisation leader q1fy27 net npa |
| MB0145 | variations300:Q17-V5 | industry | Hinglish | partial | Listed HFCs mein securitised disbursement ka leader kaun hai Q1FY27 mein? QoQ aur YoY winner batao, lekin net NPA 2 percentage point se zyada na badhe. |
| MB0146 | variations300:Q17-V6 | industry | natural | yes | Which listed HFC is the leader in securitised disbursement for January-March 2026 (Q4FY26), QoQ and YoY, with net NPA rising no more than 2 pp? |
| MB0147 | variations300:Q17-V7 | industry | natural | yes | For all listed companies in Housing Finance, which listed financial company is the securitisation leader for Q1FY27 with the net-NPA guard, and what is the evidence? |
| MB0148 | variations300:Q17-V8 | index | natural | partial | For the NIFTY HOUSING FINANCE constituents, rank the financial companies on securitised disbursement for Q1FY27, with the net-NPA guard. |
| MB0149 | variations300:Q17-V9 | industry | point-in-time | yes | As of 30 June 2026, which HFC looked like the securitisation leader for Q1FY27, and on what evidence? |
| MB0150 | variations300:Q17-V10 | industry | natural | no | Which listed HFC led securitised disbursement in Q1FY27? If the securitisation figure is not in any structured store for GIC Housing Finance (NSE: GICHSGFIN), answer NOT ... |

### Family 5 - Cross-document (0 cases)

No case declares this family.

### Family 6 - Policy -> companies (88 cases)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0011 | shivam30:Q16 | theme | terse | - | Why gold stocks fell Jun–Jul 2026 |
| MB0013 | shivam30:Q18 | industry | terse | - | OMCs: record Q4 then loss Q1; earliest PIT signal |
| MB0015 | shivam30:Q20 | stock | terse | - | Garware: tariff hit, then negative correlation |
| MB0016 | shivam30:Q21 | policy | terse | - | RBI repo hike causes; PIB or RBI only |
| MB0017 | shivam30:Q22 | theme | terse | - | Second-hand electronics boom CY2026: who benefits |
| MB0018 | shivam30:Q23 | industry | terse | - | Coal gasification drafts vs the earlier scheme |
| MB0019 | shivam30:Q24 | stock | terse | - | PARAGMILK on El Niño; dairy peers |
| MB0020 | shivam30:Q25 | policy | terse | - | Data-centre tax holiday outcome so far |
| MB0131 | variations300:Q16-V1 | theme | natural | partial | Why did gold-jewellery stocks move in June-July 2026? Give the macro move, the PIB or RBI evidence, and what the companies themselves said. |
| MB0132 | variations300:Q16-V2 | theme | natural | partial | Why did oil and gas stocks move in April-May 2026? Give the macro move, the PIB or RBI evidence, and what the companies themselves said. |
| MB0133 | variations300:Q16-V3 | theme | natural | partial | Why did the companies in the gold-jewellery theme move in Jun-Jul 2026? The event is referenced by the gold price series (USD/oz); name the PIB release or macro series yo... |
| MB0134 | variations300:Q16-V4 | theme | terse | partial | gold-jewellery stocks move Jun-Jul 2026 why |
| MB0135 | variations300:Q16-V5 | theme | Hinglish | partial | Gold-Jewellery stocks Jun-Jul 2026 mein kya hua aur kyun? PIB, RBI ya company documents se evidence do, aur batao kaun sabse zyada affected hua. |
| MB0136 | variations300:Q16-V6 | theme | natural | partial | What caused the gold-jewellery move in June-July 2026 (FY27 first half)? Use the commodity series, PIB and company evidence from that window only. |
| MB0137 | variations300:Q16-V7 | industry | natural | partial | For all listed companies in gold-jewellery, what moved in Jun-Jul 2026, and what do the macro, PIB and company evidence say caused it? |
| MB0138 | variations300:Q16-V8 | theme | natural | partial | For the gold-jewellery theme members, how did the gold price move in Jun-Jul 2026 hit the members differently, and which one was worst? |
| MB0139 | variations300:Q16-V9 | theme | point-in-time | yes | By 31 July 2026, why had gold-jewellery stocks moved? Use only evidence known by that date. |
| MB0140 | variations300:Q16-V10 | theme | natural | no | Why did PNGS Reva Diamond Jewellery (NSE: PNGSREVA) move in 7-19 Oct 2026? If the macro series for that window is missing, answer NOT IN DATA and name the series. |
| MB0151 | variations300:Q18-V1 | industry | point-in-time | yes | Sugar Q4FY26-to-Q1FY27 profit swing — which companies in Sugar swung from profit in Q4FY26 to a loss in Q1FY27, and when was that first visible point-in-time? |
| MB0152 | variations300:Q18-V2 | industry | point-in-time | yes | Media & Entertainment Q4FY26-to-Q1FY27 profit swing — which companies in Media & Entertainment swung from profit in Q4FY26 to a loss in Q1FY27, and when was that first vi... |
| MB0153 | variations300:Q18-V3 | industry | point-in-time | yes | For BSE scrip code 532543, when did the Q4FY26-to-Q1FY27 profit swing become visible point-in-time, and from which filing? |
| MB0154 | variations300:Q18-V4 | industry | terse | yes | omc q4fy26 profit q1fy27 loss earliest pit |
| MB0155 | variations300:Q18-V5 | industry | Hinglish | yes | OMCs ne Q4FY26 mein record profit aur Q1FY27 mein bada loss kaise kiya? Sabse pehle kaunsa data point point-in-time visible tha, date ke saath batao. |
| MB0156 | variations300:Q18-V6 | industry | natural | yes | For the January-March 2026 and April-June 2026 quarters, which OMCs went from record profit to a loss, and when did that first become visible? |
| MB0157 | variations300:Q18-V7 | industry | point-in-time | yes | For all listed companies in Petroleum Products, which companies swung from profit in Q4FY26 to a loss in Q1FY27, and what was the earliest point-in-time evidence? |
| MB0158 | variations300:Q18-V8 | index | point-in-time | partial | For the NIFTY OIL & GAS constituents, which companies swung from profit in Q4FY26 to a loss in Q1FY27, and what was the earliest point-in-time evidence? |
| MB0159 | variations300:Q18-V9 | industry | point-in-time | yes | As of 30 June 2026, what did the data already show about the OMC profit swing from Q4FY26 to Q1FY27? |
| MB0160 | variations300:Q18-V10 | industry | natural | no | Using the coal price series, when did the OMC Q4FY26-to-Q1FY27 trend first become visible? If the series ends before that window, answer NOT IN DATA. |
| MB0171 | variations300:Q20-V1 | stock | natural | partial | How sensitive was KRN Heat Exchanger and Refrigeration (NSE: KRN) to Customs tariff rationalization - remove 7 tariff rates (1 February 2025) in the 60 days after it, and... |
| MB0172 | variations300:Q20-V2 | stock | natural | partial | How sensitive was APL Apollo Tubes (NSE: APLAPOLLO) to Customs tariff rationalization - remove 7 tariff rates (1 February 2025) in the 60 days after it, and did its 60-da... |
| MB0173 | variations300:Q20-V3 | stock | natural | partial | How sensitive was NSE: DHARAMSI (now DMCC) to Customs tariff rationalization - remove 7 tariff rates (1 February 2025) in the 60 days after it, and did its 60-day return ... |
| MB0174 | variations300:Q20-V4 | stock | terse | partial | PAKKA tariff sensitivity rolling correlation |
| MB0175 | variations300:Q20-V5 | stock | Hinglish | partial | Eco Recycling (NSE: ECORECO) par Customs tariff rationalization - remove 7 tariff rates (1 February 2025) ka kitna asar pada, aur agle 12 mahine mein tariff news se corre... |
| MB0176 | variations300:Q20-V6 | stock | natural | partial | How did JSW Energy (NSE: JSWENERGY)'s rolling correlation with Customs tariff rationalization - remove 7 tariff rates (1 February 2025) change over the 12 months after Ma... |
| MB0177 | variations300:Q20-V7 | industry | natural | partial | For all listed companies in Industrial Products, how sensitive were the members to Customs tariff rationalization - remove 7 tariff rates (1 February 2025), and did the 6... |
| MB0178 | variations300:Q20-V8 | index | natural | partial | For the NIFTY MIDSMALLCAP400 MOMENTUM QUALITY 100 constituents, how sensitive were the members to Customs tariff rationalization - remove 7 tariff rates (1 February 2025)... |
| MB0179 | variations300:Q20-V9 | stock | point-in-time | partial | As of 31 March 2026, what did the rolling correlation of National Aluminium Company (NSE: NATIONALUM) with Customs tariff rationalization - remove 7 tariff rates (1 Febru... |
| MB0180 | variations300:Q20-V10 | stock | natural | no | For 20 Microns (NSE: 20MICRONS), did the tariff impact and any later negative correlation survive its corporate action on adjusted prices? If not, answer NOT IN DATA. |
| MB0181 | variations300:Q21-V1 | policy | natural | yes | For the Repo rate hiked 25 bps to 5.50% (2026-10-07), what were the causes, and which source published it first? |
| MB0182 | variations300:Q21-V2 | policy | natural | partial | For the Devolution of states' share in taxes increased (2026-02-01), what were the causes, and which source published it first? |
| MB0183 | variations300:Q21-V3 | policy | natural | yes | For the RBI Governor's Statement of 7 October 2026 (2026-10-07), what were the causes, and which source published it first? |
| MB0184 | variations300:Q21-V4 | policy | terse | yes | rbi repo hike 2026-10-07 causes pib or rbi |
| MB0185 | variations300:Q21-V5 | policy | Hinglish | yes | RBI ne 2026-10-07 ko repo rate kyun badhaya? Causes batao, aur ye news PIB ne publish kiya ya sirf RBI ne? Provenance ke saath. |
| MB0186 | variations300:Q21-V6 | policy | natural | yes | For the Repo rate hiked 25 bps to 5.50% of 2026-10-07, what were the causes, and was it published by PIB or only by the RBI? |
| MB0187 | variations300:Q21-V7 | industry | natural | yes | For all listed companies in banking, how does the 2026-10-07 RBI action transmit, and which sectors are named in the policy document? |
| MB0188 | variations300:Q21-V8 | index | natural | partial | For the NIFTY TOTAL MARKET constituents, how did the members react to the RBI action of 2026-10-07, and what does the PIB/RBI record show? |
| MB0189 | variations300:Q21-V9 | policy | point-in-time | no | As of 6 October 2026, what did the record show about the causes of the RBI action of 2026-10-07, and who published it first? |
| MB0190 | variations300:Q21-V10 | policy | natural | no | What were the causes of the RBI action of 2026-10-07, and was it published by PIB or only by RBI? If the policy document is not held, answer NOT IN DATA. |
| MB0191 | variations300:Q22-V1 | theme | natural | partial | For the Electronics Component Manufacturing Scheme approvals (2025-11-17), why does it matter for demand, and which sectors and listed companies does it touch? |
| MB0192 | variations300:Q22-V2 | theme | natural | partial | For the R&D in IT/Electronics/CCBT (2026-02-01), why does it matter for demand, and which sectors and listed companies does it touch? |
| MB0193 | variations300:Q22-V3 | theme | natural | partial | Using the document reference PIB PRID 2190872 on 2025-11-17, what does the policy record say about electronics demand in CY2026, and which companies does it touch? |
| MB0194 | variations300:Q22-V4 | theme | terse | partial | second hand electronics boom cy2026 who benefits |
| MB0195 | variations300:Q22-V5 | theme | Hinglish | partial | CY2026 mein second-hand aur refurbished electronics/laptops ki demand kyun badhi? Kaun listed companies ko fayda hoga, aur ye structural hai ya cyclical? Data gap bhi bat... |
| MB0196 | variations300:Q22-V6 | theme | natural | partial | Why did second-hand electronics and laptop sales rise in CY2026? Who benefits, and is the trend structural or cyclical? State any part that is NOT IN DATA. |
| MB0197 | variations300:Q22-V7 | industry | natural | partial | For all listed companies in electronics, what does the policy record say about demand in CY2026, and which companies does it touch? |
| MB0198 | variations300:Q22-V8 | index | natural | partial | For the NIFTY WAVES constituents, what does the policy and company evidence say about demand in CY2026, and who benefits? |
| MB0199 | variations300:Q22-V9 | theme | point-in-time | yes | As of 30 June 2026, what was known about the as of 30 June 2026 electronics demand trend, and which companies were named? |
| MB0200 | variations300:Q22-V10 | theme | natural | no | What do our stores say about refurbished/second-hand electronics sales in CY2026, and who benefits? If no sales series exists, answer NOT IN DATA and say which store is m... |
| MB0201 | variations300:Q23-V1 | industry | natural | yes | For the Scheme for promotion of coal/lignite gasification (2026-02-01), how does it differ from the earlier coal-gasification scheme, and which industries does it hit? |
| MB0202 | variations300:Q23-V2 | industry | natural | partial | For the National Green Hydrogen Mission progress (2025-12-16), how does it differ from the coal-gasification scheme, and which industries does it hit? |
| MB0203 | variations300:Q23-V3 | industry | natural | yes | Using the document reference Union_Budget: Union Budget FY2026-27 - Budget at a Glance (2026-02-01), how does the coal-gasification policy differ from the earlier scheme,... |
| MB0204 | variations300:Q23-V4 | industry | terse | yes | coal gasification policy draft vs earlier scheme |
| MB0205 | variations300:Q23-V5 | industry | Hinglish | yes | Coal gasification ke naye draft aur pehle wale scheme mein kya farq hai? Kaunse ministries aur industries affected hain, aur PIB/Budget se evidence do. |
| MB0206 | variations300:Q23-V6 | industry | natural | yes | How do India's coal-gasification policy drafts differ from the earlier scheme, and which industries do they hit? |
| MB0207 | variations300:Q23-V7 | industry | natural | yes | For all listed companies in coal, how does the coal-gasification policy differ from the earlier scheme, and which industries does it hit? |
| MB0208 | variations300:Q23-V8 | index | natural | partial | For the NIFTY TOTAL MARKET constituents, what does the coal-gasification policy change mean for the members, and which ones are named in policy_events? |
| MB0209 | variations300:Q23-V9 | industry | point-in-time | no | As of 31 December 2025, how did the coal-gasification drafts differ from the earlier scheme? Use only documents known by that date. |
| MB0210 | variations300:Q23-V10 | industry | natural | no | How does the coal-gasification policy change affect coal-price-sensitive companies? If the coal price series ends before 2024-2026, answer NOT IN DATA. |
| MB0211 | variations300:Q24-V1 | stock | natural | yes | What did Dodla Dairy (NSE: DODLA) say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? |
| MB0212 | variations300:Q24-V2 | stock | natural | yes | What did Milky Mist Dairy Food (NSE: MILKYMIST) say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? |
| MB0213 | variations300:Q24-V3 | stock | natural | yes | What did BSE scrip code 531531 say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? |
| MB0214 | variations300:Q24-V4 | stock | terse | yes | PARAGMILK el nino dairy margins |
| MB0215 | variations300:Q24-V5 | stock | Hinglish | yes | Heritage Foods (NSE: HERITGFOOD) ne El Nino 2026 ke asar par calls mein kya kaha? Dairy peers ka bhi comparison do, aur management ne kaise handle karne ko kaha. |
| MB0216 | variations300:Q24-V6 | stock | natural | no | What did Kwality Wall's (India) (NSE: KWIL) say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? |
| MB0217 | variations300:Q24-V7 | industry | natural | yes | For all listed companies in Fast Moving Consumer Goods, what did managements say about El Nino 2026, and how are they handling it? |
| MB0218 | variations300:Q24-V8 | index | natural | no | For the NIFTY SMALLCAP 100 constituents, how exposed are the members to El Nino 2026, and what did they say about handling it? |
| MB0219 | variations300:Q24-V9 | stock | point-in-time | no | As of 30 June 2026, what had Milkfood (NSE: MLKFOOD) said about El Nino 2026 and its dairy margins? |
| MB0220 | variations300:Q24-V10 | stock | natural | no | What did Knack Packaging (NSE: KNACK) say about El Nino 2026 on its calls? If no transcript is held for it, answer NOT IN DATA and name the store checked. |
| MB0221 | variations300:Q25-V1 | policy | natural | partial | For the startup tax holiday extension (2025-02-01), how has it played out so far for the affected industry, and what do companies say? |
| MB0222 | variations300:Q25-V2 | policy | natural | partial | For the Tax holiday for affordable housing projects extended to March 2022 (2022-01-31), how has it played out so far for the affected industry, and what do companies say... |
| MB0223 | variations300:Q25-V3 | policy | natural | partial | Using the document reference PIB PRID 2323840 on 2026-10-15, how has the data-centre tax holiday played out so far, and what do the companies in the theme say? |
| MB0224 | variations300:Q25-V4 | policy | terse | partial | data centre tax holiday outcome 2025-2026 |
| MB0225 | variations300:Q25-V5 | policy | Hinglish | partial | Data-centre operations ke liye tax holiday ka kya outcome raha? Budget, PIB, policy_events aur data-centre companies ke comments se evidence do. |
| MB0226 | variations300:Q25-V6 | policy | natural | partial | How has the tax holiday for data-centre operations in India played out so far, and what do the companies in the data-centre theme say? |
| MB0227 | variations300:Q25-V7 | industry | natural | partial | For all listed companies in data-centre, how has the tax holiday played out, and what do the companies and policy documents say? |
| MB0228 | variations300:Q25-V8 | index | natural | partial | For the NIFTY SMALLCAP 500 constituents, what has the tax holiday meant so far, and which members are named in the policy record? |
| MB0229 | variations300:Q25-V9 | policy | point-in-time | no | As of 1 February 2026, how had the data-centre tax holiday played out, using only evidence known by that date? |
| MB0230 | variations300:Q25-V10 | policy | natural | no | How has the data-centre tax holiday played out so far? If no data-centre tax holiday exists in policy_events, or the PIB starts too late, answer NOT IN DATA. |

### Family 7 - Company -> policy (0 cases)

No case declares this family.

### Family 8 - Peers (0 cases)

No case declares this family.

### Family 9 - Event window (35 cases; 20 with family inferred)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0586 | open300:A18-01 | stock | natural | yes | Titagarh filed Q1 FY27 results at 19:56 on 12 August 2026. What is the correct reaction window, and what was the return? |
| MB0587 | open300:A18-02 | stock | natural | yes | KEI filed Q1 FY27 results at 20:52 on 3 August 2026. What was the day-after return, and does it match the margin narrative? |
| MB0588 | open300:A18-03 | stock | natural | yes | BEL filed at 16:38 on 27 July 2026. The next session fell 4.46%. Was that a post-close or intraday filing? |
| MB0589 | open300:A18-04 | stock | Hinglish | partial | HAL ne 14:19 par file kiya aur 1.75% chadha — kya yeh clean reaction hai? (Hinglish) |
| MB0590 | open300:A18-05 | stock | natural | yes | RVNL filed at 17:19 on 11 August 2026 and the stock closed flat the next day. What does a zero return tell you? |
| MB0591 | open300:A18-06 | stock | natural | yes | Tata Steel filed at 19:56 on 30 July 2026 and rose 1.48% the next session. How large is that versus its own typical daily move? |
| MB0592 | open300:A18-07 | stock | natural | yes | IRCTC filed at 20:43 on 12 August 2026 and fell 1.77% the next day. What two alternatives should be ruled out first? |
| MB0593 | open300:A18-08 | stock | natural | yes | Jubilant FoodWorks filed at 16:30 on 13 August 2026. Why is the 14 August move the right window, and what was it? |
| MB0594 | open300:A18-09 | stock | natural | partial | Suzlon filed at 15:11 on 28 July 2026, during the session, and fell 9.65% that day. What can and cannot be concluded? |
| MB0595 | open300:A18-10 | stock | natural | partial | Mankind filed at 20:15 on 30 July 2026 and fell 4.13% on 31 July. What was the market doing that day? |
| MB0596 | open300:A18-11 | stock | natural | partial | PB Fintech filed a clarification on price movement on Sunday 27 September 2026. What is the first session that can react, and what did it do? |
| MB0597 | open300:A18-12 | stock | natural | yes | Trent's 1:2 bonus had an ex-date of 4 June 2026. How should an event study treat that day? |
| MB0598 | open300:A18-13 | stock | terse | partial | KAYNES 14 May 2026 — results or management change? |
| MB0599 | open300:A18-14 | stock | natural | yes | Cyient saw a bulk deal on 23 October 2026 and rose 7.81%. What does the deal data say about the direction of pressure? |
| MB0600 | open300:A18-15 | stock | natural | partial | Across the twelve Q1 FY27 result reactions here, which stock's move was largest relative to its own volatility, and what is the caveat? |
| MB0811 | ripple200:R10-01 | stock | natural | partial | A bulk deal printed on POLYCAB on 14 Jan 2026 — the same session as its largest delivery spike of the year. Take day 0 as the deal session, look at the 4 sessions before ... |
| MB0812 | ripple200:R10-02 | stock | natural | partial | KEI held its earnings call on 4 Aug 2026. Apply the 3:30 rule to the call intimation and to the results filing separately, then compare the 4 sessions before each day 0 w... |
| MB0813 | ripple200:R10-03 | stock | natural | partial | Take BEL's most recent order-win filing. If it was stamped after 15:30 IST, day 0 is the next session; if before, it is the same session. Which of the 4 sessions before d... |
| MB0814 | ripple200:R10-04 | stock | natural | partial | Take FIVESTAR's most recent rating action. Both the agency release and the company disclosure have a timestamp; use the earlier one for day 0, then test whether the 4 ses... |
| MB0815 | ripple200:R10-05 | stock | natural | partial | DIVISLAB announced a capex programme on its earnings call. The transcript is usable only when it is published, not when the call happened. Build day 0 from the publicatio... |
| MB0816 | ripple200:R10-06 | stock | natural | partial | A large steel group announces an acquisition outside trading hours. Work out which session is day 0 when the announcement is not on a trading day, then build the 4-sessio... |
| MB0817 | ripple200:R10-07 | stock | natural | partial | Take HAL's most recent management-change filing. Build day 0 from its dissemination timestamp and check the 4 sessions before it. What does the filing actually name — the... |
| MB0818 | ripple200:R10-08 | stock | natural | partial | The US tariff on shrimp-class exports is in policy_events with its own published_at. Build day 0 for the Indian exporter from that timestamp and ask whether a 4-session w... |
| MB0819 | ripple200:R10-09 | stock | natural | partial | The Union Budget speech is delivered inside the session, so day 0 is the speech session. Build the 4 sessions before it for the textile names and say whether positioning ... |
| MB0820 | ripple200:R10-10 | stock | natural | partial | The MPC statement is published before the close. Build day 0 for a bank from its timestamp, then check whether the 4 sessions before it contain anything a rule could call... |
| MB0821 | ripple200:R10-11 | stock | natural | partial | An index provider announces an inclusion and an effective date. That is two day-0s. Build both 4-session windows and say which one can show leakage and which one can only... |
| MB0822 | ripple200:R10-12 | stock | natural | partial | A PLI approval appears in a ministry release and later in the company's own disclosure. Take the earlier known_at for day 0 and ask whether the 4 sessions before it show ... |
| MB0823 | ripple200:R10-13 | stock | natural | partial | A demerger scheme is filed with the exchanges. The board approval and the filing are two candidate day-0s. Build both windows and say which one a leaker would have acted ... |
| MB0824 | ripple200:R10-14 | stock | natural | partial | A company announces a stock split, which has no cash effect. Build day 0 and check the 4 sessions before it. This is the negative control: how often does a delivery spike... |
| MB0825 | ripple200:R10-15 | stock | natural | partial | Take APLAPOLLO's most recent pledge disclosure. Build day 0 from the dissemination timestamp and check the 4 sessions before it for distribution rather than accumulation. |
| MB0826 | ripple200:R10-16 | stock | natural | partial | A tax or regulatory demand order is uploaded to the exchange. Build day 0, check the 4 sessions before it, and say which document in the store actually contains the order... |
| MB0827 | ripple200:R10-17 | stock | natural | partial | Take ORIENTPPR's most recent auditor change. Build day 0 and check the 4 sessions before it. An auditor resignation should not leak, which makes it a second control. |
| MB0828 | ripple200:R10-18 | stock | natural | partial | Take APARINDS' largest insider sale in insider_trades_v2. The intimation date gives day 0; check the 4 sessions before it and say whether the sale itself was the informat... |
| MB0829 | ripple200:R10-19 | stock | natural | partial | A company cuts its guidance on the call and the transcript is published later. Build day 0 from the publication, then check the 4 sessions before it. Which document carri... |
| MB0830 | ripple200:R10-20 | stock | natural | partial | A buyback is announced after the close, so day 0 is the next session. Check the 4 sessions before it: is the pre-window evidence of a leak, or of price support before a t... |

### Family 10 - Opinion vs truth (0 cases)

No case declares this family.

### Family 11 - Point in time (20 cases; 20 with family inferred)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0791 | ripple200:R09-01 | stock | point-in-time | no | For a cable maker's margin trough, three hop-1 series compete: the metal price, the price-hike statement, and the delivery spike. Which one turns first, and is each of th... |
| MB0792 | ripple200:R09-02 | stock | point-in-time | no | Entry-segment two-wheeler demand: does the rural wage series, the scheme allocation, or the dealer inventory turn first? Which of them is point-in-time today? |
| MB0793 | ripple200:R09-03 | stock | point-in-time | partial | Bank NIM: does the weighted average call rate, the deposit rate, or credit growth turn first? And is the deposit rate a point-in-time series at all? |
| MB0794 | ripple200:R09-04 | stock | natural | no | EPC margin: which signals first — the order book, the steel index, or the award pipeline? And which of the three is in our data with a known_at? |
| MB0795 | ripple200:R09-05 | stock | point-in-time | no | An export order is being lost. Does container freight, port throughput, or the company's delivery spike turn first? Which of them can be read point-in-time? |
| MB0796 | ripple200:R09-06 | stock | natural | no | Capex revival: order inflow, capital-goods production, or credit growth — which turns first, and which is usable without look-ahead? |
| MB0797 | ripple200:R09-07 | stock | natural | no | Power demand: plant load factor, coal stock days, or the exchange price first? Which one is a leading indicator for the aluminium smelter's cost? |
| MB0798 | ripple200:R09-08 | stock | point-in-time | no | Steel price: the HRC index, mill inventory days, or import volume first? Which is point-in-time in our data today? |
| MB0799 | ripple200:R09-09 | stock | natural | partial | US generic drug erosion: ANDA approvals, price erosion commentary, or distributor inventory first? Which one can be dated from a filing? |
| MB0800 | ripple200:R09-10 | stock | natural | no | Cement demand: dispatches, GST collection, or pet coke first? Which turns before the other two? |
| MB0801 | ripple200:R09-11 | stock | natural | no | Freight: the Baltic index, the container rate, or the charter rate first? Which one is published with a date usable in a backtest? |
| MB0802 | ripple200:R09-12 | stock | point-in-time | partial | Foreign flow: FPI limit headroom, index membership changes, or the delivery spike first? Which is point-in-time and which is a revision risk? |
| MB0803 | ripple200:R09-13 | stock | natural | no | The rupee: forward premium, spot, or exporter commentary first? Which of them is a usable leading series and which is interpretation? |
| MB0804 | ripple200:R09-14 | stock | point-in-time | no | NBFC credit cost: bounce rates, disbursement growth, or GNPA first? Which one is point-in-time in a filing, and which is not published at all? |
| MB0805 | ripple200:R09-15 | stock | natural | partial | Hospital revenue per bed: bed count, occupancy, or pricing first? Which is dated in a filing? |
| MB0806 | ripple200:R09-16 | stock | natural | no | Dairy procurement: rainfall, fodder price, or the cooperative's procurement price first? Which of them is a published series? |
| MB0807 | ripple200:R09-17 | stock | natural | no | Tyre replacement: freight movement, kilometres run, or dealer stock first? Which one is available in our data with a date? |
| MB0808 | ripple200:R09-18 | stock | natural | no | Capital-goods activity: order inflow, GST on capital goods, or the credit-to-industry series first? Which one is a revision risk? |
| MB0809 | ripple200:R09-19 | stock | natural | partial | Insurance: commission paid, annual premium equivalent, or the partner bank's fee income first? Which one is dated in a filing? |
| MB0810 | ripple200:R09-20 | stock | point-in-time | partial | A defence order: the budget allocation, the award, or the delivery first? Which of the three is usable in a point-in-time test? |

### Family 12 - When / timeline (50 cases; 20 with family inferred)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0331 | open300:A01-01 | stock | natural | yes | KEI Industries' first phase at Sanand: what month did it actually get commissioned, and how far behind the original plan was that? |
| MB0332 | open300:A01-02 | stock | natural | yes | Dixon's Vivo joint venture: from which quarter does management expect it to start showing up in revenue? |
| MB0333 | open300:A01-03 | stock | natural | yes | Tata Power's renewables arm: how much capacity was already commissioned when management spoke, and how much was due 'in the next few weeks'? |
| MB0334 | open300:A01-04 | stock | natural | yes | SRF is putting up a second pharma-intermediate plant at Dahej. How much is the capex and over what commissioning window did management guide? |
| MB0335 | open300:A01-05 | stock | natural | yes | Cochin Shipyard's ISRF joint venture with Drydocks World, Dubai: by when is it targeted to be in place, and what is it conditional on? |
| MB0336 | open300:A01-06 | stock | natural | partial | IRCTC's payment-aggregator application: what did RBI extend the deadline to, and has the licence actually come through since? |
| MB0337 | open300:A01-07 | stock | terse | partial | APLAPOLLO 8 MT by FY28 — slipped or on track? |
| MB0338 | open300:A01-08 | stock | natural | yes | Titagarh Rail Systems is 'ready to ramp up' wagon output. To what monthly run-rate, and what single condition does management put on doing it? |
| MB0339 | open300:A01-09 | stock | natural | yes | Adani Green: what renewable-capacity milestone did management claim in Q1 FY27, and how does it split between this quarter and earlier years? |
| MB0340 | open300:A01-10 | stock | natural | yes | NTPC has over 33 GW under construction. What is the coal/hydro/renewable split, and which of those is the largest single block? |
| MB0341 | open300:A01-11 | stock | natural | yes | RVNL's BharatNet work: what execution timeline did management give, and what happens after the build phase? |
| MB0342 | open300:A01-12 | stock | natural | yes | Afcons' Mumbai-Ahmedabad high-speed-rail C2 package: what is the current status of the two tunnel-boring machines? |
| MB0343 | open300:A01-13 | stock | Hinglish | yes | BEL ka QRSAM order kis approval ka wait kar raha hai, aur kab tak? (Hinglish) |
| MB0344 | open300:A01-14 | stock | natural | partial | UltraTech's capacity is 184 million tonnes including India Cements and Kesoram. What is the target it is being expanded to, and over what period? |
| MB0345 | open300:A01-15 | stock | natural | partial | Hindalco's renewable-energy capacity: how much does it have, of what mix, and what did management say it does to cost? |
| MB0346 | open300:A02-01 | stock | natural | yes | Titagarh says it will only ramp wagons once demand is 'sustainable'. What did management say the current network run-rate is, and what is it below? |
| MB0347 | open300:A02-02 | stock | natural | partial | Dixon's operating margin compressed because the mobile-PLI benefit expired. When does management expect the margin to normalise, and on what? |
| MB0348 | open300:A02-03 | stock | natural | yes | KEI's operating margin improved in FY26. By how much, and what does that say about the pricing environment for cables? |
| MB0349 | open300:A02-04 | stock | natural | partial | UltraTech says cement demand for the country grew about 4% in the quarter. What did management give as the reason the market is not stronger? |
| MB0350 | open300:A02-05 | stock | natural | partial | IndiGo reported revenue ahead of its own expectation. What did management say about the demand environment and when it expected to add capacity? |
| MB0351 | open300:A02-06 | stock | natural | yes | Polycab has started BharatNet execution. Over how many years does that run, and from when? |
| MB0352 | open300:A02-07 | stock | natural | partial | Suzlon says 4.5 GW of manufacturing capacity is fully operational. When does that capacity convert into revenue, and what gates it? |
| MB0353 | open300:A02-08 | stock | natural | partial | Amber Enterprises signed a manufacturing collaboration covering Oppo, OnePlus and Realme. When was it executed, and when does management expect it to matter? |
| MB0354 | open300:A02-09 | stock | natural | partial | Jubilant FoodWorks has close to 3,600 stores, about 2,530 in India. When does management expect store additions to return to guidance, and why the pause? |
| MB0355 | open300:A02-10 | stock | Hinglish | partial | SAIL ne Q1FY27 mein capital repairs aage khiske kyun, aur output kab recover hoga? (Hinglish) |
| MB0356 | open300:A02-11 | stock | natural | partial | Muthoot Finance opened 177 branches in a year. When does gold-loan demand seasonally peak, and what did management say about branch-level demand? |
| MB0357 | open300:A02-12 | stock | terse | yes | TEXRAIL 100 leasing rakes — when? |
| MB0358 | open300:A02-13 | stock | natural | partial | Ircon has a new dedicated-freight-corridor project in the pipeline. What is the status of the tender, and when does revenue start? |
| MB0359 | open300:A02-14 | industry | natural | partial | When does the cement industry get its next round of price increases, and what would have to change in demand for that? |
| MB0360 | open300:A02-15 | stock | Hinglish | partial | BEL ne FY27 ke liye 15% growth bola tha — kaunsa half-year usko uthana padega, aur management ne kya skew bataya? (Hinglish) |
| MB0751 | ripple200:R07-01 | stock | natural | partial | Copper moves 20% in a quarter. Using our own quarterly margin series for the cable makers, what was the last cycle's lag between the metal move and the margin trough, and... |
| MB0752 | ripple200:R07-02 | stock | natural | partial | Crude moves 20%. How many quarters pass before the paint makers' margin trough prints, and is the trough before or after the price hike is announced? |
| MB0753 | ripple200:R07-03 | stock | natural | partial | The repo is cut. Using the last easing cycle, how many quarters before the bank's NIM troughs, and does the trough arrive before or after the deposit repricing is complet... |
| MB0754 | ripple200:R07-04 | stock | natural | partial | The repo is raised. How long before an NBFC's cost of funds actually rises, given its borrowing maturities? Compute the lag from the debt schedule rather than assuming it... |
| MB0755 | ripple200:R07-05 | stock | natural | partial | The rupee falls 5%. How many quarters before the IT exporter's margin shows it, and which quarter does the hedge book shift the gain into? |
| MB0756 | ripple200:R07-06 | stock | natural | partial | Steel rises 15%. How many quarters before the forging and stamping names' margin troughs, and is the lag shorter or longer than the OEM's? |
| MB0757 | ripple200:R07-07 | stock | natural | no | A monsoon deficit of 20% hits two districts. How many quarters before tractor volume falls, and what does our own history say about the lag between rainfall and volume? |
| MB0758 | ripple200:R07-08 | stock | natural | no | MGNREGS spending rises. Trace it to rural wages, then to two-wheeler entry-segment volume, and state the lag you can actually verify versus the one you are assuming. |
| MB0759 | ripple200:R07-09 | stock | natural | partial | Central capex is released in April. How many quarters before the EPC contractor's revenue reflects it, and where does the money actually sit in the meantime? |
| MB0760 | ripple200:R07-10 | stock | natural | partial | A defence order is signed. How long before it appears in the prime's revenue, and how much of the order book is recognised in the first year? |
| MB0761 | ripple200:R07-11 | stock | natural | partial | A capacity is announced with a commissioning date. Across the last cycle, how much did the date slip, and what is the slippage measured against? |
| MB0762 | ripple200:R07-12 | stock | natural | no | A PLI application is approved. How long before the incentive cash reaches the company, and where does it appear in the P&L? |
| MB0763 | ripple200:R07-13 | stock | natural | no | A company raises equity for a plant. How many quarters from the raise to the first rupee of revenue, and what does the past cycle say about the gap between the stated and... |
| MB0764 | ripple200:R07-14 | stock | natural | no | Freight doubles. How many quarters before the importer's cash cycle lengthens, and what does the past cycle say it cost in interest? |
| MB0765 | ripple200:R07-15 | stock | natural | no | A rating is downgraded. How long before the company's incremental borrowing cost rises, and does the existing debt reprice? |
| MB0766 | ripple200:R07-16 | stock | natural | partial | A tariff is imposed on a product. How long before the exporter's order book shows the loss, and how long before the revenue does? |
| MB0767 | ripple200:R07-17 | stock | natural | partial | A price hike is announced. How many quarters before the volume loss shows, and does the margin peak before or after the volume trough? |
| MB0768 | ripple200:R07-18 | stock | natural | no | An inventory build precedes a margin recovery. How many quarters between the two in our own data, and is the build a signal or a coincidence? |
| MB0769 | ripple200:R07-19 | stock | natural | partial | A company repays debt from cash flow. How many quarters before the interest saving appears, and how much of the saving is already in the run-rate? |
| MB0770 | ripple200:R07-20 | stock | natural | no | A QIP is priced at a discount. How many quarters of EPS dilution follow, and when does the new capital start earning? |

### Family 13 - Inverse screen (15 cases)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0361 | open300:A03-01 | stock | Hinglish | partial | Konsi companies ne FY27 ke liye EBITDA margin recovery ka guidance diya hai, aur har ek ka evidence kya hai? (Hinglish) |
| MB0362 | open300:A03-02 | stock | terse | partial | Q1FY27 price hikes — cables, paints, steel |
| MB0363 | open300:A03-03 | stock | natural | partial | Which managements said a plant or line goes live in H2 FY27? terse: H2FY27 commissioning list |
| MB0364 | open300:A03-04 | stock | natural | partial | Which companies described demand as weak or below plan in Q1 FY27, and which described it as strong? Give both lists. |
| MB0365 | open300:A03-05 | stock | natural | partial | Which managements said working capital or receivables from government clients worsened last quarter? |
| MB0366 | open300:A03-06 | stock | natural | partial | Which companies announced fresh orders above Rs 1,000 crore in Q1 FY27? Include the order value and the period of execution. |
| MB0367 | open300:A03-07 | stock | Hinglish | partial | Kaunsi mid-caps ne FY27 ke liye 20% se zyada revenue growth guide kiya hai? (Hinglish) |
| MB0368 | open300:A03-08 | stock | natural | partial | Which managements said they are evaluating acquisitions or inorganic growth, and which have actually signed something? |
| MB0369 | open300:A03-09 | stock | natural | partial | Which companies flagged input-cost inflation in Q1 FY27, and which input did each name? |
| MB0370 | open300:A03-10 | stock | Hinglish | partial | Kaunsi company ne FY26 mein buyback ya special dividend announce kiya? Date aur amount ke saath batao. (Hinglish) |
| MB0371 | open300:A03-11 | stock | natural | partial | Which companies said their order book covers more than two years of revenue? Give the cover multiple you computed. |
| MB0372 | open300:A03-12 | stock | natural | partial | Which managements said they will reduce net debt this financial year, and by how much? |
| MB0373 | open300:A03-13 | stock | natural | partial | Which companies said export demand recovered in the last two quarters, and which markets did they name? |
| MB0374 | open300:A03-14 | stock | natural | partial | Which companies claimed capacity-utilisation improvement last quarter, and which gave the utilisation number? |
| MB0375 | open300:A03-15 | stock | Hinglish | partial | Which managements said margin has bottomed and expect recovery next quarter? Kaun si companies ne bottom bola? (Hinglish) |

### Family 14 - Governance and audit (45 cases)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0376 | open300:A04-01 | stock | natural | partial | What was the auditor's opinion on Reliance's latest quarterly results, and was it modified in any way? |
| MB0377 | open300:A04-02 | stock | natural | partial | Tata Steel's Q1 FY27 filing: did it carry an audit qualification, and what exactly does the stored field say? |
| MB0378 | open300:A04-03 | stock | natural | partial | Which companies filed a 'Statement on impact of audit qualification' with their latest results? How many, and which large caps? |
| MB0379 | open300:A04-04 | stock | natural | yes | Yes Bank's latest quarter: what auditor opinion was filed, and is this an audited period? |
| MB0380 | open300:A04-05 | stock | Hinglish | yes | Mankind ki subsidiary mein auditor resignation kab hui, aur kya file hua? (Hinglish) |
| MB0381 | open300:A04-06 | stock | natural | partial | Milefur's statutory auditor resigned. When was it filed, and what reason was given? |
| MB0382 | open300:A04-07 | stock | natural | yes | Picturehouse's secretarial auditor resigned. Who was the firm and when did the filing land? |
| MB0383 | open300:A04-08 | stock | natural | no | Is there any going-concern doubt flagged in the latest quarterly results of small caps? terse: going concern Q1FY27 |
| MB0384 | open300:A04-09 | stock | terse | no | emphasis-of-matter paragraphs in latest results filings |
| MB0385 | open300:A04-10 | stock | natural | partial | What were HDFC Bank's key audit matters in its latest annual report, and did any repeat? |
| MB0386 | open300:A04-11 | stock | terse | partial | Suzlon's latest results: what did the auditor's declaration say? |
| MB0387 | open300:A04-12 | stock | natural | partial | For Reliance and Tata Steel, do the standalone and consolidated filings carry the same auditor declaration in Q1 FY27? |
| MB0388 | open300:A04-13 | stock | natural | partial | What did the latest annual report say about auditor remuneration, and how fast is it rising? |
| MB0389 | open300:A04-14 | stock | natural | partial | Which companies have filed a 'Declaration of unmodified opinion' for every quarter in the last four quarters? |
| MB0390 | open300:A04-15 | stock | natural | partial | Titagarh's Q1 FY27 results: opinion declared, and does it match what the results notes say? |
| MB0391 | open300:A05-01 | stock | natural | partial | List the statutory auditor resignations filed in September 2026, with company and date. terse: auditor resignation Sep 2026 |
| MB0392 | open300:A05-02 | stock | natural | yes | How many auditor-resignation and auditor-appointment filings are in the announcement store, and what does the gap between them say? |
| MB0393 | open300:A05-03 | stock | natural | partial | Kaynes Technology filed a 'Change in Management' on 13 May 2026. Who changed, in what role, and when did it take effect? |
| MB0394 | open300:A05-04 | stock | terse | partial | CFO churn 2024-2026 listed companies |
| MB0395 | open300:A05-05 | stock | Hinglish | partial | TruAlt ke promoter ne kab pledge banaya, aur kitne shares ka? (Hinglish) |
| MB0396 | open300:A05-06 | stock | natural | partial | Which company appointed an auditor to a casual vacancy in the last quarter, and whose resignation created it? |
| MB0397 | open300:A05-07 | stock | natural | yes | Welcorp filed an intimation about its credit rating. Who took the action and when was the press release issued? |
| MB0398 | open300:A05-08 | stock | natural | partial | Which companies disclosed a SEBI penalty or show-cause notice in Q2 FY27, and what was the amount? |
| MB0399 | open300:A05-09 | stock | natural | partial | Which companies disclosed GST or income-tax demand notices in the last quarter, and were they material? |
| MB0400 | open300:A05-10 | stock | natural | partial | Which companies filed a director resignation in September 2026, and did any cite a reason? |
| MB0401 | open300:A05-11 | stock | natural | no | What is TruAlt's promoter pledge as a percentage of promoter holding in the latest quarter? terse: TRUALT pledge % |
| MB0402 | open300:A05-12 | stock | natural | no | Cluster of insider buying in Sep-Oct 2026: which promoters or KMPs bought, and how much? terse: insider buys Sep-Oct 2026 |
| MB0403 | open300:A05-13 | stock | natural | yes | On 23 October 2026 Cyient saw a large bulk deal. Who sold, at what price, and how did the stock react? |
| MB0404 | open300:A05-14 | stock | natural | partial | Did any company's auditor resign within a year of a qualified opinion? Name the company and the two dates. |
| MB0405 | open300:A05-15 | stock | Hinglish | partial | Did any auditor resign citing 'other commitments' or lack of time in the last year? Kaun sa auditor ne reason diya? (Hinglish) |
| MB0406 | open300:A06-01 | stock | natural | partial | Which promoters created a fresh pledge over their shares between August and September 2026, and which were top-ups on an existing pledge? |
| MB0407 | open300:A06-02 | stock | natural | partial | Which Q2 FY27 results notes disclose a related-party transaction that grew sharply year on year? |
| MB0408 | open300:A06-03 | stock | natural | partial | Which companies show receivables growing much faster than revenue in the last reported year? |
| MB0409 | open300:A06-04 | stock | natural | partial | Which companies disclosed a tax or regulatory demand in Q2 FY27 that is large relative to their profit? |
| MB0410 | open300:A06-05 | stock | natural | partial | Welcorp disclosed a credit-rating intimation in October 2026. Was it an upgrade, a downgrade or a review, and how would you tell? |
| MB0411 | open300:A06-06 | stock | natural | partial | Which companies wrote down inventory or took an impairment in Q1 FY27, and how large was it against EBITDA? |
| MB0412 | open300:A06-07 | stock | natural | partial | Which segment of which company swung from profit to loss last quarter, while the company reported a profit overall? |
| MB0413 | open300:A06-08 | stock | natural | partial | Which companies have operating cash flow persistently below reported profit, and for how many years? |
| MB0414 | open300:A06-09 | stock | Hinglish | partial | Kisi company ne debt covenant breach ya restructuring disclose kiya kya? (Hinglish) |
| MB0415 | open300:A06-10 | stock | natural | partial | Which companies disclosed a plant shutdown or force majeure in the last quarter, and what did they say the financial effect was? |
| MB0416 | open300:A06-11 | stock | natural | no | Which companies are in a 5% or lower price band on results day, and did the band change before the announcement? |
| MB0417 | open300:A06-12 | stock | terse | partial | Q1FY27 audit-qualification statements — how many |
| MB0418 | open300:A06-13 | stock | natural | partial | Which companies' results notes mention a related-party loan or advance to a promoter-group entity? |
| MB0419 | open300:A06-14 | stock | natural | partial | Which company changed its statutory auditor twice in three years, and is that a red flag here? |
| MB0420 | open300:A06-15 | stock | natural | no | Promoter selling before results: which companies show it in the last two quarters? terse: promoter sale before results |

### Family 15 - Market move -> why (30 cases)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0421 | open300:A07-01 | index | natural | partial | On 4 June 2024 the Nifty 50 fell 5.93%. What was the sector dispersion that day, and what kind of market move was it? |
| MB0422 | open300:A07-02 | index | Hinglish | yes | 4 June 2024 wale hafte mein Nifty ka move kya tha, aur ek din ka number kaafi hai? (Hinglish) |
| MB0423 | open300:A07-03 | index | natural | partial | On 4 June 2024, Nifty PSU Bank fell 15.14% while Nifty FMCG rose 0.95%. What does that pair tell you about positioning? |
| MB0424 | open300:A07-04 | stock | terse | partial | 4 Jun 2024 top losers, turnover floor applied |
| MB0425 | open300:A07-05 | index | natural | partial | The Union Budget 2026-27 was presented on Sunday 1 February 2026. What did the Nifty 50 do on the first trading session after it? |
| MB0426 | open300:A07-06 | index | natural | yes | What did the Nifty 50 do on the first session after the 2025-26 Budget on Saturday 1 February 2025? |
| MB0427 | open300:A07-07 | index | natural | partial | On 23 March 2020 the Nifty 50 fell 12.98%. What evidence in the store dates the cause, and what is NOT in the store? |
| MB0428 | open300:A07-08 | index | natural | partial | On 1 February 2021 the Nifty 50 rose 4.74%. Which policy lines in the store were published around that date, and do they explain it? |
| MB0429 | open300:A07-09 | index | natural | partial | On 24 February 2022 the Nifty 50 fell 4.78%. What was happening in crude, and does the crude move support a geopolitical read? |
| MB0430 | open300:A07-10 | index | natural | partial | On 24 September 2026 the Nifty 50 fell 1.64% but PB Fintech fell 36%. Was this a market move or a stock event? |
| MB0431 | open300:A07-11 | index | natural | partial | On 7 April 2025 the Nifty 50 fell 3.24%. Which stored policy event is closest, and does the date match? |
| MB0432 | open300:A07-12 | policy | natural | partial | The RBI hiked the repo rate 25 bps to 5.50% on 7 October 2026. Did the Nifty 50 or the rate-sensitive indices move that day, and can the day's move be separated from the ... |
| MB0433 | open300:A07-13 | index | natural | yes | On 23 October 2026 FIIs bought and DIIs bought much more. Who absorbed the supply, and did the index fall anyway? |
| MB0434 | open300:A07-14 | index | natural | yes | For September 2026, what were the aggregate FII and DII cash flows, and how many sessions are they based on? |
| MB0435 | open300:A07-15 | index | Hinglish | partial | On 4 June 2024 the Nifty IT fell only 0.6% while Nifty Energy fell 12.47%. Kaun sa sector sabse zyada gira, aur kyun? (Hinglish) |
| MB0436 | open300:A08-01 | stock | natural | yes | Siemens fell 42.93% on 7 April 2025. Was that a real loss of value? Explain with the corporate-action record. |
| MB0437 | open300:A08-02 | stock | natural | partial | PB Fintech fell 36% on 24 September 2026. What was scheduled that day, and what did the exchange ask for afterwards? |
| MB0438 | open300:A08-03 | stock | natural | partial | Kaynes fell 20.15% on 14 May 2026. What did the company file the previous evening, and what else was in that filing batch? |
| MB0439 | open300:A08-04 | stock | natural | partial | Trent fell 14.77% on 7 April 2025. Was there a company disclosure before the open, and what kind of update was it? |
| MB0440 | open300:A08-05 | stock | natural | partial | REC Ltd and PFC both fell more than 23% on 4 June 2024 with no company filing that day. What explains a move of that size in a lender? |
| MB0441 | open300:A08-06 | stock | terse | yes | BHEL 4 Jun 2024 volume and delivery |
| MB0442 | open300:A08-07 | stock | natural | yes | Adani Ports fell 21.15% on 4 June 2024. How does that compare with the Nifty 50 and what does the delivery data add? |
| MB0443 | open300:A08-08 | stock | natural | yes | SAIL fell 20.02% on 4 June 2024 and Nifty Metal fell 10.63%. What share of the stock move is explained by the sector? |
| MB0444 | open300:A08-09 | stock | natural | partial | Suzlon fell 9.65% on 28 July 2026 and the results were filed at 15:11 that day. What is the correct event window? |
| MB0445 | open300:A08-10 | stock | natural | partial | Bharat Electronics fell 4.46% on 28 July 2026, the session after its results. Was the market reaction consistent with the numbers? |
| MB0446 | open300:A08-11 | stock | natural | yes | Mankind Pharma fell 4.13% on 31 July 2026 after results the previous evening. What two filings should you check before calling it a results reaction? |
| MB0447 | open300:A08-12 | stock | natural | partial | KEI rose 9.49% on 4 August 2026 after results filed at 20:52 on 3 August. What did the numbers say about margin? |
| MB0448 | open300:A08-13 | stock | natural | yes | Polycab fell 3.83% on 17 July 2026, the day after results filed at 15:59. What was the actual reaction window? |
| MB0449 | open300:A08-14 | stock | natural | yes | Titagarh rose 2.06% on 13 August 2026 after results the previous evening. Was the reaction large relative to its own volatility? |
| MB0450 | open300:A08-15 | stock | Hinglish | yes | Dixon fell 2.02% on 31 July 2026 but the results were filed at 18:12, after the close. Kaun sa din ka move actually the reaction hai? (Hinglish) |

### Family 16 - Input-cost / commodity transmission (85 cases; 40 with family inferred)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0451 | open300:A09-01 | stock | natural | partial | Copper went from 5.0875 on 20 May 2024 to 6.559 on 30 September 2026. How would that hit a cable maker's margin, and what has actually happened to KEI's margin? |
| MB0452 | open300:A09-02 | stock | natural | partial | What share of a cable maker's raw-material cost is copper, and where in the filing is it stated? |
| MB0453 | open300:A09-03 | stock | natural | partial | Copper is up about 29% from May 2024. Does that help Hindustan Copper more than it hurts the cable makers, and why? |
| MB0454 | open300:A09-04 | stock | Hinglish | partial | Brent was 99.08 on 24 February 2022 and 103.53 on 30 September 2026. Kaise crude ka asar paint companies ke margin par padta hai? (Hinglish) |
| MB0455 | open300:A09-05 | stock | natural | partial | How much of an airline's cost is fuel, and what does a $4 move in Brent do to IndiGo's EBITDA? |
| MB0456 | open300:A09-06 | stock | natural | partial | Crude at $103 should hurt tyre makers through carbon black and synthetic rubber. Which listed tyre company is most exposed, and what does the AR say? |
| MB0457 | open300:A09-07 | stock | natural | partial | Crude at $103: what happens to the oil marketing companies' marketing margin, and what did IOC or BPCL say about under-recovery? |
| MB0458 | open300:A09-08 | stock | natural | no | Coal is a fuel input for NTPC and Tata Power. The coal series ends in December 2025; can you still answer a 2026 coal-cost question? |
| MB0459 | open300:A09-09 | stock | Hinglish | partial | US HRC 1,275 hai — Indian tube maker ke liye kaun sa price matter karta hai? (Hinglish) |
| MB0460 | open300:A09-10 | stock | Hinglish | partial | Gold was 2,028 on 7 August 2020 and 4,186.7 on 30 September 2026. Kaun jeetta hai—jeweller ya gold-loan NBFC? (Hinglish) |
| MB0461 | open300:A09-11 | stock | natural | partial | Aluminium was 3,285 on 30 September 2026. Who gains and who loses among Hindalco, Vedanta and a downstream user? |
| MB0462 | open300:A09-12 | stock | terse | partial | iron ore series — SAIL and JINDALSTEL 2026 margin |
| MB0463 | open300:A09-13 | stock | natural | partial | Natural gas was 3.026 on 30 September 2026. What does that do to a urea maker's cost, given administered prices? |
| MB0464 | open300:A09-14 | stock | natural | partial | Copper is also an input for switchgear and transformers. Does the SIEMENS/ABB margin tell the same story as the cable makers'? |
| MB0465 | open300:A09-15 | stock | natural | partial | A copper spike hits cable makers, who sell to EPC contractors on fixed-price contracts. Who eats the loss, and how do you prove it? |
| MB0466 | open300:A10-01 | stock | natural | partial | The rupee went from 81.48 on 30 September 2022 to 96.05 on 30 September 2026. Which listed exporters gained most, and how do you measure it? |
| MB0467 | open300:A10-02 | stock | natural | partial | Rupee depreciation helps Infosys but hurts importers. For a pharma exporter, what are the two opposing channels? |
| MB0468 | open300:A10-03 | stock | natural | partial | Rupee at 96 puts pressure on a paint company that imports crude derivatives. How would you show it in the numbers? |
| MB0469 | open300:A10-04 | stock | natural | partial | RBI raised the repo by 50bp to 5.9% on 30 September 2022. What does that do to a vehicle-finance NBFC's spread, and how fast? |
| MB0470 | open300:A10-05 | stock | Hinglish | partial | RBI ne 1 Oct 2025 ko repo hold kiya — HFC margins par kya asar, aur market ne cut price kiya tha? (Hinglish) |
| MB0471 | open300:A10-06 | stock | natural | partial | Repo cuts are supposed to help realty. What is the actual channel from repo to a DLF or Prestige sale, and how many steps are there? |
| MB0472 | open300:A10-07 | stock | natural | partial | A rate cut compresses a bank's NIM but lifts loan growth. For HDFC Bank, which effect dominated last cycle, and what does the disclosure say? |
| MB0473 | open300:A10-08 | stock | natural | partial | Muthoot's cost of funds rises with the repo. How does that interact with the gold-loan yield cap, and who bears it? |
| MB0474 | open300:A10-09 | stock | natural | partial | A weaker rupee raises an airline's dollar costs. What are the two biggest USD cost lines for IndiGo, and how are they disclosed? |
| MB0475 | open300:A10-10 | stock | natural | partial | Shipping earns in dollars and spends partly in rupees. What does rupee depreciation do to SCI's margin? |
| MB0476 | open300:A10-11 | stock | natural | partial | For a life insurer, what do higher rates do to the embedded value, and does that show up in the disclosures? |
| MB0477 | open300:A10-12 | stock | natural | partial | Repo up 250bp over two years: how would an auto-finance NBFC's spread move, and what does Bajaj Finance's disclosure show? |
| MB0478 | open300:A10-13 | stock | natural | partial | Rupee at 96 for an electronics manufacturer that imports components: what does it do to Dixon's margin and what is the hedge? |
| MB0479 | open300:A10-14 | stock | Hinglish | partial | IRFC lends to Indian Railways at fixed spreads funded by bonds. Kaise rate cut se uski profitability badalti hai? (Hinglish) |
| MB0480 | open300:A10-15 | stock | terse | partial | KPITTECH rupee depreciation margin impact |
| MB0601 | open300:A19-01 | stock | natural | partial | If the monsoon fails, which listed sectors are most exposed, and in what order would the effect show up? |
| MB0602 | open300:A19-02 | stock | natural | partial | Crude is already at 103.53 on 30 September 2026. If it holds, which listed sectors lose most, and which gain? |
| MB0603 | open300:A19-03 | stock | natural | partial | If US tariffs rise another 25 points, which listed exporters are most exposed, and what would you check first? |
| MB0604 | open300:A19-04 | stock | natural | partial | If the rupee goes to 100, who wins and who loses among listed companies? Give both sides with a channel each. |
| MB0605 | open300:A19-05 | stock | natural | partial | Gold is 4,186.7. If it goes to 5,000, do jewellers or gold-loan NBFCs do better, and why is the answer not obvious? |
| MB0606 | open300:A19-06 | stock | terse | no | coal scarcity FY27 — which sectors, answerable? |
| MB0607 | open300:A19-07 | stock | natural | partial | If the FY27 public capex of Rs 12.2 lakh crore is spent as budgeted, which listed sectors see it first, which later, and who loses? |
| MB0608 | open300:A19-08 | stock | natural | partial | If the semiconductor incentive doubles, which listed companies benefit first and which only in the second round? |
| MB0609 | open300:A19-09 | stock | natural | partial | If the RBI cuts 100bp over a year, which listed sectors re-rate first, and what breaks the chain? |
| MB0610 | open300:A19-10 | stock | natural | partial | If data-centre capex doubles, which listed companies see it first, and is the exposure measurable? |
| MB0611 | open300:A19-11 | stock | natural | partial | If EV penetration hits 30%, which listed auto-component names lose and which gain? Give both sides. |
| MB0612 | open300:A19-12 | stock | natural | partial | If China+1 accelerates, which listed sectors win, and what is the first evidence you would look for? |
| MB0613 | open300:A19-13 | stock | natural | partial | If container freight rates spike, which listed exporters lose and does a shipping line gain? |
| MB0614 | open300:A19-14 | stock | natural | partial | If GST rates are cut on consumer durables, who gains more: a durables maker or an FMCG company? |
| MB0615 | open300:A19-15 | stock | Hinglish | partial | Agar crude $100 ho jaye to kaunse listed sectors sabse zyada peedit honge? (Hinglish) |
| MB0631 | ripple200:R01-01 | stock | natural | partial | Copper rises 20% in a quarter. Trace it through cable makers' COGS, the timing of the dealer price hike, and the fixed-price EPC contracts downstream. Which listed EPC na... |
| MB0632 | ripple200:R01-02 | stock | natural | no | Natural rubber and crude-based inputs rise together. How long before tyre makers' replacement-market price hikes reach the OEMs, and what does the OEM's own cost per vehi... |
| MB0633 | ripple200:R01-03 | stock | natural | no | Steel HRC rises 15%. Auto ancillaries have annual price agreements with OEMs and quarterly raw-material indexation. Where does the margin land for the forging and stampin... |
| MB0634 | ripple200:R01-04 | stock | natural | partial | Aluminium rises and the rupee weakens in the same quarter. Conductors and switchgear get dearer, the transmission capex programme is already sanctioned, and the discoms m... |
| MB0635 | ripple200:R01-05 | stock | natural | partial | Coking coal rises. Steel mills raise HRC, construction cost rises, and highway EPC contracts are awarded on a fixed-price basis with a steel escalation clause for bridges... |
| MB0636 | ripple200:R01-06 | stock | natural | partial | Crude rises 20%. Paints pass it on to dealers with a lag, dealers stop restocking, and the volume effect arrives after the margin effect. What is the sequence in the quar... |
| MB0637 | ripple200:R01-07 | stock | natural | no | Edible-oil and crude-linked packaging costs rise into a weak rural quarter. Hindustan Unilever and the personal-care names face a cost push and a demand pull in opposite ... |
| MB0638 | ripple200:R01-08 | stock | natural | no | Gas and ammonia prices rise. Urea makers' cost goes up but the retail price is controlled, so the subsidy bill rises instead. Trace that to farm income, then to tractor a... |
| MB0639 | ripple200:R01-09 | stock | natural | no | Cotton rises 25% while the rupee weakens. Spinners' yarn price rises, garment exporters' FOB price rises, and the EU buyer has an alternative in Bangladesh. Which hop bre... |
| MB0640 | ripple200:R01-10 | stock | natural | partial | Gold rises 20%. The jeweller's inventory gains in value, the customer delays purchase, and the working-capital line grows at the same time. Which of those three hits the ... |
| MB0641 | ripple200:R01-11 | stock | natural | partial | Iron-ore fines rise after a mining-lease disruption. Pellet and sponge-iron makers reprice first, the integrated mills later, and the downstream steel-products makers las... |
| MB0642 | ripple200:R01-12 | stock | natural | partial | Coal and freight rise while power demand peaks. The generator's tariff is regulated, the aluminium smelter's power cost is not. Which listed smelter's margin moves first,... |
| MB0643 | ripple200:R01-13 | stock | natural | partial | Soda ash and energy rise. Consumer-glass and industrial-glass makers face a cost push, and their customers are FMCG and construction. Which glass maker can pass it on and... |
| MB0644 | ripple200:R01-14 | stock | natural | partial | Pulp and waste-paper prices rise. Paper makers reprice, packaging converters absorb it, and the FMCG buyer renegotiates the carton contract. Who is squeezed in the middle... |
| MB0645 | ripple200:R01-15 | stock | natural | no | Chinese intermediate prices drop and then rebound. Indian specialty-chemical makers had cut output at the low. Trace the margin recovery, the restocking by agrochemical f... |
| MB0646 | ripple200:R01-16 | stock | natural | partial | Sugar and ethanol compete for the same cane. A higher ethanol blending price pulls cane into ethanol, sugar output falls, the sugar price rises, and the OMC's blending co... |
| MB0647 | ripple200:R01-17 | stock | natural | no | Container freight doubles and transit time stretches. Importers of components hold more inventory, the cash cycle lengthens, and short-term debt rises. Which listed mid-c... |
| MB0648 | ripple200:R01-18 | stock | natural | no | Carbon black and rubber chemicals rise into a weak CV cycle. Tyre replacement demand tracks freight movement, and CV makers' volumes follow freight rates with a lag. Whic... |
| MB0649 | ripple200:R01-19 | stock | natural | partial | Pet coke and limestone rise while cement demand is soft. The large players hold price, the regional players cut. Which listed regional producer's margin breaks first, and... |
| MB0650 | ripple200:R01-20 | stock | natural | no | Copper, steel and freight all rise in one year. Transformer and switchgear makers sit between a metals index and a discom order book. Which listed equipment maker has ind... |
| MB0671 | ripple200:R03-01 | stock | natural | partial | The repo goes up 25 bps. Split the loan book into EBLR, MCLR and fixed, split the deposit book into savings and term, and compute which bank's NIM falls first. The answer... |
| MB0672 | ripple200:R03-02 | stock | natural | partial | The 2025 rate cuts reach the NBFC's cost of funds with a lag, but its AUM growth needs a credit cycle, not a rate cut. Trace the cost of funds, then the spread, then the ... |
| MB0673 | ripple200:R03-03 | stock | natural | partial | The rupee weakens 5% against the dollar. An IT services company earns in dollars and pays salaries in rupees, but also runs onsite staff paid in dollars and buys imported... |
| MB0674 | ripple200:R03-04 | stock | natural | partial | The rupee weakens. The pharma exporter earns more on the US business and pays more for imported APIs and intermediates. Which listed name is a net winner and which is a n... |
| MB0675 | ripple200:R03-05 | stock | natural | partial | The rupee weakens and a components importer sells to Indian OEMs in rupees. Trace the landed cost, then the price negotiation, then the OEM's own cost. Who absorbs the cu... |
| MB0676 | ripple200:R03-06 | stock | natural | no | Build the screen: mid-caps with high import content, a long cash cycle and thin interest cover. Which names fail first if the rupee falls and working capital stretches at... |
| MB0677 | ripple200:R03-07 | stock | natural | partial | Household savings move from term deposits to mutual funds. Trace it to the bank's deposit mix, then to its NIM, then to the cost of the loan it can no longer fund cheaply... |
| MB0678 | ripple200:R03-08 | stock | natural | partial | Commercial paper rates spike. Trace it to the NBFC's borrowing mix, then to its spread, then to the borrower it has to turn away. Which lender funds itself most from the ... |
| MB0679 | ripple200:R03-09 | stock | natural | partial | Durable liquidity is injected on a large scale. Trace it to bank credit availability, then to corporate working-capital limits, then to the inventory a distributor can ca... |
| MB0680 | ripple200:R03-10 | stock | natural | partial | The central bank changes the CRR. Trace it to the bank's lendable resources, then to the marginal corporate loan price, then to the capex it enables. How much of a 50 bps... |
| MB0681 | ripple200:R03-11 | stock | natural | partial | Rates fall and the housing-finance company's spread compresses, but prepayments rise. Net the spread compression against the faster book turnover and say which listed HFC... |
| MB0682 | ripple200:R03-12 | stock | natural | partial | The repo goes up and car loans get dearer. Trace it to the EMI, then to the monthly payment at the entry price point, then to volumes for the entry segment versus the pre... |
| MB0683 | ripple200:R03-13 | stock | natural | partial | Rates fall and renewable developers bid lower tariffs. Trace it to the LCOE, then to the bid, then to the EPC margin and the module supplier. Which listed developer can b... |
| MB0684 | ripple200:R03-14 | stock | natural | no | A sugar mill's working capital is priced off a bank rate that just rose. Trace it to the cane payment schedule, then to the farmer's payment date, then to the next season... |
| MB0685 | ripple200:R03-15 | stock | natural | partial | The rupee weakens and a shipping line earns in dollars and pays charter hire in dollars. Does the weaker rupee help the reported profit at all, and what does the balance ... |
| MB0686 | ripple200:R03-16 | stock | natural | partial | The rupee weakens and DAP is imported. Trace it to the fertiliser subsidy, then to the fiscal cost, then to the subsidy payment delay and the company's receivables. Who c... |
| MB0687 | ripple200:R03-17 | stock | natural | partial | Gold is priced in dollars and the rupee weakens. Trace it to the jeweller's rupee cost, then to the retail price, then to the volume and the working capital. Which effect... |
| MB0688 | ripple200:R03-18 | stock | natural | partial | Long rates rise and the discount rate for a 20-year infrastructure asset moves. Trace it to the bid yield, then to the asset's book value, then to the developer's ability... |
| MB0689 | ripple200:R03-19 | stock | natural | partial | A steel distributor funds inventory with a bank line. Rates rise, prices fall, and the inventory is worth less than it cost. Trace the interest cost, then the inventory w... |
| MB0690 | ripple200:R03-20 | stock | natural | partial | The rupee weakens and an exporter with dollar receivables reports a translation gain. Trace it to the hedge book, then to the mark-to-market in other income, then to the ... |

### Family 17 - Business economics (55 cases; 40 with family inferred)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0481 | open300:A11-01 | stock | natural | partial | How do food-delivery fees affect a quick-commerce operator's profitability, and which line items move? |
| MB0482 | open300:A11-02 | stock | natural | partial | EV makers are discounting heavily. Which listed EV maker's margin is most exposed, and what does the disclosure say about discounting? |
| MB0483 | open300:A11-03 | stock | natural | partial | Brokers earn float income on client balances. How much of Angel One's revenue is float income, and what happens when rates fall? |
| MB0484 | open300:A11-04 | stock | natural | partial | A food-delivery platform raises its take rate by 100bp. Who pays, and how does that reach EBITDA? |
| MB0485 | open300:A11-05 | stock | natural | partial | Fuel is the largest variable cost for an airline. At what load factor does a marginal flight turn contribution-positive, and what does IndiGo disclose? |
| MB0486 | open300:A11-06 | stock | natural | partial | Maruti pays a royalty to Suzuki. How does a depreciation in the yen or rupee change that cost, and how much of revenue is it? |
| MB0487 | open300:A11-07 | stock | Hinglish | partial | Cement mein 80% vs 70% utilisation par UltraTech ka EBITDA kitna badalta hai? (Hinglish) |
| MB0488 | open300:A11-08 | stock | natural | partial | EPC contractors are paid late by government clients. How does that change RVNL's return on capital, and where is the working-capital disclosure? |
| MB0489 | open300:A11-09 | stock | natural | partial | Paint companies talk about premiumisation. What does that do to gross margin per litre, and can you measure it from the filings? |
| MB0490 | open300:A11-10 | stock | terse | partial | BHARTIARTL ARPU vs subscriber split FY26 |
| MB0491 | open300:A11-11 | stock | natural | partial | Gold-loan ticket sizes are rising. What does that do to Muthoot's loan-to-value and risk, and where is it disclosed? |
| MB0492 | open300:A11-12 | stock | natural | partial | A retailer's store payback depends on capex per store and store EBITDA. What payback does Trent's disclosure imply, and what is missing? |
| MB0493 | open300:A11-13 | stock | natural | partial | Semiconductor content per car is rising. Does that help Motherson more than a car-volume recovery would? |
| MB0494 | open300:A11-14 | stock | natural | partial | Data-centre capex is booming. Which listed power-equipment name has the clearest revenue link, and how would you size it? |
| MB0495 | open300:A11-15 | stock | natural | partial | Hospital ARPOB is the key unit metric. What drives it at Apollo, and how much is price versus occupancy? |
| MB0711 | ripple200:R05-01 | stock | natural | partial | A PLI-backed module maker cuts its price to fill a new line. Trace it to the non-PLI small-cap's ASP, then to its utilisation, then to its ability to keep the line runnin... |
| MB0712 | ripple200:R05-02 | stock | natural | no | Announced module and cell capacity exceeds the demand implied by the renewable bid pipeline. Trace the capacity announcements, then the utilisation, then the bid tariff, ... |
| MB0713 | ripple200:R05-03 | stock | natural | partial | A large cement group buys capacity in a region where a mid-size producer earns its best margin. Trace the acquisition to regional pricing, then to the mid-size producer's... |
| MB0714 | ripple200:R05-04 | stock | natural | partial | The largest cable maker cuts dealer price to defend share in wires. Trace it to the small cable maker's gross margin, then to its ability to hold inventory, then to its b... |
| MB0715 | ripple200:R05-05 | stock | natural | partial | A large diversified group enters decorative paints. Trace it to the incumbents' price response, then to the dealer count, then to the incumbent's ad spend and margin. How... |
| MB0716 | ripple200:R05-06 | stock | natural | no | Domestic steel capacity rises into a weak global market and imports gather. Trace the capacity, then the domestic price, then the mills' ask for protection, then the user... |
| MB0717 | ripple200:R05-07 | stock | natural | no | Tyre capacity is added by three players at once just as replacement demand softens. Trace the capacity, then the dealer price, then the margin, then the OEM contract for ... |
| MB0718 | ripple200:R05-08 | stock | natural | no | Three specialty-chemical makers raise equity for the same product family. Trace the fund raise, then the capex, then the commissioned capacity, then the product price two... |
| MB0719 | ripple200:R05-09 | stock | natural | partial | A large bank cuts its home-loan rate to win prime customers. Trace it to the HFC's spread, then to the HFC's disbursement mix, then to its cost of funds. Which listed HFC... |
| MB0720 | ripple200:R05-10 | stock | natural | partial | Insurance FDI is opened and two foreign groups announce Indian JVs. Trace them to the commission paid for distribution, then to the bancassurance partner's fee, then to t... |
| MB0721 | ripple200:R05-11 | stock | natural | no | Two CDMO players commission capacity in the same molecule class. Trace the capacity, then the pricing of the contract, then the API supplier's volume, then the innovator'... |
| MB0722 | ripple200:R05-12 | stock | natural | partial | Defence orders concentrate in two primes. Trace the order to the primes' capacity, then to the tier-2 suppliers' qualification, then to the small supplier's dependence on... |
| MB0723 | ripple200:R05-13 | stock | natural | partial | Electronics manufacturing scales on a PLI scheme. Trace the scheme to the assembler's scale, then to its component import bill, then to the domestic component supplier's ... |
| MB0724 | ripple200:R05-14 | stock | natural | partial | Two hospital chains add beds in the same metro. Trace the beds, then the occupancy, then the pricing per procedure, then the doctor's share. Which listed chain is most ex... |
| MB0725 | ripple200:R05-15 | stock | natural | partial | A food-delivery aggregator raises its commission and cuts discounts at the same time. Trace it to the restaurant's take rate, then to its menu price, then to its order vo... |
| MB0726 | ripple200:R05-16 | stock | natural | no | An airline inducts a large order of narrowbodies into a market with flat demand. Trace the capacity, then the fare, then the airport's aero revenue, then the lessor's lea... |
| MB0727 | ripple200:R05-17 | stock | natural | no | Two paper makers commission recycled-board capacity just as packaging demand slows. Trace the capacity, then the board price, then the converter's cost, then the FMCG con... |
| MB0728 | ripple200:R05-18 | stock | natural | no | The competing country's garment capacity comes back on line. Trace the order hand-back, then the Indian exporter's utilisation, then its yarn purchase, then the spinner's... |
| MB0729 | ripple200:R05-19 | stock | natural | partial | A bank decides to build a small-ticket personal-loan book. Trace it to the NBFC's borrower acquisition cost, then to its ticket size, then to its credit cost. Which liste... |
| MB0730 | ripple200:R05-20 | stock | natural | partial | A pharmacy chain buys a smaller chain. Trace it to store overlap, then to the merged store's footfall, then to the supplier's trade terms, then to the generic substitutio... |
| MB0731 | ripple200:R06-01 | stock | natural | no | A mid-cap rallies 60% and raises equity. Trace the dilution, then the objects of the issue, then the capex, then the industry's capacity two years later. When does the re... |
| MB0732 | ripple200:R06-02 | stock | natural | no | A promoter releases a pledge after a rally. Trace it to the cost of the promoter's funding, then to another round of refinancing, then to the share count and the EPS. Wha... |
| MB0733 | ripple200:R06-03 | stock | natural | no | A small-cap re-rates from a 2,000 crore to a 12,000 crore market cap and enters an index. Trace it to the passive flow, then to the float, then to the price. Does the ind... |
| MB0734 | ripple200:R06-04 | stock | natural | partial | A company splits its shares. Trace it to the tick size and the retail participation, then to the delivery percentage, then to the stock's liquidity. Does a split change a... |
| MB0735 | ripple200:R06-05 | stock | natural | no | A company with surplus cash announces a buyback instead of a capex. Trace it to the EPS, then to the return on capital, then to the capacity it did not build, then to its... |
| MB0736 | ripple200:R06-06 | stock | natural | no | A company raises equity and repays debt. Trace the interest saving, then the PAT, then the rating, then the cost of the next borrowing. Is the equity cheaper than the deb... |
| MB0737 | ripple200:R06-07 | stock | natural | no | Four IPOs in one industry price in a quarter. Trace the supply of paper to the listed peers' valuation, then to their fund-raise plans, then to their capex. Who is dilute... |
| MB0738 | ripple200:R06-08 | stock | natural | partial | A promoter sells 8% through an offer for sale. Trace it to the free float, then to the index weight, then to the stock's reaction to flows. Does a higher float help or hu... |
| MB0739 | ripple200:R06-09 | stock | natural | no | A company funds a large capex with debt. Trace it to the D/E, then to the rating, then to the cost of debt, then to the capex the company can still afford. Where is the b... |
| MB0740 | ripple200:R06-10 | stock | natural | partial | A stock doubles on a narrative and then raises guidance. Trace it to the fund flow, then to the delivery volume, then to the promoter's stake, then to the next guidance. ... |
| MB0741 | ripple200:R06-11 | stock | natural | partial | A stock is removed from an index. Trace it to the passive selling, then to the delivery percentage, then to the price recovery. How long does the flow effect last? |
| MB0742 | ripple200:R06-12 | stock | natural | partial | A stock enters the F&O ban. Trace it to the volatility, then to the delivery percentage, then to the stock's behaviour after the ban lifts. What is measurable and what is... |
| MB0743 | ripple200:R06-13 | stock | natural | partial | Insiders buy before a result. Trace it to the delivery spike, then to the price move, then to the result itself. Is the insider trade evidence of the result or of the pri... |
| MB0744 | ripple200:R06-14 | stock | natural | partial | Promoters raise their stake through creeping acquisition. Trace it to the free float, then to the delivery percentage, then to the price impact of a future sale. Which li... |
| MB0745 | ripple200:R06-15 | stock | natural | no | A promoter pledge is invoked. Trace it to the forced sale, then to the price, then to the company's borrowing cost. What does the disclosure actually contain? |
| MB0746 | ripple200:R06-16 | stock | natural | partial | A company announces a rights issue at a discount. Trace it to the share count, then to the EPS, then to the ex-rights price. Which number does a naive EPS series get wron... |
| MB0747 | ripple200:R06-17 | stock | natural | no | A conglomerate demerges a division. Trace it to the sum-of-the-parts, then to the index treatment, then to the two entities' borrowing costs. Who gets a better rating aft... |
| MB0748 | ripple200:R06-18 | stock | natural | partial | A company issues warrants to promoters at a premium to the market. Trace it to the dilution, then to the promoter's stake, then to the market's read of the price. What is... |
| MB0749 | ripple200:R06-19 | stock | natural | partial | A company announces a tender buyback at a premium. Trace it to the acceptance ratio, then to the EPS, then to the promoter's stake. What does the premium tell you? |
| MB0750 | ripple200:R06-20 | stock | natural | partial | The discount rate rises and a company's project IRR no longer clears it. Trace it to the capex decision, then to the order book, then to the capacity that is never built.... |

### Family 18 - Forward policy impact (55 cases; 40 with family inferred)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0496 | open300:A12-01 | stock | natural | partial | India Semiconductor Mission 2.0 was announced with a Rs 1,000 crore allocation. Which listed companies does it actually reach, and by what channel? |
| MB0497 | open300:A12-02 | stock | natural | partial | The US announced a 100% tariff on generic drug imports from 2028. Which listed Indian pharma exporters are most exposed, and how would you rank them? |
| MB0498 | open300:A12-03 | stock | natural | partial | A 200% tariff on generic drug imports from 2029 also exists in the policy store. How does that change the answer versus the 100% line from 2028? |
| MB0499 | open300:A12-04 | stock | Hinglish | partial | US ne Indian exports par extra 10% duty lagayi — kaunse textile exporters sabse zyada expose hain? (Hinglish) |
| MB0500 | open300:A12-05 | stock | natural | partial | The Samudra Manthan offshore-exploration scheme carries Rs 84,084 crore. Who benefits among listed oil and gas names, and over what horizon? |
| MB0501 | open300:A12-06 | stock | natural | partial | PMAY-U 2.0 approved another 1.93 lakh houses. Which sectors and listed names gain, and how big is that versus annual demand? |
| MB0502 | open300:A12-07 | stock | natural | partial | CAQM Direction 98 requires PTZ-camera monitoring for red-category industries in NCR. Which listed companies must spend, and roughly how much? |
| MB0503 | open300:A12-08 | stock | natural | partial | The FY26 Budget cut customs duty on flat-rolled steel products to 15%, effective 1 May 2025. Who gains and who loses among listed companies, and in what order? |
| MB0504 | open300:A12-09 | stock | natural | partial | Union Budget 2026-27 set the railway rolling-stock capex at Rs 52,109 crore. Which listed railway names does it reach first, and which only after the award cycle? |
| MB0505 | open300:A12-10 | stock | natural | partial | India signed the EU FTA on 27 January 2026, due in force at end-2026. Which listed textile exporters gain, and what did they do on the day? |
| MB0506 | open300:A12-11 | stock | natural | no | The FY26 Budget set up a Rs 20,000 crore Nuclear Energy Mission for SMR R&D, and the SHANTI Act opened plant operations to private firms. Which listed companies can actua... |
| MB0507 | open300:A12-12 | stock | natural | partial | GST process reforms were notified in October 2026. Which listed sectors gain most from simpler compliance, and does the store let you size it? |
| MB0508 | open300:A12-13 | stock | terse | partial | anti-dumping signal — which Indian makers gain |
| MB0509 | open300:A12-14 | stock | Hinglish | no | TDB-DST signed a Rs 130 crore RDI support agreement with BigEndian Semiconductors. Kaunsi listed company ko iska fayda? (Hinglish) |
| MB0510 | open300:A12-15 | stock | natural | partial | One Budget customs line cut duty on iron and steel articles from 25% to 15%. Which listed names sit on each side of that line, and why is the sign opposite? |
| MB0651 | ripple200:R02-01 | stock | natural | partial | The Union Budget 2026-27 adds a data-centres policy and an infrastructure capex thrust. Trace it from the policy to the equipment suppliers, then to their copper and CRGO... |
| MB0652 | ripple200:R02-02 | stock | natural | partial | The EU-India FTA is concluded in January 2026 and comes into force at the end of the year. Trace the duty cut to the EU-bound garment exporter, then to its cotton cost, t... |
| MB0653 | ripple200:R02-03 | stock | natural | no | US tariffs of 50% have hit Indian labour-intensive exports since August 2025. Trace the order loss to the exporter's utilisation, then to its contract workforce, then to ... |
| MB0654 | ripple200:R02-04 | stock | natural | no | The US has legislated a 100% tariff on generic drug imports from 2028 and 200% from 2029. Trace it back through the Indian exporter's US revenue, its front-loading decisi... |
| MB0655 | ripple200:R02-05 | stock | natural | partial | The RBI raised the repo 25 bps to 5.50% on 7 October 2026 and moved the stance to calibrated tightening. Trace it through the loan book that reprices first, the deposit b... |
| MB0656 | ripple200:R02-06 | stock | natural | partial | The 2025 easing cycle cut the repo by 50 bps in two instalments. Trace it to housing-finance affordability, then to housing sales, then to cement and steel demand, and sa... |
| MB0657 | ripple200:R02-07 | stock | natural | partial | The stance moved to accommodative in April 2025. Trace it through bank credit growth, then through the financing of corporate capex, then to the capital-goods order book.... |
| MB0658 | ripple200:R02-08 | stock | natural | no | The insurance sector is opened to 100% FDI. Trace it to the insurer's capital and competition, then to the bancassurance partner bank's fee income, then to the distributo... |
| MB0659 | ripple200:R02-09 | stock | natural | partial | The ECB framework is liberalised and a concessional forex swap is offered for PSU external borrowing. Trace it to the infra borrower's cost of debt, then to the capex dec... |
| MB0660 | ripple200:R02-10 | stock | natural | partial | FPI short-term and concentration limits are removed and the Fully Accessible Route is extended to longer G-secs. Trace it to foreign ownership of mid-caps, then to the fl... |
| MB0661 | ripple200:R02-11 | stock | natural | no | The export-proceeds realisation period is restored to nine months. Trace it to the exporter's FX conversion behaviour, then to forward premia, then to the importer's hedg... |
| MB0662 | ripple200:R02-12 | stock | natural | partial | Full hedging-cost support is offered to banks raising fresh 3-5 year FCNR(B) deposits. Trace it to the bank's swap cost, then to NIM, then to credit growth. Why would a b... |
| MB0663 | ripple200:R02-13 | stock | natural | partial | FDI restrictions are eased for land-bordering countries. Trace it to the defence and telecom JVs, then to localisation, then to the supplier base. Which listed defence na... |
| MB0664 | ripple200:R02-14 | stock | natural | partial | The collateral-free MSE loan limit is raised with effect from April 2026. Trace it to bank and NBFC credit to MSME suppliers, then to the supplier's terms with its large ... |
| MB0665 | ripple200:R02-15 | stock | natural | partial | Kisan Credit Card guidelines are revised. Trace it to agri-credit availability, then to the farmer's purchase of seed and crop-protection, then to the agrochem and seed c... |
| MB0666 | ripple200:R02-16 | stock | natural | partial | Roads-and-bridges capital outlay is raised again in the Budget. Trace it to the award of EPC contracts, then to cement and steel consumption at the site, then to the equi... |
| MB0667 | ripple200:R02-17 | stock | natural | partial | Jal Jeevan Mission allocations continue. Trace them to pipe demand, then to the steel and PVC input, then to the contractor's margin under a state tender. Where does the ... |
| MB0668 | ripple200:R02-18 | stock | natural | partial | The 16th Finance Commission discontinues revenue-deficit and sector-specific grants to states. Trace it to state capex spending, then to the contractors that depend on st... |
| MB0669 | ripple200:R02-19 | stock | natural | partial | Additional borrowing space is offered to states for power-sector reforms. Trace it to discom dues and payments, then to the generator's receivable days, then to the gener... |
| MB0670 | ripple200:R02-20 | stock | natural | no | A National Mission on High Yielding Seeds is announced. Trace it to seed replacement rates, then to agrochem and fertiliser use per acre, then to farm income, then to two... |
| MB0691 | ripple200:R04-01 | stock | natural | no | A shipping route closes. Europe-bound Indian goods spend two extra weeks at sea, the buyer defers the programme, the exporter's finished stock piles up, and its export in... |
| MB0692 | ripple200:R04-02 | stock | natural | no | The US raises tariffs on steel and aluminium. Indian exporters lose the US premium, divert volume domestically, and the domestic HRC price falls. Trace it to the auto anc... |
| MB0693 | ripple200:R04-03 | stock | natural | no | Chinese producers dump surplus into India. Specialty-chemical ASPs fall, the domestic producer cuts output, and when the dumping stops the buyer has lost a qualified loca... |
| MB0694 | ripple200:R04-04 | stock | natural | partial | A tariff on generic drugs is announced for 2028. The US buyer front-loads inventory in 2027, the Indian exporter runs its plants flat out, and then the order stops. Trace... |
| MB0695 | ripple200:R04-05 | stock | natural | no | The EU brings in a carbon border adjustment on steel and aluminium. The Indian exporter's carbon cost enters the landed price, the EU buyer looks for a lower-carbon sourc... |
| MB0696 | ripple200:R04-06 | stock | natural | no | Edible-oil and fertiliser supply from the Black Sea is disrupted. Trace it to the packaged-food company's input, then to the price point, then to the rural consumer. Whic... |
| MB0697 | ripple200:R04-07 | stock | natural | no | A competitor country's garment industry is disrupted. EU and US buyers shift programmes to India, the exporter adds a shift, and cotton buying tightens. How far can the I... |
| MB0698 | ripple200:R04-08 | stock | natural | partial | Crude spikes and the retail price of petrol and diesel is not raised. Trace it to the refiner-marketer's under-recovery, then to the subsidy or the PSU's balance sheet, t... |
| MB0699 | ripple200:R04-09 | stock | natural | partial | Component export controls tighten. The Indian electronics assembler's BOM cost rises, the customer refuses a price rise, and the assembler has to localise faster than its... |
| MB0700 | ripple200:R04-10 | stock | natural | no | A trade partner opens an excess-capacity investigation. Trace it to the risk premium on Indian exports, then to the buyer's order timing, then to the exporter's capacity ... |
| MB0701 | ripple200:R04-11 | stock | natural | no | Two trade agreements pull in opposite directions: a US tariff raises the landed cost, an EU agreement lowers it. For the same exporter, which destination wins on margin, ... |
| MB0702 | ripple200:R04-12 | stock | natural | partial | Seaborne coal prices spike. The generator's fuel cost rises, the regulated tariff does not immediately, and the aluminium smelter buying from the exchange pays the mercha... |
| MB0703 | ripple200:R04-13 | stock | natural | no | LME copper jumps and a cable maker is holding inventory bought at the old price. The holding gain flatters the quarter, the dealer sees the new price list, and the order ... |
| MB0704 | ripple200:R04-14 | stock | natural | no | Foreign investors sell. The mid-cap index falls, the planned QIP window closes, and a company that needed equity funds its capex with debt instead. Trace the sequence and... |
| MB0705 | ripple200:R04-15 | stock | natural | no | War-risk premia rise on a shipping route. Trace it to the charter rate, then to the importer's landed cost, then to the inventory decision. Which listed shipping name ben... |
| MB0706 | ripple200:R04-16 | stock | natural | no | Global rubber rises sharply. Traces it to the Indian tyre maker's cost, then to the replacement price, then to the truck operator's cost per km, then to the replacement i... |
| MB0707 | ripple200:R04-17 | stock | natural | partial | Gold rises in dollars and the rupee weakens in the same quarter. Trace it to the jeweller's landed cost, then to the wedding-season volume, then to the inventory the stor... |
| MB0708 | ripple200:R04-18 | stock | natural | no | A foreign strategic buyer takes a stake in an Indian listed company's competitor. Trace it to the competitor's capacity plan, then to the industry's price behaviour, then... |
| MB0709 | ripple200:R04-19 | stock | natural | no | A monsoon deficit hits fodder and water. Milk procurement falls, the dairy's procurement price rises, and the packaged-food buyer's cost follows. Trace it and say whether... |
| MB0710 | ripple200:R04-20 | stock | natural | no | The US raises the tariff on shrimp and the EU opens a quota. The Indian exporter's destination margin flips, the hatchery's order book follows, and the farmer decides the... |

### Family 19 - Second-order / supply chain (15 cases)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0511 | open300:A13-01 | stock | natural | partial | Who makes the wagons Indian Railways buys, and who supplies those wagon makers with steel? Name both layers. |
| MB0512 | open300:A13-02 | stock | natural | partial | Defence indigenisation gave BEL and HAL large orders. Which second-layer listed suppliers gain, and how do you establish the link? |
| MB0513 | open300:A13-03 | stock | natural | partial | The TCS on coal and iron-ore sales doubles to 2% from 1 April 2026. Who is hit first, who second, and does any listed layer gain? |
| MB0514 | open300:A13-04 | stock | natural | partial | Copper goes into cables, which go into EPC projects. Who bears the copper risk in that three-layer chain, and what contract feature decides it? |
| MB0515 | open300:A13-05 | stock | natural | partial | Semiconductor Mission 2.0 should lift EMS assembly. Which chemical and material suppliers sit under that, and is the link disclosed? |
| MB0516 | open300:A13-06 | stock | terse | partial | solar module chain — BORORENEW glass/EVA link |
| MB0517 | open300:A13-07 | stock | natural | partial | BharatNet needs optical fibre and telecom gear. Which listed suppliers gain, and how is the award flowing? |
| MB0518 | open300:A13-08 | stock | natural | partial | Cochin Shipyard's Drydocks World JV will need steel and marine equipment. Which listed companies are the plausible suppliers, and what is the evidence standard? |
| MB0519 | open300:A13-09 | stock | natural | partial | The Mumbai-Ahmedabad high-speed-rail packages use TBMs. Which listed companies supply the civil inputs, and what does Afcons' own disclosure say? |
| MB0520 | open300:A13-10 | stock | Hinglish | partial | EV adoption badhne se kaunse auto-component names jeetenge aur kaun harenge? (Hinglish) |
| MB0521 | open300:A13-11 | stock | natural | no | Airline fleet expansion means more MRO and leasing. Which listed names capture that, and which part is NOT IN DATA? |
| MB0522 | open300:A13-12 | stock | natural | no | Hospital capex needs imported medical equipment. Which listed suppliers gain, and can the store quantify it? |
| MB0523 | open300:A13-13 | stock | natural | partial | US tariffs on Indian textiles have been 50% since August 2025. Which listed dye and chemical suppliers are exposed second-hand, and what is the evidence bar? |
| MB0524 | open300:A13-14 | stock | natural | partial | Budget 2026-27 put Rs 7,500 crore into railway signalling and telecom. Beyond the wagon makers, who in the listed universe gains second-hand, and in what order? |
| MB0525 | open300:A13-15 | stock | Hinglish | partial | Railway wagon banane wale ko steel kaun deta hai, aur scrap/CRGO pe exemption extend hone se chain mein kaun jeetta hai, kaun peeche reh jaata hai? (Hinglish) |

### Family 20 - Out-of-scope and bizarre (35 cases; 20 with family inferred)

| mid | source | level | style | coverage | question |
| --- | --- | --- | --- | --- | --- |
| MB0616 | open300:A20-01 | stock | terse | no | What will Reliance's share price be on Diwali 2027? |
| MB0617 | open300:A20-02 | stock | natural | no | How many electric two-wheelers did Ola Electric deliver in September 2026? |
| MB0618 | open300:A20-03 | stock | natural | partial | What is Dixon's CEO paid, and how has that changed in three years? |
| MB0619 | open300:A20-04 | index | natural | no | Which company will be the next Nifty 50 inclusion, and when? |
| MB0620 | open300:A20-05 | index | natural | partial | What exactly did the RBI governor say about the rupee at the last MPC, and does the store have his words? |
| MB0621 | open300:A20-06 | stock | terse | no | How much of Titagarh does FII money own right now? |
| MB0622 | open300:A20-07 | stock | natural | partial | How many shares did TruAlt's promoter actually pledge in September 2026? |
| MB0623 | open300:A20-08 | stock | natural | partial | Why exactly did Milefur's auditor resign? Give the auditor's own words. |
| MB0624 | open300:A20-09 | stock | terse | partial | Which listed company had the highest employee attrition in FY26? |
| MB0625 | open300:A20-10 | stock | terse | partial | How much did Suzlon pay its statutory auditor last year? |
| MB0626 | open300:A20-11 | stock | natural | no | What is the exact copper content per kilometre of a 33 kV cable? |
| MB0627 | open300:A20-12 | stock | terse | no | Which mid-cap will double in 2027? |
| MB0628 | open300:A20-13 | stock | terse | partial | SRF FY26 patent count by chemistry |
| MB0629 | open300:A20-14 | index | natural | partial | How much money did retail investors lose on 4 June 2024, in rupees? |
| MB0630 | open300:A20-15 | index | natural | partial | What did the Finance Minister say about capital-gains tax in the 2026 Budget, and is the exact sentence stored? |
| MB0771 | ripple200:R08-01 | stock | natural | partial | The rupee weakens. An aluminium producer exports metal priced in dollars and imports coal priced in dollars. Net the two legs by revenue and cost geography, and say which... |
| MB0772 | ripple200:R08-02 | stock | natural | partial | The repo is raised 25 bps. A bank's loan yield rises and its bond portfolio falls in value on the same day. Net the NIM gain against the treasury loss, and say which one ... |
| MB0773 | ripple200:R08-03 | stock | natural | partial | Copper rises. A cable maker's realisation rises with the metal, its working capital rises with the same metal, and its dealer may delay the order. Net the margin gain aga... |
| MB0774 | ripple200:R08-04 | stock | natural | partial | Crude rises. The refiner-marketer loses on the regulated retail sale and the upstream producer gains on the same barrel. If the two are the same group, is the group a net... |
| MB0775 | ripple200:R08-05 | stock | natural | partial | The US tariff goes up and the EU duty comes down. For one textile exporter, does the EU gain cover the US loss this year, or only next year? |
| MB0776 | ripple200:R08-06 | stock | natural | no | Freight rates double. A shipping line earns more on the voyage and pays more for the charter and the bunker. Net the two and say which share of the fleet is on a fixed ch... |
| MB0777 | ripple200:R08-07 | stock | natural | partial | Steel rises. The mill's revenue rises and its coking coal cost rises. Net the two and say which mill has captive coal or iron ore. |
| MB0778 | ripple200:R08-08 | stock | natural | partial | The repo is cut. A housing-finance company's spread narrows and its disbursements rise. Net the margin against the volume and say which HFC's return on equity actually im... |
| MB0779 | ripple200:R08-09 | stock | natural | partial | Gold rises. The jeweller's holding gain is real and its customer defers. Net the gain against the volume loss and say which one the auditor would let you book. |
| MB0780 | ripple200:R08-10 | stock | natural | no | An incentive scheme pays a subsidy per unit and the large player cuts the price by the same amount to win volume. Net the subsidy gain against the price cut and say who k... |
| MB0781 | ripple200:R08-11 | stock | natural | partial | The rupee weakens. An auto ancillary exports to Europe and imports components from China. Net the export gain against the import cost and say where the euro and the yuan ... |
| MB0782 | ripple200:R08-12 | stock | natural | no | Wage inflation rises. The consumer company's volume improves with the wage and its margin falls with the same wage. Net them and say which side is bigger for a labour-int... |
| MB0783 | ripple200:R08-13 | stock | natural | partial | A data-centre policy raises demand for the equipment maker and raises the power cost of its own factory. Net the order gain against the cost and say which one is bigger f... |
| MB0784 | ripple200:R08-14 | stock | natural | partial | A safeguard duty is imposed on steel. The mill's price rises and the auto ancillary's input rises. For a group that owns both a mill and an auto business, is the net posi... |
| MB0785 | ripple200:R08-15 | stock | natural | partial | Insurance FDI is opened. Capital and competition arrive together. Net the capital gain to the incumbent's stake against the compression of its underwriting margin. |
| MB0786 | ripple200:R08-16 | stock | natural | partial | Electric vehicles take share. The ancillary's engine-parts revenue falls and its EV-parts revenue rises. Net the two by product line and say which listed name has the wid... |
| MB0787 | ripple200:R08-17 | stock | natural | partial | Pet coke rises and cement demand rises at the same time. The producer's cost is up and its volume is up. Net the two and say which regional producer is best placed. |
| MB0788 | ripple200:R08-18 | stock | natural | partial | Coal gets dearer and the regulated tariff is revised at the same time. Net the fuel cost against the tariff order and say which generator gets the pass-through first. |
| MB0789 | ripple200:R08-19 | stock | natural | partial | A tariff on generic drugs raises the cost of the US business and lowers the relative cost of the Indian business. For a company with both, does the India margin rise or d... |
| MB0790 | ripple200:R08-20 | stock | natural | partial | An NBFC grows its AUM fast and its credit cost rises at the same time. Net growth against credit cost and say which listed lender's provisioning cycle is closest to turni... |

## 5. Files

- `MASTER_BANK.jsonl` - one JSON object per unique case (the representative), with `duplicates` listing every merged source row.
- `MASTER_BANK.md` - this file.
- `GAP_ROLLUP.md` - every named gap, deduplicated and ranked by unique cases blocked per unit of effort, with the held-data verdict.

