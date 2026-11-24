"""Order wins from exchange announcements (T-025, store-repair note R-003): ``order_win`` rows per filing.

A listed company discloses an order under Regulation 30 in the table SEBI prescribes, the same rows for every
company:

    Name of entity awarding the order(s)/contract(s)          -> awarder
    Significant terms and conditions ... awarded in brief     -> terms
    Whether ... awarded by domestic / international entity    -> domestic
    Nature of order(s)/contract(s)                            -> nature
    Time period by which the order(s)/contract(s) is to be executed   -> duration_text, duration_months
    Broad consideration or size of the order(s)/contract(s)   -> value_text, value_cr / value_usd_mn
    Whether promoter / promoter group ... have any interest   -> promoter_interest
    Whether ... would fall within related party transactions  -> related_party

``parse`` reads those rows by their printed labels (never by a company's wording), so it holds for any issuer; a
filing that discloses two orders gives two rows (``seq`` 1, 2).  Rules, each from a filing that broke the first
version on the ten measured stores:

* a filing counts as an order win when its headline, its subject line or its opening says an order, contract or
  letter of award was won, or when it carries the prescribed table.  A court, tax, tribunal or regulator "order"
  is not one, and neither is a results press release that mentions orders further down;
* the size comes from the table row; when that row is empty or unreadable, from the sentence that announces the
  win (``value_source`` says which: ``table``, ``body`` or ``title``).  A dollar size is kept as dollars;
* a field whose text runs into another label's words (scanned tables print labels and values out of order) is
  left empty: unsure means no value;
* an order with no printed size is still a row when the headline or the table says it was won: the win is a fact,
  the size is then ``NULL`` and ``value_text`` says what was printed;
* the same order filed twice on one day (the exchange feed repeats filings) is stored once.

The printed words sit beside every parsed figure (``value_text``, ``duration_text``, ``quote``): the figure is the
script's reading, the text is the filing's.  ``title_value_cr`` is the size in the exchange headline;
``title_mismatch`` marks a filing whose headline and body disagree (headlines are typed by hand and carry slips).
"""
from __future__ import annotations

import re
import sqlite3

RULE_TABLE = "order_table_v1"
RULE_TEXT = "order_text_v1"
PAGES = 4

# "order(s)/contract(s)" as printed, and as a scan prints it ("o\"der(s) / conh'act(s)")
# "order(s)/contract(s)" as printed, and as a scan prints it ("o\"der(s) / conh'act(s)").  The plural "s" is
# attached to its word or bracketed: a loose "\s?\(?s\)?" let the label swallow the first letter of the value
# that follows ("Order/Contract South Central Railway" -> "uth Central Railway", T-242 fresh4 #2/#6).
_OC = (r"o\S{0,2}der(?:\s*\(\s*s\s*\)|s)?\s*(?:/|or|and|&)?\s*"
       r"(?:con\S{2,5}act(?:\s*\(\s*s\s*\)|s)?[^\w\s]?)?")
