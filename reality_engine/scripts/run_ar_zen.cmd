@echo off
rem Annual reports, Zen route: OpenCode Zen free models (register reality_engine\scripts\zen_models.json) via opencode run, oldest first.
rem Restarts after a crash; exit 0 = nothing left. Log: reality_engine\data\logs\ingest_annual_reports_zen.log
cd /d "%~dp0\..\.."
set /a tries=0
:loop
set /a tries+=1
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.ingest_annual_reports --route zen %*
set rc=%errorlevel%
echo [%date% %time%] pass %tries% exit %rc% >> reality_engine\data\logs\ingest_annual_reports_zen.passes.log
if %rc%==0 goto done
if %tries% geq 200 goto done
timeout /t 30 /nobreak > nul
goto loop
:done
