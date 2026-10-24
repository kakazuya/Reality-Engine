# Concall runner patch + 25-doc pilot — handoff (2026-10-24)

Owner: Shivam · Executor: DSH worker · Reviewer: Claude
Branch: `wip/concall-runner-2026-10-24` (this checkout's `main` is left clean; check the branch out to review).

## What is done

**Runner patch — `reality_engine/scripts/concall_deepseek.py`**
- `--from-chunks`: text from `document_chunks` (ordered by `chunk_index`, overlap-aware word join, metadata header
  stripped), used when the recorded PDF is not on disk. Joins `corporate_documents` to `raw_documents` by `sha256_hash`
  first, then `source_url`.
- `--strict-date`: merged queue sorted strictly newest → oldest by real `COALESCE(bse_dissem_ts, publication_date,
  call_date)` (or the parsed call date for undated docs). Drops the PEAD and `queued_429`-first sort keys. Verified
  monotonic on 8,536 rows.
- Done-set fix: `skip_unreadable` and `skip_unreadable_text` are retryable and never done; terminal skips (`ok`,
  `skip_cover_letter`, `skip_duplicate`) stay done. A doc with no readable text now writes `skip_unreadable_text` and
  re-enters the next queue. A doc with neither a local path nor chunks is left out of the queue ("not runnable yet"),
  so absent PDFs are not burned.
- Date resolver: parses the call date from the first 3,000 chars (`Q1 FY27 Earnings Conference Call ... August 11,
  2026`, `11th August 2026`, `11-08-2026`, `held on 04-Jun—19`, `dated ...`). Prefers a date next to a call cue over a
  cover-letter date; sanity-checks call ≤ filing and ≤60 days; uses the crawl stamp only as an upper bound for the
  known crawl-stamp-overwrite rows. `date_source` is stored in a new `cc_docs.date_source` column (auto-added by
  `_ensure_column`).
- Lanes: `--lanes KEY_ENV=model[,KEY_ENV=model...]`; three lanes interleaved by queue position, each with its own
  429 bench (`LANE_TAP_S=900`, one tap worker) and a stable `x-opencode-session` per lane (`session_id(..., lane_no=i)`).
  Kilo models (`reflection/beam-free`) route to `https://api.kilo.ai/api/gateway/chat/completions`; Go keeps the old
  `zen/go` endpoint (new docs endpoint also answers, not switched). Per-lane stats logged at the end.
- Prompt default is now `prompt_v3.md` (v2 is absent).

**Supporting patches**
- `concall_pilot.call_go(model, prompt, key, session=, url=)` — gateway override + stable session.
- `concall_facts_checks.py` / `concall_deepseek_check.py` — read chunks when the PDF is missing (QA previously crashed
  on chunk-only docs); text-dated rows exempted from the `filed_at == real filing` PIT check; speaker detection extended
  to chunk text (no line breaks, lowercased text layers) via participant names. **The QA rerun was stopped by the
  wrap-up order; the current `cc_item_checks` table is from the first (pre-speaker-fix) pass.**

**Tests** — `reality_engine/tests/test_concall_reader_patch.py`, 14 tests, all pass:
```
Ran 14 tests in 1.234s
OK
```
Covers chunk join (header + overlap), from-chunks fallback, date patterns + sanity rules, retryable skip + requeue,
terminal done-set, strict ordering (including a text-dated doc and a queued_429 doc), lane URLs/sessions.

## Pilot (real `concall_facts.db`, approved)

25 newest readable transcripts, 3 lanes, 6 workers, `--max-out 48000`, 2026-10-25 00:05:18–00:12:02 IST.

| lane | docs | ok | items | sec/doc | 429 |
|---|---|---|---|---|---|
| Go key 2 `beam-free` | 9 | 9 | 771 | 88.2 | 0 |
| Kilo key 1 `reflection/beam-free` | 8 | 8 | 774 | 82.3 | 0 |
| Kilo key 2 `reflection/beam-free` | 8 | 8 | 744 | 89.5 | 0 |
| **total** | **25** | **25** | **2,289** | **86.3** | **0** |

- Wall throughput: 25 docs / 6m44s ≈ **223 transcripts/h** at 6 workers; no 429s. Items/doc: 91.6 (range 47–144).
- `concall_deepseek_check --since-run 2026-10-25T00:05`: 26 docs (25 + one leftover), **ALL CHECKS PASSED**.
- `concall_facts_checks` (first pass, all 7,504 docs): pilot items `value_in_quote` **814/818 (99.5%)**, guidance
  `period_in_quote` 74/136, `direction_supported` 10/28; `speaker_role` all `unknown` before the speaker fix.
- Runner `machine_check` removed per pilot: 146 bad quotes, 368 numbers not in text, 13 value-not-in-quote.
- 3 spot checks (quote located in the assembled chunk text; value matches): SKYWAYS capex INR 35–40 cr p.a.;
  SKYWAYS new-geography break-even 15–18 months EBITDA / 2–3 years PAT; BLEL operating EBITDA INR 27 cr, Q1 FY27.
- Extra row: `MAXHEALTH` (doc 56398) is a valid `ok` read left by the aborted 32k first attempt (run_at 00:05:09),
  not one of the 25. Keep or delete at review.

## Date resolver coverage (1,499 undated)

| bucket | count |
|---|---|
| undated transcripts | 1,499 |
| text available (chunks; 0 PDFs on disk) | 318 |
| no text (1,181) | 1,181 |
| confident date (high 104 + medium 24) | **128** |
| low confidence parsed but not used | 102 |
| no date pattern in first 3k | 88 |
| enter the strict-date queue (≥2016 after since filter) | **126** |

Resolved years: 2015:2, 2016:29, 2017:23, 2018:30, 2019:34, 2023:4, 2024:4, 2025:2. Artifact:
`tasks/concall_date_resolver_2026-10-24.json`. The queue (8,536 docs, 110 duplicates) is strictly newest→oldest;
126 text-dated rows sit at their parsed date positions.

## LongCat finding (2026-10-24/25 probe)

- Docs page still lists **LongCat 2.5 Preview Free**, model id **`longcat-2.5-preview-free`** (old and new Go
  endpoints), but the Go models API (37 models) lists **only `beam-free` as free** — LongCat is absent from the API
  listing.
- 7 calls over ~10 min: **1× HTTP 200** (23:42:07, old endpoint, key 2) and **6× HTTP 429 "Upstream request failed:
  Endpoint is unavailable"** (both endpoints, three retry rounds). Go key 1 is 403 "subscription required"; Go key 2
  Beam 200; Kilo key 1/2 Beam 200.
- Verdict: **capacity / intermittent endpoint, not removed** (it answered once). Not added as a lane; the 5-doc gate
  was not run because 6/7 calls were 429. Re-probe before any decision.

## Open problems

1. **Output truncation.** Beam default effort can consume the whole output budget on reasoning. 32k produced 4/6
   `error_json` in the first pilot attempt; 48k passed 25/25 but Kilo still hit exactly 32,000 output tokens on 2 docs
   (retries recovered). 64k works on both gateways in direct tests. Full run uses `--max-out 64000`; watch for Kilo
   per-request caps and `error_json` rows.
2. **Chunk text is lowercased and has no line breaks** on many docs (the text layer/chunker normalises whitespace).
   `join_chunks` therefore cannot preserve speaker line tags. QA speaker detection was patched to use participant
   names, but the QA table was not rebuilt before stop; `speaker_role` in `cc_item_checks` is stale `unknown`.
3. **Date parser**: only 128/1,499 undated get a confident date because 1,181 have no text and 88 start mid-call
   (cover page pruned); 102 low-confidence parses are deliberately not used. Old calls (2016–2019) are the bulk of
   the resolved set.
4. **Four newest unread transcripts** (CANBK, FEDERALBNK, UCOBANK, ANANDRATHI) have no PDF and no chunks; they are
   excluded from the queue as not runnable, not marked done. They need a BSE re-fetch + chunk pass.
5. **Queue size** 8,536 (not 12,727): 4,272 unchunked transcripts and the 4 above have no text on disk; the 1,814
   read-but-unchunked docs are already done. Fetch PDFs to grow the queue.
6. `cc_docs` now has `date_source`; old rows are NULL until re-read. `renormalise` handles the column.
7. `git status` still shows pre-existing untracked files and sandbox-denied `reality_engine/tests/tmp*` dirs from a
   failed `tempfile` test attempt; none are part of this branch.

## Exact next commands

```powershell
# 1) refresh QA checks with the speaker fix (about 10 min, rewrites cc_item_checks)
python -m reality_engine.scripts.concall_facts_checks
python -m reality_engine.scripts.concall_deepseek_check --since-run 2026-10-25T00:05

# 2) full newest -> oldest run (8,536 docs; free readers; approve separately)
python -m reality_engine.scripts.concall_deepseek --lanes "OPENCODE_GO_API_KEY_2=beam-free,KILO_API_KEY=reflection/beam-free,KILO_API_KEY_2=reflection/beam-free" --workers 6 --prompt prompt_v3.md --all-companies --since 2016-01-01 --from-chunks --strict-date --max-out 64000

# ramp only after an hour of zero 429s: --workers 9 (3 per lane), then 12

# 3) PDF side for the 4,272 unchunked + the 4 newest (parallel with extraction)
python -m reality_engine.scripts.run_annual_report_ingest --doc-type CONCALL_TRANSCRIPT --download-only --workers 4 --since 2026-01-01
python -m reality_engine.scripts.run_annual_report_ingest --doc-type CONCALL_TRANSCRIPT --local-only

# 4) LongCat only if a fresh probe is stable; 5-doc spot check first, never a default lane
python -m reality_engine.scripts.concall_deepseek --lanes "OPENCODE_GO_API_KEY_2=longcat-2.5-preview-free" --workers 1 --prompt prompt_v3.md --all-companies --since 2016-01-01 --from-chunks --strict-date --limit 5 --max-out 64000
```

Artifacts: `tasks/concall_date_resolver_2026-10-24.json`,
`reality_engine/data/logs/concall_lane_probe_2026-10-24.json`, `reality_engine/data/logs/concall_lanes.log`.
