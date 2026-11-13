"""Measure how often an evidence pack CONTAINS the grader truth."""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from statistics import median

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reality_engine.answer import evidence_pack as ep

os.environ.setdefault("REALITY_DATA_ALLOW_PAID_EMBED", "1")


def normalize_number(tok: str) -> str:
    t = (tok or "").strip()
    t = t.replace(",", "")
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return t


_PERIOD_RE = re.compile(r"(?:Q[1-4]|H[12]|9M)\s*FY\s*\d{2,4}|FY\s*\d{2,4}", re.I)
_PAGE_RE = re.compile(r"\b(?:p\.?\s*\d+|page\s+\d+)\b", re.I)
_UUID_RE = re.compile(r"\b[0-9a-f]{8,}\b", re.I)
_DATE_ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _strip_noise(text: str) -> str:
    t = text or ""
    t = _PERIOD_RE.sub(" ", t)
    t = _DATE_ISO_RE.sub(" ", t)
    t = _PAGE_RE.sub(" ", t)
    t = _UUID_RE.sub(" ", t)
    # drop years 1990-2035
    def _yr(m):
        y = int(m.group(0))
        return " " if 1990 <= y <= 2035 else m.group(0)
    t = re.sub(r"\b\d{4}\b", _yr, t)
    return t


def _extract_numbers(text: str) -> list[str]:
    cleaned = _strip_noise(text or "")
    out = []
    for m in re.finditer(r"\d[\d,]*\.?\d*", cleaned):
        raw = m.group(0)
        # percentage check
        end = m.end()
        is_pct = end < len(cleaned) and cleaned[end:end+1] == "%"
        v = normalize_number(raw)
        if not v:
            continue
        # keep rules: decimal point, 3+ digits, or percentage
        has_decimal = "." in raw
        digit_count = len(raw.replace(",", "").replace(".", ""))
        if not (has_decimal or digit_count >= 3 or is_pct):
            continue
        out.append(v)
    return out


def _extract_quoted(text: str, n: int = 3) -> list[str]:
    qs = re.findall(r'"([^"]+)"|\'([^\']+)\'', text or "")
    out = []
    for a, b in qs:
        s = (a or b).strip()
        if s:
            out.append(s)
        if len(out) >= n:
            break
    return out[:n]


def _key_phrases(text: str, n: int = 3) -> list[str]:
    # quoted first; fallback to a few 2-4 word noun-ish chunks not implemented (keep quoted)
    return _extract_quoted(text, n)


def truth_tokens(truth: str) -> dict:
    nums = _extract_numbers(truth or "")
    phrases = _key_phrases(truth or "", 3)
    return {"numbers": nums, "phrases": phrases}


def _num_set(text: str) -> set[float]:
    s = set()
    cleaned = _strip_noise(text or "")
    for m in re.finditer(r"\d[\d,]*\.?\d*", cleaned):
        raw = m.group(0)
        end = m.end()
        is_pct = end < len(cleaned) and cleaned[end:end+1] == "%"
        # keep rules
        has_decimal = "." in raw
        digit_count = len(raw.replace(",", "").replace(".", ""))
        if not (has_decimal or digit_count >= 3 or is_pct):
            continue
        try:
            s.add(float(raw.replace(",", "")))
        except ValueError:
            pass
    return s


def score_pack(pack_text: str, truth: str) -> tuple[str, list[str], list[str]]:
    tt = truth_tokens(truth)
    truth_nums = tt["numbers"]
    pack_nums = _num_set(pack_text)
    truth_floats = set()
    for n in truth_nums:
        try:
            truth_floats.add(float(n))
        except ValueError:
            pass
    found_floats = truth_floats & pack_nums
    missing_floats = truth_floats - pack_nums
    found_strs = [n for n in truth_nums if _safe_float(n) in found_floats]
    missing_strs = [n for n in truth_nums if _safe_float(n) in missing_floats]
    if truth_floats:
        if not missing_strs:
            return "hit", found_strs, missing_strs
        if found_strs:
            return "partial", found_strs, missing_strs
        return "miss", found_strs, missing_strs
    # no numbers -> phrase match
    low = (pack_text or "").lower()
    if any(p.lower() in low for p in tt["phrases"]):
        return "hit", [], []
    return "miss", [], []


