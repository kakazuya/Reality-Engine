"""Reportable segments from the raw results XBRL into ``kpi_series`` (night loop 2).

``results_xbrl.db.facts`` keeps only the undimensioned totals, so the per-segment values are read here from the raw
instance files.  Per window filing of each profile company the script writes, as ``source_type='xbrl_segment'``:

* ``segment_revenue``  (``SegmentRevenue`` on the reportable-segments axis; life insurers: the sum of net premium,
  income from investments, other income and transfer from the shareholders' account, ``is_reported`` 0),
* ``segment_ebit``     (``SegmentProfitLossBeforeTaxAndFinanceCosts``; life insurers: ``SurplusDeficit``),
* ``segment_assets`` / ``segment_liabilities`` (instant contexts; the name sits in the sister duration context),
* a filing that says ``Single segment`` and carries no segment axis gets one honest row per metric with
  ``dimension='single_segment'`` (company revenue; profit before tax + finance costs; ``is_reported`` 0).

Axis, member and period always come from the context element, never from the context id.  Segment names are
normalised and mapped, per company, to the latest filing's spelling (difflib ratio >= 0.85); the name as filed stays
in ``raw_label``.  No company literal lives here: the file list comes from the active profile.  No model, no network.

    python -m reality_engine.pilot3.build --profile <json> --part segments --out <db>
"""
from __future__ import annotations

import collections
import difflib
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from reality_engine.config import raw_dir
from reality_engine.gap_loop import prepare
from reality_engine import raw_store
from reality_engine.pilot3 import kpi, profile
from reality_engine.pilot3.registry import all_isins
from reality_engine.pilot3.stores import _basis, fiscal_period

SOURCE_TYPE = "xbrl_segment"
RULE = "xbrl_segment"
KNOWN_SOURCE = "results_xbrl.filings.dissem_ts|broadcast_ts|filing_ts"
RAW = raw_dir("raw_market") / "nse_results_xbrl"
NAME_RATIO = 0.85

LI_REVENUE_PARTS = ("NetPremium", "IncomeFormInvestments", "OtherIncome", "TransferOfFundsFromShareholdersAccount")
# concept -> (metric, is_reported) read from a context that carries a segment axis
SEGMENT_CONCEPTS = {"SegmentRevenue": ("segment_revenue", 1),
                    "SegmentProfitLossBeforeTaxAndFinanceCosts": ("segment_ebit", 1),
                    "SegmentAssets": ("segment_assets", 1), "SegmentLiabilities": ("segment_liabilities", 1)}
LI_EBIT = "SurplusDeficit"
SINGLE_FLAG = "IsCompanyReportingMultisegmentOrSingleSegment"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalise(name: str) -> str:
    """``(a) Novelis`` -> ``novelis``; spaces and punctuation collapse to one underscore."""
    text = re.sub(r"^\s*\(\s*[a-z0-9]{1,3}\s*\)\s*", "", str(name or ""), flags=re.I)
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "segment"


def _months(start: str, end: str) -> int | None:
    try:
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    except (TypeError, ValueError):
        return None
    return round(days / 30.44)


def period_label(start: str | None, end: str) -> tuple[str, str] | None:
    """``(period_type, fiscal_period)`` of a duration (Q / H1 / H2 / 9M / FY) or of an instant (start None -> Q)."""
    if start is None:
        label = fiscal_period(end)
        return ("Q", label) if label else None
    months = _months(start, end)
    y, m = int(end[:4]), int(end[5:7])
    fy = str(y + 1 if m >= 4 else y)[2:]
    if months == 3:
        label = fiscal_period(end)
        return ("Q", label) if label else None
    if months == 6:
        return ("H1", f"H1FY{fy}") if int(start[5:7]) == 4 else ("H2", f"H2FY{fy}")
    if months == 9:
        return "9M", f"9MFY{fy}"
    if months == 12:
        return "FY", f"FY{fy}"
    return None


