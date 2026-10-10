@echo off
rem Night watchdog for the deck-figure extractor. Log: reality_engine\data\logs\deck_extract_watchdog.log
cd /d "%~dp0\..\.."
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.deck_extract_watchdog
