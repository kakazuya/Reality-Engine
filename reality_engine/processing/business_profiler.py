"""Wave A2 (Task A2): Business Model Profiles canonical persistence.

Replaces the demo-only ``business_model_profiles_demo`` seed with real persistence to
the canonical ``business_model_profiles`` table (SQLite fallback; PG parity via
postgres_schema.sql). Anchored to master_companies by ISIN/symbol. All seeding is
deterministic (no LLM), driven by moat_scorer.BACKFILL_CATALOG.

AGENTS.md §3: business-quality / barriers / cashflow-machine peer of the all-peers
ensemble. Every signal is quantized to the dense substrate before thesis use.
"""

from typing import Dict, Optional

from reality_engine.db.repository import Repository, repo
from reality_engine.processing.moat_scorer import ARCHETYPE_METRICS, BACKFILL_CATALOG

DERIVED_NOTES = "Derived from financials+industry heuristics FY26"

# Canonical allowed archetypes (postgres CHECK constraint). Keep mapping reuse.
# Industry keyword -> canonical archetype (vocabulary reused from existing rows)
_DERIVED_ARCHETYPE_MAP = [
    # Financial Intermediary -> Network
    (("bank", "nbfc", "finance", "financial", "insurance"), "Network"),
    # Asset-Light Services -> Subscription SaaS
    (("software", "it services", "technology", "infotech", "it "), "Subscription SaaS"),
    # Franchise/Brand -> Tollbooth
    (("fmcg", "consumer", "retail", "food", "beverage", "durables"), "Tollbooth"),
    # IP-Driven Manufacturer -> Tollbooth
    (("pharma", "pharmaceutical"), "Tollbooth"),
    # Commodity Processor -> Commodity
    (("steel", "metal", "mining", "aluminium", "aluminum", "commodity"), "Commodity"),
    # Regulated Tollbooth -> Tollbooth
    (("power", "utility", "gas", "renewable", "energy", "electric"), "Tollbooth"),
    # Asset-Heavy OEM default
    (("auto", "capital goods", "engineering", "industrial", "machinery", "construction", "equipment", "tyre", "tire"), "Asset-Heavy OEM"),
]

_BASE_RECURRENCE = {
    "Platform": 80,
    "Tollbooth": 82,
    "Subscription SaaS": 90,
    "Asset-Heavy OEM": 50,
    "Asset-Light OEM": 65,
    "Network": 80,
    "Marketplace": 70,
    "Commodity": 45,
}


def _derived_archetype_for(industry: str, sector: str) -> str:
    text = f"{industry or ''} {sector or ''}".lower()
    for keywords, arch in _DERIVED_ARCHETYPE_MAP:
        for kw in keywords:
            if kw in text:
                return arch
    return "Asset-Heavy OEM"


def _derive_business_scores(archetype: str, roce, opm, de):
    """Heuristics from roce/opm/de to recurrence/pricing/capital/leverage.

    - roce>=15 and opm>=20 -> pricing_power 5
    - de>1 -> capital_intensity 5 else moderate
    """
    try:
        roce_f = float(roce) if roce is not None else None
    except Exception:
        roce_f = None
    try:
        opm_f = float(opm) if opm is not None else None
    except Exception:
        opm_f = None
    try:
        de_f = float(de) if de is not None else None
    except Exception:
        de_f = None

    # pricing_power 1-5
    if roce_f is not None and opm_f is not None:
        if roce_f >= 15 and opm_f >= 20:
            pricing = 5
        elif roce_f >= 12 and opm_f >= 15:
            pricing = 4
        elif opm_f >= 20:
            pricing = 4
        elif opm_f >= 12 or roce_f >= 10:
            pricing = 3
        elif opm_f >= 5:
            pricing = 3
        else:
            pricing = 2
    elif opm_f is not None:
        if opm_f >= 20:
            pricing = 5
        elif opm_f >= 15:
            pricing = 4
        elif opm_f >= 10:
            pricing = 3
        else:
            pricing = 2
    else:
        # fallback to archetype default pricing from ARCHETYPE_METRICS
        pricing = ARCHETYPE_METRICS.get(archetype, ARCHETYPE_METRICS["Asset-Heavy OEM"])["pricing"]

    # capital_intensity 1-5
    if de_f is not None:
        if de_f > 1.0:
            capital = 5
        elif de_f > 0.7:
            capital = 4
        elif de_f > 0.3:
            capital = 3
        elif de_f > 0.1:
            capital = 2
        else:
            capital = 2
        # Asset-heavy archetypes stay intensive even at low leverage
        if archetype in ("Asset-Heavy OEM", "Commodity") and capital < 3:
            capital = 3
    else:
        capital = ARCHETYPE_METRICS.get(archetype, ARCHETYPE_METRICS["Asset-Heavy OEM"])["capital"]

    # recurrence: base per archetype tweaked by opm
    recurrence = _BASE_RECURRENCE.get(archetype, 50)
    if opm_f is not None:
        if opm_f >= 20:
            recurrence = min(95, recurrence + 5)
        elif opm_f < 5:
            recurrence = max(30, recurrence - 5)

    # operating_leverage 1-5
    if opm_f is not None:
        if opm_f >= 20:
            leverage = 4
        elif opm_f >= 12:
            leverage = 3
        elif opm_f < 5:
            leverage = 2
        else:
            leverage = 3
    else:
        leverage = ARCHETYPE_METRICS.get(archetype, ARCHETYPE_METRICS["Asset-Heavy OEM"])["leverage"]

    # clamp 1-5
    pricing = max(1, min(5, int(pricing)))
    capital = max(1, min(5, int(capital)))
    leverage = max(1, min(5, int(leverage)))
    recurrence = float(max(0, min(100, recurrence)))
    return recurrence, pricing, capital, leverage


