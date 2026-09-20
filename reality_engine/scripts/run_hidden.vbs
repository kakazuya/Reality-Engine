' ===================================================================
' run_hidden.vbs — headless launcher for RealityEngine scheduled tasks.
' Usage: wscript.exe run_hidden.vbs "<target.cmd>" [args...]
' Runs the target with window style 0 (SW_HIDE: no console, no PowerShell
' window) and waits, propagating its exit code so Task Scheduler's
' Last Result still reflects the real run.
' Called by _task_command() in pipeline/{continuous_loop,forecast_tester,
' capacity_loop,news_loop}.py — never run by hand.
' NOTE: no WScript.Echo anywhere — under wscript.exe Echo pops a message
' box, which defeats the headless purpose. Failures exit silently nonzero.
' ===================================================================
Option Explicit

Dim sh, target, args, i, a, rc
Set sh = CreateObject("WScript.Shell")

If WScript.Arguments.Count = 0 Then
  WScript.Quit 1
End If

target = WScript.Arguments(0)
args = ""
For i = 1 To WScript.Arguments.Count - 1
  a = WScript.Arguments(i)
  If InStr(a, " ") > 0 And Left(a, 1) <> """" Then
    a = """" & a & """"
  End If
  args = args & " " & a
Next

rc = sh.Run("""" & target & """" & args, 0, True)
WScript.Quit rc
