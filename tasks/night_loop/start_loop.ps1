# Start one loop session detached (Win32_Process.Create), outside Claude Code's background-shell reaper.
# usage: powershell -NoProfile -ExecutionPolicy Bypass -File tasks/night_loop/start_loop.ps1 <NN>
param([string]$N)
$repo = 'C:\Users\warri\Downloads\Info_Diffusion_Model'
$log = "D:\RealityEngine\night_loop\transcripts\loop_$('{0:D2}' -f [int]$N).out"
$cmd = "cmd /c `"C:\Users\warri\AppData\Local\Programs\Python\Python314\python.exe tasks\night_loop\run_loop.py $N > $log 2>&1`""
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=$cmd; CurrentDirectory=$repo}
"started pid $($r.ProcessId) log $log"
