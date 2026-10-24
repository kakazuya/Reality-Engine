# bse_announcements schema

File: `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\bse_announcements.db` (1.1 GB)

BSE corporate-announcement feed: one metadata row per NEWSID (headline/category/timestamps/attachment) plus a per-scrip fetch ledger. Metadata only; the duckdb snapshot has a PIT-stamped copy.

## ann
rows: 1.9M · key columns: NEWSID, SCRIP_CD, symbol

- `NEWSID` TEXT
- `SCRIP_CD`
- `ATTACHMENTNAME`
- `NEWSSUB`
- `HEADLINE`
- `CATEGORYNAME`
- `SUBCATNAME`
- `NEWS_DT`
- `DT_TM`
- `News_submission_dt`
- `DissemDT`
- `QUARTER_ID`
- `Fld_Attachsize`
- `ANNOUNCEMENT_TYPE`
- `symbol` TEXT

## done
rows: ~33.2k · key columns: scrip, win

- `scrip` TEXT
- `win` INT
- `n` INT
- `at` TEXT
