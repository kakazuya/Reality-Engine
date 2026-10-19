"""Live-state context file for worker models (Shivam, 2026-10-20: a worker cannot answer from information it never got;
the orchestrator must hand over what it knows). Writes data/hotline/generated/context_now.md, read by DeepSeek / Go
workers (see data/hotline/README.md).

Contents: IST time; every running job process (python / pythonw / rclone / opencode / dsh) with command line, start time,
CPU seconds and memory; measured network upload and disk rates (5 s sample); the Drive upload timetable from
run_pdf_upload.cmd; the last Drive check summary; and the tail of every log written in the last --hours hours.
Read-only: it never starts, stops or edits anything.

    python -m reality_engine.scripts.worker_context [--hours 3] [--tail 15]
"""
import argparse
import datetime as dt
import re
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "reality_engine" / "data"
LOGS = DATA / "logs"
OUT = DATA / "hotline" / "generated" / "context_now.md"   # read by workers via ~/.dsh/AGENTS.md
JOBS = re.compile(r"^(python|pythonw|rclone|opencode|dsh|bun)(\.exe)?$", re.I)
SECRET = re.compile(r"(key|token|secret|password)[=: ]+\S+", re.I)


def rates(seconds=5):
    n0, d0 = psutil.net_io_counters(), psutil.disk_io_counters()
    time.sleep(seconds)
    n1, d1 = psutil.net_io_counters(), psutil.disk_io_counters()
    mb = lambda a, b: (b - a) / seconds / 2**20
    return (mb(n0.bytes_sent, n1.bytes_sent), mb(n0.bytes_recv, n1.bytes_recv),
            mb(d0.read_bytes, d1.read_bytes), mb(d0.write_bytes, d1.write_bytes))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=3)
    ap.add_argument("--tail", type=int, default=15)
    a = ap.parse_args()
    now = dt.datetime.now()
    L = [f"# Live context {now:%Y-%m-%d %H:%M:%S} IST (machine clock)", ""]
    up, down, dr, dw = rates()
    vm = psutil.virtual_memory()
    L += ["## Machine", f"- upload {up:.1f} MB/s, download {down:.1f} MB/s (5 s sample); disk read {dr:.1f} / write {dw:.1f} MB/s",
          f"- CPU {psutil.cpu_percent(interval=1):.0f}%, RAM free {vm.available / 2**30:.1f} GB", "", "## Running job processes"]
    for p in psutil.process_iter(["pid", "name", "cmdline", "create_time", "cpu_times", "memory_info"]):
        try:
            if not JOBS.match(p.info["name"] or ""):
                continue
            cmd = SECRET.sub(r"\1=***", " ".join(p.info["cmdline"] or []))[:300]
            start = dt.datetime.fromtimestamp(p.info["create_time"]).strftime("%m-%d %H:%M")
            cpu = sum(p.info["cpu_times"][:2]) if p.info["cpu_times"] else 0
            L.append(f"- pid {p.info['pid']} {p.info['name']} since {start}, cpu {cpu:.0f} s, "
                     f"mem {p.info['memory_info'].rss / 2**20:.0f} MB: `{cmd}`")
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError):
            continue
    L.append("- (processes of other Windows sessions, e.g. boot tasks running as S4U, may show without a command line)")
    cmdf = ROOT / "reality_engine/scripts/run_pdf_upload.cmd"
    if cmdf.exists():
        bw = sorted(set(re.findall(r'--bwlimit "([^"]+)"', cmdf.read_text(encoding="utf-8", errors="replace"))))
        L += ["", "## Drive upload (rclone, run_pdf_upload.cmd)", f"- bandwidth timetable (IST, HH:MM,rate from then on): {bw}",
              "- passes: copy pdfs -> decks -> D_pdfs, then repeat until all three exit 0"]
    summ = DATA / "drive_upload_check" / "SUMMARY.txt"
    if summ.exists():
        age = (now - dt.datetime.fromtimestamp(summ.stat().st_mtime)).total_seconds() / 60
        L += [f"- last drive_upload_check summary ({age:.0f} min old):"] + \
             ["  " + x for x in summ.read_text(encoding="utf-8", errors="replace").splitlines()[:6]]
    L += ["", f"## Logs written in the last {a.hours:g} h (last {a.tail} lines each)"]
    cut = time.time() - a.hours * 3600
    for f in sorted(LOGS.glob("*.log"), key=lambda f: -f.stat().st_mtime):
        if f.stat().st_mtime < cut or f.stat().st_size == 0:
            continue
        with f.open("rb") as fh:
            fh.seek(max(0, f.stat().st_size - 8000))
            lines = fh.read().decode("utf-8", errors="replace").splitlines()[-a.tail:]
        m = dt.datetime.fromtimestamp(f.stat().st_mtime)
        L += [f"### {f.name} (modified {m:%H:%M:%S}, {f.stat().st_size / 1024:.0f} KB)", "```",
              *[SECRET.sub(r"\1=***", x)[:300] for x in lines], "```"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(L)} lines)")


if __name__ == "__main__":
    main()
