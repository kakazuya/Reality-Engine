"""T-052: pilot3 page OCR on the HP laptop (Microsoft TextRecognizer), driven from the MSI.

The engine only answers from the signed ``RETextRecBench`` MSIX in the interactive session, so the
HP work is the same one the 1 Nov large test proved headless: render the page at 300 DPI
grayscale, run the packaged helper from a hidden scheduled task (``hp_ocr_large``), keep an error
row for a page that still fails after two retries.  Nothing is shown on the HP screen.

Pipeline (three commands, MSI side):

* ``plan``  -- read the pages already OCR'd on the MSI (``ocr_page`` rows of ``--input-db``), add
  the pages ``ocr.pending()`` still reports (the one page RapidOCR failed with "Overly large
  image"), resolve every page's PDF the way ``ocr.pending()`` does, and copy only those PDFs to
  the HP (``<remote-root>\\pdfs\\<sha[:2]>\\<sha>.pdf``).  Writes ``--plan-out``.
* ``run``   -- refuse while the console is locked, copy the plan and the HP driver, start it as a
  hidden scheduled task (session 0; the helper it launches is the packaged WinExe), and wait for
  ``ocr_pages.jsonl.gz``.
* ``fetch`` -- bring the gz and ``summary.json`` back and write ``--out`` (same ``ocr_page`` schema
  as ``ocr.py`` plus ``low_conf_numbers`` and ``error``), ``method='ocr_textrec'``, word boxes in
  PDF points.
* ``compare`` -- per company pages / numbers / agreements and 10 sample disagreements, as the
  self-contained ``OCR_COMPARE.html`` Shivam reads.
* ``cleanup`` -- remove the MSIX package, certificate, tasks, copied PDFs and build from the HP.

CLI:
  python -m reality_engine.pilot3.hp_ocr plan    [--host H] [--remote-root R] [--no-copy]
  python -m reality_engine.pilot3.hp_ocr run     [--host H] [--timeout 7200] [--no-wait]
  python -m reality_engine.pilot3.hp_ocr fetch   [--host H] [--out DB]
  python -m reality_engine.pilot3.hp_ocr compare [--textrec-db DB] [--html HTML]
  python -m reality_engine.pilot3.hp_ocr cleanup [--host H]
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import time
from collections import Counter
from pathlib import Path

from reality_engine.pilot3 import PAGES_DB, kpi, ocr, profile

HOST = "zen7s@100.78.87.112"
REMOTE_ROOT = r"C:\RE\raw\pilot3_ocr"
REMOTE_PY = r"%LOCALAPPDATA%\Programs\Python\Python314-arm64\python.exe"
TASK = "Pilot3OCR"
OCR_DIR = Path(r"D:\RealityEngine\pilot3\ocr")
def input_dbs() -> dict[str, Path]:
    """The MSI OCR database of each company the active build reads (one per company, when held)."""
    return {s: OCR_DIR / f"ocr_{s}.db" for s in profile.symbols()}
OUT_DB = OCR_DIR / "ocr_textrec.db"
PLAN_OUT = OCR_DIR / "hp_plan.jsonl"
HTML_OUT = OCR_DIR / "OCR_COMPARE.html"
STAGE = OCR_DIR / "hp_stage"
DRIVERS = Path(__file__).resolve().parents[2] / "tasks/pilot60/proto3_text"
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

METHOD = "ocr_textrec"
SCHEMA = """
CREATE TABLE IF NOT EXISTS ocr_page (
  symbol TEXT NOT NULL, doc_key TEXT NOT NULL, page INTEGER NOT NULL, doc_type TEXT, known_at TEXT,
  text TEXT NOT NULL, words_json TEXT NOT NULL, ocr_conf REAL, n_boxes INTEGER, dpi INTEGER,
  seconds REAL, method TEXT NOT NULL DEFAULT 'ocr_textrec',
  low_conf_numbers TEXT, error TEXT,
  PRIMARY KEY (symbol, doc_key, page)
);
"""
NUM_TOKEN = re.compile(r"\(?\d[\d,]*(?:\.\d+)?\)?%?")


# --------------------------------------------------------------------------- #
# SSH helpers
# --------------------------------------------------------------------------- #

def _ssh(host: str, command: str, timeout: float = 120.0) -> subprocess.CompletedProcess:
    """Run one remote command; retry a dropped connection (Wi-Fi on the HP) three times."""
    last = None
    for attempt in range(3):
        last = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", host, command],
                              capture_output=True, text=True, timeout=timeout)
        if last.returncode == 0:
            return last
        if "Connection reset" not in (last.stderr or "") and "timed out" not in (last.stderr or ""):
            break
        time.sleep(3 * (attempt + 1))
    assert last is not None
    return last


def _ps(host: str, script: str, timeout: float = 120.0) -> subprocess.CompletedProcess:
    """PowerShell over SSH.  The default HP shell is cmd, so use EncodedCommand (machines/HP_LAPTOP.md)."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    return _ssh(host, f"powershell -NoProfile -EncodedCommand {encoded}", timeout)


