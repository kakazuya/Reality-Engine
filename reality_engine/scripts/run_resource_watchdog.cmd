@echo off
rem Machine-wide resource watchdog. Log: reality_engine\data\logs\resource_watchdog.log, report: resource_watchdog_report.md
cd /d "%~dp0\..\.."
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.resource_watchdog
