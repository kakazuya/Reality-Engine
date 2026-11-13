"""Measure how often an evidence pack CONTAINS the grader truth.

``--planner script`` (default) is the round-3 word-matching planner.  ``--planner model`` builds the per-company menu
(``reality_engine.answer.menu``), has a free model write the lookup plan (``reality_engine.answer.plan_model``), runs
every validated lookup, and writes three files per question: ``pack_<qid>.json`` (the pack, its coverage and the
plan), ``pack_<qid>.txt`` (the reading copy, each item once) and ``plan_<qid>.json`` (validated plan + raw replies).
A plan that is not valid JSON after its repair call falls back to the script planner and the pack says so.
"""
from __future__ import annotations

import argparse
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
from reality_engine.answer import menu, plan_model

os.environ.setdefault("REALITY_DATA_ALLOW_PAID_EMBED", "1")


def normalize_number(tok: str) -> str:
    t = (tok or "").strip()
    t = t.replace(",", "")
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return t


_PERIOD_RE = re.compile(r"(?:Q[1-4]|H[12]|9M)\s*FY\s*\d{2,4}|FY\s*\d{2,4}", re.I)
_PAGE_RE = re.compile(r"\b(?:p\.?\s*\d+|page\s+\d+)\b", re.I)
# a document key fragment, not a share count: only tokens with a letter or a hyphen are noise (T-205 round 6)
_UUID_RE = re.compile(r"\b(?=[0-9a-f-]{8,}\b)(?=[0-9a-f-]*[a-f-])[0-9a-f-]+\b", re.I)
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


def _decimals(tok: str) -> int:
    raw = str(tok or "").replace(",", "")
    return len(raw.split(".")[1]) if "." in raw else 0


def score_pack_rounded(pack_text: str, truth: str) -> tuple[str, list[str], list[str]]:
    """Like ``score_pack`` but a truth number matches a pack number that rounds to it at the truth's own printed
    decimals (545.9 matches 545.93); long integers (a share count) are kept by the noise filter."""
    tt = truth_tokens(truth)
    truth_nums = tt["numbers"]
    pack_nums = _num_set(pack_text)
    found, missing = [], []
    for tok in truth_nums:
        target = _safe_float(tok)
        if target is None:
            continue
        d = _decimals(tok)
        if any(abs(round(p, d) - round(target, d)) < 1e-9 for p in pack_nums):
            found.append(tok)
        else:
            missing.append(tok)
    if truth_nums:
        if not missing:
            return "hit", found, missing
        return ("partial" if found else "miss"), found, missing
    low = (pack_text or "").lower()
    if any(p.lower() in low for p in tt["phrases"]):
        return "hit", [], []
    return "miss", [], []


def _safe_float(x):
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def _plan_periods(plan_info: dict) -> list[str]:
    periods = set()
    for lookup in plan_info.get("lookups") or []:
        args = lookup.get("args") or {}
        for key in ("period", "quarter_end"):
            value = args.get(key)
            if value and isinstance(value, str):
                periods.add(value)
    return sorted(periods)


def _coverage_counts(pack: dict) -> dict:
    statuses = [str(p.get("status") or "") for p in pack.get("coverage") or []]
    total = len(statuses)
    found = statuses.count("found")
    none = statuses.count("none")
    some = total - found - none
    if not total:
        q_status = "n/a"
    elif found == total:
        q_status = "all"
    elif found == 0:
        q_status = "none"
    else:
        q_status = "some"
    return {"parts": total, "parts_found": found, "parts_some": some, "parts_none": none, "q_status": q_status}


