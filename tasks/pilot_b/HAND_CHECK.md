# Pilot (b) hand checks — 10 random stored rows vs the raw source

seed 20261029; every row below is re-read from the raw file, not from the build.

| table | key | raw | stored | ok |
|---|---|---|---|---|
| `series_observation` | wb_nickel 2016-07-31 | close=10263.0 unit=($/mt) known_at=2026-10-02 | value=10263.0 unit=($/mt) known_at=2026-10-02T23:59:59 pit_conf=0.8 | OK |
| `series_observation` | wb_natgas_eu 2008-01-31 | close=10.7 unit=($/mmbtu) known_at=2026-10-02 | value=10.7 unit=($/mmbtu) known_at=2026-10-02T23:59:59 pit_conf=0.8 | OK |
| `series_observation` | wb_crude_brent 2020-04-30 | close=23.3 unit=($/bbl) known_at=2026-10-02 | value=23.3 unit=($/bbl) known_at=2026-10-02T23:59:59 pit_conf=0.8 | OK |
| `series_observation` | wb_rubber 2008-01-31 | close=2.62 unit=($/kg) known_at=2026-10-02 | value=2.62 unit=($/kg) known_at=2026-10-02T23:59:59 pit_conf=0.8 | OK |
| `series_observation` | wb_gold 2024-03-31 | close=2158.0 unit=($/troy oz) known_at=2026-10-02 | value=2158.0 unit=($/troy oz) known_at=2026-10-02T23:59:59 pit_conf=0.8 | OK |
| `series_observation` | wb_natgas_eu 2019-11-30 | close=5.15 unit=($/mmbtu) known_at=2026-10-02 | value=5.15 unit=($/mmbtu) known_at=2026-10-02T23:59:59 pit_conf=0.8 | OK |
| `series_observation` | wb_dap 2006-04-30 | close=231.8 unit=($/mt) known_at=2026-10-02 | value=231.8 unit=($/mt) known_at=2026-10-02T23:59:59 pit_conf=0.8 | OK |
| `series_observation` | wb_crude_avg 2016-08-31 | close=44.9 unit=($/bbl) known_at=2026-10-02 | value=44.9 unit=($/bbl) known_at=2026-10-02T23:59:59 pit_conf=0.8 | OK |
| `series_observation` | wb_soybean_oil 2010-09-30 | close=1035.0 unit=($/mt) known_at=2026-10-02 | value=1035.0 unit=($/mt) known_at=2026-10-02T23:59:59 pit_conf=0.8 | OK |
| `series_observation` | wb_silver 2012-11-30 | close=32.8 unit=($/troy oz) known_at=2026-10-02 | value=32.8 unit=($/troy oz) known_at=2026-10-02T23:59:59 pit_conf=0.8 | OK |
| `fno_oi_daily` | 2020-07-07 ACC 2020-07-30 0.0 FUT | oi=2316000 vol=2486 settle=1314.3 | oi=2316000 vol=2486 settle=1314.3 | OK |
| `fno_oi_daily` | 2020-11-13 ACC 2020-11-26 0.0 FUT | oi=1854500 vol=2321 settle=1678.9 | oi=1854500 vol=2321 settle=1678.9 | OK |
| `fno_oi_daily` | 2021-05-12 AARTIIND 2021-05-27 0.0 FUT | oi=866150 vol=843 settle=1745.15 | oi=866150 vol=843 settle=1745.15 | OK |
| `fno_oi_daily` | 2021-11-25 AARTIIND 2021-11-25 0.0 FUT | oi=106250 vol=1527 settle=948.5 | oi=106250 vol=1527 settle=948.5 | OK |
| `fno_oi_daily` | 2022-09-02 AARTIIND 2022-09-29 0.0 FUT | oi=2862800 vol=1974 settle=837.6 | oi=2862800 vol=1974 settle=837.6 | OK |
| `fno_oi_daily` | 2022-10-25 AARTIIND 2022-10-27 0.0 FUT | oi=849150 vol=888 settle=686.35 | oi=849150 vol=888 settle=686.35 | OK |
| `fno_oi_daily` | 2023-06-05 AARTIIND 2023-06-29 0.0 FUT | oi=5059200 vol=1400 settle=520.35 | oi=5059200 vol=1400 settle=520.35 | OK |
| `fno_oi_daily` | 2024-04-23 AARTIIND 2024-04-25 0.0 FUT | oi=4453000 vol=9114 settle=739.55 | oi=4453000 vol=9114 settle=739.55 | OK |
| `fno_oi_daily` | 2024-09-09 AARTIIND 2024-09-26 0.0 FUT | oi=15614000 vol=4587 settle=594.9 | oi=15614000 vol=4587 settle=594.9 | OK |
| `fno_oi_daily` | 2024-12-26 AARTIIND 2024-12-26 0.0 FUT | oi=1879000 vol=7981 settle=413.25 | oi=1879000 vol=7981 settle=413.25 | OK |
| `mkt_nse_full_daily` | 2026-10-15 ANURAS EQ | close= 1161.00 volume= 335769 turnover_lacs= 3926.75 deliv= 259803 deliv_pct= 77.38 | close=1161 volume=335769 turnover_lacs=3926.75 deliv=259803 deliv_pct=77.38 | OK |
| `mkt_nse_full_daily` | 2026-10-01 PRUDMOULI EQ | close= 13.49 volume= 725 turnover_lacs= 0.10 deliv= 723 deliv_pct= 99.72 | close=13.49 volume=725 turnover_lacs=0.1 deliv=723 deliv_pct=99.72 | OK |
| `mkt_nse_full_daily` | 2026-10-09 JSL EQ | close= 709.05 volume= 260251 turnover_lacs= 1840.98 deliv= 126265 deliv_pct= 48.52 | close=709.05 volume=260251 turnover_lacs=1840.98 deliv=126265 deliv_pct=48.52 | OK |
| `mkt_nse_full_daily` | 2026-10-15 REFRACTORY SM | close= 30.50 volume= 24000 turnover_lacs= 7.38 deliv= 23000 deliv_pct= 95.83 | close=30.5 volume=24000 turnover_lacs=7.38 deliv=23000 deliv_pct=95.83 | OK |
| `mkt_nse_full_daily` | 2026-10-06 TVSHLTD EQ | close= 11763.00 volume= 4509 turnover_lacs= 531.11 deliv= 2972 deliv_pct= 65.91 | close=11763 volume=4509 turnover_lacs=531.11 deliv=2972 deliv_pct=65.91 | OK |
| `mkt_nse_full_daily` | 2026-09-29 WSI EQ | close= 55.62 volume= 8869 turnover_lacs= 4.93 deliv= 8462 deliv_pct= 95.41 | close=55.62 volume=8869 turnover_lacs=4.93 deliv=8462 deliv_pct=95.41 | OK |
| `mkt_nse_full_daily` | 2026-10-15 PASUPTAC EQ | close= 79.55 volume= 1264856 turnover_lacs= 1044.50 deliv= 396951 deliv_pct= 31.38 | close=79.55 volume=1264856 turnover_lacs=1044.5 deliv=396951 deliv_pct=31.38 | OK |
| `mkt_nse_full_daily` | 2026-10-14 GROWWRAIL EQ | close= 26.37 volume= 243644 turnover_lacs= 64.35 deliv= 115658 deliv_pct= 47.47 | close=26.37 volume=243644 turnover_lacs=64.35 deliv=115658 deliv_pct=47.47 | OK |
| `mkt_nse_full_daily` | 2026-09-24 HDFCLOWVOL EQ | close= 19.81 volume= 255306 turnover_lacs= 50.59 deliv= 222873 deliv_pct= 87.30 | close=19.81 volume=255306 turnover_lacs=50.59 deliv=222873 deliv_pct=87.3 | OK |
| `mkt_nse_full_daily` | 2026-10-06 KANPRPLA EQ | close= 250.90 volume= 9852 turnover_lacs= 24.84 deliv= 5991 deliv_pct= 60.81 | close=250.9 volume=9852 turnover_lacs=24.84 deliv=5991 deliv_pct=60.81 | OK |
| `index_list` | nifty100 (held current_nifty100.csv) | 100 members in current_nifty100.csv | 100 members, coverage snapshot | OK |
| `index_list` | nifty200 (held current_nifty200.csv) | 200 members in current_nifty200.csv | 200 members, coverage snapshot | OK |
| `index_list` | nifty50 (held current_nifty50.csv) | 50 members in current_nifty50.csv | 50 members, coverage snapshot | OK |
| `index_list` | nifty500 (held current_nifty500.csv) | 500 members in current_nifty500.csv | 500 members, coverage snapshot | OK |
| `index_list` | niftymidcap150 (held current_niftymidcap150.csv) | 150 members in current_niftymidcap150.csv | 150 members, coverage snapshot | OK |
| `index_list` | niftysmallcap250 (held current_niftysmallcap250.csv) | 250 members in current_niftysmallcap250.csv | 250 members, coverage snapshot | OK |
| `company_membership_pit` | nifty100 INE397D01024 | current member in current_nifty100.csv | open interval from 2019-01-01 (snapshot_backcast, pit_conf 0.8) | OK |
| `company_membership_pit` | nifty100 INE249Z01020 | current member in current_nifty100.csv | open interval from 2025-09-30 (nse_notice, pit_conf 1.0) | OK |
| `company_membership_pit` | nifty200 INE123W01016 | current member in current_nifty200.csv | open interval from 2019-01-01 (snapshot_backcast, pit_conf 0.8) | OK |
| `company_membership_pit` | nifty200 INE704P01025 | current member in current_nifty200.csv | open interval from 2024-09-30 (nse_notice, pit_conf 1.0) | OK |
| `company_membership_pit` | nifty50 INE192A01025 | current member in current_nifty50.csv | open interval from 2021-03-31 (nse_notice, pit_conf 1.0) | OK |
| `company_membership_pit` | nifty50 INE296A01032 | current member in current_nifty50.csv | open interval from 2019-01-01 (snapshot_backcast, pit_conf 0.8) | OK |
| `company_membership_pit` | nifty500 INE138Y01010 | current member in current_nifty500.csv | open interval from 2023-03-31 (nse_notice, pit_conf 1.0) | OK |
| `company_membership_pit` | nifty500 INE0CAZ01013 | current member in current_nifty500.csv | open interval from 2026-03-30 (nse_notice, pit_conf 1.0) | OK |
| `company_membership_pit` | niftymidcap150 INE674K01013 | current member in current_niftymidcap150.csv | open interval from 2023-07-13 (nse_notice, pit_conf 1.0) | OK |
| `company_membership_pit` | niftymidcap150 INE603J01030 | current member in current_niftymidcap150.csv | open interval from 2024-03-28 (nse_notice, pit_conf 1.0) | OK |
