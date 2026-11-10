"""T-177: reference pages - sample, transcribe, reconcile.

Usage:
    python -m reality_engine.v2.reference_pages sample --stores D:/RealityEngine/p20/p20new.db,... --out <dir> --seed 20261110
    python -m reality_engine.v2.reference_pages transcribe --pages <pages.csv> --reader <MODELS name> --input text|image --out <dir> [--split dev]
    python -m reality_engine.v2.reference_pages reconcile --pages <pages.csv> --runs <dirA> <dirB> --out <dir>
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import pymupdf

from reality_engine.db.readonly import connect_ro
from reality_engine.scripts.go_session import session_id as _session_id

# Reuse free-model client pieces by import (do not copy).
from reality_engine.scripts.extract_deck_figures import (
    MODELS, render_jpeg_b64, text_numbers, parse_number,
)

# Make registry keys available when present.
try:
    from reality_engine.scripts.resource_watchdog import user_env as _user_env
    _ue = _user_env()
    for _k, _v in _ue.items():
        os.environ.setdefault(_k, _v)
except Exception:
    pass

STORE_MAP = {
    "p20": "D:/RealityEngine/p20/p20new.db",
    "p20new": "D:/RealityEngine/p20/p20new.db",
    "p20new.db": "D:/RealityEngine/p20/p20new.db",
    "u8": "D:/RealityEngine/u8/u8.db",
    "u8.db": "D:/RealityEngine/u8/u8.db",
    "q12": "D:/RealityEngine/q12/q12.db",
    "q12.db": "D:/RealityEngine/q12/q12.db",
}

DECK_FIGURES_DB = "C:/Users/warri/Downloads/Info_Diffusion_Model/reality_engine/data/deck_figures.db"

DECK_SHA_SET: set[str] | None = None


def _deck_sha_set() -> set[str]:
    global DECK_SHA_SET
    if DECK_SHA_SET is not None:
        return DECK_SHA_SET
    try:
        con = connect_ro(DECK_FIGURES_DB, timeout_s=60)
        _cur = con.execute("SELECT DISTINCT sha256 FROM pages")
        _shas = []
        if _cur is not None:
            for _row in _cur:
                if _row is not None:
                    _shas.append(_row[0])
        DECK_SHA_SET = set(_shas)
        con.close()
    except Exception:
        DECK_SHA_SET = set()
    return DECK_SHA_SET


def resolve_store(name: str) -> str:
    s = str(name).strip()
    if s in STORE_MAP:
        return STORE_MAP[s]
    if Path(s).is_file():
        return s
    # try basename
    base = Path(s).name
    if base in STORE_MAP:
        return STORE_MAP[base]
    if base.replace(".db", "") in STORE_MAP:
        return STORE_MAP[base.replace(".db", "")]
    return s


def _store_label(path: str) -> str:
    p = Path(path)
    parent = p.parent.name
    if parent in ("p20", "u8", "q12"):
        return parent
    stem = p.stem
    if stem == "p20new":
        return "p20"
    return stem


def _doc_type_norm(t: str) -> str:
    t = (t or "").lower().strip()
    if t in ("deck", "investor_presentation"):
        return "deck"
    if t in ("results", "quarterly_results"):
        return "results"
    if t in ("annual_report",):
        return "annual_report"
    return t


def _stratum(text: str, doc_type: str) -> str:
    low = (text or "").lower()
    if not low.strip():
        return "unread"
    if re.search(r"\b(lakh|lakhs|lac|lacs|crore|crores|million|millions|billion|billions|bn)\b", low):
        return "scale_words"
    periods = set(re.findall(r"\b(?:q[1-4]|h[12]|fy|9m|ytd)\s*\d{2,4}\b", low))
    if len(periods) >= 5:
        return "multi_period"
    if re.search(r"\b(particulars|description)\b", low) and low.count("\n") >= 3:
        # crude two-level header hint
        return "two_level_header"
    if doc_type == "deck":
        return "deck_panel"
    return "ruled_table"


def _page_text(con, doc_key: str, page: int) -> str:
    try:
        _cur = con.execute(
            "SELECT text FROM doc_page WHERE doc_key=? AND page=?", (doc_key, page)
        )
        row = _cur.fetchone() if _cur is not None else None
        if row:
            return row[0] or ""
    except Exception:
        pass
    return ""


def _candidate_pages(store_path: str, doc_types: tuple[str, ...]) -> list[dict[str, Any]]:
    con = connect_ro(store_path, timeout_s=60)
    label = _store_label(store_path)
    deck_shas = _deck_sha_set()
    # load docs
    _cur = con.execute(
        "SELECT doc_key, symbol, doc_type, sha256, pages FROM doc"
    )
    docs = []
    if _cur is not None:
        for _row in _cur:
            if _row is not None:
                docs.append(_row)
    out: list[dict[str, Any]] = []
    for doc_key, symbol, doc_type, sha256, pages in docs:
        dt = _doc_type_norm(doc_type)
        if dt not in doc_types:
            continue
        n_pages = pages or 0
        for pg in range(1, n_pages + 1):
            text = _page_text(con, doc_key, pg)
            tn = text_numbers(text) if text.strip() else set()
            num_count = len(tn)
            unread = (not text.strip()) or num_count < 5
            # readable requires text layer + >=15 value numbers
            readable = bool(text.strip()) and num_count >= 15
            # chart-only/no-text unread candidates only for deck
            in_first = bool(sha256 and sha256 in deck_shas) if dt == "deck" else False
            strat = _stratum(text, dt)
            if not readable and not (dt == "deck" and unread):
                continue
            if not readable:
                strat = "unread"
            out.append({
                "store": label,
                "store_path": store_path,
                "symbol": symbol,
                "doc_key": doc_key,
                "sha256": sha256 or "",
                "doc_type": dt,
                "page": pg,
                "text": text,
                "stratum": strat,
                "in_first_build": in_first,
                "num_count": num_count,
                "unread": not readable,
            })
    con.close()
    return out


def sample_pages(stores: list[str], out: Path, seed: int = 20261110) -> list[dict[str, Any]]:
    store_paths = [resolve_store(s) for s in stores]
    # collect candidates by type
    cands_by_type: dict[str, list[dict[str, Any]]] = {"deck": [], "results": [], "annual_report": []}
    for sp in store_paths:
        for dt in ("deck", "results", "annual_report"):
            cands_by_type[dt].extend(_candidate_pages(sp, (dt,)))

    rng = random.Random(seed)
    selected: list[dict[str, Any]] = []
    company_counts: dict[str, int] = {}

    def can_add(c: dict[str, Any]) -> bool:
        sym = c["symbol"]
        return company_counts.get(sym, 0) < 4

    def add(c: dict[str, Any]) -> None:
        selected.append(c)
        company_counts[c["symbol"]] = company_counts.get(c["symbol"], 0) + 1

    # deck: 4 unread first, then readable to 30
    deck_unread = [c for c in cands_by_type["deck"] if c["unread"]]
    deck_read = [c for c in cands_by_type["deck"] if not c["unread"]]
    rng.shuffle(deck_unread)
    rng.shuffle(deck_read)
    # prefer in_first_build: stable sort
    deck_unread.sort(key=lambda c: (not c["in_first_build"],))
    deck_read.sort(key=lambda c: (not c["in_first_build"],))
    # pick 4 unread
    n_unread = 0
    for c in deck_unread:
        if n_unread >= 4:
            break
        if can_add(c):
            add(c); n_unread += 1
    # pick readable to reach 30 deck total
    deck_selected_before = sum(1 for c in selected if c["doc_type"] == "deck")
    for c in deck_read:
        if deck_selected_before >= 30:
            break
        if can_add(c):
            add(c); deck_selected_before += 1

    # results: 20
    res_cands = list(cands_by_type["results"])
    rng2 = random.Random(seed + 1)
    rng2.shuffle(res_cands)
    res_count = sum(1 for c in selected if c["doc_type"] == "results")
    for c in res_cands:
        if res_count >= 20:
            break
        if can_add(c):
            add(c); res_count += 1

    # annual report: 10
    ar_cands = list(cands_by_type["annual_report"])
    rng3 = random.Random(seed + 2)
    rng3.shuffle(ar_cands)
    ar_count = sum(1 for c in selected if c["doc_type"] == "annual_report")
    for c in ar_cands:
        if ar_count >= 10:
            break
        if can_add(c):
            add(c); ar_count += 1

    # assign split balanced by doc type
    by_type: dict[str, list[dict[str, Any]]] = {"deck": [], "results": [], "annual_report": []}
    for c in selected:
        by_type[c["doc_type"]].append(c)
    rng4 = random.Random(seed + 3)
    split_map: dict[int, str] = {}
    for dt, lst in by_type.items():
        lst_sorted = sorted(lst, key=lambda c: (c["store"], c["symbol"], c["doc_key"], c["page"]))
        idxs = list(range(len(lst_sorted)))
        rng4.shuffle(idxs)
        half = len(lst_sorted) // 2
        for i, c in enumerate(lst_sorted):
            # mark via id(c)
            c["_split"] = "dev" if i < half else "frozen"
    # Actually use shuffled half for balance? Simpler: first half dev. Fine.

    # assign page_id
    ordered = sorted(selected, key=lambda c: (c["doc_type"], c["store"], c["symbol"], c["doc_key"], c["page"]))
    for i, c in enumerate(ordered, start=1):
        c["page_id"] = f"p{i:03d}"

    # write csv
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "pages.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["page_id", "store", "symbol", "doc key", "sha256", "doc type", "page", "stratum", "in_first_build", "split"])
        for c in ordered:
            w.writerow([
                c["page_id"],
                c["store"],
                c["symbol"],
                c["doc_key"],
                c["sha256"],
                c["doc_type"],
                c["page"],
                c["stratum"],
                "True" if c["in_first_build"] else "False",
                c["_split"],
            ])
    return ordered


def sample(args) -> int:
    stores = [s.strip() for s in args.stores.split(",") if s.strip()]
    out = Path(args.out)
    rows = sample_pages(stores, out, seed=args.seed)
    # counts
    from collections import Counter
    types = Counter(r["doc_type"] for r in rows)
    splits = Counter(r["_split"] for r in rows)
    print(f"sampled {len(rows)} pages: {dict(types)} splits={dict(splits)} -> {out/'pages.csv'}")
    return 0


# ---------- transcribe ----------

def _is_free(reader: str) -> bool:
    cfg = MODELS.get(reader, {})
    if cfg.get("price") != (0.0, 0.0):
        return False
    name = reader
    ident = cfg.get("id", reader)
    low = (name + " " + str(ident)).lower()
    return "free" in low


def _model_call(reader: str, prompt: str, image_b64: str | None) -> dict[str, Any]:
    cfg = MODELS.get(reader, {})
    if not cfg:
        return {"output": "", "seconds": 0.0, "in_tok": 0, "out_tok": 0, "error": "unknown model"}
    if not _is_free(reader):
        return {"output": "", "seconds": 0.0, "in_tok": 0, "out_tok": 0, "error": "not a free model"}
    import requests
    t0 = time.time()
    try:
        if cfg.get("api") == "cli":
            # opencode cli
            import base64, subprocess
            from reality_engine.scripts.ar_queue import ANSI, opencode_exe
            tmp = Path(".tmp") / "zen_tmp"
            tmp.mkdir(parents=True, exist_ok=True)
            stem = tmp / (str(time.time()).replace(".", "") + "_" + reader.replace("/", "_"))
            txt = stem.with_suffix(".txt")
            txt.write_text(prompt, encoding="utf-8")
            cmd = [opencode_exe(), "run", "-m", f"opencode/{cfg.get('id', reader)}", "--title", f"ref {reader}",
                   "Read the attached text and follow instructions exactly. Do not use tools. Reply with requested output only.",
                   "-f", str(txt)]
            if image_b64:
                img = stem.with_suffix(".jpg")
                img.write_bytes(base64.b64decode(image_b64))
                cmd += ["-f", str(img)]
            try:
                p = subprocess.run(cmd, cwd=tmp, stdin=subprocess.DEVNULL, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   timeout=300, creationflags=0x08000000)
            finally:
                txt.unlink(missing_ok=True)
                if image_b64:
                    img.unlink(missing_ok=True)
            out = "\n".join(l for l in ANSI.sub("", p.stdout).splitlines() if not l.startswith("> ")).strip()
            err = ANSI.sub("", p.stdout + " " + p.stderr)
            if p.returncode != 0 and not out:
                return {"output": "", "seconds": time.time() - t0, "in_tok": 0, "out_tok": 0,
                        "error": err[-300:]}
            return {"output": out, "seconds": time.time() - t0, "in_tok": 0, "out_tok": 0, "error": None}
        env_name = cfg.get("key_env", "OPENCODE_GO_API_KEY")
        key = os.environ.get(env_name, "")
        base = cfg.get("base", "https://opencode.ai/zen/go/v1")
        if cfg.get("api") == "gemini_native":
            import requests as _r
            body = {"contents": [{"parts": []}], "generationConfig": cfg.get("body", {})}
            parts = body["contents"][0]["parts"]
            if image_b64:
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": image_b64}})
            parts.append({"text": prompt})
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.get('id', reader)}:generateContent",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json=body, timeout=300)
            if r.status_code != 200:
                return {"output": "", "seconds": time.time() - t0, "in_tok": 0, "out_tok": 0,
                        "error": f"HTTP {r.status_code}: {r.text[:300]}"}
            j = r.json()
            u = j.get("usageMetadata", {})
            if not j.get("candidates"):
                return {"output": "", "seconds": time.time() - t0, "in_tok": 0, "out_tok": 0,
                        "error": f"no candidates: {r.text[:300]}"}
            text = "".join(p.get("text", "") for p in j["candidates"][0]["content"].get("parts", []) if not p.get("thought"))
            return {"output": text, "seconds": time.time() - t0,
                    "in_tok": u.get("promptTokenCount", 0),
                    "out_tok": u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0),
                    "error": None}
        # chat / responses (openai-compatible)
        url = base.rstrip("/") + ("/chat/completions" if cfg.get("api", "chat") == "chat" else "/responses")
        if cfg.get("api") == "chat":
            content: Any
            if image_b64:
                content = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_b64}},
                           {"type": "text", "text": prompt}]
            else:
                content = prompt
            body = {"model": cfg.get("id", reader), **cfg.get("body", {}), "messages": [{"role": "user", "content": content}]}
        else:
            url = base.rstrip("/") + "/responses"
            content = []
            if image_b64:
                content.append({"type": "input_image", "image_url": "data:image/jpeg;base64," + image_b64})
            content.append({"type": "input_text", "text": prompt})
            body = {"model": reader, **cfg.get("body", {}), "input": [{"role": "user", "content": content}]}
        r = requests.post(url, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                       "x-opencode-session": _session_id("reference_pages", reader, "", 0), "User-Agent": "reality-engine/1.0"},
                          json=body, timeout=300)
        if r.status_code != 200:
            return {"output": "", "seconds": time.time() - t0, "in_tok": 0, "out_tok": 0,
                    "error": f"HTTP {r.status_code}: {r.text[:300]}"}
        j = r.json()
        if cfg.get("api") == "chat":
            if not j.get("choices"):
                return {"output": "", "seconds": time.time() - t0, "in_tok": 0, "out_tok": 0,
                        "error": f"no choices: {r.text[:300]}"}
            text = j["choices"][0]["message"].get("content") or ""
            u = j.get("usage", {})
            return {"output": text, "seconds": time.time() - t0,
                    "in_tok": u.get("prompt_tokens", 0), "out_tok": u.get("completion_tokens", 0), "error": None}
        text = "".join(c.get("text", "") for o in j.get("output", []) if o.get("type") == "message" for c in o.get("content", []))
        u = j.get("usage", {})
        return {"output": text, "seconds": time.time() - t0,
                "in_tok": u.get("input_tokens", 0), "out_tok": u.get("output_tokens", 0), "error": None}
    except Exception as e:
        return {"output": "", "seconds": time.time() - t0, "in_tok": 0, "out_tok": 0, "error": f"{type(e).__name__}: {e}"}


TRANSCRIBE_PROMPT = (
    "Transcribe every table on this page into a grid. If the page has any table (ruled or unruled, including panels), "
    "you MUST output one object per cell; do not answer []. Use [] ONLY when the page truly has no table. "
    "Output a JSON array of objects, one per cell, with keys: \"table\" (table title as printed, or \"\" if none), "
    "\"row_label\" (row label as printed), \"col_header\" (column header as printed; join multiple header levels with "
    "\" > \"), \"value\" (value as printed), \"unit\" (unit as printed). "
    "Copy values verbatim. No summaries, computed values, or interpretation. Output only the JSON array."
)


def _parse_rows(raw: str) -> list[dict[str, Any]]:
    raw = (raw or "").strip()
    # strip markdown fences
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()
    # try direct JSON
    try:
        obj = json.loads(raw)
        if isinstance(obj, list):
            return [r for r in obj if isinstance(r, dict)]
        if isinstance(obj, dict):
            # maybe {"cells":[...]}
            for v in obj.values():
                if isinstance(v, list):
                    return [r for r in v if isinstance(r, dict)]
    except Exception:
        pass
    # extract first JSON array
    m = re.search(r"\[.*\]", raw, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, list):
                return [r for r in obj if isinstance(r, dict)]
        except Exception:
            pass
    # JSON lines
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            continue
    return rows


def _normalize_row(r: dict[str, Any]) -> dict[str, str]:
    return {
        "table": str(r.get("table", "") or ""),
        "row_label": str(r.get("row_label", r.get("row", r.get("label", ""))) or ""),
        "col_header": str(r.get("col_header", r.get("column", r.get("header", ""))) or ""),
        "value": str(r.get("value", r.get("value_text", "")) or ""),
        "unit": str(r.get("unit", r.get("unit_text", "")) or ""),
    }


def _load_pages_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _page_image_b64(store_path: str, doc_key: str, page: int) -> str:
    con = connect_ro(store_path, timeout_s=60)
    _cur = con.execute("SELECT source_key FROM doc WHERE doc_key=?", (doc_key,))
    row = _cur.fetchone() if _cur is not None else None
    con.close()
    pdf_path = row[0] if row else None
    if not pdf_path or not Path(pdf_path).is_file():
        return ""
    with pymupdf.open(pdf_path) as doc:
        if page < 1 or page > len(doc):
            return ""
        return render_jpeg_b64(doc[page - 1])


def _page_text_for(store: str, doc_key: str, page: int) -> str:
    sp = resolve_store(store)
    con = connect_ro(sp, timeout_s=60)
    text = _page_text(con, doc_key, page)
    con.close()
    return text


def transcribe_pages(pages_csv: Path, reader: str, input_mode: str, out: Path, split: str | None = None) -> int:
    if not _is_free(reader):
        raise SystemExit(f"reader {reader!r} is not a free model; refusing")
    rows_meta = _load_pages_csv(pages_csv)
    if split:
        rows_meta = [r for r in rows_meta if (r.get("split") or "").strip().lower() == split.lower()]
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "transcribe_log.csv"
    # resume: existing log
    done_ids = set()
    for p in out.glob("*.rows.json"):
        done_ids.add(p.stem.replace(".rows", ""))
    # Actually rows files named <page_id>.rows.json
    done_ids = {p.name.replace(".rows.json", "") for p in out.glob("*.rows.json")}

    log_rows: list[dict[str, Any]] = []
    # load existing log if present
    if log_path.exists():
        with log_path.open(newline="", encoding="utf-8") as fh:
            log_rows = list(csv.DictReader(fh))

    for meta in rows_meta:
        pid = meta["page_id"]
        if pid in done_ids:
            continue
        store = meta["store"]
        doc_key = meta["doc key"]
        page = int(meta["page"])
        store_path = resolve_store(store)
        if input_mode == "image":
            img = _page_image_b64(store_path, doc_key, page)
            prompt = TRANSCRIBE_PROMPT
            res = _model_call(reader, prompt, img if img else None)
        else:
            text = _page_text_for(store, doc_key, page)
            prompt = TRANSCRIBE_PROMPT + "\n\nPage text (words in reading order):\n<<<\n" + text[:12000] + "\n>>>"
            res = _model_call(reader, prompt, None)
        parsed = []
        if res["error"] is None:
            parsed = [_normalize_row(r) for r in _parse_rows(res["output"])]
        # save raw
        (out / f"{pid}.raw.txt").write_text(res["output"] or "", encoding="utf-8")
        (out / f"{pid}.rows.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=1), encoding="utf-8")
        log_rows.append({
            "page_id": pid,
            "reader": reader,
            "input": input_mode,
            "seconds": round(res["seconds"], 2),
            "in_tok": res["in_tok"],
            "out_tok": res["out_tok"],
            "error": res["error"] or "",
            "n_rows": len(parsed),
        })
        done_ids.add(pid)
        print(f"{pid}: {len(parsed)} rows, {res['seconds']:.1f}s, err={res['error']}")

    with log_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["page_id", "reader", "input", "seconds", "in_tok", "out_tok", "error", "n_rows"])
        w.writeheader()
        for lr in log_rows:
            w.writerow(lr)
    return 0


def transcribe(args) -> int:
    return transcribe_pages(Path(args.pages), args.reader, args.input, Path(args.out), args.split)


# ---------- reconcile ----------

def _norm_space(s: Any) -> str:
    return " ".join(str(s or "").split())


def _norm_value(s: Any) -> str:
    v = _norm_space(s)
    m = re.fullmatch(r"\((.+)\)", v)
    if m:
        v = "-" + m.group(1)
    v = v.replace(",", "")
    return v.casefold()


def _load_run_rows(run_dir: Path, pid: str) -> list[dict[str, str]]:
    p = run_dir / f"{pid}.rows.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [_normalize_row(r) if isinstance(r, dict) else {} for r in data]
    except Exception:
        return []
    return []


def _is_total(label: str) -> bool:
    low = _norm_space(label).lower()
    return ("total" in low) or ("subtotal" in low) or low.startswith("sum")


def reconcile_pages(pages_csv: Path, runs: list[Path], out: Path) -> int:
    meta_rows = _load_pages_csv(pages_csv)
    run_a, run_b = runs[0], runs[1]
    out.mkdir(parents=True, exist_ok=True)
    all_cells: list[dict[str, Any]] = []
    disputes: list[dict[str, Any]] = []

    for meta in meta_rows:
        pid = meta["page_id"]
        store = meta["store"]
        doc_key = meta["doc key"]
        page = int(meta["page"])
        text = _page_text_for(store, doc_key, page)
        norm_text = _norm_space(text).casefold().replace(",", "")
        # removing thousands separators from text too for verbatim check? keep both
        text_norm = _norm_space(text).casefold()

        rows_a = _load_run_rows(run_a, pid)
        rows_b = _load_run_rows(run_b, pid)

        # union keys
        keys: list[tuple[str, str, str]] = []
        seen = set()
        for r in rows_a + rows_b:
            k = (_norm_space(r.get("table", "")).casefold(),
                 _norm_space(r.get("row_label", "")).casefold(),
                 _norm_space(r.get("col_header", "")).casefold())
            if k not in seen:
                seen.add(k)
                keys.append(k)

        # map from key to row
        map_a = {}
        for r in rows_a:
            k = (_norm_space(r.get("table", "")).casefold(),
                 _norm_space(r.get("row_label", "")).casefold(),
                 _norm_space(r.get("col_header", "")).casefold())
            map_a[k] = r
        map_b = {}
        for r in rows_b:
            k = (_norm_space(r.get("table", "")).casefold(),
                 _norm_space(r.get("row_label", "")).casefold(),
                 _norm_space(r.get("col_header", "")).casefold())
            map_b[k] = r

        # group by table+col for sums check
        # build per (table, col) list of (label, value)
        table_col_values: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for k in keys:
            r = map_a.get(k) or map_b.get(k)
            if r:
                table_col_values.setdefault((k[0], k[2]), []).append((k[1], r.get("value", "")))

        sums_ok_map: dict[tuple[str, str, str], bool] = {}
        for (tbl, col), vals in table_col_values.items():
            # find total rows
            for label, value in vals:
                if _is_total(label if False else None) if False else False:
                    pass
            # Actually map label from key; recompute below
        # compute sums_ok per key
        for k in keys:
            r = map_a.get(k) or map_b.get(k)
            label = r.get("row_label", "") if r else ""
            value = r.get("value", "") if r else ""
            if not _is_total(label):
                sums_ok_map[k] = False
                continue
            # sum parts
            parts = []
            for (lbl, val) in table_col_values.get((k[0], k[2]), []):
                if lbl == k[1]:
                    continue
                if _is_total(lbl):
                    continue
                v = parse_number(val)
                if v is not None:
                    parts.append(v)
            total_v = parse_number(value)
            if total_v is None or not parts:
                sums_ok_map[k] = False
                continue
            s = sum(parts)
            tol = max(0.5, 0.005 * abs(total_v))
            sums_ok_map[k] = abs(s - total_v) <= tol

        n_cells = len(keys)
        n_agreed = 0
        n_verbatim = 0
        for k in keys:
            ra = map_a.get(k)
            rb = map_b.get(k)
            va = ra.get("value", "") if ra else ""
            ua = ra.get("unit", "") if ra else ""
            vb = rb.get("value", "") if rb else ""
            ub = rb.get("unit", "") if rb else ""
            # table/label/header original casing from ra or rb
            table = (ra or rb or {}).get("table", "")
            row_label = (ra or rb or {}).get("row_label", "")
            col_header = (ra or rb or {}).get("col_header", "")
            agreed = _norm_value(va) == _norm_value(vb) and va != "" and vb != ""
            # if only one side present, not agreed
            if ra is None or rb is None:
                agreed = False
            value_text = va if va else vb
            unit_text = ua if ua else ub
            # verbatim check
            vnorm = _norm_value(value_text).replace("-", "")
            verbatim = False
            if value_text.strip():
                # check if value token in text
                if _norm_value(value_text) in text_norm.replace(",", ""):
                    verbatim = True
                else:
                    # try without spaces
                    if _norm_value(value_text).replace(" ", "") in text_norm.replace(" ", "").replace(",", ""):
                        verbatim = True
            if verbatim:
                n_verbatim += 1
            if agreed:
                n_agreed += 1
            so = sums_ok_map.get(k, False)
            settled = "script" if (agreed and verbatim) else ""
            all_cells.append({
                "page_id": pid,
                "table": table,
                "row_label": row_label,
                "col_header": col_header,
                "value_text": value_text,
                "unit_text": unit_text,
                "agreed": "True" if agreed else "False",
                "verbatim": "True" if verbatim else "False",
                "sums_ok": "True" if so else "False",
                "settled_by": settled,
            })
            disputes.append({
                "page_id": pid,
                "table": table,
                "row_label": row_label,
                "col_header": col_header,
                "value_a": va,
                "unit_a": ua,
                "value_b": vb,
                "unit_b": ub,
                "agreed": "True" if agreed else "False",
            })

        agreed_share = (n_agreed / n_cells) if n_cells else 0.0
        verbatim_share = (n_verbatim / n_cells) if n_cells else 0.0
        print(f"{pid}: cells={n_cells} agreed_share={agreed_share:.3f} verbatim_share={verbatim_share:.3f}")

    # write reference_cells.csv
    rc_path = out / "reference_cells.csv"
    with rc_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["page_id", "table", "row_label", "col_header", "value_text", "unit_text", "agreed", "verbatim", "sums_ok", "settled_by"])
        w.writeheader()
        for c in all_cells:
            w.writerow(c)
    # write disputes.csv
    disp_path = out / "disputes.csv"
    with disp_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["page_id", "table", "row_label", "col_header", "value_a", "unit_a", "value_b", "unit_b", "agreed"])
        w.writeheader()
        for d in disputes:
            w.writerow(d)
    print(f"wrote {len(all_cells)} cells -> {rc_path}; disputes -> {disp_path}")
    return 0


def reconcile(args) -> int:
    runs = [Path(r) for r in args.runs]
    return reconcile_pages(Path(args.pages), runs, Path(args.out))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="T-177 reference pages tool")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_sample = sub.add_parser("sample")
    p_sample.add_argument("--stores", required=True)
    p_sample.add_argument("--out", required=True, type=Path)
    p_sample.add_argument("--seed", type=int, default=20261110)
    p_sample.set_defaults(func=sample)

    p_trans = sub.add_parser("transcribe")
    p_trans.add_argument("--pages", required=True, type=Path)
    p_trans.add_argument("--reader", required=True)
    p_trans.add_argument("--input", required=True, choices=["text", "image"])
    p_trans.add_argument("--out", required=True, type=Path)
    p_trans.add_argument("--split", default=None)
    p_trans.set_defaults(func=transcribe)

    p_rec = sub.add_parser("reconcile")
    p_rec.add_argument("--pages", required=True, type=Path)
    p_rec.add_argument("--runs", nargs=2, required=True)
    p_rec.add_argument("--out", required=True, type=Path)
    p_rec.set_defaults(func=reconcile)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
