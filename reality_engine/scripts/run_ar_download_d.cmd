@echo off
rem Annual reports FY2019+ for companies still trading (traded since 2025-10-01), saved on D: because C: is short of
rem space (2026-10-10: C: 142 GB free, ~20k reports / ~150 GB pending). Delisted companies' reports are left for later.
rem Repeated passes retry transient failures. Log: reality_engine\data\logs\annual_report_ingest.log
cd /d "%~dp0\..\.."
set REALITY_ENGINE_PDFS_DIR=D:\RealityEngine\pdfs
set PY="C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe"
for /l %%i in (1,1,5) do %PY% -u -m reality_engine.scripts.run_annual_report_ingest --download-only --since 2019-04-01 --active-since 2025-10-01 --workers 3
