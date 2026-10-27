# Task — concall PDF re-fetch pilot (200 docs, full access, data job)

## Goal
The original concall PDFs are gone: 0 of 21,778 `corporate_documents` concall rows have a file on disk. Drive
`InfoDiffusion_archive/pdfs/<SYMBOL>/CONCALL_TRANSCRIPT/` holds only 2,289 (A–P, partial). Before fetching all of
them, run a 200-doc pilot that measures rate, success, file validity and text casing.

## How
1. Sample 200 concall rows from `corporate_documents` (doc_type 'CONCALL_TRANSCRIPT'), read-only via `connect_ro`.
   - Stratify by year 2019–2026 and by symbol initial: A–P (on Drive) vs Q–Z (not on Drive).
   - Include 40 of the 6,086 that were never chunked.
2. For each row, try the source in this order:
   - (a) Drive copy via `reality_engine.toolbelt.drive_fetch` (folder `InfoDiffusion_archive/pdfs`) when present;
   - (b) `source_url` (BSE/NSE), politely: one request at a time, ≥2 s apart, the project's normal headers from
     `reality_engine/config.py`, and a back-off on 403/429.
3. Write each PDF to `D:\RealityEngine\raw\concall_pdfs\<sha[:2]>\<sha256>.pdf` (content-addressed).
   - Keep a manifest at `D:\RealityEngine\raw\concall_pdfs\_manifest.jsonl` with: corporate_documents.id, isin,
     symbol, source used, url, http status, bytes, sha256, recorded sha256 match (yes/no), fetched_at.
4. Validate each file:
   - PyMuPDF opens it; page count;
   - text chars;
   - share of pages with < 200 chars (image-only);
   - **casing**: share of letters that are uppercase. Expect ~3–8% in a normal transcript; ~0% means the source is
     lowercased.
5. Compare each against our existing chunks for that doc (first 500 chars, case-folded) to confirm it is the
   same transcript.

## Write scope (full access — this is the fence)
- Network: Google Drive via `drive_fetch`, and the BSE/NSE URLs in `corporate_documents.source_url`. Nothing else.
- Writes: `D:\RealityEngine\raw\concall_pdfs\` and this worktree only. No DB writes at all (manifest only). No
  `.git/config`, no `plugins/dsh-worker/`, no `~/.dsh`.
- No paid APIs. Do not commit.
- Stop at 200 docs.

## Acceptance checks
1. Table: tried / ok / failed by source and by reason (404, 403, not a PDF, sha mismatch), and by year and A–P vs Q–Z.
2. Rate: PDFs/min per source; projected wall time for all 21,778 at the measured rate.
3. Validity: page and char stats, image-only share, casing distribution, same-doc match rate.
4. 5 sample rows printed with the first 300 chars of text.
5. Tests for any new fetch code.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_concall_refetch
```

## Report
Tables above, failures with examples, recommendation for the full run (rate limits, night window, parallelism),
tool calls.
