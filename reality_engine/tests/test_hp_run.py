"""Tests for the HP job runner. No network: ssh/scp are replaced by recorders."""
from __future__ import annotations

import base64
import subprocess
import sys

import pytest

from reality_engine.scripts import hp_run


def fake_ssh(recorder, stdout="", code=0):
    def _f(argv, input_bytes=None, timeout=600):
        recorder.append((argv, input_bytes))
        return subprocess.CompletedProcess(argv, code, stdout.encode(), b"")
    return _f


def test_wrapper_runs_and_records_exit(tmp_path):
    """The .cmd owns job.log and exit.txt; a failing command must still leave its code."""
    cmd = f'"{sys.executable}" -c "import sys; print(\'hi\'); sys.stderr.write(\'err\'); sys.exit(3)"'
    (tmp_path / "run.cmd").write_bytes(hp_run.build_wrapper(str(tmp_path), cmd).encode())
    r = subprocess.run(["cmd", "/c", str(tmp_path / "run.cmd")], capture_output=True)
    assert r.returncode == 3
    assert (tmp_path / "exit.txt").read_text().strip() == "3"
    log = (tmp_path / "job.log").read_text()
    assert "hi" in log and "err" in log


def test_wrapper_keeps_ampersand_out_of_our_parsing(tmp_path):
    cmd = f'"{sys.executable}" -c "print(1+1)" & "{sys.executable}" -c "print(2+2)"'
    (tmp_path / "run.cmd").write_bytes(hp_run.build_wrapper(str(tmp_path), cmd).encode())
    subprocess.run(["cmd", "/c", str(tmp_path / "run.cmd")], capture_output=True)
    assert "2" in (tmp_path / "job.log").read_text()
    assert (tmp_path / "exit.txt").read_text().strip() == "0"


def test_names_are_checked():
    for ok in ("bench", "qnn-htp", "ocr_30", "a.b"):
        assert hp_run.check_name(ok) == ok
    for bad in ("", "..", "../x", "a b", "a\\b", "a|b"):
        with pytest.raises(SystemExit):
            hp_run.check_name(bad)


def test_ps_argv_is_utf16le_base64():
    script = "Write-Output 'ok'\n$x = 1"
    argv = hp_run._ps_argv(script)
    assert argv[:3] == ["powershell", "-NoProfile", "-EncodedCommand"]
    assert base64.b64decode(argv[3]).decode("utf-16-le") == script


def test_run_schtasks_script_writes_wrapper_and_task(monkeypatch):
    seen = []
    monkeypatch.setattr(hp_run, "_ssh", fake_ssh(seen, stdout="method=schtasks (SYSTEM)\n"))
    assert hp_run.cmd_run("bench", r"python C:\RE\bench.py", method="schtasks") == 0
    script = base64.b64decode(seen[0][0][3]).decode("utf-16-le")
    assert "schtasks /Create /TN RE_hpjob_bench" in script
    assert "/RU SYSTEM" in script
    assert "schtasks /Run /TN RE_hpjob_bench" in script
    wrapper = [p for p in script.splitlines() if "WriteAllBytes" in p][0]
    body = base64.b64decode(wrapper.split("FromBase64String('")[1].split("'")[0]).decode()
    assert 'cd /d "C:\\RE\\jobs\\bench"' in body
    assert r"python C:\RE\bench.py" in body


def test_run_wmi_and_start_methods(monkeypatch):
    for method, marker in (("wmi", "Win32_Process"), ("start", "Start-Process")):
        seen = []
        monkeypatch.setattr(hp_run, "_ssh", fake_ssh(seen, stdout="ok\n"))
        assert hp_run.cmd_run("x", "echo hi", method=method) == 0
        script = base64.b64decode(seen[0][0][3]).decode("utf-16-le")
        assert marker in script and "run.cmd" in script


def test_sync_streams_tar_into_a_fresh_tree(monkeypatch):
    seen = []
    monkeypatch.setattr(hp_run, "_ssh", fake_ssh(seen))
    monkeypatch.setattr(hp_run, "ps", lambda script: seen.append(([script], None)) or "")
    assert hp_run.cmd_sync(b"tar-bytes", "abc123") == 0
    (argv, data), = [s for s in seen if isinstance(s[0], list) and s[0][0] == "tar"]
    assert data == b"tar-bytes"
    assert argv[1:4] == ["-xf", "-", "-C"]
    assert argv[4].endswith("repo.new")
    scripts = "".join(s[0][0] for s in seen if isinstance(s[0], list) and s[0][0] != "tar")
    assert "Move-Item" in scripts and "abc123" in scripts


def test_copy_db_puts_files_under_re_db(monkeypatch, tmp_path):
    src = tmp_path / "equity.db"
    src.write_bytes(b"x" * 10)
    calls = []
    monkeypatch.setattr(hp_run, "ps", lambda script: "")
    monkeypatch.setattr(hp_run, "_scp", lambda argv: calls.append(argv)
                        or subprocess.CompletedProcess(argv, 0, b"", b""))
    assert hp_run.cmd_copy_db(src) == 0
    assert calls[0][1] == f"{hp_run.HOST}:C:/RE/db/equity.db"


def test_fetch_converts_backslashes(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(hp_run, "_scp", lambda argv: calls.append(argv)
                        or subprocess.CompletedProcess(argv, 0, b"", b""))
    dest = tmp_path / "job.log"
    assert hp_run.cmd_fetch(r"C:\RE\jobs\bench\job.log", str(dest)) == 0
    assert calls[0][0] == f"{hp_run.HOST}:C:/RE/jobs/bench/job.log"
    assert calls[0][1] == str(dest)


def test_parse_status_keeps_pipes_inside_the_last_line():
    text = (
        "bench|done|0|10-31 03:12|all good\n"
        "ocr|running||10-31 03:20|line with | pipes\n"
        "\n"
        "gone|unknown||10-30 22:00|\n"
    )
    rows = hp_run.parse_status(text)
    assert [r["name"] for r in rows] == ["bench", "ocr", "gone"]
    assert rows[1]["state"] == "running" and rows[2]["exit"] == ""
    assert rows[1]["last"] == "line with | pipes"
