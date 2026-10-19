@echo off
rem Database backup to Google Drive (scheduled task RealityEngine-DBBackup, daily 05:00; uploads stop at 13:00).
cd /d "%~dp0\..\.."
"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe" -u -m reality_engine.scripts.backup_dbs_to_drive >> reality_engine\data\logs\db_backup.out.log 2>&1
