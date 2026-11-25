"""T-242: read the image-only deck pages with the free vision models into each store's ``<stem>_ocr.db``.

Pages: every universe store's ``routes.csv`` row with ``doc_type=deck``, ``route=needs_ocr`` and a reason starting
``text layer none`` (the page has no text layer at all; 1,363 pages in ``C:/RealityEngine/tg_build/universe_fy27``).
The PDF comes from the store's ``doc.source_key`` through :mod:`reality_engine.raw_store`: a Drive-only copy is
fetched for the run and deleted afterwards.

Each page is rendered at 150 dpi (PyMuPDF), read with :data:`PROMPT`, and written as one ``ocr_page`` row (schema in
``reality_engine/pilot3/ocr.py``) whose ``method`` is the reading model's (:data:`OCR_METHODS`).  ``words_json`` holds
ONE PSEUDO-WORD PER LINE of the transcription: ``[0, i*LINE_H, len(line), i*LINE_H + 10, line]`` with ``i`` the
line's index.  The model returns plain text, not boxes, so line order becomes y order and the line's character count
its width.  That is enough for ``page_words.ocr_words`` and the reader's text checks; layout/position work must not
treat it as true geometry.  ``n_boxes`` is the line count, ``ocr_conf`` is NULL (the model states no confidence).

Two free routes, every free model allow-listed, share the pages:
``kilo`` -- ``nvidia/nemotron-3.5-super-vl:free`` over Kilo's HTTP gateway (KILO_API_KEY); the bake-off winner.
``zen``  -- in quality order, ``nemotron-3.5-super-vl-free`` (method ``ocr_nemotron_vl``; 94% recall at 58 s in the
            bake-off) then ``deepseek-v4.1-flash-free`` (method ``ocr_deepseek_flash_vl``; 92% recall at 41 s, 98% of
            the winner's recall) through ``opencode run --standalone --format json``; Zen's HTTP endpoint refuses
            every free model with ``FreeUsageLimitError`` ("Free models work in OpenCode"), so the CLI is Zen's route.
The CLI writes its log under ``%USERPROFILE%\\.local\\share\\opencode``, which a DSH-sandboxed run cannot open (EPERM),
so a sandboxed pilot uses ``--routes kilo``; outside the sandbox both routes run.
Only the ids in :data:`FREE_ROUTES` can be called (the paid Zen ids are refused by name), and a ``step_finish`` cost
above zero stops the run.  Keys are read from the machine/user environment via
``resource_watchdog.user_env`` and never printed.

A route reads with the model it has measured fastest (EWMA seconds/page, alpha :data:`EWMA_ALPHA`): an unmeasured
model is tried first in quality order, and every :data:`EXPLORE_EVERY`-th call probes the least-recently-used model so
the slower reader's speed keeps being measured.  A throttle cools that model alone (:data:`THROTTLE_START`, doubling
to :data:`THROTTLE_MAX`) and puts the page back in the queue.
Concurrency is per route (AIMD): each route starts at ``--start-workers`` (6) calls in flight, gains one after
:data:`AIMD_WINDOW` successes in a row with no throttle, loses 30% (floor one) on a throttle, and is capped by
``--max-workers`` (24).  Threads are the sum of the caps; a thread holds a route slot for its call, and every limit
change prints ``limit <route> <old>-><new> (<reason>)``.

CLI: python -m reality_engine.scripts.ocr_fill --limit 40 --seed 1125 --out-dir .tmp/ocr_pilot
      [--universe DIR] [--symbols A,B] [--resume] [--routes kilo,zen] [--start-workers 6] [--max-workers 24]
      [--log FILE] [--timeout SECONDS]
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import csv
import json
import queue
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from reality_engine import raw_store

PROMPT = ("Transcribe all text on this slide exactly, in reading order. Keep every number with its label, unit and "
          "column or period header. Output plain text only.")
DPI = 150
LINE_H = 12.0               # pseudo-word line pitch in PDF points
MAX_TRIES = 4               # a page may bounce between routes this many times before it is an error
BACKOFF_START, BACKOFF_MAX = 5.0, 120.0
DEFAULT_UNIVERSE = Path("C:/RealityEngine/tg_build/universe_fy27")

EWMA_ALPHA = 0.3                            # model seconds/page: weight of the newest sample
THROTTLE_START, THROTTLE_MAX = 30.0, 600.0  # a throttled model cools this long, doubling each time
AIMD_WINDOW = 20                            # successes in a row before a route's limit grows by one
AIMD_FACTOR = 0.7                           # a throttle cuts the route's limit to this share (floor one)
EXPLORE_EVERY = 8                           # every Nth call on a route probes its least-recently-used model

# The free allow-list.  A model id that is not here cannot be called (no --model argument exists on purpose).
FREE_ROUTES: dict[str, dict[str, Any]] = {
    "kilo": {"kind": "http", "base": "https://api.kilo.ai/api/gateway", "key_env": "KILO_API_KEY",
             "body": {"temperature": 0, "max_tokens": 8000, "reasoning": {"enabled": False}},
             "models": [{"id": "nvidia/nemotron-3.5-super-vl:free", "method": "ocr_nemotron_vl"}]},
    "zen": {"kind": "cli",
            "models": [{"id": "nemotron-3.5-super-vl-free", "method": "ocr_nemotron_vl",
                        "cli_model": "opencode/nemotron-3.5-super-vl-free"},
                       {"id": "deepseek-v4.1-flash-free", "method": "ocr_deepseek_flash_vl",
                        "cli_model": "opencode/deepseek-v4.1-flash-free"}]},
}
# Paid Zen models: never called, named so the refusal is explicit (the bake-off billed both on every call).
PAID_IDS = frozenset({"mimo-v2.6-flash-free", "hy4-flash-free"})
FREE_IDS = frozenset(m["id"] for cfg in FREE_ROUTES.values() for m in cfg["models"])
OCR_METHODS = frozenset(m["method"] for cfg in FREE_ROUTES.values() for m in cfg["models"])


def model_entry(route: str, model: dict[str, Any] | str | None = None) -> dict[str, Any]:
    """The allow-listed entry for ``model`` (id or entry) on ``route``; a paid id is refused by name.

    A model id outside the route's :data:`FREE_ROUTES` list is refused too: there is deliberately no ``--model`` flag.
    """
    entries = FREE_ROUTES[route]["models"]
    ident = model["id"] if isinstance(model, dict) else str(model or entries[0]["id"])
    bare = ident.rsplit("/", 1)[-1].split(":")[0]
    if bare in PAID_IDS:
        raise SystemExit(f"refusing paid model {ident!r}: free models only")
    for entry in entries:
        if ident in (entry["id"], entry.get("cli_model")):
            return entry
    raise SystemExit(f"refusing model {ident!r} on route {route!r}: free models only "
                     f"({[entry['id'] for entry in entries]})")


SCHEMA = """
CREATE TABLE IF NOT EXISTS ocr_page (
  symbol TEXT NOT NULL, doc_key TEXT NOT NULL, page INTEGER NOT NULL, doc_type TEXT, known_at TEXT,
  text TEXT NOT NULL, words_json TEXT NOT NULL, ocr_conf REAL, n_boxes INTEGER, dpi INTEGER,
  seconds REAL, method TEXT NOT NULL DEFAULT 'ocr_rapid',
  PRIMARY KEY (symbol, doc_key, page)
);
"""

_NUMBER = re.compile(r"(?<![\w.])[-+(]?\d[\d,]*(?:\.\d+)?")
STOP = threading.Event()
WRITE_LOCK = threading.Lock()
LOG_LOCK = threading.Lock()
_DBS: dict[Path, sqlite3.Connection] = {}


class Throttled(Exception):
    """A route answered 429 (or its free quota): retry it later, on either route."""


class PaidModel(Exception):
    """A route reported a non-zero cost: the whole run stops (brief's stop condition)."""


def _fitz():
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz
    return fitz


@contextlib.contextmanager
def _shared_acl_tempdirs():
    """Make ``tempfile.mkdtemp`` create folders any token can write into, for the run.

    Python 3.14 applies the mode ``tempfile`` asks for (0o700) as a Windows DACL; a DSH-restricted token is then
    refused inside that folder, which breaks ``raw_store.prefetch``/``local``/``keep`` on a Drive-only PDF.  Plain
    ``mkdir`` inherits the parent's permissions, so the fetched PDFs stay readable/writable and are deleted as usual."""
    original = tempfile.mkdtemp

    def mkdtemp(prefix: str | None = None, suffix: str | None = None, dir: str | None = None) -> str:
        path = Path(dir or tempfile.gettempdir()) / f"{prefix or 'tmp'}{uuid.uuid4().hex}{suffix or ''}"
        path.mkdir()
        return str(path)

    tempfile.mkdtemp = mkdtemp                       # raw_store looks the attribute up at call time
    try:
        yield
    finally:
        tempfile.mkdtemp = original


def parse_routes(value: str) -> list[str]:
    """``--routes`` -> route names, refusing anything outside :data:`FREE_ROUTES`."""
    names = [part.strip() for part in value.split(",") if part.strip()]
    bad = [name for name in names if name not in FREE_ROUTES]
    if bad:
        raise SystemExit(f"refusing non-free route(s) {bad}: only {sorted(FREE_ROUTES)} are allowed")
    return names or list(FREE_ROUTES)


def universe_stores(root: Path | str) -> list[Path]:
    """The universe store directories that carry both ``<name>.db`` and ``routes.csv``, by name."""
    root = Path(root)
    return sorted((p for p in root.iterdir() if p.is_dir() and (p / f"{p.name}.db").is_file()
                   and (p / "routes.csv").is_file()), key=lambda p: p.name)


def route_rows(store_dir: Path) -> list[tuple[str, int]]:
    """``(doc_key, page)`` of the store's image-only deck pages (route ``needs_ocr``, reason ``text layer none``)."""
    out: list[tuple[str, int]] = []
    with (store_dir / "routes.csv").open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if (row.get("doc_type") or "") != "deck" or (row.get("route") or "") != "needs_ocr":
                continue
            if not (row.get("reason") or "").startswith("text layer none"):
                continue
            try:
                out.append((str(row["doc_key"]), int(row["page"])))
            except (KeyError, ValueError):
                continue
    return out


def _doc_meta(db: Path, doc_keys: Iterable[str]) -> dict[str, tuple[str, str, str]]:
    """``{doc_key: (symbol, source_key, known_at)}`` from one store's ``doc`` table (read-only)."""
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        out: dict[str, tuple[str, str, str]] = {}
        for key in doc_keys:
            row = con.execute("SELECT symbol, source_key, known_at FROM doc WHERE doc_key=?", (key,)).fetchone()
            if row:
                out[key] = row
        return out
    finally:
        con.close()


def select(root: Path | str = DEFAULT_UNIVERSE, symbols: Iterable[str] = (), seed: int | None = None,
           limit: int | None = None) -> list[dict[str, Any]]:
    """The pages to read: ``[{store, symbol, doc_key, page, pdf, known_at}]``.

    ``symbols`` keeps only those companies; ``seed`` shuffles the full sorted list first (so a pilot is spread over
    stores and is reproducible), then ``limit`` cuts it."""
    wanted = {s.strip().upper() for s in symbols if s.strip()}
    pages: list[dict[str, Any]] = []
    for store_dir in universe_stores(root):
        rows = route_rows(store_dir)
        if not rows:
            continue
        db = store_dir / f"{store_dir.name}.db"
        meta = _doc_meta(db, {key for key, _page in rows})
        for doc_key, page in rows:
            found = meta.get(doc_key)
            if not found:
                continue
            symbol, source_key, known_at = found
            if wanted and symbol.upper() not in wanted:
                continue
            pages.append({"store": str(db), "symbol": symbol, "doc_key": doc_key, "page": page,
                          "pdf": source_key, "known_at": known_at})
    pages.sort(key=lambda p: (p["store"], p["doc_key"], p["page"]))
    if seed is not None:
        random.Random(seed).shuffle(pages)
    return pages[:limit] if limit else pages


def out_db(store_db: Path | str, out_dir: Path | str | None = None) -> Path:
    """Where a store's OCR rows go: ``<out-dir>/<stem>_ocr.db``, else beside the live store (``page_words``' sibling)."""
    path = Path(store_db)
    return Path(out_dir) / f"{path.stem}_ocr.db" if out_dir else path.with_name(f"{path.stem}_ocr.db")


def pseudo_words(text: str) -> list[list[Any]]:
    """One pseudo-word per non-empty line: ``[0, i*LINE_H, len(line), i*LINE_H+10, line]`` (see module docstring)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [[0.0, i * LINE_H, float(len(line)), i * LINE_H + 10.0, line] for i, line in enumerate(lines)]


def figures(text: str) -> int:
    """How many number tokens the transcription carries (the pilot's '>= 4 figures' count)."""
    return len(_NUMBER.findall(text))


def parse_events(raw: str) -> tuple[str, float, str]:
    """``opencode run --format json`` stream -> ``(text, cost_usd, error)``."""
    parts: list[str] = []
    cost, error = 0.0, ""
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = event.get("part") or {}
        kind = event.get("type")
        if kind == "text":
            parts.append(part.get("text") or "")
        elif kind == "step_finish":
            cost += float(part.get("cost") or 0.0)
        elif kind == "error":
            error = json.dumps(event)[:300]
    return "\n".join(p for p in parts if p).strip(), cost, error


def ask_http(route: str, png: bytes, timeout: float = 420,
             model: dict[str, Any] | str | None = None) -> str:
    """One HTTP reading (Kilo).  Raises Throttled on 429, RuntimeError on any other failure."""
    import requests

    from reality_engine.scripts.resource_watchdog import user_env

    cfg = FREE_ROUTES[route]
    if cfg["kind"] != "http":
        raise SystemExit(f"route {route!r} is not a free HTTP route")
    entry = model_entry(route, model)                               # free-only guard: no id off the allow-list
    key = user_env().get(cfg["key_env"], "")
    if not key:
        raise RuntimeError(f"{cfg['key_env']} is not set")
    body = {"model": entry["id"], **cfg["body"],
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
                {"type": "text", "text": PROMPT}]}]}
    r = requests.post(f"{cfg['base']}/chat/completions", json=body,
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, timeout=timeout)
    if r.status_code == 429:
        raise Throttled(r.text[:200])
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    if not data.get("choices"):
        raise RuntimeError(f"HTTP 200 without choices: {r.text[:200]}")
    return str(data["choices"][0]["message"].get("content") or "")


