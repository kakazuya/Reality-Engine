# H02 — bulk/block deal accumulation, provisional (Stage 1)

No variant is promoted. This is the declared isolation test; Stage 2 is separate.

Run `7c7e2d58-0d88-4f42-a8a9-05d21e2e70a3`. Snapshot `truth_2026-10-19.duckdb`, read-only. Evidence 2021–2025; 2019–2020 warm-up/audit only. Runtime 72.6s.

Pre-registration: `H02_preregistration.md`, SHA256 `dc05ce89f06b748e4bb86ced770583981fc378eb2ccd0091d1b7dc44f672b4ac`. It was written before any outcome was computed.

## Declared client sets

M1 final regex: `(?:MUTUAL FUND|\bMF\b|ASSET MANAGEMENT|\bAMC\b|INSURANCE|LIFE INSURANCE|PENSION|PROVIDENT|FUND|FUNDS|CAPITAL MANAGEMENT|INVESTMENT MANAGEMENT|SOVEREIGN|GOVERNMENT OF|MONETARY AUTHORITY|NORGES|ABU DHABI|\bGIC\b|TRUST)`; exclusion `(?:SHARE BROKING|SECURITIES PRIVATE|STOCK BROKING|COMMODITIES)`.
The top-100 hit list and the fixed 2021 M2 list are in the pre-registration file.

## Mapping and dedupe

| Year | Rows | Mapped | Unmatched | Unmatched value (₹ crore) |
|---:|---:|---:|---:|---:|
| 2019 | 17525 | 17460 | 65 | 4000.1 |
| 2020 | 15008 | 14847 | 161 | 7846.8 |
| 2021 | 30462 | 30309 | 153 | 3593.9 |
| 2022 | 39058 | 38800 | 258 | 13241.8 |
| 2023 | 38000 | 37548 | 452 | 29875.9 |
| 2024 | 53385 | 52728 | 657 | 42378.6 |
| 2025 | 40977 | 40082 | 895 | 52730.4 |

Cross-exchange duplicates removed: 29; BULK/BLOCK duplicate pairs: 2267. Promoter/insider rows excluded: 4161 (807794.0 ₹ crore).

## Coverage

| Year | U1 ISINs | Deal issuers | M1 events | M1 issuers | M2 events | M2 issuers |
|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 1833 | 2217 | 244 | 188 | 191 | 117 |
| 2022 | 2004 | 2268 | 150 | 122 | 152 | 93 |
| 2023 | 2108 | 2509 | 371 | 264 | 60 | 52 |
| 2024 | 2669 | 3120 | 604 | 444 | 94 | 67 |
| 2025 | 2573 | 2853 | 448 | 338 | 35 | 28 |

`Deal issuers` counts every mapped issuer with a clean deal that year, including issuers outside U1; the U1 columns are the eligible universe and event issuers. The event counts in this table are before the U1/price gates, so they differ from the variant counts below.

## Four confirmatory tests

Mean event excess is after 30 bp and sell-date tax, minus after-tax/cost B5. Cluster t uses entry-month clusters; BH q pools all prior ledger tests.

| Definition | Days | Events | Issuers | Mean excess | Median | t | p | HAC p | BH q | Date placebo p | Label placebo p | Max-T p | Years |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| M1 | 20 | 1329 | 683 | -0.32% | -0.87% | -0.6723 | 0.504 | 0.4847 | 0.8978 | 0.874 | 1 | 1 | -/+/+/+/- |
| M1 | 60 | 1281 | 663 | -0.01% | -1.61% | -0.009956 | 0.9921 | 0.6052 | 1 | 0.396 | 1 | 1 | -/+/-/+/- |
| M2 | 20 | 241 | 144 | -4.91% | -7.86% | -3.064 | 0.003544 | 0.0003281 | 0.05055 | 0.99 | 0.012 | 0.99 | -/-/-/-/+ |
| M2 | 60 | 240 | 144 | -6.68% | -12.58% | -2.163 | 0.03559 | 0.07029 | 0.1979 | 0.998 | 0.138 | 1 | -/-/-/-/- |

HAC p uses equal-weight observed monthly cohorts and a Bartlett Newey-West SE with ceil(horizon/21) calendar-month lags; missing months are not imputed to zero. It is reported alongside the entry-month cluster p, not substituted for it. M2's small p is on a negative mean: it is evidence of underperformance, not a long edge, and the BH q is computed from the two-sided cluster p.

## Long-only books

Each variant is a ₹10 lakh sleeve inside ₹1 crore, equal weight on admissions, 10% of lagged ADTV cap and the unchanged 8% strategy kill.

