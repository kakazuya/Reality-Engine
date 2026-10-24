@echo off
rem Chart/image-aware vision pass: annual-report image pages (FY26 first, then older) and the
rem low-text deck leftovers the first deck pass skipped.  Free readers only (dots-3 via Kilo 1/2 and
rem OpenRouter).  Resumable: finished (doc_id,page,prompt_version) rows are skipped, so restarting is
rem always safe.  One writer per DB (the Python process takes a lock and refuses a second one).
rem
rem Logs: reality_engine\data\logs\chart_pass_run.log    (stdout/stderr of every pass)
rem       reality_engine\data\logs\chart_pass.log        (progress lines from the script)
rem       reality_engine\data\logs\chart_pass_passes.log (one line per pass)
rem
rem Start it in the background from the repository root:
rem   start "" /b cmd /c reality_engine\scripts\run_chart_pass.cmd
rem or run it in the foreground and leave it going.
cd /d "%~dp0\..\.."
set PYTHONUNBUFFERED=1
set LOG=reality_engine\data\logs\chart_pass_run.log
set PASSES=reality_engine\data\logs\chart_pass_passes.log
if not exist "reality_engine\data\logs" mkdir "reality_engine\data\logs"
set /a tries=0
:loop
set /a tries+=1
echo [%date% %time%] pass %tries%: AR FY26 >> "%LOG%"
python -u -m reality_engine.scripts.extract_ar_vision --target ar --scope fy26 --max-pages 4000 --inline-render >> "%LOG%" 2>&1
set rc1=%errorlevel%
echo [%date% %time%] ar-fy26 pass %tries% exit %rc1% >> "%PASSES%"
echo [%date% %time%] pass %tries%: deck leftovers >> "%LOG%"
python -u -m reality_engine.scripts.extract_ar_vision --target decks --max-pages 4000 >> "%LOG%" 2>&1
set rc2=%errorlevel%
echo [%date% %time%] decks pass %tries% exit %rc2% >> "%PASSES%"
echo [%date% %time%] pass %tries%: AR older >> "%LOG%"
python -u -m reality_engine.scripts.extract_ar_vision --target ar --scope older --max-pages 4000 --inline-render >> "%LOG%" 2>&1
set rc3=%errorlevel%
echo [%date% %time%] ar-older pass %tries% exit %rc3% >> "%PASSES%"
if %rc1%==0 if %rc2%==0 if %rc3%==0 goto done
if %tries% geq 200 goto done
if %rc1%==3 if %rc2%==3 if %rc3%==3 (timeout /t 30 /nobreak > nul) else (timeout /t 60 /nobreak > nul)
goto loop
:done
echo [%date% %time%] chart pass finished after %tries% pass(es) >> "%PASSES%"

