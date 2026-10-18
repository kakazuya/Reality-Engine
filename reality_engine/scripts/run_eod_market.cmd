@echo off
rem End-of-day market update (scheduled task RealityEngine-EODMarket, weekdays 19:35). Log: data\logs\eod_market.log
cd /d "%~dp0\..\.."
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.run_eod_market >> reality_engine\data\logs\eod_market.log 2>&1
