' Run a .cmd hidden (window style 0), wait for it, and return its exit code so
' Task Scheduler records failures instead of a fire-and-forget 0.
rc = CreateObject("Wscript.Shell").Run("""" & WScript.Arguments(0) & """", 0, True)
WScript.Quit rc
