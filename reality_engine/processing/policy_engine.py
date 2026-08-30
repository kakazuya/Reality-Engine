"""Wave B1 (Task B1): Policy ENI peer — canonical dense-substrate persistence.

Formula: ENI = Severity(-5..+5) x Probability(0..1) -> net_impact_score.
          AggENI = SUM(net_impact_score); policy peer passes when AggENI >= 0.

This module promotes the in-memory PolicyRisk ENI dataclass (Task 6) into a
persisted, queryable signal on the dense substrate (regulatory_political_risks),
per AGENTS.md Sec.3 (all-peers ensemble; every signal quantized before thesis).
All helpers are deterministic (no LLM) and ISIN/symbol anchored via
master_companies. PostgreSQL already defines regulatory_political_risks (with a
GENERATED net_impact_score); the SQLite WAL fallback has no GENERATED columns, so
net_impact_score is computed in Python and stored explicitly here.

File ownership (Wave B1 isolation):
  - This file (policy_engine.py) — policy peer logic + persistence orchestration.
  - repository.py — additive regulatory_political_risks helpers only.
  - tests/test_policy_eni.py — deterministic acceptance tests.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from reality_engine.db.repository import Repository, repo


@dataclass
class PolicyRisk:
    """A single regulatory/political risk or tailwind for a symbol.

    ``eni`` (Effective Net Impact) is the canonical ENI score = severity x probability.
    """

    policy_name: str
    severity: float  # -5 to +5 (positive = beneficial, negative = adverse)
    probability: float  # 0 to 1
    time_horizon: str = "Mid-term"
    factor_type: Optional[str] = None
    risk_type: Optional[str] = None

    @property
    def eni(self) -> float:
        """Effective Net Impact = severity x probability (rounded to 2dp)."""
        return round(self.severity * self.probability, 2)

    @staticmethod
    def risk_type_for(severity: float) -> str:
        """Map signed severity to canonical risk_type.

        Positive -> Tailwind, negative -> Headwind, zero -> Auxiliary.
        """
        if severity > 0:
            return "Tailwind"
        if severity < 0:
            return "Headwind"
        return "Auxiliary"


def clamp_severity(value: float) -> float:
    """Clamp severity into the valid [-5, +5] band."""
    return max(-5.0, min(5.0, float(value)))


def clamp_probability(value: float) -> float:
    """Clamp probability into the valid [0, 1] band."""
    return max(0.0, min(1.0, float(value)))


def infer_factor_type(policy_name: str) -> str:
    """Infer the regulatory factor_type from a policy-name keyword heuristic.

    Used only when the caller does not supply an explicit factor_type. Default "Tariff".
    """
    n = (policy_name or "").lower()
    if any(k in n for k in ("duty", "tariff", "cust", "customs", "import", "export", "anti-dumping")):
        return "Tariff"
    if any(k in n for k in ("pli", "subsidy", "incentive", "sop", "grant", "production linked")):
        return "Subsidy"
    if any(k in n for k in ("antitrust", "penalty", "fine", "cartel", "competition")):
        return "Antitrust"
    if any(k in n for k in ("environment", "emission", "esg", "carbon", "pollution")):
        return "Environmental"
    if any(k in n for k in ("fx", "rupee", "currency", "dollar", "exchange")):
        return "FX"
    if any(k in n for k in ("gst", "tax", "cess", "levy")):
        return "Tax"
    return "Tariff"


def agg_policy_score(risks: List[PolicyRisk]) -> float:
    """Aggregate ENI across a list of PolicyRisk (sum of eni), rounded to 2dp."""
    return round(sum(r.eni for r in risks), 2)


# ---------------------------------------------------------------------------
# Canonical seed catalog (deterministic; mirrors moat_scorer.BACKFILL_CATALOG).
# Tuple order: (policy_name, severity, probability, factor_type, time_horizon)
# ---------------------------------------------------------------------------
CANONICAL_POLICY_RISKS: Dict[str, List[tuple]] = {
    # Steel producer: steel customs-duty headwind dominates a smaller PLI tailwind
    # -> AggENI < 0 (fails the policy gate). Acceptance case: Steel Cust Duty Hike
    # ENI = -3.8 * 0.85 = -3.23 (Headwind).
    "TATASTEEL": [
        ("Steel Cust Duty Hike", -3.8, 0.85, "Tariff", "Short-term"),
        ("PLI Speciality Steel", 2.5, 0.60, "Subsidy", "Structural"),
    ],
    # Defence OEM: PLI Defence tailwind + indigenisation capex tailwind -> AggENI > 0
    # (passes). PLI Defence ENI = 4.2 * 0.70 = 2.94.
    "HAL": [
        ("PLI Defence", 4.2, 0.70, "Subsidy", "Structural"),
        ("Defence Indigenisation Capex", 1.5, 0.90, "Subsidy", "Mid-term"),
    ],
    # Packaging film: RM duty headwind only -> AggENI < 0 (fails).
    "POLYPLEX": [
        ("Packaging RM Duty Headwind", -2.0, 0.70, "Tariff", "Mid-term"),
    ],
    # Energy transition beneficiary -> AggENI > 0 (passes).
    "RELIANCE": [
        ("Green Energy Transition Tailwind", 2.0, 0.80, "Subsidy", "Structural"),
    ],
}


# ---------------------------------------------------------------------------
# Expanded canonical macro-policy canon (Peer 3 — Policy Macro substrate promotion).
# ~40 rows across 24 symbols spanning 20+ distinct macro/policy levers so that
# AggENI (SUM(severity*prob)) is queryable per stock and the policy peer gate
# (is_policy_approved = AggENI >= 0) has both PASS and FAIL examples.
# Tuple order mirrors CANONICAL_POLICY_RISKS:
#   (policy_name, severity, probability, factor_type, time_horizon)
# Severity band [-5,+5]; positive = Tailwind, negative = Headwind.
# ---------------------------------------------------------------------------
CANONICAL_POLICY_RISKS_FULL: Dict[str, List[tuple]] = {
    # --- Rail / Capital Goods (Union Budget 2026 Rail Capex tailwind) ---
    "TITAGARH": [
        ("Union Budget 2026 Rail Capex", 4.0, 0.85, "Subsidy", "Structural"),
        ("Dedicated Freight Corridor Phase-2", 1.5, 0.60, "Subsidy", "Mid-term"),
    ],
    "BHEL": [
        ("Union Budget 2026 Rail Capex", 3.5, 0.80, "Subsidy", "Structural"),
        ("Thermal Capacity Addition Capex", 1.5, 0.65, "Subsidy", "Mid-term"),
    ],
    # --- Defence Indigenization DAP (tailwind HAL / BEL) ---
    "HAL": [
        ("Defence Indigenization DAP", 4.2, 0.80, "Subsidy", "Structural"),
        ("PLI Defence", 2.0, 0.70, "Subsidy", "Structural"),
    ],
    "BEL": [
        ("Defence Indigenization DAP", 3.8, 0.80, "Subsidy", "Structural"),
        ("PLI Defence", 1.5, 0.65, "Subsidy", "Structural"),
    ],
    # --- PM Surya Ghar Solar (tailwind HAVELLS / Tata Power) ---
    "HAVELLS": [
        ("PM Surya Ghar Solar", 3.0, 0.75, "Subsidy", "Mid-term"),
    ],
    "TATAPOWER": [
        ("PM Surya Ghar Solar", 3.5, 0.70, "Subsidy", "Mid-term"),
        ("Green Energy Transition Tailwind", 2.0, 0.75, "Subsidy", "Structural"),
    ],
    # --- PLI Semiconductor (tailwind KAYNES / DIXON) ---
    "KAYNES": [
        ("PLI Semiconductor", 3.5, 0.70, "Subsidy", "Structural"),
        ("Electronics Component PLI", 1.5, 0.60, "Subsidy", "Structural"),
    ],
    "DIXON": [
        ("PLI Semiconductor", 4.0, 0.75, "Subsidy", "Structural"),
        ("Electronics Component PLI", 2.0, 0.60, "Subsidy", "Structural"),
    ],
    # --- Steel customs-duty headwind (dominates PLI offset -> FAIL) ---
    "TATASTEEL": [
        ("Steel Customs Duty Hike", -3.8, 0.85, "Tariff", "Short-term"),
        ("PLI Speciality Steel", 2.5, 0.60, "Subsidy", "Structural"),
    ],
    "JSWSTEEL": [
        ("Steel Customs Duty Hike", -3.5, 0.80, "Tariff", "Short-term"),
        ("PLI Speciality Steel", 2.0, 0.55, "Subsidy", "Structural"),
    ],
    # --- Crude-oil / FX headwind (paint, airlines) + policy-adjacent Red Sea ---
    "ASIANPAINT": [
        ("Crude Oil Price Headwind", -2.5, 0.65, "FX", "Mid-term"),
        ("GST Rationalisation Paint", 0.5, 0.50, "Tax", "Mid-term"),
    ],
    "BERGERPAINT": [
        ("Crude Oil Price Headwind", -2.3, 0.60, "FX", "Mid-term"),
    ],
    "INDIGO": [
        ("Crude Oil Price Headwind", -3.0, 0.70, "FX", "Mid-term"),
    ],
    "SCI": [
        ("Red Sea Shipping Disruption", -2.0, 0.55, "Tariff", "Short-term"),
    ],
    # --- Crude-oil windfall tax headwind offset by green transition -> PASS ---
    "RELIANCE": [
        ("Crude Oil Windfall Tax", -2.0, 0.50, "Tax", "Mid-term"),
        ("Green Energy Transition Tailwind", 2.5, 0.80, "Subsidy", "Structural"),
    ],
    # --- Auto / EV policy tailwind ---
    "MARUTI": [
        ("PLI Auto / EV Policy", 2.5, 0.70, "Subsidy", "Structural"),
        ("Scrappage Policy Tailwind", 1.0, 0.55, "Tax", "Mid-term"),
    ],
    "TATAMOTORS": [
        ("PLI Auto / EV Policy", 2.8, 0.70, "Subsidy", "Structural"),
        ("Import Duty Headwind Components", -1.0, 0.45, "Tariff", "Short-term"),
    ],
    # --- Pharma PLI tailwind offsetting US FDA risk -> PASS ---
    "SUNPHARMA": [
        ("PLI Pharma", 2.0, 0.60, "Subsidy", "Structural"),
        ("US FDA Form-483 Risk", -1.5, 0.40, "Antitrust", "Short-term"),
    ],
    # --- Banking: RBI repo-cut tailwind ---
    "HDFCBANK": [
        ("RBI Repo Rate Cut Tailwind", 1.5, 0.55, "FX", "Mid-term"),
    ],
    # --- Textiles: US tariff relief tailwind ---
    "KPRMILL": [
        ("US Tariff Relief Textile", 2.5, 0.50, "Tariff", "Mid-term"),
        ("PLI Textiles", 1.0, 0.50, "Subsidy", "Structural"),
    ],
    # --- Cement: green-cement subsidy tailwind ---
    "ULTRACEMCO": [
        ("Green Cement Subsidy", 1.5, 0.50, "Subsidy", "Mid-term"),
    ],
    # --- Telecom: 5G PLI tailwind offsetting AGR dues -> PASS ---
    "BHARTIARTL": [
        ("5G Capex PLI", 2.0, 0.65, "Subsidy", "Mid-term"),
        ("AGR Dues Headwind", -1.5, 0.45, "Tax", "Short-term"),
    ],
    # --- IT: Digital India tailwind (US visa headwind dropped to keep canon ~40) ---
    "TCS": [
        ("Digital India / GovTech Tailwind", 1.5, 0.55, "Subsidy", "Structural"),
    ],
    # --- Packaging: RM duty headwind only -> FAIL ---
    "POLYPLEX": [
        ("Packaging RM Duty Headwind", -2.0, 0.70, "Tariff", "Mid-term"),
    ],
}


def seed_canonical_policy_risks_full(r: Optional[Repository] = None, manager=None) -> Dict[str, Any]:
    """Seed the full canonical macro-policy canon (~40 rows, 24 symbols).

    Promotes each (symbol, policy) into ``regulatory_political_risks`` on the
    dense substrate via :func:`upsert_policy_risk`. Returns a summary dict with
    per-symbol row counts, total rows, and the lists of symbols passing /
    failing the policy peer gate (``is_policy_approved = AggENI >= 0``), so the
    ENI quantization (AggENI = SUM(severity*prob)) is testable end-to-end.
    """
    rr = r or (Repository(manager) if manager else repo)
    rr.ensure_regulatory_political_risks_schema(manager)
    counts: Dict[str, int] = {}
    for symbol, rows in CANONICAL_POLICY_RISKS_FULL.items():
        n = 0
        for policy_name, sev, prob, ft, th in rows:
            upsert_policy_risk(
                symbol=symbol, policy_name=policy_name, severity=sev,
                probability=prob, factor_type=ft, time_horizon=th, r=rr, manager=manager,
            )
            n += 1
        counts[symbol] = n
    total = sum(counts.values())
    # is_policy_approved now returns Optional[bool] (None for unknown); for this
    # canonical canon every symbol is mapped, so results are True/False. Use strict
    # identity checks so unknown (None) would be excluded from both lists.
    approved = [s for s in counts if is_policy_approved(s, r=rr, manager=manager) is True]
    rejected = [s for s in counts if is_policy_approved(s, r=rr, manager=manager) is False]
    return {
        "rows_inserted": total,
        "symbols_seeded": len(counts),
        "per_symbol_counts": counts,
        "policy_approved": sorted(approved),
        "policy_rejected": sorted(rejected),
    }


# Alias for the full macro-policy promotion entrypoint.
seed_all_policy_risks = seed_canonical_policy_risks_full


# ---------------------------------------------------------------------------
# Persistence orchestration (calls additive repository helpers)
# ---------------------------------------------------------------------------
def upsert_policy_risk(
    symbol: str,
    policy_name: str,
    severity: float,
    probability: float,
    factor_type: Optional[str] = None,
    time_horizon: str = "Mid-term",
    isin: Optional[str] = None,
    r: Optional[Repository] = None,
    manager=None,
) -> float:
    """Persist a single policy/regulatory risk for ``symbol`` into the dense substrate.

    Clamps severity/probability, derives risk_type (Tailwind/Headwind/Auxiliary) and
    factor_type when not supplied, then delegates the actual write to
    :meth:`Repository.upsert_regulatory_political_risk` (which computes and stores
    net_impact_score in Python for the SQLite fallback).

    Returns the computed net_impact_score (ENI).
    """
    rr = r or (Repository(manager) if manager else repo)
    rr.ensure_regulatory_political_risks_schema(manager)
    sev = clamp_severity(severity)
    prob = clamp_probability(probability)
    rt = PolicyRisk.risk_type_for(sev)
    ft = factor_type or infer_factor_type(policy_name)
    return rr.upsert_regulatory_political_risk(
        symbol=symbol,
        policy_name=policy_name,
        severity_score=sev,
        probability=prob,
        risk_type=rt,
        factor_type=ft,
        time_horizon=time_horizon,
        isin=isin,
        manager=manager,
    )


def seed_steel_duty_case(r: Optional[Repository] = None, manager=None) -> Dict[str, int]:
    """Seed the canonical steel-duty headwind case (and its PLI offset) into the live DB.

    Stores the acceptance case ``Steel Cust Duty Hike`` (severity -3.8, prob 0.85 =>
    ENI -3.23, Headwind) on TATASTEEL, plus the offsetting PLI Speciality Steel tailwind,
    and the HAL net-positive PLI Defence example. Returns a per-symbol row count.
    """
    counts: Dict[str, int] = {}
    for symbol, rows in CANONICAL_POLICY_RISKS.items():
        n = 0
        for policy_name, sev, prob, ft, th in rows:
            upsert_policy_risk(
                symbol=symbol, policy_name=policy_name, severity=sev,
                probability=prob, factor_type=ft, time_horizon=th, r=r, manager=manager,
            )
            n += 1
        counts[symbol] = n
    return counts


# Alias so both names from the spec are available.
seed_canonical_policy_risks = seed_steel_duty_case


def get_agg_eni(symbol: str, r: Optional[Repository] = None, manager=None) -> Optional[float]:
    """Aggregate ENI (sum of net_impact_score) for a symbol/isin.

    Returns ``None`` when the symbol has no *mapped* risk (only coverage-only
    ``__NO_POLICY_TEMPLATE__`` or no rows). Numeric sum otherwise. Previously
    returned ``0.0`` for unknown which incorrectly became a positive signal.
    """
    rr = r or (Repository(manager) if manager else repo)
    return rr.get_policy_agg_eni(symbol, manager=manager)


def get_policy_coverage(symbol: str, r: Optional[Repository] = None, manager=None) -> str:
    """Return policy coverage status: ``mapped`` / ``no_template`` / ``unknown``."""
    rr = r or (Repository(manager) if manager else repo)
    # Prefer repository helper if present; otherwise infer via helper.
    try:
        return rr.get_policy_coverage(symbol, manager=manager)
    except Exception:
        # Fallback: infer from agg
        agg = rr.get_policy_agg_eni(symbol, manager=manager)
        if agg is not None:
            return "mapped"
        rows = rr.get_policy_risks_for_symbol(symbol, manager=manager)
        if any(row.get("policy_name") == "__NO_POLICY_TEMPLATE__" for row in rows):
            return "no_template"
        return "unknown"


def is_policy_approved(symbol: str, r: Optional[Repository] = None, manager=None, *, coerce_unknown_to_bool: Optional[bool] = None) -> Optional[bool]:
    """Policy peer gate: ``True``/``False`` for mapped ENI, ``None`` for unknown/no_template.

    ``coerce_unknown_to_bool`` is a documented compatibility knob: when set to a bool,
    unknown/no_template is coerced to that bool (e.g. ``True`` to restore the legacy
    ``0→approved`` behaviour). Internal callers should leave it as ``None`` and handle
    ``None`` explicitly rather than treating unknown as approved.
    """
    agg = get_agg_eni(symbol, r=r, manager=manager)
    if agg is None:
        if coerce_unknown_to_bool is not None:
            return bool(coerce_unknown_to_bool)
        return None
    return agg >= 0.0


def list_policy_risks(symbol: str, r: Optional[Repository] = None, manager=None) -> List[Dict[str, Any]]:
    """Return all regulatory_political_risks rows for a symbol/isin (empty if none)."""
    rr = r or (Repository(manager) if manager else repo)
    return rr.get_policy_risks_for_symbol(symbol, manager=manager)


def query_policy_adjusted_screen(min_agg_eni: float = 0.0, r: Optional[Repository] = None, manager=None) -> List[Dict[str, Any]]:
    """Emulate PostgreSQL v_policy_adjusted_screen (graceful SQLite fallback).

    Returns rows (symbol, net_policy_score, moat/financial enrichment when present)
    filtered to net_policy_score >= min_agg_eni. Always works even when moat /
    financial_metrics tables are absent.
    """
    rr = r or (Repository(manager) if manager else repo)
    return rr.query_policy_adjusted_screen(min_agg_eni=min_agg_eni, manager=manager)


def ensure_policy_adjusted_screen_view(r: Optional[Repository] = None, manager=None) -> bool:
    """Best-effort creation of a SQLite VIEW v_policy_adjusted_screen mirroring PG.

    Never raises; callers should rely on :func:`query_policy_adjusted_screen` for
    guaranteed results. Returns True if the view exists/created.
    """
    rr = r or (Repository(manager) if manager else repo)
    return rr.ensure_v_policy_adjusted_screen(manager=manager)


# ---------------------------------------------------------------------------
# Derived at-scale policy risk writer (industry -> 11 template map)
# ---------------------------------------------------------------------------
DERIVED_POLICY_TEMPLATES = [
    # Steel -> safeguard duty (Headwind)
    {"keywords": ("steel",), "policy_name": "STEEL_SAFEGUARD_DUTY", "severity": -3.0, "probability": 0.60, "time_horizon": "Mid-term", "factor_type": "Tariff"},
    # Rail -> capex push (Tailwind)
    {"keywords": ("rail",), "policy_name": "RAIL_CAPEX_PUSH", "severity": 3.2, "probability": 0.65, "time_horizon": "Structural", "factor_type": "Subsidy"},
    # Defence indigenization
    {"keywords": ("defence", "defense", "aerospace"), "policy_name": "DEFENCE_INDIGENIZATION", "severity": 3.5, "probability": 0.70, "time_horizon": "Structural", "factor_type": "Subsidy"},
    # Power/Renewable PLI tailwind
    {"keywords": ("power", "renewable", "utility", "gas", "energy"), "policy_name": "PLI_INCENTIVE_TAILWIND", "severity": 2.8, "probability": 0.60, "time_horizon": "Structural", "factor_type": "Subsidy"},
    # Pharma USFDA compliance risk
    {"keywords": ("pharma", "pharmaceutical"), "policy_name": "USFDA_COMPLIANCE_RISK", "severity": -2.6, "probability": 0.55, "time_horizon": "Mid-term", "factor_type": "Antitrust"},
    # IT visa risk
    {"keywords": ("it services", "software", "technology", "information technology"), "policy_name": "US_VISA_RISK", "severity": -2.3, "probability": 0.50, "time_horizon": "Mid-term", "factor_type": "Tariff"},
    # Fertilizer subsidy dependence
    {"keywords": ("fertilizer", "fertiliser"), "policy_name": "SUBSIDY_DEPENDENCE", "severity": -2.0, "probability": 0.60, "time_horizon": "Mid-term", "factor_type": "Subsidy"},
    # Bank/NBFC rate cycle
    {"keywords": ("bank", "nbfc", "finance", "financial", "insurance"), "policy_name": "RBI_RATE_CYCLE", "severity": 2.4, "probability": 0.55, "time_horizon": "Mid-term", "factor_type": "FX"},
    # Auto EV transition
    {"keywords": ("auto", "automobile", "tyre", "tire"), "policy_name": "EV_TRANSITION_RISK", "severity": -2.7, "probability": 0.65, "time_horizon": "Structural", "factor_type": "Subsidy"},
    # Cement infra capex tailwind
    {"keywords": ("cement",), "policy_name": "INFRA_CAPEX_TAILWIND", "severity": 2.5, "probability": 0.60, "time_horizon": "Mid-term", "factor_type": "Subsidy"},
    # Mining export duty risk
    {"keywords": ("mining",), "policy_name": "EXPORT_DUTY_RISK", "severity": -2.2, "probability": 0.50, "time_horizon": "Mid-term", "factor_type": "Tariff"},
]


def _template_for_industry(industry: str, sector: str):
    text = f"{industry or ''} {sector or ''}".lower()
    for tmpl in DERIVED_POLICY_TEMPLATES:
        for kw in tmpl["keywords"]:
            if kw in text:
                return tmpl
    return None


def seed_derived_policy_risks(universe: str = "nifty200", limit: Optional[int] = None,
                              overwrite: bool = False, r: Optional[Repository] = None,
                              manager=None, include_derived: bool = False) -> Dict[str, int]:
    """Derive regulatory_political_risks for universe via 11-template industry map.

    For each master company whose ``industry`` matches a template keyword,
    upsert a single policy risk via ``repo.upsert_regulatory_political_risk``.
    Severity band 2-4, probability 0.4-0.7, time_horizon Mid-term/Structural.
    Idempotent via UNIQUE(symbol, policy_name).

    When no template matches, insert one idempotent coverage-only row with
    ``policy_name='__NO_POLICY_TEMPLATE__'`` and ``coverage_status='no_template'``
    (no severity/probability/net impact) so every active company becomes queryable
    without fabricating a risk. Coverage rows are counted separately as
    ``coverage_rows_inserted``.

    Skip companies already having any regulatory row unless overwrite=True
    (or include_derived forces overwrite of derived-only detection).

    Returns dict with inserted / skipped_existing / scanned + coverage_rows_inserted.
    For backward compatibility ``skipped_no_template`` is retained as 0.
    """
    rr = r or (Repository(manager) if manager else repo)
    rr.ensure_regulatory_political_risks_schema(manager)

    # universe resolution
    try:
        if universe == "nifty500":
            with (manager or rr.db).session() as conn:
                rows = conn.execute("SELECT * FROM master_companies WHERE is_nifty500=1 AND is_active=1 ORDER BY nse_symbol ASC").fetchall()
                comps = [dict(x) for x in rows]
        elif universe == "all":
            with (manager or rr.db).session() as conn:
                rows = conn.execute("SELECT * FROM master_companies WHERE is_active=1 ORDER BY nse_symbol ASC").fetchall()
                comps = [dict(x) for x in rows]
        else:
            comps = rr.get_nifty200_companies()
            if not comps:
                with (manager or rr.db).session() as conn:
                    rows = conn.execute("SELECT * FROM master_companies WHERE is_nifty200=1 AND is_active=1 ORDER BY nse_symbol ASC").fetchall()
                    comps = [dict(x) for x in rows]
    except Exception:
        comps = []

    if limit is not None:
        try:
            comps = comps[: int(limit)]
        except Exception:
            pass

    scanned = len(comps)
    inserted = 0
    coverage_rows_inserted = 0
    skipped_existing = 0
    skipped_no_template = 0  # retained for compat, always 0 now (coverage rows replace it)

    mgr = manager or rr.db
    for c in comps:
        symbol = (c.get("nse_symbol") or "").strip()
        isin = (c.get("isin") or "").strip() or None
        if not symbol:
            continue

        # Skip if already has any policy row unless overwrite
        if not overwrite:
            try:
                existing = rr.get_policy_risks_for_symbol(symbol, manager=manager)
            except Exception:
                existing = []
            if existing:
                skipped_existing += 1
                continue

        tmpl = _template_for_industry(c.get("industry", ""), c.get("sector", ""))
        # Resolve isin if missing
        if not isin:
            try:
                with mgr.session() as conn:
                    row = conn.execute("SELECT isin FROM master_companies WHERE nse_symbol=?", (symbol,)).fetchone()
                    if row and row["isin"]:
                        isin = row["isin"]
            except Exception:
                pass

        if tmpl is None:
            # Insert coverage-only sentinel so this symbol is queryable without fabricating ENI
            try:
                rr.upsert_regulatory_political_risk(
                    symbol=symbol,
                    policy_name="__NO_POLICY_TEMPLATE__",
                    severity_score=None,
                    probability=None,
                    net_impact_score=None,
                    coverage_status="no_template",
                    isin=isin,
                )
                coverage_rows_inserted += 1
            except Exception:
                continue
            continue

        try:
            rr.upsert_regulatory_political_risk(
                symbol=symbol,
                policy_name=tmpl["policy_name"],
                severity_score=tmpl["severity"],
                probability=tmpl["probability"],
                factor_type=tmpl["factor_type"],
                time_horizon=tmpl["time_horizon"],
                coverage_status="mapped",
                isin=isin,
            )
            inserted += 1
        except Exception:
            continue

    return {"inserted": inserted, "rows_inserted": inserted, "skipped_existing": skipped_existing,
            "skipped_no_template": skipped_no_template, "scanned": scanned, "symbols_seeded": inserted,
            "coverage_rows_inserted": coverage_rows_inserted}


# Alias for harness expecting alternate name
seed_derived_policy_risk = seed_derived_policy_risks


if __name__ == "__main__":
    # Demonstration: seed the canonical steel-duty case and report the policy gate.
    seeded = seed_steel_duty_case()
    print("Seeded canonical policy risks:", seeded)
    for symbol in ("TATASTEEL", "HAL", "POLYPLEX", "RELIANCE"):
        agg = get_agg_eni(symbol)
        cov = get_policy_coverage(symbol)
        appr = is_policy_approved(symbol)
        agg_str = f"{agg:+.2f}" if agg is not None else "None"
        print(f"{symbol}: AggENI={agg_str} coverage={cov} approved={appr}")
    print("v_policy_adjusted_screen rows (AggENI>=0, mapped only):")
    for row in query_policy_adjusted_screen():
        print("  ", row)
