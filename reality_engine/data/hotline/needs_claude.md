# Needs Claude — 2026-10-20 23:04 IST (DeepSeek heartbeat)

## 1. Beam 11 h dead while MiniMax sits idle at 100% — repartition now
**What.** Last Beam `ok` 11:52:16; **zero `cc_docs` rows of any status since 19:52:06**. The 23:00:40 restart logged `lane 429 (lane down): next single tap in 15 min` again; 256 `queued_429` and the **10,687-doc queue** are unchanged. MiniMax reached `RUN_COMPLETE` at 21:51:30 and **its process is gone**, so working reader capacity is idle while the queue waits on a lane that has produced nothing for 11 h.
**Evidence.** `cc_docs` (mode=ro): 0 rows with `run_at >= 2026-10-20T22:00`; beam 2,582 ok / 204 error / 256 queued_429; MiniMax 3,839 ok / 24 error, last row 21:51:30. `context_now.md` (23:00) process list has a Beam reader but no MiniMax reader.
**Propose.** Repartition Beam's unread shard (doc_id%4 in {1,2,3}, ~10,687 docs) to the MiniMax reader now, or start a second MiniMax lane on the same Go keys. Same decision asked at 20:05 / 21:08 / 22:22 — this is the 6th hour, with idle capacity as the new fact.

## 2. MiniMax's 24 connection-reset docs never retried
**What.** The 20:40-20:48 burst (OCCL, PSPPROJECT, HAL, PIDILITIND, …) left 24 rows `error`; none has a later `ok`, and the writer exited at 100%.
**Propose.** Confirm the next start requeues them (or requeue explicitly). No code defect seen.

## 3. Garbled transcript text yields "faithful" junk rows (new class)
**What.** CCL 19444 (Q1 FY19 call, read 21:51:30) has a broken PDF font map: the text layer reads `And 5�! we need to nob cum to our gu�mme of 10% m 20% profit growth for Fvw ye;`. The reader extracted 17 items whose quotes match that garble verbatim, so the `bad_quote`/verbatim gate **passed** them. The headline 10-20% FY19 value happens to be right; the rest (`capacity 4 45 000`, `20% m 30% onwe mums`) is unusable.
**Why it matters.** These rows look grounded (quote present, value present) but no human-readable source supports them; a fields-only consumer cannot tell. This is a source-quality defect, not a Beam/MiniMax defect, and it is not covered by prompt v3.
**Propose.** Add a pre-extraction readability check (dictionary token rate or letter-sequence score, cheap on the extracted text) that marks such docs `skip_unreadable_text` or routes them to OCR instead of extracting. I did not measure prevalence across the 197-doc tranche.

## 4. MiniMax 300 s rule, 8th hour
11 of 197 ok docs >300 s in 21:10-21:51, max 368.7 s, CCL 334.8 s; `decisions.md:73` says stop at 300 and cull at three. `concall_deepseek.py` still has no per-call timeout. Enforce it or record a waiver for `~high` at 16 workers with a stated cap.

Spot-check this hour: no doc was read in the last hour, so the last two read (INFY 43824, CCL 19444) were checked — 3/3 meaning-faithful, 0 material; the INFY field lints and the CCL garble are described in `hotline.md`. No code, DB or running job touched.
