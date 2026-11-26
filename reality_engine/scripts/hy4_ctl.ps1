# T-242 (26 Nov 2026, Eagle): status / start / stop the always-on hy4 reading loops by PID, never by image name
# (a kill-by-name on 25 Nov 21:14 ended every worker and MCP server on the machine).
# Usable over SSH/Tailscale after the move:   pwsh -File reality_engine/scripts/hy4_ctl.ps1 status|start|stop [loop]
# Loops: transcripts (.tmp/hy4_always.sh, log hy4_lowssd.log) and ar (.tmp/hy4_ar.sh, log hy4_ar.log).
#
# 26 Nov 01:40 fix: Git bash re-launches itself (`exec bash "$0"`, `$(...)` subshells) as NEW Windows processes, so
# one recorded PID does not cover a loop, and earlier manual starts had left three transcript loops running, two
# writing obs_transcripts_394_v3.db at once.  Every action now finds the loop's processes by their EXACT command
# line (the loop script path, and readers whose --out is one of the loop's output DBs), then acts on those PIDs:
#   status  every loop instance and reader with its PID; "DUPLICATE" when more than one loop instance runs;
#   start   refuses while any instance of that loop runs (no duplicates); launches hidden; records the PID;
#   stop    ends each matched loop instance and reader by PID (taskkill /PID /T), then re-checks and lists survivors.
param([ValidateSet('status','start','stop','adopt')][string]$Action = 'status', [string]$Loop = 'all')

$Out  = 'D:\RealityEngine\hy4_out'
$Bash = 'C:\Program Files\Git\usr\bin\bash.exe'
$Loops = @{
  transcripts = @{ script = '.tmp/hy4_always.sh'; log = "$Out\hy4_lowssd.log";
                   dbs = @('obs_transcripts_fy27_v3.db', 'obs_transcripts_394_v3.db', 'obs_decks_fy27.db') }
  ar          = @{ script = '.tmp/hy4_ar.sh';     log = "$Out\hy4_ar.log"; dbs = @() }
}
$names = if ($Loop -eq 'all') { $Loops.Keys } else { @($Loop) }

function Get-LoopProcs($cfg) {
  # loop instances: bash running the loop script itself (not the `bash -lc '... exec bash <script>'` start wrapper,
  # which stays as an idle stub after the loop re-launches itself); readers: python observations whose --out VALUE
  # is one of the loop's DBs (26 Nov: matching any mention caught Wolf's recheck reader with --baseline <db>)
  $all = Get-CimInstance Win32_Process
  $script = [regex]::Escape($cfg.script)
  $wrappers = @($all | Where-Object { $_.Name -eq 'bash.exe' -and $_.CommandLine -match $script -and $_.CommandLine -match ' -lc ' })
  $loops = @($all | Where-Object { $_.Name -eq 'bash.exe' -and $_.CommandLine -match $script -and $_.CommandLine -notmatch ' -lc ' })
  $loopIds = @($loops.ProcessId)
  $roots = @($loops | Where-Object { $loopIds -notcontains $_.ParentProcessId })
  $readers = @()
  if ($cfg.dbs.Count -gt 0) {
    $readers = @($all | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'reality_engine\.v2\.observations' } | Where-Object {
      $m = [regex]::Match($_.CommandLine, '--out[= ](\S+)'); $m.Success -and ($cfg.dbs -contains (Split-Path $m.Groups[1].Value -Leaf)) })
  } else {   # ar: readers are the python children of its own loop instances
    $readers = @($all | Where-Object { $_.Name -eq 'python.exe' -and $loopIds -contains $_.ParentProcessId })
  }
  [pscustomobject]@{ roots = $roots; loops = $loops; readers = $readers; wrappers = $wrappers }
}

foreach ($n in $names) {
  $cfg = $Loops[$n]
  $procs = Get-LoopProcs $cfg
  switch ($Action) {
    'status' {
      $last = if (Test-Path $cfg.log) { (Get-Content $cfg.log -Tail 1) } else { '(no log)' }
      $flag = if ($procs.roots.Count -gt 1) { 'DUPLICATE' } elseif ($procs.roots.Count -eq 1) { 'alive' } else { 'NOT running' }
      "{0,-12} {1,-11} loop roots={2} readers={3}  last: {4}" -f $n, $flag,
        (($procs.roots | ForEach-Object ProcessId) -join ','), (($procs.readers | ForEach-Object ProcessId) -join ','), $last
    }
    'adopt' {
      if ($procs.roots.Count -ge 1) { Set-Content "$Out\$n.pid" $procs.roots[0].ProcessId; "$n adopted pid $($procs.roots[0].ProcessId) ($($procs.roots.Count) instance(s))" }
      else { "${n}: no running loop found" }
    }
    'start' {
      if ($procs.loops.Count -gt 0 -or $procs.wrappers.Count -gt 0) { "$n already running (pids $(($procs.roots | ForEach-Object ProcessId) -join ',')); stop it first"; continue }
      $p = Start-Process -WindowStyle Hidden -PassThru -FilePath $Bash -ArgumentList '-lc', "'cd /c/Users/warri/Downloads/Info_Diffusion_Model && exec bash $($cfg.script)'"
      Set-Content "$Out\$n.pid" $p.Id
      "$n started (pid $($p.Id))"
    }
    'stop' {
      $targets = @($procs.roots) + @($procs.readers) + @($procs.wrappers)
      if ($targets.Count -eq 0) { "$n not running"; continue }
      foreach ($t in $targets) { & taskkill /PID $t.ProcessId /T /F 2>$null | Out-Null }
      Start-Sleep -Seconds 2
      $left = Get-LoopProcs $cfg
      foreach ($t in @($left.loops) + @($left.readers) + @($left.wrappers)) { & taskkill /PID $t.ProcessId /F 2>$null | Out-Null }
      Start-Sleep -Seconds 1
      $left = Get-LoopProcs $cfg
      $surv = @($left.loops) + @($left.readers) + @($left.wrappers)
      if ($surv.Count) { "$n stop INCOMPLETE; survivors: $(($surv | ForEach-Object ProcessId) -join ',')" }
      else { "$n stopped (pids $(($targets | ForEach-Object ProcessId) -join ',') and their children)" }
    }
  }
}
