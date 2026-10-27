# Widened BSE concall candidates — FY25+ — 2026-10-27T22:05:47+00:00

- window: BSE dissemination date >= 2024-04-01; known_at = DissemDT
- subcategories: Analyst / Investor Meet, General, Investor Presentation, Press Release / Media Release
- announcements read: 204,685; they yield **5,139** transcript-signalling candidates
- attachment names are BSE UUIDs, so they add 0 candidates; the headline does the work
- no network: this is the `--widen --dry-run` report

## 1. Widened candidates by subcategory

| subcategory | rows |
|---|---|
| Analyst / Investor Meet | 4268 |
| General | 529 |
| Investor Presentation | 332 |
| Press Release / Media Release | 10 |
| **total** | **5139** |

By fiscal quarter:

| quarter | rows |
|---|---|
| FY25Q1 | 526 |
| FY25Q2 | 478 |
| FY25Q3 | 533 |
| FY25Q4 | 482 |
| FY26Q1 | 516 |
| FY26Q2 | 480 |
| FY26Q3 | 545 |
| FY26Q4 | 487 |
| FY27Q1 | 533 |
| FY27Q2 | 508 |
| FY27Q3 | 51 |

Subcategory x quarter:

| subcategory | quarter | rows |
|---|---|---|
| Analyst / Investor Meet | FY25Q1 | 464 |
| General | FY25Q1 | 39 |
| Investor Presentation | FY25Q1 | 23 |
| Analyst / Investor Meet | FY25Q2 | 387 |
| General | FY25Q2 | 63 |
| Investor Presentation | FY25Q2 | 28 |
| Analyst / Investor Meet | FY25Q3 | 444 |
| General | FY25Q3 | 57 |
| Investor Presentation | FY25Q3 | 32 |
| Analyst / Investor Meet | FY25Q4 | 401 |
| General | FY25Q4 | 42 |
| Investor Presentation | FY25Q4 | 39 |
| Analyst / Investor Meet | FY26Q1 | 433 |
| General | FY26Q1 | 52 |
| Investor Presentation | FY26Q1 | 28 |
| Press Release / Media Release | FY26Q1 | 3 |
| Analyst / Investor Meet | FY26Q2 | 384 |
| General | FY26Q2 | 58 |
| Investor Presentation | FY26Q2 | 35 |
| Press Release / Media Release | FY26Q2 | 3 |
| Analyst / Investor Meet | FY26Q3 | 446 |
| General | FY26Q3 | 58 |
| Investor Presentation | FY26Q3 | 40 |
| Press Release / Media Release | FY26Q3 | 1 |
| Analyst / Investor Meet | FY26Q4 | 394 |
| General | FY26Q4 | 56 |
| Investor Presentation | FY26Q4 | 36 |
| Press Release / Media Release | FY26Q4 | 1 |
| Analyst / Investor Meet | FY27Q1 | 457 |
| General | FY27Q1 | 42 |
| Investor Presentation | FY27Q1 | 33 |
| Press Release / Media Release | FY27Q1 | 1 |
| Analyst / Investor Meet | FY27Q2 | 414 |
| General | FY27Q2 | 57 |
| Investor Presentation | FY27Q2 | 36 |
| Press Release / Media Release | FY27Q2 | 1 |
| Analyst / Investor Meet | FY27Q3 | 44 |
| General | FY27Q3 | 5 |
| Investor Presentation | FY27Q3 | 2 |

## 2. Overlap with the 9,390 Earnings Call candidates

- same (ISIN, fiscal quarter): **2838**
- same attachment name: **0**
- either key: **2838** (55.2% of the widened set already covered)
- fresh rows to fetch: **2301**
- duplicates inside the widened set by (ISIN, quarter): 1061; earnings-call rows without an ISIN: 0

(ISIN, quarter) is a proxy, not proof of the same document: every covered row has a different attachment name, so some are different events in a quarter that also had an Earnings Call transcript. The dedupe drops them anyway, as specified.

```
a410df96-5beb-4d74-802f-75d7b7dde0d0 | TARIL | FY25Q1 | We would like to inform you that pursuant to Regulation 30 of SEBI (Li
bf58409d-e1e0-487c-b559-1ab11ebf21ce | TARIL | FY25Q1 | We send herewith updated details of earnings conference call to discus
7e4954f2-83c2-4f22-9b8f-884957fd1e4b | LATENTVIEW | FY25Q1 | Pursuant to Regulation 30 of SEBI (Listing Obligations and Disclosure 
a7dbc1d5-afce-484d-959e-18b5de55abf8 | 360ONE | FY25Q1 | We wish to inform you that the Company will host an earnings call at 2
4c49dfa6-e519-4c0c-9098-2556320a98e6 | DATAMATICS | FY25Q1 | Transcript of conference call with Analyst held on April 02, 2024
```