| Variant | Sleeve CAGR | Total-capital CAGR | Max sleeve DD | Portfolio DD | B5 CAGR | Excess CAGR | Kill | Fills |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| M1_20 | -0.10% | -0.01% | 9.28% | 1.00% | 12.02% | -12.12% | 2021-03-25 | 151 |
| M1_60 | 0.58% | 0.06% | 9.78% | 1.10% | 12.02% | -11.45% | 2021-03-18 | 160 |
| M2_20 | -0.80% | -0.08% | 9.19% | 0.97% | 12.02% | -12.83% | 2021-01-22 | 11 |
| M2_60 | -0.80% | -0.08% | 9.19% | 0.97% | 12.02% | -12.83% | 2021-01-22 | 11 |

The M2 20 and M2 60 books are identical because the 2021 kill happens before the 20/60 difference in scheduled exits can matter. A killed sleeve stays in cash.

## Next-open gap versus deal print

| Variant | n | Mean | Median | p10 | p25 | p75 | p90 | Positive share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M1 20 | 1329 | 2.51% | 1.56% | -1.28% | -0.01% | 4.00% | 7.61% | 74.42% |
| M1 60 | 1281 | 2.51% | 1.56% | -1.28% | -0.02% | 4.01% | 7.60% | 74.16% |
| M2 20 | 241 | 0.57% | 0.22% | -5.33% | -3.03% | 3.35% | 7.50% | 51.87% |
| M2 60 | 240 | 0.60% | 0.24% | -5.28% | -3.02% | 3.36% | 7.50% | 52.08% |

The gap is the split-adjusted t+1 opening price divided by the event's buy VWAP (the deal print times the deal-date split factor) minus one. Dividends are not added because the deal print is a raw price. A positive gap means the market opened above the deal print; it is a fooling risk, not a cost modelled twice.

## Secondary, exploratory only (not in BH or promotion)

### Lagged-liquidity terciles

| Variant | Terciile | Events | Mean excess | Median excess | Median lagged value (₹ crore) |
|---|---:|---:|---:|---:|---:|
| M1 20 | 1 | 443 | 0.07% | -0.26% | 2.5 |
| M1 20 | 2 | 443 | -0.50% | -1.18% | 16.9 |
| M1 20 | 3 | 443 | -0.51% | -0.80% | 148.3 |
| M1 60 | 1 | 427 | 0.68% | -2.32% | 2.6 |
| M1 60 | 2 | 427 | -0.57% | -1.57% | 17.1 |
| M1 60 | 3 | 427 | -0.14% | -1.05% | 151.2 |
| M2 20 | 1 | 81 | -1.22% | -8.56% | 1.4 |
| M2 20 | 2 | 80 | -8.66% | -11.06% | 5.8 |
| M2 20 | 3 | 80 | -4.89% | -5.10% | 128.5 |
| M2 60 | 1 | 80 | -3.19% | -19.63% | 1.4 |
| M2 60 | 2 | 80 | -10.89% | -17.87% | 5.7 |
| M2 60 | 3 | 80 | -5.97% | -1.92% | 128.5 |

### H01 overlap within ±5 sessions

| Variant | Events | Overlap | Rate |
|---|---:|---:|---:|
| M1 20 | 1329 | 42 | 2.31% |
| M1 60 | 1281 | 42 | 2.31% |
| M2 20 | 241 | 5 | 1.13% |
| M2 60 | 240 | 5 | 1.13% |

## Concentration and data checks

| Variant | Top-5 event positive share | Top-5 issuer positive share | Missing exits | Delayed exits | Truth jump flags |
|---|---:|---:|---:|---:|---:|
| M1 20 | 7.43% | 12.84% | 1 | 2 | 0 |
| M1 60 | 8.35% | 15.38% | 2 | 6 | 0 |
| M2 20 | 41.33% | 64.48% | 0 | 1 | 0 |
| M2 60 | 39.63% | 56.97% | 0 | 2 | 0 |

Missing exits are terminal zero-recovery bounds, not claimed sales; they are flagged in the event CSV. Any such case is a reason not to promote, regardless of the other checks. The M1 variants have one or two such events.

## Proof checks

| Variant | BH q≤.05 | Date placebo≤.05 | Directional≤.05 | Label placebo≤.05 | Max-T≤.05 | Four years sign | Both regimes | Book survives | Status |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| M1 20 | no | no | no | no | no | no | no | no | fail |
| M1 60 | no | no | no | no | no | no | no | no | fail |
| M2 20 | no | no | no | yes | no | no | no | no | fail |
| M2 60 | no | no | no | no | no | no | no | no | fail |

