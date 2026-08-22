<#
.SYNOPSIS
    Reality Engine - Windows Environment Bootstrap & Verification Script

.DESCRIPTION
    Initializes the Python environment, installs dependencies from requirements.txt,
    ensures required data and inbox directory structures exist, initializes the
    SQLite database with ontologies and canonical causal graph nodes, and verifies
    the system via the unit test suite.

.PARAMETER SkipVenv
    Skip virtual environment creation and use the currently active Python interpreter.

.PARAMETER VenvPath
    Path to the virtual environment directory. Defaults to '.venv'.

.PARAMETER PythonExe
    Name or path of the base Python executable to use. Defaults to 'python'.

.PARAMETER SkipInstall
    Skip pip dependency installation step.

.PARAMETER FullInstall
    Install optional dependencies (OCR, LanceDB, Playwright, Telethon) from requirements-optional.txt.

.PARAMETER SkipSeed
    Skip database ontology and canonical causal graph seeding.

.PARAMETER SkipTests
    Skip running the unittest test suite after setup.

.EXAMPLE
    .\bootstrap.ps1
    .\bootstrap.ps1 -SkipVenv
    .\bootstrap.ps1 -FullInstall
#>

[CmdletBinding()]
param (
    [switch]$SkipVenv,
    [string]$VenvPath = ".venv",
    [string]$PythonExe = "python",
    [switch]$SkipInstall,
    [switch]$FullInstall,
    [switch]$SkipSeed,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location -LiteralPath $ScriptRoot

Write-Host "===========================================================================" -ForegroundColor Cyan
Write-Host "  REALITY ENGINE - WINDOWS BOOTSTRAP & VERIFICATION" -ForegroundColor Cyan
Write-Host "===========================================================================" -ForegroundColor Cyan
Write-Host "Workspace Root : $ScriptRoot" -ForegroundColor Gray
Write-Host "Timestamp      : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray
Write-Host ""

# -----------------------------------------------------------------------------
# 1. Verify Python Availability and Version
# -----------------------------------------------------------------------------
Write-Host "[1/5] Checking Python installation..." -ForegroundColor Yellow
$BasePython = Get-Command $PythonExe -ErrorAction SilentlyContinue

if (-not $BasePython) {
    Write-Host "[ERROR] Python executable '$PythonExe' was not found in PATH." -ForegroundColor Red
    Write-Host "Please install Python 3.10+ from https://www.python.org/ and ensure it is added to PATH." -ForegroundColor Red
    exit 1
}

$PyVersionRaw = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
Write-Host "Found Python executable: $($BasePython.Source) (v$PyVersionRaw)" -ForegroundColor Green

$PyMajor, $PyMinor = (& $PythonExe -c "import sys; print(f'{sys.version_info.major} {sys.version_info.minor}')").Split(" ")
if ([int]$PyMajor -lt 3 -or ([int]$PyMajor -eq 3 -and [int]$PyMinor -lt 10)) {
    Write-Host "[ERROR] Reality Engine requires Python 3.10 or higher. Current version is $PyVersionRaw." -ForegroundColor Red
    exit 1
}

# -----------------------------------------------------------------------------
# 2. Virtual Environment Configuration
# -----------------------------------------------------------------------------
Write-Host "`n[2/5] Configuring Python environment..." -ForegroundColor Yellow

if ($SkipVenv) {
    Write-Host "Skipping virtual environment creation (-SkipVenv specified). Using active Python." -ForegroundColor Gray
    $ActivePython = $PythonExe
} else {
    $VenvFullPath = Join-Path $ScriptRoot $VenvPath
    $VenvPy = Join-Path $VenvFullPath "Scripts\python.exe"

    if (-not (Test-Path -LiteralPath $VenvFullPath)) {
        Write-Host "Creating virtual environment at: $VenvFullPath" -ForegroundColor Gray
        & $PythonExe -m venv $VenvFullPath
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
            exit $LASTEXITCODE
        }
    }

    if (Test-Path -LiteralPath $VenvPy) {
        $ActivePython = $VenvPy
        Write-Host "Using virtual environment Python: $ActivePython" -ForegroundColor Green
    } else {
        Write-Host "[WARNING] Virtual environment python.exe not found at $VenvPy. Falling back to $PythonExe." -ForegroundColor Yellow
        $ActivePython = $PythonExe
    }
}