def parse_file(path: Path) -> dict:
    """``{"segments": [...], "single": {...}|None, "totals": {...}}`` of one instance; values are raw floats.

    segments: dicts ``axis, member, concept, start, end, value, name``; totals: undimensioned concept -> {(start,end): v}.
    """
    root = ET.parse(path).getroot()
    contexts: dict[str, dict] = {}
    for el in root:
        if _local(el.tag) != "context":
            continue
        dims, start, end = [], None, None
        for node in el.iter():
            tag = _local(node.tag)
            if tag == "explicitMember":
                dims.append((_local(node.get("dimension", "")).split(":")[-1], (node.text or "").strip().split(":")[-1]))
            elif tag == "typedMember":
                dims.append((node.get("dimension", "").split(":")[-1], "typed"))
            elif tag == "startDate":
                start = (node.text or "").strip()
            elif tag == "endDate":
                end = (node.text or "").strip()
            elif tag == "instant":
                end = (node.text or "").strip()
        contexts[el.get("id")] = {"dims": dims, "start": start, "end": end}
    names: dict[tuple, str] = {}    # (axis, member, end) -> name from a Description... concept
    names_any: dict[tuple, str] = {}  # (member, end) -> name from any axis
    seg, totals, texts = [], collections.defaultdict(dict), {}
    for el in root:
        ref = el.get("contextRef")
        if not ref or ref not in contexts:
            continue
        ctx, concept, text = contexts[ref], _local(el.tag), (el.text or "").strip()
        dims = ctx["dims"]
        if not dims:
            texts.setdefault(concept, {})[(ctx["start"], ctx["end"])] = text
            try:
                totals[concept][(ctx["start"], ctx["end"])] = float(text)
            except ValueError:
                pass
            continue
        if len(dims) != 1 or "Segment" not in dims[0][0]:
            continue
        axis, member = dims[0]
        if concept.startswith("DescriptionOfReportableSegment"):
            names[(axis, member, ctx["end"])] = text
            names_any.setdefault((member, ctx["end"]), text)
            continue
        try:
            value = float(text)
        except ValueError:
            continue
        seg.append({"axis": axis, "member": member, "concept": concept, "start": ctx["start"], "end": ctx["end"],
                    "value": value})
    for s in seg:
        s["name"] = names.get((s["axis"], s["member"], s["end"])) or names_any.get((s["member"], s["end"])) or s["member"]
    return {"segments": seg, "totals": totals, "texts": texts}


def segment_rows(parsed: dict, period_end: str) -> list[dict]:
    """Metric rows ``{metric, name, start, end, value, is_reported, raw_value, label}`` of a parsed instance (only the
    contexts that end on the filing's period end; comparatives belong to the earlier filing)."""
    groups: dict[tuple, dict] = {}
    for s in parsed["segments"]:
        if s["end"] != period_end:
            continue
        concept, axis = s["concept"], s["axis"]
        if concept in SEGMENT_CONCEPTS:
            metric, reported = SEGMENT_CONCEPTS[concept]
        elif concept in LI_REVENUE_PARTS and axis == "SegmentRevenueAxis":
            metric, reported = "segment_revenue", 0
        elif concept == LI_EBIT and axis == "SegmentSurplusDeficitAxis":
            metric, reported = "segment_ebit", 1
        else:
            continue
        key = (metric, s["member"], s["start"], s["end"], axis)
        g = groups.setdefault(key, {"metric": metric, "name": s["name"], "start": s["start"], "end": s["end"],
                                    "value": 0.0, "is_reported": reported, "parts": [], "concept": concept})
        g["value"] += s["value"]
        g["parts"].append(f"{concept}={s['value']:.0f}")
    out = []
    for g in groups.values():
        multi = len(g["parts"]) > 1
        g["raw_value"] = ";".join(g["parts"]) if multi else f"{g['concept']}={g['value']:.0f}"
        g["label"] = g["concept"] if g["concept"] == LI_EBIT else g["name"]
        out.append(g)
    return out


