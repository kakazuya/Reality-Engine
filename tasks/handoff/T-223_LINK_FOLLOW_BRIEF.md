permission: write code in this worktree only; no network; no writes outside the worktree; no live store writes.
Ticket T-223 (store-repair notes R-012, R-014). Python 3.14, repo root = worktree root. Tests run with run_check (pytest). Commit when done.

GOAL
Write `reality_engine/pilot3/link_follow.py` (new) that turns a store's `filing` rows into fetch targets for
documents the store lacks, and two small fixes in `reality_engine/pilot3/filings.py`. All network calls go
through injectable functions so tests use fakes. Claude (the reviewer) will run it live; you never touch the network.

READ FIRST (only these):
- reality_engine/pilot3/linked_transcripts.py (whole file: reuse urls_from_text, urls_from_links, pdf_info,
  download_pdf, quarter_tag, TRANSCRIPT_TEXT, _sha256; do NOT change its public behaviour or its tests)
- reality_engine/pilot3/filings.py lines 93-180 (_Filing/_Doc/_basename), 364-425 (_match_filings_to_docs, _doc_links),
  466-560 (_process_symbol)
- reality_engine/pilot3/docs_collect.py lines 64-72 (BUCKET_TYPES) and 724-800 (_manifest_rows, _manifest_path,
  collect_manifest): new documents enter a store ONLY as new rows in the store's raw manifest.csv, which
  docs_collect then reads. Manifest header (exact, keep column order):
  isin,symbol_at_time,scrip_code,newsid,bucket,headline,category,subcat,dissem_ts,url,source,local_path,bytes,sha256,http_status,attempts,is_pdf,is_scanned_guess,skip_reason,fetched_at,status,error
- reality_engine/raw_store.py::store_bytes
- reality_engine/pilot3/call_dates.py::call_date, reality_engine/pilot3/doc_identity.py::moderator_line
- reality_engine/tests/test_linked_transcripts.py and test_pilot3_filings.py (fixture style)

EVIDENCE (real rows from live stores, 18 Nov)
- filing table columns: exchange, filing_id, symbol, isin, filed_at, exchange_category, exchange_subcategory, headline,
  attachment, kind_hint, held_doc_key, held_doc_type, held_pages, link_urls (JSON list), twin_filing_id, status.
