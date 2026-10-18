@echo off
rem PIB phase 2 (pib_regional.py): all PIB offices x languages, newest day first. Args passed through (e.g. --start/--end).
rem Log: reality_engine\data\logs\pib_regional.log
cd /d "%~dp0\..\.."
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.pib_regional %* >> reality_engine\data\logs\pib_regional.log 2>&1
