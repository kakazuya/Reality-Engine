# Task: raw fetch for three new pilot companies, a Vahan series, and new NSDL fortnights

Shivam added APOLLOHOSP (INE437A01024, BSE 508869), KIMS (INE967H01025, BSE 543308), OLAELEC (INE0LXG01040, BSE 544225) on 1 Nov. Raw fetch only: no extraction, no chunking, no LLM. Raw files go to D:\RealityEngine\raw. Do not edit tasks/pilot60/UNIVERSE.csv, anything in tasks/pilot60/pilot_bank/, or any store under reality_engine/data/pilot/v4/.

1. Documents. Fetch these three the way reality_engine/scripts/fetch_pilot60_history.py fetches the 60: it reads UNIVERSE.csv, so add a way to pass another universe file (default unchanged) and use tasks/pilot60/UNIVERSE_ADD3.csv. Also list which FY2024-25+ annual reports, concalls, decks and results are held for them and which are missing at BSE or NSE, and fetch the missing ones. Report counts by type and year.
2. NSDL. Fetch sector-wise fortnight files after 30 Sep 2026 with reality_engine/scripts/fetch_nsdl_raw.py and load them with load_market_raw (source nsdl_fpi_fortnight). Note: the site can time out; retry at its own pace.
3. Vahan. reality_engine/ingestion/headless_fetcher.py names a Vahan feed. Test whether it works. Goal: monthly registrations by maker for two-wheelers (electric, at minimum Ola Electric), from as far back as the public dashboard allows, saved raw under D:\RealityEngine\raw\vahan, with a small fetcher and a coverage note. If the dashboard blocks automated use, stop and say exactly what blocked it. Do not use financiallyfree.in; it needs a Google login.

Measure real rate limits. Report: what was fetched, counts, what failed and why, one Vahan sample row, tests run. End with a `Docs updated:` line (tasks/STATE.md is Claude's; update tasks/DATA_JOBS_AUDIT if a job is new).
