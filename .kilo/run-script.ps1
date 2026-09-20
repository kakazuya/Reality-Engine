# Agent Manager Run Script (Windows PowerShell)
# Starts the Streamlit financial terminal dashboard, runs the catch-up scheduler
# when invoked with the "catchup" argument (used by the scheduled tasks),
# or runs the Wave A nightly chain with the "nightly" argument.
param(
    [string]$Task = ""
)

# Resolve project root from this script's location, not Get-Location.
$ScriptRoot = $PSScriptRoot
if (-not $ScriptRoot) { $ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot = Split-Path -Parent $ScriptRoot
$TargetDir = if ($env:WORKTREE_PATH) { $env:WORKTREE_PATH } else { $ProjectRoot }
Set-Location -LiteralPath $TargetDir

# Resolve a Python interpreter so the script works under any account (incl. SYSTEM
# for the scheduled catch-up tasks) without relying on a user PATH.
$PyExe = @(Get-Command python -ErrorAction SilentlyContinue)[0].Source
if (-not $PyExe) { $PyExe = @(Get-Command py -ErrorAction SilentlyContinue)[0].Source }
if (-not $PyExe) { $PyExe = "python" }

if ($Task -eq "catchup") {
    Write-Host "[Kilo Run] Running Reality Engine missed-days catcher..." -ForegroundColor Cyan
    & $PyExe -m reality_engine.pipeline.catchup_scheduler
    exit $LASTEXITCODE
}

if ($Task -eq "nightly") {
    Write-Host "[Kilo Run] Running Reality Engine Wave A nightly chain..." -ForegroundColor Cyan
    & $PyExe reality_engine/cli.py nightly --part all
    exit $LASTEXITCODE
}

Write-Host "[Kilo Run] Launching Reality Engine Streamlit Terminal..." -ForegroundColor Cyan
& $PyExe reality_engine/cli.py dashboard --port 8501 --host localhost
