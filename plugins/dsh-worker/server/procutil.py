"""Windows process helpers for owned worker processes.

The plugin never kills by image name.  Cancellation validates a recorded PID
*and* its kernel creation time before calling ``taskkill /T`` for that process
tree, or opens the supervisor's job object and terminates it.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import subprocess
import sys
import time

IS_WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
STILL_ACTIVE = 259

if IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    _kernel32.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    )
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.GetCurrentProcess.argtypes = ()
    _kernel32.IsProcessInJob.argtypes = (
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.BOOL),
    )
    _kernel32.IsProcessInJob.restype = wintypes.BOOL
    _kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _kernel32.TerminateProcess.restype = wintypes.BOOL
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


if IS_WINDOWS:
    _kernel32.Process32FirstW.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_PROCESSENTRY32W),
    )
    _kernel32.Process32FirstW.restype = wintypes.BOOL
    _kernel32.Process32NextW.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_PROCESSENTRY32W),
    )
    _kernel32.Process32NextW.restype = wintypes.BOOL


def _filetime_value(ft: "wintypes.FILETIME") -> int:
    return (int(ft.dwHighDateTime) << 32) | int(ft.dwLowDateTime)


def process_creation_time(pid: int) -> int | None:
    """Return the Windows creation time in 100ns ticks, or None."""
    if not IS_WINDOWS:
        return None
    try:
        handle = _kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
    except (OSError, ValueError, OverflowError):
        return None
    if not handle:
        return None
    try:
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not _kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        return _filetime_value(created)
    finally:
        _kernel32.CloseHandle(handle)


def process_alive(pid: int, creation_time: int | None = None) -> bool:
    if not pid or int(pid) <= 0:
        return False
    if not IS_WINDOWS:
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, ProcessLookupError):
            return False
    try:
        handle = _kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
    except (OSError, ValueError, OverflowError):
        return False
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        if code.value != STILL_ACTIVE:
            return False
        if creation_time is not None:
            current = process_creation_time(int(pid))
            return current == int(creation_time)
        return True
    finally:
        _kernel32.CloseHandle(handle)


def terminate_process(pid: int) -> bool:
    """Terminate exactly one PID (no tree), by process handle.

    Used by tests and by ``kill_tree`` as the restricted-token-safe primitive:
    ``OpenProcess(PROCESS_TERMINATE)`` on a process created by the same token
    succeeds even where ``taskkill`` is denied (e.g. the DSH agent sandbox),
    and it never matches by image name.
    """
    if not pid or int(pid) <= 0:
        return False
    if IS_WINDOWS:
        try:
            handle = _kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
        except (OSError, ValueError, OverflowError):
            return False
        if not handle:
            return False
        try:
            return bool(_kernel32.TerminateProcess(handle, 1))
        finally:
            _kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 15)
        return True
    except OSError:
        return False


def _process_parent_map() -> dict[int, int]:
    if not IS_WINDOWS:
        return {}
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or int(snapshot) == INVALID_HANDLE_VALUE:
        return {}
    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    parents: dict[int, int] = {}
    try:
        ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    return parents


def process_tree(pid: int) -> list[int]:
    """Breadth-first [pid, children, grandchildren, ...] from a snapshot."""
    parents = _process_parent_map()
    children: dict[int, list[int]] = {}
    for child, parent in parents.items():
        children.setdefault(parent, []).append(child)
    order = [int(pid)]
    seen = {int(pid)}
    index = 0
    while index < len(order):
        for child in children.get(order[index], []):
            if child not in seen:
                seen.add(child)
                order.append(child)
        index += 1
    return order


def kill_tree(pid: int, timeout: float = 20.0) -> bool:
    """Terminate exactly the process tree rooted at ``pid``.

    The caller must validate ownership first.  No image-name matching is used.
    ``taskkill /T /F`` is tried first (the normal desktop case); when it is
    denied -- e.g. under a restricted agent sandbox token -- the same tree is
    terminated natively by parent PID from a Toolhelp snapshot.
    """
    if not pid or int(pid) <= 0:
        return False
    if IS_WINDOWS:
        try:
            completed = subprocess.run(
                ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=CREATE_NO_WINDOW,
            )
            if completed.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
        tree = process_tree(int(pid))
        # Leaves first: parents cannot re-spawn or reparent before their
        # children are gone.
        for target in reversed(tree):
            terminate_process(target)
        deadline = time.monotonic() + min(5.0, timeout)
        while time.monotonic() < deadline:
            if not process_alive(int(pid)):
                return True
            time.sleep(0.05)
        return False
    try:
        os.killpg(int(pid), 15)
    except OSError:
        try:
            os.kill(int(pid), 15)
        except OSError:
            return False
    return True


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_void_p),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class WinJob:
    """A Windows job object with KILL_ON_JOB_CLOSE.

    The supervisor holds this for its lifetime.  If the supervisor is killed,
    the OS closes the handle and terminates any worker still in the job, which
    prevents an orphaned writer.  For mutating jobs the supervisor assigns
    itself to the job before spawning the worker, so the child inherits
    containment; the plugin fails the job closed if that assignment or the
    post-spawn membership check fails.  Read-only jobs may continue without
    containment.
    """

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    def __init__(self) -> None:
        self.handle = None
        self.error: str | None = None
        self.self_assigned = False
        if not IS_WINDOWS:
            self.error = "not_windows"
            return
        _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        _kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        _kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        _kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = _kernel32.CreateJobObjectW(None, None)
        if not handle:
            self.error = f"CreateJobObject failed ({ctypes.get_last_error()})"
            return
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _kernel32.SetInformationJobObject(
            handle,
            self.JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            self.error = f"SetInformationJobObject failed ({ctypes.get_last_error()})"
            _kernel32.CloseHandle(handle)
            return
        self.handle = handle

    def assign(self, process_handle: int) -> bool:
        if not self.handle:
            return False
        if not _kernel32.AssignProcessToJobObject(
            self.handle, wintypes.HANDLE(int(process_handle))
        ):
            self.error = f"AssignProcessToJobObject failed ({ctypes.get_last_error()})"
            return False
        return True

    def assign_current_process(self) -> bool:
        """Put the supervisor itself in the job before it spawns a worker.

        Child processes inherit job membership by default, so a mutating worker
        is contained from its first instruction rather than being assigned
        after it has already started writing.
        """
        if not self.handle:
            return False
        ok = self.assign(int(_kernel32.GetCurrentProcess()))
        if ok:
            self.self_assigned = True
        return ok

    def contains(self, process_handle: int) -> bool:
        if not self.handle:
            return False
        result = wintypes.BOOL()
        if not _kernel32.IsProcessInJob(
            wintypes.HANDLE(int(process_handle)), self.handle, ctypes.byref(result)
        ):
            self.error = f"IsProcessInJob failed ({ctypes.get_last_error()})"
            return False
        return bool(result.value)

    def close(self) -> None:
        if self.handle:
            _kernel32.CloseHandle(self.handle)
            self.handle = None


def hidden_creationflags() -> int:
    return CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0


def interpreter() -> str:
    return sys.executable
