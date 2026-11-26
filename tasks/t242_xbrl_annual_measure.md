# T-242 filed-figure cross-check: annual/half-year extension (26 Nov 2026, dsh DeepSeek, Wolf)

`reality_engine/v2/xbrl_crosscheck.py` now checks hy4 rows against two filed sources: `fin_quarter_xbrl` (quarter P&L,
as before) and `fin_annual_line` (`statement` BS/P&L/CF, `period_type` H1/FY/Q). BS matches on the as-at date
(`as_at_date`); P&L/CF matches only when the printed duration and end date both agree (`duration_end`: half year -> H1,
year -> FY, quarter -> Q; a two-date span must sit in the duration's day range). Cash-flow lines whose sign convention
varies (capex, purchase of PPE/intangible, dividends, repayment, taxes, leases) match on |value|. A row checked by both
sources keeps one verdict: a match in either wins, a contradiction only when no source matches. A mismatch against a
store-derived (`is_reported=0`) line never contradicts; an empty basis is never called wrong.

Run 26 Nov 2026 17:56 IST, out-dir `.tmp/checks_xbrl` (not installed):

| DB | match (incl. sign-conv) | sign-conv match | unit fix | contradicts | checked rows | contradicts share |
|---|---|---|---|---|---|---|
| `obs_results_fy27.db` | 2,448 (P&L 1,977 / BS 328 / CF 143) | 13 (included) | 132 (P&L 113 / BS 16 / CF 3) | 232 (P&L 207 / BS 21 / CF 4) | 2,812 | 8.3% |
| `obs_ar_fy27.db` | 0 | 0 | 0 | 0 | 0 | - |

Status moves available on the results file: matches 890 verified + 1,558 unverified; contradictions 66 verified would
be demoted; unit fixes 7 verified would be demoted. Skips on results: 1,266 non-company scope, 434 segment, 21,061 no
duration named, 16,095 no filed line at the period; 30 store-derived-line mismatches and 11 unlabelled-basis mismatches
were deliberately not called wrong.

`obs_ar_fy27.db` gives 0 verdicts for a coverage reason, not a matcher failure: its 588 symbols are the small-cap free
window; 247 of them are in the annual table but only on H1 30 Sep lines, and none of the 335 symbols that carry a
31 March FY/BS line is in the AR DB. Every AR row therefore skips (12,584 no filed line, 7,984 no duration named,
4,582 non-company scope, 1,904 segment).

## Seed-7 judgment of the new (annual-source) contradictions

20 of the 60 annual-source contradictions in the 17:56 file, sampled with `random.Random(7)`. The source PDFs under
`D:/RealityEngine/raw/pilot60_history` have been pruned, so each case was judged on the reader's own recorded page row
(`printed_label`, `printed_axis`, `group_path`, `series_title`), the other rows it produced on the same page and the
filed row. **14 real read/wrong-served rows, 6 store-side matcher misses -> 70%**, below the 80% bar.

| id | symbol / measure | filed vs stored | judgment |
|---|---|---|---|
| 48242 | ARVINDFASN total_equity | 1,231.07 cr vs 978.79 cr | matcher: store total_equity = owners 978.79 + NCI 252.28; the page's Total Equity is owners' |
| 35430 | ALPINETEX total_equity | 197.38 cr vs 199.72 cr | matcher: printed Total Equity includes NCI; store total_equity = owners' equity |
| 62940 | AGARWALEYE equity_share_capital | 33.22 cr vs 31.70 cr | matcher: store line vs its own share_capital table (31.70 cr) |
| 77080 | APEX cash_and_cash_equivalents | 2.70 cr vs 22.70 cr | real: 2,270.34 lakh read against a 270.34 lakh cash line (CF closing 2.70 cr agrees) |
| 7223 | BAJAJHLDNG investments | 87,014.28 cr vs 41,077.03 cr | real: "Other investments" sub-line served as total investments |
| 18680 | ABLBL other_expenses H1 | 1,401.49 cr vs 1,049.61 cr | matcher: store tag aggregates more than the printed (h) line |
| 95306 | AXISCADES finance_cost H1 | 1,471.39 L vs 1,579.29 L | real: cash-flow adjustment "Finance costs #" served as P&L finance cost |
| 76794 | ANURAS other_income H1 | 278.03 m vs 152.38 m | real: Q2 column with H1 period (right H1 278.03 also read) |
| 34036 | ALOKINDS pat H1 | -346.67 cr vs +346.67 cr | real: "loss of 346.67 crore" stored positive |
| 62000 | AERONEU cash_flow.financing | -4.65 cr vs +5.82 cr | real: bracketed negative read positive; value also differs |
| 76828 | ANURAS finance_cost H1 | 1,053.76 m vs 561.84 m | real: Q2 column with H1 period (right H1 1,053.76 also read) |
| 95722 | AXITA finance_cost H1 | 72.12 L vs -67.58 L | real: cash-flow finance cost read negative and at the wrong magnitude |
| 73322 | ANANDRATHI total_assets | 1,601.6 cr vs 8.04 cr | real: 804.45 read with lakh scale, no plausible line |
| 42340 | ANUP revenue_from_operations H1 | 3,076.53 m vs 1,671.17 m | real: quarter column with H1 period (right H1 2,850.10 also read) |
| 4506 | ASTRAL total_assets | 58,746 m vs 11,272 m | real: subsidiaries-note "include total assets" served as company total |
| 27944 | AGARWALEYE cash_flow.investing | -195.10 L vs 1,195.10 L | real: OCR-garbled value served positive |
| 63443 | AGARWALEYE equity_share_capital | 33.22 cr vs 31.70 cr | matcher: same store line defect as 62940 |
| 63440 | AGARWALEYE equity_share_capital | 33.22 cr vs 31.70 cr | matcher: same store line defect as 62940 |
| 95368 | AXISCADES finance_cost H1 | 1,471.39 L vs 107.90 L | real: CF non-cash finance cost served as P&L finance cost |
| 42352 | ANUP pat H1 | 715.38 L vs 914.97 L | real: period/basis column mix (right H1 1,025.78 also read) |

A second seed-7 sample of the 20 contradictions that would demote a **verified** row (both sources, 17:52 snapshot)
judged 14/20 real (70%): ACC PBT 200 vs 198 cr (rounded near-1% miss), ABCAPITAL presentation PAT 1,175 vs filed
1,223.85 cr, ABB/ALOKINDS other-expenses aggregation and ANURAS total-equity were store-side; the rest were wrong
columns, notes, discontinued operations, signs and scales.

## Rule to ship later

Do not install the annual verdict file in `D:/RealityEngine/checks/xbrl` yet. Normalise these store lines first, then
re-judge: (1) `other_expenses` tags aggregate more than the printed (h) line for several companies, (2) `total_equity`
holds owners' equity where the page's Total Equity includes NCI (and the reverse for ARVINDFASN/ALPINETEX), (3)
`equity_share_capital` has a stale 33.22 cr line for AGARWALEYE against the store's own `share_capital` table (31.70
cr). The match side (2,448 `xbrl_match` rows) is safe to install after review; the 132 unit fixes and 232
contradictions need it. Tests: `reality_engine/tests/test_xbrl_crosscheck.py` (10 passed).
