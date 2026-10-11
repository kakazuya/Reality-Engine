@echo off
rem Annual-report fact extraction with the free passed readers (LongCat + Gemma 4 31B on every Google key).
rem Restarts after a crash; exit 0 = nothing left. Log: reality_engine\data\logs\ingest_annual_reports.log
cd /d "%~dp0\..\.."
set /a tries=0
:loop
set /a tries+=1
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.ingest_annual_reports %*
set rc=%errorlevel%
echo [%date% %time%] pass %tries% exit %rc% >> reality_engine\data\logs\ingest_annual_reports.passes.log
if %rc%==0 goto done
if %tries% geq 200 goto done
timeout /t 30 /nobreak > nul
goto loop
:done
