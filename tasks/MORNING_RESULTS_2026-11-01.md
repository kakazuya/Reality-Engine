# Results from the night of 1 Nov 2026 (Wolf, written 05:10 IST)

## Prototype on Bajaj Finance, Hindalco, KEC
Cost is fine, quality is not. No wider run. Full grade: `tasks/pilot60/PROTOTYPE3_CLAUDE_GRADE_2026-11-01.md`.
- Reader about $1.16 at Go rates; forecast $13 to $26 for 60 names, before fixes.
- 0 of 40 sampled answers right; 78% of numbers missed in the recall check; false rows passed the worker's accuracy check (Bajaj NIM of 90%).

## OCR on one frozen page set
Rows: `D:\RealityEngine\ocr_test_20261101`; scorer `score_haiku.py` there. Bar: 95% found, 98% correct.

| 100 table pages | Digital pages (66), reliable truth | Image-backed (34), truth unreliable |
|---|---|---|
| Haiku 5.5 | 98.9% found, 97.7% correct | 84.4%, 88.8% |
| Windows AI `TextRecognizer` | 97.4%, 96.0% | 83.6%, 87.4% |
| Windows OCR | 90.6%, 92.4% | 80.9%, 83.8% |

On 150 pages Windows AI found 93.8% with 92.4% correct on table pages. RapidOCR on the MSI used a different sample: 91.6% and 91.0%. No engine or pair clears the bar as scored.

**Main finding:** 34 of 100 table pages (29 of 45 results pages) are scanned images carrying a hidden OCR text layer, and that layer can be wrong. Tata Elxsi results page: the layer gives `0055.19` and `Mar 3L,2019` where the page prints `10,056.19` and `Mar 31, 2019`. Consequences, not yet measured at scale:
1. Those pages were used as truth, so every engine's score on them is unreliable. They need hand truth.
2. Any store built from such text layers can hold wrong numbers.
3. "4,647 pages need OCR" is too low, because it treats these layers as real text.

Windows AI on 10 truly scanned pages: 98.9% of hand-read key numbers. 161 pages/min, so 4,647 pages in about 0.5 h. It needs a signed package, removed after the test; its source is outside the repo at `C:\RE\bench\textrec\` on the HP.

Haiku used 995,856 subagent tokens, about 10,000 per page, as reported per agent. 4 of 10 batches passed 100k (100,788 to 105,780): Claude's sizing error. Free vision models not tested.

## Efficiency, latest count
Cached tokens per step -34%, control call -29%, shell share -18%, LSP use up. Claude edit share, batchable steps, calls before first edit, read share and test failure rate all worse. Sleep in loops is near zero. Final verdict is due; `tasks/efficiency/FIX_TRACKER_2026-10-31.md` has the interim.

## Not merged, nothing pushed
Unreviewed branches or worktrees: raw fetch `dsh/20261031T200654Z-2d667ad0`, RapidOCR `dsh/20261031T222045Z-a1c65afb`, prototype worktree `20261031T215040Z-4ef5184a` (uncommitted), HP patches `dsh-hp/hp-20261101T035009-ab1d74` (docs), `dsh-hp/hp-20261101T034935-31ca45` (formulas), `dsh-hp/hp-20261101T040329-6fce13` (OCR), older grader job. Claude's edits on `main` are uncommitted too. NSDL 15 Oct file is already loaded in the live database.
