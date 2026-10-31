# Local Haiku session: hard annual-report pages

Written 2026-10-16 ~00:05 by the co-pilot session (context 75% full). Shivam wants spare weekly Pro quota spent on
Claude Haiku helper agents re-reading the HARD annual-report material. A separate session is finishing the deck
batches (`tasks/LOCAL_HAIKU_SESSION.md`), so do not touch `reality_engine/data/claude_queue/cloud_hard_*`.

## Usage rules

- Before every wave, check plan usage (`get_usage`; ToolSearch "select:mcp__ccd_session_mgmt__get_usage").
  - Stop above ~85% of the 5-hour window.
  - Two Haiku sessions share the same plan.
- One agent per small unit (<= ~10 pieces of <= 18k characters); waves of 10 agents in parallel, foreground.
- Keep your own context small: agents write files and reply with one line.

## 1. Find the hard reports (read-only first)

`reality_engine/data/ar_facts.db`:

- **Reports with many unverified numbers:**

  ```sql
  SELECT doc_id, symbol, fiscal_year, SUM(value_check='not_found') nf, COUNT(*) n FROM ar_facts
  WHERE value IS NOT NULL GROUP BY doc_id HAVING n >= 50 AND 1.0*nf/n > 0.10 ORDER BY 1.0*nf/n DESC
  ```

  ~141 reports / ~17.5k facts on 10-15. Coptic-digit fonts are already handled by `value_check` (FONT_DIGITS) and
  17 such reports were re-checked.
- **Pieces that failed for good:** `ar_pieces.status='error'` after all tries.
- **Reports with pieces too large for Google:** released to the main run; the log line is "released to the main run".
- **The one truly unreadable PDF:** SDC (text split times out).

Sample 3-5 reports and classify why their numbers fail the check:

- garbled text layer (another font encoding);
- scanned pages (no text layer);
- tables split across lines;
- genuine misreads by a weak reader (see `ar_facts.model`).

The cause decides the fix:

- An encoding the checker can learn: fix `value_check`. No quota needed.
- Text is fine but the reader was weak: Haiku re-reads the TEXT pieces.
- No usable text: Haiku reads page IMAGES, like the deck pipeline.

## 2. Build the re-read path (no code exists yet)

`reality_engine/scripts/ar_queue.py` has `export` / `import` / `drive` for external readers, but `export` only takes
reports nobody has started. Add a mode, e.g. `export-docs --doc-ids ... --run R`, that:

- writes each piece prompt (`ingest_annual_reports.prompt_for('exhaustive')` template, PIECE_CHARS 18000) as
  `NNNN.prompt.txt` in `reality_engine/data/ar_queue/<run>/`, grouped into folders of ~10 pieces, plus `manifest.json`
  (doc_id, piece, page range, prompt version);
- imports answers as model `claude-haiku-5-5`. **Replace** the report's earlier facts only when Haiku's answer
  verifies better (lower not_found share). Keep the old facts otherwise. Never delete without a better replacement.

Validate on ONE report first, comparing facts and not_found before and after. Then scale.

- For image-only pages: render pages with PyMuPDF (as `claude_page_queue.py` does for decks) and reuse the deck agent
  instructions adapted to annual reports.

## 3. Report to Shivam

- What the hard reports were, by cause.
- What was fixed for free (checker rules) vs re-read by Haiku.
- Quota used and facts gained or verified.
- Update `tasks/STATE.md` and append results to `tasks/ar_study/READER_FINDINGS.md`.

## Do not

- Do not restart the annual-report workers unnecessarily. Killing only the parent orphans `--pieces-json` children;
  the watchdog cleans those up.
- Do not use paid API models.
- Do not mark facts verified without checking them against the page text.
