"""T-188: local OCR readers - small vision models on llama.cpp (llama-server), page image in, grid rows out.

    python -m reality_engine.v2.local_reader run --model paddlevl --pages <pages.csv> \
        --pdf-pages <pdf_pages dir> --out <run dir> [--split dev] [--only p001,p002] [--bin <llama.cpp dir>]
    python -m reality_engine.v2.local_reader convert <page.raw.txt>    # converter only, no GPU needed
    python -m reality_engine.v2.local_reader models                    # the registry

Each model is served once (one at a time), then stopped. Per page the run dir gets the same files every other
reader run has: ``<page_id>.raw.txt`` (the model's own reply) and ``<page_id>.rows.json`` (grid rows:
table, row_label, col_header, value, unit), plus ``run_log.csv`` and ``run_meta.json``.
Resumable: a page whose rows.json exists is skipped.

The server runs hidden: no console window, no shell, no browser tab.
"""
from __future__ import annotations

import argparse
import base64
import csv
import html as _html
import json
import re
import subprocess
import sys
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pymupdf
import requests

from reality_engine.v2.reference_pages import _normalize_row

RE_ROOT = Path("D:/RealityEngine")
LLAMA_ROOT = RE_ROOT / "tools" / "llamacpp"
MODEL_ROOT = RE_ROOT / "models"

# One entry per model: the weights, the vision projector, and the prompt from that model's own card.
MODELS: dict[str, dict[str, Any]] = {
    "paddlevl": {
        "gguf": MODEL_ROOT / "paddlevl" / "PaddleOCR-VL-1.6-GGUF.gguf",
        "mmproj": MODEL_ROOT / "paddlevl" / "PaddleOCR-VL-1.6-GGUF-mmproj.gguf",
        "prompts": ["Table Recognition:", "Chart Recognition:"],  # the card's own tasks; chart fills a chart panel
        "port": 8091,
    },
    "glmocr": {
        "gguf": MODEL_ROOT / "glmocr" / "GLM-OCR-Q8_0.gguf",
        "mmproj": MODEL_ROOT / "glmocr" / "mmproj-GLM-OCR-Q8_0.gguf",
        "prompts": ["Table Recognition:"],  # card: Text Recognition: / Table Recognition: / Formula Recognition:
        "max_tokens": 5500,                 # its HTML is wordy: a 400-row table needs more than 4096
        "port": 8092,
    },
    "lighton": {
        "gguf": MODEL_ROOT / "lighton" / "LightOnOCR-3-0.8B.Q8_0.gguf",
        "mmproj": MODEL_ROOT / "lighton" / "LightOnOCR-3-0.8B.mmproj-q8_0.gguf",
        "prompts": [""],            # card: empty prompt = full-page transcription to markdown
        "port": 8093,
    },
}

RUN_LOG_FIELDS = ["page_id", "seconds", "prompt_tokens", "output_tokens", "error"]

CREATE_NO_WINDOW = 0x08000000


# ---------------------------------------------------------------- converter

def _clean(s: str) -> str:
    """One cell of model output to one plain string: tags dropped, whitespace collapsed."""
    s = re.sub(r"<br\s*/?>", " ", s or "")
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("\\n", " ")                                  # OTSL escapes a line break inside a cell
    s = re.sub(r"\\\(\^\{+([^{}]+)\}+\\\)", r"\1", s)          # LaTeX superscript: \(^{{*}}\) -> *
    s = s.replace("\\(", "(").replace("\\)", ")")
    s = s.replace("**", "").replace("__", "")
    return " ".join(_html.unescape(s).split())


_MEASURE = re.compile(r"^\(?-?\d(?:[\d,]*\d)?(?:\.\d+)?\)?%?$")


def _is_measure(cell: str) -> bool:
    """A printed figure (14,416 / 40% / (60%) / 3.36); a bare year is a period label, not a figure."""
    t = _clean(cell).replace(" ", "")
    if not _MEASURE.fullmatch(t):
        return False
    return not re.fullmatch(r"(?:19|20)\d\d", t)


def _is_header_row(cells: list[str]) -> bool:
    return any(cells) and not any(_is_measure(c) for c in cells)


