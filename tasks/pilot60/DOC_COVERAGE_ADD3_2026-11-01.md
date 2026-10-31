# ADD3 raw-document coverage (2026-11-01)

The three names Shivam added to the pilot on 1 Nov, fetched the way the 60 were
fetched and checked against what the stores already hold.

| symbol | ISIN | BSE code |
|---|---|---|
| APOLLOHOSP | INE437A01024 | 508869 |
| KIMS | INE967H01025 | 543308 |
| OLAELEC | INE0LXG01040 | 544225 |

- Universe: `tasks/pilot60/UNIVERSE_ADD3.csv` (new). `tasks/pilot60/UNIVERSE.csv` is untouched.
- Fetcher: `reality_engine/scripts/fetch_pilot60_history.py` — it gained `--universe`
  (default unchanged) and `--window-start/--window-end` (default still
  2019-01-01..2024-04-01) so the same raw pipeline can cover FY2024-25 onward.
- Raw files: `D:\RealityEngine\raw\pilot60_history\<SYMBOL>\<bucket>\<newsid>.pdf`
- Manifest (shared with the 60): `reality_engine/data/pilot/pilot60_history_manifest.db`
- Per-FY matrices: `DOC_COVERAGE_ADD3_HISTORY_2026-11-01.md` (2019-01-01..2024-03-31)
  and `DOC_COVERAGE_ADD3_FY25PLUS_2026-11-01.md` (2024-04-01..2026-10-31).

## Commands

```bash
python -m reality_engine.scripts.fetch_pilot60_history --measure \
    --universe tasks/pilot60/UNIVERSE_ADD3.csv
python -m reality_engine.scripts.fetch_pilot60_history --fetch \
    --universe tasks/pilot60/UNIVERSE_ADD3.csv \
    --window-start 2019-01-01 --window-end 2024-04-01
python -m reality_engine.scripts.fetch_pilot60_history --fetch \
    --universe tasks/pilot60/UNIVERSE_ADD3.csv \
    --window-start 2024-04-01 --window-end 2026-11-01
python -m reality_engine.scripts.fetch_pilot60_history --coverage \
    --universe tasks/pilot60/UNIVERSE_ADD3.csv \
    --window-start 2024-04-01 --window-end 2026-11-01 \
    --out tasks/pilot60/DOC_COVERAGE_ADD3_FY25PLUS_2026-11-01.md
```

## What the run did

| window | PDFs held | text-only (no attachment) | fetch errors | routine skips |
|---|---:|---:|---:|---:|
| 2019-01-01..2024-03-31 | 631 | 33 | 0 | 348 |
| 2024-04-01..2026-10-31 | 639 | 8 | 0 | 83 |
| **total** | **1,270** | **41** | **0** | **431** |

Per symbol: APOLLOHOSP 557 held / 26 text-only / 311 skipped; KIMS 401 / 8 / 85;
OLAELEC 312 / 7 / 35. The manifest's only fetch error is a HINDPETRO 404, outside
this task. "Text-only" means BSE lists the announcement but publishes no attachment,
so there is nothing to download; the newsid stays in the manifest with status `no_file`.

## Counts by type and year — held/listed

**History window (FY19..FY24).** FY = the year the fiscal year ends (March).

| bucket | APOLLOHOSP | KIMS | OLAELEC |
|---|---|---|---|
| annual_report | 6/6 | 3/3 | 0/0 |
| investor_presentation | 13/13 | 13/13 | 0/0 |
| concall_transcript | 3/3 | 10/10 | 0/0 |
| concall_audio_link | 0/0 | 11/11 | 0/0 |
| quarterly_results | 33/33 | 25/25 | 0/0 |
| results_press_release | 0/0 | 10/10 | 0/0 |
| material_filing | 353/368 | 151/159 | 0/0 |

**FY2024-25 onward (FY25..FY27).**

| bucket | APOLLOHOSP | KIMS | OLAELEC |
|---|---|---|---|
| annual_report | 3/3 | 4/4 | 3/3 |
| investor_presentation | 8/8 | 8/8 | 5/5 |
| concall_transcript | 0/0 | 6/6 | 5/5 |
| concall_audio_link | 0/0 | 6/6 | 6/6 |
| quarterly_results | 4/4 | 8/8 | 10/10 |
| results_press_release | 0/0 | 7/7 | 0/0 |
| material_filing | 134/135 | 139/139 | 283/290 |

The 41 text-only rows are all `material_filing` and are the whole of the shortfall:
APOLLOHOSP FY19 1, FY20 8, FY21 6, FY22 9, FY23 1, FY26 1; KIMS FY22 5, FY23 3;
OLAELEC FY25 1, FY26 5, FY27 1. Every annual report, presentation, transcript and
quarterly-results file that BSE lists for the three is held.

## FY2024-25+ held in the other stores (not re-downloaded)

`fetch_rows()` hard-links a file already held by `corporate_documents` / `deck_sources`
(for the same BSE newsid) instead of fetching it again; none of these rows needed that.

| store | APOLLOHOSP | KIMS | OLAELEC |
|---|---:|---:|---:|
| `results_xbrl.filings`, FY25 / FY26 / FY27 to 2026-06-30 | 2 / 8 / 2 | 3 / 12 / 2 | 8 / 8 / 4 |
| `corporate_documents` annual reports (all years, all with local file) | 17 | 6 | 3 |
| `corporate_documents` concall transcripts (rows / with file) | 4 / 4 | 22 / 21 | 9 / 9 |
| `deck_figures.deck_sources` decks | 25 | 26 | 7 |
| `concall_facts.cc_docs` processed transcripts | 2 | 7 | 2 |

Open points, stated rather than papered over:

- **APOLLOHOSP transcripts after FY24:** the BSE feed lists none under
  `Earnings Call Transcript` after FY24, so the matrix shows 0/0. `corporate_documents`
  does hold 4 (2022-05-27..2026-08-28) from the other discovery path, all with files.
  Nothing is missing; the two sources simply classify the filings differently.
- **NSE:** not used as a fallback. All three have BSE scrip codes and the BSE feed lists
  their filings; NSE results XBRL is already held in `results_xbrl.db`. The
  `--nse-fallback` path stays for NSE-only names.
- The 60-name matrix `HISTORY_COVERAGE_2026-10-30.md` predates these rows: its per-name
  cells are unchanged, but its manifest-wide status totals no longer describe the whole
  manifest. Use the two ADD3 matrices above for the 63-name manifest.

## Verification

- `python -m unittest reality_engine.tests.test_pilot60_history` — 15 tests, OK
  (adds one test that a custom universe CSV is read).
- Every PDF written by the fetcher is `%PDF`-checked (`download()` rejects HTML/ZIP);
  `scan_pass()` filled `is_scanned_guess` for the new files.
- Per-symbol held counts sum to the manifest `ok` rows exactly (557 + 401 + 312 = 1,270),
  and the held/listed cells reproduce the 41 text-only rows with no residue.
