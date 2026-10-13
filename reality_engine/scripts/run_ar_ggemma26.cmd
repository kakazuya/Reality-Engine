@echo off
rem Annual reports, Google route 3: Gemma 4 26B on every GEMINI_API_KEY (36k-char pieces, exhaustive prompt), Gemma 31B re-reads empty answers; oldest first.
rem Restarts after a crash; exit 0 = nothing left. Log: reality_engine\data\logs\ingest_annual_reports_google_gemma-4-26b.log
cd /d "%~dp0\..\.."
set /a tries=0
:loop
set /a tries+=1
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.ingest_annual_reports --route google --google-model gemma-4-26b-a4b-it %*
set rc=%errorlevel%
echo [%date% %time%] pass %tries% exit %rc% >> reality_engine\data\logs\ingest_annual_reports_google_gemma-4-26b.passes.log
if %rc%==0 goto done
if %tries% geq 200 goto done
timeout /t 30 /nobreak > nul
goto loop
:done
