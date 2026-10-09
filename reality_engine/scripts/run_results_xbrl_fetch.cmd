@echo off
rem Resumable download of NSE financial-results XBRL files (skips files already on disk).
rem Runs detached from any Claude session; log in reality_engine\data\logs\.
cd /d C:\Users\warri\Downloads\Info_Diffusion_Model
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.fetch_nse_api_raw --datasets nse_results_xbrl >> reality_engine\data\logs\fetch_nse_results_xbrl.log 2>&1
