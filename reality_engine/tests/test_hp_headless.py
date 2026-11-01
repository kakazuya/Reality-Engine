"""Nothing may reach the HP screen (Shivam's ruling, 1 Nov 2026).

No HP, no build and no database are needed: these checks read the source in this
checkout, so they run anywhere.

What they enforce:

* every csproj under ``reality_engine/tools/textrec`` is a GUI-subsystem
  ``WinExe`` -- a console helper would open a window for every batch;
* HP launcher code (``reality_engine/scripts/hp_*.py`` and everything under
  ``reality_engine/tools``) reaches the interactive session only through the one
  named helper ``interactive_task_script()``, which applies the hidden settings:
  no other ``Register-ScheduledTask`` and no ``/IT`` anywhere;
* ``schtasks /Create`` runs as SYSTEM (session 0), ``Start-Process`` asks for a
  hidden window, and a WMI ``Win32_Process.Create`` passes a hidden startup
  info;
* the driver's PE guard refuses to launch a console EXE in the interactive
  session.
"""
from __future__ import annotations

import ast
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "reality_engine" / "tools"
TEXTREC = TOOLS / "textrec"
SCRIPTS = REPO / "reality_engine" / "scripts"

HELPER = "interactive_task_script"
HELPER_FILE = "hp_ocr_large.py"

INTERACTIVE = re.compile(r"-LogonType\s+['\"]?Interactive\b|(?<![\w-])/IT(?![\w-])",
                         re.IGNORECASE)
REGISTER = re.compile(r"Register-ScheduledTask")
SCHTASKS_CREATE = re.compile(r"schtasks\s+/Create", re.IGNORECASE)
SYSTEM_ACCOUNT = re.compile(r"/RU\s+['\"]?SYSTEM\b", re.IGNORECASE)
START_PROCESS = re.compile(r"Start-Process\s+-")
HIDDEN_WINDOW = re.compile(r"-WindowStyle\s+['\"]?Hidden", re.IGNORECASE)
WMI_CREATE = re.compile(r"Win32_Process[\s\S]{0,400}?MethodName\s+Create", re.IGNORECASE)
HIDDEN_STARTUP = re.compile(r"ShowWindow")

OLD_CONSOLE_PROJECT = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0-windows10.0.19041.0</TargetFramework>
  </PropertyGroup>
</Project>
"""


# --------------------------------------------------------------------------- #
# 1. Every textrec build is a GUI-subsystem WinExe
# --------------------------------------------------------------------------- #

def output_type(csproj: Path) -> str:
    """The csproj's <OutputType>, or "" when it does not declare one."""
    root = ET.parse(csproj).getroot()
    node = root.find(".//OutputType")
    return (node.text or "").strip() if node is not None else ""


def csproj_failures(root: Path) -> list[str]:
    """Every project under root whose output is not a windowless WinExe."""
    failures = []
    for csproj in sorted(root.rglob("*.csproj")):
        kind = output_type(csproj)
        if kind.lower() != "winexe":
            failures.append(f"{csproj}: OutputType={kind or '(missing)'}, want WinExe")
    return failures


def test_every_textrec_project_builds_a_gui_exe():
    assert TEXTREC.is_dir()
    assert csproj_failures(TEXTREC) == []


def test_the_gui_check_rejects_the_old_console_project(tmp_path):
    """The check itself is real: a console project must fail it."""
    (tmp_path / "textrec.csproj").write_text(OLD_CONSOLE_PROJECT, encoding="utf-8")
    failures = csproj_failures(tmp_path)
    assert len(failures) == 1
    assert "OutputType=Exe" in failures[0]


def test_the_experimental_project_is_a_gui_exe():
    assert output_type(TEXTREC / "experimental" / "textrec20.csproj") == "WinExe"


# --------------------------------------------------------------------------- #
# 2. Launchers keep the interactive session hidden
# --------------------------------------------------------------------------- #

