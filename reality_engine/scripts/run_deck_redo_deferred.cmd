@echo off
rem Second readings for the pages marked "second reading deferred" (re-renders only those pages, reuses their primary reading).
call "%~dp0run_deck_extract.cmd" --redo-deferred
