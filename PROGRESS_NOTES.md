# PROGRESS_NOTES (T-062, guidance wrong rows)

- 2026-11-04: read `guidance.py` rules; copied `combined3.db` -> `w_guid2.db` by sqlite3 backup; baseline 95 rows
  (BAJFINANCE 6, ETERNAL 12, HDFCBANK 2, HINDALCO 31, HINDUNILVR 3, INFY 16, KEC 14, MARUTI 1, SBILIFE 5, SUNPHARMA 5).
- Done: growth-sentence rule (whole-sentence growth verb when the metric word is not in the sentence), IRP/APE as an
  insurer's top line, present-perfect movement as past, delta/reduction and margin-accretion as changes not levels,
  "out of <total>" slice rule, "in the Qn level" and "next quarter" periods, `other` needs a target wording or a
  single number (a labelled percentage list is a mix), worded direction read from its own words, non_par/protection
  dimensions, `reach 9%, 10%` pair. Rebuilt `w_guid2.db`: 90 rows. checkpages 145/314 held, A1 709/898 held (every
  company level), 28 tests pass. Docs updated (blueprint guidance bullets, guide O6 + test counts, STATE.md).
- Next: none for the ticket; hand read (seed 20261112) is all right. Blockers: none.
