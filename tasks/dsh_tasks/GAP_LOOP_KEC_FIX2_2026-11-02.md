# Gap loop fixes, round 2: a prepared store instead of raw MCP output (T-048)

Ticket: T-048

Goal: The first real run of `reality_engine/gap_loop/` failed in 3 minutes. Ledger, `D:\RealityEngine\sandbox\kec_loop\state\ledger.jsonl`:
- `answer-01` (10 questions), then halved to 5, then 2: all three Haiku attempts `over context limit` at 95k. The 2-question session made only 4 `mcp__reality-data__facts` calls and 3 Bash calls: one `facts` reply (default limit 80 rows, full provenance) is tens of thousands of tokens. Raw MCP replies cannot fit a 100k session.
- Tier 2: `start refused: repo_root_write_requires_confirmation`.
- `cost_usd` is 0 on every row although tokens were used.

Fix it so the model reads small, prepared data and code does the bulk work (Shivam wants the method, not brute-force reading, and the ledger must show which):

1. **Prepare stage, code only, no model, before round 1** (idempotent; skip what is done):
   - Text of every PDF under the sandbox `raw\` with `fitz`, page by page, into `kec.db doc_text` (`method='script_text'`); a page with under 50 characters of text is recorded `method='needs_ocr'` with empty text (OCR is a fix-stage job). An FTS5 index over `doc_text` for search.
   - A `docs` table: `doc_key` (path under raw), doc type, title, filing date and `known_at`. Map BSE attachment-id file names to their announcement through the read-only `bse_announcements` / `corporate_documents` stores (attachment name = file name); transcripts from KEC's site through `raw\company_site_transcripts\_manifest.json`. A file you cannot date gets `known_at` NULL and is excluded from answers with an as-of date.
   - Copy KEC's rows from the read-only stores into `kec.db`, each with its source table and key: facts from `ar_facts`, `deck_figures`, `results_xbrl`, `concall_facts`; daily prices and delivery (NSE and BSE); shareholding; announcements list. Use the same read-only connections the reality-data server uses (`plugins/reality-data/server/`).
   - Log what it did: files, pages by method, rows per table, seconds. Put these counts in the ledger as a `prepare` unit with `tier=0`.
2. **Answer and fix sessions read `kec.db` only**, through small SQL with `LIMIT` and FTS queries run by Python/Bash; remove the `reality-data` MCP from tier-1 sessions. A number cites either a `doc_text` page (checked as now) or a `kec.db` table row (`table`, `rowid`): the check reads that row and needs the value in it, and the quote too when given. Remove the MCP re-run path from the checks only if nothing else needs it.
3. **Answer units of 5 questions**, not 10.
4. **Tier 2 start** passes `confirm_repo_root_write=True` along with the existing approval.
5. **Cost**: `cost_usd` must come from the session's `result` event `total_cost_usd`; when the session is killed before a result event, estimate from the token counts at Haiku 5.5 list price (look it up in the claude-api reference in the repo or the CLI output; say which) and mark the row `cost_estimated`.

Files: `reality_engine/gap_loop/`, `reality_engine/scripts/session_runner.py` if the cost fix belongs there, `reality_engine/tests/test_gap_loop.py`, `docs/DEVELOPER_GUIDE.md` section N.

Accept: `python -m pytest reality_engine/tests/test_gap_loop.py reality_engine/tests/test_doc_review_loop.py -q` passes with no model call, with new tests: prepare on a tiny sandbox (two small PDFs made in the test, one page with no text) fills `doc_text`, flags `needs_ocr`, builds `docs`; a number citing a `kec.db` row passes when the value is in it and fails when not; tier-2 start carries `confirm_repo_root_write`; a killed session gets an estimated cost. Then run the prepare stage for real: `python -m reality_engine.gap_loop --sandbox D:\RealityEngine\sandbox\kec_loop --prepare-only` (writes only inside the sandbox; delete the old `kec.db`, `state\ledger.jsonl` and `escalations.jsonl` there first, they hold the failed run) and report its counts. Do not start a model run.

Stop if: a store cannot be read for KEC (name it); the mapping of attachment ids to dates leaves more than a third of the history PDFs undated (report the count and stop before answering).

Budget: 2 hours, about 120 tool calls.

Docs updated: required in your report.
