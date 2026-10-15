# Annual-report reading: contingency if LongCat (Go) stops being free

Written 2026-10-14 02:45 (Shivam: "we absolutely need a contingency plan"). Numbers from `ar_facts.db` and the run logs.

## Exposure

| Reader | Pages/min (10-13 14:00-24:00) | Durable? |
|---|---|---|
| LongCat, Go x2 accounts | 421 | No: "free, limited time" promo (Go docs) |
| Gemma 4 26B, 30 Google projects | 130 | Yes (Gemma is free-tier only; no paid tier exists) |
| Gemma 4 31B, 30 Google projects | 57 | Yes |
| Flash-Lite 3.5 / 3.1 | 33 / 21 | Yes, 500 calls/day per project each |
| Zen (Cat Jam, Big Pickle, Muse, ...) | ~5 averaged (one ~6.5k-page burst after 05:30 IST) | Promo models |
| Cat Jam, Go x2 | unknown: 40k pages in 80 min, then an upstream quota cut both accounts at 01:56:53 | Promo |

Left at 02:45: ~27.1k reports, ~3.5M pages after the year-over-year skip. With LongCat ~4 days; without ~10 days.
Left by fiscal year: FY2019 1,314 · FY2020 3,790 · FY2021 3,946 · FY2022 4,123 · FY2023 4,252 · FY2024 4,319 ·
FY2025 4,511 · FY2026 863. The newest-first and oldest-first routes have already cleared most of FY2026 and FY2019,
so what is left is the proof window itself; reordering gains little (pushing FY2019 last moves ~4% of the work).

## Trigger (how we know)

- Main run log: `longcat-2.5-preview-free ... rate-limited; benched` repeating for > 1 h, or HTTP 402/403 for LongCat.
- `new_reader_check.py` (every 2 h): LongCat gone from the Go free list.
- Either one appears in the watchdog report that every Claude session sees.

## Levers, biggest first

1. **CPU-first reading for what remains** (biggest; ~3x fewer LLM pages). Statements come from `results_xbrl.db`; CPU
   parses tables and keeps those that validate; only new prose (year-over-year diff) and failing tables go to a free
   LLM. Measured 2026-10-11: LLM share ~28% of characters. Cost: build steps 5-6 of the AR build plan in STATE.md, and
   CPU rows were ~74% fully right against a 90% target (row clean-up to-do 3). Decide before LongCat ends whether the
   quality trade is acceptable for the leftover reports.
2. **More Google projects** (Shivam testing 2026-10-14). ~8 pages/min per project across Gemma 26B, Gemma 31B and
   Flash-Lite; 30 more = ~+240 pages/min. Risk: Google APIs ToS 2d ("will not attempt to circumvent ... limitations");
   a suspension could hit the existing 30 keys too.
3. **Cat Jam** once its quota window is known (watch running). Then new free models: the 2-hourly check
   (`new_reader_check.py`) auto-tests new Zen models (CLI) and, since 2026-10-14 03:00, new Go free models through the
   Go API (run `t-go-<model>-<mmdd>`, 4 workers); a Go pass joins the main run at 32 slots per Go account and the main
   run restarts. Kilo additions are reported only. CPU-first build (lever 1): parked by Shivam 2026-10-14.
4. **Paid fallback, only with Shivam's go-ahead**: a Haiku 5.5 batch for the remainder (keep each request under 100K
   tokens: 5x price above); estimate before running.

## Not worth it

- More slots on Gemma/Flash-Lite (paced by tokens/min, Google's serving speed or daily caps), more Zen slots (one
  daily allowance), more Kilo keys (one shared quota per model).
