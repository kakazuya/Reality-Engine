"""Verified-vs-inferred flags for DeepSeek concall facts + our own guidance direction (2026-10-18).

DeepSeek copies numbers and quotes faithfully (97.5% of numbers sit inside their own quote) but labels such as guidance
direction / period / basis are its interpretation (direction backed by a comparison word in its own quote only 23% of
the time). This writes cc_item_checks (one row per cc_items row; no API calls, re-runnable):
  value_in_quote       every number of the value is inside the item's own quote
  period_in_quote      the quote itself names a time (FY / year / quarter / month ...)
  direction_supported  model said raised/lowered/maintained AND the quote has a comparison word
  speaker_role         management / analyst / moderator / unknown: speaker tag before the quote in the transcript,
                       management = matches a participant name the model listed for the call
  metric_key           normalised metric (revenue_growth, ebitda_margin, capex, ...) or NULL
  value_low/high, value_is_pct   parsed number or range
  item_fy              fiscal year the item refers to (from its period text)
  computed_direction   OUR direction for guidance: vs the same company's latest EARLIER call (filed before this one)
                       with the same metric_key and item_fy: raised / lowered / maintained (+-2% of the midpoint),
                       'new' when no earlier call has it, 'no_prior_call' when we hold no earlier call of that company.
                       Point-in-time: only filings public before this call are compared.

    python -m reality_engine.scripts.concall_facts_checks
"""
import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

from reality_engine.scripts.concall_period import parse_period

ROOT = Path(__file__).resolve().parents[2]
FACTS = ROOT / "reality_engine/data/concall_facts.db"
MAIN = ROOT / "reality_engine/data/equity_intelligence.db"
DDL = """CREATE TABLE IF NOT EXISTS cc_item_checks (doc_id INTEGER, list_name TEXT, idx INTEGER,
    value_in_quote INTEGER, period_in_quote INTEGER, direction_supported INTEGER, speaker_role TEXT, speaker TEXT,
    metric_key TEXT, value_low REAL, value_high REAL, value_is_pct INTEGER, item_fy INTEGER,
    computed_direction TEXT, prev_doc_id INTEGER, prev_value_mid REAL, checked_at TEXT,
    PRIMARY KEY (doc_id, list_name, idx))"""
METRICS = [  # first match wins; order matters (margin before revenue, growth before level)
    ("ebitda_margin", r"ebitda.*margin|operating margin|ebit margin"), ("gross_margin", r"gross margin"),
    ("pat_margin", r"pat margin|net margin|profit margin"), ("margin", r"^margins?$|margin"),
    ("revenue_growth", r"(revenue|top ?line|sales|turnover|income).*(growth|cagr)|growth.*(revenue|top ?line|sales)"),
    ("revenue", r"revenue|top ?line|sales|turnover"), ("ebitda_growth", r"ebitda.*growth"), ("ebitda", r"ebitda"),
    ("pat_growth", r"(pat|profit).*growth|earnings growth"), ("pat", r"\bpat\b|net profit|profit after tax"),
    ("volume_growth", r"volume.*growth"), ("volume", r"volume"), ("capex", r"capex|capital expenditure"),
    ("order_inflow", r"order inflow|order intake"), ("order_book", r"order ?book"),
    ("credit_cost", r"credit cost"), ("nim", r"\bnim\b|net interest margin"), ("aum_growth", r"aum.*growth|loan book growth|advances growth"),
    ("aum", r"\baum\b|loan book|advances"), ("roe", r"\broe\b"), ("roa", r"\broa\b"), ("roce", r"\broce\b"),
    ("utilisation", r"utili[sz]ation"), ("tax_rate", r"tax rate"), ("working_capital_days", r"working capital"),
]
TIME = re.compile(r"\bfy|\b20\d\d\b|quarter|\bq[1-4]\b|\bh[12]\b|year|month|annual|next \d|by \d", re.I)
CMP = re.compile(r"maintain|reiterat|revis|rais|upgrad|lower|cut|earlier|previous|retain|same as|reaffirm|unchanged|"
                 r"stick|increase our guidance|reduce our guidance|from .* to ", re.I)
SPEAKER = re.compile(r"(?m)^\s*([A-Z][A-Za-z.'\- ]{2,60}?)\s*:")


def unit_class(v):
    t = (v or "").lower()
    if re.search(r"bps|basis point", t): return "bps"
    if "%" in t or "per cent" in t or "percent" in t: return "pct"
    if re.search(r"\bcr\b|crore", t): return "crore"
    if re.search(r"\bmn\b|million", t): return "mn"
    if re.search(r"\bbn\b|billion", t): return "bn"
    if re.search(r"\blakh|\blac", t): return "lakh"
    return "num"