def ensure_schema(manager=None, r: Optional[Repository] = None) -> Repository:
    """Create the canonical business_model_profiles table if absent."""
    rr = r or repo
    rr.ensure_business_profile_schema(manager)
    return rr


def upsert_business_profile(symbol: str, archetype: str, recurrence: float,
                            pricing_power: int, capital_intensity: int,
                            operating_leverage: int, notes: str = "",
                            isin: Optional[str] = None,
                            r: Optional[Repository] = None, manager=None) -> bool:
    """Persist (upsert) a business model profile for ``symbol``."""
    rr = r or repo
    rr.ensure_business_profile_schema(manager)
    rr.upsert_business_model_profile(
        symbol=symbol, archetype=archetype,
        revenue_recurrence_pct=recurrence, pricing_power_score=pricing_power,
        capital_intensity_score=capital_intensity,
        operating_leverage_score=operating_leverage,
        qualitative_notes=notes, isin=isin,
    )
    return True


def seed_business_profiles(top: int = 20, r: Optional[Repository] = None,
                            manager=None) -> dict:
    """Seed canonical business_model_profiles from the A2 curated catalog.

    Delegates to moat_scorer.backfill_top_n so the moat + business-profile peers
    share a single source of truth.
    """
    from reality_engine.processing.moat_scorer import backfill_top_n
    return backfill_top_n(top=top, r=r, manager=manager)


def seed_nifty200(top: Optional[int] = None, r: Optional[Repository] = None,
                  manager=None) -> dict:
    """Seed the full Nifty200 business-quality peer (curated + derived).

    Delegates to moat_scorer.backfill_nifty200 so the moat + business-profile
    peers share a single source of truth and full Nifty200 coverage.
    """
    from reality_engine.processing.moat_scorer import backfill_nifty200
    return backfill_nifty200(top=top, r=r, manager=manager)


def get_profile(symbol: str, r: Optional[Repository] = None):
    """Convenience read helper (delegates to repository)."""
    rr = r or repo
    return rr.get_business_model_profile(symbol)


