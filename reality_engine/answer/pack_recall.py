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
    # strip trailing zeros after decimal
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return t


def _extract_numbers(text: str) -> list[str]:
    out = []
    for m in re.finditer(r"\d[\d,]*\.?\d*", text or ""):
        v = normalize_number(m.group(0))
        if v:
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


def truth_tokens(truth: str) -> dict:
    nums = _extract_numbers(truth or "")
    phrases = _extract_quoted(truth or "", 3)
    return {"numbers": nums, "phrases": phrases}


def _num_set(text: str) -> set[float]:
    s = set()
    for m in re.finditer(r"\d[\d,]*\.?\d*", text or ""):
        try:
            s.add(float(m.group(0).replace(",", "")))
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
    # map back to strings
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
        p = ep.plan(question, as_of)
        pack = ep.gather(store, symbol, p, as_of)
        elapsed = time.time() - t0
        # write pack file
        pack_path = Path(out_dir) / f"pack_{qid}.json"
        pack_path.write_text(json.dumps(pack, ensure_ascii=False, default=str), encoding="utf-8")
        status, found, missing = score_pack(pack.get("text", ""), truth)
        rows_out.append({
            "qid": qid,
            "kind": p.get("kind"),
            "hit": status,
            "found": ";".join(found),
            "missing": ";".join(missing),
            "pack_chars": pack.get("chars", 0),
            "items": pack.get("items_count", len(pack.get("items", []))),
            "seconds": round(elapsed, 3),
            "routes_nonempty": ";".join(pack.get("routes_nonempty", [])),
        })
    # write CSV
    csv_path = Path(out_dir).parent / "pack_recall.csv" if False else Path(out_dir) / "pack_recall.csv"
    # The brief wants out .tmp/pack/bluestar/pack_recall.csv? Actually "Output CSV" unspecified location; put in out_dir
    csv_path = Path(out_dir) / "pack_recall.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["qid", "kind", "hit", "found", "missing", "pack_chars", "items", "seconds", "routes_nonempty"])
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
        # truths
        import csv as _csv
        rows = []
        for fn in ("grades_1.csv", "grades_2.csv", "grades_3.csv"):
            with open(f"D:/RealityEngine/bluestar/report/{fn}", newline="", encoding="utf-8") as f:
                rows.extend(list(_csv.DictReader(f)))
        truths = {}
        # group by qid, take longest truth
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
