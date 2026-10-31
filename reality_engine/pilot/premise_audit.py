"""Rule-check the instance premises against the held stores.

Gate 95% review (2026-10-31), idea 3: an estimated 23-28% of instance rows rest
on a premise that is false for the substituted company ("Bajaj Finance's order
book is Rs 9,923 crore"; "APL Apollo fell 20.15% on 14 May 2026").  Only the
part a store can settle is adjudicated here, deterministically:

* a move premise ("X fell 20.15% on 14 May 2026") against the stored session
  close-to-close move (raw close series, the basis the bank's numbers came from);
* a leftover company name against the master identity of the named company;
* a business-type premise (order book / airline / tobacco / lending) against the
  company's sector and basic industry, plus the order-book disclosures held;
* a listing premise against the company's first stored session.

A row is called ``false`` only when a stored value contradicts it, and that
value and its source travel with the row.  ``cannot_check`` is the default for
anything a store cannot settle; ``holds`` is reserved for a move premise the
store confirms.  Point in time: a premise dated after the row's ``as_of`` is not
judged, and a blank ``as_of`` is judged at the declared :data:`AUDIT_DATE`.

    python -m reality_engine.pilot.premise_audit            # writes the JSONL + prints counts
    python -m reality_engine.pilot.premise_audit --sheet-a tasks/arch_v4/SHIVAM_SHEET_PREMISES.md
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import re
from pathlib import Path

from reality_engine.db.readonly import connect_ro

SEED = 20261031              # committed seed for the review sheets
AUDIT_DATE = "2026-10-19"    # declared snapshot for a row with a blank as_of
PRICE_TOLERANCE_PP = 0.05    # bank figures are 2 dp of the stored move
STORE_START = "2019-01-01"   # first session in company_state_daily

# ---------------------------------------------------------------- text parsing

MOVE_VERBS = {
    "rose": 1, "gained": 1, "surged": 1, "jumped": 1, "rallied": 1, "advanced": 1,
    "fell": -1, "lost": -1, "plunged": -1, "dropped": -1, "slipped": -1, "declined": -1,
}
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
VERB_RE = re.compile(r"\b(" + "|".join(MOVE_VERBS) + r")\b", re.I)
MONTHS = {m.lower(): i for i, m in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"), 1)}
DATE_TEXT_RE = re.compile(
    r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{4})", re.I)
DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
RELATIVE_RE = re.compile(
    r"\b(that day|the next session|the next day|the same day|next session)\b", re.I)
FLOOR_RE = re.compile(r"\b(more than|at least|over|above)\b\s*$", re.I)
NON_PRICE_HEAD_RE = re.compile(
    r"delivery|margin|growth|yield|revenue|profit|volume|turnover|cagr|holding|order", re.I)
LEGAL_RE = re.compile(r"\s+(limited|ltd|private|pvt|corporation|corp)\b\.?$", re.I)
STOPWORDS = {"the", "a", "an", "of", "and"}
# Group words shared by several listed companies: a bare first word is not an alias.
GROUP_WORDS = {"tata", "bajaj", "adani", "hindustan", "indian", "reliance", "mahindra",
               "jindal", "godrej", "aditya", "kotak", "hdfc", "icici", "axis", "jio",
               "dlf", "larsen", "sun", "shri", "shree", "united", "global", "general",
               "national", "oriental", "new", "india",
               # ordinary business words that start a sentence in the bank's text
               "shipping", "cement", "steel", "power", "finance", "capital", "hotels",
               "airline", "airlines", "pharma", "chemicals", "textiles", "energy", "infra",
               "infrastructure", "industries", "bank", "motors", "auto", "foods", "oil",
               "gas", "port", "ports", "engineering", "electrical", "digital",
               "technologies", "systems", "services", "metals", "mining", "paper", "sugar",
               "dairy", "retail", "media", "telecom", "realty", "housing", "insurance",
               "health", "life"}


def _iso_from_text(match: re.Match) -> str:
    """One explicit date match -> ``YYYY-MM-DD``."""
    if match.re is DATE_ISO_RE:
        return match.group(0)
    return "%s-%02d-%02d" % (match.group(3), MONTHS[match.group(2).lower()], int(match.group(1)))


def _explicit_date(text: str) -> str | None:
    for pattern in (DATE_TEXT_RE, DATE_ISO_RE):
        match = pattern.search(text)
        if match:
            return _iso_from_text(match)
    return None


def _period_span(period: str | None) -> list[str]:
    return ["-".join(part) for part in DATE_ISO_RE.findall(period or "")]


def _sentence_around(question: str, start: int, end: int) -> str:
    """The sentence that carries the percentage, so a later date cannot hijack it."""
    left = max(question.rfind(". ", 0, start), question.rfind("? ", 0, start),
               question.rfind("! ", 0, start))
    left = 0 if left < 0 else left + 2
    rights = [index for index in (question.find(". ", end), question.find("? ", end),
                                  question.find("! ", end)) if index >= 0]
    return question[left:min(rights) if rights else len(question)]


def parse_move_premise(question: str, period: str | None = None) -> dict | None:
    """The first "verb N% on a date" premise in ``question``, or ``None``.

    Returns ``{"verb", "direction", "claimed_pct", "signed_pct", "date", "phrase",
    "floor"}``; ``date`` is ``None`` when neither an explicit date nor a relative
    phrase resolved from ``period`` is available.
    """
    for match in PCT_RE.finditer(question):
        head_start = max(0, match.start() - 70)
        head = question[head_start:match.start()]
        verbs = list(VERB_RE.finditer(head))
        if not verbs:
            continue
        if NON_PRICE_HEAD_RE.search(head[-45:]):
            continue                          # "delivery % jumped above 60%" is not a price move
        verb = verbs[-1]                      # nearest verb wins ("Advanced Materials fell ...")
        direction = MOVE_VERBS[verb.group(1).lower()]
        claimed = float(match.group(1))
        sentence = _sentence_around(question, match.start(), match.end())
        date = None
        if RELATIVE_RE.search(sentence):
            days = _period_span(period)
            if days:
                date = days[-1]
        if date is None:
            date = _explicit_date(sentence)
        if date is None:
            date = _explicit_date(question)
        if date is None:
            days = _period_span(period)
            if days:
                date = days[-1]
        return {"verb": verb.group(1), "direction": direction, "claimed_pct": claimed,
                "signed_pct": direction * claimed, "date": date,
                "phrase": question[head_start + verb.start():match.end()].strip(),
                "floor": bool(FLOOR_RE.search(head))}
    return None


def judge_move(premise: dict, actual_pct: float,
               tolerance_pp: float = PRICE_TOLERANCE_PP) -> tuple[str, float]:
    """``holds`` when the stored move agrees with the claimed one, else ``false``."""
    claimed = float(premise["signed_pct"])
    diff = float(actual_pct) - claimed
    if premise.get("floor"):
        if claimed < 0:
            ok = actual_pct < 0 and abs(actual_pct) >= abs(claimed) - tolerance_pp
        else:
            ok = actual_pct > 0 and actual_pct >= claimed - tolerance_pp
    else:
        ok = abs(diff) <= tolerance_pp
    return ("holds" if ok else "false"), round(diff, 4)


# -------------------------------------------------------------- business class

# premise name -> (question pattern, industry pattern that can carry the premise)
BUSINESS_CLASSES = {
    "order_book": (
        r"order book|order-book|order inflow|order intake|book-to-bill",
        r"capital goods|construction|industrial|electrical equipment|aerospace|defence|"
        r"machinery|pump|compressor|casting|forging|cable|railway|shipbuild|infrastructure|"
        r"engineering|equipment",
    ),
    "airline": (
        r"\bairline\b|load factor|\baircraft\b|\bfleet\b",
        r"airline|aviation",
    ),
    "tobacco": (
        r"tobacco|cigarette",
        r"tobacco|cigarette",
    ),
    "lender": (
        r"\bnim\b|\bnpa\b|loan book|net interest",
        r"financial|bank|nbfc|insurance|finance|capital markets|lending",
    ),
}
LISTING_RX = re.compile(
    r"listing[- ]day|listing pop|listing ke baad|grey[- ]market|since the (ipo|listing)|"
    r"first[- ]day (close|return)|listed at a discount|listing day", re.I)
ISIN_RX = re.compile(r"\bINE[0-9A-Z]{9}\b")


def business_class(question: str) -> str | None:
    """The first business-type premise the question states, or ``None``."""
    for name, (pattern, _) in BUSINESS_CLASSES.items():
        if re.search(pattern, question or "", re.I):
            return name
    return None


def class_applicable(name: str, identities: list[dict]) -> bool:
    """True when any entity's name, sector or industry can carry the premise's business."""
    pattern = BUSINESS_CLASSES[name][1]
    for identity in identities:
        text = " ".join(str(identity.get(key) or "") for key in
                        ("name", "sector", "industry", "basic_industry"))
        if re.search(pattern, text, re.I):
            return True
    return False


# -------------------------------------------------------------- alias matching

def company_aliases(name: str | None, symbol: str | None = None,
                    bse_code: str | None = None) -> set[str]:
    """Lower-case ways a company is spelled in a question (name, base name,
    first two name words, symbol).  Keeps only aliases of four characters or
    more so short symbols do not collide with ordinary words."""
    aliases: set[str] = set()
    name = (name or "").strip()
    if len(name) >= 6:
        aliases.add(name.lower())
        base = LEGAL_RE.sub("", name).strip()
        if base and base.lower() != name.lower():
            aliases.add(base.lower())
        words = re.findall(r"[A-Za-z0-9&]+", base or name)
        if len(words) >= 2 and words[0].lower() not in STOPWORDS:
            aliases.add(" ".join(words[:2]).lower())
        if len(words[0]) >= 6 and words[0].lower() not in GROUP_WORDS:
            aliases.add(words[0].lower())     # "Garware: tariff hit" names the parent
    for value in (symbol, bse_code):
        value = str(value or "").strip()
        if len(value) >= 4:
            aliases.add(value.lower())
    return {alias for alias in aliases if len(alias) >= 4}


def alias_regex(aliases: set[str]) -> re.Pattern | None:
    if not aliases:
        return None
    ordered = sorted((re.escape(alias) for alias in aliases), key=len, reverse=True)
    return re.compile(r"(?<![A-Za-z0-9])(" + "|".join(ordered) + r")(?![A-Za-z0-9])", re.I)


# ------------------------------------------------------------------- row audit

REASON_VERDICT = {
    "price_move_contradicted": "false",
    "names_other_company": "false",
    "business_type_mismatch": "false",
    "listing_premise_outside_store": "false",
    "price_move_confirmed": "holds",
    "price_move_not_stored": "cannot_check",
    "price_after_as_of": "cannot_check",
    "price_date_unresolved": "cannot_check",
    "business_type_plausible": "cannot_check",
    "text_identical_generic": "cannot_check",
    "premise_not_checkable": "cannot_check",
    "no_substitution": "cannot_check",
}


def _entity_isins(row: dict) -> list[str]:
    return [str(e.get("isin")) for e in (row.get("entities") or [])
            if isinstance(e, dict) and e.get("isin")]


def _identity_note(identity: dict, isin: str = "") -> str:
    bits = [identity.get("symbol") or identity.get("name") or isin or "?"]
    for key in ("sector", "industry", "basic_industry"):
        if identity.get(key):
            bits.append("%s=%s" % (key, identity[key]))
    return "; ".join(str(bit) for bit in bits)


def audit_row(row: dict, parent: dict | None, lookups) -> dict:
    """One instance -> one audit record (verdict, reasons, evidence, source)."""
    question = str(row.get("question") or "")
    as_of = str(row.get("as_of") or "")[:10] or AUDIT_DATE
    as_of_basis = "row as_of" if row.get("as_of") else "declared snapshot " + AUDIT_DATE
    isins = _entity_isins(row)
    kind = str(row.get("kind") or "")
    reasons: list[str] = []
    evidence: list[dict] = []
    identities = {isin: dict(lookups.identity(isin)) for isin in isins}
    for entity in row.get("entities") or []:
        isin = str((entity or {}).get("isin") or "")
        if isin in identities:
            for key in ("symbol", "name"):
                if not identities[isin].get(key) and entity.get(key):
                    identities[isin][key] = entity[key]

    def add(reason: str, value: str, source: str) -> None:
        reasons.append(reason)
        evidence.append({"reason": reason, "value": value, "source": source})

    if kind == "as_is":
        add("no_substitution",
            "kind=as_is: the row runs on the parent's own entities, no company was substituted",
            "tasks/pilot60/INSTANCES.jsonl")
        return _record(row, parent, question, identities, reasons, evidence, as_of, as_of_basis)

    premise = parse_move_premise(question, row.get("period"))
    if premise and kind == "stock" and len(isins) == 1:
        identity = identities[isins[0]]
        if premise["date"] is None:
            add("price_date_unresolved",
                "move premise %r names no date that the period resolves" % premise["phrase"],
                "audit rule: reality_engine/pilot/premise_audit.py")
        elif premise["date"] > as_of:
            add("price_after_as_of",
                "premise date %s is after the row's as_of %s, so it was not knowable"
                % (premise["date"], as_of), "point-in-time rule; row as_of")
        else:
            move = lookups.move(isins[0], premise["date"])
            if not move:
                around = lookups.sessions_around(isins[0], premise["date"])
                add("price_move_not_stored",
                    "no stored session for %s on %s (nearest: %s)"
                    % (identity.get("symbol") or isins[0], premise["date"], around or "none"),
                    "equity_intelligence.daily_price_delivery / mkt_bse_eq_daily")
            else:
                verdict, diff = judge_move(premise, move["pct"])
                add("price_move_confirmed" if verdict == "holds" else "price_move_contradicted",
                    "claimed %+.2f%% on %s; stored %+.2f%% (%s %.2f on %s -> %.2f on %s; "
                    "difference %+.2f pp)"
                    % (premise["signed_pct"], premise["date"], move["pct"], move["basis"],
                       move["prev_close"], move["prev_date"], move["close"], move["date"], diff),
                    move["source"])

    parent_isin = ""
    for item in row.get("substituted_from") or []:
        if isinstance(item, dict) and item.get("isin"):
            parent_isin = str(item["isin"])
            break
    if parent_isin and parent_isin not in isins:
        found = lookups.names_in(question, parent_isin)
        if found:
            own = identities.get(isins[0] if isins else "") or {}
            add("names_other_company",
                "question names the parent %r (ISIN %s) where the instance entity is %s "
                "(ISIN %s)" % (found, parent_isin,
                               own.get("symbol") or own.get("name") or "?",
                               isins[0] if isins else "?"),
                "identity: equity_intelligence.master_companies[isin=%s]; parent: "
                "tasks/master_bank/MASTER_BANK.jsonl" % parent_isin)
    spoken = [isin for isin in ISIN_RX.findall(question) if isin not in isins]
    if spoken:
        other = spoken[0]
        named = lookups.identity(other)
        add("names_other_company",
            "question names ISIN %s (%s) where the instance entity is %s"
            % (other, named.get("name") or named.get("symbol") or "not in master_companies",
               identities.get(isins[0] if isins else "", {}).get("symbol") or "?"),
            "identity: equity_intelligence.master_companies[isin=%s]" % other)

    class_name = business_class(question)
    if class_name:
        applicable = class_applicable(class_name, list(identities.values()))
        count, _ = lookups.order_book_count(isins[0] if isins else "")
        note = _identity_note(identities.get(isins[0] if isins else "", {}),
                              isins[0] if isins else "")
        if class_name == "order_book":
            # its own concalls mentioning an order book are a counter-signal: then we cannot rule it out
            applicable = applicable or count > 0
            extra = "; held order-book disclosures for this name: %d" % count
            flag_source = ("concall_facts.concall_facts.db cc_items[list_name=order_book]; "
                           "identity: equity_intelligence.master_companies + "
                           "pilot/pilot60/sector_pit.db company_sector_pit")
        else:
            extra = ""
            flag_source = ("identity: equity_intelligence.master_companies[isin=%s] + "
                           "pilot/pilot60/sector_pit.db company_sector_pit"
                           % (isins[0] if isins else "?"))
        if applicable:
            add("business_type_plausible",
                "%s premise can fit %s%s; the asserted figure itself was not verified"
                % (class_name, note, extra), flag_source)
        else:
            add("business_type_mismatch",
                "%s premise does not fit %s%s" % (class_name, note, extra), flag_source)

    if LISTING_RX.search(question):
        first = lookups.first_session(isins[0] if isins else "")
        if first and first <= STORE_START:
            add("listing_premise_outside_store",
                "question presupposes a listing event for %s; its first stored session is %s, "
                "the store's first session, so no listing-day return is in the held window"
                % (identities.get(isins[0] if isins else "", {}).get("symbol") or "?", first),
                "pilot/pilot60/market_state_pilot.db company_state_daily[isin=%s]"
                % (isins[0] if isins else "?"))

    if not reasons and question.strip() == str((parent or {}).get("question") or "").strip():
        add("text_identical_generic",
            "question text is the parent's verbatim; it names no company and carries no "
            "store-checkable premise, so held data cannot rule it false",
            "tasks/pilot60/INSTANCES.jsonl; tasks/master_bank/MASTER_BANK.jsonl")

    if not reasons:
        add("premise_not_checkable",
            "no rule settled this row: no move premise in text, no parent name, no "
            "business-type keyword, no listing presupposition",
            "audit rule set: reality_engine/pilot/premise_audit.py")
    return _record(row, parent, question, identities, reasons, evidence, as_of, as_of_basis)


def _record(row: dict, parent: dict | None, question: str, identities: dict,
            reasons: list[str], evidence: list[dict], as_of: str,
            as_of_basis: str) -> dict:
    verdicts = [REASON_VERDICT.get(reason, "cannot_check") for reason in reasons]
    verdict = ("false" if "false" in verdicts else
               "cannot_check" if "cannot_check" in verdicts else "holds")
    return {
        "mid": row.get("mid"),
        "parent_mid": row.get("parent_mid"),
        "kind": row.get("kind"),
        "bucket": row.get("bucket"),
        "family": row.get("family"),
        "sector": row.get("sector"),
        "entities": [{"isin": isin,
                      "symbol": identities.get(isin, {}).get("symbol"),
                      "name": identities.get(isin, {}).get("name"),
                      "sector": identities.get(isin, {}).get("sector"),
                      "industry": identities.get(isin, {}).get("industry"),
                      "basic_industry": identities.get(isin, {}).get("basic_industry")}
                     for isin in identities],
        "question": question,
        "parent_question": str((parent or {}).get("question") or ""),
        "verdict": verdict,
        "reason": reasons[0],
        "reasons": reasons,
        "evidence": evidence,
        "as_of_used": as_of,
        "as_of_basis": as_of_basis,
        "source": evidence[0]["source"] if evidence else "",
    }


# ------------------------------------------------------------------- summaries

def summarise(records: list[dict]) -> dict:
    verdicts = collections.Counter(record["verdict"] for record in records)
    by_reason = collections.Counter(record["reason"] for record in records)
    bucket: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    family: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for record in records:
        bucket[str(record.get("bucket") or record.get("kind") or "-")][record["reason"]] += 1
        for value in record.get("family") or []:
            family[str(value)][record["reason"]] += 1
    price = [r for r in records if any(reason.startswith("price_") for reason in r["reasons"])]
    identical = [r for r in records if r.get("kind") == "stock" and
                 str(r.get("question") or "").strip() ==
                 str(r.get("parent_question") or "").strip()]
    names = [r for r in records if "names_other_company" in r["reasons"]]
    return {
        "rows": len(records),
        "verdicts": dict(verdicts),
        "by_reason": dict(by_reason),
        "by_bucket": {key: dict(value) for key, value in sorted(bucket.items())},
        "by_family": {key: dict(value) for key, value in sorted(family.items())},
        "price_premises": {
            "rows": len(price),
            "confirmed": sum(1 for r in price if "price_move_confirmed" in r["reasons"]),
            "contradicted": sum(1 for r in price
                                if "price_move_contradicted" in r["reasons"]),
            "not_checkable": sum(1 for r in price if any(
                reason in r["reasons"] for reason in
                ("price_move_not_stored", "price_date_unresolved", "price_after_as_of"))),
        },
        "identical_to_parent": len(identical),
        "identical_by_reason": dict(collections.Counter(r["reason"] for r in identical)),
        "identical_naming_parent": sum(1 for r in identical
                                       if "names_other_company" in r["reasons"]),
        "names_other_company": len(names),
    }


# ------------------------------------------------------------------- real stores

def _rows(connection, sql: str, args: tuple = ()) -> list:
    """Rows of one read-only statement (the connection's cursor is Optional to a checker)."""
    cursor = connection.execute(sql, args)
    return cursor.fetchall() if cursor is not None else []


def _row(connection, sql: str, args: tuple = ()):
    cursor = connection.execute(sql, args)
    return cursor.fetchone() if cursor is not None else None


class StoreLookups:
    """Bounded read-only lookups behind :func:`audit_row`."""

    def __init__(self, data_root: Path):
        self.eq = connect_ro(Path(data_root) / "equity_intelligence.db", timeout_s=30)
        self.pilot = connect_ro(Path(data_root) / "pilot" / "pilot60" / "market_state_pilot.db",
                                timeout_s=30, immutable=True)
        self.sector = connect_ro(Path(data_root) / "pilot" / "pilot60" / "sector_pit.db",
                                 timeout_s=30, immutable=True)
        self.concalls = connect_ro(Path(data_root) / "concall_facts.db", timeout_s=30,
                                   immutable=True)
        self._identity: dict[str, dict] = {}
        self._first: dict[str, str | None] = {}
        self._ob: dict[str, int] = {}
        self._aliases: dict[str, set[str]] = {}
        self._moves: dict[tuple[str, str], dict | None] = {}
        self._load()

    def _load(self) -> None:
        for isin, name, symbol, bse, sector, industry in _rows(
                self.eq,
                "SELECT isin, company_name, nse_symbol, bse_code, sector, industry "
                "FROM master_companies"):
            self._identity[isin] = {"name": name or "", "symbol": symbol or "",
                                    "bse_code": str(bse or ""), "sector": sector or "",
                                    "industry": industry or "", "basic_industry": ""}
        for isin, sector, industry, basic in _rows(
                self.sector,
                "SELECT isin, sector, industry, basic_industry FROM company_sector_pit "
                "WHERE valid_to IS NULL"):
            entry = self._identity.setdefault(isin, {
                "name": "", "symbol": "", "bse_code": "", "sector": "", "industry": "",
                "basic_industry": ""})
            entry.update({"sector": sector or entry["sector"],
                          "industry": industry or entry["industry"],
                          "basic_industry": basic or entry["basic_industry"]})
        for isin, count in _rows(
                self.concalls,
                "SELECT isin, COUNT(*) FROM cc_items WHERE list_name='order_book' "
                "GROUP BY isin"):
            self._ob[isin] = int(count)

    def close(self) -> None:
        for con in (self.eq, self.pilot, self.sector, self.concalls):
            con.close()

    def identity(self, isin: str) -> dict:
        return self._identity.get(isin) or {
            "name": "", "symbol": "", "bse_code": "", "sector": "", "industry": "",
            "basic_industry": ""}

    def move(self, isin: str, date: str) -> dict | None:
        key = (isin, date)
        if key in self._moves:
            return self._moves[key]
        bars = _rows(
            self.eq,
            "SELECT date, close FROM daily_price_delivery WHERE date BETWEEN "
            "date(?, '-12 day') AND date(?, '+4 day') AND isin=? ORDER BY date",
            (date, date, isin))
        source = "equity_intelligence.daily_price_delivery[isin=%s,date=%s] (NSE close)"
        if not bars:
            bars = _rows(
                self.eq,
                "SELECT date, close FROM mkt_bse_eq_daily WHERE date BETWEEN "
                "date(?, '-12 day') AND date(?, '+4 day') AND isin=? ORDER BY date",
                (date, date, isin))
            source = "equity_intelligence.mkt_bse_eq_daily[isin=%s,date=%s] (BSE close)"
        if not bars:
            bars = _rows(
                self.pilot,
                "SELECT date, close FROM company_state_daily WHERE date BETWEEN "
                "date(?, '-12 day') AND date(?, '+4 day') AND isin=? ORDER BY date",
                (date, date, isin))
            source = ("pilot/pilot60/market_state_pilot.db company_state_daily"
                      "[isin=%s,date=%s] (pilot panel close)")
        move = None
        for index, (bar_date, close) in enumerate(bars):
            if bar_date == date and index and close:
                prev_date, prev_close = bars[index - 1]
                if prev_close:
                    move = {"date": bar_date, "close": float(close),
                            "prev_date": prev_date, "prev_close": float(prev_close),
                            "basis": "close-to-close",
                            "pct": round((float(close) / float(prev_close) - 1) * 100, 4),
                            "source": source % (isin, date)}
                break
        self._moves[key] = move
        return move

    def sessions_around(self, isin: str, date: str) -> str | None:
        row = _row(
            self.pilot,
            "SELECT MIN(date), MAX(date) FROM company_state_daily WHERE isin=? "
            "AND date BETWEEN date(?, '-10 day') AND date(?, '+10 day')",
            (isin, date, date))
        if row and row[0]:
            return "sessions %s..%s" % (row[0], row[1])
        first = self.first_session(isin)
        return "first session %s" % first if first else None

    def first_session(self, isin: str) -> str | None:
        if isin not in self._first:
            row = _row(self.pilot,
                       "SELECT MIN(date) FROM company_state_daily WHERE isin=?", (isin,))
            self._first[isin] = row[0] if row and row[0] else None
        return self._first[isin]

    def order_book_count(self, isin: str) -> tuple[int, str]:
        return (self._ob.get(isin, 0),
                "concall_facts.concall_facts.db cc_items[list_name=order_book]")

    def aliases(self, isin: str) -> set[str]:
        if isin not in self._aliases:
            identity = self.identity(isin)
            self._aliases[isin] = company_aliases(
                identity.get("name"), identity.get("symbol"), identity.get("bse_code"))
        return self._aliases[isin]

    def names_in(self, question: str, isin: str) -> str | None:
        pattern = alias_regex(self.aliases(isin))
        if not pattern:
            return None
        match = pattern.search(question or "")
        return match.group(1) if match else None


# ---------------------------------------------------------------- orchestration

def load_instances(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def load_parents(path: Path) -> dict[str, dict]:
    parents = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            case = json.loads(line)
            parents[case["mid"]] = case
    return parents


def audit_all(rows: list[dict], parents: dict[str, dict], lookups) -> list[dict]:
    records = []
    for row in rows:
        parent = parents.get(str(row.get("parent_mid")))
        records.append(audit_row(row, parent, lookups))
    return records


def select_sheet_a(records: list[dict], count: int = 30, seed: int = SEED) -> list[dict]:
    """Flagged rows, seeded: three per reason with a store-backed flag, then false rows.

    ``no_substitution`` (an as_is row, nothing was substituted),
    ``premise_not_checkable`` (no specific flag) and ``price_move_confirmed`` (the
    control that passes) are not shown to Shivam as flags.
    """
    skip = ("no_substitution", "premise_not_checkable", "price_move_confirmed")
    shown = [record for record in records if record["reason"] not in skip]
    rng = random.Random(seed)
    by_reason: dict[str, list[dict]] = collections.defaultdict(list)
    for record in shown:
        by_reason[record["reason"]].append(record)
    for values in by_reason.values():
        rng.shuffle(values)
    order = sorted(by_reason, key=lambda reason: (-len(by_reason[reason]), reason))
    picked, seen = [], set()
    for reason in order:
        for record in by_reason[reason][:3]:
            picked.append(record)
            seen.add(record["mid"])
    pool = [record for record in shown if record["verdict"] == "false"
            and record["mid"] not in seen]
    rng.shuffle(pool)
    for record in pool:
        if len(picked) >= count:
            break
        picked.append(record)
    picked = sorted(picked[:count], key=lambda record: (order.index(record["reason"]),
                                                        record["mid"]))
    return picked


def sheet_a_markdown(records: list[dict], summary: dict | None = None,
                     seed: int = SEED) -> str:
    summary = summary or {k: 0 for k in ("false", "cannot_check", "rows")}
    counts = summary.get("verdicts") or {}
    price = summary.get("price_premises") or {}
    lines = [
        "# Sheet A - 30 flagged instance premises for Shivam",
        "",
        "Built from `tasks/pilot60/PREMISE_AUDIT_2026-10-31.jsonl` on 31 Oct 2026, "
        "seed `%d`. Each row below is one the audit flagged with a store-backed reason; "
        "three rows per reason, then a seeded fill from the false rows. The %s rows with "
        "no specific flag and the %s as_is rows are not shown."
        % (seed, summary.get("by_reason", {}).get("premise_not_checkable", 0),
           summary.get("by_reason", {}).get("no_substitution", 0)),
        "",
        "The audit over all 2,098 instances: **%d false**, %d `cannot_check`, %d holds. "
        "Of %d move premises, **%d of %d checkable are contradicted** by the stored close "
        "(%d not stored). **%d of 1,551 stock instances** repeat the parent's text "
        "verbatim, and %d of those still name the parent company."
        % (counts.get("false", 0), counts.get("cannot_check", 0), counts.get("holds", 0),
           price.get("rows", 0), price.get("contradicted", 0),
           price.get("contradicted", 0) + price.get("confirmed", 0),
           price.get("not_checkable", 0), summary.get("identical_to_parent", 0),
           summary.get("identical_naming_parent", 0)),
        "",
        "**Read me:** every flag below cites a value read from a store, with the store "
        "named. `false` means a stored value contradicts the premise; `cannot_check` "
        "means no held store can settle it. These are flags, not rulings.",
        "",
        "The review's decision rule (idea 3): if you call **fewer than 20** of these 30 "
        "ill-posed, the instance-repair idea is dropped. Write **Y** (ill-posed), "
        "**N** (well-posed) or **?** in the verdict column.",
        "",
    ]
    for index, record in enumerate(records, 1):
        evidence = record["evidence"][0]
        entity = (record["entities"][0] if record["entities"] else {})
        label = entity.get("symbol") or entity.get("name") or entity.get("isin") or "-"
        family = ",".join(str(value) for value in (record.get("family") or [])) or "-"
        lines += [
            "**%d. `%s`** (%s, %s, family %s) - %s" % (
                index, record["mid"], label,
                record.get("bucket") or record.get("kind"), family, record["question"]),
            "- Flag: **%s** - %s" % (record["reason"], evidence["value"]),
            "- Source: `%s` - Verdict: ______" % evidence["source"],
            "",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instances", type=Path,
                        default=repo / "tasks" / "pilot60" / "INSTANCES.jsonl")
    parser.add_argument("--bank", type=Path,
                        default=repo / "tasks" / "master_bank" / "MASTER_BANK.jsonl")
    parser.add_argument("--out", type=Path,
                        default=repo / "tasks" / "pilot60" / "PREMISE_AUDIT_2026-10-31.jsonl")
    parser.add_argument("--sheet-a", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0, help="audit only the first N rows")
    args = parser.parse_args(argv)

    rows = load_instances(args.instances)
    if args.limit:
        rows = rows[:args.limit]
    parents = load_parents(args.bank)
    data_root = Path(os.environ.get("REALITY_DATA_ROOT", repo / "reality_engine" / "data"))
    lookups = StoreLookups(data_root)
    try:
        records = audit_all(rows, parents, lookups)
    finally:
        lookups.close()
    with args.out.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary = summarise(records)
    summary["out"] = str(args.out)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.sheet_a:
        args.sheet_a.write_text(sheet_a_markdown(select_sheet_a(records), summary),
                                encoding="utf-8")
        print("sheet A ->", args.sheet_a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