A pass still does not promote: the full data-completeness gate is unmet, the benchmark entry is a previous-close proxy, BSE total returns are derived, tax is the snapshot base capital-gains model, and the deal print is not executable.

## Independent verification

`reality_engine/harness/verify_h02.py` recomputes the final artifacts by different queries and arithmetic from the snapshot, opening it read-only and writing neither the snapshot nor the ledger. It passed 9 of 9 checks on the final files — sampled deal net values, entry and exit prices, tax and net returns, sampled B5 returns, event means, the BH q, a full FIFO replay of one book, the snapshot size/mtime and the pre-registration hash — and recorded the result in `H02_verification.json`.

The check first ran on the 199-draw draft and returned 8 of 9. `sample_b5` failed on 3 of the 30 sampled events: the checker's benchmark return sat 1.4–1.5 percentage points below the run's stored value on each.

| Variant | Event date | Entry | Run `b5_net` | First checker | Gap |
|---|---|---:|---:|---:|---:|
| M1 20 | 2024-01-25 | 2024-01-29 | 3.95% | 2.52% | −1.44 pp |
| M1 20 | 2024-11-05 | 2024-11-06 | 2.62% | 1.09% | −1.53 pp |
| M1 60 | 2024-01-25 | 2024-01-29 | 6.45% | 4.98% | −1.47 pp |

The fault was in the checker, not the run. `B5Path` buys the benchmark at the previous session's TRI close, so its first event factor is `tri[entry]/tri[entry-1]`; at an index switch it realises the outgoing index through the session before and restarts from that same close. The first checker began each segment at its first session's close instead of the session before, dropping one session of benchmark return per segment. Replaying that convention reproduces the three failing values exactly (2.5186%, 1.0902%, 4.9815%); starting each segment a session earlier reproduces the stored values exactly (3.9539%, 2.6249%, 6.4527%). The legs it dropped were +1.29% (Nifty Smallcap 250, 25→29 Jan 2024), +1.89% (Nifty Smallcap 250, 5→6 Nov 2024) and +0.34% (BSE IPO, 31 Jan→1 Feb 2024). Both constructions charge 30 bp and sell-date tax on each segment, so the omitted gross legs carry through to the net gap above.

The corrected checker passed 9 of 9 on the same draft files, and 9 of 9 on the final files. Nothing in the run moved: no run was executed between the failing and the passing draft check, the only edit was to `verify_h02.py`, and nothing in the run imports it; the three stored values in the table are the ones the first checker compared against, and they are the values in the final artifact; the final 499-draw run reproduced the draft's four variant rows on event count, mean, cluster t, p and BH q (the placebo p are not comparable, the draft being a 199-draw run and the final 499); and no harness, event or tax code changed. H02's B5 is the same `B5Path` used by the earlier H01 results.

## Placebo design

499 date draws: deal dates permuted within each stock-year, identities/net values retained, PIT/U1/entry/exit recomputed. 499 label draws: M1/M2 labels permuted across all deal-days within year × lagged-liquidity tercile × prior-200-trend sign, preserving the number of events per stratum. Max-T is the full-grid maximum absolute cluster t across the four variants.

## Deviations and limits

