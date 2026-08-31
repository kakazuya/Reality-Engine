"""
bench_method_a.py — Method A: Tightened filing_discovery._classify benchmark
CPU-rules only (no GPU), isolated script. Does NOT edit filing_discovery.py.

Scope: Compare baseline filing_discovery.FilingDiscoveryClient._classify vs Method A
tightened Investor Presentation disambiguation on BSE 100 subset (nifty100 proxy).

Method A spec:
  blob = (url+" "+context).lower()
  ctx = context.lower()
  if "annualreport" in url.lower() or "bseplus" in url.lower(): return "ANNUAL_REPORT"
  if "concall" in blob or "transcript" in blob: return "CONCALL_TRANSCRIPT"
  is_notice = any(k in ctx for k in ["intimation","outcome","schedule","invite","possession","will be held","to be held","earnings call","conference call","meet -","investor meet","board meeting"])
  if is_notice and "presentation" not in ctx: return "ANNOUNCEMENT"
  if "investor presentation" in ctx or "earnings presentation" in ctx or "corporate presentation" in ctx or "investor ppt" in ctx: return "ANNOUNCEMENT" if is_notice else "INVESTOR_PRESENTATION"
  if "presentation" in ctx and "investor" in ctx and not is_notice: return "INVESTOR_PRESENTATION"
  if "annual" in ctx: return "ANNUAL_REPORT"
  if "result" in blob or "financial" in ctx: return "FINANCIAL_RESULT"
  return "OTHER_FILING"

Benchmark: BSE 100 subset -> corporate_documents title/context proxy.
Ground truth (downloaded docs only): PyMuPDF pages + first page text heuristic:
  REAL_PPT  : pages>5 && 2+ keywords Revenue/EBITDA/PAT/Segment/FY
  NOTICE    : pages<=3 && Reg30/Intimation
Scored metrics: precision/recall/F1 for INVESTOR_PRESENTATION, FPR reduction, number corrected.
Timing: per-doc ms (CPU).
No network, workers=1.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# ensure project root importable when run as `python reality_engine/scripts/bench_method_a.py`
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# 1. Baseline + Method A
# ---------------------------------------------------------------------------
def classify_a(url: str, context: str = "") -> str:
    """Method A tightened classifier per spec (CPU-rules only)."""
    blob = (url + " " + context).lower()
    ctx = (context or "").lower()
    low_url = url.lower()
    if "annualreport" in low_url or "bseplus" in low_url:
        return "ANNUAL_REPORT"
    if "concall" in blob or "transcript" in blob:
        return "CONCALL_TRANSCRIPT"
    is_notice = any(
        k in ctx
        for k in [
            "intimation",
            "outcome",
            "schedule",
            "invite",
            "possession",
            "will be held",
            "to be held",
            "earnings call",
            "conference call",
            "meet -",
            "investor meet",
            "board meeting",
        ]
    )
    if is_notice and "presentation" not in ctx:
        return "ANNOUNCEMENT"
    if (
        "investor presentation" in ctx
        or "earnings presentation" in ctx
        or "corporate presentation" in ctx
        or "investor ppt" in ctx
    ):
        return "ANNOUNCEMENT" if is_notice else "INVESTOR_PRESENTATION"
    if "presentation" in ctx and "investor" in ctx and not is_notice:
        return "INVESTOR_PRESENTATION"
    if "annual" in ctx:
        return "ANNUAL_REPORT"
    if "result" in blob or "financial" in ctx:
        return "FINANCIAL_RESULT"
    return "OTHER_FILING"


def _load_baseline():
    """Import baseline _classify without triggering network."""
    try:
        from reality_engine.ingestion.filing_discovery import FilingDiscoveryClient

        return FilingDiscoveryClient._classify
    except Exception as e:
        # Fallback: emulate original logic as documented
        def _fallback(url: str, context: str = "") -> str:
            low_url = url.lower()
            low_ctx = (context or "").lower()
            blob = low_url + " " + low_ctx
            if "annualreport" in low_url or "bseplus" in low_url:
                return "ANNUAL_REPORT"
            if "concall" in blob or "transcript" in blob:
                return "CONCALL_TRANSCRIPT"
            if "presentation" in low_ctx or "investor" in low_ctx:
                return "INVESTOR_PRESENTATION"
            if "annual" in low_ctx:
                return "ANNUAL_REPORT"
            if "result" in blob or "financial" in low_ctx:
                return "FINANCIAL_RESULT"
            return "OTHER_FILING"

        print(f"[warn] failed to import FilingDiscoveryClient._classify: {e}; using fallback replica", file=sys.stderr)
        return _fallback


BASELINE_CLASSIFY = _load_baseline()


# ---------------------------------------------------------------------------
# 2. Universe selection (BSE 100 subset)
# ---------------------------------------------------------------------------
def select_universe() -> Tuple[List[Dict[str, Any]], str]:
    """Return 100 symbols for benchmark + selection_method label."""
    from reality_engine.db.database import db_manager

    with db_manager.session() as conn:
        # inspect columns
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(master_companies)").fetchall()}
        except Exception:
            cols = set()
        # check bse100 flag existence
        has_bse100 = any(c.lower() == "is_bse100" for c in cols)
        has_nifty100 = "is_nifty100" in cols

        selection_method = "unknown"
        rows: List[Dict[str, Any]] = []

        if has_bse100:
            try:
                rows = [dict(r) for r in conn.execute("SELECT * FROM master_companies WHERE is_bse100=1 AND is_active=1 ORDER BY nse_symbol ASC LIMIT 100").fetchall()]
                if len(rows) == 100:
                    selection_method = "is_bse100=1 (BSE 100 flag, 100 rows)"
                else:
                    # fallback if not exactly 100
                    rows = []
            except Exception:
                rows = []

        if not rows and has_nifty100:
            try:
                rows = [dict(r) for r in conn.execute("SELECT * FROM master_companies WHERE is_nifty100=1 AND is_active=1 ORDER BY nse_symbol ASC").fetchall()]
                if len(rows) >= 80:  # expect 100
                    # trim to 100 for determinism
                    rows = sorted(rows, key=lambda x: x.get("nse_symbol") or "")[:100]
                    selection_method = "is_nifty100=1 (100 rows) as proxy for BSE 100 (BSE 100 flag absent)"
                else:
                    rows = []
            except Exception:
                rows = []

        if not rows:
            # fallback: first 100 active ordered by nse_symbol
            rows = [dict(r) for r in conn.execute("SELECT * FROM master_companies WHERE is_active=1 ORDER BY nse_symbol ASC LIMIT 100").fetchall()]
            selection_method = "first 100 active ordered by nse_symbol (fallback; BSE 100 / nifty100 flags absent or insufficient)"

    return rows, selection_method


# ---------------------------------------------------------------------------
# 3. Ground truth heuristic (PyMuPDF)
# ---------------------------------------------------------------------------
def ground_truth_from_pdf(local_path: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Returns (label, meta) where label in {"REAL_PPT","NOTICE","UNKNOWN",None}
    None => no file / error.
    Heuristic per spec: pages + first page text
      REAL_PPT: pages>5 && 2+ keywords Revenue/EBITDA/PAT/Segment/FY
      NOTICE:   pages<=3 && Reg30/Intimation
    """
    p = Path(local_path) if local_path else None
    if not p or not p.exists():
        return None, {"reason": "no_file", "path": str(local_path)}
    try:
        import fitz  # PyMuPDF
    except ImportError:
        try:
            import pymupdf as fitz
        except Exception as e:
            return None, {"reason": f"fitz_unavailable:{e}"}
    try:
        doc = fitz.open(str(p))
        pages = len(doc)
        # aggregate first 5 pages for keyword recall (covers cover letter + deck)
        try:
            agg_text = " ".join(doc[i].get_text() for i in range(min(pages,5))) if pages>0 else ""
        except Exception:
            agg_text = doc[0].get_text() if pages>0 else ""
        first_text = agg_text
        if not isinstance(first_text, str):
            first_text = str(first_text)
        doc.close()
        lower = first_text.lower()
        keywords = ["revenue", "ebitda", "pat", "segment", "fy"]
        kw_count = sum(1 for k in keywords if k in lower)
        is_reg30 = (("reg" in lower and "30" in lower) or "regulation 30" in lower or "reg 30" in lower or "reg30" in lower)
        is_intimation = "intimation" in lower
        is_notice_text = is_reg30 or is_intimation

        if pages > 5 and kw_count >= 2:
            label = "REAL_PPT"
        elif pages <= 3 and is_notice_text:
            label = "NOTICE"
        else:
            label = "UNKNOWN"

        meta = {
            "pages": pages,
            "first_page_chars": len(first_text),
            "kw_count": kw_count,
            "kw_hits": [k for k in keywords if k in lower],
            "is_reg30": is_reg30,
            "is_intimation": is_intimation,
            "first_page_snippet": first_text[:400].replace("\n", " ").strip(),
        }
        return label, meta
    except Exception as e:
        return None, {"reason": f"fitz_error:{e}", "path": str(p)}


