"""Rule-based earnings-call statement extractor -> table transcript_statement (T-049 B). No model, no OCR, no network.

CLI: python -m reality_engine.pilot3.transcripts --out <db> [--symbols KEC,BAJFINANCE,HINDALCO] [--sandbox-root DIR]

One row per sentence spoken by management (md/ceo/cfo/mgmt/ir) in a held earnings-call transcript: speaker, role,
section (prepared|qa), topic tags from lexicon/topics.yaml, numbers with unit and period, the exact sentence.
Analysts, the moderator and boilerplate headers/footers are not stored. A sentence that is cut by a page break is
stored on the page where it starts with is_fragment=1; quote is always a literal slice of that page's text.
Page text comes from doc_text (method script_text); pages marked needs_ocr are skipped and counted.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

import yaml

from .kpi import COMPANIES, LEX_DIR, SANDBOX_ROOT, VAL_RX, _UNIT_BY_SUFFIX, parse_periods, to_float, _norm_cur

SCHEMA = """
CREATE TABLE IF NOT EXISTS transcript_statement (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL, isin TEXT, doc_key TEXT NOT NULL, call_date TEXT, call_period TEXT, page INTEGER NOT NULL,
  seq INTEGER NOT NULL, speaker TEXT NOT NULL, role TEXT NOT NULL, section TEXT NOT NULL,
  topics TEXT NOT NULL, period_discussed TEXT, period_source TEXT, numbers_json TEXT NOT NULL,
  statement TEXT NOT NULL, quote TEXT NOT NULL, is_fragment INTEGER NOT NULL DEFAULT 0,
  known_at TEXT, known_at_source TEXT, extractor_rule TEXT NOT NULL,
  UNIQUE(symbol, doc_key, page, seq)
);
CREATE INDEX IF NOT EXISTS ix_ts_sym_call ON transcript_statement(symbol, call_date);
"""

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
SPEAKER_RX = re.compile(r"^[ 	]*([A-Z][A-Za-z.'’\-]+(?: [A-Za-z.'’\-]+){0,4}):(?=[ 	]|$)", re.M)
SPEAKER_MID_RX = re.compile(r"(?<=[.?!] )([A-Z][A-Za-z.'’\-]+(?: [A-Z][A-Za-z.'’\-]+){1,3}):(?=[ 	]|$)", re.M)
PAGE_NO_RX = re.compile(r"^[ \t]*Page \d+ of \d+[ \t]*$", re.M)
DATE_LINE_RX = re.compile(r"^[ \t]*(?:" + MONTHS + r") \d{1,2}, \d{4}[ \t]*$", re.M)
CALL_DATE_RX = re.compile(r"(" + MONTHS + r") (\d{1,2}), (\d{4})")
ABBR = ("Mr", "Ms", "Mrs", "Dr", "Rs", "No", "vs", "Inc", "Ltd", "approx", "Sr", "Jr", "St", "Co", "Corp", "etc", "i.e", "e.g", "FY", "Q")
SENT_END_RX = re.compile(r"(?<=[.?!])[\"”’')]*\s+(?=[\"“‘'(A-Z0-9₹$])")
NOT_SPEAKERS = ("Corporate", "Registered", "Email", "Website", "Phone", "Tel", "Note", "Disclaimer", "Source", "CIN", "Page", "Symbol", "Scrip", "SCRIP", "Sub", "Date", "Ref", "MANAGEMENT", "To", "Dear", "Subject", "Attention")
QA_START_RX = re.compile(r"question[- ]and[- ]answer|first question|open the floor|q ?& ?a session|take (up )?(the )?questions", re.I)
NAME = r"([A-Z][A-Za-z.'’\-]+(?:\s+[A-Z][A-Za-z.'’\-]+){0,3})"
ANALYST_INTRO_RX = re.compile(r"(?i:line of|question (?:is )?from|next question comes from|first question is from)\s+(?i:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)?\s*" + NAME)
HOST_INTRO_RX = re.compile(r"(?i:over to|hand (?:the )?conference over to|hand it over to)\s+(?i:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)?\s*" + NAME + r"\s+(?i:from|of)\s+")
MGMT_INTRO_RX = re.compile(r"(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)\s+([A-Z][A-Za-z.'’\-]+(?:\s+[A-Z][A-Za-z.'’\-]+){0,3})\s*[,–-]\s*(?:the\s+)?"
                           r"(Managing Director|MD|CEO|Chief Executive|CFO|Chief Financial|Head of Investor|Whole[- ]time Director|President|Executive Director|Group Chief)", re.I)
QUARTER_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def load_topics():
    d = yaml.safe_load((LEX_DIR / "topics.yaml").read_text(encoding="utf-8"))
    topics = [(t["tag"], [re.compile(p, re.I) for p in t["patterns"]], t.get("companies")) for t in d["topics"]]
    return topics, d.get("people", {})


def tag_topics(topics, company: str, sentence: str) -> list[str]:
    tags = []
    for tag, rxs, comps in topics:
        if comps and company not in comps:
            continue
        if any(rx.search(sentence) for rx in rxs):
            tags.append(tag)
    return tags or ["other"]


def _norm_name(n: str) -> str:
    return re.sub(r"[^a-z ]", "", n.lower()).strip()


def _same_person(a: str, b: str) -> bool:
    ta, tb = _norm_name(a).split(), _norm_name(b).split()
    if not ta or not tb:
        return False
    if set(ta) <= set(tb) or set(tb) <= set(ta):
        return True
    return ta[0] == tb[0] and (ta[-1][:4] == tb[-1][:4])


def call_period_of(title: str, texts: list[str]) -> str | None:
    head = (title or "") + " \n" + " \n".join(texts[:2])
    ps = [p for p in parse_periods(head) if p.canon.startswith("Q")]
    if ps:
        return ps[0].canon
    m = re.search(r"FY\s?['’]?\s?(\d{2,4})\s+(first|second|third|fourth)\s+quarter", head, re.I) or \
        re.search(r"(first|second|third|fourth)\s+quarter\s+(?:of\s+)?(?:the\s+)?(?:financial year|FY)\s?['’]?\s?(\d{2,4})", head, re.I)
    if m:
        g = m.groups()
        a, b = (g[1], g[0]) if g[0].isdigit() else (g[0], g[1])
        return f"Q{QUARTER_WORDS[b.lower()]}FY{int(a[-2:]):02d}"
    return None


def call_date_of(first_page: str, known_at: str | None) -> str | None:
    m = CALL_DATE_RX.search(first_page[:1500])
    if m:
        mon = [x.lower() for x in MONTHS.split("|")].index(m.group(1).lower()) + 1
        return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}"
    return (known_at or "")[:10] or None


def boilerplate_lines(pages: list[str]) -> set[str]:
    """Lines that repeat on at least 60% of the pages (company name, running headers)."""
    c = Counter()
    for t in pages:
        for l in {x.strip() for x in t.split("\n") if x.strip()}:
            c[l] += 1
    n = max(len(pages), 1)
    return {l for l, k in c.items() if k >= max(3, 0.6 * n) and len(l) < 80}


def mask_noise(text: str, boiler: set[str]) -> str:
    """Same-length copy of text with page numbers, date lines and repeated headers blanked (offsets stay valid)."""
    w = list(text)
    def blank(a, b):
        for i in range(a, b):
            if w[i] != "\n":
                w[i] = " "
    for rx in (PAGE_NO_RX, DATE_LINE_RX):
        for m in rx.finditer(text):
            blank(m.start(), m.end())
    pos = 0
    for line in text.split("\n"):
        if line.strip() in boiler and not SPEAKER_RX.match(line):
            blank(pos, pos + len(line))
        pos += len(line) + 1
    return "".join(w)


def split_sentences(seg: str, base: int):
    """[(start, end)] absolute offsets of sentences in seg (seg starts at base). Abbreviation/decimal safe."""
    spans, start = [], 0
    for m in SENT_END_RX.finditer(seg):
        pre = seg[max(0, m.start() - 8):m.start()]
        last = re.findall(r"([A-Za-z.]+)\.$", pre)
        if last and last[-1].rstrip(".") in ABBR:
            continue
        if re.search(r"\b[A-Z]\.$", pre):       # initials
            continue
        spans.append((base + start, base + len(seg[:m.end()].rstrip())))
        start = m.end()
    spans.append((base + start, base + len(seg)))
    return [(a, b) for a, b in spans if seg[a - base:b - base].strip()]


def numbers_in(sentence: str, default_period: str | None):
    out = []
    pers = parse_periods(sentence)
    spans = [(p.start, p.end) for p in pers]
    for m in VAL_RX.finditer(sentence):
        if any(a <= m.start("num") < b for a, b in spans):
            continue
        cur, suf = _norm_cur(m.group("cur")), (m.group("suf") or "").lower().rstrip(".")
        base = _UNIT_BY_SUFFIX.get(suf)
        if not cur and not base:
            continue
        v = to_float(m.group("num"))
        if v is None:
            continue
        if cur == "usd" and base == "mn":
            unit = "usd_mn"
        elif cur == "usd" and base == "bn":
            unit = "usd_bn"
        elif cur == "usd":
            unit = "usd"
        elif base == "inr_cr" or (cur == "inr" and base in (None, "inr_cr")):
            unit = "inr_cr" if base == "inr_cr" else "inr"
        else:
            unit = base or cur
        # nearest period in the sentence (after the number first), else None
        after = [p for p in pers if p.start >= m.end() and p.start - m.end() <= 40]
        before = [p for p in pers if p.end <= m.start() and m.start() - p.end <= 40]
        per = (after or before[-1:] or [None])[0]
        out.append({"value": v, "unit": unit, "period": per.canon if per else default_period, "raw": m.group(0).strip(),
                    "period_source": "sentence" if per else "call"})
    return out


def role_of(speaker: str, company: str, people: dict, analysts: list[str], mgmt: dict[str, str]) -> str:
    if speaker.lower().startswith("moderator") or speaker.lower() == "operator":
        return "moderator"
    if speaker.lower() in ("participant", "analyst", "questioner", "unidentified participant", "unidentified speaker"):
        return "analyst"
    if speaker.lower() in ("management", "company representative", "company management"):
        return "mgmt"
    for k in people.get(company, []):
        if _same_person(k["name"], speaker):
            return k["role"]
    for n, r in mgmt.items():
        if _same_person(n, speaker):
            return r
    if any(_same_person(a, speaker) for a in analysts):
        return "analyst"
    return "unknown"


def _title_role(title: str) -> str:
    t = title.lower()
    if "chief financial" in t or t.startswith("cfo"):
        return "cfo"
    if "head of investor" in t:
        return "ir"
    if "managing director" in t or t.startswith("md") or "chief executive" in t or t.startswith("ceo"):
        return "md"
    return "mgmt"


def extract_doc(sym: str, doc_key: str, title: str, known_at: str, pages: list[tuple[int, str]], topics, people, st: dict):
    texts = [t for _, t in pages]
    boiler = boilerplate_lines(texts)
    cperiod = call_period_of(title, texts)
    cdate = call_date_of(texts[0], known_at)
    full = "\n".join(texts)
    analysts = [m.group(1) for m in ANALYST_INTRO_RX.finditer(full) if m.group(1)] + \
               [m.group(1) for m in HOST_INTRO_RX.finditer(full)]
    mgmt = {m.group(1): _title_role(m.group(2)) for m in MGMT_INTRO_RX.finditer(full)}
    speaker, section, seq, prev_role, started = "unknown", "prepared", 0, "moderator", False
    rows = []
    for page, raw in pages:
        w = mask_noise(raw, boiler)
        marks = sorted((m.start(1), m.end(), m.group(1)) for rx in (SPEAKER_RX, SPEAKER_MID_RX) for m in rx.finditer(w)
                       if not m.group(1).startswith(NOT_SPEAKERS))
        bounds = [(0, marks[0][0], speaker)] if marks and marks[0][0] > 0 else ([] if marks else [(0, len(w), speaker)])
        for k, (a, b, name) in enumerate(marks):
            end = marks[k + 1][0] if k + 1 < len(marks) else len(w)
            bounds.append((b, end, name))
            speaker = name
        for a, b, name in bounds:
            role = role_of(name, sym, people, analysts, mgmt)
            if role == "unknown" and section == "qa" and prev_role == "moderator":
                analysts.append(name)
                role = "analyst"
            prev_role = role
            if role not in ("unknown", "analyst") and not started:
                started = True      # cover letter / headers before the first real speaker are not call content
            if not started:
                continue
            seg = w[a:b]
            if role == "moderator" and QA_START_RX.search(seg):
                section = "qa"
            if role in ("moderator", "analyst"):
                continue
            if role == "unknown":      # cannot tell management from a stray analyst: counted, not stored
                st["unknown_speakers"][name] += 1
                continue
            for (s0, e0) in split_sentences(seg, a):
                q = raw[s0:e0].strip()
                if len(q) < 25 or not re.search(r"[A-Za-z]{3}", q):
                    continue
                seq += 1
                sent = " ".join(q.split())
                per = parse_periods(sent)
                if per:
                    pdisc, psrc = per[0].canon, "sentence"
                else:
                    pdisc, psrc = cperiod, "call"
                frag = int(not re.search(r"[.?!][\"”’')]*$", q) or q[0].islower())
                rows.append((sym, None, doc_key, cdate, cperiod, page, seq, name, role, section,
                             ",".join(tag_topics(topics, sym, sent)), pdisc, psrc,
                             json.dumps(numbers_in(sent, cperiod), ensure_ascii=False), sent, q, frag, known_at,
                             "docs.known_at", "transcript_v1"))
    return rows


COLS = ("symbol isin doc_key call_date call_period page seq speaker role section topics period_discussed period_source "
        "numbers_json statement quote is_fragment known_at known_at_source extractor_rule").split()


def run(out: str, symbols: list[str], sandbox: Path, limit_docs: int | None = None) -> dict:
    t0 = time.time()
    topics, people = load_topics()
    con = sqlite3.connect(out)
    con.executescript(SCHEMA)
    stats: dict = {}
    sql = f"INSERT OR IGNORE INTO transcript_statement({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})"
    for sym in symbols:
        src = sqlite3.connect(f"file:{(sandbox / (COMPANIES[sym] + '_loop') / (COMPANIES[sym] + '.db')).as_posix()}?mode=ro", uri=True)
        con.execute("DELETE FROM transcript_statement WHERE symbol=?", (sym,))
        st = stats[sym] = {"docs": 0, "pages": 0, "needs_ocr": 0, "unknown_speakers": Counter()}
        docs = src.execute("SELECT doc_key, title, known_at FROM docs WHERE doc_type='transcript' ORDER BY known_at").fetchall()
        if limit_docs:
            docs = docs[:limit_docs]
        for doc_key, title, known_at in docs:
            allp = src.execute("SELECT page, text, method FROM doc_text WHERE doc_key=? ORDER BY page", (doc_key,)).fetchall()
            st["needs_ocr"] += sum(1 for _, _, m in allp if m == "needs_ocr")
            pages = [(p, t) for p, t, m in allp if m == "script_text" and t]
            if not pages:
                continue
            st["docs"] += 1
            st["pages"] += len(pages)
            con.executemany(sql, extract_doc(sym, doc_key, title, known_at, pages, topics, people, st))
        con.commit()
        st["rows"] = con.execute("SELECT count(*) FROM transcript_statement WHERE symbol=?", (sym,)).fetchone()[0]
        st["unknown_speakers"] = dict(st["unknown_speakers"].most_common(5))
        src.close()
    stats["seconds"] = round(time.time() - t0, 1)
    con.close()
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default="KEC,BAJFINANCE,HINDALCO")
    ap.add_argument("--sandbox-root", default=str(SANDBOX_ROOT))
    ap.add_argument("--limit-docs", type=int, default=None)
    a = ap.parse_args(argv)
    stats = run(a.out, [s.strip().upper() for s in a.symbols.split(",") if s.strip()], Path(a.sandbox_root), a.limit_docs)
    for k, v in stats.items():
        print(k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