1. Deal feeds are end-of-day (date-only). Entry is the next regular-session open; no intraday print is treated as executable.
2. NSE symbols are mapped only through symbol_isin_history valid on the deal date. BSE codes use security_master.bse_code; a code mapping to more than one issuer is refused. Unmatched rows and value are reported by year, not dropped silently.
3. The same trade can appear on both exchanges and in both the bulk and block feeds. Duplicates are paired one-for-one by (date, client, side, qty, price, issuer); same-exchange same-type identical rows are retained because they may be separate trades. Residual duplicate reporting is possible.
4. Promoter/insider exclusion is company-specific: exact normalized name against nse_insider (symbol->ISIN valid on the disclosure date) and bse_insider target-company promoter names, plus a PROMOTER token. SAST is not used because it also contains institutions. Family trusts or promoter vehicles not disclosed as insiders can remain; M1's declared TRUST token can therefore include a promoter trust. Coverage gaps: 8,486 nse_insider rows (4.8%) had no date-valid symbol mapping and 759 bse_insider rows (0.5%) had an ISIN absent from security_master; those names are not in the exclusion set.
5. M2 is the fixed top-20 2021 repeat-client list after the declared broker/prop exclusions. It is dominated by proprietary/HFT firms; the exclusion tokens are exactly the four declared tokens, not a general 'securities' filter. The list is not chosen with future data.
6. Net value is quantity x price from the feed. Block/bulk prints are negotiated prices, not executable market prices. The next-open gap versus the event buy VWAP is reported; the 30 bp round-trip cost is the only execution cost modelled.
7. U1 is tested at the signal session (last regular session on or before the deal date); entry must have a finite opening total-return price. No missing value is zero-imputed.
8. Prices are total-return adjusted through the shared panel. A missing scheduled close exits at the stock's next actual close; if none exists through 2025-12-31, a zero-recovery bound is retained and flagged, never booked as a fictitious sale.
9. Event returns are t+1 open to scheduled close, after 30 bp and snapshot sell-date STCG. 20/60-session holds are short-term. No annual LTCG allowance is claimed by an isolated event.
10. B5 uses the previous-session TRI close as its entry proxy because the snapshot has no index opens; BSE total-return series are derived. Event and book B5 pay the same cost/tax conventions.
11. Date placebo permutes deal dates within stock-year and recomputes PIT/U1/entry/exit. Label placebo permutes M1/M2 labels across all deal-days within year x lagged-liquidity tercile x prior-200-trend sign, preserving counts per stratum. Neither is an independent-draw proof.
12. BH pools every prior ledger row and the four current tests. The ledger is append-only; this run does not rewrite earlier H01 rows.
13. Books use equal weights on admissions, fractional total-return units, 10% of lagged ADTV, 10% strategy allocation and the unchanged 8% kill. A kill decision fills at the next executable open and can overshoot 8%. No issuer cap is added in this declared run.
14. No 2026 deal rows or 2026 outcomes are loaded. The full data-completeness gate remains unmet; coverage is printed rather than assumed.

## Tests

88 tests passed: 18 new H02 harness tests and 70 existing harness tests. All prior ledger rows remain in the BH family.

## Appendix A — pre-registration, verbatim (written before any outcome)

# H02 pre-registration — written before any outcome was computed

Written: `2026-10-21T20:21:26+00:00`. Snapshot: `truth_2026-10-19.duckdb`, read-only.
Evidence window: 2021-01-01 → 2025-12-31. 2019–2020 deals are warm-up/audit only.
No price, return, benchmark or book outcome was read before this file was written.
Its SHA256 is recorded in `H02_results.json`.

## Fixed signal

- Net value per (issuer, date, declared client set) = Σ buy value − Σ sell value; buy/sell is from the exchange deal feed. Event = net buy ≥ ₹1 crore (10,000,000 INR).
- Entry at t+1 open; never the deal-date close. Deal dates are known end-of-day IST (`known_at_utc` is 18:29:59 UTC = 23:59:59 IST).
- Universe U1 at the signal session; 30 bp round trip; sell-date STCG; B5 benchmark; 20 and 60 trading-day holds; 8% strategy kill.

## M1 — broad institution regex (final, fixed)

Applied case-insensitively to a normalized client name: uppercase, non-alphanumerics replaced by spaces, multiple spaces collapsed, trimmed.

```text
M1_PATTERN = '(?:MUTUAL FUND|\\bMF\\b|ASSET MANAGEMENT|\\bAMC\\b|INSURANCE|LIFE INSURANCE|PENSION|PROVIDENT|FUND|FUNDS|CAPITAL MANAGEMENT|INVESTMENT MANAGEMENT|SOVEREIGN|GOVERNMENT OF|MONETARY AUTHORITY|NORGES|ABU DHABI|\\bGIC\\b|TRUST)'
M1_EXCLUDE = '(?:SHARE BROKING|SECURITIES PRIVATE|STOCK BROKING|COMMODITIES)'
```

The exclusion is applied to the same normalized name. A name that matches both is not M1. The declared tokens are exactly those in the task: `MUTUAL FUND`, ` MF `, `ASSET MANAGEMENT`, `AMC`, `INSURANCE`, `LIFE INSURANCE`, `PENSION`, `PROVIDENT`, `FUND`, `FUNDS`, `CAPITAL MANAGEMENT`, `INVESTMENT MANAGEMENT`, `SOVEREIGN`, `GOVERNMENT OF`, `MONETARY AUTHORITY`, `NORGES`, `ABU DHABI`, `GIC `, `TRUST`; exclusions `SHARE BROKING`, `SECURITIES PRIVATE`, `STOCK BROKING`, `COMMODITIES`.

## M1 hit list — top 100 clients by deal value (2021–2025)

