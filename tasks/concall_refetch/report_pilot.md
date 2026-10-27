# Concall PDF refetch — FY25+ BSE transcripts — 2026-10-27T10:41:37+00:00

- window: BSE dissemination date >= 2024-04-01 (ann.SUBCATNAME = 'Earnings Call Transcript'), known_at = DissemDT, never a crawl date
- candidates: 9390 announcements, 11 fiscal quarters x A-P/Q-Z
- rate enforced: one request at a time, >= 2.5 s apart (<= 24.0 requests/min), back-off on 403/429/503

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

- sampled 200, ok 200, failed 0, reused 12, skipped 0
- wall clock 10.4 min, 188 HTTP requests, 19.19 PDFs/min end-to-end
- classes: {'cover_letter': 12, 'audio_link': 2, 'transcript': 182, 'intimation': 2, 'other': 2}
- transcript share on fetched docs: 91.0%; duplicates: 0 (0.0% of transcripts)

| source | tried | reused | ok | failed | reasons |
|---|---|---|---|---|---|
| bse | 188 | 0 | 188 | 0 | - |
| probe | 12 | 12 | 12 | 0 | - |

| cell | tried | ok | failed | unique transcripts |
|---|---|---|---|---|
| FY25Q1-A-P | 13 | 13 | 0 | 10 |
| FY25Q1-Q-Z | 5 | 5 | 0 | 3 |
| FY25Q2-A-P | 12 | 12 | 0 | 10 |
| FY25Q2-Q-Z | 5 | 5 | 0 | 5 |
| FY25Q3-A-P | 13 | 13 | 0 | 11 |
| FY25Q3-Q-Z | 6 | 6 | 0 | 6 |
| FY25Q4-A-P | 12 | 12 | 0 | 12 |
| FY25Q4-Q-Z | 5 | 5 | 0 | 5 |
| FY26Q1-A-P | 14 | 14 | 0 | 14 |
| FY26Q1-Q-Z | 6 | 6 | 0 | 6 |
| FY26Q2-A-P | 13 | 13 | 0 | 13 |
| FY26Q2-Q-Z | 5 | 5 | 0 | 5 |
| FY26Q3-A-P | 15 | 15 | 0 | 15 |
| FY26Q3-Q-Z | 7 | 7 | 0 | 6 |
| FY26Q4-A-P | 15 | 15 | 0 | 13 |
| FY26Q4-Q-Z | 6 | 6 | 0 | 6 |
| FY27Q1-A-P | 17 | 17 | 0 | 13 |
| FY27Q1-Q-Z | 7 | 7 | 0 | 7 |
| FY27Q2-A-P | 16 | 16 | 0 | 15 |
| FY27Q2-Q-Z | 6 | 6 | 0 | 5 |
| FY27Q3-A-P | 1 | 1 | 0 | 1 |
| FY27Q3-Q-Z | 1 | 1 | 0 | 1 |

- pages: n=200 min=1.0 median=18.0 mean=17.02 p90=23.0 max=42.0
- text chars: n=200 min=854.0 median=47376.0 mean=45446.405 p90=64351.0 max=144650.0
- image-only page share: n=200 min=0.0 median=0.0 mean=0.0052 p90=0.0 max=0.9333
- uppercase letter share: n=200 min=0.0288 median=0.0545 mean=0.0637 p90=0.0748 max=0.2525
- same-document shingle match: n=160 min=0.0 median=1.0 mean=0.9281 p90=1.0 max=1.0
- same-document match rate (>= 0.5 shingles): 98.1%
- lowercased sources (uppercase < 0.5%): 0
- recorded sha256 matched the fetched bytes: 198 of 198 rows carrying one (the other 2 had no
  recorded sha because they are absent from corporate_documents; see §9)

## 7. Projection for the full FY25+ window (unique real transcripts)

| metric | value |
|---|---|
| candidates | 9390 |
| already on disk (reuse, no fetch) | 560 |
| fetches still needed | 8830 |
| measured transcript share | 91.0% |
| measured duplicate share | 0.0% |
| estimated unique real transcripts | 8545 |
| already held unique transcripts | 496 |
| unique transcripts still to fetch | 8049 |
| fetch wall time at 24.0 req/min | 6.1 h (368 min) |
| requests incl. retries (success 100%) | 8830 |

## 8. Samples

### DWARKESH FY25Q1 — cover_letter (2024-05-02T17:17:37.917)

- source=bse reused=False bytes=294774 sha256 `e1a0c3d83290746e…` pages=1 chars=1352 upper=0.2108667529107374
- headline: Earning Call Transcript

```
REF: DSIL/2024-25/047 May 02, 2024 Corporate Relationship Department BSE Limited Phiroze Jeejeebhoy Towers Dalal Street, Fort, Mumbai - 400 001 Fax: 22723 2082 /3132 National Stock Exchange of India Limited “Exchange Plaza” Bandra – Kurla Complex, Bandra [E], Mumbai - 400 051 Scrip Code - 532610 Scr
```

### GREENPANEL FY25Q1 — audio_link (2024-05-03T15:16:00.317)

