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
}


def _topic_hits(row: dict[str, Any], terms: list[str]) -> tuple[list[str], list[str]]:
    """(terms hit in title/policy_name, terms hit only in sector/company/product)."""
    head = f"{row.get('title') or ''} {row.get('policy_name') or ''}".lower()
    fields = " ".join(str(row.get(key) or "")
                      for key in ("sectors", "companies", "products")).lower()
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
    terms = ([term for term in raw_terms if term not in GENERIC_TERMS] +
             [term for term in raw_terms if term in GENERIC_TERMS])[:4]
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
    if date_from and date_from == date_to:
        lookback = max(lookback, DATE_LOOKBACK_DAYS)
    start = date_from
    if date_from:
        try:
            start = (date.fromisoformat(date_from) - timedelta(days=lookback)).isoformat()
        except ValueError:
            start = date_from
    clause, params = terms_clause(terms, ["p.title", "p.policy_name", "p.sectors",
                                          "p.companies", "p.products"])
    # Rank the candidates in SQL by how many asked terms they carry, so a generic term
    # ("budget", "order") cannot push the real topical claims past the row limit.
    head_cols = ["lower(COALESCE(p.title,''))", "lower(COALESCE(p.policy_name,''))"]
    field_cols = ["lower(COALESCE(p.sectors,''))", "lower(COALESCE(p.companies,''))",
                  "lower(COALESCE(p.products,''))"]
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
        if date_to and published > date_to:
            continue
        if start and published < start:
            continue
        score = 3 * title_hits + 2 * field_hits + (2 if asks else 0)
        if date_to and published == date_to:
            score += 2
        scored.append((score, title_hits + field_hits, published,
                       int(row.get("id") or 0), row))
    scored.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
    return [item[4] for item in scored[:5]]


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
    try:
        rows = ctx.rows(
            "market_state",
            f"SELECT isin FROM company_sector_pit WHERE {column} = ? "
            "AND valid_from <= ? AND (valid_to IS NULL OR valid_to >= ?) "
            "ORDER BY isin LIMIT ?", (ident, as_of, as_of, MAX_TARGETS))
        if rows:
            return rows
    except Exception:  # noqa: BLE001 - the T1 store is optional in a fixture root
        pass
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


def _targets_from_claims(ctx: Any, rows: list[dict], as_of: str) -> tuple[list[dict], list[str]]:
    """macro_claim_target -> held ISINs (sector/basic_industry/isin/theme)."""
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
            try:
                theme_rows = ctx.rows(
                    "equity_intelligence",
                    "SELECT isin FROM universe_membership WHERE theme=? "
                    "AND (valid_from IS NULL OR valid_from<=?) "
                    "AND (valid_to IS NULL OR valid_to>=?) LIMIT ?",
                    (ident, as_of, as_of, MAX_TARGETS))
            except Exception:  # noqa: BLE001 - theme membership is not built in the live DB
                theme_rows = []
            for row in theme_rows:
                add(row, kind, ident)
            if not theme_rows:
                notes.append(f"theme '{ident}' membership table not held")
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
    gate_table = (status.split(":", 1)[-1] if status.startswith("needs_new_table:") else None)
    try:
        policies = _policy(ctx, slots, as_of)
    except Exception as exc:  # noqa: BLE001
        return envelope("RIPPLE", ok=False, why="tool", checked=CHECKED,
                        detail=f"policy store failed: {type(exc).__name__}: {exc}")
    if not policies:
        detail = f"no policy event matching the ask published on or before {as_of}"
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
        policy = policies[0]
        rows, db = _claim_target_rows(ctx, policy["id"], as_of)
        claim_notes = (_targets_from_claims(ctx, rows, as_of)[1] if rows else [])
        missing = gate_table or ("macro_claim_target" if rows else "company_sector_pit")
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
