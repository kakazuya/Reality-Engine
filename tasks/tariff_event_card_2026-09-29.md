# Tariff event study — frozen card (written BEFORE any returns were computed)

Question: did US tariff news move Indian listed stocks in the direction and ordering their US-goods exposure implies, and was the move complete on day 0 (efficient) or did it drift (diffusion)?

## Events (first NSE session after the documented release, IST)
| id | US-side release | IST | first session | dir |
|---|---|---|---|---|
| E1 | Liberation Day, India 26% (announced ~4pm ET Apr 2) | Apr 3 ~01:30 | 2025-04-03 | escalation |
| E2 | 90-day pause (Truth Social, Apr 9 pm ET) | Apr 9 late night | first session >= 2025-04-10 (data decides holidays) | de-escalation |
| E3 | 25% + "penalty" (Truth Social, published 12:34 UTC Jul 30 = 18:04 IST, CNBC) | Jul 30 18:04 | 2025-07-31 | escalation |
| E4 | "raise very substantially in 24 hrs" (CNBC Squawk Box 8:30 EDT Aug 5 = 18:00 IST) | Aug 5 18:00 | 2025-08-06 | escalation |
| E5 | EO 14329 signed Aug 6 (extra 25%, total 50%) | Aug 6 eve | 2025-08-07 | none expected (already priced by E4) |
| E6 | EO effective 12:01am EDT Aug 27 | Aug 27 09:31 | 2025-08-27 | none expected (priced) |
| E7 | Modi-Trump call, 18% deal + Russian-oil penalty removed (Feb 2 2026) | Feb 2 evening | 2026-02-03 | de-escalation |

Sources: KPMG India note (Sep 2025), India Briefing (Feb 2026), CNBC Jul 30 & Aug 5-6, Federal Register EO 14329, Al Jazeera/CNBC Feb 2-3 2026.
Known confound: E7 sits one session after Union Budget (Feb 1 2026).

## Groups (fixed by sector/exposure knowledge, not returns; approximate, unverified against filings)
- TARIFFED (US-heavy, not exempt: apparel/home textile, shrimp, jewellery exporter, auto components, solar): WELSPUNLIV GOKEX ICIL TRIDENT KPRMILL ARVIND HIMATSEIDE AVANTIFEED APEX VAIBHAVGBL SONACOMS BHARATFORG SANSERA SUPRAJIT SUNDRMFAST CRAFTSMAN WAAREEENER
- PHARMA (US-heavy, exempt from reciprocal tariff, 232 probe pending): SUNPHARMA DRREDDY LUPIN ZYDUSLIFE AUROPHARMA GLENMARK GRANULES TORNTPHARM ALKEM CIPLA BIOCON
- ITSERV (US-heavy services, outside goods tariffs): INFY TCS WIPRO HCLTECH TECHM LTIM COFORGE PERSISTENT MPHASIS
- EMS (smartphones, exempt): DIXON
- CONTROL: every other liquid EQ stock (median turnover >= Rs 50 lakh over last 60 sessions pre-event, traded >= 90% of them). Also serves as the market factor.

## Measurement
Daily return = close/prev_close - 1 (NSE prev_close is corporate-action adjusted; |r|>30% dropped as artifact). Market model on estimation window [-250,-21] sessions vs equal-weight CONTROL mean; need >=150 obs. Abnormal return AR. Windows: CAR[0], CAR[0,1], CAR[0,4], drift CAR[2,19], anticipation CAR[-5,-1].

## Hypotheses (directional, one primary)
PRIMARY: pooled signed CAR[0,1] of TARIFFED over E1,E2,E3,E4,E7 (sign = -1 escalation, +1 de-escalation) > 0.
SECONDARY: (a) |TARIFFED| > |PHARMA|, |ITSERV| ordering; (b) E5, E6 incremental CAR[0,1] ~ 0 (efficient) — nonzero = under-reaction/diffusion; (c) drift CAR[2,19] same sign as day-0 = diffusion; (d) anticipation CAR[-5,-1].
## Inference
Placebo: 400 random non-event dates (excluding +-25 sessions of any event) through the identical pipeline give the null distribution of group-basket CAR (absorbs sector-common shocks). Pooled null: 5000 draws of 5 placebo dates with the same sign vector. Permutation: 5000 random same-size stock groups from CONTROL. Report one-sided p vs placebo; treat p<0.05 as suggestive only (5 events, 2 seasons, not independent of one another).
## Failure = VOID
Any event where fewer than 60% of a group's names have valid data.
## Attempt ledger
Run 1 = this card unchanged. Any later change = new run, listed here.
Run 1 executed 2026-09-29 with the card unchanged. Two return-independent code fixes before the final run: price history loaded from 2021-10 (placebo pool was too small with 2024-03), control-stock regressions skipped for placebo dates. Aug 27 2025 was an NSE holiday, so E6 = 2025-08-28 by the data calendar. Results: analysis/tariff_event_study.py stdout (card sha256 1e6fb5788e5f2bc6).
