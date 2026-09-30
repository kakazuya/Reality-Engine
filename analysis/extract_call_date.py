"""
Extract the real (call-date, filing-date) pair from a BSE/NSE Reg-30 earnings-call
transcript cover page, so `corporate_documents.doc_date` (currently the CRAWL date)
can be corrected with provenance.

Read-only. Opens PDFs read-only, touches no DB. Emits JSONL to stdout or a file.

Why: the drain stamps doc_date=event_date=event_source='doc_date' with the day it
fetched the file. A 6-document MCX sample showed real letterhead dates spanning
May-2025..Aug-2026 under crawl stamps of 2026-08-28. This recovers the truth from
the document body.

Patterns are deliberately narrow and return None rather than guessing. Every
extraction carries the evidence span so a human can audit it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path

import pymupdf

# ---------------------------------------------------------------- month names
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))

# "August 12, 2026" / "12 August 2026" / "August 12 2026" / "12th August, 2026"
DATE_PATTERNS = [
    re.compile(rf"\b({MONTH_RE})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I),
    re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({MONTH_RE}),?\s+(\d{{4}})\b", re.I),
]

# The call itself. BSE Reg-30 transcripts say "...held on Wednesday, August 12, 2026".
# NSE/other formats vary, so we accept "held on <date>" and a bare "on <date>" near
# a call/quarter keyword.
WEEKDAY = (r"(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day")
CALL_HELD_RE = re.compile(
    rf"held\s+on\s*({WEEKDAY})?\s*,?\s*[,:]?\s*"
    rf"((?:{MONTH_RE})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{MONTH_RE}),?\s+\d{{4}})",
    re.I,
)
CALL_QUARTER_RE = re.compile(
    r"\b(Q[1-4])\s*[-–]?\s*(?:FY)?\s*[-–]?\s*(\d{4}|\d{2})\b", re.I
)
CONTEXT_CHARS = 150
EARNINGS_CONTEXT_RE = re.compile(
    r"earnings|quarter|results|transcript|analyst|investor|conference\s+call|"
    r"financial\s+(?:and\s+operational\s+)?performance",
    re.I,
)
# Meeting types that share the "held on" phrasing and must NOT be scored as
# earnings calls when no earnings language is present.
NON_EARNINGS_MEETING_RE = re.compile(
    r"annual\s+general\s+meeting|\b\d+(?:st|nd|rd|th)\s+agm|extra[-\s]?ordinary|"
    r"board\s+meeting|investor\s+meet(?:ing)?\b(?!\s+call)",
    re.I,
)
CALL_KEYWORD_RE = re.compile(
    r"earnings\s+(?:conference\s+)?call|investor\s+analyst|conference\s+call", re.I
)

# Running transcript header, e.g. "State Bank of India  November 03, 2021  Page 2 of 19"
# or "Apar Industries Limited ... Q4 & FY16 Earnings Conference Call  May 26, 2016".
# Repeated on every page, so a high-confidence fallback when no cover letter exists.
HEADER_DATE_RE = re.compile(
    rf"\b((?:{MONTH_RE})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{MONTH_RE}),?\s+\d{{4}})"
    rf"\s*(?:IST)?\s*(?:Page\s+\d+\s+of\s+\d+)?",
    re.I,
)
# Cover-page letterhead: a date near a filing reference like "MCX/SEC/2730".
SEC_REF_RE = re.compile(r"\b[A-Z]{2,5}/[A-Z]{2,4}/\d+\b")
# Boilerplate that must never be taken as the letter date.
# Date confounders only: these mark a period-end or contact block rather than the
# letter date. Deliberately excludes "scrip code:", which is genuine letterhead and
# always follows the date on a BSE Reg-30 cover page.
BOILERPLATE_RE = re.compile(
    r"for\s+the\s+(?:quarter|year)\s+ended|year\s+ended|as\s+on\s+[\d-]|"
    r"registered\s+office|www\.|tel\s*:|fax\s*:|e-mail\s*:",
    re.I,
)

# Pages of interest. The cover letter is normally p1, but BSE Reg-30 filings
# sometimes carry the letter on p2-3, and many transcripts only date themselves in
# the running header from p2 onward. 5 pages is a bounded read of short text.
MAX_PAGES = 5


@dataclass
class Extraction:
    path: str
    company_hint: str | None
    call_date: str | None          # ISO. ONLY from an explicit "held on <date>"
                                   # phrase: the date the call was HELD.
    publication_date: str | None   # ISO. Reg-30 letterhead / running-header /
                                   # e-filing stamp: when the TRANSCRIPT became
                                   # publicly filed. NOT the call date.
    quarter: str | None            # e.g. "Q1FY2027"
    sec_ref: str | None
    call_date_source: str | None   # "held_on" | "publication_proxy"
    evidence: str | None           # verbatim span, for audit
    pages_used: int
    status: str                    # ok | no_text_layer | no_date_found | unparsed
    pua_rate: float = 0.0
    # Provenance tier, strongest first. Never collapse these into one field.
    #   1 held_on      explicit "held on <date>" AND a filing date recovered
    #   2 held_only    held_on present but no filing date, or implausible lag
    #   3 publication  only a letterhead / e-filing / running-header date.
    #                  This is when the text became PUBLIC, not the call date.
    #   0 none         nothing recovered; row must stay honest-NULL
    date_tier: int = 0
    needs_review: bool = False
    review_reason: str | None = None
    # Days between the call and the transcript becoming public. None when the
    # filing date was not recovered. Never fabricate 0.
    filing_lag_days: int | None = None



def _to_iso(mon: str, day: str, year: str) -> str | None:
    m = MONTHS.get(mon.lower())
    if not m:
        return None
    try:
        d, y = int(day), int(year)
        if not (1 <= d <= 31) or not (2000 <= y <= 2035):
            return None
        return f"{y:04d}-{m:02d}-{d:02d}"
    except (TypeError, ValueError):
        return None


def _find_dates(text: str) -> list[tuple[str, int, int, int]]:
    """All plausible (iso, start, end) dates in a span of text."""
    out: list[tuple[str, int, int, int]] = []
    for month_first, pat in ((True, DATE_PATTERNS[0]), (False, DATE_PATTERNS[1])):
        for mo in pat.finditer(text):
            iso = (_to_iso(mo.group(1), mo.group(2), mo.group(3)) if month_first
                   else _to_iso(mo.group(2), mo.group(1), mo.group(3)))
            if iso:
                out.append((iso, mo.start(), mo.end()))
    return out


def _pua_rate(text: str) -> float:
    if not text:
        return 0.0
    pua = sum(1 for ch in text if 0xE000 <= ord(ch) <= 0xF8FF)
    return pua / len(text)


def extract(path: str | Path, company_hint: str | None = None) -> Extraction:
    path = Path(path)
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # noqa: BLE001
        return Extraction(str(path), company_hint, None, None, None, None, None,
                          None, 0, f"open_error:{type(exc).__name__}")

    text_parts: list[str] = []
    pua_chars = 0
    total_chars = 0
    for pno in range(min(doc.page_count, MAX_PAGES)):
        try:
            t = doc[pno].get_text() or ""
        except Exception:  # noqa: BLE001
            continue
        text_parts.append(t)
        pua_chars += sum(1 for ch in t if 0xE000 <= ord(ch) <= 0xF8FF)
        total_chars += len(t)
    page_count = doc.page_count
    doc.close()

    text = "\n".join(text_parts)
    pr = pua_chars / total_chars if total_chars else 0.0
    if not text.strip() or pr > 0.5:
        return Extraction(str(path), company_hint, None, None, None, None, None,
                          None, min(MAX_PAGES, page_count),
                          "no_text_layer" if not text.strip() else "pua_poison",
                          pr)

    norm = re.sub(r"[ \t]+", " ", text)

    # 1. Best signal: the "held on <date>" phrase.
    call_date = None
    call_src = None
    evidence = None
    weekday_mismatch = None
    context_reject = None
    call_pos = None
    m = CALL_HELD_RE.search(norm)
    weekday_claim = None
    if m:
        weekday_claim = m.group(1)
        call_date = next((d for d, s, e in _find_dates(m.group(2)) if s == 0), None)
        if call_date and weekday_claim:
            # Free correctness check: the weekday printed in the filing must match
            # the calendar weekday of the claimed date. A mismatch means we read
            # the wrong branch (another meeting, an OCR fault, a re-filing).
            # Many filings omit the weekday; then there is nothing to check.
            want = weekday_claim[:3].lower()
            have = date.fromisoformat(call_date).strftime("%a").lower()
            if want != have:
                weekday_mismatch = f"{weekday_claim}!={call_date}({have})"
                call_date = None
            else:
                call_src = "held_on"
                call_pos = m.start()
                evidence = norm[max(0, m.start() - 60): m.end() + 60].replace("\n", " ").strip()
        elif call_date:
            call_src = "held_on"
            call_pos = m.start()
            evidence = norm[max(0, m.start() - 60): m.end() + 60].replace("\n", " ").strip()

    # 1b. Context gate. "held on <date>" is ALSO how AGMs, board meetings and
    # investor meets are phrased. Only call this an earnings call when
    # earnings/quarter/results/transcript language appears within CONTEXT_CHARS
    # of the match. Without this the guidance-raise frame inherits AGM dates.
    if call_src == "held_on" and call_pos is not None:
        lo = max(0, call_pos - CONTEXT_CHARS)
        hi = min(len(norm), call_pos + CONTEXT_CHARS)
        ctx = norm[lo:hi]
        # Hard veto: AGM / board-meeting / EGM language anywhere in the window
        # disqualifies the row, even if "transcript" is also present (AGMs
        # produce transcripts too).
        if NON_EARNINGS_MEETING_RE.search(ctx):
            call_src = None
            call_date = None
            context_reject = "non_earnings_meeting"
        elif not EARNINGS_CONTEXT_RE.search(ctx):
            call_src = None
            call_date = None
            context_reject = "no_earnings_context"

    # 2. Filing letterhead: a date adjacent to a Reg-30 reference, not boilerplate.
    publication_date = None
    if call_src is None or call_date != publication_date:
        for ref in SEC_REF_RE.finditer(norm):
            # Forward-only: the letter date follows the reference. Looking back
            # pulls in the CIN/email header block, which is pure boilerplate.
            window = norm[ref.start(): ref.start() + 300]
            for iso, s, e in _find_dates(window):
                after = window[e: e + 90]
                before = window[max(0, s - 60): s]
                if BOILERPLATE_RE.search(after) or BOILERPLATE_RE.search(before):
                    continue
                publication_date = iso
                if call_date is None:
                    call_date, call_src = iso, "publication_proxy"
                    evidence = window[max(0, s - 80): e + 120].replace("\n", " ").strip()
                break
            if publication_date:
                break

    # 3. Quarter from the subject line.
    quarter = None
    qm = CALL_QUARTER_RE.search(norm)
    if qm:
        yr = qm.group(2)
        if len(yr) == 2:
            yr = f"20{yr}"
        quarter = f"{qm.group(1).upper()}FY{yr}"

    # 4. Last resort: running-header date (repeated on every transcript page).
    if call_date is None:
        for hm in HEADER_DATE_RE.finditer(norm):
            cand = next((d for d, s0, e0 in _find_dates(hm.group(1)) if s0 == 0), None)
            if cand:
                call_date, call_src = cand, "publication_proxy"
                evidence = norm[max(0, hm.start() - 70): hm.end() + 30].replace("\n", " ").strip()
                break

    sec = SEC_REF_RE.search(norm)
    status = "ok" if (call_date or publication_date) else "no_date_found"

    lag = None
    if call_date and publication_date:
        try:
            lag = (date.fromisoformat(publication_date)
                   - date.fromisoformat(call_date)).days
        except ValueError:
            lag = None

    # Tier + triage. A publication-date match is NEVER promoted to a call date.
    reasons: list[str] = []
    if call_src == "held_on":
        tier = 2 if publication_date is None else 1
        if publication_date is None:
            reasons.append("held_on_without_filing_date")
        elif lag is not None and lag > 8:
            tier = 2
            reasons.append(f"filing_lag_gt_8d:{lag}")
    elif call_date:
        tier = 3
        reasons.append("publication_date_only_not_call_date")
    else:
        tier = 0
        reasons.append("no_date_recovered")
    if weekday_mismatch:
        reasons.append(f"weekday_mismatch:{weekday_mismatch}")
    if context_reject:
        reasons.append(context_reject)

    # Filed before the call would be a parse contradiction: void, keep the span.
    if lag is not None and lag < 0:
        tier = 0
        call_date = None
        reasons.append(f"negative_lag_voided:{lag}")

    return Extraction(
        path=str(path), company_hint=company_hint, call_date=call_date,
        publication_date=publication_date, quarter=quarter,
        sec_ref=sec.group(0) if sec else None, call_date_source=call_src,
        evidence=evidence, pages_used=min(MAX_PAGES, page_count),
        status=status, pua_rate=round(pr, 4),
        date_tier=tier, needs_review=bool(reasons),
        review_reason=";".join(reasons) if reasons else None,
        filing_lag_days=lag,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+", help="PDF paths")
    ap.add_argument("--out", help="write JSONL here instead of stdout")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    paths = args.paths[: args.limit] if args.limit else args.paths
    results = [extract(p) for p in paths]

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            for r in results:
                fh.write(json.dumps(asdict(r)) + "\n")
        print(f"wrote {len(results)} -> {args.out}", file=sys.stderr)
    else:
        for r in results:
            print(json.dumps(asdict(r)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