def digits(s):
    return [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", s or "") if re.search(r"\d", x)]


RANGE = re.compile(r"(\d[\d,]*\.?\d*)\s*%?\s*(?:crores?|cr)?\s*(?:-|–|—|to|and)\s*(?:rs\.?|inr|₹)?\s*(\d[\d,]*\.?\d*)", re.I)


def value_range(v):
    """(low, high) of a value: an explicit range 'X to Y' / 'X-Y', else the first number ('80% plus/minus 5%' -> 80,
    not the mean of 80 and 5, which made MTAR's guidance look lowered on 2026-10-19)"""
    # years and period labels are not values ('FY27 15%' -> 15)
    t = re.sub(r"\bFY\s*'?\d{2,4}(?:\s*-\s*\d{2})?\b|\b(?:19|20)\d{2}\b|\b[QH][1-4]\b", " ", v or "", flags=re.I)
    m = RANGE.search(t)
    if m:
        a, b = float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
        if b >= a:
            return a, b
    d = digits(t)
    return (d[0], d[0]) if d else (None, None)


def norm(s):
    return " ".join(re.findall(r"[a-z0-9%.]+", (s or "").lower()))


def metric_key(m):
    t = (m or "").lower()
    for k, rx in METRICS:
        if re.search(rx, t):
            return k
    return None


def speaker_of(text, ntext_index, quote, participants, recur, analysts):
    """speaker tag nearest before the quote; role by participant surname match"""
    q = norm(quote)[:80]
    if not q:
        return None, "unknown"
    nt, idx_map = ntext_index
    pos = nt.find(q)
    if pos < 0:
        return None, "unknown"
    raw_pos = idx_map[pos]
    # a speaker tag looks like a name (<= 5 capitalised words) and recurs in the call; one-off 'tags' are section
    # headings ('Disclaimer:', 'Now coming to the consolidated financial performance:'), which the first version took
    # for speakers and so marked management facts as analyst words
    tags = [m for m in SPEAKER.finditer(text, 0, raw_pos) if _is_name(m.group(1)) and recur.get(m.group(1).strip(), 0) >= 2]
    if not tags:
        return None, "unknown"
    name = tags[-1].group(1).strip()
    low = name.lower()
    if "moderator" in low or "operator" in low:
        return name, "unknown"   # the moderator hands over; the speaker's own tag was missed
    full = _full(name)
    if full in analysts:
        return name, "analyst"     # introduced by the moderator as a questioner (full name, not a shared surname)
    mgmt = {_full((p.get("name") or "") if isinstance(p, dict) else str(p).split(",")[0]) for p in participants}
    if full in mgmt or any(m and (m in full or full in m) for m in mgmt if len(m.split()) >= 2) or "management" in low:
        return name, "management"
    return name, "unknown"     # neither a listed participant nor an introduced analyst (headers, unlisted executives)


def _full(n):
    w = [x for x in re.findall(r"[a-z]+", (n or "").lower()) if x not in {"mr", "ms", "mrs", "shri", "dr", "sir"}]
    return " ".join(w)


INTRO = re.compile(r"(?:question|line|comes?|is) from (?:the line of )?(?:Mr\.?|Ms\.?|Mrs\.?)?\s*([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,3})", re.I)


def analyst_names(text):
    """full names of people the moderator introduced as questioners ('next question is from the line of X from Y').
    Full names only: surnames like Sharma / Shah / Jain are shared by analysts and executives (2026-10-19 sample)."""
    out = set()
    for m in INTRO.finditer(text):
        n = _full(re.split(r"\s+(?:from|of|with)\s+", m.group(1), flags=re.I)[0])
        if len(n.split()) >= 2:
            out.add(n)
    return out


LINK = {"of", "and", "the", "from", "&", "-", "for", "on", "behalf", "de", "da"}


def _is_name(tag):
    w = tag.strip().replace(".", " ").split()
    return 1 <= len(w) <= 5 and all(x[0].isupper() or x.lower() in LINK for x in w)


def recurring_tags(text):
    out = {}
    for m in SPEAKER.finditer(text):
        k = m.group(1).strip(); out[k] = out.get(k, 0) + 1
    return out


def norm_index(text):
    """normalised text plus a map from normalised positions back to raw positions"""
    out, idx = [], []
    prev_space = True
    for i, ch in enumerate(text.lower()):
        if ch.isalnum() or ch in "%.":
            out.append(ch); idx.append(i); prev_space = False
        elif not prev_space:
            out.append(" "); idx.append(i); prev_space = True
    return "".join(out), idx


def main():
    out = sqlite3.connect(FACTS, timeout=300)
    out.execute(DDL)
    main_db = sqlite3.connect(f"file:{MAIN}?mode=ro", uri=True)
    docs = out.execute("SELECT doc_id, isin, filed_at, raw_json FROM cc_docs WHERE status='ok' ORDER BY filed_at").fetchall()
    import pymupdf
    rows, n = [], 0
    for doc_id, isin, filed, raw in docs:
        participants = json.loads(raw).get("participants") or []
        path = main_db.execute("SELECT local_file_path FROM corporate_documents WHERE id=?", (doc_id,)).fetchone()[0]
        with pymupdf.open(path) as d:
            text = "\n".join(p.get_text() for p in d)
        ni = norm_index(text)
        recur = recurring_tags(text)
        analysts = analyst_names(text)
        for ln, idx, value, period, direction, quote, metric in out.execute(
                "SELECT list_name, idx, value, period, direction, quote, metric FROM cc_items WHERE doc_id=?", (doc_id,)):
            vd, qd = digits(value), digits(quote)
            vin = int(bool(vd) and all(any(abs(v - x) < 1e-9 for x in qd) for v in vd)) if vd else None
            pin = int(bool(TIME.search(quote or ""))) if quote else 0
            dsup = (int(bool(CMP.search(quote or ""))) if direction in ("raised", "lowered", "maintained") else None)
            spk, role = speaker_of(text, ni, quote, participants, recur, analysts)
            mk = metric_key(metric) if ln in ("guidance", "key_numbers", "capex", "order_book") else None
            lo, hi = value_range(value)
            pfy = parse_period(period)
            rows.append([doc_id, ln, idx, vin, pin, dsup, role, spk, mk, lo, hi, int("%" in (value or "")),
                         pfy[1] if pfy else None, None, None, None, dt.datetime.now().isoformat(timespec="seconds")])
            n += 1
    with out:
        out.execute("DELETE FROM cc_item_checks")
        out.executemany("INSERT INTO cc_item_checks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    # our own guidance direction, point-in-time: compare with the latest EARLIER call of the same company
    g = out.execute("""SELECT c.doc_id, c.idx, d.isin, d.filed_at, c.metric_key, c.item_fy, c.value_low, c.value_high, i.value
                       FROM cc_item_checks c JOIN cc_docs d ON d.doc_id=c.doc_id
                       JOIN cc_items i ON i.doc_id=c.doc_id AND i.list_name=c.list_name AND i.idx=c.idx
                       WHERE c.list_name='guidance' AND c.metric_key IS NOT NULL AND c.item_fy IS NOT NULL
                         AND c.value_low IS NOT NULL ORDER BY d.filed_at""").fetchall()
    calls = {}
    for doc_id, isin, filed in out.execute("SELECT doc_id, isin, filed_at FROM cc_docs WHERE status='ok'"):
        calls.setdefault(isin, []).append((filed, doc_id))
    seen = {}   # (isin, metric, fy, is_pct) -> list of (filed, doc_id, mid)
    upd = []
    for doc_id, idx, isin, filed, mk, fy, lo, hi, value in g:
        # compare like with like only: same unit class, and within 2x (2026-10-19 sample: 'Rs 8.5-9 crores' segment
        # figure vs '1,800-1,900' total, and '150 bps' expansion vs a '15%' level, were read as 'lowered'/'raised')
        key = (isin, mk, fy, unit_class(value)); mid = (lo + hi) / 2
        prev = [p for p in seen.get(key, []) if p[0] < filed]
        if prev and prev[-1][2] and not (0.5 <= mid / prev[-1][2] <= 2):
            upd.append(("not_comparable", prev[-1][1], prev[-1][2], doc_id, "guidance", idx))
        elif prev:
            pf, pdoc, pmid = prev[-1]
            ch = (mid - pmid) / abs(pmid) if pmid else 0
            dirn = "raised" if ch > 0.02 else "lowered" if ch < -0.02 else "maintained"
            upd.append((dirn, pdoc, pmid, doc_id, "guidance", idx))
        else:
            earlier = any(f < filed for f, _ in calls.get(isin, []))
            upd.append(("new" if earlier else "no_prior_call", None, None, doc_id, "guidance", idx))
        seen.setdefault(key, []).append((filed, doc_id, mid))
    with out:
        out.executemany("UPDATE cc_item_checks SET computed_direction=?, prev_doc_id=?, prev_value_mid=? "
                        "WHERE doc_id=? AND list_name=? AND idx=?", upd)
    s = lambda q: out.execute(q).fetchone()
    print(f"items checked {n} over {len(docs)} calls")
    print("value_in_quote  ", s("SELECT SUM(value_in_quote), COUNT(value_in_quote) FROM cc_item_checks"))
    print("period_in_quote (guidance)", s("SELECT SUM(period_in_quote), COUNT(*) FROM cc_item_checks WHERE list_name='guidance'"))
    print("direction_supported", s("SELECT SUM(direction_supported), COUNT(direction_supported) FROM cc_item_checks"))
    print("speaker_role", out.execute("SELECT speaker_role, COUNT(*) FROM cc_item_checks GROUP BY 1").fetchall())
    print("metric_key on guidance", s("SELECT COUNT(metric_key), COUNT(*) FROM cc_item_checks WHERE list_name='guidance'"))
    print("computed_direction", out.execute("SELECT computed_direction, COUNT(*) FROM cc_item_checks WHERE computed_direction IS NOT NULL GROUP BY 1").fetchall())


if __name__ == "__main__":
    main()
