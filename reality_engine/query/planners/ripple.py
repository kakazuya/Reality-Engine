"""RIPPLE: trigger -> exposure -> transmission -> market, stopping at the gap.

Stage 1 reads ``policy_events`` (PIT ``published_at``).  When the claim-target table
is held (``macro_claim_target`` in the live DB, or the pilot DB named by
``REALITY_MACRO_PILOT_DB``), stage 2 takes the claim's own curated targets —
sector / basic industry / ISIN / theme — instead of re-parsing the free-text
``policy_events.sectors``; without it the planner falls back to the text parse so
nothing regresses.  The sector hop reads the T1 ``company_sector_pit`` as of the
decision day and falls back to today's live classification.  Every row is dated at
the window it is about and filtered through ``in_period``, so a policy or price
from another period is dropped rather than reported.  Stage 3 (cost/segment
transmission) is not held yet, so a chain that needs it says which table is
missing instead of inventing the link.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from reality_engine.query import compute

from . import envelope, fmt_num, in_period, terms_clause

CHECKED = ["equity_intelligence.policy_events", "equity_intelligence.master_companies",
           "equity_intelligence.daily_price_delivery", "macro_claim_target"]
MISSING_TABLES = ["company_cost_structure", "company_segment_pnl", "company_price_revision",
                  "macro_claim_target", "company_sector_pit"]
MAX_TARGETS = 40
MAX_CANDIDATES = 400
#: A same-day ask may still be answered by a policy announced in the run-up to it.
DATE_LOOKBACK_DAYS = 90
#: The ask prints its date to the day; a claim may be stamped a day or two either side.
#: The bench's own named-document rule uses the same three-day tolerance.
DATE_GRACE_DAYS = 3
#: Declared gaps that make a case an EVENT / corporate-action ask, not a policy one.  A
#: trigger that finds nothing on one of these cases is not a RIPPLE gap: the case's own
#: annotation says which store it needs, and none of these is a policy store.
EVENT_TABLES = {"event_day0", "event_leakage_window", "corporate_action",
                "corporate_actions", "corporate_action_register", "bulk_block_deals"}

_STATES = ("tamil nadu|karnataka|kerala|maharashtra|gujarat|rajasthan|punjab|haryana|"
           "odisha|assam|bihar|jharkhand|chhattisgarh|telangana|goa|delhi|uttarakhand|"
           "himachal pradesh|uttar pradesh|madhya pradesh|west bengal|andhra pradesh|"
           "nagaland|tripura|meghalaya|manipur|mizoram|sikkim|arunachal pradesh")
#: The issuer an ask names.  Only what the text actually names is required.
ISSUER_ASK = (
    ("state_budget", re.compile(rf"\b(state budget|state finance|{_STATES})\b", re.I)),
    ("rbi", re.compile(r"\b(rbi|reserve bank|mpc|monetary policy|repo rate|repo|reverse repo|"
                       r"sdf|msf|governor)\b", re.I)),
    ("survey", re.compile(r"\beconomic survey\b", re.I)),
    ("tariff", re.compile(r"\b(customs|tariff|tariffs|duty|duties|cbic|safeguard|anti-dumping|"
                          r"fta|export duty|import duty)\b", re.I)),
    ("union_budget", re.compile(r"\b(union budget|union finance|budget speech|the budget|"
                                r"finance commission)\b", re.I)),
    ("pib", re.compile(r"\b(pib|press release|ministry of|cabinet approves)\b", re.I)),
)
#: Which source can carry the policy when the ask names that issuer.
ISSUER_ALLOWED = {
    "state_budget": {"state_budget"},
    "rbi": {"rbi"},
    "survey": {"survey"},
    "tariff": {"tariff", "union_budget", "pib"},
    "union_budget": {"union_budget"},
    "pib": {"pib", "union_budget"},
}


def _issuer_asks(question: str) -> set[str]:
    found: set[str] = set()
    for name, pattern in ISSUER_ASK:
        if pattern.search(question):
            found |= ISSUER_ALLOWED[name]
    if "union_budget" in found and "state_budget" in found and \
            not re.search(r"\bunion\b", question, re.I):
        found.discard("union_budget")  # "the Karnataka budget" is not the Union Budget
    return found


def _issuer_class(row: dict[str, Any]) -> str:
    source = str(row.get("source_type") or "")
    kind = str(row.get("source_kind") or "")
    instrument = str(row.get("instrument") or "").lower()
    if kind == "pib" or source.startswith("PIB"):
        return "pib"
    if source.startswith("State_Budget"):
        return "state_budget"
    if source.startswith("Economic_Survey"):
        return "survey"
    if source.startswith("Union_Budget"):
        return "union_budget"
    if source.startswith("RBI"):
        return "rbi"
    if instrument in {"customs_duty", "tariff_trade"}:
        return "tariff"
    return "other"


#: Words that appear in so many claims that one of them alone is not a trigger.
#: Hinglish function words are here because the bank's Hinglish asks put them into the
#: term window where they match nothing in the corpus (``mein``, ``kyun``, ``batao``).
GENERIC_TERMS = {
    "amount", "announced", "announces", "anything", "application", "applications",
    "approval", "approved", "award", "backed", "bank", "banks", "board", "budget",
    "candidate", "capacity", "capital", "cash", "check", "collection", "company",
    "companies", "contains", "control", "cost", "costs", "cut", "cuts", "delivery",
    "demand", "disclosure", "domestic", "earlier", "effect", "exchanges", "expenditure",
    "export", "exports", "filed", "filing", "fuel", "government", "growth", "higher",
    "import", "imported", "imports", "incentive", "incentives", "india", "indian",
    "industry", "industries", "infrastructure", "investment", "later", "loan", "loans",
    "lower", "manufacturing", "market", "markets", "ministry", "national", "negative",
    "order", "other", "participation", "pays", "player", "policy", "power", "price",
    "prices", "production", "published", "quarter", "quarters", "rate", "rates",
    "reaches", "release", "retail", "rupee", "scheme", "schemes", "sector", "sectors",
    "sessions", "share", "shares", "size", "spend", "spending", "split", "state",
    "states", "statement", "subsidy", "subsidies", "tick", "timestamp", "trace",
    "turns", "unit", "weakens",
    # Hinglish / transliterated function words: filler, never a topic.
    "asar", "aur", "batao", "bhi", "dena", "dijiye", "gaya", "hai", "hain", "hua",
    "kaisa", "kaise", "kam", "kare", "karke", "kaun", "ke", "ki", "kitna", "ko",
    "kuch", "kya", "kyun", "me", "mein", "nahi", "par", "sa", "sabse", "se", "tha",
    "un", "us", "wala", "wale", "ye", "yeh", "zyada",
}

#: Ask wording -> the vocabulary the policy corpus actually uses.  Deterministic and
#: curated: a synonym only widens the search ("rationalization"/"rationalisation"), it
#: never replaces the issuer, date and topic gates below.
TRIGGER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "el nino": ("drought", "rainfall", "kharif"),
    "nino": ("drought", "rainfall", "kharif"),
    "rationalization": ("rationalisation",),
    "rationalisation": ("rationalization",),
    "green hydrogen": ("hydrogen",),
    "coal-gasification": ("gasification",),
    "gasification": ("coal gasification", "syngas"),
    "data centre": ("data center",),
    "data-centre": ("data center", "data centre"),
    "data center": ("data centre",),
    "jewellery": ("jewelry", "gems", "bullion"),
    "jewelry": ("jewellery", "gems", "bullion"),
    "bullion": ("gold",),
    "pli": ("production linked", "incentive"),
    "tax holiday": ("tax exemption", "tax incentive"),
    "buy-back": ("buyback",),
}


def _expand(terms: list[str], symbol: str = "") -> list[str]:
    """The search terms, synonym-expanded and without the ask's own ticker: a company
    name never appears in a policy row, so it must not consume a window slot."""
    drop = {symbol.lower()} if symbol else set()
    out: list[str] = []
    for term in terms:
        key = str(term).lower().strip()
        if not key or key in drop:
            continue
        if key not in out:
            out.append(key)
        for extra in TRIGGER_SYNONYMS.get(key, ()):  # one level, no recursion
            if extra not in out:
                out.append(extra)
    return out[:9]


def _topic_hits(row: dict[str, Any], terms: list[str]) -> tuple[list[str], list[str]]:
    """(terms hit in title/policy_name, terms hit only in the claim's own fields).

    The claim's ``instrument`` is one of those fields: a duty claim IS a tariff claim
    even when its title never prints the word the ask used.
    """
    head = f"{row.get('title') or ''} {row.get('policy_name') or ''}".lower()
    fields = " ".join(str(row.get(key) or "") for key in
                      ("sectors", "companies", "products", "instrument")).lower()
    title_terms = [term for term in terms if term in head]
    field_terms = [term for term in terms if term not in title_terms and term in fields]
    return title_terms, field_terms


def _declared_ids(template: object) -> list[int]:
    return [int(match) for match in re.findall(r"policy_events\.id=(\d+)",
                                               str(template or ""))]


def _scored_candidates(ctx: Any, slots: dict[str, Any], as_of: str) -> list[dict]:
    """Free-text candidates that pass issuer + date + topic gates, best score first."""
    question = str(slots.get("question") or "")
    raw_terms = [str(t).lower() for t in (slots.get("terms") or []) if len(str(t)) > 3]
    # Topical (non-generic) words first: the question order can lead with filler
    # ("weakens", "imported") and push the word that names the policy out of the window.
    # The window is eight, not four: a tariff ask opens with the company's own trade
    # ("sensitive", "heat", "exchanger") before it reaches "customs".
    terms = ([term for term in raw_terms if term not in GENERIC_TERMS] +
             [term for term in raw_terms if term in GENERIC_TERMS])[:8]
    terms = _expand(terms, str(slots.get("symbol") or ""))
    asks = _issuer_asks(question)
    # A date window is a gate when the ask names a time, and a one-year recency gate when
    # it merely has a decision date: the policy driving a 2026 question is not a 2020 one.
    basis = str(slots.get("period_basis") or "")
    lookback = 0
    windowed = basis not in {"", "none", "as_of"}
    if basis == "as_of" and as_of < "2099-01-01":
        windowed = True
        lookback = 365
    date_from = str(slots.get("date_from") or "")[:10] if windowed else ""
    date_to = str(slots.get("date_to") or "")[:10] if windowed else ""
    gate_to = date_to
    if date_from and date_from == date_to:
        lookback = max(lookback, DATE_LOOKBACK_DAYS)
    start = date_from
    if date_from:
        try:
            first = date.fromisoformat(date_from)
            # A window that starts after the decision day asks what happens next; the
            # policy behind it is already published, so the run-up is measured from the
            # decision day, not from a future window start.
            if as_of < "2099-01-01" and first > date.fromisoformat(as_of):
                anchor = date.fromisoformat(as_of)
                lookback = max(lookback, 365)
            else:
                anchor = first
            start = (anchor - timedelta(days=lookback)).isoformat()
        except ValueError:
            start = date_from
    if gate_to:
        try:  # the ask's date is printed to the day; the claim may be stamped a day later
            gate_to = (date.fromisoformat(gate_to)
                       + timedelta(days=DATE_GRACE_DAYS)).isoformat()
        except ValueError:
            pass
    clause, params = terms_clause(terms, ["p.title", "p.policy_name", "p.sectors",
                                          "p.companies", "p.products", "p.instrument"])
    # Rank the candidates in SQL by how many asked terms they carry, so a generic term
    # ("budget", "order") cannot push the real topical claims past the row limit.
    head_cols = ["lower(COALESCE(p.title,''))", "lower(COALESCE(p.policy_name,''))"]
    field_cols = ["lower(COALESCE(p.sectors,''))", "lower(COALESCE(p.companies,''))",
                  "lower(COALESCE(p.products,''))", "lower(COALESCE(p.instrument,''))"]
    terms_score, terms_params = [], []
    for term in terms:
        like = f"%{term}%"
        terms_score.append(
            " + (CASE WHEN (" + " OR ".join(f"{col} LIKE ?" for col in head_cols) + ") "
            f"THEN 3 WHEN (" + " OR ".join(f"{col} LIKE ?" for col in field_cols) + ") "
            "THEN 2 ELSE 0 END)")
        terms_params.extend([like] * (len(head_cols) + len(field_cols)))
    hits_expr = "(" + " + ".join(terms_score) + ")" if terms_score else "0"
    where = ["COALESCE(p.published_at,'') <> ''", "substr(p.published_at,1,10) <= ?"]
    args: list[Any] = [*terms_params, as_of]
    if clause:
        where.append(clause)
        args.extend(params)
    rows = ctx.rows(
        "equity_intelligence",
        "SELECT p.id, p.title, p.policy_name, p.sectors, p.companies, p.products, "
        "p.direction_for_industry, p.effective_date, p.published_at, p.quote, p.instrument, "
        f"p.source_kind, d.source_type, {hits_expr} AS hits FROM policy_events p "
        "LEFT JOIN raw_documents d ON p.source_kind='doc' AND d.doc_id = p.source_id "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY hits DESC, p.published_at DESC, p.id DESC LIMIT ?",
        args + [MAX_CANDIDATES])
    scored = []
    for row in rows:
        if asks and _issuer_class(row) not in asks:
            continue
        title_terms, field_terms = _topic_hits(row, terms)
        matched = title_terms + field_terms
        # A generic word is not a trigger: the match must carry at least one topical
        # (non-generic) term.  The issuer, when named, is an additional gate, not a
        # substitute for one.
        if not any(term not in GENERIC_TERMS for term in matched):
            continue
        title_hits, field_hits = len(title_terms), len(field_terms)
        published = str(row.get("published_at") or "")[:10]
        if not published:
            continue
        if gate_to and published > gate_to:
            continue
        if start and published < start:
            continue
        score = 3 * title_hits + 2 * field_hits + (2 if asks else 0)
        if date_to and published == date_to:
            score += 2
        scored.append((score, title_hits + field_hits, published,
                       int(row.get("id") or 0), row))
    scored.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
    # Eight, not five: the strongest-scoring claims are not always the ones whose own
    # targets map to a held ISIN, and ``plan`` walks this list until one does.
    return [item[4] for item in scored[:8]]


def _policy(ctx: Any, slots: dict[str, Any], as_of: str) -> list[dict[str, Any]]:
    """Trigger match: declared evidence id, else issuer + date window + topic overlap."""
    declared = _declared_ids(slots.get("template"))
    if declared:
        marks = ",".join("?" * len(declared))
        found = ctx.rows(
            "equity_intelligence",
            "SELECT p.id, p.title, p.policy_name, p.sectors, p.companies, p.products, "
            "p.direction_for_industry, p.effective_date, p.published_at, p.quote, "
            "p.instrument, p.source_kind, d.source_type FROM policy_events p "
            "LEFT JOIN raw_documents d ON p.source_kind='doc' AND d.doc_id = p.source_id "
            f"WHERE p.id IN ({marks}) AND COALESCE(p.published_at,'') <> '' "
            "AND substr(p.published_at,1,10) <= ?",
            [*declared, as_of])
        if found:
            order = {value: index for index, value in enumerate(declared)}
            found.sort(key=lambda row: (order.get(int(row["id"]), len(order)),
                                        str(row.get("published_at") or ""),
                                        int(row.get("id") or 0)))
            return found[:5]
    return _scored_candidates(ctx, slots, as_of)


def _targets(ctx: Any, policy: dict[str, Any]) -> list[dict[str, Any]]:
    sectors = [s.strip().lower() for s in re.split(r"[,;|]", policy.get("sectors") or "")
               if len(s.strip()) > 2][:4]
    companies = [c.strip() for c in re.split(r"[,;|]", policy.get("companies") or "")
                 if len(c.strip()) > 2][:8]
    if companies:
        clauses = " OR ".join("upper(COALESCE(company_name,'')) LIKE ?" for _ in companies)
        return ctx.rows(
            "equity_intelligence",
            f"SELECT isin, nse_symbol, company_name FROM master_companies WHERE {clauses} "
            "AND is_active=1 LIMIT 20", [f"%{c.upper()}%" for c in companies])
    if sectors:
        clauses = " OR ".join("lower(COALESCE(sector,'') || ' ' || COALESCE(industry,'')) LIKE ?"
                              for _ in sectors)
        return ctx.rows(
            "equity_intelligence",
            f"SELECT isin, nse_symbol, company_name FROM master_companies WHERE {clauses} "
            "AND is_active=1 LIMIT 25", [f"%{s}%" for s in sectors])
    return []


def _claim_target_rows(ctx: Any, policy_id: Any, as_of: str) -> tuple[list[dict], str | None]:
    """Target rows for one claim, PIT-filtered on the claim document's known_at."""
    for db in ("equity_intelligence", "macro_pilot"):
        try:
            claim = ctx.one(db, "SELECT doc_id, known_at FROM macro_claim WHERE claim_id=?",
                            (policy_id,))
        except Exception:  # noqa: BLE001 - a DDL-built table may not carry the pilot column
            try:
                claim = ctx.one(db, "SELECT doc_id FROM macro_claim WHERE claim_id=?",
                                (policy_id,))
            except Exception:  # noqa: BLE001 - the table is a pilot, not every root has it
                continue
        if not claim:
            continue
        known = str(claim.get("known_at") or "")
        if not known:
            doc = ctx.one(db, "SELECT known_at FROM macro_doc WHERE doc_id=?",
                          (claim.get("doc_id"),))
            known = str((doc or {}).get("known_at") or "")
        if not known or known[:10] > as_of:
            continue
        rows = ctx.rows(
            db,
            "SELECT target_kind, target_id, direction, weight FROM macro_claim_target "
            "WHERE claim_id=? ORDER BY weight DESC, target_kind, target_id LIMIT ?",
            (policy_id, MAX_TARGETS))
        if rows:
            return rows, db
    return [], None


def _claim_meta(ctx: Any, db: str, policy_id: Any) -> dict[str, Any] | None:
    """The claim's parsed effective date and its confidence (pilot-only columns)."""
    try:
        return ctx.one(db, "SELECT effective_date, effective_pit_conf, known_at "
                           "FROM macro_claim WHERE claim_id=?", (policy_id,))
    except Exception:  # noqa: BLE001 - an older pilot DB has no pit_conf column
        try:
            return ctx.one(db, "SELECT effective_date, known_at FROM macro_claim "
                               "WHERE claim_id=?", (policy_id,))
        except Exception:  # noqa: BLE001
            return None


def _company_rows(ctx: Any, sql: str, args: tuple) -> list[dict]:
    try:
        return ctx.rows("equity_intelligence", sql, args)
    except Exception:  # noqa: BLE001 - a fixture root may hold only one industry table
        return []


def _sector_targets(ctx: Any, kind: str, ident: str, as_of: str) -> list[dict[str, Any]]:
    """Held ISINs in a sector/basic industry at ``as_of``: the PIT store, else live.

    ``company_sector_pit`` is piecewise-constant (``valid_from``/``valid_to``), so a
    label adopted after the decision day is not used before it.  A root without the
    T1 build falls back to today's classification, which is stated as degraded.
    """
    column = "basic_industry" if kind == "basic_industry" else "sector"
    for db in ("sector_pit", "market_state"):
        try:
            rows = ctx.rows(
                db,
                f"SELECT isin FROM company_sector_pit WHERE {column} = ? "
                "AND valid_from <= ? AND (valid_to IS NULL OR valid_to >= ?) "
                "ORDER BY isin LIMIT ?", (ident, as_of, as_of, MAX_TARGETS))
            if rows:
                return rows
        except Exception:  # noqa: BLE001 - the PIT store is optional in a fixture root
            continue
    rows = _company_rows(
        ctx,
        f"SELECT isin, symbol AS nse_symbol FROM company_industry WHERE {column} = ? "
        "LIMIT ?", (ident, MAX_TARGETS))
    if not rows and kind == "sector":
        rows = _company_rows(
            ctx, "SELECT isin, nse_symbol, company_name FROM master_companies "
                 "WHERE is_active=1 AND (sector = ? OR industry = ?) LIMIT ?",
            (ident, ident, MAX_TARGETS))
    return rows


#: Theme id -> the thematic NSE index whose members are held in
#: ``company_membership_pit``.  Only a theme with a real index is listed: a curated
#: guess would be a membership claim the table cannot support.
THEME_INDEX = {"defence": "niftyindiadefence", "omc_refining": "niftyoilgas"}
#: A commodity's own wording in ``company_cost_structure.input_key``.
COMMODITY_COST_ALIASES = {
    "coal": ("coal", "coking", "coking_coal"), "crude": ("crude", "fuel", "brent"),
    "natural gas": ("gas", "lng"), "steel": ("steel", "iron"), "aluminium": ("alum"),
    "copper": ("copper",), "power": ("power",), "freight": ("freight",),
    "cotton": ("cotton", "yarn"), "rubber": ("rubber",), "gold": ("gold", "bullion"),
    "silver": ("silver",), "palm oil": ("palm", "edible"), "urea": ("urea", "fertil"),
}
#: A state budget's named state -> the held project/product rows that place a plant
#: there.  The extraction store is the only held facility-location source; when it does
#: not carry the state the hop says so instead of guessing an ISIN.
STATE_SOURCES = (
    ("capex_project", "project", "quote"),
    ("company_capacity_utilisation", "product", "quote"),
)


def _theme_targets(ctx: Any, ident: str, as_of: str) -> list[dict[str, Any]]:
    """Theme members from ``company_membership_pit`` (thematic indices, pilot (b) store)."""
    index_code = THEME_INDEX.get(str(ident).lower().replace("-", "_"))
    if not index_code:
        return []
    try:
        return ctx.rows(
            "market_state_b",
            "SELECT isin FROM company_membership_pit WHERE index_code = ? "
            "AND added_on <= ? AND (removed_on IS NULL OR removed_on >= ?) "
            "ORDER BY isin LIMIT ?", (index_code, as_of, as_of, MAX_TARGETS))
    except Exception:  # noqa: BLE001 - the pilot (b) store is optional
        return []


def _commodity_targets(ctx: Any, ident: str, as_of: str) -> tuple[list[dict], str | None]:
    """Commodity users/producers: held input-share rows, then the industry map.

    ``company_cost_structure`` names the inputs a company buys (``coking_coal``,
    ``fuel``); the claim builder's own product -> industry map names the industries that
    produce or consume the commodity.  Either route returns held ISINs only.
    """
    from reality_engine.pilot.macro_claims import PRODUCT_TERMS  # the one curated map

    key = " ".join(str(ident or "").lower().replace("_", " ").split())
    if not key:
        return [], None
    found: list[dict[str, Any]] = []
    aliases = {key} | set(COMMODITY_COST_ALIASES.get(key, ()))
    clauses = " OR ".join("lower(COALESCE(input_key,'')) LIKE ?" for _ in aliases)
    try:
        found += ctx.rows(
            "metric_state",
            f"SELECT DISTINCT isin FROM company_cost_structure WHERE known_at <= ? "
            f"AND ({clauses}) ORDER BY isin LIMIT ?",
            [as_of, *[f"%{alias}%" for alias in sorted(aliases)], MAX_TARGETS])
    except Exception:  # noqa: BLE001 - the extraction store is optional
        pass
    for term, industries in PRODUCT_TERMS.items():
        if key != term and not re.search(r"\b" + re.escape(term) + r"\b", key):
            continue
        for kind, industry in industries:
            if len(found) >= MAX_TARGETS:
                break
            found += _sector_targets(ctx, kind, industry, as_of)
    if found:
        return found, None
    return [], (f"commodity '{ident}' has no held cost-structure row or industry map")


def _state_targets(ctx: Any, ident: str, as_of: str) -> list[dict[str, Any]]:
    """Held ISINs with a plant/product that names the state (extraction store)."""
    state = str(ident or "").lower()
    if not state:
        return []
    found: list[dict[str, Any]] = []
    for table, name_col, quote_col in STATE_SOURCES:
        try:
            found += ctx.rows(
                "metric_state",
                f"SELECT DISTINCT isin FROM {table} WHERE known_at <= ? AND ("
                f"lower(COALESCE({name_col},'')) LIKE ? OR "
                f"lower(COALESCE({quote_col},'')) LIKE ?) ORDER BY isin LIMIT ?",
                (as_of, f"%{state}%", f"%{state}%", MAX_TARGETS))
        except Exception:  # noqa: BLE001 - the extraction store is optional
            continue
        if len(found) >= MAX_TARGETS:
            break
    return found[:MAX_TARGETS]


def _targets_from_claims(ctx: Any, rows: list[dict], as_of: str) -> tuple[list[dict], list[str]]:
    """macro_claim_target -> held ISINs (any of the six target kinds)."""
    found: dict[str, dict] = {}
    notes: list[str] = []

    def add(company: dict, kind: str, ident: str) -> None:
        isin = str(company.get("isin") or "")
        if isin and isin not in found and len(found) < MAX_TARGETS:
            found[isin] = {"isin": isin, "nse_symbol": company.get("nse_symbol"),
                           "company_name": company.get("company_name"),
                           "target_kind": kind, "target_id": ident}

    for target in rows:
        kind, ident = str(target.get("target_kind") or ""), str(target.get("target_id") or "")
        if kind == "isin":
            add({"isin": ident}, kind, ident)
        elif kind in ("sector", "basic_industry"):
            for row in _sector_targets(ctx, kind, ident, as_of):
                add(row, kind, ident)
        elif kind == "theme":
            theme_rows = _theme_targets(ctx, ident, as_of)
            for row in theme_rows:
                add(row, kind, ident)
            if not theme_rows:
                notes.append(f"theme '{ident}' has no thematic index in "
                             "company_membership_pit")
        elif kind == "state":
            state_rows = _state_targets(ctx, ident, as_of)
            for row in state_rows:
                add(row, kind, ident)
            if not state_rows:
                notes.append(f"state '{ident}' has no held plant/location fact "
                             "(extract_pilot60 capex_project/company_capacity_utilisation)")
        elif kind == "commodity":
            commodity_rows, note = _commodity_targets(ctx, ident, as_of)
            for row in commodity_rows:
                add(row, kind, ident)
            if note:
                notes.append(note)
        else:
            notes.append(f"{kind} target '{ident}' has no held ISIN map")
    return list(found.values()), notes


def _market(ctx: Any, isins: list[str], start: str, end: str) -> dict[str, float]:
    if not isins:
        return {}
    try:
        marks = ",".join("?" * len(isins))
        rows = ctx.rows(
            "equity_intelligence",
            "SELECT isin, date, close FROM daily_price_delivery "
            f"WHERE isin IN ({marks}) AND date >= ? AND date <= ? ORDER BY isin, date",
            [*isins, start, end])
    except Exception:
        return {}
    bucket: dict[str, list[tuple[str, float]]] = {}
    for row in rows:
        bucket.setdefault(row["isin"], []).append((row["date"], row["close"]))
    out = {}
    for isin, points in bucket.items():
        ret, _, _ = compute.window_return(points)
        if ret is not None:
            out[isin] = ret
    return out


def plan(slots: dict[str, Any], as_of: str, ctx: Any) -> dict[str, Any]:
    if not slots.get("needs", {}).get("ripple"):
        return envelope("RIPPLE", ok=True, na=True, checked=CHECKED,
                        detail="no policy/ripple chain asked; RIPPLE not applicable")
    status = str(slots.get("status") or "")
    declared = status.split(":", 1)[-1] if ":" in status else ""
    gate_table = declared if status.startswith("needs_new_table:") else None
    try:
        policies = _policy(ctx, slots, as_of)
    except Exception as exc:  # noqa: BLE001
        return envelope("RIPPLE", ok=False, why="tool", checked=CHECKED,
                        detail=f"policy store failed: {type(exc).__name__}: {exc}")
    if not policies:
        detail = f"no policy event matching the ask published on or before {as_of}"
        if declared in EVENT_TABLES:
            # The case's own gap is an event / corporate-action store, so it is an EVENT
            # ask: no policy trigger exists to find, and this is not a RIPPLE failure.
            return envelope("RIPPLE", ok=True, na=True, checked=CHECKED,
                            detail=f"{detail}; the case's gap is {declared}, not a policy "
                                   "store: RIPPLE not applicable")
        if gate_table:
            return envelope("RIPPLE", ok=False, why="schema", checked=CHECKED, gap=gate_table,
                            detail=f"{detail}; the chain needs {gate_table}",
                            nid_reason=f"BLOCKED_SCHEMA: {gate_table}")
        return envelope("RIPPLE", ok=False, why="no_doc", checked=CHECKED,
                        detail=detail, nid_reason=detail)
    # A trigger whose targets map to no held ISIN is not the chain the ask wants:
    # keep the next-best trigger instead of answering "schema gap" on the first one.
    policy = claim_meta = None
    targets: list[dict[str, Any]] = []
    claim_notes: list[str] = []
    target_source = ""
    for candidate in policies:
        rows, db = _claim_target_rows(ctx, candidate["id"], as_of)
        meta = _claim_meta(ctx, db, candidate["id"]) if db else None
        mapped, notes = _targets_from_claims(ctx, rows, as_of) if rows else ([], [])
        found = mapped or _targets(ctx, candidate)
        if not found:
            continue
        policy, claim_meta, targets = candidate, meta, found
        claim_notes = notes
        target_source = (f"macro_claim_target ({db})" if mapped else "policy_events.sectors")
        break
    if policy is None:
        if declared in EVENT_TABLES:
            # The case's own gap is an event / corporate-action store and the trigger
            # found nothing it can map: this is not a RIPPLE answer to give either way.
            return envelope("RIPPLE", ok=True, na=True, checked=CHECKED,
                            detail=f"no policy trigger with held targets; the case's gap "
                                   f"is {declared}, not a policy store: RIPPLE not applicable")
        policy = policies[0]
        rows, db = _claim_target_rows(ctx, policy["id"], as_of)
        claim_notes = (_targets_from_claims(ctx, rows, as_of)[1] if rows else [])
        # Name the store that would close the gap, from the target kinds the claim
        # actually carries (a state target needs a facility map, not a sector one).
        kinds = {str(row.get("target_kind") or "") for row in rows}
        missing = gate_table or next(
            (table for kind, table in (("state", "company_facilities_pit"),
                                       ("theme", "company_theme_pit"),
                                       ("commodity", "company_cost_structure"),
                                       ("sector", "company_sector_pit"),
                                       ("basic_industry", "company_sector_pit"))
             if kind in kinds), "macro_claim_target")
        detail = (f"policy {policy.get('title') or policy.get('policy_name')} matched, but its "
                  f"sector/company targets do not map to held ISINs ({missing})")
        if claim_notes:
            detail += "; " + "; ".join(claim_notes[:2])
        return envelope("RIPPLE", ok=False, why="schema", checked=CHECKED, gap=missing,
                        detail=detail, nid_reason=detail)
    # The market window anchors on the parsed effective date only when the parse is
    # precise enough to trust; a prose date ("end of 2026") falls back to publication,
    # which is the day the market actually learns of the policy.
    published = str(policy.get("published_at") or as_of)[:10]
    anchor, anchor_conf = published, 0.0
    if claim_meta and claim_meta.get("effective_date"):
        effective = str(claim_meta["effective_date"])[:10]
        confidence = float(claim_meta.get("effective_pit_conf") or 0.0)
        if published <= effective <= as_of and confidence >= 0.7:
            anchor, anchor_conf = effective, confidence
    # An ask that names its own window is about that window's move, not the policy's
    # publication day: measure the window the router resolved, with a few sessions of
    # baseline before it, so the row it returns is dated inside the ask.
    basis = str(slots.get("period_basis") or "")
    asked_from = str(slots.get("date_from") or "")[:10]
    asked_to = str(slots.get("date_to") or "")[:10]
    windowed = basis in ("named date", "named dates", "month", "month span",
                         "quarter end", "fiscal year end", "quarter span",
                         "fiscal year span", "since")
    if windowed and len(asked_from) == 10:
        period_label = asked_from
        start = (date.fromisoformat(asked_from) - timedelta(days=5)).isoformat()
        end = min(asked_to if len(asked_to) == 10 and asked_to >= asked_from else asked_from,
                  as_of)
    else:
        period_label = anchor
        start = (date.fromisoformat(anchor) - timedelta(days=5)).isoformat()
        end = min((date.fromisoformat(anchor) + timedelta(days=10)).isoformat(), as_of)
    moves = _market(ctx, [t["isin"] for t in targets], start, end)
    names = {t["isin"]: t["nse_symbol"] for t in targets}
    ranked = sorted(moves.items(), key=lambda item: item[1], reverse=True)
    detail = (f"trigger: {policy.get('policy_name') or policy.get('title')} "
              f"(known {published}, effective {anchor}"
              + (f" pit_conf {anchor_conf:.2f}" if anchor_conf else "")
              + f"); {len(targets)} held target(s) via {target_source}")
    if ranked:
        detail += "; market: " + ", ".join(f"{names.get(i) or i} {fmt_num(v)}%"
                                           for i, v in ranked[:4])
    degraded = ["transmission hop (input share / pass-through) is not held: "
                "company_cost_structure, company_segment_pnl"]
    if claim_notes:
        degraded.append("claim target map: " + "; ".join(claim_notes[:3]))
    # Rows are dated at the window they are about, so a policy/price from another
    # period is dropped here instead of being reported as this period's answer.
    rows = [{"ref": f"policy_events:{policy['id']}", "known_at": published,
             "period": published, "item": "policy",
             "title": policy.get("title") or policy.get("policy_name")}] + [
        {"ref": f"daily_price_delivery:{isin}", "known_at": end, "period": period_label,
         "isin": isin, "item": "window return", "return_pct": value, "value": value}
        for isin, value in ranked[:10]]
    kept = in_period(rows, slots, hop="RIPPLE")
    if len(kept) < len(rows):
        degraded.append(f"{len(rows) - len(kept)} row(s) outside the asked period were "
                        "dropped")
    if not kept:
        detail = (f"policy {policy.get('policy_name') or policy.get('title')} matched with "
                  f"{len(targets)} held target(s), but no row about it falls in the asked "
                  f"period ({asked_from}..{asked_to or asked_from})")
        return envelope("RIPPLE", ok=False, why="no_doc", checked=CHECKED, degraded=degraded,
                        detail=detail, nid_reason=detail)
    return envelope(
        "RIPPLE", ok=True, gap=None, rows=kept,
        provenance=[{"ref": f"policy_events:{policy['id']}", "known_at": published}],
        pit=f"claim published_at <= {as_of}; market rows date <= {as_of}", checked=CHECKED,
        degraded=degraded, detail=detail)
