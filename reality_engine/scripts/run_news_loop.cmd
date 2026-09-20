@echo off
rem ===================================================================
rem News loop entry point (Windows Task Scheduler target).
rem Daily: official-outlet RSS ingest + infographic capture + prune.
rem Register with:  python -m reality_engine.pipeline.news_loop --install
rem ===================================================================
setlocal
cd /d "%~dp0..\.."

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" -m reality_engine.pipeline.news_loop --run %*
exit /b %ERRORLEVEL%