LABELS = (
    ("awarder", re.compile(rf"name\s+of\s+(?:the\s+)?(?:entity|entities|customer|client|party)\s+awarding\s+(?:the\s+)?{_OC}", re.I)),
    ("terms", re.compile(rf"significant\s+terms\s+and\s+conditions\s+of\s+(?:the\s+)?{_OC}(?:\s*awarded)?(?:\s+in\s+brief)?", re.I)),
    ("domestic", re.compile(rf"whether\s+(?:the\s+)?{_OC}\s*(?:have|has)\s+been\s+awarded\s+by\s+(?:a\s+)?domestic\s*(?:/|or)?\s*"
                            r"international\s+entity", re.I)),
    ("nature", re.compile(rf"nature\s+of\s+(?:the\s+)?{_OC}", re.I)),
    ("domestic", re.compile(r"whether\s+domestic\s*(?:/|or)\s*international", re.I)),
    ("duration", re.compile(rf"time\s+period\s+(?:by|within)\s+which\s+(?:the\s+)?{_OC}\S?\s*(?:is|are)\s+to\s+be\s+executed", re.I)),
    ("value", re.compile(rf"broad\s+consideration\s+or\s+size\s+of\s+(?:the\s+)?{_OC}", re.I)),
    ("promoter_interest", re.compile(
        r"whether\s+(?:the\s+)?promoter\s*(?:/|or)?\s*promoter\s+group\s*(?:/|or)?\s*(?:group\s+)?compan(?:y|ies)\s+ha(?:ve|s)\s+any\s+"
        rf"interest\s+in\s+the\s+entity\s+that\s+awarded\s+the\s+{_OC}\??"
        r"(?:\s*if\s+yes\s*,?\s*nature\s+of\s+interest\s+and\s+details\s+thereof\.?)?", re.I)),
    ("related_party", re.compile(
        rf"whether\s+(?:the\s+)?{_OC}\s*would\s+fall\s+within\s+related\s+party\s+transactions?\??"
        r"(?:\s*if\s+yes\s*,?\s*whether\s+the\s+same\s+is\s+done\s+at\s+.?arm.?s\s+length.?\.?)?", re.I)),
)
_LABEL_WORDS = re.compile(r"significant\s+terms|whether\s+(?:the\s+)?(?:order|promoter|domestic)|nature\s+of\s+(?:the\s+)?o\S{0,2}der|"
                          r"time\s+period\s+by\s+which|broad\s+consideration|name\s+of\s+(?:the\s+)?entity", re.I)

_RUPEES = re.compile(r"(?:₹|`|\bRs\.?|\bINR|\bRupees)\s*([\d,]+(?:\.\d+)?)\s*/?-?\s*(crores?|cr\b\.?|lakhs?|lacs?|millions?|mn|"
                     r"billions?|bn)\b", re.I)
# a figure written out in rupees, at least ten lakh, with no unit word after it
_RUPEES_FULL = re.compile(r"(?:₹|`|\bRs\.?|\bINR|\bRupees)\s*(\d{1,3}(?:,\d{2,3}){2,}(?:\.\d+)?|\d{7,}(?:\.\d+)?)(?:\s*/-)?"
                          r"(?!\s*(?:crores?|cr\b|lakhs?|lacs?|millions?|mn|billions?|bn))", re.I)
_DOLLARS = re.compile(r"(?:\bUSD|\bUS\s?\$|\$)\s*([\d,]+(?:\.\d+)?)\s*(millions?|mn|billions?|bn)\b", re.I)
_TO_CRORE = {"crore": 1.0, "cr": 1.0, "lakh": 0.01, "lac": 0.01, "million": 0.1, "mn": 0.1, "billion": 100.0, "bn": 100.0}
_TO_USD_MN = {"million": 1.0, "mn": 1.0, "billion": 1000.0, "bn": 1000.0}
_DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*\)?\s*(?:\(\s*[a-z -]+\s*\)\s*)?(months?|years?|yrs?|weeks?|days?)\b", re.I)
_TO_MONTHS = {"month": 1.0, "year": 12.0, "yr": 12.0, "week": 12.0 / 52.0, "day": 12.0 / 365.0}

_NOUN = (r"(?:work\s+orders?|purchase\s+orders?|supply\s+orders?|orders?|sub-?\s?contracts?|contracts?|"
         r"letters?\s+of\s+(?:award|intent|acceptance)|LOAs?|LOIs?)")
_GAP = r"(?:[^.]|(?<=\bRs)\.|\.(?=\d)){0,120}?"          # within one sentence; "Rs. 385" and "1.5" do not end it
# an order was won: a winning verb with an order noun close by (never a bare "order")
WIN = re.compile(
    r"\b(?:secures?|secured|receives?|received|bags?|bagged|wins?|won|obtained|been\s+awarded|awarded\s+with|"
    r"emerged\s+as\s+(?:the\s+)?(?:L-?1|lowest)\s+bidder)\b" + _GAP + r"\b" + _NOUN + r"\b"
    r"|\b(?:receipt|award|bagging|receiving|winning|securing)(?:\s*/\s*\w+)?\s+of\s+(?:an?\s+|new\s+|the\s+|fresh\s+)*" + _NOUN + r"\b"
    r"|\bintimation\s+of\s+(?:work\s+)?orders?\s+received\b"
    r"|\b" + _NOUN + r"\s+(?:received|secured|bagged|won)\b", re.I)