def _scp(src: str, dst: str, timeout: float = 3600.0) -> None:
    result = subprocess.run(["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-r", "-q", src, dst],
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"scp {src} -> {dst} failed: {result.stderr[-600:]}")


LOCK_PS = r"""
$ErrorActionPreference='Continue'
$src=@"
using System;
using System.Runtime.InteropServices;
public class WTS2 {
 [DllImport("wtsapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)] public static extern bool WTSQuerySessionInformationW(IntPtr hServer, int sessionId, int infoClass, out IntPtr ppBuffer, out int pBytes);
 [DllImport("wtsapi32.dll")] public static extern void WTSFreeMemory(IntPtr p);
 [DllImport("kernel32.dll")] public static extern int WTSGetActiveConsoleSessionId();
}
"@
Add-Type -TypeDefinition $src
$sid=[WTS2]::WTSGetActiveConsoleSessionId()
$buf=[IntPtr]::Zero; $len=0
$ok=[WTS2]::WTSQuerySessionInformationW([IntPtr]::Zero,$sid,25,[ref]$buf,[ref]$len)
$flags=-1
if($ok -and $len -ge 20){ $b=New-Object byte[] $len; [Runtime.InteropServices.Marshal]::Copy($buf,$b,0,$len); $flags=[BitConverter]::ToInt32($b,16); [WTS2]::WTSFreeMemory($buf) }
"flags=$flags"
"""


def lock_state(host: str) -> int:
    """Console session flags from WTSQuerySessionInformationW class 25: 0 locked, 1 unlocked, -1 unknown."""
    out = _ps(host, LOCK_PS).stdout
    match = re.search(r"flags=(-?\d+)", out)
    return int(match.group(1)) if match else -1


# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #

def _input_rows(input_dbs: dict[str, Path]) -> tuple[dict[str, set], dict[tuple, tuple]]:
    """{(symbol, doc_key, page)} of the MSI OCR runs, and (symbol, doc_key, page) -> (doc_type, known_at)."""
    pages: dict[str, set] = {}
    meta: dict[tuple, tuple] = {}
    for symbol, path in input_dbs.items():
        if not path or not Path(path).is_file():
            continue
        con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        try:
            for doc_key, page, doc_type, known_at in con.execute(
                    "SELECT doc_key, page, doc_type, known_at FROM ocr_page WHERE symbol=?", (symbol,)):
                pages.setdefault(symbol, set()).add((doc_key, page))
                meta[(symbol, doc_key, page)] = (doc_type, known_at)
        finally:
            con.close()
    return pages, meta


def _pages_db_sources(pages_db: Path | str | None) -> dict[str, str]:
    """pages.db doc_key -> source_path (the PDF the collector read)."""
    path = Path(pages_db) if pages_db else None
    if path is None or not path.is_file():
        return {}
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return dict(con.execute("SELECT doc_key, source_path FROM doc"))
    finally:
        con.close()