def ask_cli(route: str, png: bytes, timeout: float = 420,
            model: dict[str, Any] | str | None = None) -> str:
    """One OpenCode Zen reading through ``opencode run --standalone`` (HTTP refuses free models there).

    Parses the JSON event stream; a non-zero ``step_finish`` cost raises :class:`PaidModel` and stops the run."""
    from reality_engine.scripts.ar_queue import opencode_exe

    cfg = FREE_ROUTES[route]
    if cfg["kind"] != "cli":
        raise SystemExit(f"route {route!r} is not a free CLI route")
    entry = model_entry(route, model)                               # free-only guard: no id off the allow-list
    exe = opencode_exe()
    if not exe:
        raise RuntimeError("opencode executable not found")
    tmp = Path(tempfile.mkdtemp(prefix="ocr_fill_"))
    image = tmp / "page.png"
    image.write_bytes(png)
    try:
        proc = subprocess.run([exe, "run", "--standalone", "-m", entry["cli_model"], "--format", "json",
                               "-f", str(image), PROMPT],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                              cwd=tmp, stdin=subprocess.DEVNULL, creationflags=0x08000000)  # no console window
    except subprocess.TimeoutExpired:
        raise RuntimeError("opencode run timed out")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    text, cost, error = parse_events(proc.stdout)
    if cost > 0:
        raise PaidModel(f"{route} reported a cost of {cost} on a free model")
    if not text:
        err = (error or proc.stderr or proc.stdout)[-300:]
        if "rate limit" in err.lower() or "usage limit" in err.lower():
            raise Throttled(err)
        raise RuntimeError(f"opencode run: {err}")
    return text