def run_set(questions_path: str, truths: dict, store: str, out_dir: str, symbol_default: str = "",
            planner: str = "script", plan_model_name: str = plan_model.MODEL,
            cache_dir: str | None = None, limit: int = 0):
    os.makedirs(str(out_dir), exist_ok=True)
    qs = json.loads(Path(questions_path).read_text(encoding="utf-8"))
    if limit:
        qs = qs[:limit]
    rows_out = []
    plan_summary = []
    for q in qs:
        qid = q["qid"]
        question = q["question"]
        as_of = q["as_of"]
        symbol = q.get("symbol") or symbol_default
        truth = truths.get(qid, "")
        t0 = time.time()
        plan_info = None
        if planner == "model":
            menu_dict = menu.build(store, symbol, as_of)
            menu_text = menu.render(menu_dict)
            plan_info = plan_model.write_plan(question, as_of, menu_text, plan_model_name,
                                              menu=menu_dict, cache_dir=cache_dir)
            if plan_info.get("planner") == "model":
                # union: the round-3 script plan still runs under the model's lookups (T-205 round 5)
                plan = ep.plan(question, as_of, symbol=symbol)
                plan["question"] = question
                pack = ep.gather(store, symbol, plan, as_of, max_chars=180000,
                                 lookups=plan_info.get("lookups") or [], parts=plan_info.get("parts") or [])
            else:
                plan = ep.plan(question, as_of, symbol=symbol)
                pack = ep.gather(store, symbol, plan, as_of)
                pack["planner"] = "script_fallback"
            pack["plan_model"] = plan_info
            for rejected in plan_info.get("rejected") or []:
                pack["route_errors"].append({"route": rejected.get("route"), "args": rejected.get("args"),
                                             "rejected": rejected.get("reason")})
            (Path(out_dir) / f"plan_{qid}.json").write_text(
                json.dumps(plan_info, ensure_ascii=False, default=str), encoding="utf-8")
        else:
            plan = ep.plan(question, as_of, symbol=symbol)
            pack = ep.gather(store, symbol, plan, as_of)
            pack["planner"] = "script"
        elapsed = time.time() - t0
        # the reading copy is what the answer model sees: build it once, write those exact bytes, score those bytes
        reading = ep.reading_text(pack, max_chars=150000)
        (Path(out_dir) / f"pack_{qid}.txt").write_text(reading, encoding="utf-8")
        pack["reading_chars"] = len(reading)
        pack_path = Path(out_dir) / f"pack_{qid}.json"
        pack_path.write_text(json.dumps(pack, ensure_ascii=False, default=str), encoding="utf-8")
        status, found, missing = score_pack(reading, truth)
        status_json, _, _ = score_pack(pack.get("text", ""), truth)
        status_rounded, _, rounded_missing = score_pack_rounded(reading, truth)
        ph = phrase_hits(reading, truth)
        cov = _coverage_counts(pack)
        rejected = len(plan_info.get("rejected") or []) if plan_info else 0
        row = {
            "qid": qid,
            "kind": plan.get("kind"),
            "hit": status,
            "hit_json": status_json,
            "hit_rounded": status_rounded,
            "found": ";".join(found),
            "missing": ";".join(missing),
            "missing_rounded": ";".join(rounded_missing),
            "phrase_hits": ph,
            "pack_chars": pack.get("chars", 0),
            "items": pack.get("items_count", len(pack.get("items", []))),
            "seconds": round(elapsed, 3),
            "routes_nonempty": ";".join(pack.get("routes_nonempty", [])),
            "planner": pack.get("planner"),
            "parts": cov["parts"],
            "parts_found": cov["parts_found"],
            "parts_some": cov["parts_some"],
            "parts_none": cov["parts_none"],
            "q_status": cov["q_status"],
            "rejected": rejected,
            "model_calls": (plan_info or {}).get("model_calls", 0),
            "plan_seconds": (plan_info or {}).get("seconds", 0),
            "reading_chars": len(reading),
            "reading_cut": pack.get("reading_cut_count", 0),
            "plan_items": pack.get("plan_items", 0),
            "script_items": pack.get("script_items", 0),
        }
        rows_out.append(row)
        if plan_info is not None:
            plan_summary.append({"qid": qid, "planner": plan_info.get("planner"),
                                 "parts": plan_info.get("parts") or [],
                                 "lookups": plan_info.get("lookups") or [],
                                 "rejected": plan_info.get("rejected") or [],
                                 "model_calls": plan_info.get("model_calls"),
                                 "plan_seconds": plan_info.get("seconds"),
                                 "cached": plan_info.get("cached")})
    csv_path = Path(out_dir) / "pack_recall.csv"
    fieldnames = ["qid", "kind", "hit", "hit_json", "hit_rounded", "found", "missing", "missing_rounded",
                  "phrase_hits", "pack_chars", "items", "seconds", "routes_nonempty", "planner", "parts",
                  "parts_found", "parts_some", "parts_none", "q_status", "rejected", "model_calls",
                  "plan_seconds", "reading_chars", "reading_cut", "plan_items", "script_items"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)
    summary = summarize(rows_out, plan_summary)
    (Path(out_dir) / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows_out, summary


def summarize(rows: list[dict], plan_summary: list[dict]) -> dict:
    """The round-4 numbers: part coverage, rejected lookups, model calls, reading-copy size."""
    parts = [r["parts"] for r in rows if r.get("parts")]
    reading = [r["reading_chars"] for r in rows]
    planned = [r for r in rows if r.get("planner") in ("model", "script_fallback")]
    plan_secs = [r["plan_seconds"] for r in planned]
    calls = [r["model_calls"] for r in planned]
    rejected = [r["rejected"] for r in planned]
    out = {
        "questions": len(rows),
        # the reading copy is the scored text; hit_json is the JSON pack, hit_rounded the rounded-number reading score
        "hit": sum(1 for r in rows if r["hit"] == "hit"),
        "partial": sum(1 for r in rows if r["hit"] == "partial"),
        "miss": sum(1 for r in rows if r["hit"] == "miss"),
        "hit_json": sum(1 for r in rows if r.get("hit_json") == "hit"),
        "partial_json": sum(1 for r in rows if r.get("hit_json") == "partial"),
        "miss_json": sum(1 for r in rows if r.get("hit_json") == "miss"),
        "hit_rounded": sum(1 for r in rows if r.get("hit_rounded") == "hit"),
        "partial_rounded": sum(1 for r in rows if r.get("hit_rounded") == "partial"),
        "miss_rounded": sum(1 for r in rows if r.get("hit_rounded") == "miss"),
        "planner": {p: sum(1 for r in rows if r["planner"] == p) for p in sorted({r["planner"] for r in rows})},
        "questions_all_parts_found": sum(1 for r in rows if r.get("q_status") == "all"),
        "questions_some_parts_found": sum(1 for r in rows if r.get("q_status") == "some"),
        "questions_no_part_found": sum(1 for r in rows if r.get("q_status") == "none"),
        "reading_chars": {"median": round(median(reading), 1) if reading else 0, "max": max(reading or [0])},
        "reading_cut": {"median": median([r.get("reading_cut", 0) for r in rows]) if rows else 0,
                        "max": max([r.get("reading_cut", 0) for r in rows] or [0])},
        "plan_items": {"median": median([r.get("plan_items", 0) for r in rows]) if rows else 0},
        "script_items": {"median": median([r.get("script_items", 0) for r in rows]) if rows else 0},
        "pack_chars": {"median": round(median([r["pack_chars"] for r in rows]), 1) if rows else 0,
                       "max": max([r["pack_chars"] for r in rows] or [0])},
    }
    if planned:
        out["plan_seconds"] = {"median": round(median(plan_secs), 2), "max": round(max(plan_secs), 2),
                               "sum": round(sum(plan_secs), 1)}
        out["model_calls"] = {"median": median(calls), "max": max(calls), "sum": sum(calls)}
        out["rejected_lookups"] = {"median": median(rejected), "max": max(rejected), "sum": sum(rejected)}
        out["parts_per_question"] = {"median": median(parts), "max": max(parts)} if parts else {}
        out["plans"] = plan_summary
    return out


def _truths_for(args) -> tuple[str, dict, str]:
    if args.set == "bluestar":
        questions_path = "D:/RealityEngine/bluestar/answers/questions_in.json"
        store = "D:/RealityEngine/bluestar/bluestar.db"
        rows = []
        for fn in ("grades_1.csv", "grades_2.csv", "grades_3.csv"):
            with open(f"D:/RealityEngine/bluestar/report/{fn}", newline="", encoding="utf-8") as f:
                rows.extend(list(csv.DictReader(f)))
        by_qid = {}
        for r in rows:
            by_qid.setdefault(r["qid"], []).append(r)
        truths = {qid: max((r.get("truth", "") or "" for r in rs), key=len) for qid, rs in by_qid.items()}
        return questions_path, truths, store
    questions_path = "D:/RealityEngine/aurobindo/answers/questions_in.json"
    store = "D:/RealityEngine/aurobindo/aurobindo.db"
    with open("D:/RealityEngine/aurobindo/report/key_round1.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    truths = {r["qid"]: (r.get("reference", "") or "") for r in rows}
    return questions_path, truths, store


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["bluestar", "aurobindo"], required=True)
    ap.add_argument("--workspace", default=".")
    ap.add_argument("--planner", choices=["script", "model"], default="script")
    ap.add_argument("--plan-model", default=plan_model.MODEL)
    ap.add_argument("--out", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    questions_path, truths, store = _truths_for(args)
    symbol = "BLUESTARCO" if args.set == "bluestar" else "AUROPHARMA"
    out_dir = Path(args.out) if args.out else ws / ".tmp" / ("pack_model" if args.planner == "model" else "pack") / args.set
    cache_dir = ws / ".tmp" / "plan_cache" if args.planner == "model" else None
    try:
        rows, summary = run_set(questions_path, truths, store, str(out_dir), symbol_default=symbol,
                                planner=args.planner, plan_model_name=args.plan_model,
                                cache_dir=str(cache_dir) if cache_dir else None, limit=args.limit)
    except plan_model.BillingError as exc:
        print(json.dumps({"error": "billing", "detail": str(exc)[:300]}), file=sys.stderr)
        return 3
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
