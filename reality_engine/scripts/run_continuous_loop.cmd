@echo off
rem ===================================================================
rem Continuous loop entry point (Windows Task Scheduler target).
rem Every 30 minutes: harness health brief + one unattended agent pass.
rem Register with:  python -m reality_engine.pipeline.continuous_loop --install
rem ===================================================================
setlocal
cd /d "%~dp0..\.."

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" -m reality_engine.pipeline.continuous_loop --agent %*
exit /b %ERRORLEVEL%