def derive_universe_profiles(universe: str = "nifty200", limit: Optional[int] = None,
                             overwrite: bool = False, r: Optional[Repository] = None,
                             manager=None) -> Dict[str, int]:
    """Derive business_model_profiles for master companies having annual_financials.

    Archetype via industry keyword map reusing canonical vocabulary (Platform/
    Tollbooth/Subscription SaaS/Asset-Heavy OEM/... checked via
    business_model_profiles.archetype). Financial heuristics from
    annual_financials (roce_pct, opm_pct, debt_to_equity) blended into
    recurrence/pricing/capital/leverage.

    Idempotent: skip symbols having an existing row whose
    qualitative_notes does NOT start with 'Derived' unless overwrite=True.
    ISIN and symbol are set explicitly.

    Returns dict with counts: derived, skipped_curated, scanned, skipped_no_financials.
    """
    rr = r or (Repository(manager) if manager else repo)
    rr.ensure_business_profile_schema(manager)

    # Resolve universe companies
    try:
        if universe == "nifty500":
            comps = rr.get_all_companies(active_only=True)
            # filter is_nifty500 flag via direct SQL for reliability
            with (manager or rr.db).session() as conn:
                rows = conn.execute(
                    "SELECT * FROM master_companies WHERE is_nifty500=1 AND is_active=1 ORDER BY nse_symbol ASC"
                ).fetchall()
                comps = [dict(x) for x in rows]
        elif universe == "all":
            with (manager or rr.db).session() as conn:
                rows = conn.execute(
                    "SELECT * FROM master_companies WHERE is_active=1 ORDER BY nse_symbol ASC"
                ).fetchall()
                comps = [dict(x) for x in rows]
        else:  # nifty200 default
            comps = rr.get_nifty200_companies()
            if not comps:
                with (manager or rr.db).session() as conn:
                    rows = conn.execute(
                        "SELECT * FROM master_companies WHERE is_nifty200=1 AND is_active=1 ORDER BY nse_symbol ASC"
                    ).fetchall()
                    comps = [dict(x) for x in rows]
    except Exception:
        comps = []

    if limit is not None:
        try:
            comps = comps[: int(limit)]
        except Exception:
            pass

    scanned = len(comps)
    derived = 0
    skipped_curated = 0
    skipped_no_fin = 0

    mgr = manager or rr.db
    for c in comps:
        symbol = (c.get("nse_symbol") or "").strip()
        isin = (c.get("isin") or "").strip() or None
        if not symbol or not isin:
            # still try to resolve isin via repo helper if missing
            if not isin:
                try:
                    with mgr.session() as conn:
                        row = conn.execute("SELECT isin FROM master_companies WHERE nse_symbol=?", (symbol,)).fetchone()
                        if row and row["isin"]:
                            isin = row["isin"]
                except Exception:
                    pass
            if not symbol:
                continue

        # Idempotency: skip curated rows unless overwrite
        try:
            existing = rr.get_business_model_profile(symbol)
        except Exception:
            existing = None
        if existing is not None and not overwrite:
            notes = (existing.get("qualitative_notes") or existing.get("notes") or "") or ""
            is_derived = str(notes).startswith("Derived")
            if not is_derived:
                skipped_curated += 1
                continue
            # also skip already-derived for idempotent second run
            # (no new row needed)
            skipped_curated += 1
            continue

        # Require annual_financials for this isin/symbol
        fin_row = None
        try:
            with mgr.session() as conn:
                # Prefer isin match
                fin_row = conn.execute(
                    "SELECT roce_pct, opm_pct, debt_to_equity FROM annual_financials WHERE isin=? ORDER BY fiscal_year DESC LIMIT 1",
                    (isin,),
                ).fetchone()
                if fin_row is None and symbol:
                    fin_row = conn.execute(
                        "SELECT roce_pct, opm_pct, debt_to_equity FROM annual_financials WHERE symbol=? ORDER BY fiscal_year DESC LIMIT 1",
                        (symbol,),
                    ).fetchone()
        except Exception:
            fin_row = None
        if fin_row is None:
            skipped_no_fin += 1
            continue

        roce = fin_row["roce_pct"] if fin_row else None
        opm = fin_row["opm_pct"] if fin_row else None
        de = fin_row["debt_to_equity"] if fin_row else None

        archetype = _derived_archetype_for(c.get("industry"), c.get("sector"))
        recurrence, pricing, capital, leverage = _derive_business_scores(archetype, roce, opm, de)

        # Ensure archetype is allowed (CHECK constraint) - fallback
        allowed = {"Platform", "Tollbooth", "Subscription SaaS", "Asset-Heavy OEM", "Asset-Light OEM", "Network", "Marketplace", "Commodity"}
        if archetype not in allowed:
            archetype = "Asset-Heavy OEM"

        try:
            rr.upsert_business_model_profile(
                symbol=symbol,
                archetype=archetype,
                revenue_recurrence_pct=float(recurrence),
                pricing_power_score=int(pricing),
                capital_intensity_score=int(capital),
                operating_leverage_score=int(leverage),
                qualitative_notes=DERIVED_NOTES,
                isin=isin,
            )
            derived += 1
        except Exception:
            # constraint failure etc -> skip
            skipped_no_fin += 1
            continue

    return {
        "derived": derived,
        "business_profile": derived,
        "skipped_curated": skipped_curated,
        "scanned": scanned,
        "skipped_no_financials": skipped_no_fin,
    }


# Back-compat alias used by some harnesses
derive_profiles = derive_universe_profiles


if __name__ == "__main__":
    print("seeded:", seed_business_profiles())
