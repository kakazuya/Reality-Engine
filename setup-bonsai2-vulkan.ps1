$ErrorActionPreference = "Stop"

$Url  = "https://github.com/PrismML-Eng/llama.cpp/releases/download/prism-b10685-7dffb15/llama-prism-b10685-7dffb15-bin-win-vulkan-x64.zip"
$Zip  = Join-Path $env:USERPROFILE "Downloads\llama-prism-b10685-7dffb15-bin-win-vulkan-x64.zip"
$Dest = "C:\Users\warri\prism-llama-bonsai2"
$MODEL  = "C:\Users\warri\.lmstudio\models\prism-ml\Ternary-Bonsai-2-27B-gguf\Ternary-Bonsai-2-27B-PTQ1_0.gguf"
$MMPROJ = "C:\Users\warri\.lmstudio\models\prism-ml\Ternary-Bonsai-2-27B-gguf\Ternary-Bonsai-2-27B-mmproj-BF16.gguf"

Write-Host "URL : $Url"
Write-Host "ZIP : $Zip"
Write-Host "DEST: $Dest"

# 1) Download (skip if already exists and size > 10MB)
$needDownload = $true
if (Test-Path -LiteralPath $Zip) {
    $size = (Get-Item -LiteralPath $Zip).Length
    Write-Host ("Existing zip size: {0} bytes ({1:N2} MB)" -f $size, ($size / 1MB))
    if ($size -gt 10MB) {
        Write-Host "Skip download: existing zip > 10MB."
        $needDownload = $false
    } else {
        Write-Host "Existing zip too small, re-downloading..."
    }
}
if ($needDownload) {
    Write-Host "Downloading with Invoke-WebRequest..."
    Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing
    Write-Host "Download complete."
}

# 2) Extract (create dir, Expand-Archive -Force)
if (!(Test-Path -LiteralPath $Dest)) {
    New-Item -ItemType Directory -Path $Dest | Out-Null
    Write-Host "Created: $Dest"
}
Write-Host "Extracting to $Dest ..."
Expand-Archive -Path $Zip -DestinationPath $Dest -Force
Write-Host "Extract complete."

# 3) Resolve $BIN (handle both bin\llama-server.exe and llama-server.exe layouts)
$BIN = $null
$cand1 = Join-Path $Dest "bin\llama-server.exe"
$cand2 = Join-Path $Dest "llama-server.exe"
if (Test-Path -LiteralPath $cand1) {
    $BIN = $cand1
} elseif (Test-Path -LiteralPath $cand2) {
    $BIN = $cand2
} else {
    $found = Get-ChildItem -Path $Dest -Filter "llama-server.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $BIN = $found.FullName }
}
Write-Host "BIN: $BIN"

# 4) Verify
Write-Host ("Test-Path BIN    ({0}): {1}" -f $BIN, (Test-Path $BIN))
Write-Host ("Test-Path MODEL  ({0}): {1}" -f $MODEL, (Test-Path -LiteralPath $MODEL))
Write-Host ("Test-Path MMPROJ ({0}): {1}" -f $MMPROJ, (Test-Path -LiteralPath $MMPROJ))
if (!(Test-Path $BIN)) { throw "llama-server.exe not found under $Dest" }

Write-Host "Running version check..."
& $BIN --version

# 5) Tier-1 conservative server command (manual start only - NOT auto-started here)
Write-Host ""
Write-Host "TIER-1 CONSERVATIVE (RX 6700 XT 12GB-safe, manual start):"
$cmd = "& `"$BIN`" -m `"$MODEL`" --mmproj `"$MMPROJ`" --host 127.0.0.1 --port 8080 -c 4096 --n-gpu-layers 45 --threads 8 --temp 0.7 --top-p 0.9 --repeat-penalty 1.1"
Write-Host $cmd
