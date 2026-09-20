@echo off
rem ===================================================================
rem Forecast test entry point (Windows Task Scheduler target).
rem Scores resolvable past prediction runs via the Wave B harness.
rem Register with:  python -m reality_engine.pipeline.forecast_tester --install
rem ===================================================================
setlocal
cd /d "%~dp0..\.."

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" -m reality_engine.pipeline.forecast_tester %*
exit /b %ERRORLEVEL%