Values are gross deal value (quantity × price) after mapping, dedupe and company-specific promoter/insider exclusion. `promoter_name_any_issuer` is informational: the same name can be a promoter of one issuer and an ordinary client in another, which is why exclusion is company-specific.

| # | Client | Deal value (₹ crore) | Rows | M1 match | Broker/prop | Promoter name (any issuer) |
|---:|---|---:|---:|:---:|:---:|:---:|
| 1 | GRAVITON RESEARCH CAPITAL LLP | 448284.69 | 12764 | no | no | no |
| 2 | HRTI PRIVATE LIMITED | 169912.09 | 4988 | no | no | no |
| 3 | ISHARES CORE MSCI EMERGING MARKETS ETF | 79217.05 | 1711 | no | no | no |
| 4 | ISHARES CORE EMERGING MARKETS MAURITIUS CO | 78611.40 | 1704 | no | no | no |
| 5 | NK SECURITIES RESEARCH PRIVATE LIMITED | 52172.73 | 2240 | no | no | no |
| 6 | BNP PARIBAS ARBITRAGE | 52061.85 | 385 | no | no | no |
| 7 | AAKRAYA RESEARCH LLP | 51843.62 | 1124 | no | no | no |
| 8 | JUMP TRADING FINANCIAL INDIA PRIVATE LIMITED | 50965.02 | 452 | no | no | no |
| 9 | SBI MUTUAL FUND | 50478.07 | 195 | yes | no | no |
| 10 | TOBACCO MANUFACTURERS (INDIA) LIMITED | 50448.12 | 53 | no | no | no |
| 11 | SOCIETE GENERALE | 45334.60 | 556 | no | no | no |
| 12 | XTX MARKETS LLP | 39259.82 | 1588 | no | no | no |
| 13 | QE SECURITIES LLP | 38322.88 | 2262 | no | no | no |
| 14 | ISHARES INDIA INDEX MAURITIUS COMPANY | 33235.09 | 434 | no | no | no |
| 15 | ISHARES MSCI INDIA ETF | 33235.09 | 434 | no | no | no |
| 16 | INTEGRATED CORE STRATEGIES ASIA PTE LTD | 28359.28 | 120 | no | no | no |
| 17 | ISHARES EMERGING MARKETS INDEX MAURITIUS CO | 26982.96 | 404 | no | no | no |
| 18 | ISHARES MSCI EMERGING MARKETS ETF | 26982.96 | 404 | no | no | no |
| 19 | JUNOMONETA FINSOL PRIVATE LIMITED | 26949.16 | 744 | no | no | no |
| 20 | BNP PARIBAS FINANCIAL MARKETS | 25878.60 | 122 | no | no | no |
| 21 | ICICI PRUDENTIAL MUTUAL FUND | 23567.22 | 173 | yes | no | no |
| 22 | THE CHINKERPOO FAMILY TRUST | 22890.03 | 8 | yes | no | no |
| 23 | BOFA SECURITIES EUROPE SA | 22540.33 | 192 | no | no | no |
| 24 | MORGAN STANLEY ASIA SINGAPORE PTE | 20976.71 | 242 | no | no | no |
| 25 | CANADA PENSION PLAN INVESTMENT BOARD | 19970.21 | 22 | yes | no | no |
| 26 | GOVERNMENT OF SINGAPORE | 19959.94 | 48 | yes | no | no |
| 27 | SHARE INDIA SECURITIES LIMITED | 19650.15 | 1137 | no | no | no |
| 28 | S.B. ADANI FAMILY TRUST | 19586.36 | 5 | yes | no | no |
| 29 | GOLDMAN SACHS (SINGAPORE) PTE.- ODI | 18434.33 | 281 | no | no | no |
| 30 | GOLDMAN SACHS FUNDS  GOLDMAN SACHS INDIA EQUITY PORTFOLIO | 17442.10 | 141 | yes | no | no |
| 31 | IRAGE BROKING SERVICES LLP | 17230.60 | 962 | no | no | no |
| 32 | GQG PARTNERS EMERGING MARKETS EQUITY FUND | 16221.77 | 26 | yes | no | no |
| 33 | UBS PRINCIPAL CAPITAL ASIA LIMITED | 15615.93 | 71 | no | no | no |
| 34 | TOWER RESEARCH CAPITAL MARKETS INDIA PRIVATE LIMITED | 14267.92 | 186 | no | no | no |
| 35 | CA ROVER HOLDINGS | 13692.26 | 7 | no | no | no |
| 36 | GOLDMAN SACHS BANK EUROPE SE - ODI | 12693.45 | 207 | no | no | no |
| 37 | ALPHAGREP SECURITIES PRIVATE LIMITED | 12479.61 | 342 | no | yes | no |
| 38 | MANSI SHARE AND STOCK ADVISORS PVT LTD | 12458.74 | 1206 | no | no | no |
| 39 | CA EMERALD INVESTMENTS | 12166.00 | 52 | no | no | no |
| 40 | ANTFIN SINGAPORE HOLDING PTE. LTD. | 11695.50 | 5 | no | no | no |
| 41 | DODONA HOLDINGS LIMITED | 11515.47 | 19 | no | no | no |
| 42 | SIDDHARTHA YOG | 11515.47 | 19 | no | no | no |
| 43 | TPG ASIA VII SF PTE LTD | 11510.98 | 58 | no | no | no |
| 44 | MARSHALL WACE INVESTMENT STRATEGIES - EUREKA FUND | 11175.61 | 138 | yes | no | no |
| 45 | MOTILAL OSWAL MUTUAL FUND | 11059.07 | 72 | yes | no | no |
| 46 | GOLDMAN SACHS INDIA FUND LIMITED | 10995.00 | 58 | yes | no | no |
| 47 | QE SECURITIES | 10633.59 | 908 | no | no | no |
| 48 | ABRDN INVESTMENT MANAGEMENT LIMITED | 10461.55 | 24 | yes | no | no |
| 49 | SMALLCAP WORLD FUND INC | 10320.62 | 62 | yes | no | no |
| 50 | ACME TRADE AND INVESTMENT LTD | 10298.08 | 6 | no | no | no |
| 51 | SAMAYAT SERVICES LLP | 10220.40 | 2 | no | no | no |
| 52 | ADANI COMMODITIES LLP | 9967.32 | 14 | no | yes | no |
| 53 | JAINAM BROKING LIMITED | 9929.96 | 608 | no | no | no |
| 54 | NIPPON INDIA MUTUAL FUND | 9922.51 | 100 | yes | no | no |
| 55 | MUSIGMA SECURITIES | 9689.51 | 430 | no | no | no |
| 56 | COPTHALL MAURITIUS INVESTMENT LIMITED | 9637.92 | 75 | no | no | no |
| 57 | SIDDHANT COMMERCIALS PRIVATE LIMITED | 9579.45 | 2 | no | no | no |
| 58 | MATHISYS ADVISORS LLP | 9546.51 | 524 | no | no | no |
| 59 | HDFC MUTUAL FUND | 9503.81 | 132 | yes | no | no |
| 60 | KOTAK MAHINDRA MUTUAL FUND | 9470.40 | 69 | yes | no | no |
| 61 | PLUTUS WEALTH MANAGEMENT LLP | 9258.40 | 108 | no | no | no |
| 62 | RAKESH GANGWAL | 8961.65 | 6 | no | no | no |
| 63 | SINGAPORE VII TOPCO III PTE LTD | 8961.39 | 2 | no | no | no |
| 64 | GOLDMAN SACHS TRUST II-GOLDMAN SACHS GQG PARTNERS INTL OPPORTUNITIES FUND | 8865.31 | 5 | yes | no | no |
| 65 | GOLDMAN SACHS TRUST II - GOLDMAN SACHS GQG PARTNERS INTERNATIONAL OPPORTUNITIES FUND | 8607.19 | 7 | yes | no | no |
| 66 | QUALITY INVESTMENT HOLDINGS PCC | 8573.59 | 13 | no | no | no |
| 67 | ALIPAY SINGAPORE HOLDING PTE. LTD. | 8304.90 | 34 | no | no | no |
| 68 | VANGUARD TOTAL INTERNATIONAL STOCK INDEX FUND | 8266.08 | 190 | yes | no | no |
| 69 | MULTIPLIER SHARE & STOCK ADVISORS PRIVATE LIMITED | 7767.52 | 4910 | no | no | no |
| 70 | NEW WORLD FUND, INC | 7622.14 | 17 | yes | no | no |
| 71 | RKN ENTERPRISES | 7605.80 | 9 | no | no | yes |
| 72 | RELIANCE TRUST INSTITUTIONAL RETIREMENT TRUST SERIES ELEVEN | 7416.88 | 16 | yes | no | no |
| 73 | AFRO ASIA TRADE AND INVESTMENTS LTD | 7411.83 | 1 | no | no | no |
| 74 | ANTFIN (NETHERLANDS) HOLDING B.V. | 7114.43 | 17 | no | no | no |
| 75 | ELIXIR WEALTH MANAGEMENT PRIVATE LIMITED | 7047.21 | 361 | no | no | no |
| 76 | SPARK INSTITUTIONAL EQUITIES PRIVATE LIMITED | 6949.79 | 2 | no | no | no |
| 77 | STANDARD LIFE MAURITIUS HOLDINGS 2006 LTD | 6783.60 | 2 | no | no | no |
| 78 | SHOBHA GANGWAL | 6730.59 | 8 | no | no | no |
| 79 | VFTR C INSTITUTIONAL TOTAL INTERNATIONAL STOCK MARKET INDEX TRUST II | 6724.33 | 171 | yes | no | no |
| 80 | PI OPPORTUNITIES AIF V LLP | 6704.83 | 50 | no | no | no |
| 81 | GREAT TERRAIN INVESTMENT LTD | 6658.51 | 34 | no | no | no |
| 82 | RECOVERY OFFICER I DRT II | 6554.87 | 7 | no | no | no |
| 83 | CRONY VYAPAR PVT LTD | 6521.70 | 522 | no | no | no |
| 84 | GQG PARTNERS INTERNATIONAL EQUITY CIT | 6512.36 | 10 | no | no | no |
| 85 | MICROCURVES TRADING PRIVATE LIMITED | 6400.33 | 262 | no | no | no |
| 86 | ADITYA BIRLA SUN LIFE MUTUAL FUND | 6328.79 | 121 | yes | no | no |
| 87 | NORGES BANK ON ACCOUNT OF THE GOVERNMENT PENSION FUND GLOBAL | 6328.46 | 69 | yes | no | no |
| 88 | SUMITOMO MITSUI BANKING CORPORATION | 6256.13 | 2 | no | no | no |
| 89 | THE VANGUARD GROUP  INC A/C VANGUARD EMERG. MKTS STOCK INDEXFD A SERIES OF V I E I F | 6185.65 | 52 | no | no | no |
| 90 | SETU SECURITIES PVT LTD | 5852.39 | 1190 | no | no | no |
| 91 | WESTBRIDGE CROSSOVER FUND LLC | 5842.98 | 9 | yes | no | no |
| 92 | VAIBHAV STOCK AND DERIVATIVES BROKING PRIVATE LIMITED | 5828.76 | 204 | no | no | no |
| 93 | BEIGE LIMITED | 5751.56 | 4 | no | no | no |
| 94 | GHISALLO MASTER FUND LP | 5677.05 | 61 | yes | no | no |
| 95 | BC ASIA INVESTMENTS VII LIMITED | 5624.97 | 9 | no | no | no |
| 96 | BPCL TRUST FOR INVESTMENT IN SHARES | 5525.42 | 1 | yes | no | no |
| 97 | SURJECTIVE RESEARCH CAPITAL LLP | 5499.32 | 62 | no | no | no |
| 98 | CITIGROUP GLOBAL MARKETS MAURITIUS PRIVATE LIMITED | 5446.09 | 54 | no | no | no |
| 99 | SW CAPITAL PRIVATE LIMITED | 5423.65 | 412 | no | no | yes |
| 100 | ENVESTCOM HOLDING RSC LTD | 5400.38 | 5 | no | no | no |

