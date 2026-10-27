# Task — raw originals inventory: do we hold the original file for every document we need?

## Goal
The v3 re-chunk must start from original documents, because 67–100% of today's chunks are lowercased (concalls
80%, ARs 67%, PIB 99%, budgets 100%). Concall PDFs turned out to be missing entirely. For **every other document
type**, find out what fraction of the documents we need has a readable original on this laptop, on D, or on Google
Drive, and what must be re-fetched. Read-only census; no fetching.

## Document types
- Annual reports;
- investor decks;
- quarterly results PDFs (for the notes);
- material announcements and order wins;
- PIB releases;
- Union and state budgets;
- RBI policy documents;
- Economic Survey;
- offer documents.

Concalls are being handled by another worker. Skip them except to report their Drive count.

## Where to look
- Registries, read-only via `reality_engine.db.readonly.connect_ro`; bounded queries only:
  - `equity_intelligence.db`: `raw_documents` (source_type, local_file_path, sha256_hash, source_url) and
    `corporate_documents` (doc_type, local_file_path, sha256_hash, source_url);
  - `deck_figures.db:deck_sources`;
  - `bse_announcements.db`;
  - `results_xbrl.db`.
- Disks:
  - `D:\RealityEngine\pdfs` (5,364 AR PDFs, moved 2026-10-25; record in `D:\RealityEngine\raw\_migration\2026-10-25.json`);
  - `D:\RealityEngine\raw\*` (decks_full 116 GB, ar_queue, deck_page_text, …);
  - `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\` (anything raw left there).
- Google Drive, read-only listing only:
  - `rclone lsf -R --files-only gdrive_ro:InfoDiffusion_archive` (and the `decks` folder used by `toolbelt.drive_fetch`);
  - rclone is at `C:\Users\warri\AppData\Local\Microsoft\WinGet\Links\rclone.exe`.
- Match registry rows to files by sha256 where recorded, else by path or filename; hash files only when needed to
  confirm a match.

## For each document type, report
| field | meaning |
|---|---|
| needed | rows in the registry (2019+ where the type is company-specific), excluding test/demo/quarantined rows |
| original on laptop / D / Drive | counts (a file counts once even when it is in several places) |
| text-only | we hold extracted text but no original (and whether that text is lowercased: sample 200) |
| missing | no original anywhere; how many have a `source_url` for re-fetch |
| non-documents | rows that are not the document type (cover letters, intimations, duplicates), estimated from a 200-row sample |
| est. re-fetch | volume and time at the measured BSE rate (~15 PDFs/min) |

Also list any raw folder on D or Drive that no registry points to (orphans worth registering).

## Rules
- Read-only everywhere.
- Network: only the `rclone lsf` listing above. No downloads, no paid APIs.
- Write only in your worktree (`.tmp/` and the report). Do not commit.

## Acceptance checks
1. The table filled for all 9 types, each number traced to a query or listing.
2. 200-row samples for casing and non-documents, per type where text exists.
3. An orphan list.
4. A prioritised re-fetch list matching Shivam's priority order (decks/concalls → announcements → ARs →
   PIB/budgets → RBI).

## Test command(s)
```bash
python -c "print('census only')"
```

## Report
The table, samples, orphans, re-fetch list, and the queries and listings you ran.