- source=bse reused=False bytes=911826 sha256 `f162155c51dc8def…` pages=1 chars=1229 upper=0.1487603305785124
- headline: Audio Recording of Concall held on 2nd May 2024

```
GPIL/2024-2025 May 03, 2024 BSE Limited Phiroze Jeejeebhoy Towers Dalal Street Mumbai – 400001 Scrip Code: 542857 NaƟonal Stock Exchange of India Limited Exchange Plaza, 5th Floor, Plot no. C/1, G Block Bandra – Kurla Complex , Bandra (E), Mumbai – 400051 Symbol: GREENPANEL Dear Sirs, Sub: Audio rec
```

### CENTRALBK FY25Q1 — transcript (2024-05-08T15:12:50.65)

- source=bse reused=False bytes=1010396 sha256 `a6376a48533ceaf2…` pages=15 chars=37675 upper=0.06952374069523741
- headline: Disclosure under Regulation 30 and Regulation 46(2)(oa) of SEBI (LODR) Regulations, 2015 Transcript of Bank''s Conference/Earnings call with the Analysts/Investors.

```
INVESTORS RELATION DIVISION Central Office केंद्रीय कायाालय: चंदर मुखी, नरीमन पॉइंट, मुंबई - 400 021 दूरभाष/Tel.: 022-6638 7575 Central Office: Chander Mukhi, Nariman Point, Mumbai - 400 021 ईमेल/Email ID: smird@centralbank.co.in Follow us on Central Bank of India www.centralbankofindia.co.in CO:IRD
```

### ARVIND FY25Q1 — cover_letter (2024-05-10T17:04:23.04)

- source=bse reused=False bytes=657832 sha256 `28e21a19a008feb0…` pages=1 chars=1097 upper=0.17693315858453473
- headline: Concall Transcripts

```
10th May, 2024 BSE Limited Listing Dept./ Dept. of Corporate Services Phiroze Jeejeebhoy Towers Dalal Street Mumbai - 400001 Security Code : 500101 Security ID : ARVIND National Stock Exchange of India Limited Listing Dept., Exchange Plaza, 5th Floor Plot No. C/1, G. Block Bandra-Kurla Complex Bandr
```

### KANSAINER FY25Q1 — transcript (2024-05-13T16:54:47.13)

- source=probe reused=True bytes=2594192 sha256 `45f49df62f136db5…` pages=26 chars=94170 upper=0.04447659164078344
- headline: We are enclosing herewith the transcript of the Investors Meet held on 7th May, 2024, for your information and reference.

```
13th May, 2024 1. Corporate Relationship Department BSE Limited, PhirozeJeejeebhoy Towers, Dalal Street, Mumbai - 400001. 2. Manager – Listing National Stock Exchange of India Ltd. Exchange Plaza, C-1, Block G, BandraKurla Complex, Bandra (E), Mumbai - 400051. Sub.: Q4 & FY 2023-24 Financial Results
```

## 9. Supplementary checks (computed from the manifest after the run)

- **Rate per source**: BSE 188 PDFs in 10.35 min = **18.2 PDFs/min** (188 requests, 0 retries,
  0 non-200 responses); probe reuse 12/12 instant, no network. The 2.5 s pacer is the floor, but
  each download + PyMuPDF validation takes ~0.8 s on top, so the loop settles at ~18/min rather
  than the 24/min pacing ceiling.
- **recorded sha256**: **198/198** rows that carried a sha from the old crawl got byte-identical
  files from BSE today. The two `no` values in section 6 are the two sampled rows that have no
  recorded sha because they are absent from `corporate_documents` (CANFINHOME, UCOBANK); a
  reporting bug counted those as `no` and was fixed after the run (`sha_match_status`).
- **duplicates**: the pilot saw **0/182 transcripts** duplicate. That is not evidence of a 0%
  rate: a pair is only visible when both of its rows land in a 200-row sample (~0.2 expected
  pairs). Metadata-only measures for the whole set:
  - exact byte duplicates: 30 rows (0.32%);
  - same (isin, dissemination quarter): 427 rows (4.5%), but 94 of their headlines are audio-link /
    intimation and some groups are genuinely different events in one quarter (HATSUN filed three
    different interviews; ANANDRATHI filed an audio link + the transcript). This is an upper bound
    on transcript duplication;
  - the 560 already-classified probe PDFs contain **0 duplicate transcripts among 496**.
  Plan on a 0.3–4.5% dedupe band.
- **projection at the measured throughput**: 8,830 fetches at 18.2/min = **8.1 h**; at the 24/min
  pacing floor 6.1 h. Unique real transcripts: **8,545** at 0% dedupe, **8,160** at the 4.5%
  upper bound; 496 are already held, so **7,664–8,049 still to fetch**.
- **recommendation**: one worker, 2.5 s pacer, no parallelism, run in a single ~20:00–06:00 IST
  window (8–9 h is enough). Stop and resume after 30–60 s on 403/429/503; never rotate IPs. Keep
  classifying after download: ~9% of the `Earnings Call Transcript` rows are cover letters,
  audio-link letters or intimations, and their headlines look exactly like transcripts, so
  pre-filtering by headline is not worth the risk of dropping a real transcript.

