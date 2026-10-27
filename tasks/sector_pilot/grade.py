"""Build business profiles from evidence, grade NSE/BSE labels, write the CSV."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import taxonomy as tx

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]

UNIT_TO_CR = {
    "rs crore": 1.0, "rs. crore": 1.0, "rs cr": 1.0, "crore": 1.0, "inr crore": 1.0,
    "₹ crore": 1.0, "rs million": 0.1, "rs. million": 0.1, "rs mn": 0.1, "million": 0.1,
    "₹ million": 0.1, "inr million": 0.1, "rs lakh": 0.01, "rs. lakh": 0.01, "lakh": 0.01,
    "₹ lakh": 0.01, "inr lakh": 0.01, "rs lacs": 0.01, "rs. lacs": 0.01, "lacs": 0.01,
    "lakhs": 0.01, "rs lac": 0.01, "rs billion": 10.0, "billion": 10.0,
}
EXACT_SEG = {
    "power": "POWER", "cement": "CEMENT", "chemicals": "CHEMICALS", "chemical": "CHEMICALS",
    "textiles": "TEXTILES", "textile": "TEXTILES", "pharma": "HEALTHCARE",
    "pharmaceuticals": "HEALTHCARE", "retail": "RETAIL", "steel": "METALS",
    "fertilizers": "CHEMICALS", "fertilisers": "CHEMICALS", "paints": "CHEMICALS",
    "engineering": "CAPITAL_GOODS", "logistics": "LOGISTICS", "packaging": "PACKAGING",
    "wealth management": "FINANCE", "insurance": "FINANCE", "hotels": "LEISURE",
}
SKIP_SEG = re.compile(
    r"inter[- ]?segment|eliminat|unallocat|total|reconcil|less:|add:|concentration|"
    r"geograph|previous year|prior year|segment assets|segment liabilit|customer|"
    r"business segment$|primary segment|reportable segment", re.I)
GEO_SEG = re.compile(
    r"^(?:india|outside india|domestic|export|exports|overseas|usa|u\.s\.|europe|africa|"
    r"middle east|asia|row|rest of|north america|united states|americas|other geograph\w*)",
    re.I)
STALE_HINT = re.compile(
    r"discontinu|ceased|exited|demerg|hived|sold off|divested|no longer|"
    r"transfer of .{0,30}undertaking|struck off|closed (?:the|its) .{0,20}business", re.I)
CORE_DESC = re.compile(
    r"(?:is (?:primarily |mainly |currently )?engaged in(?: the business of)?|"
    r"engaged in the business of|the business of|manufactures?|produces?|provides?|"
    r"deals? in|offers?|is into|carries on the business of)\s+"
    r"([^.;|]{15,260})", re.I)


def _clean_seg_name(name: str) -> str:
    n = re.sub(r"\(standalone\)|\(consolidated\)|standalone|consolidated", "", name, flags=re.I)
    n = re.sub(r"\((?:prior|previous) year[^)]*\)", "", n, flags=re.I)
    n = re.sub(r"\((?:external|internal)\)", "", n, flags=re.I)
    n = re.sub(r"\([^)]*\d[^)]*\)", "", n)
    n = re.sub(r"\bFY\s?\d{2,4}\b|\b20\d\d(?:-\d\d)?\b", "", n, flags=re.I)
    n = re.sub(r"^(?:revenue|sales|income|turnover)\s+from\s+", "", n, flags=re.I)
    n = re.sub(r"\s+", " ", n).strip(" -:;,")
    return n


NON_REV = re.compile(
    r"assets?|liabilit|capex|capital expenditure|profit|pbit|ebitda|margin|concentration|"
    r"expenditure|reconciliation|depreciation|tax|employee|result", re.I)
REV_ITEM = re.compile(r"revenue|sales|turnover|income from operations", re.I)


def parse_segments(ev):
    """Return segments = [{name, cr, share}] from ar_facts segment rows.

    Only revenue-type rows count: "Segment assets - X" and "Segment
    liabilities - X" are common in ar_facts and must never become revenue.
    """
    by_name = {}
    share_hint = {}
    for row in ev.get("seg_rows", []):
        item = row.get("item") or ""
        unit = (row.get("unit") or "").strip().lower()
        value = row.get("value")
        if SKIP_SEG.search(item):
            continue
        m = re.search(r"segment revenue share\s*[-–:]\s*(.+)", item, re.I)
        if m and unit == "%" and isinstance(value, (int, float)) and 0 < value <= 100:
            name = _clean_seg_name(m.group(1))
            if name and not GEO_SEG.search(name):
                share_hint[name.lower()] = value / 100.0
            continue
        if NON_REV.search(item) or not REV_ITEM.search(item):
            continue
        name = None
        m = re.search(
            r"segment\s+(?:total\s+)?(?:revenue|sales)(?:\s*\(external\))?\s*[-–:]\s*(.+?)$",
            item, re.I)
        if m and not re.match(r"^(?:from|total|others?)\b", m.group(1), re.I):
            name = _clean_seg_name(m.group(1))
        if not name:
            m = re.match(r"^(.+?)\s+segment\s+(?:total\s+)?(?:revenue|sales)", item, re.I)
            if m:
                name = _clean_seg_name(m.group(1))
        if not name:
            m = re.match(r"^(.+?)\s+segment", item, re.I)
            if m and "revenue" in item.lower():
                name = _clean_seg_name(m.group(1))
        if not name:
            m = re.match(r"^(?:revenue|sales|income|turnover)\s+from\s+(.+)", item, re.I)
            if m:
                name = _clean_seg_name(m.group(1))
        if not name or not name.strip() or SKIP_SEG.search(name):
            continue
        if GEO_SEG.search(name):
            continue
        factor = UNIT_TO_CR.get(unit)
        if factor is None or not isinstance(value, (int, float)) or value <= 0:
            continue
        key = name.lower()
        by_name[key] = {"name": name, "cr": by_name.get(key, {}).get("cr", 0.0) + value * factor}
    segs = list(by_name.values())
    total = sum(s["cr"] for s in segs)
    for s in segs:
        s["share"] = s["cr"] / total if total else 0.0
    if not segs and share_hint:
        for name, sh in share_hint.items():
            segs.append({"name": name, "cr": sh, "share": sh})
    return segs


def _seg_family(name: str):
    key = name.strip().lower()
    if key in EXACT_SEG:
        return EXACT_SEG[key]
    return tx.segment_family(name)


def build_profile(ev):
    segs = parse_segments(ev)
    prof = {"segments": segs, "shares": defaultdict(float), "unknown_seg_share": 0.0,
            "text": Counter(), "chars": 0, "thin": False}
    for s in segs:
        fam = _seg_family(s["name"])
        if fam is None:
            prof["unknown_seg_share"] += s["share"]
        else:
            prof["shares"][fam] += s["share"]

    texts = []
    for c in ev.get("ar_chunks", []):
        texts.append(re.sub(r"^\[Metadata:[^\]]*\]\s*", "", c.get("text") or ""))
    for q in ev.get("ar_quotes", []):
        texts.append(q.get("quote") or "")
    for s in ev.get("seg_rows", []):
        texts.append(f"{s.get('item') or ''} {s.get('quote') or ''}")
    for c in ev.get("concall", []):
        texts.append(c.get("statement") or "")
    for d in ev.get("deck_facts", []):
        texts.append(d.get("metric") or "")
    body = "\n".join(texts)
    prof["chars"] = len(body)
    prof["body"] = body

    all_others = bool(segs) and all(
        re.match(r"^(?:others?|other operating|unallocat)", s["name"], re.I) for s in segs)
    if all_others:
        prof["shares"] = defaultdict(float)
        prof["unknown_seg_share"] = 1.0
        prof["all_others"] = True
    else:
        prof["all_others"] = False

    # the "we are engaged in ..." sentences carry the business; weight them x3
    core = []
    for m in CORE_DESC.finditer(body):
        snippet = re.sub(r"\s+", " ", m.group(1)).strip()
        if len(snippet) >= 15:
            core.append(snippet)
    core_text = "\n".join(core[:6])
    prof["core"] = core_text[:900]
    txt = Counter(tx.text_signals(body))
    for fam, n in tx.text_signals(core_text).items():
        txt[fam] += n * 3
    prof["text"] = txt

    if prof["shares"]:
        prof["primary"] = max(prof["shares"], key=prof["shares"].get)
        prof["primary_share"] = prof["shares"][prof["primary"]]
        prof["mode"] = "segments"
    elif prof["text"]:
        prof["primary"] = prof["text"].most_common(1)[0][0]
        prof["primary_share"] = 0.0
        prof["mode"] = "text"
    else:
        prof["primary"] = None
        prof["primary_share"] = 0.0
        prof["mode"] = "none"

    top_text = max(prof["text"].values()) if prof["text"] else 0
    prof["alternates"] = {f for f, n in prof["text"].items()
                          if f != prof["primary"] and n >= max(3, top_text * 0.5)}
    prof["thin"] = (not segs and prof["chars"] < 300) or prof["primary"] is None
    if not segs and sum(prof["text"].values()) < 3 and len(prof.get("core") or "") < 60:
        prof["thin"] = True
    if prof.get("all_others") and len(prof.get("core") or "") < 40:
        prof["thin"] = True
    return prof


def main_business_line(prof):
    segs = sorted(prof["segments"], key=lambda s: -s["cr"])
    if segs:
        return "; ".join(f"{s['name']} ({s['share'] * 100:.0f}%)" for s in segs[:3])
    hits = prof["text"].most_common(2)
    if hits:
        return "text signals: " + ", ".join(f"{k.lower()} ({v})" for k, v in hits)
    return ""


def evidence_refs(ev):
    refs = [f"{s['store']}[{s['doc']}]" for s in ev.get("sources", [])]
    for c in ev.get("ar_chunks", [])[:2]:
        refs.append(f"document_chunks doc_id={c['doc_id']} chunk={c['chunk_index']}")
    for s in ev.get("seg_rows", [])[:1]:
        refs.append(f"ar_facts.segment FY={s['fy']} item={s['item'][:50]}")
    return " | ".join(refs[:4])


def _stale_for(prof, fam):
    if fam not in prof["shares"]:
        return False
    for s in prof["segments"]:
        if _seg_family(s["name"]) == fam and s["share"] < 0.05:
            for m in STALE_HINT.finditer(prof["body"]):
                window = prof["body"][max(0, m.start() - 160):m.end() + 160]
                if tx.family_hits(window) and fam in tx.family_hits(window):
                    return True
    return False


# NSE sector labels are coarse parents: the children accepted under each label.
LABEL_ACCEPT = {
    "Consumer Durables": {"CONSUMER_DURABLES", "JEWELLERY", "CHEMICALS", "CAPITAL_GOODS"},
    "Capital Goods": {"CAPITAL_GOODS", "PACKAGING", "DEFENCE", "AUTO", "CEMENT"},
    "Services": {"SERVICES", "LOGISTICS", "LEISURE", "EDUCATION", "CONSUMER_SERVICES"},
    "Consumer Services": {"CONSUMER_SERVICES", "RETAIL", "LEISURE", "EDUCATION"},
    "Media Entertainment & Publication": {"MEDIA", "TELECOM"},
    "Utilities": {"UTILITIES", "POWER", "CHEMICALS"},
    "Construction Materials": {"CEMENT", "CONSTRUCTION", "CHEMICALS", "PAPER"},
    "Oil Gas & Consumable Fuels": {"OIL_GAS", "POWER", "LOGISTICS"},
    "Fast Moving Consumer Goods": {"FMCG", "AGRI", "PAPER", "CONSUMER_DURABLES"},
    "Metals & Mining": {"METALS", "MINING"},
    "Information Technology": {"IT", "TELECOM"},
    "Healthcare": {"HEALTHCARE"},
    "Chemicals": {"CHEMICALS", "FMCG", "PAPER"},
    "Textiles": {"TEXTILES"},
    "Realty": {"REALTY", "CONSTRUCTION"},
    "Construction": {"CONSTRUCTION", "REALTY", "CEMENT"},
    "Power": {"POWER", "UTILITIES"},
    "Financial Services": {"FINANCE", "REALTY"},
    "Telecommunication": {"TELECOM", "MEDIA"},
    "Forest Materials": {"PAPER", "CHEMICALS"},
}


LABEL_ACCEPT["Capital Goods"] |= {"METALS"}


def _accept(label_text):
    if not label_text:
        return set()
    out = set(LABEL_ACCEPT.get(label_text, set()))
    out |= LABEL_ACCEPT.get(label_text.title(), set())
    return out


def _diversified_ok(prof):
    """A 'Diversified' label is right when the evidence really has 2+ businesses."""
    fams = {f for f, sh in prof["shares"].items() if sh >= 0.15}
    top = prof["text"].most_common(3)
    fams |= {f for f, n in top if n >= 3}
    return len(fams) >= 2


def _grade(fam, label_text, prof, level):
    """level in {'sector','industry'}; returns (grade, reason, error_type)."""
    if prof["thin"]:
        return "cannot_tell", "evidence too thin to establish the business", ""
    p = prof["primary"]
    if tx.is_generic(label_text) and level == "industry":
        if label_text.lower().startswith("diversified") and _diversified_ok(prof):
            fams = prof["shares"] or {f for f, _ in prof["text"].most_common(3)}
            return "correct", f"genuinely multi-business: {', '.join(sorted(fams))}", ""
        return "partly", f"too-generic label '{label_text}' (actual: {p.lower()})", "too_generic"
    if fam is None:
        return "partly", f"label '{label_text}' maps to no business family; actual {p.lower()}", "too_generic"

    if fam == p:
        return "correct", f"matches the dominant business ({p.lower()})", ""
    if label_text.lower().startswith("diversified") and _diversified_ok(prof):
        return "correct", f"genuinely multi-business: {', '.join(sorted(prof['shares'] or {f for f, _ in prof['text'].most_common(3)}))}", ""
    if level == "sector":
        accepted = _accept(label_text)
        match = ({p} | set(prof["alternates"])) & accepted
        ok_via_alt = all(
            prof["mode"] != "segments" or prof["shares"].get(f, 0.0) >= 0.15
            for f in match - {p})
        if match and (p in accepted or ok_via_alt):
            return "correct", f"'{label_text}' covers the {sorted(match)[0].lower()} business", ""
    if level == "sector" and tx.same_sector(fam, p):
        return "correct", f"same sector as the dominant {p.lower()} business", ""
    if level == "sector" and tx.SECTOR_PARENT.get(tx.coarse(p)) == tx.coarse(fam):
        return "correct", f"'{label_text}' is the parent sector of the {p.lower()} business", ""
    if level == "industry" and prof["mode"] == "text" and fam in prof["alternates"]:
        topn = max(1, prof["text"].get(p, 1))
        if prof["text"].get(fam, 0) >= 0.6 * topn:
            return "correct", f"business text supports both {p.lower()} and {fam.lower()}", ""
    share = prof["shares"].get(fam, 0.0)
    if share >= 0.40:
        return "correct", f"a co-dominant segment ({share * 100:.0f}% of segment revenue)", ""
    if _stale_for(prof, fam):
        return "stale", f"label fits an old/discontinued line; current business is {p.lower()}", "pivot_stale"
    if share > 0:
        err = "conglomerate" if len(prof["shares"]) >= 3 and prof["primary_share"] < 0.6 else "minor_segment"
        return "partly", f"only a minor segment ({share * 100:.0f}% of segment revenue)", err
    if fam in prof["alternates"]:
        return "partly", f"business text also covers {fam.lower()}, but the main business is {p.lower()}", "mixed_business"
    if level == "industry" and tx.same_sector(fam, p):
        return "partly", f"right sector, wrong industry (actual: {p.lower()})", "wrong_industry"
    return "wrong", f"no support in the FY2024-25 evidence (actual: {p.lower()})", "plainly_wrong"


BSE_MACRO = {
    "Industrials": {"CAPITAL_GOODS", "AUTO", "DEFENCE", "LOGISTICS", "PACKAGING",
                    "CONSTRUCTION", "SERVICES", "PAPER", "CEMENT", "CHEMICALS",
                    "TEXTILES", "METALS", "MINING"},
    "Materials": {"METALS", "CHEMICALS", "CEMENT", "PAPER", "PACKAGING", "MINING"},
    "Commodities": {"METALS", "CHEMICALS", "CEMENT", "PAPER", "OIL_GAS", "MINING"},
    "Energy": {"OIL_GAS", "POWER"},
    "Utilities": {"POWER", "UTILITIES", "OIL_GAS"},
    "Consumer Discretionary": {"AUTO", "RETAIL", "CONSUMER_DURABLES", "LEISURE",
                               "TEXTILES", "JEWELLERY", "MEDIA", "SERVICES",
                               "CONSUMER_SERVICES", "EDUCATION", "REALTY"},
    "Consumer Staples": {"FMCG", "AGRI", "RETAIL"},
    "Fast Moving Consumer Goods": {"FMCG", "AGRI"},
    "Consumer": {"FMCG", "RETAIL", "CONSUMER_DURABLES", "LEISURE", "TEXTILES",
                 "JEWELLERY", "EDUCATION", "AGRI", "CONSUMER_SERVICES"},
    "Financial Services": {"FINANCE", "REALTY"},
    "Healthcare": {"HEALTHCARE"},
    "Information Technology": {"IT"},
    "Telecommunication": {"TELECOM"},
    "Communication Services": {"MEDIA", "TELECOM"},
    "Real Estate": {"REALTY"},
    "Services": {"SERVICES", "LOGISTICS", "LEISURE", "EDUCATION"},
}


def grade_row(row, ev, bse, override=None):
    prof = build_profile(ev)
    override = override or {}
    if override.get("primary"):
        prof["primary"] = override["primary"]
        prof["mode"] = "manual"
        prof["thin"] = False
    out = {"profile": prof}

    nse_levels = (("sector", row.get("nse_sector") or ""),
                  ("industry", row.get("nse_industry") or ""))
    for level, label in nse_levels:
        if not label:
            g, why, err = "n/a", "no NSE label (BSE-only / unlabelled company)", ""
        else:
            g, why, err = _grade(tx.family_of_label(label), label, prof, level)
        out[f"nse_{level}_grade"], out[f"nse_{level}_reason"], out[f"nse_{level}_err"] = g, why, err

    bse_sector = (bse or {}).get("sector") or ""
    bse_industry = (bse or {}).get("industry") or (bse or {}).get("industry_new") or ""
    for level, label in (("sector", bse_sector), ("industry", bse_industry)):
        if not bse:
            g, why, err = "cannot_tell", "BSE header unavailable", "bse_unavailable"
        elif not label:
            g, why, err = "cannot_tell", "BSE header carries no label", "bse_unavailable"
        elif prof["thin"]:
            g, why, err = "cannot_tell", "evidence too thin to establish the business", ""
        elif level == "sector" and (tx.family_of_label(label) == prof["primary"]
                                    or (label.lower().startswith("diversified")
                                        and _diversified_ok(prof))
                                    or prof["primary"] in BSE_MACRO.get(label, set())):
            g, why, err = "correct", f"BSE macro '{label}' covers the {prof['primary'].lower()} business", ""
        else:
            g, why, err = _grade(tx.family_of_label(label), label, prof, level)
        out[f"bse_{level}_grade"], out[f"bse_{level}_reason"], out[f"bse_{level}_err"] = g, why, err

    errs = {out[k] for k in ("nse_sector_err", "nse_industry_err",
                             "bse_sector_err", "bse_industry_err") if out.get(k)}
    out["error_types"] = ";".join(sorted(errs))

    # supplementary: BSE `industry_new` is the mid-level field the audit wanted
    # as a sector filler; grade it at sector granularity for comparison.
    bse_new = (bse or {}).get("industry_new") or ""
    if not bse or not bse_new or prof["thin"]:
        out["bse_industry_new_grade"] = "cannot_tell" if not bse or prof["thin"] else "n/a"
    else:
        g2, _why, _e = _grade(tx.family_of_label(bse_new), bse_new, prof, "sector")
        out["bse_industry_new_grade"] = g2

    # manual adjudications (documented in overrides.json)
    for key, (grade, reason) in (override.get("grades") or {}).items():
        out[f"{key}_grade"] = grade
        out[f"{key}_reason"] = reason
        out[f"{key}_err"] = ""
    if override.get("grades"):
        errs = {out[k] for k in ("nse_sector_err", "nse_industry_err",
                                 "bse_sector_err", "bse_industry_err") if out.get(k)}
        out["error_types"] = ";".join(sorted(errs)) + (";manual" if not errs else ";manual")
    return out


def main():
    sample = json.loads((OUT / "sample.json").read_text(encoding="utf-8"))["rows"]
    evidence = json.loads((OUT / "evidence.json").read_text(encoding="utf-8"))
    bse_path = ROOT / ".tmp" / "bse_header_results.json"
    bse_all = json.loads(bse_path.read_text(encoding="utf-8")) if bse_path.exists() else {}
    ov_path = OUT / "overrides.json"
    overrides = json.loads(ov_path.read_text(encoding="utf-8")) if ov_path.exists() else {}

    out_rows = []
    for r in sample:
        ev = evidence.get(r["isin"], {})
        bse = bse_all.get(str(r["bse_code"]))
        g = grade_row(r, ev, bse, overrides.get(r["isin"]))
        prof = g.pop("profile")
        row = {
            "isin": r["isin"], "symbol": r["symbol"], "bse_code": r["bse_code"],
            "bucket": r["bucket"], "cap_tier": r["cap_tier"],
            "multi_segment": "yes" if r["multi_segment"] else "no",
            "nse_macro": r["nse_macro"], "nse_sector": r["nse_sector"],
            "nse_industry": r["nse_industry"], "nse_basic_industry": r["nse_basic_industry"],
            "bse_sector": (bse or {}).get("sector") or "",
            "bse_industry": (bse or {}).get("industry") or "",
            "bse_industry_new": (bse or {}).get("industry_new") or "",
            "segment_split": main_business_line(prof),
            "main_business": (prof["primary"] or "").lower(),
            "business_basis": prof["mode"],
            "evidence_refs": evidence_refs(ev),
            "evidence_chars": str(prof["chars"]),
            **g,
        }
        out_rows.append(row)

    fields = list(out_rows[0])
    with (OUT / "sector_label_pilot.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    (OUT / "grades.json").write_text(json.dumps(out_rows, indent=1, ensure_ascii=False),
                                     encoding="utf-8")

    for level in ("nse_sector", "nse_industry", "bse_sector", "bse_industry"):
        print(level, dict(Counter(r[f"{level}_grade"] for r in out_rows)))
    ct = sum(1 for r in out_rows
             if any(r[f"{x}_grade"] == "cannot_tell" for x in
                    ("nse_sector", "nse_industry", "bse_sector", "bse_industry")))
    print("rows with any cannot_tell:", ct)
    print("errors:", Counter(e for r in out_rows for e in r["error_types"].split(";") if e))
    print("bse resolved:", sum(1 for r in out_rows if r["bse_sector"]))
    print("wrote", len(out_rows), "rows")


if __name__ == "__main__":
    main()
