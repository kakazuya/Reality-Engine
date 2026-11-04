# Worker: guidance recall on pilot10

Goal: real forward guidance held in transcript statements becomes `guidance` rows for every company with real transcripts, without losing the precision loop 3 won. Today on `D:\RealityEngine\pilot10\scratch\combined.db`: BAJFINANCE 6, HDFCBANK 1, HINDALCO 31, HINDUNILVR 1, INFY 14, KEC 13, SBILIFE 1, ETERNAL 0, SUNPHARMA 0, MARUTI 0.

Ticket: T-058

Evidence: `transcript_statement` on that database holds these sentences and `guidance` holds none of them (doc_key suffix, page):
- SUNPHARMA 9f3e072921 p6: "On the guidance, we expect high single-digit consolidated top line growth for FY27". A worded target with no digit.
- SBILIFE bd5b8a9331 p16: "the guidance of 14% to 15% overall company". SBILIFE 146b7a1f07 p18: "the guidance of 26% to 28% range" (margin). Speaker is stored as `Management`.
- ETERNAL 48485a9e47 p4: "overall guidance of 60% CAGR". ETERNAL 48485a9e47 p6: "5-6% margin that we are saying we will get to". ETERNAL 07eb15a5d9 p3: "over the next 1 or 2 years, we expect the margins to remain flattish". ETERNAL 07eb15a5d9 p12: "in steady state it could get to about INR 11 lakh per day per store".
- HINDUNILVR 30e33bc311 p11: "full year '27 will be ahead of full year '26, and we are retaining that guidance". HINDUNILVR b8661c2a40 p30: "fiscal year'27 to be better than fiscal year'26 on the top line and the margins to stay in the guided range".
- HDFCBANK c68c39dc8a p14: "the provision coverage will be in the 70s, mid-70s or higher".
- Not guidance, must stay out: HINDUNILVR 6898e22003 p4 "EBITDA margin at 23.7%, coming in at the higher end of our guidance" (a past result). SUNPHARMA 1f3c4fd225 p4 "Exceptional items for Q1 FY27 include a charge" (a past item). HDFCBANK 547a7db75e p10 about who will chair the Board (no metric).
- `guidance` columns: id, symbol, isin, metric, target_period, low, high, unit, direction, said_on, doc_key, page, quote, speaker, known_at, known_at_source, revision_of, extractor_rule. A worded target has `low` and `high` null, and `direction` plus the exact quote carry it. Do not invent numbers for "high single-digit".
- Code: `reality_engine/pilot3/guidance.py`: `DOC_TYPES` line 47, `MAX_ROWS_PER_PAGE` line 48, `CUE` line 53, `PAST_ONLY` line 57, `FORWARD` line 76, `METRICS` line 106, `numbers()` line 179. Use `outline` for the rest. Blueprint and guide O state the false-positive rules from loop 3: keep every one.
- MARUTI has only 1-page cover letters as transcripts (5 docs, 5 pages), so 0 rows from transcripts is expected. Read its decks, and report what is there.

Rules: general wording only, no company names in code, and a sector word goes in a lexicon. A row needs a named metric and the exact quote. Precision outranks recall.

Data: copy `combined.db` to `D:\RealityEngine\pilot10\scratch\w_guid.db` by sqlite3 `backup`. Never write `pilot10.db` or `combined.db`.

Fast check: `python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part guidance --out D:\RealityEngine\pilot10\scratch\w_guid.db` (about 6 s for all 10). Run it in the foreground; do not poll.

Accept:
1. Every sentence listed above as guidance gives a right row, or the report says why not. The three listed as not guidance give none.
2. Hand read of 20 random rows per company (all rows if fewer): at least 18 of 20 right, quote and period shown in the report.
3. `python -m reality_engine.night_eval.answerable --db D:\RealityEngine\pilot10\scratch\w_guid.db --qset tasks/night_loop/questions/dev.jsonl --out D:\RealityEngine\pilot10\scratch\a1_guid.json`: at least 694 of 898, no company lower. Do not change the grader. Its 22 needs named `guidance.guidance` stay unmet: report them.
4. `python -m pytest reality_engine/tests/test_pilot3_guidance.py -q` with new tests from the sentences above, and `python -m reality_engine.pilot3.checkpages run` still at 145.

Files: `reality_engine/pilot3/guidance.py`, `reality_engine/pilot3/lexicon/*.yaml` if needed, `reality_engine/tests/test_pilot3_guidance.py`, your paragraph in `docs/PILOT3_BLUEPRINT.md` and guide O in `docs/DEVELOPER_GUIDE.md`. Do not touch `tasks/`. Keep `PROGRESS_NOTES.md` out of the diff.

Stop if: free RAM stays under 2.5 GB for 10 minutes, or precision falls under 18 of 20 on a company after two tries. Report the rows either way.

Budget: 120 tool calls. End with rows per company before and after, the hand read, A1 per company, and a `Docs updated:` line.
