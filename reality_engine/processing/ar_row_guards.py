"""Guards for the annual-report row clean-up pass (tasks/AR_INGESTION_PROTOCOL.md, LLM stage a).

A free model gets CPU-parsed table rows and returns a cleaner label, unit and period for each. It fixes most parser
errors, but in the 2026-10-12 test (tasks/ar_study/free_test/FINDINGS.md) it also introduced three kinds of
corruption that must never reach storage:
  1. currency scale changed (a crore table relabelled "rupees"): the value would be off by 10^7;
  2. year changed against the column header ("As at 31/03/2023" turned into 2024);
  3. label swapped for another row's label ("Turnover" -> "Reserves & Surplus").
Each guard accepts the model's change only when the row's own text (label, column header, page header) supports it;
otherwise the parser's field stays and a flag records the rejected change. The value is never touched here.
"""
import re

CURRENCY = {"rupees", "thousand", "lakh", "crore", "million", "billion"}
NON_CURRENCY = {"percent", "count", "shares", "tonnes", "m3", "kwh", "gj", "days", "ratio", "times"}
_PARSER_UNIT = {"%": "percent", "lakhs": "lakh", "crores": "crore", "cr": "crore", "mn": "million", "rs": "rupees",
                "inr": "rupees", "rupee": "rupees", "number": "count", "nos": "count"}

# words in a row's text that justify a non-currency unit
_UNIT_EVIDENCE = {
    "percent": r"%|percent|per cent",
    "count": r"\bno\.|\bnos?\b|number|count|\bheadcount|employees|workers|units\b|quantity|\bqty\b|options\b",
    "shares": r"\bshares?\b|no\. of shares",
    "tonnes": r"\btonnes?\b|\btons?\b|\bmt\b|\bmtpa\b",
    "m3": r"\bm3\b|m³|cubic|kl\b|kilolit",
    "kwh": r"\bkwh\b|\bmwh\b|\bgwh\b",
    "gj": r"\bgj\b|\btj\b|joule",
    "days": r"\bdays?\b",
    "ratio": r"\bratio\b|\bx\b|:1\b",
    "times": r"\btimes\b|\bx\b|\bratio\b",
}
# currency-scale words in a header
_SCALE_EVIDENCE = {
    "crore": r"crore|\bcr\b",
    "lakh": r"lakh|\blacs?\b",
    "million": r"million|\bmn\b",
    "billion": r"billion|\bbn\b",
    "thousand": r"thousand|[‘’']000|\b000s\b",
}
_CURRENCY_MARK = r"₹|`|\brs\.?|\binr\b|rupees?"

GENERIC = {"other", "others", "total", "assets", "asset", "liabilities", "liability", "year", "years", "the", "and",
           "for", "from", "with", "under", "note", "notes", "refer", "below", "above", "march", "end", "beginning",
           "balance", "amount", "current", "non"}


def norm_unit(u):
    if u is None:
        return None
    u = str(u).strip().lower()
    return _PARSER_UNIT.get(u, u)


def guard_unit(parser_unit, model_unit, evidence_text):
    """Model unit, or the parser's when the change is not supported by the row's own text."""
    p, m = norm_unit(parser_unit), norm_unit(model_unit)
    if not m or m == p:
        return p, None
    t = (evidence_text or "").lower()
    if m in NON_CURRENCY:
        if re.search(_UNIT_EVIDENCE[m], t):
            return m, None
        return p, f"unit {m!r} rejected: no evidence in label/header"
    if m in CURRENCY:
        if p is None:
            return m, None
        if m == "rupees":   # absolute rupees: a currency mark with no scale word anywhere in the row's text
            if re.search(_CURRENCY_MARK, t) and not any(re.search(rx, t) for rx in _SCALE_EVIDENCE.values()):
                return m, None
            return p, "unit 'rupees' rejected: header carries a scale or no currency mark"
        if re.search(_SCALE_EVIDENCE[m], t):
            return m, None
        return p, f"unit {m!r} rejected: scale not stated in label/header"
    return p, f"unit {m!r} rejected: unknown unit"


