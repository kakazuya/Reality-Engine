# Agent Manager Worktree Setup Script (Windows PowerShell)
# Runs once when a managed worktree is initialized.
param()

$ErrorActionPreference = "Stop"
# Resolve project root from this script's location, not Get-Location (which is C:\Windows\System32 when run via absolute path).
$ScriptRoot = $PSScriptRoot
if (-not $ScriptRoot) { $ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot = Split-Path -Parent $ScriptRoot
$TargetDir = if ($env:WORKTREE_PATH) { $env:WORKTREE_PATH } else { $ProjectRoot }
Set-Location -LiteralPath $TargetDir

Write-Host "[Kilo Setup] Initializing Reality Engine worktree at: $TargetDir" -ForegroundColor Cyan

# 1. Create required runtime directories
$Dirs = @(
    "reality_engine\data",
    "reality_engine\data\bhavcopy",
    "reality_engine\data\pdfs",
    "reality_engine\data\reports",
    "reality_engine\data\browser_profile",
    "reality_engine\data\lancedb",
    "reality_engine\data\inbox\images",
    "reality_engine\data\inbox\pdfs",
    "reality_engine\data\inbox\text",
    "reality_engine\data\inbox\processed",
    "reality_engine\data\inbox\failed"
)

foreach ($d in $Dirs) {
    $full = Join-Path $TargetDir $d
    if (-not (Test-Path -LiteralPath $full)) {
        New-Item -ItemType Directory -Path $full -Force | Out-Null
    }
}

# 2. Dependency installation is opt-in. Setup scripts must not trigger large
#    downloads implicitly when a worktree is created.
if ($env:KILO_INSTALL_DEPS -eq "1" -and (Test-Path "requirements.txt")) {
    python -m pip install -r requirements.txt
} else {
    Write-Host "[Kilo Setup] Dependencies not installed. Set KILO_INSTALL_DEPS=1 to opt in." -ForegroundColor Yellow
}

# 3. Keep worktree setup side-effect-light; use /bootstrap explicitly for data.
Write-Host "[Kilo Setup] Runtime directories prepared. Run /bootstrap when fixture data is needed." -ForegroundColor Gray

# 4. Register the twice-daily Missed-Days Catcher with Windows Task Scheduler.
#    Runs at 16:00 IST (pre-close check) and 23:00 IST (post-close full run),
#    idempotently (delete-then-create), under SYSTEM so it fires even when the
#    user is not logged on, and with wake-to-run enabled where supported.
Write-Host "[Kilo Setup] Registering Reality Engine catch-up scheduler tasks..." -ForegroundColor Cyan
$RunScript = Join-Path $TargetDir ".kilo\run-script.ps1"
$PyExe = @(Get-Command python -ErrorAction SilentlyContinue)[0].Source
if (-not $PyExe) { $PyExe = @(Get-Command py -ErrorAction SilentlyContinue)[0].Source }
if (-not $PyExe) { $PyExe = "python" }

function Register-CatchupTask {
    param([string]$Name, [string]$Time)
    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    schtasks /delete /tn "$Name" /f 2>&1 | Out-Null
    # Use PowerShell ScheduledTasks module (avoids schtasks.exe quoting hell).
    try {
        $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RunScript`" catchup"
        $Trigger = New-ScheduledTaskTrigger -Daily -At $Time
        $Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
        $Settings = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
        Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null
        Write-Host "[Kilo Setup]   $Name -> daily $Time IST (wake-to-run enabled)" -ForegroundColor Gray
    } catch {
        # Fallback to schtasks.exe with proper backtick-quoted inner path.
        Write-Host "[Kilo Setup]   ScheduledTasks module unavailable, falling back to schtasks.exe: $_" -ForegroundColor Yellow
        $tr = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$RunScript`" catchup"
        schtasks /create /tn "$Name" /tr "$tr" /sc daily /st $Time /ru SYSTEM /rl HIGHEST /f 2>&1 | Out-Null
        try {
            $t = Get-ScheduledTask -TaskName "$Name" -ErrorAction SilentlyContinue
            if ($t) { $t.Settings.WakeToRun = $true; $t | Set-ScheduledTask -ErrorAction SilentlyContinue | Out-Null }
        } catch {}
        Write-Host "[Kilo Setup]   $Name -> daily $Time IST (wake-to-run unavailable in this edition)" -ForegroundColor Gray
    }
    $ErrorActionPreference = $prevPref
}
Register-CatchupTask "RealityEngine_Catchup_4pm" "16:00"
Register-CatchupTask "RealityEngine_Catchup_11pm" "23:00"

# WSL / cron fallback (uncomment if running under WSL instead of native Windows):
#   wsl -e bash -c 'cd "$(wslpath "$TargetDir")" && ./reality_engine/.kilo/setup-script.sh --cron'

Write-Host "[Kilo Setup] Worktree initialized successfully." -ForegroundColor Green
