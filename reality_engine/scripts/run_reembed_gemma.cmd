@echo off
rem EmbeddingGemma re-embed of every chunk (reembed_gemma.py, Shivam approved 2026-10-19). Resumable; restarts after a crash.
rem Waits until the 2026 transcript chunk job (concall_2026_chunk.log) is complete: one GPU embedder at a time.
rem Log: reality_engine\data\logs\reembed_gemma.log
cd /d "%~dp0\..\.."
:wait
findstr /c:"RUN_COMPLETE" reality_engine\data\logs\concall_2026_chunk.log > nul 2>&1
if errorlevel 1 (timeout /t 120 /nobreak > nul & goto wait)
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.reembed_gemma --plan-new >> reality_engine\data\logs\reembed_gemma.out.log 2>&1
set /a tries=0
:loop
set /a tries+=1
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.reembed_gemma %* >> reality_engine\data\logs\reembed_gemma.out.log 2>&1
set rc=%errorlevel%
echo [%date% %time%] pass %tries% exit %rc% >> reality_engine\data\logs\reembed_gemma.passes.log
if %rc%==0 goto done
if %tries% geq 30 goto done
timeout /t 120 /nobreak > nul
goto loop
:done
