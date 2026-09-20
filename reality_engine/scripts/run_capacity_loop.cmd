@echo off
rem ===================================================================
rem Capacity governor entry point (Windows Task Scheduler target).
rem Evaluates explainer-capacity moves; report-only unless --apply-capacity.
rem Register with:  python -m reality_engine.pipeline.capacity_loop --install
rem ===================================================================
setlocal
cd /d "%~dp0..\.."

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" -m reality_engine.pipeline.capacity_loop %*
exit /b %ERRORLEVEL%
