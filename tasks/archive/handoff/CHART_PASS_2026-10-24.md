# Chart/image-aware vision pass — handoff (2026-10-24/25)

Owner: Shivam · Builder: DeepSeek · Reviewer: Claude. Status: **code + gate done; bulk NOT started**
(worktree sandbox is read-only for the live DBs, so the run must start from the main checkout).

## What is built

| file | purpose |
|---|---|
| `reality_engine/scripts/extract_ar_vision.py` | The pass. Reuses the deck reader path (`extract_deck_figures`: page gate, renderer, reader configs, adaptive limiters, 429 handling, `metric \| period \| number \| unit` parser) and adds AR storage + deck leftovers. |
| `reality_engine/scripts/run_chart_pass.cmd` | One-command resumable launcher: AR FY26 → deck leftovers → older AR, 4,000 pages per pass, loops until all three report 0. |
| `reality_engine/tests/test_extract_ar_vision.py` | 22 offline tests (routing, garbled detection, parsing, storage/resume, 3-strike culls, queue selection, path/fetch, lock). All pass. |
| `.gitignore` | Ignores `reality_engine/data/chart_gate*/`, `chart_pdfs/`, local sandbox scratch. |

AR output is additive only: four new tables in `ar_facts.db` —
`ar_vision_pages`, `ar_vision_outputs`, `ar_vision_facts`, `ar_vision_chart_trends` — each carrying
`doc_id, page_no, isin, symbol, fiscal_year, known_at` (plus `ar_vision_docs` for the garbled-scan cache).
The AR text tables are never touched. Deck leftovers are written into the existing
`deck_figures.db` tables under prompt version `leftover-<hash>`, plus `leftover_attempts` for the page cull.

Readers: dots-3 free only (`dots-studio/dots-3-note-preview:free` on Kilo key 1 and key 2, and
`dots-3@openrouter`), 30+30+4 in flight. A reader is benched 30 min after three consecutive failures;
a page is final after three failed attempts.

Page selection:
- AR: reports with text on < 50% of pages (the ~700 / 86k set), newest filing first; plus a one-time
  sampled scan of FY26 dense-text reports for mis-encoded font layers (caches `garbled=1` in
  `ar_vision_docs`, no hand-maintained 70-list). A page is read when its text layer is unusable/sparse,
  it is image-heavy, and (when RapidOCR is available) the image has >= 2 numbers. If RapidOCR is
  absent the page is read rather than silently skipped.
- Decks: pages the first pass skipped with `text_chars < 100`, `img_cov >= 0.5` and no output at all,
  newest deck first. Deck PDFs are fetched from `gdrive:InfoDiffusion_archive/decks` on demand and
  deleted after their pages are read; older AR PDFs likewise from `pdfs`/`D_pdfs`.

## Gate results (step 5)

Run: `reality_engine/data/chart_gate/20261025_002910/` (report + 30 page PNGs + raw answers;
ignored by git, on disk). 30 low-text pages from 10 FY26 reports, **same reader, two prompts**
(A = deck-style, B = table-first + CHART lines), dots-3 free, 12 workers.

| prompt | answered | facts | identifiable | cross-prompt agreement | median |
|---|---|---|---|---|---|
| A | 28/30 | 278 | 80.2% | 86.0% | 4.6 s |
| B | 28/30 | 270 | 95.9% | 89.8% | 5.8 s |

**Manual spot-check of 10 pages** (prompt A, against the rendered PNGs; full table in
`reality_engine/data/chart_gate/20261025_000502/manual_check.md`):
**241 rows, 228 correct = 94.6%**; excluding the 8 registration/DIN rows the prompt says to skip,
**228/233 = 97.9% of business-value rows**. Clean pages (P&L, cash-flow, ratios, fixed assets) were
value-perfect; the two failure modes were faint scans (KGDENIM: 4 decimal/scale misreads in 54 rows)
and signature pages (registration/DIN numbers still emitted). Prompt A is the production prompt:
prompt B found more numbers on the ratio page but shifted the table columns into `metric`/`unit`.
RapidOCR is **not installed** in this worktree, so the automated page-reference column is empty; the
manual PNG check is the precision evidence. Install `rapidocr-onnxruntime` (optional requirements)
to restore the automated check and the OCR number gate.

## Queue sizes (measured 2026-10-25, `--queue`)

| queue | docs | pages | image-only |
|---|---|---|---|
| AR FY26 (< 50% text) | 128 | 17,568 | 14,986 |
| AR older (< 50% text) | 572 | 68,485 | 58,535 |
| FY26 dense-text reports to garbled-scan | 4,988 | — | — |
| Deck leftovers (strict: text_chars<100, img_cov>=0.5) | — | **60,059** | — |
| Deck leftovers (looser: text_chars<200, img_cov>=0.15) | — | 86,151 | — |

The brief's 62,598 is between the two deck cutoffs (different snapshot/cutoff); both thresholds are
arguments in `load_deck_pages`, so Claude can pick the exact class.

## Pages/hour

Measured in a one-document smoke (80 pages, 49 reader pages, 64 requests in flight):
**1.2-2.1 pages/s = ~4,300-7,700 pages/h**, gate median 4.6-5.8 s/call. Expect **6,000-9,000 pages/h**
on the main checkout with all three free readers healthy; with RapidOCR installed the serial OCR gate
(~0.4-0.5 s/page) is the floor at ~7-9k/h, without it there is no OCR cost but more low-text pages
are read. A 4,000-page pass is roughly 30-50 minutes plus deck downloads.

