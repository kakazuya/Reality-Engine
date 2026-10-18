@echo off
rem PIB English (Delhi HQ) backfill 2021-01-01 -> today: day listings, release bodies with posting time, search layer.
rem Resumable (listed days / fetched bodies are skipped). Log: reality_engine\data\logs\pib_backfill.log
cd /d "%~dp0\..\.."
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.pib_feed --start 2021-01-01 >> reality_engine\data\logs\pib_backfill.log 2>&1