## 3. Recall against the pilot's 1,771 other-subcategory old rows

- old rows outside the Earnings Call set: 1,771
- of those inside the four subcategories (the widest this mode can reach): 1,686
- caught by the widened filter: **1,589** (89.7% of all 1,771, 94.2% of the in-scope 1,686)
- missed: 182
- why the misses missed: {'not in the BSE announcement feed': 66, 'no transcript signal in the headline': 63, 'schedule / intimation only': 26, 'other subcategory': 19, 'audio/video or recording link': 8}

20 misses (newsid | subcategory | headline):

```
09f198dc-33ee-4829-869e-c37b6f9b38d2 | Analyst / Investor Meet | Please refer enclosed file
5f25346c-2bcf-4e8d-86f2-6246ff1ad7fd | Analyst / Investor Meet | Please refer enclosed file
98dd2f4c-d729-4dae-b727-1ce96c6b58de | Analyst / Investor Meet | Please refer enclosed file
aff33236-0a86-4c64-8e08-18c688241a92 | Analyst / Investor Meet | Please refer enclosed file
941e9216-61f0-4c83-acd0-218c2246bb21 | Analyst / Investor Meet | please refer enclosed file
a6ac5e6e-587e-49cf-ae2b-8ca28da10f07 | Analyst / Investor Meet | Dear Sir/Ma'am, Pursuant to Regulation 46(2) of the Securities Exchange Boa
5db34f93-b7db-47a9-b7b0-492911dce166 | Analyst / Investor Meet | Dear Sir/Ma'am, Pursuant to Regulation 46(2) of the Securities Exchange Boa
b89c96ec-af5d-43ab-a741-e69a0fdbf6ea | Analyst / Investor Meet | as per annexure enclosed
7f7b42c5-b75c-4705-832f-7653fd6c7f71 | Analyst / Investor Meet | Audio link of Investor Call held on 30th April, 2024
5690bec6-0e97-43e8-9da1-d85a9695784d | Analyst / Investor Meet | In continuation of our letter dated 5th August, 2024 and pursuant to Regula
298a034f-2ce2-42e4-8e67-499737506e56 | Analyst / Investor Meet | In furtherance to our letters dated August 09, 2024 and August 14, 2024, pu
0728711c-a6f2-4440-88f0-2573845831f2 | Analyst / Investor Meet | In furtherance to our letters dated November 18, 2025 and November 25, 2025
580cf8ef-6363-4124-9b9e-9bad6fecb73f | Analyst / Investor Meet | Attached
b5a9437e-831f-4206-be66-87fc328c6007 | Analyst / Investor Meet | Pursuant to Regulation 30 read with Para A of Part A of Schedule III of the
835aa6af-07e0-414c-92fa-798a3631548e | Analyst / Investor Meet | Pursuant to Regulation 30 read with Para A of Schedule III and Regulation 4
bb60874c-c7b1-46df-9c07-e780c7678ce3 | Analyst / Investor Meet | Pursuant to Regulation 30 read with Para A of Schedule III and Regulation 4
7507cd0c-bf53-4fd4-a2dc-462a2465606a | Analyst / Investor Meet | Pursuant to Regulation 30 read with Para A of Schedule III and Regulation 4
7e15ae90-0761-4615-a4b1-a21bb0c1e5c2 | Analyst / Investor Meet | Pursuant to Regulation 30 read with Para A of Schedule III and Regulation 4
c9650e19-e0d8-44b5-a6a3-d588c0f8dfd2 | Analyst / Investor Meet | We wish to inform you that, pursuant to Regulation 30 of the Securities and
c6b6d2df-72c1-410b-be80-09daf67b3595 | Analyst / Investor Meet | In continuation to our letter dated May 08, 2025 and May 13, 2025 and pursu
```

## 4. Classifier precision on widened docs already on disk

- stores checked: D:\RealityEngine\raw\concall_pdfs_probe, D:\RealityEngine\raw\concall_pdfs
- widened candidates with bytes on disk: 101
- sampled and classified: 40 (ok 40)
- precision (real transcripts / sampled): **85.0%** (34/40); over readable PDFs: 85.0%
- classes: {'cover_letter': 3, 'transcript': 34, 'audio_link': 2, 'intimation': 1}

## 5. Fetch time for the fresh rows

| metric | value |
|---|---|
| widened candidates | 5139 |
| already in the Earnings Call set (no fetch) | 2838 |
| fresh fetches | 2301 |
| pacing floor | 1 request / 2.5 s (<= 24.0/min) |
| wall time at the pacing floor | 1.6 h (96 min) |
| wall time at the measured 18.2/min | 2.1 h |
| expected real transcripts (precision 85.0%) | 1956 |

Run it later, only after the 9,390 fetch has finished:

```bash
python -m reality_engine.scripts.concall_refetch --widen --fetch --interval 2.5
```
