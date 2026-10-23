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