# -----------------------------------------------------------------------------
# 3. Dependency Installation
# -----------------------------------------------------------------------------
Write-Host "`n[3/5] Installing dependencies..." -ForegroundColor Yellow

if ($SkipInstall) {
    Write-Host "Skipping dependency installation (-SkipInstall specified)." -ForegroundColor Gray
} else {
    Write-Host "Upgrading pip, setuptools, and wheel..." -ForegroundColor Gray
    & $ActivePython -m pip install --upgrade pip setuptools wheel --quiet

    $ReqFile = if ($FullInstall -and (Test-Path "requirements-optional.txt")) {
        "requirements-optional.txt"
    } else {
        "requirements.txt"
    }

    if (Test-Path $ReqFile) {
        Write-Host "Installing dependencies from $ReqFile..." -ForegroundColor Gray
        & $ActivePython -m pip install -r $ReqFile
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Dependency installation encountered errors." -ForegroundColor Red
            exit $LASTEXITCODE
        }
        Write-Host "Dependencies successfully installed." -ForegroundColor Green
    } else {
        Write-Host "[WARNING] Manifest $ReqFile not found. Skipping pip install." -ForegroundColor Yellow
    }
}

# -----------------------------------------------------------------------------
# 4. Create Runtime Directory Layout & Initialize Database
# -----------------------------------------------------------------------------
Write-Host "`n[4/5] Initializing runtime directories & database..." -ForegroundColor Yellow

$RuntimeDirs = @(
    "reality_engine\data",
    "reality_engine\data\bhavcopy",
    "reality_engine\data\pdfs",
    "reality_engine\data\reports",
    "reality_engine\data\browser_profile",
    "reality_engine\data\lancedb",
    "reality_engine\data\inbox",
    "reality_engine\data\inbox\images",
    "reality_engine\data\inbox\pdfs",
    "reality_engine\data\inbox\text",
    "reality_engine\data\inbox\processed",
    "reality_engine\data\inbox\failed"
)

foreach ($dir in $RuntimeDirs) {
    $fullDir = Join-Path $ScriptRoot $dir
    if (-not (Test-Path -LiteralPath $fullDir)) {
        New-Item -ItemType Directory -Path $fullDir -Force | Out-Null
        Write-Host "  Created: $dir" -ForegroundColor Gray
    }
}

if ($SkipSeed) {
    Write-Host "Skipping database ontology seeding (-SkipSeed specified)." -ForegroundColor Gray
} else {
    Write-Host "Seeding parameter ontologies and canonical causal graph..." -ForegroundColor Gray
    & $ActivePython reality_engine/cli.py seed-ontologies
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Database seeding failed." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# -----------------------------------------------------------------------------
# 5. Verification via Test Suite
# -----------------------------------------------------------------------------
Write-Host "`n[5/5] Running verification test suite..." -ForegroundColor Yellow

if ($SkipTests) {
    Write-Host "Skipping verification test suite (-SkipTests specified)." -ForegroundColor Gray
} else {
    Write-Host "Executing unit tests..." -ForegroundColor Gray
    & $ActivePython -m unittest discover -s reality_engine/tests -p "test_*.py"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Verification tests failed. Please review the output above." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "All verification tests passed successfully." -ForegroundColor Green
}

# -----------------------------------------------------------------------------
# Completion Summary
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "===========================================================================" -ForegroundColor Green
Write-Host "  BOOTSTRAP COMPLETED SUCCESSFULLY" -ForegroundColor Green
Write-Host "===========================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next Steps & Operational Commands:" -ForegroundColor Cyan
Write-Host "  1. Launch Web Dashboard :  $ActivePython reality_engine/cli.py dashboard"
Write-Host "  2. Screen Top Stocks    :  $ActivePython reality_engine/cli.py screen --universe nifty200 --top 10"
Write-Host "  3. Daily Alpha Report   :  $ActivePython reality_engine/cli.py run-daily-alpha"
Write-Host "  4. Run Ingestion Pipeline: $ActivePython reality_engine/cli.py run-phase1 --days 25 --top 200"
Write-Host ""
