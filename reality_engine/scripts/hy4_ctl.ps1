# T-242 (26 Nov 2026, Eagle): status / start / stop the always-on hy4 reading loops by PID FILE, never by image name
# (a kill-by-name on 25 Nov 21:14 ended every worker and MCP server on the machine).
# Usable over SSH/Tailscale after the move:   pwsh -File reality_engine/scripts/hy4_ctl.ps1 status|start|stop [loop]
# Loops: transcripts (.tmp/hy4_always.sh, log hy4_lowssd.log) and ar (.tmp/hy4_ar.sh, log hy4_ar.log).
# start launches the loop hidden (no window), records the loop's bash PID in D:/RealityEngine/hy4_out/<loop>.pid,
# and refuses if that PID is still alive. stop kills ONLY the recorded PID and its child tree (taskkill /PID /T).
param([ValidateSet('status','start','stop','adopt')][string]$Action = 'status', [string]$Loop = 'all')

$Repo = 'C:\Users\warri\Downloads\Info_Diffusion_Model'
$Out  = 'D:\RealityEngine\hy4_out'
$Bash = 'C:\Program Files\Git\usr\bin\bash.exe'
$Loops = @{
  transcripts = @{ script = '.tmp/hy4_always.sh'; log = "$Out\hy4_lowssd.log" }
  ar          = @{ script = '.tmp/hy4_ar.sh';     log = "$Out\hy4_ar.log" }
}
$names = if ($Loop -eq 'all') { $Loops.Keys } else { @($Loop) }

function Get-LoopPid($name) {
  $f = "$Out\$name.pid"
  if (Test-Path $f) { [int](Get-Content $f -TotalCount 1) } else { $null }
}
function Test-Alive($procId) { $procId -and (Get-Process -Id $procId -ErrorAction SilentlyContinue) }

foreach ($n in $names) {
  $cfg = $Loops[$n]
  $procId = Get-LoopPid $n
  switch ($Action) {
    'status' {
      $alive = if (Test-Alive $procId) { 'alive' } else { 'NOT running' }
      $last = if (Test-Path $cfg.log) { (Get-Content $cfg.log -Tail 1) } else { '(no log)' }
      "{0,-12} pid={1,-6} {2,-12} last: {3}" -f $n, $procId, $alive, $last
    }
    'adopt' {   # record the PID of a loop that is already running (started before this script existed)
      $p = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match [regex]::Escape($cfg.script) -and $_.CommandLine -match '-lc' } | Select-Object -First 1
      if ($p) { Set-Content "$Out\$n.pid" $p.ProcessId; "$n adopted pid $($p.ProcessId)" } else { "${n}: no running loop found" }
    }
    'start' {
      if (Test-Alive $procId) { "$n already running (pid $procId)"; continue }
      $p = Start-Process -WindowStyle Hidden -PassThru -FilePath $Bash -ArgumentList '-lc', "'cd /c/Users/warri/Downloads/Info_Diffusion_Model && exec bash $($cfg.script)'"
      Set-Content "$Out\$n.pid" $p.Id
      "$n started (pid $($p.Id))"
    }
    'stop' {
      if (-not (Test-Alive $procId)) { "$n not running"; continue }
      & taskkill /PID $procId /T /F | Out-Null
      "$n stopped (pid $procId and its children)"
    }
  }
}