### Largest clients removed by the company-specific promoter/insider rule

| # | Client | Deal value (₹ crore) | Rows |
|---:|---|---:|---:|
| 1 | PASTEL LIMITED | 42744.24 | 5 |
| 2 | INDIAN CONTINENT INVESTMENT LIMITED | 35209.37 | 5 |
| 3 | ROBERT BOSCH GMBH | 29462.09 | 1 |
| 4 | ROBERT BOSCH INTERNATIONALE BETEILIGUNGEN AG | 29462.09 | 1 |
| 5 | BHARTI TELECOM LIMITED | 24166.83 | 4 |
| 6 | HULST B V | 16771.98 | 8 |
| 7 | KAYAK INVESTMENTS HOLDING PTE.LTD | 15438.75 | 6 |
| 8 | FINSIDER INTERNATIONAL COMPANY LIMITED | 14190.57 | 4 |
| 9 | BCP TOPCO IX PTE. LTD. | 11461.67 | 2 |
| 10 | ADANI TRADING SERVICES LLP | 10298.08 | 6 |

## M2 — top-20 repeat clients, first evidence year only (2021)

Ranked by distinct deal-days in 2021 after dedupe and company-specific promoter/insider removal, excluding the declared broker/prop tokens. Ties break by normalized client name. The list is frozen here and is not chosen with 2022–2025 data.

