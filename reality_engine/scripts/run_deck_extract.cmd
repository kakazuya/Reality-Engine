@echo off
rem Deck-figure extraction, run until there is nothing left to read.
rem  - exit 3: the pass read pages; go round again (decks may still be arriving from fetch_decks.py)
rem  - exit 0: a pass found nothing new; stop
rem  - anything else: crash (MuPDF can kill the process on a malformed PDF; the file gets a strike and is
rem    skipped after two), restart after 20 s
rem Resumable: finished pages are never re-read. Log: reality_engine\data\logs\extract_deck_figures.log
cd /d "%~dp0\..\.."
set /a tries=0
:loop
set /a tries+=1
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.extract_deck_figures %*
set rc=%errorlevel%
echo [%date% %time%] pass %tries% exit %rc% >> reality_engine\data\logs\extract_deck_figures.passes.log
if %rc%==0 goto done
if %tries% geq 500 goto done
if %rc%==3 (timeout /t 300 /nobreak > nul) else (timeout /t 20 /nobreak > nul)
goto loop
:done