def _resolve_pdf(symbol: str, doc_key: str, page: int, pending_map: dict, sources: dict[str, str],
                 sandbox: Path, raw_root: Path) -> tuple[Path | None, tuple | None]:
    """The PDF for one page the way ``ocr.pending`` resolves it: pages.db source_path first, then the
    ``pilot60_history`` copy under the raw root, then the sandbox ``raw`` file, then the decks_full
    sha key.  The MSI runs stored old sandbox keys (``history/...``); the same document is now held
    under ``pilot60_history/<SYM>/...`` (pages.db, doc_alias)."""
    tail = doc_key[len("history/"):] if doc_key.startswith("history/") else doc_key
    candidates = [f"pilot60_history/{symbol}/{tail}"]
    if candidates[0] != doc_key:
        candidates.append(doc_key)
    for key in candidates:
        row = pending_map.get((key, page))
        if row:
            return Path(row[4]), (row[2], row[3])
        source = sources.get(key)
        if source and Path(source).is_file():
            return Path(source), None
        raw = raw_root / key
        if raw.is_file():
            return raw, None
    sandbox_pdf = sandbox / f"{symbol.lower()}_loop" / "raw" / doc_key
    if sandbox_pdf.is_file():
        return sandbox_pdf, None
    return None, None


def build_plan(symbols: list[str], input_dbs: dict[str, Path], pages_db: Path | str | None = PAGES_DB,
               sandbox: Path = kpi.SANDBOX_ROOT, raw_root: Path = kpi.RAW_ROOT) -> tuple[list[dict], dict]:
    """Every page the MSI read (the input OCR rows) plus every page still pending, with its PDF."""
    rows, meta = _input_rows({s: input_dbs[s] for s in symbols if s in input_dbs})
    sources = _pages_db_sources(pages_db)
    plan: list[dict] = []
    stats: dict = {}
    for symbol in symbols:
        done = rows.get(symbol, set())
        left = ocr.pending(symbol, sandbox, raw_root, done, pages_db)
        wanted = {(k, p) for k, p in done} | {(r[0], r[1]) for r in left}
        pending_map = {(r[0], r[1]): r for r in ocr.pending(symbol, sandbox, raw_root, set(), pages_db)}
        st = stats.setdefault(symbol, {"msi_rows": len(done), "left_pending": len(left), "pages": 0, "missing": 0})
        for doc_key, page in sorted(wanted):
            pdf, pdf_meta = _resolve_pdf(symbol, doc_key, page, pending_map, sources, sandbox, raw_root)
            doc_type, known_at = meta.get((symbol, doc_key, page), (None, None))
            if pdf_meta:
                doc_type, known_at = doc_type or pdf_meta[0], known_at or pdf_meta[1]
            if pdf is None or not pdf.is_file():
                st["missing"] += 1
                continue
            plan.append({"symbol": symbol, "doc_key": doc_key, "page": page, "doc_type": doc_type,
                         "known_at": known_at, "pdf_path": str(pdf)})
            st["pages"] += 1
    return plan, stats


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_plan(plan: list[dict], plan_out: Path, stage: Path) -> dict:
    """Give every page its PDF's sha256, hard-link the unique PDFs into ``stage/pdf`` and write the plan."""
    by_path: dict[str, str] = {}
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "pdfs").mkdir(exist_ok=True)
    for row in plan:
        path = row.pop("pdf_path")
        sha = by_path.get(path)
        if sha is None:
            sha = by_path[path] = _sha256(Path(path))
            target = stage / "pdfs" / sha[:2] / f"{sha}.pdf"
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                try:
                    target.hardlink_to(path)
                except OSError:
                    shutil.copy2(path, target)
        row["pdf"] = f"pdfs/{sha[:2]}/{sha}.pdf"
    plan_out.parent.mkdir(parents=True, exist_ok=True)
    plan_out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in plan), encoding="utf-8")
    return {"pages": len(plan), "pdfs": len(by_path),
            "mb": round(sum(Path(p).stat().st_size for p in by_path) / 1e6, 1)}


