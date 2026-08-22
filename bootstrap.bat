@echo off
REM ===========================================================================
REM Reality Engine - Windows Command Prompt Bootstrap Launcher
REM ===========================================================================
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1" %*
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Bootstrap script failed with exit code %ERRORLEVEL%.
    exit /b %ERRORLEVEL%
)
endlocal