- c08 NAVKARCORP link_only, kind_hint call_intimation, 1-page letter: link_urls ['https://navkarcorp.com/upload_data/Files/transcript-of-investor-conference-call-16-10-2025.pdf'] -> a transcript PDF. Same company: '.../investor-call-audio-recording-27-10-2026.mp3' -> audio only.
  Same company 3-page letters: ['https://www.jsw.in/infrastructure', 'https://services.choruscall.in/DiamondPassRegistration/register?confirmationNu'] -> a call INVITATION (future call, parent's site): nothing to fetch.
- c02 SEAMECLTD: ['https://www.seamec.in/'] on intimation letters (homepage only: nothing to fetch from the letter); ['https://seamec.in/upload/Seamec%20Earnings%20call.mp3', ...] -> audio.
- c05 MANINFRA: ['https://www.maninfra.com/analyst-corner/'] on a letter saying the transcript is uploaded -> investor page: find the PDF on that page whose name/anchor text matches the call (date or quarter).
- c06 SUBEXLTD: 'https://www.subex.com/investors/announcement-filing/#investor-analyst-call' (page with fragment: drop fragment, fetch page).
- c07 SPMLINFRA: '.../SPML-Concall-12-11-2024.mp3', 'https://www.mediafire.com/file/.../Concall-...mp3/file' -> audio; choruscall / zoom.us / kaptify registration links -> invitation.
- c08 JSW: 'https://tinyurl.com/JSWInfraQ1FY27' (shortener: follow redirects, then treat the final URL as pdf/page).
- c12 BUG: NSE-only store, all 241 filings 'not_fetched' though 207 docs are held: doc.source_key is
  'D:/RealityEngine/raw/pilot60_history/VIVIANA/material_filing/nse_105811821.pdf' and filing_id is '105811821'
  (NSE seq_id); the attachment basename is 'VIVIANA_07112026..._covering_letter.pdf', so neither matcher fires.

STEPS
1. filings.py fix A (match NSE by seq_id): in _match_filings_to_docs, before the attachment-name match, an NSE
   filing whose `filing_id` is all digits matches a held doc whose source basename is exactly f"nse_{filing_id}.pdf"
   (one-to-one, same as the other matchers). Test: the c12 shape above gives 'held'.
2. filings.py fix B (link resolved): a held doc whose source_key contains the path segment
   `linked_docs/<SYMBOL>/` and whose file name starts with f"{exchange}_{filing_id}_" marks THAT filing row
   status 'link_held' (instead of 'link_only'); held_doc_key stays the cover letter; add column `resolved_doc_key TEXT` (schema.ensure_columns pattern already used for
   twin_filing_id in run(); add it to the CREATE in pilot3/schema.py too) and set status 'link_held'. Update the
   filing_coverage view in pilot3/schema.py so 'link_held' counts as held (read how 'held' and 'link_only' are
   counted there; add a `link_held` column next to `link_only`). Test it.
3. link_follow.py: `classify_letter(text, urls) -> (intent, targets)` where intent is one of
   'transcript', 'deck', 'audio', 'invitation', 'unknown', from the letter text and URLs:
   - audio: every usable URL ends .mp3/.mp4/.m4a/.wav/.aac or is youtube.com/youtu.be/mediafire .../file, or the
     text says 'audio recording'/'audio link'/'recording of the' and no .pdf URL exists.
   - invitation: text says the call 'is scheduled'/'will be held'/'invite'/'registration'/'dial-in' AND no URL is a
     .pdf; URLs on choruscall.in, zoom.us, kaptify.in, webex, teams.microsoft, reg.dsnl.in, diamondpass are
     invitation links, never targets.
   - transcript: text says 'transcript' (and not only 'transcript will be'); deck: 'investor presentation' /
     'earnings presentation' / 'presentation' with a link.
   - targets: URLs that are not invitation/audio links and not a bare homepage (path '' or '/'); fragments dropped;
     .pdf first. Order kept.
   Test every evidence row above.
4. `resolve(target, intent, anchor_date, company_names, *, get) -> dict` with `get(url) -> (final_url, content_type, bytes)`
   injectable (default uses requests with linked_transcripts' polite per-host pacing and DEFAULT_HEADERS, 60 s timeout,
   follow redirects, max 40 MB):
   - PDF bytes (%PDF-) -> candidate.
   - HTML -> collect <a href> links (absolute-ise with urljoin) that end .pdf or contain '.pdf?'; score each by:
     intent words in href or anchor text (transcript/concall/con-call/earnings call for transcript;
     presentation/investor ppt for deck) +3; a date in href/anchor text within 30 days of anchor_date +3 (parse
     dd-mm-yyyy, dd.mm.yyyy, yyyymmdd, ddmmyyyy, 'january-28-2025', '28th January 2025'); quarter_tag(anchor_date)
     style tag (Q2FY26, Q2-FY26, Q2 FY 2026) +2; keep score >= 4, best first, try at most 3.
   - A one/two-page PDF that itself links a PDF is followed once (like linked_transcripts.resolve_pdf).
   - Accept a candidate only if: pages >= 3; for transcript intent TRANSCRIPT_TEXT or moderator_line hits in the
     first 3 pages; for deck intent pages >= 5 and not transcript-like; any company_names token (from company.name,
     words >= 4 letters, minus Limited/Ltd/India/Industries/Corporation) or the symbol appears in the first 2 pages
     (rejects the parent company's file); printed call date (call_date) if found is within 60 days before
     anchor_date+5. Return {'status':'resolved', url, data, pages, texts, kind} or {'status':'failed', reason}
     with reason in: http_<code>, not_pdf, no_pdf_on_page, no_matching_pdf, too_short, not_transcript,
     wrong_company, date_mismatch, network.
5. `plan_store(store_db, *, get=None) -> list[dict]`: read-only connection; rows = filing rows with status
   'link_only' (dedupe: one plan item per distinct target URL per symbol; the same PDF linked from the BSE and NSE
   twin letters is fetched once and attributed to the earliest filing). Letter text = doc_page text of
   held_doc_key; urls = json link_urls. anchor_date = filed_at[:10]. Output item: exchange, filing_id, symbol,
   isin, bse_code, filed_at, intent, target, outcome ('resolved','held' (sha already in doc.sha256),'audio_only',
   'invitation','no_target','failed'), reason, pages, sha256, url, data (resolved only).
   ALSO plan 'not_fetched' filings whose kind_hint is transcript or deck and whose attachment is a URL or a BSE
   attachment name (BSE: https://www.bseindia.com/xml-data/corpfiling/AttachHis/<ATTACHMENTNAME>; NSE: attachment is
   already a URL): same accept rules, intent from kind_hint, outcome as above, source 'exchange'.
6. `apply_plan(store_dir, items, raw_root=Path('D:/RealityEngine/raw/linked_docs'), store=raw_store.store_bytes)`:
   for each resolved item: dest = raw_root / symbol / f"{exchange}_{filing_id}_{sha[:12]}.pdf"; store(dest, data,
   index_path=raw_root/'_dedupe'/'sha_index.db'); append ONE row to <store_dir>/raw/manifest.csv (never rewrite
   existing rows; skip if a row with the same sha256 or newsid exists): isin, symbol_at_time=symbol,
   scrip_code=bse_code, newsid=f"link:{exchange}:{filing_id}", bucket = 'concall_transcript' or
   'investor_presentation', headline = f"{call label from URL file name} (linked from {exchange} filing {filing_id})",
   category 'Company Update', subcat 'Earnings Call Transcript' / 'Investor Presentation', dissem_ts = filed_at
   (the letter's own time: the earliest moment the link was public), url, source='link_follow' or 'exchange',
   local_path=str(dest), bytes, sha256, http_status 200, attempts 1, is_pdf 1, is_scanned_guess = 1 if mean page
   chars < 50 else 0, skip_reason '', fetched_at now ISO seconds, status 'ok', error ''.
   Also write <store_dir>/link_follow/<run_id>.csv: one row per plan item WITHOUT data/texts.
   Returns counts by outcome.
7. Website finder `find_site_docs(store_db, symbol, *, get=None, since='2024-04-01')`:
   - website = most frequent domain matching `www\.[a-z0-9-]+(\.[a-z0-9-]+)+` (or https?://domain) across the
     company's own doc_page text of its first 30 held docs' page 1, excluding bseindia, nseindia, sebi.gov,
     mca.gov, choruscall, zoom, kaptify, linkintime, kfintech, cdsl, nsdl, gmail, and the domains of share registrars;
     need >= 3 hits else 'no_website'.
   - fetch the homepage; follow at most 12 same-domain links whose href or text contains investor / financial /
     results / presentation / transcript / concall / analyst / shareholder (depth 2, <= 40 pages total per company);
     collect PDF links with their anchor text; keep those whose href/text names transcript/concall/earnings call
     (transcript) or presentation/investor ppt (deck), and whose date or quarter tag (from href/text) is on or after
     `since` (undated links are skipped and counted).
   - each kept PDF goes through the same accept rules (anchor_date = the date from the link, else skipped).
   - returns {'website', 'pages_crawled', 'pdfs_seen', 'items': [...plan items with source 'company_site',
     exchange 'SITE', filing_id = sha[:16]], 'verdict': 'found' | 'no_call_documents_on_site' | 'no_website' |
     'site_unreachable'}. apply_plan handles SITE items the same way, but dissem_ts = fetched_at (a site file has no
     filing time: never back-date it).
8. CLI: `python -m reality_engine.pilot3.link_follow --store-dir <dir> [--plan-only] [--site] [--symbols A,B] [--json out]`
   prints a per-symbol table: link_only letters, resolved, held, audio_only, invitation, failed by reason, exchange
   not_fetched transcripts/decks resolved, site verdict and docs found.
9. Tests in reality_engine/tests/test_link_follow.py with a fake `get` and in-memory PDFs built with pymupdf
   (pymupdf.open(); page.insert_text). Cover: each evidence row's intent; HTML page pick by date and by quarter
   tag; parent-company PDF rejected (wrong_company); 2-page PDF rejected (too_short); deck/transcript check;
   manifest append is idempotent and keeps the header; twin dedupe; fix A and fix B in test_pilot3_filings.py.
10. Docs: add a section '9u. Link follower and website finder (T-223, R-012/R-014)' to docs/PILOT3_BLUEPRINT.md
   after 9t (what it reads, the intents, accept rules, manifest row, statuses link_held, CLI); update 9t for fix A/B.

LIMITS / PITFALLS
- Do not edit: comparatives.py, segments_printed.py, ar_notes.py, ar_statements.py, scripts/store_repair.py,
  scripts/store_diff.py, linked_transcripts.py public functions (you may import them).
- Never write the store database from link_follow (read-only connect `file:...?mode=ro`); documents enter only via manifest.csv.
- doc_type is never taken from the exchange label; the bucket only seeds it, docs_collect retypes by pages.
- No new dependencies (requests, pymupdf, stdlib html.parser/re only).
- Keep functions small; type hints; ruff clean; basedpyright clean on changed files (run_check).
BUDGET / STOP: 90 minutes. If a step is blocked, finish the others, write what blocked in your final answer.
ACCEPT: all new and existing tests in test_link_follow.py, test_pilot3_filings.py, test_linked_transcripts.py,
test_docs_collect.py pass; final answer lists files changed, tests run with counts, and any rule you could not meet.
