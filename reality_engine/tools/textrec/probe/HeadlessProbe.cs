// Windowless evidence probe for the "nothing on the HP screen" rule (Shivam,
// 1 Nov 2026).  Runs inside the interactive session as a GUI-subsystem WinExe:
// no console, no window, no focus.  Every --sample-ms it records the foreground
// window (process and title) and every *visible* top-level window owned by
// textrec, conhost, cmd, powershell, pwsh or python.  Once a second it snapshots
// the session's process table (pid, parent pid, name) so a conhost.exe child of
// textrec cannot hide, and writes a full table at start and end.
//
// Output: one JSON object per line, appended to --out.  Pass means every
// "sample" has foreground.watched=false and no "watched" windows, and the
// process table never shows a conhost/cmd/powershell/pwsh/python child of the
// helper.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

internal static class Probe
{
    private const int DWMWA_CLOAKED = 14;
    private const int GWL_EXSTYLE = -20;
    private const long WS_EX_TOOLWINDOW = 0x00000080;
    private const uint TH32CS_SNAPPROCESS = 0x00000002;

    // The processes the brief says must never own a visible window here.
    private static readonly string[] Watched =
    {
        "textrec", "textrec20", "conhost", "cmd", "powershell", "pwsh", "python",
    };

    private delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr extra);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct PROCESSENTRY32W
    {
        public uint dwSize;
        public uint cntUsage;
        public uint th32ProcessID;
        public IntPtr th32DefaultHeapID;
        public uint th32ModuleID;
        public uint cntThreads;
        public uint th32ParentProcessID;
        public int pcPriClassBase;
        public uint dwFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string szExeFile;
    }

    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(
        IntPtr hwnd, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowTextW(
        IntPtr hwnd, StringBuilder text, int count);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowTextLengthW(
        IntPtr hwnd);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] private static extern bool EnumWindows(
        EnumWindowsProc callback, IntPtr extra);
    [DllImport("user32.dll")] private static extern IntPtr GetWindowLongPtrW(
        IntPtr hwnd, int index);
    [DllImport("dwmapi.dll")] private static extern int DwmGetWindowAttribute(
        IntPtr hwnd, int attribute, out int value, int size);
    [DllImport("kernel32.dll")] private static extern bool ProcessIdToSessionId(
        uint pid, out uint session);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern IntPtr
        CreateToolhelp32Snapshot(uint flags, uint pid);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool Process32FirstW(IntPtr snapshot, ref PROCESSENTRY32W entry);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool Process32NextW(IntPtr snapshot, ref PROCESSENTRY32W entry);
    [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);

    private static StreamWriter _log;
    private static readonly Dictionary<uint, string> Names = new();

    private static string Name(uint pid)
    {
        if (Names.TryGetValue(pid, out var known)) return known;
        try
        {
            using var process = Process.GetProcessById((int)pid);
            known = process.ProcessName;
        }
        catch
        {
            known = "?";
        }
        Names[pid] = known;
        return known;
    }

    private static bool IsWatched(string name)
    {
        foreach (var watched in Watched)
        {
            if (string.Equals(name, watched, StringComparison.OrdinalIgnoreCase)) return true;
        }
        return false;
    }

    private static string Title(IntPtr hwnd)
    {
        var length = GetWindowTextLengthW(hwnd);
        var buffer = new StringBuilder(Math.Max(1, length + 1));
        GetWindowTextW(hwnd, buffer, buffer.Capacity);
        return buffer.ToString();
    }

    private static bool IsVisible(IntPtr hwnd)
    {
        if (!IsWindowVisible(hwnd)) return false;
        if (DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, out var cloaked, sizeof(int)) == 0 &&
            cloaked != 0)
        {
            return false;
        }
        return (GetWindowLongPtrW(hwnd, GWL_EXSTYLE).ToInt64() & WS_EX_TOOLWINDOW) == 0;
    }

    /// <summary>Every visible top-level window: pid, process, title.</summary>
    private static List<Dictionary<string, object>> VisibleWindows()
    {
        var windows = new List<Dictionary<string, object>>();
        EnumWindows((hwnd, _) =>
        {
            if (!IsVisible(hwnd)) return true;
            GetWindowThreadProcessId(hwnd, out var pid);
            windows.Add(new Dictionary<string, object>
            {
                ["pid"] = pid,
                ["process"] = Name(pid),
                ["title"] = Title(hwnd),
            });
            return true;
        }, IntPtr.Zero);
        return windows;
    }

    /// <summary>
    /// Any WS_VISIBLE top-level window owned by a watched process, ignoring DWM
    /// cloaking and the tool-window style.  On a locked desktop everything is
    /// cloaked, but a console window created there still carries WS_VISIBLE, so
    /// this is the check that cannot be fooled by the lock screen.
    /// </summary>
    private static List<Dictionary<string, object>> WatchedWindows()
    {
        var windows = new List<Dictionary<string, object>>();
        EnumWindows((hwnd, _) =>
        {
            if (!IsWindowVisible(hwnd)) return true;
            GetWindowThreadProcessId(hwnd, out var pid);
            var name = Name(pid);
            if (!IsWatched(name)) return true;
            DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, out var cloaked, sizeof(int));
            windows.Add(new Dictionary<string, object>
            {
                ["pid"] = pid,
                ["process"] = name,
                ["title"] = Title(hwnd),
                ["cloaked"] = cloaked != 0,
            });
            return true;
        }, IntPtr.Zero);
        return windows;
    }

    private static Dictionary<string, object> Window(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero) return null;
        GetWindowThreadProcessId(hwnd, out var pid);
        return new Dictionary<string, object>
        {
            ["pid"] = pid,
            ["process"] = Name(pid),
            ["title"] = Title(hwnd),
            ["watched"] = IsWatched(Name(pid)),
        };
    }

    /// <summary>The session's process table from the same snapshot Win32_Process uses.</summary>
    private static List<Dictionary<string, object>> Processes(uint session)
    {
        var list = new List<Dictionary<string, object>>();
        var snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if (snapshot == IntPtr.Zero || snapshot == new IntPtr(-1)) return list;
        try
        {
            var entry = new PROCESSENTRY32W
            {
                dwSize = (uint)Marshal.SizeOf<PROCESSENTRY32W>(),
            };
            if (!Process32FirstW(snapshot, ref entry)) return list;
            do
            {
                if (!ProcessIdToSessionId(entry.th32ProcessID, out var sid) || sid != session)
                {
                    continue;
                }
                list.Add(new Dictionary<string, object>
                {
                    ["pid"] = entry.th32ProcessID,
                    ["ppid"] = entry.th32ParentProcessID,
                    ["process"] = entry.szExeFile.TrimEnd('\0'),
                });
            } while (Process32NextW(snapshot, ref entry));
        }
        finally
        {
            CloseHandle(snapshot);
        }
        list.Sort((left, right) => ((uint)left["pid"]).CompareTo((uint)right["pid"]));
        return list;
    }

    private static void Emit(Dictionary<string, object> row)
    {
        row["t"] = DateTime.Now.ToString("HH:mm:ss.fff");
        _log.WriteLine(JsonSerializer.Serialize(row));
        _log.Flush();
    }

    private static int Main(string[] args)
    {
        double seconds = 120;
        var sampleMs = 100;
        string outPath = null, stopFile = null;
        for (var i = 0; i < args.Length - 1; i++)
        {
            if (args[i] == "--seconds") double.TryParse(args[i + 1], out seconds);
            else if (args[i] == "--sample-ms") int.TryParse(args[i + 1], out sampleMs);
            else if (args[i] == "--out") outPath = args[i + 1];
            else if (args[i] == "--stop-file") stopFile = args[i + 1];
        }
        if (outPath == null) return 2;
        if (sampleMs < 50) sampleMs = 50;

        var session = (uint)Process.GetCurrentProcess().SessionId;
        // A measurement instrument must not be starved by the batch it measures:
        // run at high priority and record every sample interval, so a gap over
        // 200 ms is visible instead of hidden.
        Process.GetCurrentProcess().PriorityClass = ProcessPriorityClass.High;
        System.Threading.Thread.CurrentThread.Priority = System.Threading.ThreadPriority.Highest;
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outPath)) ?? ".");
        using var log = new StreamWriter(outPath, false, new UTF8Encoding(false));
        _log = log;

        Emit(new Dictionary<string, object>
        {
            ["kind"] = "start",
            ["session"] = session,
            ["pid"] = Environment.ProcessId,
            ["sample_ms"] = sampleMs,
            ["seconds"] = seconds,
            ["windows"] = VisibleWindows(),
            ["processes"] = Processes(session),
        });

        var deadline = DateTime.UtcNow.AddSeconds(seconds);
        var clock = Stopwatch.StartNew();
        var nextSample = DateTime.UtcNow;
        var nextTable = DateTime.UtcNow;
        var lastTable = "";
        long samples = 0, watchedWindows = 0, watchedForeground = 0;
        double lastAtMs = 0, maxGapMs = 0;
        while (DateTime.UtcNow < deadline)
        {
            if (!string.IsNullOrEmpty(stopFile) && File.Exists(stopFile)) break;
            var now = DateTime.UtcNow;
            if (now >= nextSample)
            {
                nextSample = now.AddMilliseconds(sampleMs);
                var atMs = clock.Elapsed.TotalMilliseconds;
                var gapMs = samples == 0 ? 0 : atMs - lastAtMs;
                if (gapMs > maxGapMs) maxGapMs = gapMs;
                lastAtMs = atMs;
                var windows = VisibleWindows();
                var watched = WatchedWindows();
                var foreground = Window(GetForegroundWindow());
                samples++;
                watchedWindows += watched.Count;
                var foregroundWatched = foreground != null && (bool)foreground["watched"];
                if (foregroundWatched) watchedForeground++;
                Emit(new Dictionary<string, object>
                {
                    ["kind"] = "sample",
                    ["at_ms"] = Math.Round(atMs, 1),
                    ["gap_ms"] = Math.Round(gapMs, 1),
                    ["foreground"] = foreground,
                    ["watched"] = watched,
                    ["visible_count"] = windows.Count,
                    ["focus_change"] = foregroundWatched,
                });
            }
            if (DateTime.UtcNow >= nextTable)
            {
                nextTable = DateTime.UtcNow.AddSeconds(1);
                var table = Processes(session);
                var text = JsonSerializer.Serialize(table);
                if (text != lastTable)
                {
                    lastTable = text;
                    Emit(new Dictionary<string, object>
                    {
                        ["kind"] = "processes",
                        ["processes"] = table,
                    });
                }
            }
            System.Threading.Thread.Sleep(10);
        }

        Emit(new Dictionary<string, object>
        {
            ["kind"] = "end",
            ["samples"] = samples,
            ["max_gap_ms"] = Math.Round(maxGapMs, 1),
            ["watched_window_observations"] = watchedWindows,
            ["watched_foreground_observations"] = watchedForeground,
            ["windows"] = VisibleWindows(),
            ["processes"] = Processes(session),
        });
        return 0;
    }
}
