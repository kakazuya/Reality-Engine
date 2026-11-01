# Task: can we restart concall fact extraction on free readers? (readiness check, no bulk run)

Owner: Shivam (2026-10-24): "For concalls I don't just need chunking, I need extracted facts going into the database.
We were using BEAM, MiniMax and LongCat 2.5 free on Go keys to extract. Is it possible again? Go key 1 will likely
return 401/400 as that subscription is gone." Reviewer: Claude. Report only; do NOT start a bulk extraction.

## Context

- Coverage audit today (`tasks/coverage/coverage_2026-10-24.json`, family 1): 21,703 concall transcripts known;
  15,617 chunked; 7,477 read into `concall_facts.db`; 6,086 filed but unchunked; 8,140 chunked but unread; 2026
  read-but-unchunked 342; 242 companies with zero chunked (DEEDEV, GVT&D, HIMATSEIDE, GODREJPROP...).
  No transcript PDFs are on this laptop (PC copies were deleted after upload to `gdrive:InfoDiffusion_archive`).
- Existing pipeline: jobs.yaml job `concall_extraction` ("2026 set complete to 2026-10-14; Go quota-bound") and the
  reader scripts behind it; STATE.md + `reality_engine/data/hotline/decisions.md` record the reader history
  ("Beam" multi-model runs 2026-10-20, 6 workers, 429 handling, 300 s/transcript cap, three-strikes cull, the
  25/25 must-find gate before a model joins the reader pool, interleaved models). Read those first.
- Keys: user env (HKCU) via `reality_engine.scripts.resource_watchdog.user_env()`; Go account 1 = `OPENCODE_GO_API_KEY`
  (expected dead), account 2 = `OPENCODE_GO_API_KEY_2`; also Zen / Kilo / Gemini keys may exist. Never print key values.
- Rules: free models only on subscriptions (no paid model without Shivam's OK); every Go call sends a stable
  `x-opencode-session` via `go_session.session_id` (never uuid4 per call); off-peak is now.

## Do

1. Find the concall reader code path and its model routes (BEAM / MiniMax / LongCat 2.5 / others) and how results land
   in `concall_facts.db` (tables, QA checks).
2. Probe each candidate route with ONE tiny request (a 1-line prompt, max_tokens ~16): Go key 1, Go key 2, and the
   free models currently listed (OpenCode Go free list, Zen, Kilo). Record HTTP status/error per key×model, latency,
   and whether the model is still free. Total probes ≤ 30.
3. Throughput plan: per working route, measured or recorded rate (transcripts/hour) and quota limits; estimate time to
   read (a) the 342 2026 read-gaps' companions, (b) 6,086 unchunked, (c) 8,140 chunked-unread. Note that unchunked ones
   first need their PDFs from Drive/BSE (check `rclone lsf gdrive:InfoDiffusion_archive` for a transcripts folder).
4. Quality: which of the working models already passed the 25/25 must-find reader gate (decisions.md); which would
   need it.
5. A recommended run plan: order (DEEDEV + 242 zero-coverage companies and 2026 first), route mix, parallel workers,
   chunk + extract in one pass where possible, and what Claude/Shivam must approve.

Final answer: the route table (key × model → status), throughput/time estimates, gate status, the run plan, and the
exact command(s) to start it. Write it also to `tasks/CONCALL_READER_READINESS_2026-10-24.md`.