def cmd_plan(args) -> int:
    dbs = {s: path for s, path in input_dbs().items() if s in args.symbols}
    for path in map(Path, args.input_db):
        if path.name in {f"ocr_{s}.db" for s in args.symbols}:
            dbs[path.name[len("ocr_"):-len(".db")]] = path
    plan, stats = build_plan(args.symbols, dbs, Path(args.pages_db) if args.pages_db else None)
    info = write_plan(plan, Path(args.plan_out), Path(args.stage))
    info.update(stats)
    print(json.dumps(info, indent=1))
    if args.no_copy:
        return 0
    remote = args.remote_root
    _ps(args.host, f"Remove-Item -Recurse -Force -ErrorAction SilentlyContinue '{remote}\\pdfs'; "
                   f"New-Item -ItemType Directory -Force -Path '{remote}' | Out-Null")
    _scp(str(Path(args.stage) / "pdfs"), f"{args.host}:{remote.replace(chr(92), '/')}/pdfs")
    _scp(args.plan_out, f"{args.host}:{remote.replace(chr(92), '/')}/plan.jsonl")
    print("copied", info["pages"], "pages /", info["pdfs"], "PDFs /", info["mb"], "MB to", remote)
    return 0


# --------------------------------------------------------------------------- #
# run on the HP
# --------------------------------------------------------------------------- #

START_PS = r"""
$ErrorActionPreference='Stop'
$root='@ROOT@'
$py="$env:LOCALAPPDATA\Programs\Python\Python314-arm64\python.exe"
if (-not (Test-Path $py)) { throw "python not found: $py" }
if (-not (Get-AppxPackage -Name 'RETextRecBench')) { throw "RETextRecBench MSIX is not installed; rebuild it per tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md section 11" }
$arg = '"@ROOT@\hp_ocr_pages.py" pilot3_ocr --docs "@ROOT@" --plan "@ROOT@\plan.jsonl" --out "@ROOT@\ocr_pages.jsonl.gz" --log "@ROOT@\run.log" --summary "@ROOT@\summary.json"'
$a = New-ScheduledTaskAction -Execute $py -Argument $arg -WorkingDirectory '@ROOT@'
$p = New-ScheduledTaskPrincipal -UserId '@USER@' -LogonType S4U -RunLevel Limited
$s = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 8) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName '@TASK@' -Action $a -Principal $p -Settings $s -Force | Out-Null
Start-ScheduledTask -TaskName '@TASK@'
"""

PROGRESS_PS = r"""
$root='%(root)s'
$parts=@(Get-ChildItem "$root\parts\*.jsonl" -ErrorAction SilentlyContinue)
"parts=" + $parts.Count
"gz=" + (Test-Path "$root\ocr_pages.jsonl.gz")
$t=Get-ScheduledTask -TaskName '%(task)s' -ErrorAction SilentlyContinue
if($t){ "state=" + $t.State; "result=" + (Get-ScheduledTaskInfo -TaskName '%(task)s').LastTaskResult }
if(Test-Path "$root\run.log"){ Get-Content "$root\run.log" -Tail 2 }
"""


def start_hp(host: str, root: str, fresh: bool = False) -> dict:
    lock = lock_state(host)
    if lock != 1:
        raise RuntimeError(f"HP console session is locked (flags={lock}); not starting (headless rule)")
    remote = root.replace(chr(92), "/")
    _ps(host, f"New-Item -ItemType Directory -Force -Path '{root}\\parts' | Out-Null")
    if fresh:
        _ps(host, f"Remove-Item -Recurse -Force -ErrorAction SilentlyContinue '{root}\\parts'; "
                  f"New-Item -ItemType Directory -Force -Path '{root}\\parts' | Out-Null")
    for name, folder in (("hp_ocr_pages.py", DRIVERS), ("hp_ocr_large.py", SCRIPTS)):
        _scp(str(folder / name), f"{host}:{remote}/{name}")
    for stale in ("run.log", "ocr_pages.jsonl.gz", "summary.json"):
        _ps(host, f"Remove-Item -Force -ErrorAction SilentlyContinue '{root}\\{stale}'")
    user = _ssh(host, "whoami").stdout.strip() or "sumit_hp\\zen7s"
    script = (START_PS.replace("@ROOT@", root).replace("@USER@", user).replace("@TASK@", TASK))
    result = _ps(host, script)
    if result.returncode != 0:
        raise RuntimeError("task start failed: " + (result.stdout + result.stderr)[-800:])
    return {"user": user, "lock": lock}


