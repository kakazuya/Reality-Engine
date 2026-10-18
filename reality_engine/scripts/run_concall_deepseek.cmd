@echo off
rem 2026 concall transcripts -> DeepSeek V4.1 Flash on OpenCode Go key 2 (concall_deepseek.py). Restarts after a crash.
rem Log: reality_engine\data\logs\concall_deepseek.log ; output reality_engine\data\concall_facts.db
cd /d "%~dp0\..\.."
set /a tries=0
:loop
set /a tries+=1
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.concall_deepseek --workers 8 %*
set rc=%errorlevel%
echo [%date% %time%] pass %tries% exit %rc% >> reality_engine\data\logs\concall_deepseek.passes.log
if %rc%==0 goto done
if %tries% geq 50 goto done
timeout /t 60 /nobreak > nul
goto loop
:done