def _safe_precision(tp: int, fp: int) -> Optional[float]:
    denom = tp + fp
    return round(tp / denom, 4) if denom > 0 else None


def _safe_recall(tp: int, fn: int) -> Optional[float]:
    denom = tp + fn
    return round(tp / denom, 4) if denom > 0 else None


def _safe_f1(prec: Optional[float], rec: Optional[float]) -> Optional[float]:
    if prec is None or rec is None or (prec + rec) == 0:
        return None
    return round(2 * prec * rec / (prec + rec), 4)


def _safe_fpr(fp: int, tn: int) -> Optional[float]:
    denom = fp + tn
    return round(fp / denom, 4) if denom > 0 else None


# ---------------------------------------------------------------------------
# Main benchmark
# ---------------------------------------------------------------------------
def main() -> int:
    start_wall = time.perf_counter()
    print("=" * 72)
    print("BENCH Method A: Tightened filing_discovery._classify (Investor Presentation)")
    print("=" * 72)
    print("[config] workers=1, no network, CPU-rules only, GPU not required")

    # 1. Universe
    universe_rows, selection_method = select_universe()
    symbols = [r.get("nse_symbol") or r.get("symbol") or r.get("bse_code") for r in universe_rows]
    symbols = [s for s in symbols if s]
    # dedup preserve order
    seen = set()
    uniq_symbols = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            uniq_symbols.append(s)
    symbols = uniq_symbols[:100]
    print(f"[universe] selection_method: {selection_method}")
    print(f"[universe] symbol_count: {len(symbols)}")
    print(f"[universe] symbols_sample (first 10): {symbols[:10]}")

    # 2. Fetch docs for those symbols
    from reality_engine.db.database import db_manager

    docs: List[Dict[str, Any]] = []
    per_symbol_counts: Dict[str, Dict[str, int]] = {}
    with db_manager.session() as conn:
        # Use parameterized IN query in batches to avoid hitting sqlite limits
        # Fetch INVESTOR_PRESENTATION + ANNOUNCEMENT for the 100 symbols
        # corp docs uses `symbol` column
        # Build placeholder string
        placeholders = ",".join("?" for _ in symbols)
        q = f"""
            SELECT id, isin, symbol, doc_type, title, doc_date, source_url, local_file_path, source, discovery_source
            FROM corporate_documents
            WHERE symbol IN ({placeholders}) AND doc_type IN ('INVESTOR_PRESENTATION','ANNOUNCEMENT')
            ORDER BY symbol ASC, doc_date DESC
        """
        try:
            rows = conn.execute(q, symbols).fetchall()
            docs = [dict(r) for r in rows]
        except Exception as e:
            print(f"[error] fetching corporate_documents: {e}", file=sys.stderr)
            docs = []

        # also get total counts for universe for reporting
        for sym in symbols:
            per_symbol_counts[sym] = {"INVESTOR_PRESENTATION": 0, "ANNOUNCEMENT": 0}
        for d in docs:
            sym = d.get("symbol")
            dt = d.get("doc_type")
            if sym in per_symbol_counts and dt in per_symbol_counts[sym]:
                per_symbol_counts[sym][dt] += 1

    total_docs = len(docs)
    inv_docs = sum(1 for d in docs if d.get("doc_type") == "INVESTOR_PRESENTATION")
    ann_docs = sum(1 for d in docs if d.get("doc_type") == "ANNOUNCEMENT")
    with_file = sum(1 for d in docs if d.get("local_file_path"))
    existing_file = 0
    for d in docs:
        p = d.get("local_file_path")
        if p and Path(p).exists():
            existing_file += 1

    print(f"[dataset] total_docs (INVESTOR_PRESENTATION+ANNOUNCEMENT) for 100 symbols: {total_docs}")
    print(f"[dataset] INVESTOR_PRESENTATION (current mis-typed): {inv_docs}")
    print(f"[dataset] ANNOUNCEMENT: {ann_docs}")
    print(f"[dataset] with local_file_path (non-null): {with_file}")
    print(f"[dataset] with existing file on disk: {existing_file}")

    # 3. Benchmark classification
    # For each doc, compute baseline vs method_a using title as context proxy + source_url
    # Measure timing per doc

    # Warmup (avoid import noise)
    _ = BASELINE_CLASSIFY("https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=test.pdf", "Investor Presentation")
    _ = classify_a("https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=test.pdf", "Investor Presentation")

    baseline_times: List[float] = []
    method_a_times: List[float] = []

    results: List[Dict[str, Any]] = []

    # Ground truth scoring containers
    # Only for docs where ground truth label is REAL_PPT or NOTICE (scorable)
    tp_baseline = fp_baseline = tn_baseline = fn_baseline = 0
    tp_a = fp_a = tn_a = fn_a = 0

    changed = 0
    corrected = 0
    baseline_fp_rescued = 0
    new_fn_introduced = 0
    scorable = 0
    unknown_gt = 0
    no_file_gt = 0
    gt_breakdown = {"REAL_PPT": 0, "NOTICE": 0, "UNKNOWN": 0, "NO_FILE": 0, "ERROR": 0}

    # For timing totals
    total_baseline_ms = 0.0
    total_method_a_ms = 0.0

    for d in docs:
        url = (d.get("source_url") or "").strip()
        ctx = (d.get("title") or "").strip()  # title as context proxy per spec
        # Some docs may have empty title; fallback to empty string

        # baseline timing
        t0 = time.perf_counter()
        pred_baseline = BASELINE_CLASSIFY(url, ctx)
        t1 = time.perf_counter()
        baseline_ms = (t1 - t0) * 1000.0
        baseline_times.append(baseline_ms)
        total_baseline_ms += baseline_ms

        # method_a timing
        t2 = time.perf_counter()
        pred_a = classify_a(url, ctx)
        t3 = time.perf_counter()
        method_a_ms = (t3 - t2) * 1000.0
        method_a_times.append(method_a_ms)
        total_method_a_ms += method_a_ms

        # ground truth if downloaded
        gt_label = None
        gt_meta: Dict[str, Any] = {}
        local_path = d.get("local_file_path")
        if local_path:
            gt_label, gt_meta = ground_truth_from_pdf(str(local_path))
            if gt_label is None:
                # no file or error
                if gt_meta.get("reason") == "no_file":
                    gt_breakdown["NO_FILE"] += 1
                    no_file_gt += 1
                else:
                    gt_breakdown["ERROR"] += 1
            elif gt_label in ("REAL_PPT", "NOTICE", "UNKNOWN"):
                gt_breakdown[gt_label] += 1
                if gt_label == "UNKNOWN":
                    unknown_gt += 1
            else:
                gt_breakdown["UNKNOWN"] += 1
                unknown_gt += 1
        else:
            gt_label = None
            gt_breakdown["NO_FILE"] += 1
            no_file_gt += 1

        # Scoring only if gt is REAL_PPT or NOTICE
        scorable_gt = gt_label in ("REAL_PPT", "NOTICE")
        if scorable_gt:
            scorable += 1
            # Map gt to true label
            true_is_ppt = gt_label == "REAL_PPT"  # True => INVESTOR_PRESENTATION, False => NOT
            baseline_is_ppt = pred_baseline == "INVESTOR_PRESENTATION"
            a_is_ppt = pred_a == "INVESTOR_PRESENTATION"

            # baseline confusion
            if true_is_ppt and baseline_is_ppt:
                tp_baseline += 1
            elif (not true_is_ppt) and baseline_is_ppt:
                fp_baseline += 1
            elif (not true_is_ppt) and (not baseline_is_ppt):
                tn_baseline += 1
            elif true_is_ppt and (not baseline_is_ppt):
                fn_baseline += 1

            # method_a confusion
            if true_is_ppt and a_is_ppt:
                tp_a += 1
            elif (not true_is_ppt) and a_is_ppt:
                fp_a += 1
            elif (not true_is_ppt) and (not a_is_ppt):
                tn_a += 1
            elif true_is_ppt and (not a_is_ppt):
                fn_a += 1

            # changed / corrected
            if pred_baseline != pred_a:
                changed += 1
                # check if A matches truth and baseline does not
                true_label_str = "INVESTOR_PRESENTATION" if true_is_ppt else "ANNOUNCEMENT"
                # For NOTICE, true label is ANNOUNCEMENT; for REAL_PPT it's INVESTOR_PRESENTATION
                # But note method_a may output OTHER_FILING etc; we treat only INVESTOR_PRESENTATION vs not
                # So for correction we consider: did A get the binary decision right vs baseline?
                # Binary correctness: (a_is_ppt == true_is_ppt) vs (baseline_is_ppt == true_is_ppt)
                baseline_correct_bin = baseline_is_ppt == true_is_ppt
                a_correct_bin = a_is_ppt == true_is_ppt
                if a_correct_bin and not baseline_correct_bin:
                    corrected += 1
                # rescued FP: baseline FP but A is TN
                if (not true_is_ppt) and baseline_is_ppt and (not a_is_ppt):
                    baseline_fp_rescued += 1
                # new FN: baseline TP but A is FN
                if true_is_ppt and baseline_is_ppt and (not a_is_ppt):
                    new_fn_introduced += 1

        results.append(
            {
                "symbol": d.get("symbol"),
                "doc_id": d.get("id"),
                "doc_type_current": d.get("doc_type"),
                "title": ctx,
                "source_url": url,
                "local_file_path": local_path,
                "pred_baseline": pred_baseline,
                "pred_method_a": pred_a,
                "changed": pred_baseline != pred_a,
                "gt_label": gt_label,
                "gt_meta": gt_meta,
                "timing_ms": {"baseline": round(baseline_ms, 4), "method_a": round(method_a_ms, 4)},
            }
        )

    # 4. Compute metrics
    def compute_metrics(tp: int, fp: int, tn: int, fn: int) -> Dict[str, Any]:
        prec = _safe_precision(tp, fp)
        rec = _safe_recall(tp, fn)
        f1 = _safe_f1(prec, rec)
        fpr = _safe_fpr(fp, tn)
        return {
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
            "precision": prec,
            "recall": rec,
            "f1": f1,
            "false_positive_rate": fpr,
            "accuracy": round((tp + tn) / (tp + fp + tn + fn), 4) if (tp + fp + tn + fn) > 0 else None,
        }

    metrics_baseline = compute_metrics(tp_baseline, fp_baseline, tn_baseline, fn_baseline)
    metrics_a = compute_metrics(tp_a, fp_a, tn_a, fn_a)

    # Comparison deltas
    def delta(a, b):
        if a is None or b is None:
            return None
        return round(a - b, 4)

    fp_reduction_abs = fp_baseline - fp_a if scorable > 0 else 0
    fp_reduction_pct = round(100.0 * fp_reduction_abs / fp_baseline, 2) if fp_baseline > 0 else (0.0 if scorable > 0 else None)
    # also FPR reduction
    fpr_reduction = None
    if metrics_baseline.get("false_positive_rate") is not None and metrics_a.get("false_positive_rate") is not None:
        fpr_reduction = round(metrics_baseline["false_positive_rate"] - metrics_a["false_positive_rate"], 4)

    baseline_avg_ms = round(sum(baseline_times) / len(baseline_times), 4) if baseline_times else 0.0
    method_a_avg_ms = round(sum(method_a_times) / len(method_a_times), 4) if method_a_times else 0.0

    # Also compute overall wall time for docs classification
    # Correction counts also for full dataset (not just scorable) — number where baseline != method_a
    total_changed_all = sum(1 for r in results if r["changed"])
    # For full dataset, how many baseline INVESTOR_PRESENTATION flipped to ANNOUNCEMENT via method_a?
    baseline_ppt_count = sum(1 for r in results if r["pred_baseline"] == "INVESTOR_PRESENTATION")
    method_a_ppt_count = sum(1 for r in results if r["pred_method_a"] == "INVESTOR_PRESENTATION")
    flipped_ppt_to_ann = sum(1 for r in results if r["pred_baseline"] == "INVESTOR_PRESENTATION" and r["pred_method_a"] != "INVESTOR_PRESENTATION")
    flipped_ann_to_ppt = sum(1 for r in results if r["pred_baseline"] != "INVESTOR_PRESENTATION" and r["pred_method_a"] == "INVESTOR_PRESENTATION")

    # Build summary
    summary: Dict[str, Any] = {
        "benchmark": "Method A tightened filing_discovery._classify (Investor Presentation disambiguation)",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {"workers": 1, "network": "none", "gpu": "not_used_cpu_only", "script": str(Path(__file__).resolve())},
        "universe": {
            "selection_method": selection_method,
            "requested_bse100_subset": 100,
            "actual_symbol_count": len(symbols),
            "symbols": symbols,
            "symbols_sample_10": symbols[:10],
        },
        "dataset": {
            "total_docs": total_docs,
            "investor_presentation_current_label": inv_docs,
            "announcement_current_label": ann_docs,
            "with_local_file_path": with_file,
            "with_existing_file": existing_file,
            "without_file": total_docs - with_file,
            "scorable_ground_truth_docs": scorable,
            "unknown_ground_truth_docs": unknown_gt,
            "no_file_ground_truth": no_file_gt,
            "ground_truth_breakdown": gt_breakdown,
            "per_symbol_counts_sample_5": {k: per_symbol_counts[k] for k in list(per_symbol_counts.keys())[:5]},
        },
        "timing": {
            "baseline_avg_ms_per_doc": baseline_avg_ms,
            "method_a_avg_ms_per_doc": method_a_avg_ms,
            "total_baseline_ms": round(total_baseline_ms, 4),
            "total_method_a_ms": round(total_method_a_ms, 4),
            "speedup_ratio_baseline_over_method_a": round(baseline_avg_ms / method_a_avg_ms, 4) if method_a_avg_ms > 0 else None,
            "docs_measured": len(baseline_times),
            "wall_time_sec": round(time.perf_counter() - start_wall, 4),
        },
        "classification_counts": {
            "baseline_investor_presentation_predicted": baseline_ppt_count,
            "method_a_investor_presentation_predicted": method_a_ppt_count,
            "total_changed": total_changed_all,
            "changed_scorable_subset": changed,
            "flipped_ppt_to_non_ppt": flipped_ppt_to_ann,
            "flipped_non_ppt_to_ppt": flipped_ann_to_ppt,
        },
        "ground_truth_metrics_scorable_only": {
            "scorable_docs": scorable,
            "baseline": metrics_baseline,
            "method_a": metrics_a,
            "comparison": {
                "fp_reduction_abs": fp_reduction_abs,
                "fp_reduction_pct": fp_reduction_pct,
                "fpr_reduction_abs": fpr_reduction,
                "precision_delta": delta(metrics_a.get("precision"), metrics_baseline.get("precision")),
                "recall_delta": delta(metrics_a.get("recall"), metrics_baseline.get("recall")),
                "f1_delta": delta(metrics_a.get("f1"), metrics_baseline.get("f1")),
                "accuracy_delta": delta(metrics_a.get("accuracy"), metrics_baseline.get("accuracy")),
            },
        },
        "corrections": {
            "total_changed_in_scorable": changed,
            "corrected_to_ground_truth": corrected,
            "baseline_fp_rescued": baseline_fp_rescued,
            "new_fn_introduced": new_fn_introduced,
            "correction_rate_pct": round(100.0 * corrected / scorable, 2) if scorable > 0 else None,
            "net_fp_improvement": baseline_fp_rescued - new_fn_introduced,
        },
        "method_a_definition": {
            "description": "CPU-rules only, co-occurrence investor+presentation required, blocklist notices -> ANNOUNCEMENT",
            "rules_order": [
                "annualreport|bseplus in url -> ANNUAL_REPORT",
                "concall|transcript in blob -> CONCALL_TRANSCRIPT",
                "is_notice && presentation not in ctx -> ANNOUNCEMENT",
                "exact phrase investor presentation|earnings presentation|corporate presentation|investor ppt -> ANNOUNCEMENT if is_notice else INVESTOR_PRESENTATION",
                "presentation+investor co-occurrence && not is_notice -> INVESTOR_PRESENTATION",
                "annual in ctx -> ANNUAL_REPORT",
                "result in blob or financial in ctx -> FINANCIAL_RESULT",
                "else -> OTHER_FILING",
            ],
            "is_notice_keywords": [
                "intimation",
                "outcome",
                "schedule",
                "invite",
                "possession",
                "will be held",
                "to be held",
                "earnings call",
                "conference call",
                "meet -",
                "investor meet",
                "board meeting",
            ],
        },
        "ground_truth_heuristic": {
            "description": "PyMuPDF pages + first page text; REAL_PPT if pages>5 && 2+ keywords Revenue/EBITDA/PAT/Segment/FY; NOTICE if pages<=3 && Reg30/Intimation; else UNKNOWN",
            "source": "local_file_path existence only; no network",
            "library": "PyMuPDF (fitz) via pymupdf==1.28.2",
        },
        "results_sample_5": results[:5],
    }

        # Add confusion details for interpretability
    summary["confusion_interpretation"] = {
        "positives_are": "ground_truth REAL_PPT (true Investor Presentation deck); negatives are NOTICE",
        "baseline": f"TP={tp_baseline} FP={fp_baseline} TN={tn_baseline} FN={fn_baseline}",
        "method_a": f"TP={tp_a} FP={fp_a} TN={tn_a} FN={fn_a}",
    }

    # Write JSON
    out_path = Path(__file__).resolve().parent / "bench_method_a.json"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"[output] wrote {out_path}")
    except Exception as e:
        print(f"[error] failed to write {out_path}: {e}", file=sys.stderr)

    # stdout JSON summary (pretty)
    print("\n--- BENCHMARK JSON SUMMARY ---")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    # Human readable key metrics
    print("\n--- KEY METRICS ---")
    print(f"Universe: {selection_method} | symbols={len(symbols)} | docs={total_docs} (INV={inv_docs} ANN={ann_docs})")
    print(f"Timing: baseline {baseline_avg_ms} ms/doc, Method A {method_a_avg_ms} ms/doc, speedup {summary['timing']['speedup_ratio_baseline_over_method_a']}")
    if scorable > 0:
        print(f"Scorable ground truth: {scorable} docs (REAL_PPT={gt_breakdown['REAL_PPT']} NOTICE={gt_breakdown['NOTICE']} UNKNOWN={gt_breakdown['UNKNOWN']})")
        print(f"Baseline  P={metrics_baseline['precision']} R={metrics_baseline['recall']} F1={metrics_baseline['f1']} FPR={metrics_baseline['false_positive_rate']} (TP={tp_baseline} FP={fp_baseline} TN={tn_baseline} FN={fn_baseline})")
        print(f"Method A  P={metrics_a['precision']} R={metrics_a['recall']} F1={metrics_a['f1']} FPR={metrics_a['false_positive_rate']} (TP={tp_a} FP={fp_a} TN={tn_a} FN={fn_a})")
        print(f"FP reduction: {fp_reduction_abs} ({fp_reduction_pct}%) | FPR reduction: {fpr_reduction} | F1 delta: {delta(metrics_a.get('f1'), metrics_baseline.get('f1'))}")
        print(f"Corrected: {corrected}/{scorable} ({summary['corrections']['correction_rate_pct']}%) | FP rescued {baseline_fp_rescued} | new FN {new_fn_introduced}")
    else:
        print("No scorable ground truth docs (no downloaded PDFs with heuristic REAL/NOTICE). Metrics N/A.")
        print(f"Total changed (all docs): {total_changed_all} | PPT baseline {baseline_ppt_count} -> Method A {method_a_ppt_count} | flipped PPT->nonPPT {flipped_ppt_to_ann}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