def helper_span(text: str) -> tuple[int | None, int | None]:
    """Line span of the one allowed interactive-task helper in a module."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return (None, None)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == HELPER:
            return (node.lineno, getattr(node, "end_lineno", node.lineno))
    return (None, None)


def launcher_failures(files: list[Path]) -> list[str]:
    """Every way this source could put a window on the HP's screen."""
    failures: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        start, end = helper_span(text)
        allowed = (path.name == HELPER_FILE, start, end)

        def in_helper(number: int) -> bool:
            return bool(allowed[0] and start and end and start <= number <= end)

        for number, line in enumerate(lines, 1):
            if INTERACTIVE.search(line) and not in_helper(number):
                failures.append(
                    f"{path.name}:{number}: interactive-session launch outside "
                    f"{HELPER}(): {line.strip()}")
            if REGISTER.search(line) and not in_helper(number):
                failures.append(
                    f"{path.name}:{number}: Register-ScheduledTask outside "
                    f"{HELPER}(): {line.strip()}")
            if SCHTASKS_CREATE.search(line) and not SYSTEM_ACCOUNT.search(line):
                failures.append(
                    f"{path.name}:{number}: schtasks /Create must run as SYSTEM "
                    f"(session 0), never the logged-on user: {line.strip()}")
            if START_PROCESS.search(line) and not HIDDEN_WINDOW.search(
                    "\n".join(lines[number - 1:number + 1])):
                failures.append(
                    f"{path.name}:{number}: Start-Process without -WindowStyle "
                    f"Hidden: {line.strip()}")
        if WMI_CREATE.search(text) and not HIDDEN_STARTUP.search(text):
            failures.append(
                f"{path.name}: WMI Win32_Process.Create without a hidden startup "
                f"info (ShowWindow)")

        if path.name == HELPER_FILE:
            if not (start and end):
                failures.append(f"{path.name}: missing the {HELPER}() helper")
            else:
                body = "\n".join(lines[start - 1:end])
                if not HIDDEN_WINDOW.search(body) and "-Hidden" not in body:
                    failures.append(
                        f"{path.name}: {HELPER}() does not apply hidden settings")
                if not INTERACTIVE.search(body):
                    failures.append(
                        f"{path.name}: {HELPER}() no longer launches the "
                        f"interactive task it is named for")
    return failures


def hp_launcher_sources() -> list[Path]:
    return sorted(SCRIPTS.glob("hp_*.py")) + sorted(TOOLS.rglob("*.py"))


def test_hp_launchers_stay_off_the_screen():
    files = hp_launcher_sources()
    assert files, "no HP launcher sources found"
    assert launcher_failures(files) == []


def test_the_launcher_check_rejects_an_unhidden_interactive_task(tmp_path):
    bad = tmp_path / "hp_bad.py"
    bad.write_text(
        'def start():\n'
        '    script = ("$p=New-ScheduledTaskPrincipal -UserId x '
        '-LogonType Interactive; Register-ScheduledTask -TaskName t")\n',
        encoding="utf-8")
    failures = launcher_failures([bad])
    assert any("interactive-session launch outside" in failure for failure in failures)
    assert any("Register-ScheduledTask outside" in failure for failure in failures)


def test_the_launcher_check_rejects_a_visible_launcher(tmp_path):
    bad = tmp_path / "hp_bad.py"
    bad.write_text(
        'def start():\n'
        '    script = "schtasks /Create /TN x /TR job.cmd /SC ONCE"\n'
        '    other = "Start-Process -FilePath cmd.exe -ArgumentList /c,job.cmd"\n'
        '    wmi = "Invoke-CimMethod -ClassName Win32_Process -MethodName Create"\n',
        encoding="utf-8")
    failures = launcher_failures([bad])
    assert any("must run as SYSTEM" in failure for failure in failures)
    assert any("Start-Process without -WindowStyle Hidden" in failure for failure in failures)
    assert any("without a hidden startup info" in failure for failure in failures)


def test_the_helper_must_apply_hidden_settings(tmp_path):
    bad = tmp_path / HELPER_FILE
    bad.write_text(
        f'def {HELPER}(alias, args, task, user):\n'
        '    return ("$p=New-ScheduledTaskPrincipal -UserId x -LogonType Interactive; "\n'
        '            "Register-ScheduledTask -TaskName t")\n',
        encoding="utf-8")
    failures = launcher_failures([bad])
    assert any("does not apply hidden settings" in failure for failure in failures)


# --------------------------------------------------------------------------- #
# 3. The driver refuses a console EXE before it enters the interactive session
# --------------------------------------------------------------------------- #

def pe_image(subsystem: int) -> bytes:
    """A minimal PE header with the given IMAGE_OPTIONAL_HEADER.Subsystem."""
    pe_offset = 0x80
    image = bytearray(pe_offset + 4 + 20 + 80)
    image[0:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, pe_offset)
    image[pe_offset:pe_offset + 4] = b"PE\0\0"
    struct.pack_into("<H", image, pe_offset + 4 + 20 + 68, subsystem)
    return bytes(image)


def test_driver_refuses_a_console_exe(tmp_path):
    from reality_engine.scripts.hp_ocr_large import assert_gui_subsystem, pe_subsystem

    console = tmp_path / "textrec.exe"
    console.write_bytes(pe_image(3))
    with pytest.raises(RuntimeError, match="not GUI"):
        assert_gui_subsystem(console)

    gui = tmp_path / "textrec.exe"
    gui.write_bytes(pe_image(2))
    assert assert_gui_subsystem(gui) == 2
    assert pe_subsystem(gui) == 2


def test_driver_reads_the_subsystem_of_a_real_exe():
    """The parser works on a real executable that is on every Windows box."""
    from reality_engine.scripts.hp_ocr_large import pe_subsystem

    for candidate in (Path(r"C:\Windows\System32\notepad.exe"),
                      Path(r"C:\Windows\System32\conhost.exe")):
        if candidate.exists():
            assert pe_subsystem(candidate) in (2, 3)
            return
    pytest.skip("no system executable to read")
