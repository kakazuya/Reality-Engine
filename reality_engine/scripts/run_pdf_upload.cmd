@echo off
rem Upload the PDFs / decks not yet on Drive (2026-10-19, Shivam: rclone instead of browser uploads).
rem Source: the "remaining" hard-link folders made by drive_upload_check.py --links (only files missing from Drive).
rem Destination: Drive folder InfoDiffusion_archive created by rclone (id 1A3MOQ...), subfolders pdfs / decks / D_pdfs.
rem Resumable: rclone copy skips files already uploaded; the loop retries after a failure (network, power).
rem Bandwidth (IST, system clock): 24 MB/s 01:00-07:00 with 8 transfers (Shivam 2026-10-20: ~300 Mbps at night, the
rem line is busy until ~1 am), 512 KB/s 07:00-13:00 (DB backup window), 4 MB/s 13:00-01:00 (RDP lag is fine).
rem Log: reality_engine\data\logs\pdf_upload.rclone.log, passes in pdf_upload.passes.log
cd /d "%~dp0\..\.."
set /a tries=0
:loop
set /a tries+=1
"C:\Users\warri\AppData\Local\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.75.1-windows-amd64\rclone.exe" copy "C:\Users\warri\Downloads\InfoDiffusion_remaining\pdfs" gdrive:pdfs --drive-root-folder-id 1A3MOQnFsYw27Vk4DVmypfdIHR9ERydHB --bwlimit "01:00,24M 07:00,512k 13:00,4M" --transfers 8 --checkers 8 --drive-chunk-size 32M --tpslimit 10 --retries 10 --low-level-retries 20 --log-level NOTICE --stats 10m --stats-one-line --log-file reality_engine\data\logs\pdf_upload.rclone.log
set rc1=%errorlevel%
"C:\Users\warri\AppData\Local\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.75.1-windows-amd64\rclone.exe" copy "C:\Users\warri\Downloads\InfoDiffusion_remaining\decks" gdrive:decks --drive-root-folder-id 1A3MOQnFsYw27Vk4DVmypfdIHR9ERydHB --bwlimit "01:00,24M 07:00,512k 13:00,4M" --transfers 8 --checkers 8 --drive-chunk-size 32M --tpslimit 10 --retries 10 --low-level-retries 20 --log-level NOTICE --stats 10m --stats-one-line --log-file reality_engine\data\logs\pdf_upload.rclone.log
set rc2=%errorlevel%
"C:\Users\warri\AppData\Local\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.75.1-windows-amd64\rclone.exe" copy "D:\RealityEngine\remaining_pdfs" gdrive:D_pdfs --drive-root-folder-id 1A3MOQnFsYw27Vk4DVmypfdIHR9ERydHB --bwlimit "01:00,24M 07:00,512k 13:00,4M" --transfers 8 --checkers 8 --drive-chunk-size 32M --tpslimit 10 --retries 10 --low-level-retries 20 --log-level NOTICE --stats 10m --stats-one-line --log-file reality_engine\data\logs\pdf_upload.rclone.log
set rc3=%errorlevel%
echo [%date% %time%] pass %tries% rc %rc1% %rc2% %rc3% >> reality_engine\data\logs\pdf_upload.passes.log
if %rc1%%rc2%%rc3%==000 goto done
if %tries% geq 50 goto done
timeout /t 300 /nobreak > nul
goto loop
:done
