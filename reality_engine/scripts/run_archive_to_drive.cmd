@echo off
rem Archive raw document files to Google Drive (rclone remote "gdrive", scope drive.file), then verify every file by MD5.
rem Copy only: nothing local is deleted (Shivam, 2026-10-17: delete local copies only after he confirms).
rem Re-runnable: rclone skips files already on Drive with the same size and MD5.
rem Logs: reality_engine\data\logs\archive_<folder>.log (copy) and archive_<folder>_check.log (verification).
setlocal enabledelayedexpansion
cd /d "%~dp0\..\.."
set RCLONE=C:\Users\warri\AppData\Local\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.75.1-windows-amd64\rclone.exe
for %%F in (pdfs decks) do (
  "%RCLONE%" copy "reality_engine\data\%%F" "gdrive:InfoDiffusion_archive/%%F" --checksum --transfers 8 --checkers 16 --drive-chunk-size 128M --stats 5m --stats-one-line --log-level INFO --log-file "reality_engine\data\logs\archive_%%F.log"
  echo [%date% %time%] copy %%F exit !errorlevel! >> reality_engine\data\logs\archive_passes.log
  "%RCLONE%" check "reality_engine\data\%%F" "gdrive:InfoDiffusion_archive/%%F" --one-way --checkers 16 --log-level NOTICE --log-file "reality_engine\data\logs\archive_%%F_check.log" --missing-on-dst "reality_engine\data\logs\archive_%%F_missing.txt" --differ "reality_engine\data\logs\archive_%%F_differ.txt"
  echo [%date% %time%] check %%F exit !errorlevel! >> reality_engine\data\logs\archive_passes.log
)