def fiscal_years(text):
    """Fiscal year-ends (as 'YYYY') mentioned in a header: 2023, 31/03/2023, 2022-23, FY 2023-24, FY24."""
    t = text or ""
    out = set()
    for a, b in re.findall(r"\b(20\d\d)\s*[-–/]\s*(\d\d)\b(?![/\d])", t):
        out.add(a[:2] + b)
    for y in re.findall(r"(?<![\d])(20\d\d)(?![\d])", t):
        out.add(y)
    for y in re.findall(r"\bFY\s*'?(\d\d)\b", t, re.I):
        out.add("20" + y)
    # "2022-23" also matched its start year by the plain rule: drop it unless written alone elsewhere
    for a, b in re.findall(r"\b(20\d\d)\s*[-–]\s*(\d\d)\b", t):
        if len(re.findall(rf"(?<![\d]){a}(?![\d])", t)) == 1:
            out.discard(a)
    return out


def guard_period(parser_period, model_period, header_text):
    """Model period, or the parser's when the column header does not support the change."""
    p = (parser_period or "").rstrip("*") or None
    m = (model_period or "").strip() or None
    if m in ("null", "None"):
        m = None
    if m == p or m is None:
        return p, None
    years = fiscal_years(header_text)
    if p is None:
        return (m, None) if m[:4] in years else (p, f"period {m} rejected: year not in header")
    if m[:4] in years and p[:4] not in years:
        return m, None
    return p, f"period {m} rejected: header supports {sorted(years) or 'no year'}"


def _words(s):
    return [w for w in re.findall(r"[a-z]{3,}", (s or "").lower())]


def guard_label(parser_label, model_label, min_share=0.6, column=""):
    """Model label, or the parser's when it does not keep most of the parser label's own words (a swapped row).
    Only the first 8 words of the parser label count (later words are often a merged heading). A label built only
    from words of the row's own label and column header is a trim (footer or heading junk removed), never a swap."""
    if not model_label or model_label == parser_label:
        return parser_label, None
    if set(_words(model_label)) <= set(_words(parser_label)) | set(_words(column)):
        return model_label, None
    own = re.split(r"\bnote\s*\d+\s*:", parser_label or "", flags=re.I)[0]   # drop a merged "Note 49: ..." heading
    first = _words(own)[:8]
    core = [w for w in first if w not in GENERIC]
    if len(core) < 2:   # a label of mostly generic words ("Balance at the end of the year"): judge on all of them
        core = first
    if not core:
        return model_label, None
    have = set(_words(model_label))
    share = sum(w in have for w in core) / len(core)
    if share >= min_share:
        return model_label, None
    return parser_label, f"label {model_label!r} rejected: shares {share:.0%} of the row's own words"


def apply(row, answer, page_header="", verified=True):
    """Merge one model answer into a parser row. Returns (cleaned row, flags). The value is copied, never changed."""
    # the model's own label is not evidence (it could invent "No. of shares" to justify a unit)
    evidence = " ".join(str(x or "") for x in (row.get("label"), row.get("column"), page_header))
    header = " ".join(str(x or "") for x in (row.get("column"), row.get("label")))
    out, flags = dict(row), []
    out["label_clean"], f = guard_label(row.get("label"), answer.get("label"), column=row.get("column") or ""); flags.append(f)
    out["unit"], f = guard_unit(row.get("unit"), answer.get("unit"), evidence); flags.append(f)
    out["period"], f = guard_period(row.get("period"), answer.get("period_end"), header); flags.append(f)
    keep = answer.get("keep", True)
    if keep is False and verified:
        flags.append("drop ignored: row is verified")
        keep = True
    out["keep"] = bool(keep)   # scope stays as the section set it; the model may not change it
    return out, [f for f in flags if f]