| # | Client | Distinct deal-days 2021 | 2021 deal value (₹ crore) | 2021 rows |
|---:|---|---:|---:|---:|
| 1 | ALPHA LEON ENTERPRISES LLP | 213 | 2548.40 | 1349 |
| 2 | GRAVITON RESEARCH CAPITAL LLP | 191 | 27340.42 | 1644 |
| 3 | OLGA TRADING PRIVATE LIMITED | 177 | 950.42 | 677 |
| 4 | XTX MARKETS LLP | 166 | 25176.74 | 798 |
| 5 | TOPGAIN FINANCE PRIVATE LIMITED | 113 | 921.17 | 354 |
| 6 | NK SECURITIES RESEARCH PRIVATE LIMITED | 111 | 6988.54 | 338 |
| 7 | QE SECURITIES | 91 | 2622.55 | 272 |
| 8 | MANSI SHARES & STOCK ADVISORS PVT LTD | 78 | 1454.27 | 228 |
| 9 | ADROIT FINANCIAL SERVICES PVT LTD | 75 | 1498.68 | 197 |
| 10 | NNM SECURITIES PVT LTD | 74 | 168.51 | 176 |
| 11 | VAIBHAV STOCK AND DERIVATIVES BROKING PRIVATE LIMITED | 73 | 5062.90 | 172 |
| 12 | ASHOK KUMAR SINGH | 63 | 6.71 | 95 |
| 13 | ESPS FINSERVE PRIVATE LIMITED | 57 | 3.64 | 83 |
| 14 | SHERWOOD SECURITIES PVT LTD | 55 | 21.54 | 91 |
| 15 | ANKITA VISHAL SHAH | 50 | 477.19 | 120 |
| 16 | B M TRADERS | 50 | 185.91 | 113 |
| 17 | JUMP TRADING FINANCIAL INDIA PRIVATE LIMITED | 47 | 24425.42 | 108 |
| 18 | NAVEEN  GUPTA | 47 | 8.44 | 104 |
| 19 | KABIR SHRAN DAGAR | 46 | 7.35 | 80 |
| 20 | PARESH DHIRAJLAL SHAH | 46 | 13.39 | 67 |

