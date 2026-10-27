"""Shared deterministic sampler for the sector-label pilot (seed 20261028).

`draw(exclude)` returns the 200 rows.  Excluding ISINs re-runs the SAME seeded
draw with those candidates removed, so a replaced company is literally the next
draw in its stratum rather than a new random sample.
"""
from __future__ import annotations

import os
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from reality_engine.db.readonly import connect_ro

SEED = 20261028
FY_CUTOFF = "2025-03-31"


def _load():
    data = Path(os.environ["REALITY_DATA_ROOT"])
    eq = connect_ro(data / "equity_intelligence.db", timeout_s=120)
    ar = connect_ro(data / "ar_facts.db", timeout_s=120)
    rx = connect_ro(data / "results_xbrl.db", timeout_s=120)
    return data, eq, ar, rx


def _pools(eq, ar, rx, exclude):
    masters = {}
    for row in eq.execute(
        "select isin,nse_symbol,bse_code,company_name,industry,sector,market_cap_tier,"
        "is_active from master_companies"):
        isin, nse, bse, name, ind, sec, tier, active = row
        masters[isin] = {"isin": isin, "symbol": nse or "", "bse_code": (bse or "").strip(),
                         "name": name or "", "master_industry": ind or "",
                         "master_sector": sec or "", "tier": tier, "active": active}
    for isin, bse in eq.execute(
            "select isin,bse_code from security_master where bse_code is not null and bse_code<>''"):
        if isin in masters and not masters[isin]["bse_code"]:
            masters[isin]["bse_code"] = str(bse).strip()

    cap = {}
    for isin, mcap in eq.execute(
            "select isin,max(market_cap_inr_cr) from company_forensic_health "
            "where market_cap_inr_cr is not null group by isin"):
        cap[isin] = float(mcap)

    def tier_of(isin):
        mcap = cap.get(isin)
        if mcap is not None:
            if mcap >= 50000:
                return "LARGE"
            if mcap >= 10000:
                return "MID"
            if mcap >= 1000:
                return "SMALL"
            return "MICRO"
        t = masters[isin]["tier"]
        return t if t in ("SMALL", "MICRO") else None

    label = {}
    for row in eq.execute(
            "select isin,symbol,macro,sector,industry,basic_industry from company_industry"):
        label[row[0]] = {"symbol": row[1], "macro": row[2] or "", "sector": row[3] or "",
                         "industry": row[4] or "", "basic_industry": row[5] or ""}

    ar_fy = defaultdict(set)
    for isin, fy in ar.execute("select isin,fiscal_year from ar_docs"):
        if fy and fy >= FY_CUTOFF:
            ar_fy[isin].add(fy)
    xbrl_fy = dict(rx.execute(
        "select isin,max(period_end) from filings where period_end>=? group by isin", (FY_CUTOFF,)))
    deck_fy = set()
    df = connect_ro(Path(os.environ["REALITY_DATA_ROOT"]) / "deck_figures.db", timeout_s=60)
    for (isin,) in df.execute(
            "select distinct isin from deck_sources where known_at>='2025-01-01' and isin is not null"):
        if isin:
            deck_fy.add(isin)

    def evidence_kinds(isin):
        kinds = []
        if ar_fy.get(isin):
            kinds.append("ar")
        if isin in xbrl_fy:
            kinds.append("xbrl")
        if isin in deck_fy:
            kinds.append("deck")
        if not kinds:
            n = eq.execute(
                "select 1 from document_chunks where isin=? and "
                "(event_date>='2025-01-01' or published_date>='2025-01-01') limit 1", (isin,)).fetchone()
            if n:
                kinds.append("chunks")
        return kinds

    pool_a, pool_b = [], []
    rejects = Counter()
    for isin, m in masters.items():
        if isin in exclude or not m["active"] or not m["bse_code"]:
            continue
        t = tier_of(isin)
        if t not in ("SMALL", "MICRO"):
            continue
        kinds = evidence_kinds(isin)
        if not kinds:
            rejects["no_evidence"] += 1
            continue
        rec = dict(m, tier=t, evidence="+".join(kinds))
        if isin in label and label[isin]["sector"]:
            rec["nse"] = label[isin]
            pool_a.append(rec)
        elif isin in label:
            rejects["label_row_but_blank_sector"] += 1
        else:
            pool_b.append(rec)
    return pool_a, pool_b, rejects


