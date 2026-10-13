@echo off
rem Overnight profile tuner: finishes pending exhaustive-prompt tests, switches passing models to the exhaustive prompt
rem in reader_profiles.json and restarts their worker. Log: reality_engine\data\logs\profile_tuner.log
cd /d "%~dp0\..\.."
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.profile_tuner >> reality_engine\data\logs\profile_tuner.out 2>&1