# an "order" that is not a customer's: the word that binds to "order" names a court, a tax office or a regulator
NOT_A_WIN = re.compile(
    r"\b(?:court|tribunal|nclt|nclat|itat|cestat|sebi|adjudicat\w+|assessment|penalty|demand|tax|gst|customs|appellate|"
    r"regional\s+director|commissioner|stay|interim|final|impugned)\s+orders?\b"
    r"|\borders?\s+(?:passed|dated|under\s+section|of\s+the\s+hon|copy|regarding|giving\s+effect)"
    r"|\bvide\s+(?:its\s+)?order\b|\bshow\s+cause\b|\bletter\s+of\s+offer\b|\bincome[- ]tax\s+act\b"
    r"|\bhon.{0,3}ble\b|\barbitra\w+\b|\bliquidation\b|\bsanction\s+letter\b", re.I)
RESULTS_RELEASE = re.compile(r"\b(?:un-?audited|audited)\s+(?:standalone\s+|consolidated\s+)?financial\s+results\b|"
                             r"\bresults?\s+for\s+the\s+(?:quarter|half|year|nine)\b|\bQ[1-4]\s?FY\s?\d{2}\b", re.I)
_SUBJECT = re.compile(r"\bSub(?:ject)?\s*[:.\-–]\s*(.{0,260})", re.I)
_ROW_MARK = re.compile(r"(?:\s+|^)(?:\(?[a-zA-Z]\)|\(?\d{1,2}[.)]?|[A-Za-z]\.?|[ivx]{1,4}[.)])\s*$")
_LEAD_JUNK = re.compile(r"^[\s:;\-–|?.,)]+")
_TAIL = re.compile(r"\b(?:this\s+is\s+for\s+your\s+(?:kind\s+)?information|kindly\s+take|you\s+are\s+requested|thanking\s+you|"
                   r"yours\s+(?:faithfully|sincerely|truly)|for\s+and\s+on\s+behalf|we\s+request\s+you|the\s+above\s+may\s+kindly|"
                   r"this\s+letter\s+of|the\s+(?:LOA|LOI|order)\s+has\s+been\s+received)\b", re.I)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _unit(word: str) -> str:
    return word.lower().rstrip(".").rstrip("s")


def money_cr(text: str) -> float | None:
    """The first rupee amount of ``text``, in crore: ``Rs. 495.86 Crores`` or a full figure (``Rs. 28,59,32,004/-``)."""
    unit = _RUPEES.search(text or "")
    full = _RUPEES_FULL.search(text or "")
    try:
        if full and (not unit or full.start() < unit.start()):
            return round(float(full[1].replace(",", "")) / 1e7, 4)
        if unit:
            return round(float(unit[1].replace(",", "")) * _TO_CRORE[_unit(unit[2])], 4)
    except (KeyError, ValueError):
        return None
    return None


def money_usd_mn(text: str) -> float | None:
    """The first dollar amount of ``text``, in USD million."""
    match = _DOLLARS.search(text or "")
    if not match:
        return None
    try:
        return round(float(match[1].replace(",", "")) * _TO_USD_MN[_unit(match[2])], 4)
    except (KeyError, ValueError):
        return None


def months(text: str) -> float | None:
    """The duration ``text`` states, in months; ``None`` when it states none or more than one (a start-up period,
    a build period and a licence term in one cell: the words are kept, no single figure is right)."""
    found = {round(float(m[1]) * _TO_MONTHS[_unit(m[2])], 1) for m in _DURATION.finditer(text or "")}
    return found.pop() if len(found) == 1 else None


