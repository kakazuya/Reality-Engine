@echo off
REM ---------------------------------------------------------------------------
REM Weekly SEBI filing ingestion (DRHP/Prospectus -> dense substrate).
REM Registered as a Windows Scheduled Task; see tasks/README or run:
REM   schtasks /query /tn "RealityEngine_WeeklySEBIIngest"
REM
REM REALITY_ENGINE_GPU_DUTY caps the DirectML embedder so the desktop compositor
REM keeps headroom on this single-GPU machine (no iGPU).
REM ---------------------------------------------------------------------------
set REALITY_ENGINE_GPU_DUTY=0.85
set REALITY_ENGINE_EMBED_BACKEND=auto
set REALITY_ENGINE_EMBED_SERVER=http://127.0.0.1:8099
cd /d "%~dp0..\.."
python -m reality_engine.scripts.weekly_sebi_ingest --since 2021 --workers 4 --ingest-workers 2 --resolve-workers 6 %* >> "reality_engine\data\logs\offer_backfill\weekly_task.log" 2>&1
exit /b %ERRORLEVEL%
