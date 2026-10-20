# One-time, run in an ADMINISTRATOR PowerShell (Shivam): lets the crash-recovery, EOD, backup and DeepSeek-heartbeat tasks run at boot
# WITHOUT anyone logging in (S4U: runs as warri, no password stored). Without this they wait until warri logs on.
#   powershell -ExecutionPolicy Bypass -File reality_engine\scripts\setup_boot_tasks_admin.ps1
$root = 'C:\Users\warri\Downloads\Info_Diffusion_Model'
$p = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited
$set = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$a = New-ScheduledTaskAction -Execute 'C:\Users\warri\AppData\Local\Programs\Python\Python314\pythonw.exe' -Argument '-u -m reality_engine.scripts.boot_recover' -WorkingDirectory $root
Register-ScheduledTask -TaskName 'RealityEngine-BootRecover' -Trigger @((New-ScheduledTaskTrigger -AtStartup), (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME")) -Action $a -Principal $p -Settings $set -Description 'Crash recovery: restart all Reality Engine jobs after a reboot / power cut (boot_recover.py).' -Force | Out-Null
foreach ($n in 'RealityEngine-EODMarket', 'RealityEngine-DBBackup', 'RealityEngine-DeepSeekHeartbeat') { Set-ScheduledTask -TaskName $n -Principal $p -Settings $set | Out-Null }
Get-ScheduledTask -TaskName 'RealityEngine-BootRecover', 'RealityEngine-EODMarket', 'RealityEngine-DBBackup', 'RealityEngine-DeepSeekHeartbeat' | ForEach-Object { '{0}: {1}' -f $_.TaskName, $_.Principal.LogonType }