def _label_hits(flat: str) -> list[tuple[int, int, str]]:
    hits = sorted((m.start(), m.end(), field) for field, rx in LABELS for m in rx.finditer(flat))
    kept: list[tuple[int, int, str]] = []
    for hit in hits:                                   # overlapping label matches: the earliest wins
        if kept and hit[0] < kept[-1][1]:
            continue
        kept.append(hit)
    return kept


def tables(text: str) -> list[dict[str, str]]:
    """One ``{field: printed value}`` per order the prescribed rows disclose (a second awarder row starts a second
    order); a label's value runs to the next label, and a value that swallowed a label is dropped."""
    flat = _flat(text)
    hits = _label_hits(flat)
    orders: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for i, (_start, end, field) in enumerate(hits):
        stop = hits[i + 1][0] if i + 1 < len(hits) else min(len(flat), end + 300)
        value = flat[end:stop]
        tail = _TAIL.search(value)
        if tail:
            value = value[: tail.start()]
        value = _ROW_MARK.sub("", _LEAD_JUNK.sub("", value)).strip(" :;-–|")
        if field == "awarder" and "awarder" in current:
            orders.append(current)
            current = {}
        if value and field not in current and not _LABEL_WORDS.search(value):
            current[field] = value[:500]
    if current:
        orders.append(current)
    return [o for o in orders if len(o) >= 2]


def _opening(title: str, flat: str) -> tuple[str, str]:
    """(where the win is said, the words): the headline, the subject line, or the opening of the letter."""
    head = _flat(title)
    if WIN.search(head) and not NOT_A_WIN.search(head):
        return "title", head
    subject = _SUBJECT.search(flat)
    if subject and WIN.search(subject[1]) and not NOT_A_WIN.search(subject[1]):
        return "subject", subject[1]
    start = subject.end() if subject else 0
    body = flat[start: start + 900]
    win = WIN.search(body)
    if win:
        sentence = body[max(0, win.start() - 160): win.end() + 260]
        if not NOT_A_WIN.search(sentence) and not RESULTS_RELEASE.search(flat[:700]) and not RESULTS_RELEASE.search(head):
            return "body", sentence
    return "", ""


def _yes_no(value: str | None) -> str | None:
    if not value:
        return None
    if re.match(r"\W*yes\b", value, re.I):
        return "yes"
    if re.match(r"\W*(?:no\b|nil\b|none\b|not\s+applicable|n\.?\s?a\.?\b)", value, re.I):
        return "no"
    return None