def ask(route: str, png: bytes, timeout: float = 420,
        model: dict[str, Any] | str | None = None) -> str:
    """One reading from ``route`` with ``model`` (the seam tests monkeypatch; the route's first model by default)."""
    if FREE_ROUTES[route]["kind"] == "http":
        return ask_http(route, png, timeout, model)
    return ask_cli(route, png, timeout, model)


def render_page(pdf: str, page: int) -> bytes:
    """A page's PNG at :data:`DPI` (a Drive-only PDF is fetched by the store's ``prefetch`` first)."""
    store = raw_store.default_store()
    fitz = _fitz()
    with store.local(pdf) as source:
        doc = fitz.open(str(source))
        try:
            return doc[page - 1].get_pixmap(dpi=DPI, alpha=False).tobytes("png")
        finally:
            doc.close()


class Reader:
    """Per-route AIMD slots and per-model rotation, both under one condition (thread-safe).

    A route starts at ``start`` calls in flight, gains one after :data:`AIMD_WINDOW` successes in a row and loses 30%
    (floor one) on a throttle: it settles one notch below refusal.  ``model_for`` picks the model with the lowest EWMA
    seconds/page among the models not cooling down, tries every unmeasured model first in quality order, and makes
    every :data:`EXPLORE_EVERY`-th call on a route probe its least-recently-used model."""

    def __init__(self, routes: Iterable[str], start: int, cap: int):
        self.cv = threading.Condition()
        self.order = list(routes)
        self.cap = max(1, cap)
        self.routes = {name: {"limit": max(1, min(start, self.cap)), "cap": self.cap, "active": 0, "calls": 0,
                              "streak": 0, "ok": 0, "err": 0, "throttled": 0} for name in self.order}
        self.models = {name: [{"entry": entry, "ewma": None, "cool": 0.0, "cool_next": THROTTLE_START,
                               "last": 0, "ok": 0, "err": 0, "throttled": 0, "seconds": []}
                              for entry in FREE_ROUTES[name]["models"]] for name in self.order}
        self.tick = 0
        self.rr = 0
        self.limit_log: list[tuple[str, int, int, str]] = []

    def acquire(self) -> str | None:
        """Block until a route has a free slot, hold it and return the route's name (pair with :meth:`release`).

        Returns None when the run is stopping (a paid model answered), so the caller never holds a slot it must drop."""
        with self.cv:
            while not STOP.is_set():
                for i in range(len(self.order)):
                    name = self.order[(self.rr + i) % len(self.order)]
                    route = self.routes[name]
                    if route["active"] < route["limit"]:
                        route["active"] += 1
                        self.rr = (self.rr + i + 1) % len(self.order)
                        return name
                self.cv.wait(1.0)
            return None

    def release(self, route: str) -> None:
        with self.cv:
            self.routes[route]["active"] -= 1
            self.cv.notify_all()

    def model_for(self, route: str, now: float | None = None) -> dict[str, Any] | None:
        """The model to call on ``route``; waits out cooling models, returns None when the run stops meanwhile."""
        with self.cv:
            while not STOP.is_set():
                current = time.time() if now is None else now
                ready = [m for m in self.models[route] if m["cool"] <= current]
                if ready:
                    self.tick += 1
                    counts = self.routes[route]
                    counts["calls"] += 1
                    if counts["calls"] % EXPLORE_EVERY == 0:                 # probe the least-recently-used model
                        pick = min(ready, key=lambda m: m["last"])
                    else:
                        unmeasured = [m for m in ready if m["ewma"] is None]
                        pick = unmeasured[0] if unmeasured else min(ready, key=lambda m: (m["ewma"], m["last"]))
                    pick["last"] = self.tick
                    return pick["entry"]
                self.cv.wait(max(0.05, min(min(m["cool"] for m in self.models[route]) - current, 1.0)))
            return None

    def success(self, route: str, model: dict[str, Any], seconds: float) -> None:
        """Record one reading: the model's EWMA and cooling reset, the route's additive-increase streak."""
        with self.cv:
            state = self._model(route, model)
            if state is not None:
                state["ok"] += 1
                state["seconds"].append(seconds)
                state["ewma"] = (seconds if state["ewma"] is None
                                 else EWMA_ALPHA * seconds + (1 - EWMA_ALPHA) * state["ewma"])
                state["cool"], state["cool_next"] = 0.0, THROTTLE_START
            route_state = self.routes[route]
            route_state["ok"] += 1
            route_state["streak"] += 1
            if route_state["streak"] >= AIMD_WINDOW:
                route_state["streak"] = 0
                if route_state["limit"] < route_state["cap"]:
                    old = route_state["limit"]
                    route_state["limit"] = old + 1
                    self._limit(route, old, old + 1, f"{AIMD_WINDOW} ok")
            self.cv.notify_all()

    def throttle(self, route: str, model: dict[str, Any] | None, reason: str = "429") -> None:
        """Record a throttle: cool that model alone (not its siblings) and cut the route's limit by 30%."""
        with self.cv:
            state = self._model(route, model) if model else None
            if state is not None:
                state["throttled"] += 1
                state["cool"] = time.time() + state["cool_next"]
                state["cool_next"] = min(state["cool_next"] * 2, THROTTLE_MAX)
            route_state = self.routes[route]
            route_state["throttled"] += 1
            route_state["streak"] = 0
            old = route_state["limit"]
            new = max(1, int(old * AIMD_FACTOR))
            route_state["limit"] = new
            if new != old:
                self._limit(route, old, new, reason)
            self.cv.notify_all()

    def error(self, route: str, model: dict[str, Any] | None, reason: str) -> None:
        """Record a failed call (not a throttle): no limit change, the success streak restarts."""
        with self.cv:
            state = self._model(route, model) if model else None
            if state is not None:
                state["err"] += 1
            route_state = self.routes[route]
            route_state["err"] += 1
            route_state["streak"] = 0
            self.cv.notify_all()

    def summary(self) -> tuple[dict[str, Any], dict[str, int]]:
        """``({model id: {ok, err, throttled, median_s}}, {route: final limit})`` for the run summary."""
        with self.cv:
            models: dict[str, Any] = {}
            for states in self.models.values():
                for state in states:
                    seconds = sorted(state["seconds"])
                    models[state["entry"]["id"]] = {
                        "ok": state["ok"], "err": state["err"], "throttled": state["throttled"],
                        "median_s": round(seconds[len(seconds) // 2], 1) if seconds else 0.0}
            return models, {name: state["limit"] for name, state in self.routes.items()}

    def _model(self, route: str, model: dict[str, Any]) -> dict[str, Any] | None:
        for state in self.models[route]:
            if state["entry"] is model or state["entry"]["id"] == model["id"]:
                return state
        return None

    def _limit(self, route: str, old: int, new: int, reason: str) -> None:
        self.limit_log.append((route, old, new, reason))
        print(f"limit {route} {old}->{new} ({reason})", flush=True)


def _label(route: str, model: dict[str, Any]) -> str:
    """``kilo:nemotron-3.5`` / ``zen:deepseek-v4.1``: the route and short model name of a log line."""
    bare = model["id"].rsplit("/", 1)[-1].split(":")[0].removesuffix("-free")
    return f"{route}:{'-'.join(bare.split('-')[:2])}"


def _db(path: Path) -> sqlite3.Connection:
    with WRITE_LOCK:
        con = _DBS.get(path)
        if con is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(path, check_same_thread=False)
            con.executescript(SCHEMA)
            con.commit()
            _DBS[path] = con
        return con


_META_LOCK = threading.Lock()
_STATS: dict[str, Any] = {}


def _stats() -> dict[str, Any]:
    with _META_LOCK:
        if not _STATS:
            _STATS.update({"written": 0, "skipped": 0, "errors": 0, "attempt_errors": 0,
                          "route": Counter(), "seconds": [], "figures": [], "pages_with_4_figures": 0,
                          "samples": [], "paid": ""})
        return _STATS


def _log(fh, record: dict[str, Any]) -> None:
    with LOG_LOCK:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()


def _write(item: dict[str, Any], text: str, route: str, model: dict[str, Any], seconds: float, fh) -> None:
    words = pseudo_words(text)
    n_figures = figures(text)
    out = out_db(item["store"], item.get("out_dir"))
    con = _db(out)
    with WRITE_LOCK:
        con.execute("INSERT OR REPLACE INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (item["symbol"], item["doc_key"], item["page"], "deck", item["known_at"], text,
                     json.dumps(words, ensure_ascii=False, separators=(",", ":")), None, len(words), DPI,
                     round(seconds, 2), model["method"]))
        con.commit()
        stats = _stats()
        stats["written"] += 1
        stats["route"][route] += 1
        stats["seconds"].append(round(seconds, 2))
        stats["figures"].append(n_figures)
        stats["pages_with_4_figures"] += int(n_figures >= 4)
        if len(stats["samples"]) < 10:
            stats["samples"].append({"symbol": item["symbol"], "doc_key": item["doc_key"], "page": item["page"],
                                     "route": route, "model": model["id"], "method": model["method"],
                                     "seconds": round(seconds, 2), "text": text})
        _log(fh, {"symbol": item["symbol"], "store": item["store"], "doc_key": item["doc_key"], "page": item["page"],
                  "route": route, "model": model["id"], "seconds": round(seconds, 2), "error": "",
                  "chars": len(text), "figures": n_figures, "written": True})
    print(f"ok   {_label(route, model)} {item['symbol']:12s} p{item['page']:<3d} {seconds:5.1f}s "
          f"{len(text):5d} chars", flush=True)


def _attempt_error(item: dict[str, Any], route: str, model: dict[str, Any] | None, error: str, fh,
                   page_error: bool) -> None:
    stats = _stats()                                   # takes the lock itself: never call it inside _META_LOCK
    label = _label(route, model) if model else route
    with _META_LOCK:
        stats["attempt_errors"] += 1
        if page_error:
            stats["errors"] += 1
        _log(fh, {"symbol": item["symbol"], "store": item["store"], "doc_key": item["doc_key"],
                  "page": item["page"], "route": route, "model": (model or {}).get("id", ""), "seconds": 0,
                  "error": error[:300], "written": False, "page_error": page_error})
    print(f"ERR  {label} {item['symbol']:12s} p{item['page']:<3d} {'page' if page_error else 'retry'}: "
          f"{error[:120]}", flush=True)


def _drain(q: queue.Queue) -> None:
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return
        q.task_done()


def _worker(reader: Reader, q: queue.Queue, timeout: float, fh) -> None:
    """Take a page, hold a route slot for one call, and retry it on another route or model on failure."""
    backoff = BACKOFF_START
    while True:
        item = q.get()
        if item is None:
            q.task_done()
            return
        try:
            if STOP.is_set():
                continue
            item["tries"] = item.get("tries", 0) + 1
            route = reader.acquire()
            if route is None:
                continue
            try:
                model = reader.model_for(route)
                if model is None or STOP.is_set():
                    continue
                item.setdefault("failed", set()).add(route)
                t0 = time.time()
                try:
                    text = ask(route, render_page(item["pdf"], item["page"]), timeout, model)
                    if not text.strip():
                        raise RuntimeError("empty transcription")
                except Throttled as ex:
                    reader.throttle(route, model, "429")
                    if item["tries"] <= MAX_TRIES:
                        q.put(item)
                        time.sleep(backoff)
                        backoff = min(backoff * 2, BACKOFF_MAX)
                    else:
                        _attempt_error(item, route, model, f"429 after {item['tries']} tries: {ex}", fh, True)
                    continue
                except PaidModel as ex:
                    reader.error(route, model, "paid")
                    _attempt_error(item, route, model, str(ex), fh, True)
                    _stats()["paid"] = str(ex)                  # _stats() takes the lock itself
                    STOP.set()
                    _drain(q)
                    return
                except Exception as ex:                       # transient call failure: let another route try once
                    reader.error(route, model, str(ex))
                    page_error = item["tries"] >= MAX_TRIES or (len(item["failed"]) >= len(reader.order)
                                                                and item["tries"] >= max(2, len(reader.order)))
                    _attempt_error(item, route, model, str(ex), fh, page_error)
                    if not page_error:
                        time.sleep(2)
                        q.put(item)
                    continue
                backoff = BACKOFF_START
                seconds = time.time() - t0
                reader.success(route, model, seconds)
                _write(item, text, route, model, seconds, fh)
            finally:
                reader.release(route)
        finally:
            q.task_done()


def _held(out: Path) -> dict[tuple[str, str, int], str]:
    """``{(symbol, doc_key, page): method}`` already in an output database (empty when it does not exist)."""
    if not out.is_file():
        return {}
    try:
        con = sqlite3.connect(f"file:{out.as_posix()}?mode=ro", uri=True)
        try:
            return {(str(r[0]), str(r[1]), int(r[2])): str(r[3] or "")
                    for r in con.execute("SELECT symbol, doc_key, page, method FROM ocr_page")}
        finally:
            con.close()
    except sqlite3.Error:
        return {}


def run(pages: list[dict[str, Any]], routes: list[str], out_dir: Path | str | None = None, resume: bool = False,
        log: Path | str | None = None, timeout: float = 420, enabled: dict[str, bool] | None = None,
        start_workers: int = 6, max_workers: int = 24) -> dict[str, Any]:
    """Read ``pages`` over ``routes`` and write the rows.  Returns the summary dict.

    Each route starts at ``start_workers`` calls in flight and adapts between one and ``max_workers``; threads are the
    sum of the caps and a thread holds a route slot for its call.  A page already held under any ocr_fill method
    (:data:`OCR_METHODS`) is never overwritten; ``resume`` also skips pages this fill already read, whichever of its
    models read them.  With ``out_dir`` the rows go to ``<out_dir>/<stem>_ocr.db`` and nothing is written beside a
    live store."""
    log_path = Path(log) if log else (Path(out_dir) / "ocr_fill.jsonl" if out_dir else Path("ocr_fill.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    STOP.clear()
    with _META_LOCK:
        _STATS.clear()
    if enabled is None:                          # a route without its key is left out, not failed page by page
        from reality_engine.scripts.resource_watchdog import user_env
        env = user_env()
        enabled = {r: FREE_ROUTES[r]["kind"] == "cli" or bool(env.get(FREE_ROUTES[r].get("key_env", "")))
                   for r in routes}
    active = [r for r in routes if enabled.get(r, True)]
    stats = _stats()
    stats["routes_enabled"] = active
    held_cache: dict[Path, dict[tuple[str, str, int], str]] = {}
    todo: list[dict[str, Any]] = []
    for item in pages:
        item = dict(item)
        item["out_dir"] = str(out_dir) if out_dir else None
        out = out_db(item["store"], item["out_dir"])
        if out not in held_cache:
            held_cache[out] = _held(out)
        method = held_cache[out].get((item["symbol"], item["doc_key"], item["page"]))
        if method is not None and (method not in OCR_METHODS or resume):
            stats["skipped"] += 1
            continue
        todo.append(item)
    if not active:
        raise SystemExit("no usable free route (keys missing and no CLI route)")
    reader = Reader(active, start_workers, max_workers)
    store = raw_store.default_store()
    q: queue.Queue = queue.Queue()
    for item in todo:
        q.put(item)
    with log_path.open("a", encoding="utf-8") as fh, _shared_acl_tempdirs(), \
            store.prefetch([item["pdf"] for item in todo]):
        threads = [threading.Thread(target=_worker, args=(reader, q, timeout, fh), daemon=True)
                   for _ in range(sum(state["cap"] for state in reader.routes.values()))]
        for thread in threads:
            thread.start()
        q.join()
        for _thread in threads:
            q.put(None)
        for thread in threads:
            thread.join()
    for con in _DBS.values():
        con.commit()
        con.close()
    _DBS.clear()
    stats["models"], stats["limits"] = reader.summary()
    total_seconds = round(sum(stats["seconds"]), 1)
    stats["pages"] = len(pages)
    stats["todo"] = len(todo)
    stats["seconds_total"] = total_seconds
    stats["seconds_per_page"] = round(total_seconds / stats["written"], 1) if stats["written"] else 0.0
    stats["median_seconds"] = round(sorted(stats["seconds"])[len(stats["seconds"]) // 2], 1) if stats["seconds"] else 0.0
    samples = Path(log_path).with_name("samples.txt")
    samples.write_text("\n\n".join(f"== {s['symbol']} p{s['page']} [{s['route']}:{s['model']}] {s['seconds']}s\n"
                                   f"{s['text']}" for s in stats["samples"]), encoding="utf-8")
    stats["log"] = str(log_path)
    stats["samples_file"] = str(samples)
    STOP.clear()
    print(json.dumps({k: (dict(v) if isinstance(v, Counter) else v) for k, v in stats.items()
                      if k not in ("seconds", "figures", "samples")}, indent=2))
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="fill <store>_ocr.db with free vision-model readings of the image-only "
                                             "deck pages")
    ap.add_argument("--universe", default=str(DEFAULT_UNIVERSE), help="the universe root holding c*/routes.csv")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None, help="shuffle the sorted page list first (reproducible pilot)")
    ap.add_argument("--symbols", default=None, help="comma-separated symbols (default: every universe company)")
    ap.add_argument("--out-dir", default=None, help="write <store stem>_ocr.db under this dir instead of beside the "
                                                    "live store (a pilot must not feed the live loop)")
    ap.add_argument("--resume", action="store_true", help="skip pages these models already read")
    ap.add_argument("--routes", default="kilo,zen")
    ap.add_argument("--start-workers", type=int, default=6,
                    help="each route's starting calls in flight; AIMD grows it (default 6)")
    ap.add_argument("--max-workers", type=int, default=24,
                    help="cap for each route's calls in flight; threads = the sum of the caps (default 24)")
    ap.add_argument("--log", default=None)
    ap.add_argument("--timeout", type=float, default=420)
    args = ap.parse_args(argv)
    pages = select(args.universe, [s for s in (args.symbols or "").split(",") if s], args.seed, args.limit)
    if not pages:
        print("no pages selected", file=sys.stderr)
        return 1
    run(pages, parse_routes(args.routes), args.out_dir, args.resume, args.log, args.timeout,
        start_workers=args.start_workers, max_workers=args.max_workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