def _split_header(rows: list[tuple[list[str], bool]]) -> tuple[list[list[str]], list[list[str]]]:
    """Leading header rows (explicit <th>, else one digit-free first row) and the body rows."""
    head: list[list[str]] = []
    i = 0
    while i < len(rows) and i < 6 and rows[i][1]:
        head.append(rows[i][0])
        i += 1
    if not head and rows and _is_header_row(rows[0][0]):
        head, i = [rows[0][0]], 1
    return head, [r[0] for r in rows[i:]]


def _is_banner(cells: list[str]) -> str:
    """A merged banner row (one text across the row) names the panel; it is not a header level."""
    filled = [c for c in cells if c]
    return filled[0] if len(cells) > 1 and filled and len(set(filled)) == 1 else ""


def _otsl_banner(marks: list[str]) -> bool:
    """OTSL marks one text merged across the row: a single <fcel> and nothing but <lcel> after it."""
    return marks.count("fcel") == 1 and marks.count("lcel") >= 2


def rows_from_table(head: list[list[str]], body: list[list[str]], table: str = "") -> list[dict[str, str]]:
    """A headered table to cells: one row per printed value, its header joined level by level with ' > '."""
    ncol = max([len(r) for r in head + body] or [0])
    heads = [" > ".join(p for p in ((_clean(r[j]) if j < len(r) else "") for r in head) if p) for j in range(ncol)]
    units = [""] * ncol
    out: list[dict[str, str]] = []
    for cells in body:
        cells = [_clean(c) for c in cells]
        label = cells[0] if cells else ""
        if len(cells) > 1 and label.rstrip(":").strip().lower() in ("unit", "units", "rs.", "(rs.)"):
            for j in range(1, ncol):        # a printed unit row belongs to the columns, not to a cell
                units[j] = cells[j] if j < len(cells) else ""
            continue
        for j in range(1, ncol):
            value = cells[j] if j < len(cells) else ""
            if not value or not any(ch.isdigit() for ch in value):
                continue                    # a blank cell, a dash or a word is not a figure
            out.append({"table": table, "row_label": label, "col_header": heads[j], "value": value, "unit": units[j]})
    return out