def hp_progress(host: str, root: str) -> dict:
    out = _ps(host, PROGRESS_PS % {"root": root, "task": TASK}).stdout
    data = {"parts": 0, "gz": False, "state": "", "result": "", "tail": []}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("parts="):
            data["parts"] = int(line[6:] or 0)
        elif line.startswith("gz="):
            data["gz"] = line[3:] == "True"
        elif line.startswith("state="):
            data["state"] = line[6:]
        elif line.startswith("result="):
            data["result"] = line[7:]
        elif line:
            data["tail"].append(line)
    return data


def cmd_run(args) -> int:
    info = start_hp(args.host, args.remote_root, args.fresh)
    print("started", json.dumps(info))
    if args.no_wait:
        return 0
    deadline = time.time() + args.timeout
    ready = 0
    while time.time() < deadline:
        time.sleep(args.poll)
        p = hp_progress(args.host, args.remote_root)
        print(time.strftime("%H:%M:%S"), "parts", p["parts"], "gz", p["gz"], "state", p["state"],
              "|", (p["tail"][-1] if p["tail"] else ""), flush=True)
        if p["gz"] and p["state"] not in ("Running", "Queued", "Unknown"):
            return 0
        if p["state"] in ("Ready", "Disabled"):
            ready = ready + 1 if not p["gz"] else 0
            if ready >= 3:                      # exited before writing the gz: a real failure, not a race
                raise RuntimeError(f"driver task stopped without output (result={p['result']})")
    raise TimeoutError(f"no OCR result after {args.timeout:.0f}s")


CLEANUP_PS = r"""
$ErrorActionPreference='Continue'
Unregister-ScheduledTask -TaskName 'Pilot3OCR' -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName 'RETextRecBench' -Confirm:$false -ErrorAction SilentlyContinue
Get-AppxPackage -Name 'RETextRecBench' | Remove-AppxPackage -ErrorAction SilentlyContinue
foreach($d in 'Cert:\LocalMachine\Root','Cert:\LocalMachine\TrustedPeople','Cert:\CurrentUser\My'){
  Get-ChildItem $d -ErrorAction SilentlyContinue | Where-Object {$_.Subject -like '*CN=REBench*'} |
    ForEach-Object { Remove-Item -Path $_.PSPath -Force -ErrorAction SilentlyContinue }
}
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue '@ROOT@'
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\RE\ocr_large\work\pilot3_ocr*'
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\RE\ocr_large\textrec_build'
"package=" + [bool](Get-AppxPackage -Name 'RETextRecBench')
"root=" + (Test-Path '@ROOT@')
"task=" + [bool](Get-ScheduledTask -TaskName 'Pilot3OCR' -ErrorAction SilentlyContinue)
"helper=" + [bool](Get-ScheduledTask -TaskName 'RETextRecBench' -ErrorAction SilentlyContinue)
"certs=" + @(Get-ChildItem 'Cert:\LocalMachine\Root','Cert:\LocalMachine\TrustedPeople' -ErrorAction SilentlyContinue |
  Where-Object {$_.Subject -like '*CN=REBench*'}).Count
"""


def cmd_cleanup(args) -> int:
    """Remove the package, certificate, tasks, copied PDFs and build from the HP (the result is fetched)."""
    out = _ps(args.host, CLEANUP_PS.replace("@ROOT@", args.remote_root)).stdout
    print(out.strip())
    return 0 if "package=False" in out and "root=False" in out else 1


# --------------------------------------------------------------------------- #
# fetch -> ocr_textrec.db
# --------------------------------------------------------------------------- #

