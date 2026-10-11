# Verdict (checked by Claude against the slide images)
- Unsupported numbers were all on the slides: NILAINFRA p22 "6.20/2.19" split into 52-week high/low (correct);
  ASRL p3 "two units" as 2 (correct); TEJASNET p6 "20" is the 20th-anniversary logo (junk, not a misread). No misreads.
- Gemini 3.1 Flash-Lite (reasoning none): numbers excellent (98% of Haiku's, 0 misreads) but identifiable 78.1%,
  below the ~85% bar: 232 figures without a period (Dots 58), 37 chart axis ticks kept, segment breakdowns without the
  segment name. With reasoning low: 72.2%, worse. FAILS the bar; not used as a deck reader (a second reader must beat
  the primaries, Dots 85.4% / LongCat ~85%).

## Round 2 (same 40 pages)
| reader | answered | identifiable | Haiku's numbers | unsupported | median s | free quota per project |
|---|---|---|---|---|---|---|
| Gemma 4 31B (native API, thinking minimal) | 39/40 (1 Google 500 after retries) | **86.9%** | 99% | 0 | 54 | 30/min, 16k tokens/min (~17 pages/min), 14.4k/day |
| Gemini 3.8 Flash (reasoning none) | 28/40 (20/day cap on both keys) | 80.2% | 100% | 2 (junk: "ISO 9001:2008", H2/N2/O2 subscripts) | 9 | 5/min, 20/day |
| Gemini 3.1 Flash-Lite | 40/40 | 78.1% | 98% | 0 | 6 | 15/min, 500/day |
| Dots (baseline) | 40/40 | 85.4% | 97% | 0 (the "2" is "two units") | 7 | Kilo free |
Gemma 4 31B PASSES (identifiable >= ~85%, no misreads, 97.5% answered). Its labels are at Dots' level (86.9 vs 85.4),
well below Step (96%) and Haiku (100%), so it adds capacity, not a better second opinion. Gemini 3.8 Flash fails
(80.2%) and its 20/day quota makes it useless for volume.
