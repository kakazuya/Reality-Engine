# Concall PDF refetch — FY25+ BSE transcripts — 2026-10-28T14:18:24+00:00

- window: BSE dissemination date >= 2024-04-01 (ann.SUBCATNAME = 'Earnings Call Transcript'), known_at = DissemDT, never a crawl date
- candidates: 9390 announcements, 11 fiscal quarters x A-P/Q-Z
- rate enforced: >= 0.25 s between requests across 8 worker(s) (<= 240.0 requests/min); a 403/429/503 pauses every worker

## 1. Candidate set

| quarter | A-P | Q-Z | total |
|---|---|---|---|
| FY25Q1 | 606 | 252 | 858 |
| FY25Q2 | 574 | 233 | 807 |
| FY25Q3 | 607 | 266 | 873 |
| FY25Q4 | 590 | 246 | 836 |
| FY26Q1 | 656 | 280 | 936 |
| FY26Q2 | 626 | 258 | 884 |
| FY26Q3 | 724 | 310 | 1034 |
| FY26Q4 | 703 | 285 | 988 |
| FY27Q1 | 778 | 342 | 1120 |
| FY27Q2 | 733 | 301 | 1034 |
| FY27Q3 | 16 | 4 | 20 |

Attachment sizes: min=29,633 median=665,528 p90=2,268,241 max=22,877,560 bytes; 9390 rows

## 2. Old `corporate_documents` coverage (FY25+)

- old CONCALL_TRANSCRIPT rows with a usable filing date in the window: 12675
- of them covered by this ann candidate set (bse_newsid): 9385
- candidates missing from corporate_documents: 5
- old rows NOT in this candidate set: 1771 filed under another BSE subcategory + 1519 with no bse_newsid (NSE-sourced)
- of those old rows, same (isin, fiscal quarter) as a candidate (BSE/NSE or refiled duplicate): 930
- their BSE subcategories: {'Analyst / Investor Meet': 1437, 'General': 236, '(not in ann)': 74, 'Investor Presentation': 12, 'AGM': 9, 'Acquisition': 1, 'Press Release / Media Release': 1, 'Meeting Updates': 1}

Missing from the old side (examples):

```
16743fab-182f-49f9-8072-995dbacdddd0 | SRF | 2024-10-24T07:34:51.053 | Audio recording of the Earnings call held on 23rd October 20
ac9b997f-e84b-41a1-ae2e-76b277c4e8a4 | GLASSWALL | 2026-10-13T17:09:32.703 | Transcript of Earnings Call with respect to Financial Result
b3d0c90d-a6fe-4fe0-952f-ad380f9fbc1a | ARCIL | 2026-10-13T17:40:52.833 | Submission of Transcript of Earnings Conference Call held on
cd603afb-96b8-45c1-914d-c9d72f2316bf | KANOHAR | 2026-10-14T14:22:57.94 | Transcript of Earnings Call with respect to Financial Result
a461d052-8d3d-476e-a68c-1a93703d4a66 | TCS | 2026-10-14T15:55:38.44 | Transcript of earnings conference call for quarter and six-m
```

Missing from the candidate set (examples):

```
140704 | d7273254-5219-43a7-a20a-4c357791d591 | RBL Bank Limited informs the exchange about Transcript of Ea | 2026-10-16T19:32:57.417
140710 | 874dc202-8f1a-4a05-a09c-cb6157b26e76 | Enclosed herewith transcript of the Earnings Call held on Fr | 2026-10-19T19:27:05.577
140711 | 304ef81b-1c22-4182-bdef-248a7511229b | Transcript of Conference Call held on October 16, 2026 | 2026-10-19T17:09:58.57
140712 | 5c774950-0839-43bc-8fa7-9aa90f7cb026 | Transcript of the Post Results Conference Call on Consolidat | 2026-10-19T16:46:23.53
140713 | a0dbc78f-d931-4092-a709-0749d8448b81 | The Company has informed the Exchange about Transcript of Ea | 2026-10-19T15:29:19.927
```

## 3. Probe store (read-only reuse)

- staged PDFs: 773 (bad sha/name: 0)
- candidates with bytes already on disk: 560 (6.0%) across 560 distinct files
- classification of those (all 560 readable): {'transcript': 496, 'cover_letter': 39, 'audio_link': 13, 'intimation': 6, 'other': 6}
- unique real transcripts already held: 496 of 496 transcripts (transcript share 88.6%, duplicate share 0.0%)

## 4. Headlines (all candidates, no fetch)

- distinct headlines: 7967; repeat-headline rows: 1865

| guessed class | rows |
|---|---|
| transcript? | 7920 |
| unknown | 579 |
| intimation | 553 |
| audio_link | 338 |

Top headlines:

```
  297  Earnings Call Transcript
   92  Earning Call Transcript
   69  Earnings call transcript
   44  Transcript of Earnings Call
   40  Transcript
   31  Earnings call Transcript
   19  Enclosed
   19  Attached
   19  Earning call transcript
   18  Transcript of Earning Call
   17  As enclosed
   17  As per attachment
```

## 5. Duplicates from metadata alone (no fetch)

- identical sha256 among rows that carry one: 30 duplicate rows in 30 groups (0.32%)
- same (isin, quarter, attachment size): 30 duplicate rows in 30 groups (0.3%); size-rule precision where both rows carry a sha256: 30/30 pairs
- same (isin, quarter) — the same call refiled under another newsid: 427 duplicate rows in 403 groups (4.5%)
- same (isin, attachment size) ignoring quarter: 30 rows
- same (headline, size): 26 rows in 26 groups