class _HtmlTables(HTMLParser):
    """Every top-level <table> as rows of (cells, all-cells-were-<th>), colspan and rowspan expanded."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[tuple[list[str], bool]]] = []
        self._depth = 0
        self._rows: list[tuple[list[tuple[str, int, int]], bool]] | None = None
        self._row: list[tuple[str, int, int]] | None = None
        self._allth = True
        self._cell: list[str] | None = None
        self._span = (1, 1)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._rows = []
        elif self._depth != 1:
            return
        elif tag == "tr":
            self._row, self._allth = [], True
        elif tag in ("td", "th") and self._row is not None:
            a = dict(attrs)
            self._cell = []
            self._span = (int(a.get("colspan") or 1), int(a.get("rowspan") or 1))
            if tag == "td":
                self._allth = False

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            if self._depth == 1 and self._rows is not None:
                self.tables.append(_expand_spans(self._rows))
                self._rows = None
            self._depth = max(0, self._depth - 1)
        elif self._depth != 1:
            return
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(("".join(self._cell), self._span[0], self._span[1]))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._rows is not None and self._row:
                self._rows.append((self._row, self._allth))
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._depth == 1 and self._cell is not None:
            self._cell.append(data)


def _expand_spans(rows: list[tuple[list[tuple[str, int, int]], bool]]) -> list[tuple[list[str], bool]]:
    """A colspan repeats its text across the columns it covers; a rowspan repeats it down the rows it covers."""
    out: list[tuple[list[str], bool]] = []
    carry: dict[int, tuple[str, int]] = {}
    for raw, allth in rows:
        cells: list[str] = []
        col = 0
        queue = list(raw)
        while queue or col in carry:
            if col in carry:
                text, left = carry[col]
                cells.append(text)
                if left <= 1:
                    del carry[col]
                else:
                    carry[col] = (text, left - 1)
                col += 1
                continue
            text, colspan, rowspan = queue.pop(0)
            for _ in range(max(1, colspan)):
                cells.append(text)
                if rowspan > 1:
                    carry[col] = (text, rowspan - 1)
                col += 1
        out.append((cells, allth))
    return out


def rows_from_html(raw: str) -> list[dict[str, str]]:
    parser = _HtmlTables()
    try:
        parser.feed(raw or "")
        parser.close()
    except Exception:                       # malformed markup: keep whatever tables parsed
        pass
    if parser._rows:                        # a reply cut off at max_tokens still yields its finished rows
        parser.tables.append(_expand_spans(parser._rows))
        parser._rows = None
    out: list[dict[str, str]] = []
    for rows in parser.tables:
        head, body = _split_header(rows)
        out.extend(rows_from_table(head, body))
    return out


_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _pipe_line(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def rows_from_markdown(raw: str) -> list[dict[str, str]]:
    """Every GFM pipe table (a separator row) and every bare run of pipe rows, to cells."""
    blocks: list[list[str]] = []
    cur: list[str] = []
    for line in (raw or "").splitlines():
        if _pipe_line(line):
            cur.append(line)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    out: list[dict[str, str]] = []
    for block in blocks:
        if len(block) < 2:
            continue
        sep = next((k for k, ln in enumerate(block) if _SEP.match(ln.strip())), None)
        if sep is not None:
            head = [_cells(block[sep - 1])] if sep >= 1 else []
            body = [_cells(ln) for ln in block[sep + 1:]]
        else:
            head, body = [_cells(block[0])], [_cells(ln) for ln in block[1:]]
        out.extend(rows_from_table(head, body))
    return out


_OTSL_MARK = re.compile(r"<(fcel|ecel|lcel|ucel|xcel)>")


def rows_from_otsl(raw: str, table: str = "") -> list[dict[str, str]]:
    """PaddleOCR-VL table recognition: OTSL rows (`<fcel>cell<ecel><nl>`); a merged banner row starts a panel."""
    first = _OTSL_MARK.search(raw or "")
    if first is None:
        return []
    head_note = raw[:first.start()]
    title = table or next((ln.strip() for ln in reversed(head_note.splitlines()) if ln.strip()), "")
    groups: list[tuple[str, list[list[str]], list[list[str]]]] = []
    cur: list[tuple[list[str], bool]] = []
    cur_title = title
    for line in raw.split("<nl>"):
        parts = re.split(r"<(fcel|ecel|lcel|ucel|xcel)>", line)
        marks = parts[1::2]
        cells: list[str] = []
        for i in range(1, len(parts) - 1, 2):
            mark, text = parts[i], _clean(parts[i + 1])
            if mark == "lcel":
                cells.append(cells[-1] if cells else "")
            elif mark in ("ucel", "xcel"):
                cells.append("")
            else:
                cells.append(text)
        if not cells:
            continue
        if _otsl_banner(marks):              # a panel heading: close the table above, name the one below
            name = next((c for c in cells if c), "")
            if cur:
                groups.append((cur_title, *_split_header(cur)))
                cur, cur_title = [], name or cur_title
            elif name and not cur_title:
                cur_title = name
            continue
        cur.append((cells, _is_header_row(cells)))
    if cur:
        groups.append((cur_title, *_split_header(cur)))
    out: list[dict[str, str]] = []
    for name, head, body in groups:
        out.extend(rows_from_table(head, body, name))
    return out


def convert(raw: str) -> list[dict[str, str]]:
    """A model's native page reply (OTSL, HTML tables, markdown tables, any of them fenced) to our grid rows."""
    raw = raw or ""
    rows = rows_from_otsl(raw)
    if "<table" in raw.lower():
        rows.extend(rows_from_html(raw))
    rows.extend(rows_from_markdown(raw))
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[dict[str, str]] = []
    for r in rows:
        key = (r["row_label"], r["col_header"], r["value"], r["unit"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


# ---------------------------------------------------------------- page image

def render_png(pdf: Path, max_side: int = 1600, dpi: int = 200) -> bytes:
    """One-page PDF to PNG bytes at the given DPI, shrunk (never grown) so the long side fits max_side."""
    with pymupdf.open(str(pdf)) as doc:
        page = doc[0]
        pix = page.get_pixmap(dpi=dpi)
        long_side = max(pix.width, pix.height)
        if long_side > max_side:
            pix = page.get_pixmap(dpi=max(72, int(dpi * max_side / long_side)))
    return pix.tobytes("png")


# ---------------------------------------------------------------- llama-server

def find_bin(explicit: str | None = None) -> Path:
    """The llama.cpp build directory that holds llama-server.exe (newest name wins)."""
    if explicit:
        p = Path(explicit)
        if (p / "llama-server.exe").exists():
            return p
        below = sorted(p.glob("*/llama-server.exe"))
        if below:
            return below[-1].parent
        raise SystemExit(f"no llama-server.exe in {p} or one directory below it")
    hits = sorted(LLAMA_ROOT.glob("*/llama-server.exe")) or sorted(LLAMA_ROOT.glob("*/*/llama-server.exe"))
    if not hits:
        raise SystemExit(f"no llama-server.exe under {LLAMA_ROOT}; unzip a llama.cpp build there")
    return hits[-1].parent


def server_cmd(bin_dir: Path, spec: dict[str, Any], port: int, ctx: int, gpu_layers: int) -> list[str]:
    return [
        str(bin_dir / "llama-server.exe"),
        "-m", str(spec["gguf"]),
        "--mmproj", str(spec["mmproj"]),
        "-c", str(ctx), "-np", "1",       # one slot; the vision batch needs the default ubatch (>= image tokens)
        "-ngl", str(gpu_layers),
        "--host", "127.0.0.1", "--port", str(port),
        "--temp", "0", "-lv", "4",        # -lv 4 keeps the CUDA0 / "offloading ... to GPU" lines in server.log
    ]


def start_server(bin_dir: Path, spec: dict[str, Any], port: int, ctx: int, gpu_layers: int,
                 log_path: Path, wait_s: int = 600) -> tuple[subprocess.Popen[bytes], float]:
    """Start llama-server hidden and wait for /health. Raises with the log tail if it dies."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = log_path.open("ab")
    t0 = time.time()
    proc = subprocess.Popen(server_cmd(bin_dir, spec, port, ctx, gpu_layers), shell=False, stdin=subprocess.DEVNULL,
                            stdout=fh, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW, close_fds=True)
    while time.time() - t0 < wait_s:
        if proc.poll() is not None:
            fh.close()
            raise RuntimeError(f"llama-server exited {proc.returncode}:\n" + _tail(log_path))
        try:
            if requests.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return proc, time.time() - t0
        except requests.RequestException:
            pass
        time.sleep(2)
    stop_server(proc)
    fh.close()
    raise RuntimeError(f"llama-server not healthy in {wait_s}s:\n" + _tail(log_path))


def stop_server(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _tail(path: Path, n: int = 40) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def log_evidence(log_path: Path, n: int = 12) -> list[str]:
    """The lines that prove the GPU did the work: backend device, offloaded layers."""
    pats = ("CUDA0", "Vulkan0", "offloaded", "offload", "using device", "ggml_cuda", "mmproj")
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [ln.strip()[:200] for ln in lines if any(p.lower() in ln.lower() for p in pats)][:n]


def gpu_mem_mb() -> int:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=15, creationflags=CREATE_NO_WINDOW)
        return int(out.stdout.strip().splitlines()[0])
    except Exception:
        return -1


class _VramPeak(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak = 0
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            v = gpu_mem_mb()
            self.peak = max(self.peak, v)
            self._stop.wait(3)

    def stop(self) -> int:
        self._stop.set()
        self.join(timeout=20)
        return self.peak


# ---------------------------------------------------------------- one page

def ask(port: int, png: bytes, prompt: str, max_tokens: int = 4096, timeout_s: int = 1800) -> dict[str, Any]:
    """One page image to the served model; the reply with its cost."""
    content: list[dict[str, Any]] = [{"type": "image_url",
                                      "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]
    if prompt:
        content.append({"type": "text", "text": prompt})
    body = {"messages": [{"role": "user", "content": content}], "temperature": 0, "max_tokens": max_tokens,
            "stream": False}
    t0 = time.time()
    res: dict[str, Any] = {"output": "", "seconds": 0.0, "prompt_tokens": 0, "output_tokens": 0, "error": None}
    try:
        r = requests.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=body, timeout=timeout_s)
    except requests.RequestException as exc:
        res["error"] = f"request failed: {exc}"
        res["seconds"] = time.time() - t0
        return res
    res["seconds"] = time.time() - t0
    if r.status_code != 200:
        res["error"] = f"http {r.status_code}: {r.text[:300]}"
        return res
    try:
        data = r.json()
        msg = data["choices"][0]["message"]
        res["output"] = msg.get("content") or msg.get("reasoning_content") or ""
        usage = data.get("usage") or {}
        res["prompt_tokens"] = int(usage.get("prompt_tokens") or 0)
        res["output_tokens"] = int(usage.get("completion_tokens") or 0)
    except (KeyError, IndexError, ValueError) as exc:
        res["error"] = f"bad reply: {exc}"
    return res


def read_pages(pages_csv: Path, split: str | None = None, only: set[str] | None = None) -> list[dict[str, str]]:
    with pages_csv.open(newline="", encoding="utf-8") as fh:
        meta = list(csv.DictReader(fh))
    if split:
        meta = [m for m in meta if (m.get("split") or "").strip().lower() == split.lower()]
    if only:
        meta = [m for m in meta if m.get("page_id") in only]
    return meta


def write_run_log(out: Path, rows: list[dict[str, Any]]) -> None:
    with (out / "run_log.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RUN_LOG_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in RUN_LOG_FIELDS})


def run_pages(model: str, pages_csv: Path, pdf_pages: Path, out: Path, split: str | None = None,
              only: set[str] | None = None, bin_dir: Path | None = None, ctx: int = 8192,
              max_side: int = 1600, max_tokens: int | None = None, gpu_layers: int = 99,
              port: int | None = None, prompt: str | None = None) -> int:
    spec = dict(MODELS[model])
    max_tokens = max_tokens or int(spec.get("max_tokens") or 4096)
    if prompt is not None:              # dev-only tuning: another native task prompt for the same weights
        spec["prompts"] = [prompt]
    for part in ("gguf", "mmproj"):
        if not Path(spec[part]).is_file():
            raise SystemExit(f"{model}: missing {part} {spec[part]}")
    out.mkdir(parents=True, exist_ok=True)
    port = port or int(spec["port"])
    meta = read_pages(pages_csv, split, only)
    done = {p.name.replace(".rows.json", "") for p in out.glob("*.rows.json")}
    todo = [m for m in meta if m["page_id"] not in done]
    log_rows: list[dict[str, Any]] = []
    log_path = out / "run_log.csv"
    if log_path.exists():
        with log_path.open(newline="", encoding="utf-8") as fh:
            log_rows = [dict(r) for r in csv.DictReader(fh)]
    print(f"{model}: {len(meta)} pages selected, {len(done & {m['page_id'] for m in meta})} already done, "
          f"{len(todo)} to run")
    if not todo:
        return 0
    bin_dir = find_bin(str(bin_dir) if bin_dir else None)
    server_log = out / "server.log"
    peak = _VramPeak()
    server_log.write_text("", encoding="utf-8")
    proc, load_s = start_server(bin_dir, spec, port, ctx, gpu_layers, server_log)
    peak.start()
    meta_out = {"model": model, "gguf": str(spec["gguf"]), "mmproj": str(spec["mmproj"]),
                "prompts": spec["prompts"], "bin": str(bin_dir), "ctx": ctx, "max_side": max_side, "max_tokens": max_tokens,
                "gpu_layers": gpu_layers, "load_seconds": round(load_s, 1),
                "backend_lines": log_evidence(server_log)}
    try:
        for m in todo:
            pid = m["page_id"]
            pdf = pdf_pages / f"{pid}.pdf"
            rows: list[dict[str, Any]] = []
            seconds = ptok = otok = 0.0
            error = None
            replies: list[str] = []
            if not pdf.exists():
                error = f"no pdf {pdf}"
            else:
                png = render_png(pdf, max_side)
                for pr in spec["prompts"]:          # the model's own tasks, in order; stop at the first with cells
                    res = ask(port, png, pr, max_tokens)
                    seconds += res["seconds"]
                    ptok += res["prompt_tokens"]
                    otok += res["output_tokens"]
                    replies.append(f"<<<prompt: {pr or '(empty)'}>>>\n{res['output'] or ''}")
                    error = res["error"]
                    if error:
                        continue
                    rows = [_normalize_row(r) for r in convert(res["output"])]
                    if rows:
                        break
            (out / f"{pid}.raw.txt").write_text("\n\n".join(replies), encoding="utf-8")
            (out / f"{pid}.rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
            log_rows = [r for r in log_rows if r.get("page_id") != pid]
            log_rows.append({"page_id": pid, "seconds": round(seconds, 2), "prompt_tokens": int(ptok),
                             "output_tokens": int(otok), "error": error or ""})
            write_run_log(out, log_rows)
            print(f"{pid}: {len(rows)} rows, {seconds:.1f}s, {int(ptok)}p/{int(otok)}o tok, err={error}", flush=True)
    finally:
        peak_mb = peak.stop()
        stop_server(proc)
        meta_out["vram_peak_mb"] = peak_mb
        meta_out["pages_done"] = len([p for p in out.glob("*.rows.json")])
        meta_out["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        (out / "run_meta.json").write_text(json.dumps(meta_out, ensure_ascii=False, indent=1), encoding="utf-8")
        write_run_log(out, log_rows)
    return 0


def reconvert(run_dir: Path) -> int:
    """Re-run the converter over a finished run's raw replies (no GPU): the model output is the only input."""
    raws = sorted(run_dir.glob("*.raw.txt"))
    total = 0
    for raw in raws:
        pid = raw.name.replace(".raw.txt", "")
        rows = [_normalize_row(r) for r in convert(raw.read_text(encoding="utf-8", errors="replace"))]
        (run_dir / f"{pid}.rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        total += len(rows)
    print(f"{len(raws)} pages, {total} rows reconverted in {run_dir}")
    return 0


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Local llama.cpp OCR readers (T-188)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="serve one model and read pages into a run dir")
    r.add_argument("--model", required=True, choices=sorted(MODELS))
    r.add_argument("--pages", required=True, type=Path)
    r.add_argument("--pdf-pages", required=True, type=Path)
    r.add_argument("--out", required=True, type=Path)
    r.add_argument("--split", default=None)
    r.add_argument("--only", default=None, help="comma-separated page ids")
    r.add_argument("--bin", default=None, help="llama.cpp build dir holding llama-server.exe")
    r.add_argument("--ctx", type=int, default=8192)
    r.add_argument("--max-side", type=int, default=1600)
    r.add_argument("--max-tokens", type=int, default=None, help="default: the model registry value")
    r.add_argument("--gpu-layers", type=int, default=99)
    r.add_argument("--port", type=int, default=None)
    r.add_argument("--prompt", default=None, help="override the model's native prompt (dev tuning)")

    c = sub.add_parser("convert", help="run the converter on a saved raw reply")
    c.add_argument("raw", type=Path)

    rc = sub.add_parser("reconvert", help="rewrite rows.json for every raw reply in a finished run dir")
    rc.add_argument("run_dir", type=Path)

    sub.add_parser("models", help="print the model registry")

    args = ap.parse_args(argv)
    if args.cmd == "run":
        only = {p.strip() for p in args.only.split(",") if p.strip()} if args.only else None
        return run_pages(args.model, args.pages, args.pdf_pages, args.out, args.split, only,
                         Path(args.bin) if args.bin else None, args.ctx, args.max_side, args.max_tokens,
                         args.gpu_layers, args.port, args.prompt)
    if args.cmd == "convert":
        rows = [_normalize_row(r) for r in convert(args.raw.read_text(encoding="utf-8", errors="replace"))]
        print(json.dumps(rows[:40], ensure_ascii=False, indent=1))
        print(f"{len(rows)} rows", file=sys.stderr)
        return 0
    if args.cmd == "reconvert":
        return reconvert(args.run_dir)
    for name, spec in sorted(MODELS.items()):
        print(f"{name}\t{spec['gguf']}\t{spec['mmproj']}\tprompts={spec['prompts']!r}\tport={spec['port']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
