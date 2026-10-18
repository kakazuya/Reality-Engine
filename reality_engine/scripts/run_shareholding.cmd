@echo off
rem Shareholding pattern backfill (fetch_shareholding.py): month index 2021 ->, per-symbol listing (full history),
rem XBRL download (~0.4 s each), parse. Log: reality_engine\data\logs\shareholding.log
cd /d "%~dp0\..\.."
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.fetch_shareholding --index --start 2021-01 >> reality_engine\data\logs\shareholding.log 2>&1
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.fetch_shareholding --symbols >> reality_engine\data\logs\shareholding.log 2>&1
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.fetch_shareholding --xbrl >> reality_engine\data\logs\shareholding.log 2>&1
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.fetch_shareholding --parse >> reality_engine\data\logs\shareholding.log 2>&1
