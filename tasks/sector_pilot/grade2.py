"""Grade the NSE/BSE sector labels from hand-read decisions.

decisions.jsonl (d1..d4) carries, per ISIN: fam (business family), sec
(secondary families), biz (one sentence), quote (verbatim or SEG=<name>),
segs (revenue split display).  This module resolves the quote to its source,
grades the five label fields by meaning, and writes CSV + JSON.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

import taxonomy as tx

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1] / "tasks" / "sector_pilot"
ROOT = TASK.parents[1]

# NSE basic-industry strings that are not fully covered by taxonomy.NSE_INDUSTRY
LABEL_FIX = {
    "RESIDENTIAL/COMMERCIAL/SEZ Project": "REALTY",
    "Residential Commercial Projects": "REALTY",
    "CONSUMER FOOD": "FMCG",
    "Road Assets - Toll Annuity Hybrid-Annuity": "LOGISTICS",
    "SPINNING-COTTON/BLENDED": "TEXTILES",
    "HOTELS/RESORTS": "LEISURE",
    "HOSPITAL": "HEALTHCARE",
    "Tour Travel Related Services": "LEISURE",
    "Film Production Distribution & Exhibition": "MEDIA",
    "Film Production, Distribution & Exhibition": "MEDIA",
    "Oil, Gas & Consumable Fuels": "OIL_GAS",
}

GENERIC = (set(tx.GENERIC_LABELS) - {"diversified metals"}) | {
    "other electrical equipment", "other food products", "other agricultural products",
    "other construction materials", "other textile products", "other utilities",
    "industrial products", "diversified consumer products",
}

# What a (usually macro) label legitimately covers, by meaning: the label names
# the business or a parent of it.  Used at sector granularity and for BSE
# industry_new; a generic or "Other X" label is handled before this.
SECTOR_ACCEPT = {
    "Automobile and Auto Components": {"AUTO"},
    "AUTOMOBILE": {"AUTO"},
    "Capital Goods": {"CAPITAL_GOODS", "AUTO", "DEFENCE", "PACKAGING", "METALS"},
    "Chemicals": {"CHEMICALS"},
    "Construction": {"CONSTRUCTION", "REALTY", "CEMENT"},
    "CONSTRUCTION": {"CONSTRUCTION", "REALTY", "CEMENT"},
    "Construction Materials": {"CEMENT", "CONSTRUCTION", "PACKAGING"},
    "Consumer Durables": {"CONSUMER_DURABLES", "JEWELLERY", "CHEMICALS"},
    "Consumer Services": {"CONSUMER_SERVICES", "RETAIL", "LEISURE", "EDUCATION"},
    "Fast Moving Consumer Goods": {"FMCG", "AGRI", "PAPER"},
    "CONSUMER GOODS": {"FMCG", "AGRI", "PAPER", "CONSUMER_DURABLES"},
    "Financial Services": {"FINANCE", "DIVERSIFIED"},
    "Healthcare": {"HEALTHCARE"},
    "HEALTHCARE SERVICES": {"HEALTHCARE"},
    "Information Technology": {"IT", "TELECOM"},
    "Media Entertainment & Publication": {"MEDIA", "TELECOM"},
    "Media, Entertainment & Publication": {"MEDIA", "TELECOM"},
    "Metals & Mining": {"METALS"},
    "Oil Gas & Consumable Fuels": {"OIL_GAS", "POWER"},
    "Oil, Gas & Consumable Fuels": {"OIL_GAS", "POWER"},
    "Power": {"POWER", "UTILITIES", "CONSTRUCTION", "CAPITAL_GOODS"},
    "Realty": {"REALTY", "CONSTRUCTION"},
    "Real Estate": {"REALTY", "CONSTRUCTION"},
    "Services": {"SERVICES", "LOGISTICS", "LEISURE", "EDUCATION", "CONSUMER_SERVICES"},
    "SERVICES": {"SERVICES", "LOGISTICS", "LEISURE", "EDUCATION", "CONSUMER_SERVICES"},
    "Textiles": {"TEXTILES"},
    "TEXTILES": {"TEXTILES"},
    "Telecommunication": {"TELECOM"},
    "Utilities": {"UTILITIES", "POWER"},
    "Forest Materials": {"PAPER"},
    "Diversified": {"DIVERSIFIED"},
    "Consumer Discretionary": {"AUTO", "RETAIL", "CONSUMER_DURABLES", "LEISURE", "TEXTILES",
                               "JEWELLERY", "MEDIA", "SERVICES", "CONSUMER_SERVICES",
                               "EDUCATION", "REALTY", "CHEMICALS"},
    "Commodities": {"METALS", "CHEMICALS", "CEMENT", "PAPER", "OIL_GAS"},
    "Materials": {"METALS", "CHEMICALS", "CEMENT", "PAPER", "PACKAGING"},
    "Industrials": {"CAPITAL_GOODS", "AUTO", "DEFENCE", "LOGISTICS", "PACKAGING",
                    "CONSTRUCTION", "SERVICES", "METALS"},
    "Energy": {"OIL_GAS", "POWER"},
    "Consumer Staples": {"FMCG", "AGRI"},
    "Consumer": {"FMCG", "RETAIL", "CONSUMER_DURABLES", "LEISURE", "TEXTILES",
                 "JEWELLERY", "EDUCATION", "AGRI", "CONSUMER_SERVICES"},
    "Communication Services": {"MEDIA", "TELECOM"},
}

HOLDING_LABELS = {"diversified", "holding company", "investment company",
                  "diversified commercial services"}


def norm(s: str) -> str:
    s = (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-")
    for a, b in (("ﬁ", "fi"), ("ﬂ", "fl"), ("ﬀ", "ff"), ("ﬃ", "ffi"), ("ﬄ", "ffl")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().lower()


def label_family(label: str):
    if not label:
        return None
    if label in LABEL_FIX:
        return LABEL_FIX[label]
    return tx.family_of_label(label)


def is_generic(label: str) -> bool:
    return (label or "").strip().lower() in GENERIC


def resolve_quote(ev, q):
    """Return (quote_text, reference) for a decision quote."""
    isin = ev.get("isin") or ""
    if q == "__EMPTY__":
        return "(no text in evidence bundle)", f"evidence.json[isin={isin}] (empty)"
    if q.startswith("SEG="):
        key = q[4:].lower()
        hits = [s for s in ev.get("seg_rows", []) if key in (s.get("item") or "").lower()]
        if not hits:
            raise SystemExit(f"SEG quote not found for {isin}: {q}")

        def seg_rank(s):
            it = (s.get("item") or "").lower()
            return (("revenue" in it) * 3 + ("sales" in it) + ("turnover" in it),
                    -len(it))

        s = max(hits, key=seg_rank)
        txt = s["item"]
        ref = f"ar_facts[isin={isin} fy={s['fy']} item={s['item'][:60]}]"
        return txt, ref
    nq = norm(q)
    candidates = [nq]
    if ": " in nq:
        candidates.append(nq.split(": ", 1)[1])
    for s in ev.get("ar_quotes", []):
        body = norm(s.get("quote") or "")
        item = norm(s.get("item") or "")
        if any(c in body or c in item for c in candidates):
            txt = s.get("quote") or s.get("item") or ""
            for c in candidates:
                if c in body:
                    txt = s.get("quote") or ""
                    break
                if c in item:
                    txt = s.get("item") or ""
                    break
            return txt, f"ar_facts[isin={isin} category={s.get('category')} fy={s.get('fy')}]"
    for c in ev.get("ar_chunks", []):
        if nq in norm(c.get("text") or ""):
            return q, f"document_chunks[doc_id={c['doc_id']} chunk={c['chunk_index']}]"
    for d in ev.get("deck_facts", []):
        if nq in norm(str(d.get("metric") or "")):
            return str(d["metric"]), \
                f"deck_figures[sha256={(d.get('sha256') or '')[:12]} known_at={(d.get('known_at') or '')[:10]}]"
    raise SystemExit(f"quote not found for {isin}: {q!r}")


def trim25(text: str) -> str:
    words = text.split()
    return " ".join(words[:25]) if len(words) > 25 else text


def grade_sector(label, fam, sec, level):
    lf = label_family(label)
    low = (label or "").strip().lower()
    if fam == "DIVERSIFIED" and low in HOLDING_LABELS:
        return "correct", f"'{label}' fits a genuinely multi-business holding company", ""
    if low == "diversified":
        if fam == "DIVERSIFIED":
            return "correct", "genuinely multi-business; 'Diversified' is accurate", ""
        return "partly", "too-generic 'Diversified' for a single-business company", "too_generic"
    if lf is None:
        return "partly", f"'{label}' maps to no business family", "unmapped_label"
    if lf == fam:
        return "correct", f"names the {fam.lower()} business", ""
    if fam in SECTOR_ACCEPT.get(label, set()):
        return "correct", f"'{label}' is a correct parent/umbrella for the {fam.lower()} business", ""
    if set(sec) & SECTOR_ACCEPT.get(label, set()):
        return "partly", f"names only a secondary leg, not the main {fam.lower()} business", "minor_segment"
    if tx.same_sector(lf, fam):
        return "partly", f"right macro area, imprecise for the {fam.lower()} business", "too_generic"
    return "wrong", f"a different business: label says {lf.lower()}, company is {fam.lower()}", "plainly_wrong"


def grade_industry(label, fam, sec, level):
    lf = label_family(label)
    if is_generic(label):
        if fam == "DIVERSIFIED" and label.strip().lower() == "diversified":
            return "correct", "genuinely multi-business; 'Diversified' is accurate", ""
        return "partly", f"too-generic '{label}'", "too_generic"
    if fam == "DIVERSIFIED" and label.strip().lower() in HOLDING_LABELS:
        return "correct", f"'{label}' fits a genuinely multi-business holding company", ""
    if lf is None:
        return "partly", f"'{label}' maps to no business family", "unmapped_label"
    if lf == fam:
        return "correct", f"names the {fam.lower()} business", ""
    if lf in sec:
        return "partly", f"names only a secondary leg, not the main {fam.lower()} business", "minor_segment"
    if tx.same_sector(lf, fam):
        return "partly", f"right sector, wrong industry (actual: {fam.lower()})", "wrong_industry"
    return "wrong", f"a different business: label says {lf.lower()}, company is {fam.lower()}", "plainly_wrong"


def main():
    sample = json.loads((TASK / "sample.json").read_text(encoding="utf-8"))["rows"]
    evidence = json.loads((TASK / "evidence.json").read_text(encoding="utf-8"))
    bse_all = json.loads((ROOT / ".tmp" / "bse_header_results.json").read_text(encoding="utf-8"))
    decisions = {}
    for p in sorted((ROOT / ".tmp" / "regrade").glob("d*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                decisions[d["isin"]] = d
    assert len(decisions) == 200, len(decisions)
    assert {r["isin"] for r in sample} == set(decisions), "sample/decision ISIN mismatch"

    out_rows = []
    missing = []
    for r in sample:
        ev = evidence.get(r["isin"], {})
        bse = bse_all.get(str(r["bse_code"]), {}) or {}
        d = decisions[r["isin"]]
        fam = d["fam"]
        sec = d.get("sec") or []
        try:
            quote, ref = resolve_quote(ev, d["quote"])
        except SystemExit as exc:
            missing.append(str(exc))
            quote, ref = "", ""
        quote = trim25(quote)

        if not fam:
            grades = {k: ("cannot_tell", "evidence does not establish the business", "cannot_tell_evidence")
                      for k in ("nse_sector", "nse_industry", "bse_sector", "bse_industry",
                                "bse_industry_new")}
            if not r.get("nse_sector"):
                grades["nse_sector"] = grades["nse_industry"] = ("n/a", "no NSE label", "")
        else:
            # NSE industry is graded on the deepest NSE label held (basic industry
            # when present), because that is the exchange's specific industry call.
            nse_deep = r.get("nse_basic_industry") or r.get("nse_industry") or ""
            grades = {
                "nse_sector": grade_sector(r.get("nse_sector") or "", fam, sec, "sector")
                if r.get("nse_sector") else ("n/a", "no NSE label (unlabelled/BSE-only)", ""),
                "nse_industry": grade_industry(nse_deep, fam, sec, "industry")
                if r.get("nse_sector") else ("n/a", "no NSE label (unlabelled/BSE-only)", ""),
                "bse_sector": grade_sector(bse.get("sector") or "", fam, sec, "sector"),
                "bse_industry": grade_industry(bse.get("industry") or "", fam, sec, "industry"),
                "bse_industry_new": grade_sector(bse.get("industry_new") or "", fam, sec, "sector"),
            }
        out = {
            "isin": r["isin"], "symbol": r["symbol"], "bse_code": r["bse_code"],
            "bucket": r["bucket"], "cap_tier": r["cap_tier"],
            "multi_segment": "yes" if r["multi_segment"] else "no",
            "nse_macro": r["nse_macro"], "nse_sector": r["nse_sector"],
            "nse_industry": r["nse_industry"], "nse_basic_industry": r["nse_basic_industry"],
            "nse_industry_graded": (r.get("nse_basic_industry") or r.get("nse_industry") or "") if fam else "",
            "bse_sector": bse.get("sector") or "",
            "bse_industry": bse.get("industry") or "",
            "bse_industry_new": bse.get("industry_new") or "",
            "segment_split": d["segs"],
            "main_business": d["biz"],
            "main_business_family": fam.lower(),
            "business_basis": d["basis"],
            "evidence_quote": quote,
            "quote_ref": ref,
            "evidence_chars": str(sum(len(c.get("text") or "") for c in ev.get("ar_chunks", []))),
        }
        errs = set()
        for k in d.get("stale") or []:
            if k in grades:
                grades[k] = ("stale",
                             "label fits the old business; the evidence shows the pivot "
                             f"({d['biz'].split(':')[0][:90]})", "pivot_stale")
        for k, (g, why, err) in grades.items():
            out[f"{k}_grade"] = g
            out[f"{k}_reason"] = why
            if err:
                errs.add(err)
        if fam == "DIVERSIFIED" and len(sec) >= 2 and "too_generic" in errs:
            errs.discard("too_generic")
            errs.add("conglomerate")
        out["error_types"] = ";".join(sorted(errs))
        out_rows.append(out)

    fields = list(out_rows[0])
    if missing:
        print(f"MISSING QUOTES ({len(missing)}):")
        for m in missing:
            print(" ", m)
        raise SystemExit(1)
    with (TASK / "sector_label_pilot.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    (TASK / "grades.json").write_text(json.dumps(out_rows, indent=1, ensure_ascii=False),
                                      encoding="utf-8")
    print("wrote", len(out_rows), "rows")
    for k in ("nse_sector", "nse_industry", "bse_sector", "bse_industry", "bse_industry_new"):
        print(k, dict(Counter(x[f"{k}_grade"] for x in out_rows)))
    print("families", dict(Counter(x["main_business_family"] for x in out_rows).most_common()))
    n = sum(1 for x in out_rows if x["main_business_family"] == "")
    print("cannot_tell rows:", n)


if __name__ == "__main__":
    main()
