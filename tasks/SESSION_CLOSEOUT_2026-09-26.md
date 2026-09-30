# Session Closeout — 2026-09-26 (self-contained; new session starts here)

> Prior session carried 7.8M+ tokens that will NOT transfer. Everything below re-probed at closeout time
> (2026-09-26T06:28:21 UTC live reads) unless marked as cited history. Trust this + `tasks/verification_evening_2026-09-25.md`
> (§§0–7) + `tasks/desk_drain_progress_2026-09-25.md` (§8); distrust unwritten memory.
> Goal stays ACTIVE — this doc preserves state, it does not satisfy acceptance criteria. Never call `goal complete` on it.

## 1. Objective (user-stated)

Cause→effect model: why prices moved, residual = mispricing → cash BUY/SELL/HOLD maximizing return on capital.
Prop-desk frame: CEO of a long-short hedge opening a Mumbai proprietary desk on Indian equities, initial capital
**₹10cr cash Oct 2021**, may hold cash/gold/silver up to 40% when not ROI-positive; maximize capital + return with
minimal drawdown, net of taxes (STCG/LTCG + STT + harvesting), impact cost and charges, with wide-margin alpha.
Goal-mode objective (binding): persistent data-pipeline + continuous-evaluation loop — drain document-ingest backlog
to **0 pending rows** and grow an audited track record where BUY/SELL beat their universe index by **≥500bps net of
50bps** on 30/90/180/365-day horizons across nifty50/midcap150/smallcap250/microcap250, weekly cohorts, calibration
apply-gate respected. CEO verdict (unchanged): **paper only — NO live edge, nothing promotes** until a leg clears the
full bar (§4). Prior SIP frame (₹1L 2021-10-27 + ₹50k/mo → ₹30.5L in; benchmark post-tax XIRR 7.06%) remains the yardstick.

## 2. Live processes (re-probed at close; AMBIGUOUS — read carefully)

| Process | State at close | Flags / notes |
|---|---|---|
| `embed-server` | proc `exited` up 8h12m, persistent+detached — BUT `/health → 200 {"status":"ok"}` at 06:26 UTC | Hub state stale (seen before: OS `llama-server.exe` alive + LISTENING while hub says exited). Re-probe TCP + `/health` first; restart ONLY via hub persist+detached if truly down. Vulkan-only :8099, bge-small q8_0. |
| `drain-annual-all-resume` | proc `exited` up 8h14m, persistent+detached (was pid 14804 → pid 3740 after mode flip; running [68/23775] at last tail) | May have finished or been reaped; queue log shows no new stage line after 03:34 UTC, only hourly lock-skips 04:40–11:40. |
| Hourly `RealityEngine-AnnualDrain` | Ready, hourly, last result 0; VBS restored (1-line launcher), task runs `run_annual_drain.cmd` (`--only annual_n200 --batch 10`, GPU_DUTY 0.90/VULKAN_BATCH 96) | Ticks skip on queue lock by design. ONSTART embed+drain tasks NOT registered (needs ELEVATED) — open. |
| Other supervised | All exited (concall-n200-persist 7h28m, smokes, panel-10, concall-n50, chunk-index-rebuild, annual-resume-v2) | History, not live. |

Writer-state ambiguity (do NOT assume free): WAL 0.011 GB age ~11–45s (young = writes seconds ago) vs lock age
~999–1098s (~17–18 min) vs proc all-exited vs hourly 11:40 lock-skip vs ingest tail alive ([517–518/23712] ABREL +
`database is locked` warnings 11:18/11:38). Either an untracked writer is mid-batch or tails are settling.
**Next session's first job: re-prove writer (proc + tasklist + WAL/lock ages ×2 + tail movement + :8099 health)
before any DDL, stage launch, quarantine, trigger, or index work.**
Recreate with: embed via hub (persist+detached, probe `/health`); drain via `run_ingestion_queue --only <stage>`
persist+detached, one writer at a time. Never co-run GPU/DB jobs. Never launch a duplicate while lock held
(it just `skipping overlapping invocation` — or worse, contends).

## 3. Environment / settings orders executed (with file refs + log proof)

