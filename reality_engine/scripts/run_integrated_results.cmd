@echo off
rem Quarterly results from Mar-2025 (NSE 'Integrated Filing - Financials'): refresh index, download XBRL, parse into
rem reality_engine\data\results_xbrl.db. Resumable: downloaded files and parsed filings are skipped.
rem Log: reality_engine\data\logs\integrated_results.log
cd /d "%~dp0\..\.."
set PY="C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe"
%PY% -u -m reality_engine.scripts.fetch_nse_api_raw --datasets nse_integrated,nse_integrated_xbrl >> reality_engine\data\logs\integrated_results.log 2>&1
%PY% -u -m reality_engine.scripts.parse_nse_results_xbrl >> reality_engine\data\logs\integrated_results.log 2>&1
echo [%date% %time%] done >> reality_engine\data\logs\integrated_results.log
