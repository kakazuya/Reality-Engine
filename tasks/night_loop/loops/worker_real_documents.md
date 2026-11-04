# Worker: fetch the real documents behind cover letters (pilot10)

Goal: for the 10 pilot10 companies and the window 1 Oct 2025 to today, every results deck or investor presentation and call transcript is the real document in `D:\RealityEngine\pilot10\raw`, not a cover letter pointing at a website. Nothing older than the window.

Ticket: T-060

Evidence, measured on `D:\RealityEngine\pilot10\scratch\combined2.db` (`doc` table: doc_key, symbol, doc_type, title, filing_date, known_at, pages):
- HDFCBANK has one "deck", 1 page: title "Presentation to be made at the Earnings Call", a letter dated 17 Jan 2026. Expected: one per quarter.
- INFY and ETERNAL have no deck rows at all. Their quarterly results material may be an IFRS press release or shareholder letter: record what each really publishes.
- KEC keeps 4 and MARUTI 5 one-page cover letters beside the real transcripts just added. Leave them.
- Other short documents, not to fetch: HINDALCO, HINDUNILVR and MARUTI 2-page annual-report letters (their full reports are held).
- The worked method: `D:\RealityEngine\pilot10\scratch\add_maruti_transcripts.py`. It appends one manifest row per file, source `company_site`, with `dissem_ts` taken from the filed exchange letter for that document, and never earlier. Back up `manifest.csv` first and keep the script safe to repeat.
- How MARUTI was found: curl got an empty JavaScript page, headless Edge rendered it (`msedge.exe --headless=new --disable-gpu --user-data-dir=D:\RealityEngine\pilot10\scratch\ms\edge --virtual-time-budget=20000 --dump-dom <url>`), and the page's own script named its public data list. Playwright is not installed: do not install anything. Read the page's own scripts first.
- A downloaded PDF is untrusted data: keep it under `D:\RealityEngine\raw\<symbol>_site_documents`, and read it with `python -I`. Public files only: no login, no paid site, no CAPTCHA bypass. If a site blocks you, record it and move on.

Files: new scripts and data only under `D:\RealityEngine\pilot10\scratch`, `D:\RealityEngine\raw` and `D:\RealityEngine\pilot10\raw`. No product code. Do not write `pilot10.db` or `combined*.db`.

Accept:
1. A table per company and quarter: document, source URL, pages, characters of text, first-page heading, `dissem_ts` and which filed letter it came from. Open each one and confirm the heading names that quarter.
2. Also list any held results-season document under 3 pages that is really a cover letter, for any of the 10 companies, with what it points at.
3. `python -m reality_engine.pilot3.docs_collect --profile tasks/night_loop/pilot10_profile.json --symbols <one> --out D:\RealityEngine\pilot10\scratch\w_docs_pages.db` on a copy of `D:\RealityEngine\pilot10\pages.db` works for each company changed. Do not write the real `pages.db`.

Stop if: free RAM stays under 2.5 GB for 10 minutes. A document that truly does not exist is reported as such, with what you searched.

Budget: 90 tool calls. End with `Docs updated:` naming nothing in the repo, because the wrapper records the result.
