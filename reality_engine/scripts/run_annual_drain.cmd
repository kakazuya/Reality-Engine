@echo off
REM ---------------------------------------------------------------------------
REM Annual-report drain watchdog (hourly): resumes annual_n200 ingestion.
REM Idempotent and resumable; the scheduled task must not overlap the live
REM writer because extra SQLite writers add I/O spikes without increasing work.
REM Resource targets are deliberately below the 97% user ceiling.
REM ---------------------------------------------------------------------------
set REALITY_ENGINE_GPU_DUTY=0.90
set REALITY_ENGINE_VULKAN_BATCH=96
set REALITY_ENGINE_CPU_TARGET=0.90
set REALITY_ENGINE_DISK_TARGET=0.90
set REALITY_ENGINE_MEMORY_TARGET=0.85
set REALITY_ENGINE_RESOURCE_POLL=0.25
set REALITY_ENGINE_RESOURCE_MAX_WAIT=30
set REALITY_ENGINE_MIN_FREE_GB=20
set REALITY_ENGINE_RESOURCE_GUARD=1
set REALITY_ENGINE_EMBED_BACKEND=vulkan
set REALITY_ENGINE_EMBED_SERVER=http://127.0.0.1:8099
cd /d "%~dp0..\.."
python -m reality_engine.scripts.run_ingestion_queue --only annual_n200 --batch 10 >> "reality_engine\data\logs\annual_drain_watchdog.log" 2>&1
exit /b %ERRORLEVEL%