## Facts written

Bulk: **0** (not started, per the read-only constraint). The gate wrote no DB rows. The one-doc smoke
wrote 896 facts to a throwaway `reality_engine/data/chart_smoke2.db` (deleted); it is not production.

## Open problems / must verify before the bulk run

1. **Run from the main checkout.** The worktree sandbox cannot write `ar_facts.db` / `deck_figures.db`
   or `reality_engine/data`; the live run must start after merging. `REALITY_DATA_ROOT` must point at
   the live data dir (or be unset, which defaults to `reality_engine/data`).
2. **Readers alive.** Probe Kilo 1/2 and OpenRouter dots-3 with one image before leaving it overnight;
   the script culls a reader after 3 consecutive failures but does not recover it before 30 min.
3. **rclone.** `gdrive:` remote must be configured for the main-checkout user; deck and older-AR
   fetches use `rclone copyto`. Check `rclone lsf gdrive:InfoDiffusion_archive/decks` and
   `.../pdfs`. Downloads go to `reality_engine/data/chart_pdfs/` and older AR/deck copies are deleted
   after their pages are read (FY26 AR is never copied).
4. **Single writer.** The AR ingest and deck extractor are stopped today. The launcher takes
   `reality_engine/data/logs/chart_pass.lock`; a second instance exits 2. If a stale lock remains,
   delete it only after checking the PID.
5. **Disk.** `chart_pdfs` needs headroom for the largest deck/AR batch; 4,000 pages per pass keeps it
   bounded, but monitor C: (141 GB free at build time).
6. **Garbled scan cost.** The first FY26 pass samples 4 pages of 4,988 dense-text reports (~20-40 min)
   before reading; it is cached in `ar_vision_docs` and is not repeated. `--no-garbled-scan` skips it
   (the 70 mis-encoded reports are then missed until the scan runs).
7. **Inline renderer.** The launcher uses `--inline-render` because the worktree sandbox blocks
   `ProcessPoolExecutor` named pipes. A MuPDF crash is handled by the `chart_pass.current` marker +
   `bad_docs` strikes (2 strikes = skip). The default pool path is still available on the main
   checkout without `--inline-render` if crash isolation is preferred.
8. **Deck fetch assumption.** `deck_sources.local_path` must contain a `decks\<bse|nse>\...` path;
   `drive_rel` maps it to `decks/<rel>`. Pages from `corporate_documents` fall back to the live
   `local_file_path`. Decks not on Drive are skipped and counted in the log.
9. **Existing deck tests** (`test_extract_deck_figures`) fail in this sandbox only because
   `tempfile.TemporaryDirectory` cannot write under the confined ACL; the new 22 tests pass.

## Exact launcher command

From the main checkout, after merge (one command, resumable, loops until done):

```bat
reality_engine\scripts\run_chart_pass.cmd
```

Background variant (returns immediately):

```bat
start "" /b cmd /c reality_engine\scripts\run_chart_pass.cmd
```

Logs:
- `reality_engine/data/logs/chart_pass_run.log` — stdout/stderr of every pass
- `reality_engine/data/logs/chart_pass.log` — progress lines (pages/s, pages/h, facts)
- `reality_engine/data/logs/chart_pass_passes.log` — one line per pass and exit code

Each loop pass runs, in order: AR FY26 4,000 pages → deck leftovers 4,000 pages → older AR 4,000 pages.
Exit 3 = did work (loop again), 0 = that target is empty, anything else = crash (retry after 60 s,
200 passes max). To resume after a stop, run the same command; finished `(doc_id, page, prompt_version)`
rows and deck `(sha256, page)` rows are skipped.

Useful pre-flight / inspection:

```bat
python -m reality_engine.scripts.extract_ar_vision --queue
python -m reality_engine.scripts.extract_ar_vision --gate 30
python -m reality_engine.scripts.extract_ar_vision --target ar --scope fy26 --limit-docs 1 --max-pages 20 --inline-render
python -m unittest reality_engine.tests.test_extract_ar_vision -v
```

Verify after the first pass:
`SELECT status, COUNT(*) FROM ar_vision_pages GROUP BY 1;`
`SELECT COUNT(*), COUNT(known_at), COUNT(isin) FROM ar_vision_facts;`
`SELECT COUNT(*) FROM ar_vision_chart_trends;`
and the deck-side `SELECT COUNT(*) FROM pages WHERE prompt_version LIKE 'leftover-%' AND status='ok';`

## Gate artifacts on disk (gitignored)

- `reality_engine/data/chart_gate/20261025_002910/` — latest 30-page × 2-prompt report + PNGs + answers
- `reality_engine/data/chart_gate/20261025_000502/manual_check.md` — 10-page manual precision table
- `reality_engine/data/chart_gate_src/` — the 12 FY26 gate PDFs copied into the worktree

## Worktree commit note

`git add` from this worktree is blocked by the sandbox (`index.lock` under the main repo's
`.git/worktrees/...` is outside the workspace). The four changed/new paths are staged by the
supervisor's auto-commit on job success:
`.gitignore`, `reality_engine/scripts/extract_ar_vision.py`,
`reality_engine/scripts/run_chart_pass.cmd`,
`reality_engine/tests/test_extract_ar_vision.py`, `tasks/handoff/CHART_PASS_2026-10-24.md`.
No DB, PDF, gate PNG or cache is tracked; those paths are gitignored.
