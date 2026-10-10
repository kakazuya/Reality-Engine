@echo off
rem Download (no chunking) every indexed filing in scope, all companies, newest first. Resumable: re-run to continue.
rem  - annual reports filed since 2019-04-01 (FY2019 onwards), then concall transcripts filed since 2022-01-01
rem  - each stage is repeated (up to 5 passes) so rows that failed on a transient error get another try
rem Chunking waits for the annual-report value study (tasks/ANNUAL_REPORT_VALUE_STUDY.md).
rem Log: reality_engine\data\logs\annual_report_ingest.log
rem Usage: run_filing_download.cmd [ar|concall|both]   (default both)
cd /d "%~dp0\..\.."
set PY="C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe"
set WHAT=%1
if "%WHAT%"=="" set WHAT=both
if not "%WHAT%"=="concall" for /l %%i in (1,1,5) do %PY% -u -m reality_engine.scripts.run_annual_report_ingest --download-only --since 2019-04-01 --workers 3
if not "%WHAT%"=="ar" for /l %%i in (1,1,5) do %PY% -u -m reality_engine.scripts.run_annual_report_ingest --download-only --since 2022-01-01 --workers 3 --doc-type CONCALL_TRANSCRIPT
