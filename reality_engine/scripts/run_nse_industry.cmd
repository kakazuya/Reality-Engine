@echo off
rem NSE industry classification for all listed companies (fetch_nse_industry.py). Log: reality_engine\data\logs\nse_industry.log
cd /d "%~dp0\..\.."
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.fetch_nse_industry >> reality_engine\data\logs\nse_industry.log 2>&1