- Env pins (queue log verified each stage): `GPU_DUTY=0.90 VULKAN_BATCH=96 EMBED_BACKEND=vulkan
  EMBED_SERVER=http://127.0.0.1:8099`. Single SQLite writer + `ingestion_queue.lock` (msvcrt); hourly ticks skip on lock.
- `reality_engine/config.py:305`: `cache_size -64000 → -256000` (manager sessions confirm −256000/180000/WAL/mmap-1GB;
  bare-`sqlite3` probes showing −2000/5000 are invalid — they never apply `SQLITE_PRAGMAS`). Busy_timeout already
  180000. Running drain keeps startup pragmas; new connections pick up the bump. No restart forced.
- DB tuning applied live (tuner exit 0, 1,040s, sole writer): 5/5 indexes verbatim in `sqlite_master`
  (`idx_docchunks_symbol_chunk`, partial `idx_docchunks_noindustry`, `idx_corpdocs_pending`,
  `idx_portfolio_open_sym`, `idx_rawdoc_type_pub`).
- Event-date/version migration complete: columns on all 3 tables (chunks 18 / corp 17 / raw 15 cols), backfill
  1,766,186 rows, still_null 0; triggers DROP+CREATEd to honest-NULL (verified: zero `date('now')` in trigger bodies,
  `'unknown'` fallback; 12/12 `test_event_version` green on temp DBs).
- Poison quarantine applied live (row id=5880 → `is_processed=2`, exactly 1 sentinel corpus-wide) + `CANDIDATE_SQL`
  carries `AND COALESCE(cd.is_processed,0)<>2` (symbol + n200/n50 guards intact, 4 placeholders, py_compile clean).
  `annual_n200` exit=0 with 0 rows after — the 20×/478s `no_chunks` burn did not return.
- PUA root fix applied live: `document_parser.py` (+35 additive: `PUA_POISON_THRESHOLD=0.5`, `pua_rate`,
  `is_pua_poisoned`) + `pdf_ingestor.py` (+134/−7: OCR reroute, pdfplumber guard, `no_text_layer` status);
  `test_pua_fallback.py` 4/4 green live; `no_text_layer` firing in production (SHYAMMETL/SJVN/SONATSOFTW lines).
  Post-drain re-run still queued (applied mid-writer).
- Watchdog hardening shipped in worktree (untracked): `run_ingestion_queue.py` fail-fast (env-gated, default OFF,
  break at 3 consecutive) + nonzero wrapper (`QUEUE_INCOMPLETE` return 1 — overnight logs prove it: hourly
  `annual_n200` failures now read ERROR not QUEUE_COMPLETE). `run_hidden.vbs` restored (was 0 bytes); task Ready.
  ONSTART registration + fail-fast enablement + queue-unit test still open (needs ELEVATED + post-drain window).
- Test hygiene: `test_horizon_excess.py:663` with-open fix, 37/37 @4.8s. 5-file gate re-targeted to promotion math.
- User orders honored: Bitdefender exclusions done (AV stopped blocking); session-bound runners flipped to
  persist+detached before close (mode flip restarts once — new pid, uptime reset — expected, not failure).

## 4. Book state + revocations (promotion bar in full)

Book (06:28 UTC): 681 closed / 160 open; closed BUY 58 / HOLD 615 / SELL 8; open BUY 107 / HOLD 52 / SELL 1.
EOD max 2026-09-24. Live ledger (`portfolio-ledger`, exit 0): N50 n=14 −20bps hit 0.357 (4 cohorts); Midcap n=46
−335bps hit 0.043 (5 cohorts); small/micro n=0; evaluated 66, unmapped 24, uncovered 6. All horizons identical per
universe (T9 realized-window diagnostic). Calibration (`run-calibration`, exit 0): folds 3, decided 3, improved 1,
`recommend_apply=false` — healthy refusal, not failure.
Promotion bar (per horizon, all required): cohort-clustered mean ≥+500bps net of measured costs; ≥30 weekly cohorts
(≥13 for 20D); hit-rate CI lower >0.5 (cluster-robust); same sign in both regimes; shuffle-entry placebo ≈0 (|≤100bps).
REVOKED (never regress, never re-quote as edge): SELL +527bps (closes: −20bps — artifact of long-framed terms +
stop-as-gain); blended +29.8 profit (entirely the SELL artifact); T10 confirmation filter (1W/29L, hit 0.03);
T11 trend entry (6/34). Proven in `tasks/strategy_tracker.md` (T4/T5 rows + promotion log) +
`tasks/next_wave_plan_2026-09-23.md` §2A + `tasks/test_findings_2026-09-24.md`.

