@echo off
rem NSE circuit hits + price bands / surveillance stages, 2019 -> (fetch_nse_pr.py). Log: reality_engine\data\logs\nse_pr.log
cd /d "%~dp0\..\.."
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.fetch_nse_pr --start 2019-01-01 >> reality_engine\data\logs\nse_pr.log 2>&1