def write_db(rows: list[dict], plan_out: str | Path, out: str | Path) -> dict:
    """Write fetched HP rows as ``ocr_page`` rows (word boxes x 72/300 -> PDF points) and check coverage."""
    planned = {(r["symbol"], r["doc_key"], r["page"]) for r in
               map(json.loads, Path(plan_out).read_text(encoding="utf-8").splitlines())}
    # the runner carries the plan row through, so the id is symbol|doc_key|page
    for row in rows:
        symbol, doc_key, page = str(row["id"]).split("|")
        row["symbol"], row["doc_key"], row["page"] = symbol, doc_key, int(page)
    got = {(r["symbol"], r["doc_key"], r["page"]) for r in rows}
    missing = planned - got
    wordless = sum(1 for r in rows if r.get("text") and not (r.get("line_rows") or []))
    if wordless:
        raise RuntimeError(f"{wordless} rows have text but no line_rows (gz from an old HP driver); "
                           "re-run `run --fresh`")
    con = sqlite3.connect(out)
    con.executescript(SCHEMA)
    k = 72.0 / 300.0
    stats: dict = {}
    for row in rows:
        words = []
        for line in row.get("line_rows") or []:
            for word in line.get("words") or []:
                box = word.get("box") or [0, 0, 0, 0]
                words.append([round(box[0] * k, 2), round(box[1] * k, 2), round(box[2] * k, 2),
                              round(box[3] * k, 2), word.get("text") or "", word.get("confidence")])
        text = row.get("text") or ""
        con.execute("INSERT OR REPLACE INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (row["symbol"], row["doc_key"], row["page"], row.get("doc_type"), row.get("known_at"),
                     text, json.dumps(words, separators=(",", ":")), row.get("mean_confidence"),
                     len(words), 300, row.get("seconds"), METHOD,
                     json.dumps(row.get("low_conf_numbers") or [], separators=(",", ":")),
                     row.get("error")))
        st = stats.setdefault(row["symbol"], {"rows": 0, "errors": 0, "blank": 0, "seconds": 0.0})
        st["rows"] += 1
        st["errors"] += int(bool(row.get("error")))
        st["blank"] += int(not text)
        st["seconds"] += row.get("seconds") or 0
    con.commit()
    con.close()
    report = {"planned": len(planned), "rows": len(rows), "missing": len(missing), "per_symbol": stats}
    if missing:
        report["missing_sample"] = sorted(missing)[:5]
    return report