def parse(title: str, text: str) -> list[dict]:
    """The order-win records of one filing (headline + first pages); empty when it is not an order win."""
    flat = _flat(text)
    head = _flat(title)
    if NOT_A_WIN.search(head) and not WIN.search(head):
        return []
    where, words = _opening(title, flat)
    found = tables(text)
    if not where and not found:
        return []
    if found and not where and NOT_A_WIN.search(flat[:900]):
        return []
    # the sentence that announces the win: the first one that also prints a size, else the first one
    leads = [flat[max(0, m.start() - 160): m.end() + 300] for m in WIN.finditer(flat[:2500])]
    lead = next((s for s in leads if money_cr(s) is not None or money_usd_mn(s) is not None),
                leads[0] if leads else (words or head))
    title_value = money_cr(head)
    records = []
    for seq, fields in enumerate(found or [{}], 1):
        value_text = fields.get("value")
        value, usd, source = money_cr(value_text or ""), money_usd_mn(value_text or ""), "table"
        if value is None and usd is None and len(found) <= 1:
            for origin, words_here in (("body", lead), ("title", head)):
                value, usd = money_cr(words_here), money_usd_mn(words_here)
                if value is not None or usd is not None:
                    source = origin
                    printed = (_RUPEES.search(words_here) or _RUPEES_FULL.search(words_here)
                               or _DOLLARS.search(words_here))
                    value_text = value_text or (printed[0] if printed else None)
                    break
            else:
                source = None
        if not fields and where == "body" and value is None and usd is None:
            return []                                  # an opening sentence alone, with no size: not sure, no row
        domestic = fields.get("domestic")
        duration_text = fields.get("duration")
        records.append({
            "seq": seq, "awarder": fields.get("awarder"), "nature": fields.get("nature"), "terms": fields.get("terms"),
            "domestic": (None if not domestic else "international" if re.match(r"\W*international", domestic, re.I)
                         else "domestic" if re.match(r"\W*domestic", domestic, re.I) else None),
            "value_cr": value, "value_usd_mn": usd, "value_text": value_text, "value_source": source,
            "duration_months": months(duration_text or ""), "duration_text": duration_text,
            "promoter_interest": _yes_no(fields.get("promoter_interest")),
            "related_party": _yes_no(fields.get("related_party")),
            "title_value_cr": title_value, "title_mismatch": 0, "quote": lead[:460],
            "extractor_rule": RULE_TABLE if fields else RULE_TEXT,
        })
    total = sum(r["value_cr"] for r in records if r["value_cr"] is not None)
    if title_value is not None and total and abs(total - title_value) > 0.005 * max(1.0, title_value):
        for record in records:
            record["title_mismatch"] = 1
    return records


COLUMNS = ("symbol", "isin", "announced", "doc_key", "page", "seq", "awarder", "nature", "terms", "domestic", "value_cr",
           "value_usd_mn", "value_text", "value_source", "duration_months", "duration_text", "promoter_interest",
           "related_party", "title_value_cr", "title_mismatch", "title", "quote", "known_at", "known_at_source",
           "extractor_rule")


def build(conn: sqlite3.Connection) -> dict:
    """Rewrite ``order_win`` from every announcement and press release the store holds."""
    conn.execute("DELETE FROM order_win")
    docs = conn.execute(
        "SELECT doc_key, symbol, isin, title, filing_date, COALESCE(known_at, filing_date) FROM doc "
        "WHERE doc_type IN ('announcement','press_release') ORDER BY COALESCE(known_at, filing_date), doc_key").fetchall()
    rows, seen, stats = [], set(), {"filings": 0, "duplicates": 0, RULE_TABLE: 0, RULE_TEXT: 0, "no_value": 0,
                                    "title_mismatch": 0}
    for doc_key, symbol, isin, title, filing_date, known_at in docs:
        pages = conn.execute("SELECT page, text FROM doc_page WHERE doc_key=? ORDER BY page LIMIT ?",
                             (doc_key, PAGES)).fetchall()
        records = parse(title or "", "\n".join(p[1] or "" for p in pages))
        if not records:
            continue
        same = (symbol, filing_date, tuple((r["value_cr"], r["value_usd_mn"], r["awarder"]) for r in records))
        if same in seen and any(r["value_cr"] is not None or r["value_usd_mn"] is not None for r in records):
            stats["duplicates"] += 1
            continue
        seen.add(same)
        stats["filings"] += 1
        for r in records:
            stats[r["extractor_rule"]] += 1
            stats["no_value"] += int(r["value_cr"] is None and r["value_usd_mn"] is None)
            stats["title_mismatch"] += r["title_mismatch"]
            rows.append((symbol, isin, filing_date, doc_key, int(pages[0][0]) if pages else 1, r["seq"], r["awarder"],
                         r["nature"], r["terms"], r["domestic"], r["value_cr"], r["value_usd_mn"], r["value_text"],
                         r["value_source"], r["duration_months"], r["duration_text"], r["promoter_interest"],
                         r["related_party"], r["title_value_cr"], r["title_mismatch"], title, r["quote"], known_at,
                         "doc.known_at", r["extractor_rule"]))
    conn.executemany(f"INSERT INTO order_win ({', '.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})", rows)
    conn.commit()
    return {"rows": len(rows), **stats}