def single_rows(parsed: dict, period_end: str) -> list[dict]:
    """One row per duration and metric for a filing that says ``Single segment`` (empty otherwise)."""
    texts, totals = parsed["texts"], parsed["totals"]
    flag = next(iter(texts.get(SINGLE_FLAG, {}).values()), "")
    if flag.strip().lower() != "single segment":
        return []
    desc = next((v for v in texts.get("DescriptionOfSingleSegment", {}).values()
                 if v and v.strip().upper() != "NA"), "")[:200] or "Single segment"
    out = []
    for (start, end), concept, value in _single_revenue(totals):
        if end == period_end and start:
            out.append({"metric": "segment_revenue", "name": "single_segment", "start": start, "end": end,
                        "value": value, "is_reported": 0, "raw_value": f"{concept}={value:.0f}", "label": desc})
    pbt, fin = totals.get("ProfitBeforeTax", {}), totals.get("FinanceCosts", {})
    for (start, end), p in pbt.items():
        if end == period_end and start and (start, end) in fin:
            out.append({"metric": "segment_ebit", "name": "single_segment", "start": start, "end": end,
                        "value": p + fin[(start, end)], "is_reported": 0, "label": desc,
                        "raw_value": f"ProfitBeforeTax={p:.0f};FinanceCosts={fin[(start, end)]:.0f}"})
    return out


def _single_revenue(totals: dict):
    """(period, concept, value): RevenueFromOperations, else total Income, per period."""
    rev, inc = totals.get("RevenueFromOperations", {}), totals.get("Income", {})
    for period in sorted(set(rev) | set(inc), key=lambda p: (p[0] or "", p[1] or "")):
        if period in rev:
            yield period, "RevenueFromOperations", rev[period]
        else:
            yield period, "Income", inc[period]


def reconcile(parsed: dict, rows: list[dict]) -> list[dict]:
    """Check 3: per duration, sum of ``segment_revenue`` less ``InterSegmentRevenue`` against the filing's undimensioned
    ``SegmentRevenueFromOperations`` (1% tolerance).  Returns the failures; filings without that total are not checked."""
    total = parsed["totals"].get("SegmentRevenueFromOperations", {})
    inter = parsed["totals"].get("InterSegmentRevenue", {})
    sums: dict[tuple, float] = collections.defaultdict(float)
    for r in rows:
        if r["metric"] == "segment_revenue" and r["name"] != "single_segment":
            sums[(r["start"], r["end"])] += r["value"]
    fails = []
    for period, got in sums.items():
        want = total.get(period)
        if want is None:
            continue
        calc = got - inter.get(period, 0.0)
        if abs(calc - want) > 0.01 * max(abs(want), 1.0):
            fails.append({"period": f"{period[0]}..{period[1]}", "segments_less_inter": calc, "filing_total": want})
    return fails


def _canonical(names_by_file: list[tuple[str, list[str]]]) -> dict[str, str]:
    """Map every normalised name of a company to a canonical spelling.  Names that occur together in one filing are
    different segments and never merge; similar names (ratio >= ``NAME_RATIO``) that never occur together merge, and
    the canonical spelling is the one in the most filings (a tie goes to the latest filing)."""
    count: dict[str, int] = collections.Counter()
    last: dict[str, str] = {}
    together: dict[str, set[str]] = collections.defaultdict(set)
    for key, names in names_by_file:
        for n in set(names):
            count[n] += 1
            last[n] = max(last.get(n, ""), key)
            together[n].update(m for m in names if m != n)
    clusters: dict[str, set[str]] = {}  # canonical -> members
    mapping: dict[str, str] = {}
    for n in sorted(count, key=lambda x: (-count[x], _neg(last[x]), x)):
        best, score = None, 0.0
        for c, members in clusters.items():
            if together[n] & members:
                continue
            r = difflib.SequenceMatcher(None, n, c).ratio()
            if r > score:
                best, score = c, r
        if best is not None and score >= NAME_RATIO:
            clusters[best].add(n)
            mapping[n] = best
        else:
            clusters[n] = {n}
            mapping[n] = n
    return mapping


def _neg(s: str) -> tuple:
    """Sort key putting the larger string first."""
    return tuple(-ord(ch) for ch in s)


