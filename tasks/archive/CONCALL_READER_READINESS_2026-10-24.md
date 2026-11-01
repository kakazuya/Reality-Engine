# Concall reader readiness — can extraction restart on free readers?

**Date:** 2026-10-24 ~23:10 IST (off-peak) · **Owner question:** Shivam (2026-10-24) · **Reviewer:** Claude
**Report only — no bulk extraction was started.** One 110-piece reader-admission gate was started on a free model
(Flint on Kilo) because Shivam approved small free gate tests; no concall transcript was read.

## Bottom line

- **Yes, but on one model only: `beam-free`.** Go account 2 still serves it free (HTTP 200, cost 0); Go account 1 is
  dead (403 "active OpenCode Go subscription required"). Kilo serves the same `reflection/beam-free` free on both Kilo
  keys. **MiniMax M3.1 Flash free is retired (410 ModelDeprecated); LongCat 2.5 Preview free is retired (429 "Endpoint
  is unavailable", delisted).** Zen free models still list but the CLI route is off under the standing IP-block decision
  and direct calls 403.
- **The blocker is not the models, it is the text.** 0 of 20,158 recorded concall PDFs exist on this laptop; the Drive
  archive holds only **2,289** transcript PDFs (partial A–P, mostly 1–2 per company). But **9,954 unread transcripts
  already exist as text in `document_chunks`**, so extraction can restart **today** without any PDF — after one small
  code change to feed the reader from stored chunks. The other 4,272 unread transcripts need a PDF (BSE re-fetch works:
  two trial downloads returned `application/pdf`, HTTP 200).
- **Measured capacity:** Beam read 2,582 transcripts in 7.8 h at 32 workers = **329 transcripts/h** (56 s each) before
  upstream 429s; MiniMax did 215/h at 16 workers (now dead). One Beam lane ≈ **330/h**; a second Beam lane on Kilo
  (same model, own gateway) could roughly double it, untested for text throughput.
- **Time:** 2026 queue = 1,994 unread → **~6 h** on one lane, ~3 h on two. All 12,727 dated unread → **~39 h** one lane,
  ~19 h two. The 1,499 undated transcripts stay out (no point-in-time date), as the standing rule says.
- **Quality:** Beam is the only working reader with a recorded gate: **23/25 must-find on Go, admitted by Shivam
  2026-10-17 despite the miss**; concall recall 92.9% vs paid DeepSeek; prompt-v3 blind reviews found 0 material errors
  in 32 items (v2: 2/48). LongCat passed 25/25 but is gone. Flint hit **25/25** on 2026-10-24 but extracted 3,712 facts
  (depth rule 4,500) and runs ~160 s per 18 k-char piece, so it fails admission and would breach the 300 s cull on a
  48 k-char transcript.

## 1. Reader code path, routes, and where facts land

- Runner: `reality_engine/scripts/concall_deepseek.py` — queue from `equity_intelligence.db.corporate_documents`
  (`doc_type='CONCALL_TRANSCRIPT'`, `COALESCE(bse_dissem_ts, publication_date, call_date) >= --since`, a non-empty
  `local_file_path`), optional Telegram-company filter (`tg_company_isins.json`, off with `--all-companies`), sharded by
  `doc_id % n`, newest filing first inside a PEAD-priority group.
- Reader call: `concall_pilot.call_go()` → `POST https://opencode.ai/zen/go/v1/chat/completions`, `max_tokens=--max-out`
  (32,000), header `x-opencode-session` from `go_session.session_id()` (stable per job/model/key/lane). Prompt is
  `data/concall_pilot/prompt_v3.md` (v2 is **absent** — the default `PROMPT_FILE="prompt_v2.md"` therefore crashes into
  per-doc `status='error'` unless `--prompt prompt_v3.md` is passed).
- Prompt output → `parse_json` → `concall_pilot.machine_check` (quote verbatim, every value's digits in the transcript,
  basis word present, plus the prompt-v3 value-in-quote gate) → `cc_docs` + `cc_items` in `concall_facts.db`.
- QA: `concall_facts_checks.py` writes `cc_item_checks` (value_in_quote / period_in_quote / direction_supported /
  speaker_role / metric_key / computed_direction); `concall_deepseek_check.py` checks labels/periods/duplicates.
- Free models bypass the spend guard (`FREE_MODELS`), but still use the same 429 lane logic: a 429 benches the whole
  lane, one worker taps it every 15 min, and no doc is spent (256 Beam `queued_429` rows from 2026-10-20 are still first
  in the queue).
- The extractor reads the PDF itself with PyMuPDF only (`text_of`, lines 124–127). It never reads `document_chunks`,
  never OCRs, never sees images, and has no per-call timeout (the 300 s rule is enforced nowhere in this file).

## 2. Route table (one tiny call per key × model; 18 model calls total, 1 CLI attempt)

Prompt "Reply with the single word OK.", `max_tokens=16`, stable session header. Latency is the full round trip.

| # | Route / key | Model | HTTP | Latency | Free? | Evidence / error |
|---|---|---|---|---|---|---|
| 1 | Go key 1 | `beam-free` | **403** | 1.0 s | listed free, unusable | "An active OpenCode Go subscription is required to use Go models." |
| 2 | Go key 1 | `minimax-m3.1-flash-free` | **410** | 1.0 s | gone | ModelDeprecated |
| 3 | Go key 1 | `longcat-2.5-preview-free` | **403** | 1.0 s | gone | subscription error (model also delisted) |
| 4 | Go key 2 | `beam-free` | **200** | 1.4 s | **yes** (cost 0, `billing_source: go`) | 16 completion tokens, all reasoning; route alive |
| 5 | Go key 2 | `minimax-m3.1-flash-free` | **410** | 1.0 s | gone | ModelDeprecated |
| 6 | Go key 2 | `longcat-2.5-preview-free` | **429** | 1.8 s | gone | "Endpoint is unavailable" (retried twice, same) |
| 7 | Kilo key 1 | `reflection/beam-free` | **200** | 1.5 s | **yes** (market_cost 0) | route alive |
| 8 | Kilo key 1 | `nvidia/nemotron-3-super-120b-a12b:free` | **404** | 0.6 s | listed free | provider "Function … not found" |
| 9 | Kilo key 2 | `reflection/beam-free` | **200** | 1.3 s | **yes** | route alive |
| 10 | Kilo key 2 | `nvidia/nemotron-3-super-120b-a12b:free` | **404** | 0.6 s | listed free | same provider 404 |
| 11 | Kilo key 1 | `nvidia/nemotron-3.5-lightning:free` | **200** | 1.0 s | yes | ping only; previously AR-failed |
| 12 | Kilo key 1 | `recursive/flint-v1.0:free` | **200** | 0.7 s | yes | gate: 25/25 but 3,712 facts < 4,500 depth |
| 13 | Kilo key 1 | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | **200** | 1.6 s | yes | ping ok; gate failed to run (502) |
| 14 | Kilo key 1 | `xingchen-agi/xing4.0-29b-a4b:free` | **429** | 1.3 s | listed free | upstream rate-limited (twice) |
| 15 | Zen direct (no Zen key in env) | `big-pickle` | **403** | 0.9 s | policy | FreeTierError "free tier can only be used from within OpenCode" |
| 16 | Zen CLI | any | n/a | — | — | CLI cannot start under this file sandbox (`EPERM` on its own log). `new_reader_check.ZEN_BLOCKED=True` by standing decision; the IP block is still on record. |

**Model lists (fetched live):** the model-list GET returns 200 on both Go keys (key 1 can list but cannot call). Go = 37
models, **only `beam-free` is free**; `minimax-m3.1-flash` / `longcat-2.0` now exist only as paid ids (not called).
Zen = 85 models, 8 free (`beam-free`, `flint-40b-free`, `mimo-v2.6-flash-free`, `nemotron-3.5-super-vl-free`,
`nemotron-3.5-lightning-free`, `jev-1.13-free`, `deepseek-v4.1-flash-free`, `glm-5.3-flash-free`) but unreachable from
this IP/CLI. Kilo = 402 models, 14 free (`reflection/beam-free`, Dots, Nemotron variants, Flint, Laguna, LFM, etc.).

**Verification of "still free":** Go usage block on the working call: `"cost": 0, "opencode": {"billing_source": "go",
"list_cost": 0}`; Kilo usage block: `"market_cost": 0` for Beam, Flint, Lightning, Nano.

## 3. Inventory and the PDF wall

Live ledger (corporate_documents date basis, not the published_date year split):

| bucket | docs |
|---|---|
| known concall transcripts | 21,703 |
| chunked (text in `document_chunks`) | 15,617 |
| read OK (`cc_docs.status='ok'`, all models) | 7,477 |
| — Beam-free | 2,582 |
| — MiniMax M3.1 Flash free (high) | 3,839 |
| — DeepSeek V4.1 Flash (paid) | 1,056 |
| read & chunked | 5,663 |
| read but unchunked (search gap) | 1,814 (342 of them 2026) |
| chunked but unread | **9,954** |
| unchunked and unread | **4,272** |
| total unread | **14,226** |
| undated (no PIT date; excluded by rule) | 1,499 (318 chunked, 1,181 unchunked) |
| dated unread (the real queue) | **12,727** |

Note: the coverage JSON's "8,140 chunked-unread" assumes every read doc is chunked. It is not: 1,814 read docs have no
chunks, so the true chunked-unread count is 9,954. The 342 figure is exact.

**PDFs:** 20,158 transcripts record a `local_file_path`, **0 exist**. Drive `InfoDiffusion_archive/pdfs/<SYMBOL>/CONCALL_TRANSCRIPT/`
holds **2,289** PDFs (alphabetically it stops at P; TCS / RELIANCE / POWERGRID folders are absent; zero-coverage companies
have 1 each — GODREJPROP 1/42, DABUR 1/40, HIMATSEIDE 1/44, GVT&D 1/46, DEEDEV 2/9). So Drive alone cannot restore the
queue. BSE re-fetch does work: two sampled `AnnPdfOpen.aspx` links returned HTTP 200 `application/pdf` with a browser UA
and `Referer: https://www.bseindia.com/`. The PC copy is unavailable until ~26/27-Nov.

**What this means:** the 9,954 chunked-unread transcripts can be extracted with **no PDF and no download** if the runner
can read stored chunk text. The 4,272 unchunked-unread (plus 1,814 for the search layer) need the BSE re-fetch/chunk pass.

**Do not start the current runner before the patch.** A missing PDF raises inside `text_of`, and `work()` saves it as
`status='skip_unreadable'`; the queue's done-set counts every `skip_*` as done. Starting now would therefore burn all
17,869 absent PDFs permanently in one pass. The chunk-based patch must also treat a missing file as "not runnable yet",
not as `skip_unreadable`.

## 4. Throughput and time-to-read

Measured from `cc_docs` (not a bench):

| reader | docs | wall window | rate | avg per doc |
|---|---|---|---|---|
| Beam-free | 2,582 | 2026-10-20 04:01–11:52 (7.8 h) | **329/h** | 56.3 s |
| MiniMax free (dead) | 3,839 | 17.8 h | 215/h | 181.5 s |
| DeepSeek paid (benchmark) | 1,056 | 5.3 h | 197/h | 106.9 s |

Concurrency caveat: Beam's 32-worker run hit upstream 429 at 11:52 and wrote nothing after; Shivam reset it to 6 workers
with a 15-min single tap and it stayed down that evening. So 329/h is an upper observed rate, not a guaranteed one.
Plan on **250–330/h per Beam lane** and ramp by bisection while 429s stay ~0.

Latest-period-first schedule (PIT filing date; queue = chunked-unread + unchunked-unread):

| period | unread | 1 lane @330/h | 2 lanes @660/h |
|---|---|---|---|
| 2026 | 1,994 | 6.0 h | 3.0 h |
| 2025 | 2,709 | 8.2 h | 4.1 h |
| 2024 | 2,529 | 7.7 h | 3.8 h |
| 2023 | 2,347 | 7.1 h | 3.6 h |
| 2022 | 1,849 | 5.6 h | 2.8 h |
| 2021 | 746 | 2.3 h | 1.1 h |
| 2020 | 439 | 1.3 h | 0.7 h |
| ≤2019 | 114 | 0.3 h | 0.2 h |
| **dated total** | **12,727** | **38.6 h** | **19.3 h** |
| undated (excluded) | 1,499 | +4.5 h | +2.3 h |

2026 is 1,994 not 3,493: the coverage file's 5,104 "2026" is a `published_date` count inflated by the 1,499 undated
filings (event_date overwrite artifact). The 2026 **PIT-dated** set is 3,605 (1,611 read, 1,994 unread). The newest
block is small and fast: 2026-10 (7 docs), 2026-09 (4), 2026-08 (454), 2026-07 (148) → the newest 613 docs ≈ 1.9 h.

The three numbers the brief asked about, reconciled:
- **342 (2026 read-but-unchunked):** no extraction left — they already have facts; they need a PDF only to be chunked
  for the search layer (~15 min at the measured 21–40 reports/min chunking rate), part of the 1,814 backfill.
- **6,086 unchunked:** 1,814 are already read (chunking only, ~1 h once PDFs are fetched) and **4,272 are unread**
  (fetch + chunk + extract, ~13 h of Beam time).
- **"8,140" chunked-unread is really 9,954** (the JSON assumed every read doc was chunked). These need no PDF at all:
  ~30 h on one Beam lane, ~15 h on two; the 2026 subset (1,625) is ~5 h.

PDF tail: the 4,272 unchunked-unread need a BSE fetch; measured fetch rates earlier were ~15 PDFs/min on BSE (1,069 in
72 min) and ~36 files/min on rclone. So ~4–5 h of download before the unchunked half of a period can be read. Run it in
parallel with extraction.

**Quota:** Go free models carry no per-model dollar cap (cost 0), so the old $16/$40/$80 windows do not bind. The
binding limits are upstream concurrency/429 and the single-subscription key (key 1 dead). Kilo free models share one
Kilo quota per model across keys; deck history shows no throttle to 120 parallel, and 429 at 300.

## 5. Reader/gate status

| model | 25/25 must-find | Concall evidence | Verdict |
|---|---|---|---|
| Beam-free (Go) | **23/25**, 0.1% numbers not in text; admitted by Shivam 2026-10-17 despite the miss | 92.9% recall vs DeepSeek, 44 s/transcript; prompt-v3 blind review: 0 material errors/32 items (v2: 2/48) | **production reader** |
| Beam-free (Zen) | `reader_watch.json` records run `t-beam-1017` result `pass` (score file not retained) | same model; Zen route blocked now | not usable |
| MiniMax M3.1 Flash free | no AR gate record; joined on the concall bench | 93.3% recall at xhigh (245 s), 97.2% at max (268 s); 11/197 docs >300 s; v3 review 0/32 | **retired (410)** |
| LongCat 2.5 Preview free | **25/25** | used as verifier, not reader | **retired (429 endpoint)** |
| Flint v1.0 (Kilo) | **25/25 must-find**, 0.2% numbers not in text (6/2,788), 0/110 unanswered — **but 3,712 facts < the 4,500 depth rule** | ~70–288 s per 18 k-char AR piece (median ~160 s) → extrapolated ~430 s per 48 k-char transcript, over the 300 s cull | **not admitted** (depth + speed) |
| Nemotron Nano Omni (Kilo) | gate attempted, **failed to run**: 0/110, upstream 502 `ResourceExhausted` / connection resets | — | not admitted |
| Nemotron 3.5 Lightning (Kilo) | earlier AR fail (422 facts, shallow); ping works | — | not a reader |
| Kilo Beam (`reflection/beam-free`) | same model, host not separately gated | ping 200 | usable as a second lane pending a host gate/throughput check |

The standing gate is the AR 110-piece test (`ar_queue.py test-export` + `drive`): pass = 25/25 must-find, <1% numbers
not in the text, every piece answered, ≥4,500 facts. Beam's 23/25 is a recorded miss with Shivam's explicit waiver, not
a pass.

## 6. Recommended run plan (strict latest → oldest)

**Order:** one merged queue over `chunked-unread` + `unchunked-unread`, sorted strictly by real filing/call date
(`COALESCE(bse_dissem_ts, publication_date, call_date)`) descending; no PEAD-first group; undated excluded. DEEDEV and
the 242 zero-coverage companies fall in by date — DEEDEV's calls are 2026-08-11, 2026-05-27, 2026-02-10, 2025-11-12 …
so its newest call lands in the 2026-08 block (454 docs), not ahead of it.

**Phases**
1. **Patch (Claude review, ~30 lines):** `concall_deepseek.py` gains `--from-chunks` (read `document_chunks.content`
   ordered by `chunk_index`, overlap-aware join; allow docs without `local_file_path`) and `--strict-date` (drop the
   PEAD and `queued_429`-first sort keys — retries re-enter at their date position; union both sources). Also pass
   `--prompt prompt_v3.md` explicitly — v2 is not on disk.
2. **Pilot (free, ~1 h):** 25 newest docs (2026-10) through `--from-chunks`; verify quotes/values with
   `concall_facts_checks`, compare one doc against the chunk text, check `cc_docs.seconds` stays under 300 s.
3. **2026 lane (one Beam lane, 8 workers):** 1,994 docs ≈ 6 h; newest block first (613 docs ≈ 2 h). Two lanes once the
   Kilo Beam host passes a throughput check; do not exceed 8–12 workers per lane without a 429-free ramp.
4. **PDF side (parallel):** BSE re-fetch the 369 unchunked 2026 transcripts (+ 342 read-but-unchunked for search) and
   walk back; `--download-only` then `--local-only` so chunking uses the OCR-capable PDFIngestor; those docs then join
   the same date queue.
5. **Walk back** 2025 → 2019 by period; the 4,272 unchunked docs enter as their PDFs land. Requeue the 228 `error` and
   256 `queued_429` rows automatically (they are not marked done).
6. **QA after each batch:** `concall_facts_checks`, `concall_deepseek_check`; spot-check 1–2 items per batch for meaning
   (verbatim quotes alone are not sufficient — the Dhanuka lesson).

**Route mix:** Beam on Go key 2 as the primary lane; Beam on Kilo key 1 (then key 2) as a second lane only after a
short host check (same model, separate gateway). No MiniMax/LongCat/Zen calls — they are dead or blocked. No paid model.

**Workers:** 8 per lane to start (Beam's 6-worker setting was a 429 recovery, its 32-worker run produced 329/h), raise
to 16 only if 429s stay at zero for an hour. Keep `LANE_TAP_S=900` handling and the "429 never spends an attempt" rule.

**What must be approved**
- Claude: the `--from-chunks` / `--strict-date` patch (queue union, overlap join, no `local_file_path` requirement).
- Shivam: (a) free-only run on Go key 2 + Kilo; (b) BSE re-download of ~4,272 transcripts; (c) excluding the 1,499
  undated; (d) **keeping Flint out** — it missed the 4,500-fact depth rule and is too slow per transcript; (e) a cheap
  garbled-text readability gate (`skip_unreadable_text`) before production, since a garbled PDF produces "faithful" junk
  rows.

## 7. Exact commands

Prerequisite patch (not applied — report only): `--from-chunks`, `--strict-date`, and the overlap-aware chunk join in
`concall_deepseek.py`; default `--prompt` to `prompt_v3.md` or pass it every time. **Without the patch there is no safe
start command** — the current runner would mark every missing PDF `skip_unreadable` and drop it from all future queues.

```powershell
# 0) optional: restore the 2,289 Drive PDFs that exist (A–P, partial; does not cover the queue)
rclone copy gdrive_ro:InfoDiffusion_archive/pdfs reality_engine\data\pdfs `
  --include "*/CONCALL_TRANSCRIPT/*.pdf" --transfers 8 --checkers 8

# 1) pilot: 25 newest chunked-only docs, free, one lane (after the patch)
python -m reality_engine.scripts.concall_deepseek --model beam-free --keys OPENCODE_GO_API_KEY_2 `
  --workers 4 --prompt prompt_v3.md --all-companies --since 2016-01-01 --from-chunks --strict-date --limit 25

# 2) production lane 1 (free, Go key 2)
python -m reality_engine.scripts.concall_deepseek --model beam-free --keys OPENCODE_GO_API_KEY_2 `
  --workers 8 --prompt prompt_v3.md --all-companies --since 2016-01-01 --from-chunks --strict-date

# 3) second lane on Kilo (same model, separate gateway) — only after a host throughput check
python -m reality_engine.scripts.concall_deepseek --model reflection/beam-free `
  --keys KILO_API_KEY,KILO_API_KEY_2 --workers 8 --prompt prompt_v3.md --all-companies --since 2016-01-01 `
  --from-chunks --strict-date
```

The `--model reflection/beam-free` lane needs `concall_pilot.call_go` to choose the Kilo URL for `kilo:`-prefixed ids
(today `call_go` always posts to OpenCode Go). That is a 5-line branch; without it, add Kilo models to `FREE_MODELS` is
not enough.

```powershell
# 4) PDF side: fetch missing PDFs from BSE and record paths (no LLM), then chunk with OCR fallback
python -m reality_engine.scripts.run_annual_report_ingest --doc-type CONCALL_TRANSCRIPT `
  --download-only --workers 4 --since 2026-01-01
python -m reality_engine.scripts.run_annual_report_ingest --doc-type CONCALL_TRANSCRIPT --local-only

# 5) QA after a batch
python -m reality_engine.scripts.concall_facts_checks
python -m reality_engine.scripts.concall_deepseek_check
```

`jobs.yaml`'s `concall_extraction` (`--workers 25 --week-cap 1000`) is stale: 25 workers is above Beam's 429-safe
concurrency and the week cap is meaningless for a free model. Do not start that entry as written.

## 8. Images and charts: what each family does today

| family | non-text path in code | what happens to images/charts | measured low-text / image-only volume | free vision cost |
|---|---|---|---|---|
| Concall transcripts | `concall_deepseek.text_of` = PyMuPDF `get_text()` per page; no OCR, no vision, no page classifier. Chunking (`run_annual_report_ingest` → `PDFIngestor`) does have Marker→PyMuPDF→RapidOCR fallback, but the extractor never sees OCR text | image-only or garbled pages become empty/garbled text; <4,000 chars → `skip_cover_letter`; garbled text can pass the verbatim gate (CCL 19444) | no local PDFs, so page-level audit impossible. 15,618 chunked docs: 2,366 with <2k chars, 405 2–10k, 506 10–25k, 12,341 ≥25k. Cover letters 2,297. Known garble: 1 of a 197-doc tranche (~0.5%) → order 10² not 10³ in the remaining queue | unmeasured; ~2–3k pages if 0.5% garble holds; <1 h at deck rates |
| Annual reports | `ingest_annual_reports` line 490 `page.get_text()` only; `no_text` status if no text pages; PUA-poison guard catches one encoding class | scanned/image pages are dropped or stored empty; charts/tables inside images never read; 70 FY26 reports carry mis-encoded font layers not caught by the PUA guard | 33,268 done; **60 `no_text`**, 10 partial, 4 unreadable; **700 reports with <50% text pages** = 86,053 pages of which only 12,532 have text → **~73.5k image-only pages**; FY26: 110 reports <50%, 65 <20% | Dots 7.8 s/page, free; 73.5k pages ≈ 8 h at ~10k pages/h; +70 garbled FY26 reports (~7k pages) ≈ 1 h |
| Investor decks | `extract_deck_figures.py`: render every kept page to JPEG (1600 px) and send to a vision model with the page's text layer as digit reference; skip only no-number/no-image pages | **image-aware already**: charts and slide tables are read by a vision model; 13.57M facts, chart-trend table exists | 815,837 pages: 627,251 ok, 188,586 skipped; 132,007 pages <100 chars text; 107,436 low-text with image coverage ≥0.3; 44,838 low-text pages have a vision output; 62,598 low-text image-heavy pages have none (mostly skipped); 83,027 ok pages yielded zero facts | measured 7.8–7.9 s/page (Dots, free), 13.1 s (LongCat, now dead), 0 USD; ~10k pages/h sustained (239,757 pages on 2026-10-10); Dots on 2 Kilo accounts is the only live free vision reader |
| PIB releases | `pib_feed.py` parses HTML body text into `pib_releases`/`raw_documents`; no PDF, OCR or vision | charts/annexure images in press releases are not stored at all; 11,343 English releases have empty bodies (no text, not chunked) | 11,690 PIB_Press_Release docs, 23,737 chunks, 44.7M chars; regional 8,816 rows, 0 chunked | no image path exists; a chart pass would first have to fetch/store the original PDFs |
| RBI / Budget / macro | `fetch_macro_docs` stores PDFs; ingestion via `PDFIngestor` (Marker layout → PyMuPDF → RapidOCR DirectML fallback if the layer is scanned/PUA-poisoned) | text is extracted, but charts and scanned annexures depend on the OCR fallback; no vision model | Economic Survey 19 docs/8,110 chunks; Union Budget 35/1,831; RBI Monetary Policy 135 docs but only 63 chunked (72 never parsed); RBI MPC Minutes 47/24; RBI Annual Report 17/319. 95 RBI/macro docs unchunked in total | not measured: no page counts in the DB; a page-count pass is the first step. Budget/Survey PDFs are page-heavy, so a full vision pass would be the largest job of the five |

Net: **decks are the only family already image-aware.** Concalls are text-layer-only (and their extractor does not even
use the chunker's OCR). Annual reports are text-layer-only with a separate manual OCR/reread tool
(`ar_ocr_reread.py`, RapidOCR, built for the 111 garbled reports), not a production path. PIB has no image path. Macro
has OCR, not vision.

A chart-aware pass on free readers is feasible at zero model cost on Dots (7.8 s/page, ~10k pages/h observed), but it
is a **throughput** decision: ~73.5k AR image-only pages + ~63k deck low-text pages with no vision output (mostly pages
the router skipped, so a subset really needs a read) + macro pages of unknown size. Concalls need the cheapest version
first: a readability/garble gate on the extracted text (a dictionary token-rate check already exists in
`ar_queue.page_kind`) before any vision spend.

## 9. What I did not do / caveats

- No bulk extraction, no concall transcript read. The only LLM work was 18 one-line route probes and the approved free
  reader-admission gates (Flint completed 110 pieces; Nemotron Nano was stopped after repeated upstream 502s).
- The Zen CLI could not be started under the workstation file sandbox (it writes its own log outside the workspace); the
  direct Zen call returned the expected 403. Zen remains untestable here and is off by policy (`ZEN_BLOCKED=True`).
- The Drive transcript count is from `rclone lsf` and is a hard ceiling only for what is on Drive **today**; it is not a
  census of the archive (the PC copy is offline, and the upload was incomplete).
- Concall low-text volume cannot be measured page-by-page because no concall PDFs are local; the chunk-char distribution
  and the CCL garble case are proxies, not a census.
- The 25/25 gate is an AR-document gate; Beam's concall-specific evidence is the 25-transcript bench plus blind reviews.
  Flint's gate measures quality on AR pieces, not concall speed.

**Artifacts:** `tasks/concall_reader_probe_2026-10-24.json` (raw probe rows),
`tasks/concall_transcripts_on_drive_2026-10-24.txt` (2,289 Drive paths),
`reality_engine/data/ar_queue/t-readiness-flint-1024/SCORE.md` (25/25, 0.2%, 3,712 facts),
`reality_engine/data/logs/concall_deepseek.log`.