## 5. Strategies / tests (verdicts, no re-runs)

- T1–T12 tracker stands: 5 method passes (T2/T3/T7/T8/T9), 1 infra verdict (T12 KEEP bge-small), 1 inconclusive (T6),
  4 dead/revoked P&L claims (T1/T4/T5/T10/T11). Zero promotable legs.
- F1 forensic-avoidance (`tasks/desk_f1_screen_2026-09-25.md`): **KILL, terminal — adverse sign.** All 16 cells
  negative (−129 to −11,559bps); cohorts 4; regimes untestable (uptrend 0); placebo −183 to −26,702bps; hit-lo max
  0.292. 0/5. No threshold re-tuning, no same-design rerun; only pre-registered follow-ups (quarterly cadence,
  BUY-overlay, robust estimator) stay valid.
- F2 continuation-momentum (`tasks/desk_f2_grid_2026-09-25.md`): **KILL, no k-tuning.** 12,502 entries / 257 weeks /
  21,190 legs. 30D net-tax N50 10.1 / Mid 73.8 / Small 3.3 / Micro 978.0 (only Micro ≥500, voided by placebo 3,166bps
  + hit-lo 0.480 + late-sample coverage). Placebo fails everywhere (|74–40,379|bps, exceeds real in 15/16 cells).
  Midcap 90/180/365 = single-name unadjusted corporate-action jumps (SWANDEF +78,237%) — void, not edge.
  Reopen needs a new pre-registration (split-adjusted prices + matched-volatility placebo), never a silent re-run.
- Suites: 5-file promotion-math gate 5/5 green serial ~13s (horizon 37+4sub ~4.2s, sip 17 ~1.6s, ledger 29+2sub ~4.0s,
  event 12 ~2.3s, desk 33 ~0.9s) — stamped in `tasks/verification_evening_2026-09-25.md` (0/5 met). Full suite 738
  green per 2026-09-22 baseline (199.65s xdist = 1.3× contention-bound; ~270s serial; exit-5 = environmental).
  Shard A (36 mods ~136s) + Shard B (38 mods) plan + bootstrap ~60s anchor recorded in tech pipeline. Full shards
  stay post-drain only, never beside the writer.

## 6. Numbers + disk map + verify commands (live at close)

- chunks **1,994,571** (NULL-content 0 at last audit; event NULLs 0 at migrate; re-probe next session); corp 103,631:
  pending OTHER 37,150 / ANNUAL **25,294** / ANNOUNCE 16,085 / CONCALL 9,140 / FINRES 2,707 / INVPRES 585
  (total pending 91,961; processed ~11,669; sentinel exactly 1). Drain trajectory: ANNUAL 26,262→25,294 (−968);
  chunks 1,685,464→1,994,571 (+309k). Index marker STALE: rows 1,398,908 / source 1,642,865 (built 09-24) vs live
  ~1.99M (drift ~350k) — `refresh` queued post-drain, expect `source_chunks_at_build == COUNT(document_chunks)`.