def segment_names(ar, isins):
    """Distinct plausible segment names in the latest FY (batched, indexed)."""
    out = {}
    for i in range(0, len(isins), 200):
        batch = isins[i:i + 200]
        qmarks = ",".join("?" * len(batch))
        rows = ar.execute(
            f"select isin,fiscal_year,item from ar_facts where isin in ({qmarks}) "
            "and category='segment' and fiscal_year>=?", (*batch, FY_CUTOFF)).fetchall()
        per = defaultdict(lambda: defaultdict(set))
        for isin, fy, item in rows:
            if not item:
                continue
            low = item.lower()
            if "share of" in low or "reason" in low or "projected" in low or "pat from" in low:
                continue
            m = re.search(r"segment revenue(?: \(external\))?\s*-\s*(.+?)\s*(?:fy\d\d|\d{4})?$",
                          item, re.I)
            name = m.group(1).strip().lower() if m else None
            if name is None:
                m2 = re.match(r"^(.+?)\s+segment\s+(?:revenue|pbit|profit|ebitda)", item, re.I)
                name = m2.group(1).strip().lower() if m2 else None
            if name:
                per[isin][fy].add(name)
        for isin, fys in per.items():
            out[isin] = sorted(fys[max(fys)])
    return out


def draw(exclude=()):
    data, eq, ar, rx = _load()
    exclude = set(exclude)
    pool_a, pool_b, rejects = _pools(eq, ar, rx, exclude)
    segs = segment_names(ar, [r["isin"] for r in pool_a if "ar" in r["evidence"]])
    for r in pool_a:
        r["segments_found"] = segs.get(r["isin"], [])
        r["multi_segment"] = len(r["segments_found"]) >= 2

    rng = random.Random(SEED)
    a_by_sector = defaultdict(list)
    a_multi = []
    for r in pool_a:
        a_by_sector[r["nse"]["sector"] or "(blank)"].append(r)
        if r["multi_segment"]:
            a_multi.append(r)
    for bucket in a_by_sector.values():
        rng.shuffle(bucket)
    rng.shuffle(a_multi)

    chosen_a, used_a = [], set()
    by_sector_multi = defaultdict(list)
    for r in a_multi:
        by_sector_multi[r["nse"]["sector"] or "(blank)"].append(r)
    sectors = sorted(by_sector_multi)
    idx = 0
    while len(chosen_a) < 40 and any(by_sector_multi[s] for s in sectors):
        s = sectors[idx % len(sectors)]
        if by_sector_multi[s] and len(chosen_a) < 40:
            r = by_sector_multi[s].pop(0)
            if r["isin"] not in used_a:
                chosen_a.append(r)
                used_a.add(r["isin"])
        idx += 1

    order = sorted(a_by_sector)
    idx, guard = 0, 0
    while len(chosen_a) < 150 and guard < 10000:
        s = order[idx % len(order)]
        if a_by_sector[s]:
            r = a_by_sector[s].pop(0)
            if r["isin"] not in used_a:
                chosen_a.append(r)
                used_a.add(r["isin"])
        idx += 1
        guard += 1

    b_by_sec = defaultdict(list)
    for r in pool_b:
        b_by_sec[r["master_sector"] or "(unknown)"].append(r)
    for bucket in b_by_sec.values():
        rng.shuffle(bucket)
    chosen_b, used_b = [], set()
    order_b = sorted(b_by_sec)
    idx, guard = 0, 0
    while len(chosen_b) < 50 and guard < 10000:
        s = order_b[idx % len(order_b)]
        if b_by_sec[s]:
            r = b_by_sec[s].pop(0)
            if r["isin"] not in used_b:
                chosen_b.append(r)
                used_b.add(r["isin"])
        idx += 1
        guard += 1

    sample = []
    for i, r in enumerate(chosen_a + chosen_b):
        sample.append({
            "isn": i + 1,
            "bucket": "A_nse_labelled" if r in chosen_a else "B_unlabelled",
            "isin": r["isin"],
            "symbol": r["symbol"],
            "bse_code": r["bse_code"],
            "company_name": r["name"],
            "cap_tier": r["tier"],
            "evidence_kinds": r["evidence"],
            "multi_segment": bool(r.get("multi_segment", False)),
            "segments_found": r.get("segments_found", []),
            "nse_macro": (r.get("nse") or {}).get("macro", ""),
            "nse_sector": (r.get("nse") or {}).get("sector", ""),
            "nse_industry": (r.get("nse") or {}).get("industry", ""),
            "nse_basic_industry": (r.get("nse") or {}).get("basic_industry", ""),
            "master_industry": r["master_industry"],
            "master_sector": r["master_sector"],
        })
    return sample, dict(rejects)
