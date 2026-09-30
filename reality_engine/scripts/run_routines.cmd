@echo off
rem ===================================================================
rem Clock-time routines dispatcher (Windows Task Scheduler target).
rem Every 5 minutes: run every due routine (LAST.md chained).
rem Register with:  python -m reality_engine.pipeline.routines --install
rem ===================================================================
setlocal
cd /d "%~dp0..\.."

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" -m reality_engine.pipeline.routines --tick %*
exit /b %ERRORLEVEL%