- DB 32.812 GB; WAL 0.011 GB (young — see §2 ambiguity); lock ~18 min. Disk 445.5 free / 804.4 GB total.
- Disk map (`reality_engine/data`, measured): **pdfs 66.42 GB / 17,881 files** (downloaded filings — the weight);
  DB 32.81 GB (1.99M chunks content+embedding JSON + FTS5 + indexes + 3.1M price rows); models 8.19 GB (bonsai 7.1 +
  gguf); lancedb 3.23 GB (4 near-duplicate copies: json 492MB + f32 169MB + npy 113MB + meta 230MB + tmp);
  vector_index 2.16 GB (npy 2.15 GB, rebuildable ~17 min); snapshots ~4.9 GB (post_bse 2.18 + pre_substrate 1.69 +
  pre_dedup 1.03 — reclaim candidates, NOT deleted); bhavcopy 0.44 GB / 1,600 CSVs; inbox 0.27; logs 0.07;
  reports 0.01; macro_pdfs 0.09. Growth driver = filings (full 93k drain ≈ tens of GB more); structural waste =
  triple-stored embeddings (SQLite TEXT + LanceDB + npy) + snapshots. Guard enforces 20 GB free at checkpoints only.
- Verify commands (scope = claim scope):
  `python reality_engine/cli.py portfolio-ledger --horizons 30,90,180,365 --universes nifty50,midcap150,smallcap250,microcap250`
  · `python reality_engine/cli.py run-calibration`
  · read-only sqlite: `max(daily_price_delivery.date)`, `portfolio_actions` status/action splits,
  `count(document_chunks)`, `corporate_documents ... group by doc_type/is_processed`, `PRAGMA table_info` +
  trigger bodies in `sqlite_master`
  · `python reality_engine/scripts/migrate_event_version.py --db <DB> --dry-run` (lock-free audit)
  · 5-file gate serially (never beside writer); shards A/B post-drain only.

## 7. Open items + next actions + ruled decisions

Ordered (each step speeds the next; single writer throughout): 1) re-probe writer (§2) → 2) resume `annual_all`
(resumable at next CANDIDATE_SQL row) → `concall_all` → `refresh` → `business_map --top-k 20`, one at a time →
3) PUA post-drain re-run → 4) calibration re-run post-P0b (≥2 lenses voting) → 5) F1/F2 pre-registered follow-ups only
→ 6) slippage audit + universe-map fix → 7) ONSTART registration (ELEVATED) + fail-fast enablement + queue-unit test
→ 8) 5-file wall re-stamp + full shards → 9) versioning triage (8 owned files ONLY, never `git add -A`) → 10) dedup
(lancedb canonize + sha-skip) + reclaim (snapshots/npy, owner-confirmed).
Waiting predicates: drain exit + lock free + explicit go for every write (migration/index/quarantine/rebuild);
EOD beyond 2026-09-24 for forward resolution; ≥30 weekly cohorts + positive edge for any promotion.
Ruled (decided, not open): paper-only until the bar; poison quarantine applied; bulk-HELD cleared after event cols;
untracked ≠ illegitimate (232-file index is partial — judge by live proof); bare-sqlite PRAGMA probes invalid (use
manager); trigger `date('now')` banned; CANDIDATE_SQL needs `<>2` + 4 placeholders; no denylist edits
(`db/repository.py`, `db/schema.sql`); no live-row deletes; no `git stash` (shared); no full suites beside writer;
fiscal-only batches may flow; tech edits judged by `py_compile` + scoped green, versioning is owner's post-drain call.
Todos persisted: 9/17 done, 8 open (Drain backlog; TrackRecord ×2; Calibration shards; TechAccel watchdog/rebuild/
dedup/PUA-rerun). Goal ACTIVE.

## Scars (repo-specific invariants)

Queue lock is the only writer mutex (msvcrt, auto-releases on crash — hourly ticks rely on it); wrapper exit codes
are load-bearing (0 = all stages 0, else `QUEUE_INCOMPLETE` = 1); stage subprocesses import code fresh per doc (no
mid-drain file edits to imported modules); triggers fire on every insert (fix only via migrate script holding lock);
`is_processed=2` is meaningless without the `<>2` predicate + covering index shipped atomically; PUA-rate ≥0.5 →
OCR reroute, `no_text_layer` ≠ `no_chunks`; sha256 dedup fires post-download (pre-download skip impossible without
ETag memoization); xdist `-n 12` is ~1.3× (DirectML sequential) — serial shards are the fast path; hub proc state
goes stale (OS tasklist + socket + WAL/lock ages are ground truth); mode flip restarts a service (new pid — expected).
