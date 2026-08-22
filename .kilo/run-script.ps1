# Agent Manager Run Script (Windows PowerShell)
# Starts the Streamlit financial terminal dashboard.
param()

$TargetDir = if ($env:WORKTREE_PATH) { $env:WORKTREE_PATH } else { Get-Location }
Set-Location -LiteralPath $TargetDir

Write-Host "[Kilo Run] Launching Reality Engine Streamlit Terminal..." -ForegroundColor Cyan
python reality_engine/cli.py dashboard --port 8501 --host localhost
