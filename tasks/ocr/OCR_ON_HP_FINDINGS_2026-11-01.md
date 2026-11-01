# OCR on the HP laptop: findings, 1 Nov 2026

**Microsoft `TextRecognizer` at 300 DPI grayscale found 96.65% of numbers and read 97.16% correctly on held-out digital table pages.** The bar is 95% and 98%, so correct fails, and no setting closes the gap. All tables and page-level detail are in `tasks/ocr/OCR_ON_HP_FINDINGS_2026-11-01.xlsx`.

## How the larger test worked
- Sample: 1,000 digital table pages, 300 prose pages and 150 scanned results filings (1,087 pages) from 63 companies, seed 20261101. Digital pages exclude images over 10% of the page.
- Settings were tuned on 15 companies and frozen. Claude scored the other 48 on the MSI. Their answer keys never reached the HP.
- Scores: `score_large.py`, unchanged after the job began. Letters and Roman numerals are scored apart from numbers.
- Job `hp-20261101T140451-175638`; branch `dsh-hp/hp-20261101T140451-175638`, not merged. Worker's full report, including how to rebuild the signed package: `tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md` on that branch.

## Held-out result
| Pages | Found | Correct |
|---|---:|---:|
| All table pages, 759 | 96.65% | 97.16% |
| Annual reports | 98.57% | 98.29% |
| Presentations | 97.14% | 98.60% |
| Quarterly results | 94.14% | 94.93% |
| 200 DPI baseline, all table pages | 95.69% | 97.20% |

Company-level 95% range: 95.3 to 97.9% found, 96.5 to 97.8% correct. Words 98.5% and 97.7%; Roman numerals 94.1% and 97.8%. Speed 122.9 pages a minute.

## What we learned
1. **Settings barely move accuracy.** There is no alphabet or language setting. 300 DPI and grayscale help slightly, other clean-up does not, SDK 2.0 options do nothing here, and `ImageScaler` is blocked.
2. **Errors are concentrated.** The worst 5% of pages hold 56% of number errors, mostly huge tables in tiny print. Rotated pages score 80.17% and 90.56%; upright pages 97.39% and 97.42%.
3. **Confidence is useful.** Using only numbers with confidence of 0.9 or above gives 98.03% correct, with 1,154 unique numbers to check. This cutoff was picked after seeing held-out scores, so it needs fresh pages.
4. **It beats hidden text layers on scans.** 76.2% against 65.3% of XBRL facts on 58 filings. This comparison is relative, since digital filings match 49.8% on the same measure. Correctness on scans is not measured.
5. **Hidden text layers can be wrong**, as the Tata Elxsi page shows (`0055.19` for `10,056.19`). One digital page's text layer is also garbled by its font encoding (`D00349`). The size of this problem in our stores is not measured.
6. **Simple check flags failed.** Letters inside numbers: 3 true errors, 28 false alarms. Column totals: 0 true errors, 15 false alarms.

## Files
`tasks/ocr/large_test/`: `sample.py`, `xbrl_truth.py`, `xbrl_ceiling.py`, `score_large.py`, `heldout_scores.json`. Sample, keys and rows: `D:\RealityEngine\ocr_large_20261101`. HP copy: `C:\RE\ocr_large`.

## Next
On a fresh page sample: tile rotated and tiny-print pages, and send low-confidence numbers to a checker. Paid readers need Shivam's OK. All HP runs must be headless: `machines/HP_LAPTOP.md`.