def _filings(symbol: str) -> list[dict]:
    isins = all_isins(symbol)
    marks = ",".join("?" * len(isins))
    start = profile.window_start() or "0000-00-00"
    rows, types = prepare._read_sqlite(
        "results_xbrl.db", "filings",
        f"SELECT file, isin, consolidated, period_start, period_end, coalesce(dissem_ts, broadcast_ts, filing_ts) AS known_at "
        f"FROM filings WHERE isin IN ({marks}) AND period_end >= ? ORDER BY period_end, known_at", tuple(isins) + (start,))
    cols = list(types)
    found = [dict(zip(cols, r)) for r in rows]
    latest: dict[tuple, dict] = {}
    for f in found:  # a revision of the same period and basis: keep the latest known_at
        latest[(f["period_end"], _basis(f["consolidated"]))] = f
    return sorted(latest.values(), key=lambda f: (f["period_end"], f["known_at"] or ""))


def _ensure_table(con: sqlite3.Connection) -> None:
    con.executescript(kpi.SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(kpi_series)")}
    for name, ddl in kpi.NEW_COLS:
        if name not in have:
            con.execute(f"ALTER TABLE kpi_series ADD COLUMN {name} {ddl}")


def run(db_path: str, symbols: list[str], raw_root: Path | None = None) -> dict:
    """Write the segment rows of ``symbols`` into ``kpi_series`` of ``db_path`` (their ``xbrl_segment`` rows first
    deleted).  Returns ``{symbol: {"files", "rows", "single_rows", "recon_failures", "failures": [...]}}``."""
    raw = Path(raw_root) if raw_root else RAW
    con = sqlite3.connect(db_path)
    _ensure_table(con)
    stats: dict = {}
    sql = f"INSERT OR IGNORE INTO kpi_series({','.join(kpi.COLS)}) VALUES({','.join('?' * len(kpi.COLS))})"
    try:
        for sym in symbols:
            con.execute("DELETE FROM kpi_series WHERE symbol=? AND source_type=?", (sym, SOURCE_TYPE))
            filings = _filings(sym)
            parsed_files = []
            store = raw_store.default_store()   # T-102: the XBRL files live on Drive; one prefetch per company
            with store.prefetch([raw / f["file"] for f in filings]):
                for f in filings:
                    path = raw / f["file"]
                    if not store.exists(path):
                        continue
                    with store.local(path) as local:
                        parsed = parse_file(local)
                    rows = segment_rows(parsed, f["period_end"]) or single_rows(parsed, f["period_end"])
                    parsed_files.append((f, parsed, rows))
            mapping = _canonical([(f["period_end"] + "|" + (f["known_at"] or ""),
                                   sorted({normalise(r["name"]) for r in rows if r["name"] != "single_segment"}))
                                  for f, _, rows in parsed_files])
            n_rows = n_single = 0
            failures = []
            for f, parsed, rows in parsed_files:
                basis = _basis(f["consolidated"])
                for fail in reconcile(parsed, rows):
                    failures.append({"file": f["file"], "period_end": f["period_end"], "basis": basis, **fail})
                batch = []
                for r in rows:
                    label = period_label(r["start"], r["end"])
                    if label is None:
                        continue
                    ptype, fiscal = label
                    dim = "single_segment" if r["name"] == "single_segment" else mapping.get(normalise(r["name"]), normalise(r["name"]))
                    batch.append((sym, r["metric"], dim, r["value"], "inr", 1, ptype, fiscal, r["end"], basis,
                                  f["file"], 0, "", f["known_at"], KNOWN_SOURCE, r["is_reported"], r["label"],
                                  r["raw_value"], RULE, "xbrl", 5, "xbrl", None, SOURCE_TYPE, sym))
                    n_single += dim == "single_segment"
                if batch:
                    con.executemany(sql, batch)
                    n_rows += len(batch)
                    con.execute("UPDATE kpi_series SET isin=? WHERE symbol=? AND doc_key=? AND isin IS NULL",
                                (f["isin"], sym, f["file"]))
            stats[sym] = {"files": len(parsed_files), "rows": n_rows, "single_rows": n_single,
                          "recon_failures": len(failures), "failures": failures}
        con.commit()
    finally:
        con.close()
    return stats