## 6. Pilot (200 docs)

- sampled 9390, ok 9382, failed 8, reused 560, skipped 0
- resumed from the journal (not fetched again): 4810
- wall clock 20.3 min, 4317 HTTP requests, 461.91 PDFs/min end-to-end
- classes: {'other': 69, 'transcript': 8301, 'cover_letter': 698, 'audio_link': 234, 'intimation': 80, 'failed': 8}
- transcript share on fetched docs: 88.5%; duplicates: 129 (1.6% of transcripts)

| source | tried | reused | ok | failed | reasons |
|---|---|---|---|---|---|
| bse | 8830 | 0 | 8822 | 8 | not a PDF=8 |
| probe | 560 | 560 | 560 | 0 | - |

| cell | tried | ok | failed | unique transcripts |
|---|---|---|---|---|
| FY25Q1-A-P | 606 | 606 | 0 | 505 |
| FY25Q1-Q-Z | 252 | 252 | 0 | 214 |
| FY25Q2-A-P | 574 | 574 | 0 | 479 |
| FY25Q2-Q-Z | 233 | 233 | 0 | 196 |
| FY25Q3-A-P | 607 | 607 | 0 | 523 |
| FY25Q3-Q-Z | 266 | 266 | 0 | 226 |
| FY25Q4-A-P | 590 | 590 | 0 | 512 |
| FY25Q4-Q-Z | 246 | 246 | 0 | 211 |
| FY26Q1-A-P | 656 | 656 | 0 | 581 |
| FY26Q1-Q-Z | 280 | 280 | 0 | 243 |
| FY26Q2-A-P | 626 | 626 | 0 | 556 |
| FY26Q2-Q-Z | 258 | 258 | 0 | 222 |
| FY26Q3-A-P | 724 | 724 | 0 | 638 |
| FY26Q3-Q-Z | 310 | 310 | 0 | 271 |
| FY26Q4-A-P | 703 | 703 | 0 | 627 |
| FY26Q4-Q-Z | 285 | 285 | 0 | 251 |
| FY27Q1-A-P | 778 | 774 | 4 | 688 |
| FY27Q1-Q-Z | 342 | 338 | 4 | 300 |
| FY27Q2-A-P | 733 | 733 | 0 | 646 |
| FY27Q2-Q-Z | 301 | 301 | 0 | 268 |
| FY27Q3-A-P | 16 | 16 | 0 | 11 |
| FY27Q3-Q-Z | 4 | 4 | 0 | 4 |

- pages: n=4572 min=1.0 median=17.0 mean=16.5521 p90=23.0 max=87.0
- text chars: n=9382 min=0.0 median=46049.0 mean=42775.931 p90=61227.0 max=238336.0
- image-only page share: n=4572 min=0.0 median=0.0 mean=0.0028 p90=0.0 max=0.9565
- uppercase letter share: n=4572 min=0.026 median=0.0546 mean=0.0661 p90=0.095 max=0.3856
- same-document shingle match: n=3762 min=0.0 median=1.0 mean=0.9365 p90=1.0 max=1.0
- same-document match rate (>= 0.5 shingles): 98.3%
- lowercased sources (uppercase < 0.5%): 0
- recorded sha256 matched the fetched bytes: [('yes', 4555)] of 9373 rows carrying one

## 7. Projection for the full FY25+ window (unique real transcripts)

| metric | value |
|---|---|
| candidates | 9390 |
| already on disk (reuse, no fetch) | 560 |
| fetches still needed | 8830 |
| measured transcript share | 88.5% |
| measured duplicate share | 1.6% |
| estimated unique real transcripts | 8179 |
| already held unique transcripts | 496 |
| unique transcripts still to fetch | 7683 |
| fetch wall time at 240.0 req/min | 0.6 h (37 min) |
| requests incl. retries (success 100%) | 8838 |

## 8. Samples

### HATSUN FY25Q1 — other (2024-04-05T16:22:27.56)

- source=bse reused=False bytes=4348103 sha256 `78a43693a58a5fd4…` pages=None chars=8411 upper=None
- headline: Transcript of the Interview given by Mr. R G Chandramogan, Chairman of the Company to CNBC-TV18 on April 01, 2024

```

```

### GOPAL FY25Q1 — transcript (2024-04-08T18:20:39.777)

- source=bse reused=False bytes=1847674 sha256 `6e0a590ccb59b6a4…` pages=None chars=55534 upper=None
- headline: enclosed herewith the transcript of the earnings conference call with Investors and Analysts.

```

```

### ATAM FY25Q1 — cover_letter (2024-04-11T18:45:51.813)

- source=bse reused=False bytes=735890 sha256 `ecb595a9fb544da0…` pages=None chars=2697 upper=None
- headline: Pursuant to Regulation 30 and Part A of Schedule III of SEBI (LODR) Regulations, 2015, we would like to inform you that the Company will hold a Earnings Conference Call with Investors on ....

```

```

### ANANDRATHI FY25Q1 — audio_link (2024-04-15T17:52:17.227)

- source=bse reused=False bytes=264287 sha256 `396951a2cd558ab8…` pages=None chars=2065 upper=None
- headline: Link of Audio Recording of Earning conference call held today i.e. 15th April, 2024  .

```

```

### ANGELONE FY25Q1 — cover_letter (2024-04-18T18:44:22.66)

- source=bse reused=False bytes=626681 sha256 `fe5a2876864ceeb7…` pages=None chars=1982 upper=None
- headline: Earnings call transcript

```

```