def phrase_hits(pack_text: str, truth: str) -> int:
    tt = truth_tokens(truth)
    low = (pack_text or "").lower()
    return sum(1 for p in tt["phrases"] if p.lower() in low)


def _safe_float(x):
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def _longest_truth(rows: list[dict], qid: str, col: str) -> str:
    cands = [r.get(col, "") or "" for r in rows if r.get("qid") == qid]
    if not cands:
        return ""
    return max(cands, key=len)


def run_set(questions_path: str, truths: dict, store: str, out_dir: str, symbol_default: str = ""):
    os.makedirs(str(out_dir), exist_ok=True)
    qs = json.loads(Path(questions_path).read_text(encoding="utf-8"))
    rows_out = []
    for q in qs:
        qid = q["qid"]
        question = q["question"]
        as_of = q["as_of"]
        symbol = q.get("symbol") or symbol_default
        truth = truths.get(qid, "")
        t0 = time.time()
        p = ep.plan(question, as_of, symbol=symbol)
        pack = ep.gather(store, symbol, p, as_of)
        elapsed = time.time() - t0
        pack_path = Path(out_dir) / f"pack_{qid}.json"
        pack_path.write_text(json.dumps(pack, ensure_ascii=False, default=str), encoding="utf-8")
        status, found, missing = score_pack(pack.get("text", ""), truth)
        ph = phrase_hits(pack.get("text", ""), truth)
        rows_out.append({
            "qid": qid,
            "kind": p.get("kind"),
            "hit": status,
            "found": ";".join(found),
            "missing": ";".join(missing),
            "phrase_hits": ph,
            "pack_chars": pack.get("chars", 0),
            "items": pack.get("items_count", len(pack.get("items", []))),
            "seconds": round(elapsed, 3),
            "routes_nonempty": ";".join(pack.get("routes_nonempty", [])),
        })
    csv_path = Path(out_dir) / "pack_recall.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["qid", "kind", "hit", "found", "missing", "phrase_hits", "pack_chars", "items", "seconds", "routes_nonempty"])
        w.writeheader()
        w.writerows(rows_out)
    return rows_out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["bluestar", "aurobindo"], required=True)
    ap.add_argument("--workspace", default=".")
    args = ap.parse_args()
    ws = Path(args.workspace)
    if args.set == "bluestar":
        questions_path = "D:/RealityEngine/bluestar/answers/questions_in.json"
        store = "D:/RealityEngine/bluestar/bluestar.db"
        out_dir = str(ws / ".tmp" / "pack" / "bluestar")
        import csv as _csv
        rows = []
        for fn in ("grades_1.csv", "grades_2.csv", "grades_3.csv"):
            with open(f"D:/RealityEngine/bluestar/report/{fn}", newline="", encoding="utf-8") as f:
                rows.extend(list(_csv.DictReader(f)))
        truths = {}
        by_qid = {}
        for r in rows:
            by_qid.setdefault(r["qid"], []).append(r)
        for qid, rs in by_qid.items():
            truths[qid] = max((r.get("truth", "") or "" for r in rs), key=len)
        run_set(questions_path, truths, store, out_dir, symbol_default="BLUESTARCO")
        try:
            mirror = Path("D:/RealityEngine/bluestar/pack")
            mirror.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copyfile(Path(out_dir) / "pack_recall.csv", mirror / "pack_recall.csv")
        except Exception:
            pass
    else:
        questions_path = "D:/RealityEngine/aurobindo/answers/questions_in.json"
        store = "D:/RealityEngine/aurobindo/aurobindo.db"
        out_dir = str(ws / ".tmp" / "pack" / "aurobindo")
        import csv as _csv
        rows = list(_csv.DictReader(open("D:/RealityEngine/aurobindo/report/key_round1.csv", newline="", encoding="utf-8")))
        truths = {r["qid"]: (r.get("reference", "") or "") for r in rows}
        run_set(questions_path, truths, store, out_dir, symbol_default="AUROPHARMA")
        try:
            mirror = Path("D:/RealityEngine/aurobindo/pack")
            mirror.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copyfile(Path(out_dir) / "pack_recall.csv", mirror / "pack_recall.csv")
        except Exception:
            pass


if __name__ == "__main__":
    main()
