# Progress — sector label accuracy pilot

- 2026-10-28: context pack read; schema probes done (company_industry 2,055 rows/28 sectors; master_companies 6,940;
  ar_facts 32.4M facts; BSE header endpoint reachable).
- 2026-10-28: fixed-seed sample drawn and written before evidence read: 150 NSE-labelled (28 sectors, 57 multi-segment) +
  50 unlabelled, small/micro only; 6 thin-evidence draws replaced (replacements.csv).
- 2026-10-28: BSE headers fetched for 206 sample codes (200 initial + 6 replacements), 206 OK / 0 failed, raw JSON in
  .tmp/bse_header/; one availability probe outside the sample.
- 2026-10-28: evidence bundle built for all 200 (AR segment revenue, AR business text, quotes, deck facts); grading done
  with a business-family taxonomy + acceptance sets + 2 documented manual adjudications.
- 2026-10-28: sector_label_pilot.csv (200 rows, unique ISINs, evidence refs on every row) and REPORT.md written;
  cannot_tell 11/200 = 5.5%.
- Next: controller review; then decide the BSE-fill policy per REPORT.md §6.
- Blockers: none.