## Deal mapping, dedupe and promoter/insider exclusion

- NSE: `symbol` → `symbol_isin_history` valid on the deal date → `security_master.issuer`. Unmatched: 2641 rows in 2019–2025 (153667.6 ₹ crore); by year in the results JSON.
- BSE: `sc_code` → `security_master.bse_code` (a code mapping to more than one issuer is refused). BSE accounts for the remainder of unmatched rows; see the year table.
- Dedupe: 29 cross-exchange pairs and 2267 BULK/BLOCK duplicate pairs removed one-for-one. Same-exchange, same-type identical rows are retained: they can be genuine separate trades.
- Promoter/insider exclusion: company-specific exact normalized-name match against `nse_insider` (symbol→ISIN valid on the disclosure date) and `bse_insider` target-company promoter names; plus any client name containing `PROMOTER`. Excluded 4161 rows / 807794.0 ₹ crore. 39148 company-name pairs, 2848 issuers, 35110 names.
- SAST is not used as a name source because it also contains institutional acquirers; company-name/PROMOTER heuristics beyond the explicit token are not used.

## Year-by-year mapping coverage

| Year | Rows | Mapped | Unmatched | Value (₹ crore) | Unmatched value (₹ crore) |
|---:|---:|---:|---:|---:|---:|
| 2019 | 17525 | 17460 | 65 | 435295.0 | 4000.1 |
| 2020 | 15008 | 14847 | 161 | 554650.4 | 7846.8 |
| 2021 | 30462 | 30309 | 153 | 731127.7 | 3593.9 |
| 2022 | 39058 | 38800 | 258 | 602342.7 | 13241.8 |
| 2023 | 38000 | 37548 | 452 | 804389.2 | 29875.9 |
| 2024 | 53385 | 52728 | 657 | 1327663.7 | 42378.6 |
| 2025 | 40977 | 40082 | 895 | 1169852.4 | 52730.4 |

2026 deal rows exist in the snapshot and are excluded from every computation here; they are not loaded into the working table.



## Reproduction

`python -m reality_engine.harness.run_h02 --placebo-draws 499`

Git HEAD `1dedba8016152cba45b5e693abce327ee33cc661`; new source files are uncommitted and their SHA256 hashes are in the JSON. No 2026 outcomes, paid worker, commit, push or upload.