def cmd_fetch(args) -> int:
    root = args.remote_root
    remote = root.replace(chr(92), "/")
    if not args.no_copy:
        for name, local in (("ocr_pages.jsonl.gz", Path(args.gz)),
                            ("summary.json", Path(args.gz).with_name("hp_summary.json")),
                            ("run.log", Path(args.gz).with_name("hp_run.log"))):
            try:
                _scp(f"{args.host}:{remote}/{name}", str(local))
            except RuntimeError:
                if name == "ocr_pages.jsonl.gz":
                    raise
    with gzip.open(args.gz, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    report = write_db(rows, args.plan_out, args.out)
    print(json.dumps(report, indent=1))
    return 0 if not report["missing"] else 1


# --------------------------------------------------------------------------- #
# compare the two engines
# --------------------------------------------------------------------------- #

def _numbers(words: list) -> list[tuple[str, str, float]]:
    """(normalised, raw token, confidence) of every word that is a number."""
    out = []
    for word in words:
        token = (word[4] or "").strip()
        if not NUM_TOKEN.fullmatch(token):
            continue
        normal = token.replace(",", "").strip("()%").rstrip(".")
        if normal:
            out.append((normal, token, float(word[5] or 0.0)))
    return out


def _line_words(words: list, box: list) -> str:
    """The words on the same visual line as ``box``, left to right: the reading behind one token."""
    height = max(1.0, box[3] - box[1])
    y = (box[1] + box[3]) / 2
    line = [w for w in words if abs((w[1] + w[3]) / 2 - y) <= max(3.0, 0.45 * height)]
    line.sort(key=lambda w: w[0])
    return " ".join((w[4] or "") for w in line)[:160]


def _load_words(con: sqlite3.Connection, table: str = "ocr_page") -> dict:
    out: dict = {}
    for symbol, doc_key, page, wj in con.execute(f"SELECT symbol, doc_key, page, words_json FROM {table} WHERE n_boxes>0"):
        try:
            out[(symbol, doc_key, page)] = [list(w) for w in json.loads(wj)]
        except (TypeError, ValueError):
            continue
    return out


def cmd_compare(args) -> int:
    msi: dict = {}
    for path in sorted(Path(args.msi_dir).glob("ocr_*.db")):
        if path.name == Path(args.textrec_db).name or path.name.endswith("_rev.db"):
            continue
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            for key, words in _load_words(con).items():
                msi.setdefault(key, words)
        finally:
            con.close()
    con = sqlite3.connect(f"file:{Path(args.textrec_db).as_posix()}?mode=ro", uri=True)
    textrec = _load_words(con)
    con.close()
    report = {}
    disagreements = []
    for symbol in profile.symbols():
        pages = {k for k in textrec if k[0] == symbol}
        both = pages & set(msi)
        st = {"pages_textrec": len(pages), "pages_both": len(both), "numbers_textrec": 0, "numbers_rapid": 0,
              "agree": 0, "only_textrec": 0, "only_rapid": 0}
        for key in sorted(both):
            tn, rn = _numbers(textrec[key]), _numbers(msi[key])
            st["numbers_textrec"] += len(tn)
            st["numbers_rapid"] += len(rn)
            t = Counter(n for n, _, _ in tn)
            r = Counter(n for n, _, _ in rn)
            st["agree"] += sum((t & r).values())
            st["only_textrec"] += sum((t - r).values())
            st["only_rapid"] += sum((r - t).values())
            extra = sum((t - r).values()) + sum((r - t).values())
            if extra:
                disagreements.append((extra, symbol, key, set(t - r), set(r - t), textrec[key], msi[key]))
        report[symbol] = st
    con = sqlite3.connect(f"file:{Path(args.textrec_db).as_posix()}?mode=ro", uri=True)
    errors = dict(con.execute("SELECT symbol, count(*) FROM ocr_page WHERE error IS NOT NULL GROUP BY symbol"))
    con.close()
    disagreements.sort(key=lambda item: -item[0])
    seen: set = set()
    samples = []
    for item in disagreements:          # the same page text is held under several doc_keys: show it once
        signature = (item[1], item[2][2], tuple(sorted(item[3])), tuple(sorted(item[4])))
        if signature in seen:
            continue
        seen.add(signature)
        samples.append(item)
        if len(samples) >= 10:
            break
    html = _html(report, errors, samples, len(msi), len(textrec))
    Path(args.html).parent.mkdir(parents=True, exist_ok=True)
    Path(args.html).write_text(html, encoding="utf-8")
    print(json.dumps({"per_symbol": report, "html": str(args.html)}, indent=1))
    return 0


def _esc(text) -> str:
    return (str(text if text is not None else "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _html(report: dict, errors: dict, samples: list, msi_pages: int, textrec_pages: int) -> str:
    total = {k: sum(v[k] for v in report.values()) for k in next(iter(report.values()))}
    rows = "".join(
        f"<tr><td>{_esc(s)}</td><td>{v['pages_textrec']}</td><td>{v['pages_both']}</td>"
        f"<td>{v['numbers_textrec']}</td><td>{v['numbers_rapid']}</td><td>{v['agree']}</td>"
        f"<td>{v['only_textrec']}</td><td>{v['only_rapid']}</td><td>{errors.get(s, 0)}</td></tr>"
        for s, v in report.items())
    def cell(only: set, words: list) -> str:
        out = []
        for normal, raw, conf in _numbers(words):
            if normal in only and len(out) < 2:
                box = next((w for w in words if (w[4] or "").strip() == raw), [0, 0, 0, 0])
                out.append(f"<b>{_esc(raw)}</b> (conf {conf:.2f}) — {_esc(_line_words(words, box))}")
        return "<br>".join(out) or "—"

    sample_rows = []
    for _extra, symbol, (_, doc_key, page), only_t, only_r, twords, rwords in samples:
        sample_rows.append(f"<tr><td>{_esc(symbol)}</td><td>{_esc(doc_key)} p{page}</td>"
                           f"<td>{cell(only_t, twords)}</td><td>{cell(only_r, rwords)}</td></tr>")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Pilot3 OCR: TextRecognizer vs RapidOCR</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}}
h1{{font-size:22px}} h2{{font-size:17px;margin-top:28px}}
table{{border-collapse:collapse;margin-top:8px}} th,td{{border:1px solid #bbb;padding:5px 8px;font-size:13px;vertical-align:top}}
th{{background:#eee;text-align:left}} td.num{{text-align:right}}
.small{{color:#666;font-size:12px}} code{{background:#f4f4f4;padding:1px 3px}}
</style></head><body>
<h1>Pilot3 page OCR: Microsoft TextRecognizer (HP) vs RapidOCR (MSI)</h1>
<p class="small">Both engines read the same 300 DPI grayscale page renders. Numbers are numeric tokens in the
word boxes; a number agrees when the same normalised token is on the same page. TextRecognizer pages:
{textrec_pages}, RapidOCR pages: {msi_pages}. Generated by <code>reality_engine.pilot3.hp_ocr compare</code>.</p>
<h2>Per company</h2>
<table><tr><th>Company</th><th>Pages (TextRecognizer)</th><th>Pages read by both</th><th>Numbers (TextRecognizer)</th>
<th>Numbers (RapidOCR)</th><th>Agree</th><th>Only TextRecognizer</th><th>Only RapidOCR</th><th>Error rows</th></tr>
{rows}
<tr><th>Total</th><th>{total['pages_textrec']}</th><th>{total['pages_both']}</th><th>{total['numbers_textrec']}</th>
<th>{total['numbers_rapid']}</th><th>{total['agree']}</th><th>{total['only_textrec']}</th>
<th>{total['only_rapid']}</th><th>{sum(errors.values())}</th></tr></table>
<h2>10 sample disagreements (both readings)</h2>
<table><tr><th>Company</th><th>Page</th><th>TextRecognizer reading</th><th>RapidOCR reading</th></tr>
{''.join(sample_rows) or '<tr><td colspan="4">No disagreement.</td></tr>'}</table>
<p class="small">The line under each token is the same visual line on the page. A token missing from one
engine is shown as an empty cell.</p>
</body></html>
"""


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    pl = sub.add_parser("plan")
    pl.add_argument("--host", default=HOST)
    pl.add_argument("--remote-root", default=REMOTE_ROOT)
    pl.add_argument("--symbols", default=None, help="default: the profile's companies, else the default database's")
    pl.add_argument("--input-db", action="append", default=[])
    pl.add_argument("--pages-db", default=str(PAGES_DB))
    pl.add_argument("--plan-out", default=str(PLAN_OUT))
    pl.add_argument("--stage", default=str(STAGE))
    pl.add_argument("--no-copy", action="store_true")
    pl.set_defaults(func=cmd_plan)
    ru = sub.add_parser("run")
    ru.add_argument("--host", default=HOST)
    ru.add_argument("--remote-root", default=REMOTE_ROOT)
    ru.add_argument("--timeout", type=float, default=7200)
    ru.add_argument("--poll", type=float, default=45)
    ru.add_argument("--no-wait", action="store_true")
    ru.add_argument("--fresh", action="store_true", help="discard the HP batches and read every page again")
    ru.set_defaults(func=cmd_run)
    fe = sub.add_parser("fetch")
    fe.add_argument("--host", default=HOST)
    fe.add_argument("--remote-root", default=REMOTE_ROOT)
    fe.add_argument("--plan-out", default=str(PLAN_OUT))
    fe.add_argument("--gz", default=str(OCR_DIR / "ocr_pages.jsonl.gz"))
    fe.add_argument("--out", default=str(OUT_DB))
    fe.add_argument("--no-copy", action="store_true", help="use the local --gz (the HP copy is already fetched)")
    fe.set_defaults(func=cmd_fetch)
    co = sub.add_parser("compare")
    co.add_argument("--msi-dir", default=str(OCR_DIR))
    co.add_argument("--textrec-db", default=str(OUT_DB))
    co.add_argument("--html", default=str(HTML_OUT))
    co.set_defaults(func=cmd_compare)
    cl = sub.add_parser("cleanup")
    cl.add_argument("--host", default=HOST)
    cl.add_argument("--remote-root", default=REMOTE_ROOT)
    cl.set_defaults(func=cmd_cleanup)
    a = ap.parse_args(argv)
    a.symbols = [s.strip().upper() for s in (getattr(a, "symbols", "") or ",".join(profile.symbols())).split(",")
                 if s.strip()]
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
