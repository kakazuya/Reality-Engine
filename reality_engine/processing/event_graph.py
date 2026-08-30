"""Wave D2 — Transient Event-Graph Spawner.

Spawns a transient macro/event graph (``macro_events`` + ``ripple_effects`` DAG) from a
Pydantic ``MacroEventExtraction`` lens. Per AGENTS.md §3 #4 and plan §2 Wave D Task D2,
every signal is quantized into the dense substrate *before* it influences a thesis — no
free-text graph creation.

Flow:
    parse_event_nuance(%) -> fetch_supply_chain_neighbors(2nd-order fwd/back)
    -> Pydantic MacroEventExtraction (validated) -> repository.upsert_event_graph
    (single transaction -> atomic rollback) -> trace_transient_chain (PN/MN/S).

Example ``US_TARIFF_TEXTILE_RELIEF``: a 30% tariff relief whose PRIMARY (a small tariffed
exporter) is NOT the biggest beneficiary — the downstream TextileMachinery rebound carries
the largest significance ``S`` (verified by ``trace_transient_chain`` ordering ``S DESC``).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from reality_engine.agent.schemas import (
    MacroEventExtraction,
    PrimaryConsequence,
    RippleConsequence,
)
from reality_engine.db.database import db_manager
from reality_engine.db.repository import Repository
from reality_engine.processing.causal_engine import CausalGraphEngine
from reality_engine.processing.distillation_engine import DistillationEngine


class EventGraphSpawner:
    """Transient event-graph spawner (deterministic, SQLite-fallback compatible)."""

    # Deterministic transient supply-chain map for the US textile tariff relief case.
    TEXTILE_PRIMARY = "TextileExporter_Small"
    TEXTILE_UPSTREAM = ["CottonGrowers", "DyeChemicals", "YarnSpinners"]
    TEXTILE_DOWNSTREAM = ["GarmentFactories", "TextileMachineryMakers", "RetailApparel"]

    # ------------------------------------------------------------------
    # Supply-chain peer (Peer 4) — supplemental 2nd-order fwd/back fixtures for
    # the steel-duty / rail-capex / nuclear-mission transient chains. These make
    # ``fetch_supply_chain_neighbors`` dense for the supply-chain lens so the
    # spawner degrades to curated live data for these macro events too.
    #
    # Keyed by BOTH the transient event id and the canonical primary-target name
    # so callers may pass either. Each entry carries upstream (back) + downstream
    # (forward) neighbor lists (one hop each way; 2nd-order is realized in the
    # ripple_effects DAG via trace_ripple_chain).
    # ------------------------------------------------------------------
    STEEL_PRIMARY = "DomesticSteelProducers"
    RAIL_PRIMARY = "RailInfraDevelopers"
    NUCLEAR_PRIMARY = "NuclearPowerOperators"

    _SUPPLY_CHAIN_FIXTURES = {
        "US_TARIFF_TEXTILE_RELIEF": {
            "upstream": TEXTILE_UPSTREAM,
            "downstream": TEXTILE_DOWNSTREAM,
        },
        "STEEL_SAFEGUARD_DUTY": {
            "upstream": ["IronOreMiners", "CokingCoalImporters", "CapexGoodsMakers"],
            "downstream": ["WagonMakers", "AutoOEMs", "ConstructionFirms"],
        },
        "RAIL_CAPEX_PUSH": {
            "upstream": ["SteelMakers", "CementMakers", "SignalingOEMs"],
            "downstream": ["WagonMakers", "EPCContractors", "ComponentSuppliers"],
        },
        "NUCLEAR_MISSION": {
            "upstream": ["UraniumImporters", "HeavyWaterSuppliers"],
            "downstream": ["ReactorEPCMakers", "CableOEMs", "EngineeringEPC"],
        },
        STEEL_PRIMARY: {
            "upstream": ["IronOreMiners", "CokingCoalImporters", "CapexGoodsMakers"],
            "downstream": ["WagonMakers", "AutoOEMs", "ConstructionFirms"],
        },
        RAIL_PRIMARY: {
            "upstream": ["SteelMakers", "CementMakers", "SignalingOEMs"],
            "downstream": ["WagonMakers", "EPCContractors", "ComponentSuppliers"],
        },
        NUCLEAR_PRIMARY: {
            "upstream": ["UraniumImporters", "HeavyWaterSuppliers"],
            "downstream": ["ReactorEPCMakers", "CableOEMs", "EngineeringEPC"],
        },
    }

    # Event nuance fixtures — quantized parse of the policy text (%, date, exceptions,
    # conditional US-plant flag). Extend this map for future transient events.
    _NUANCE_FIXTURES = {
        "US_TARIFF_TEXTILE_RELIEF": {
            "pct_reduction": 30.0,
            "effective_date": "2026-04-01",
            "exceptions": ["dyes", "yarn"],
            "conditional_flag": True,
            "conditional_detail": "relief conditional on setting up a US manufacturing plant",
        },
        "STEEL_SAFEGUARD_DUTY": {
            "pct_reduction": 12.0,
            "effective_date": "2025-04-21",
            "exceptions": ["stainless_steel_specialty_grades"],
            "conditional_flag": False,
            "conditional_detail": "applies while import surge persists, reviewed semi-annually",
        },
        "RAIL_CAPEX_PUSH": {
            "pct_reduction": 9.0,
            "effective_date": "2026-02-01",
            "exceptions": [],
            "conditional_flag": False,
            "conditional_detail": "Rail capex outlay up approximately 9 percent year over year; Vande Bharat and Kavach lines prioritised",
        },
        "NUCLEAR_MISSION": {
            "pct_reduction": 1.0,
            "effective_date": "2026-04-01",
            "exceptions": [],
            "conditional_flag": True,
            "conditional_detail": "Nuclear Energy Mission targets 100 GW by 2047; incentives conditional on private participation",
        },
    }

    # ------------------------------------------------------------------
    # Deterministic semantic -> actual company mapping (additive company-resolution layer)
    # Symbols verified read-only against production master_companies (2026-08-30):
    #   steel producers: TATASTEEL (INE081A01020, row 1879), JSWSTEEL (INE019A01038, 974),
    #                    SAIL (INE114A01011, 1617), JINDALSTEL (INE749A01030, 946)
    #   wagon makers: TITAGARH (INE615H01020, 1929), TEXRAIL (INE621L01012, 1904)
    #   textile/exporter: TRIDENT (INE064C01022), KPRMILL (INE930H01031),
    #                     VTL (INE825A01020), WELSPUNLIV (INE192B01031), GOKEX (INE887G01027)
    #   rail/rolling-stock/EPC/signalling (RAIL_CAPEX_PUSH, 2026-08-30 verification via
    #                    master_companies read-only query): RVNL (INE415G01027),
    #                    IRCON (INE326T01011), RITES (INE320J01015), TITAGARH (INE615H01020),
    #                    TEXRAIL (INE621L01012), KAYNES (INE918Z01012); BEML (INE258A01016)
    #                    verified as listed (500420) but omitted to respect 6-symbol cap
    #                    (swap-ready; re-verify via SELECT rowid FROM master_companies
    #                    WHERE nse_symbol=? before use)
    #   nuclear EPC/power/cable (NUCLEAR_MISSION, 2026-08-30 verification):
    #                    NTPC (INE733E01010), BHEL (INE257A01026), LT (INE018A01030),
    #                    SIEMENS (INE003A01024); all SELECT rowid verified, case-insensitive
    # Each list is 3-6 symbols total per event, defensible, and checked for existence
    # before use — missing symbols are skipped so empty temp DBs keep semantic rows.
    # RAIL/NUCLEAR keys match ripple template target= semantics and order_level:
    #   RAIL_CAPEX_PUSH: RailInfraDevelopers (order1 primary), WagonMakers/EPCContractors
    #                    (downstream forward, order2), SignalingOEMs (upstream back, order2)
    #                    — SteelMakers/CementMakers/ComponentSuppliers are valid template
    #                    keys but no company map needed (pure industry lens)
    #   NUCLEAR_MISSION: NuclearPowerOperators (order1 primary), ReactorEPCMakers/CableOEMs/
    #                    EngineeringEPC (downstream forward, order2),
    #                    UraniumImporters/HeavyWaterSuppliers upstream keys are valid
    #                    template keys but have no listed-company counterpart (importers)
    # ------------------------------------------------------------------
    _COMPANY_MAP = {
        "STEEL_SAFEGUARD_DUTY": {
            "DomesticSteelProducers": ["TATASTEEL", "JSWSTEEL", "SAIL", "JINDALSTEL"],
            "WagonMakers": ["TITAGARH", "TEXRAIL"],
        },
        "US_TARIFF_TEXTILE_RELIEF": {
            "TextileExporter_Small": ["GOKEX"],
            "GarmentFactories": ["TRIDENT", "KPRMILL", "VTL"],
            "RetailApparel": ["WELSPUNLIV"],
        },
        "RAIL_CAPEX_PUSH": {
            "RailInfraDevelopers": ["RVNL", "IRCON"],
            "WagonMakers": ["TITAGARH", "TEXRAIL"],
            "EPCContractors": ["RITES"],
            "SignalingOEMs": ["KAYNES"],
        },
        "NUCLEAR_MISSION": {
            "NuclearPowerOperators": ["NTPC"],
            "ReactorEPCMakers": ["BHEL"],
            "EngineeringEPC": ["LT"],
            "CableOEMs": ["SIEMENS"],
        },
    }

    def __init__(self, manager=None):
        self.db = manager or db_manager
        self.repo = Repository(self.db)
        self.causal = CausalGraphEngine(self.db)
        self._distill = DistillationEngine(self.db)

    # ------------------------------------------------------------------
    # 1. Parse event nuance (% reduction, effective date, exceptions, conditional)
    # ------------------------------------------------------------------
    def parse_event_nuance(self, event_id: str) -> Dict[str, Any]:
        """Parse quantized nuance for a known transient event id.

        Returns ``pct_reduction``, ``effective_date``, ``exceptions``, ``conditional_flag``
        and ``conditional_detail``. Unknown events return a zero/blank nuance (graceful —
        no crash, no free-text leakage to the substrate).
        """
        nuance = self._NUANCE_FIXTURES.get(event_id, {})
        return {
            "event_id": event_id,
            "pct_reduction": float(nuance.get("pct_reduction", 0.0)),
            "effective_date": nuance.get("effective_date"),
            "exceptions": list(nuance.get("exceptions", [])),
            "conditional_flag": bool(nuance.get("conditional_flag", False)),
            "conditional_detail": nuance.get("conditional_detail"),
        }

    # ------------------------------------------------------------------
    # 2. Fetch supply-chain neighbors (2nd-order forward/back)
    # ------------------------------------------------------------------
    def fetch_supply_chain_neighbors(self, primary_target: str, max_hops: int = 2) -> Dict[str, List[str]]:
        """Return deterministic upstream (back) + downstream (forward) neighbors.

        ``max_hops`` is accepted for API symmetry; the curated fixture map is one hop each
        way. Looks up the expanded supply-chain fixture map (textile + steel/rail/nuclear)
        first, then falls back to ``geopolitical_supply_chain`` distilled parameters for
        arbitrary symbols so the spawner degrades to live data when available.
        """
        upstream: List[str] = []
        downstream: List[str] = []
        fixture = self._SUPPLY_CHAIN_FIXTURES.get(primary_target)
        if fixture is None and primary_target in ("Textiles", self.TEXTILE_PRIMARY):
            fixture = self._SUPPLY_CHAIN_FIXTURES["US_TARIFF_TEXTILE_RELIEF"]
        if fixture is not None:
            upstream = list(fixture["upstream"])
            downstream = list(fixture["downstream"])
        else:
            try:
                params = self.repo.get_distilled_parameters(primary_target, "geopolitical_supply_chain")
                if params:
                    deps = (params[0].get("value", {}) or {}).get("supply_chain_dependencies", [])
                    upstream = [str(d) for d in deps]
            except Exception:
                pass
        return {"upstream": upstream, "downstream": downstream}

    # ------------------------------------------------------------------
    # 2b. Deterministic company resolution (additive layer)
    # ------------------------------------------------------------------
    def _resolve_company_id(self, symbol: str) -> Optional[int]:
        """Resolve master_companies.rowid for a symbol/isin (strip/upper, tolerant).

        Returns the integer rowid or None when the symbol is absent. Never raises
        and never fakes an id — absent symbols are skipped by the caller.
        """
        if not symbol or not isinstance(symbol, str):
            return None
        sym = symbol.strip()
        if not sym:
            return None
        try:
            with self.db.session() as conn:
                # Try exact nse_symbol / bse_code / isin first
                row = conn.execute(
                    "SELECT rowid FROM master_companies WHERE nse_symbol = ? OR bse_code = ? OR isin = ? LIMIT 1",
                    (sym, sym, sym),
                ).fetchone()
                if row:
                    return int(row["rowid"])
                # Case-insensitive fallback (handles temp DB seeding with varied case)
                row = conn.execute(
                    "SELECT rowid FROM master_companies WHERE UPPER(TRIM(nse_symbol)) = UPPER(TRIM(?)) "
                    "OR UPPER(TRIM(bse_code)) = UPPER(TRIM(?)) LIMIT 1",
                    (sym, sym),
                ).fetchone()
                if row:
                    return int(row["rowid"])
        except Exception:
            return None
        return None

    def _enrich_ripples_with_companies(self, event_id: str, ripples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Add deterministic company-linked ripples for STEEL / US_TARIFF (additive, not replacement).

        For each semantic target_name in ``_COMPANY_MAP[event_id]`` the method finds
        the template semantic ripple (via ``target=SEMANTIC`` in its transmission_channel)
        and clones it for every verified symbol in the map. The clone keeps the
        original order_level / raw / prob / lag / elasticity / significance so the
        causal formulas PN/MN/S are preserved; only target_type/target_company_id/
        transmission_channel are company-resolved. Symbols absent from master_companies
        are skipped (no fake ids). The semantic rows are preserved — the layer is
        additive.
        """
        mapping = self._COMPANY_MAP.get(event_id)
        if not mapping:
            return ripples
        # Quick index: semantic -> template ripple (first match)
        enriched: List[Dict[str, Any]] = list(ripples)
        # Primary ref is needed as parent for order-2 company clones
        primary_ref: Optional[Any] = None
        for r in ripples:
            if r.get("order_level") == 1 and r.get("_ref") is not None and r.get("_parent_ref") is None:
                primary_ref = r.get("_ref")
                break
        if primary_ref is None:
            for r in ripples:
                if r.get("order_level") == 1 and r.get("_ref") is not None:
                    primary_ref = r.get("_ref")
                    break
        counter = 0
        for semantic, symbols in mapping.items():
            # Find the template semantic ripple that carries this semantic name
            template = None
            for r in ripples:
                ch = r.get("transmission_channel") or ""
                if f"target={semantic}" in ch:
                    template = r
                    break
            if template is None:
                continue
            t_order = template.get("order_level")
            t_raw = template.get("raw_magnitude")
            t_prob = template.get("probability")
            t_lag = template.get("lag_time_months")
            t_elasticity = template.get("transmission_elasticity", 1.0)
            t_significance = template.get("significance_rank")
            # Determine parent ref for the clone
            if t_order == 1:
                parent_ref = None
            else:
                # Order 2/3 company clones are children of the primary (same parent as template)
                parent_ref = template.get("_parent_ref")
                if parent_ref is None:
                    parent_ref = primary_ref
            for sym in symbols:
                cid = self._resolve_company_id(sym)
                if cid is None:
                    continue
                # Unique _ref for the clone; counter ensures deterministic ordering
                base_ref = template.get("_ref") or f"p0_{semantic}"
                new_ref = f"{base_ref}_c_{sym}_{counter}"
                counter += 1
                # Preserve significance; if missing, recompute via the same formula
                sig = t_significance
                if sig is None:
                    try:
                        from reality_engine.processing.distillation_engine import DistillationEngine
                        # For order 1 clones, cumulative is just prob/lag; for order 2, need primary's prob/lag
                        # Reuse template's already-computed significance by recomputing from raw/prob/lag
                        # For order 2 we need cumulative: primary_prob * prob
                        if t_order == 1:
                            sig = DistillationEngine._significance(float(t_raw or 0), float(t_prob or 0), float(t_elasticity), int(t_lag or 0))
                        else:
                            # Find primary prob/lag to compute cumulative
                            prim_prob = 1.0
                            prim_lag = 0
                            for pr in ripples:
                                if pr.get("order_level") == 1:
                                    prim_prob = float(pr.get("probability") or 1.0)
                                    prim_lag = int(pr.get("lag_time_months") or 0)
                                    break
                            cum_prob = prim_prob * float(t_prob or 1.0)
                            cum_lag = prim_lag + int(t_lag or 0)
                            sig = DistillationEngine._significance(float(t_raw or 0), cum_prob, float(t_elasticity), cum_lag)
                    except Exception:
                        sig = t_significance
                new_ripple: Dict[str, Any] = {
                    "order_level": t_order,
                    "target_type": "Company",
                    "target_company_id": cid,
                    "target_sector_id": None,
                    "target_industry_id": None,
                    "transmission_channel": f"target={sym} | company_resolved:{semantic} | {template.get('transmission_channel','')}",
                    "transmission_elasticity": t_elasticity,
                    "raw_magnitude": t_raw,
                    "probability": t_prob,
                    "lag_time_months": t_lag,
                    "significance_rank": sig,
                    "_ref": new_ref,
                    "_parent_ref": parent_ref,
                }
                enriched.append(new_ripple)
        return enriched

    # ------------------------------------------------------------------
    # 3. Spawn a transient event (Pydantic-validated, transactional)
    # ------------------------------------------------------------------
    def spawn_transient_event(
        self,
        event_name: str,
        event_category: str,
        doc_id: Optional[int] = None,
        extraction: Any = None,
        primary_target: Optional[str] = None,
        event_id: Optional[str] = None,
        max_hops: int = 3,
    ) -> Dict[str, Any]:
        """Spawn a transient ``macro_events`` row + ``ripple_effects`` DAG (transactional).

        ``extraction`` MUST be a valid ``MacroEventExtraction`` (Pydantic) or a dict that
        validates to one. Invalid extraction -> ``ValueError`` raised BEFORE any write, so
        no half-written graph lands in the substrate. All writes happen inside one
        repository transaction (``upsert_event_graph``) for atomic rollback.
        """
        if extraction is None:
            raise ValueError("spawn_transient_event requires a MacroEventExtraction lens (no free-text graph).")

        # Enforce Pydantic validation — never free-text graph creation.
        try:
            extraction = MacroEventExtraction.model_validate(extraction)
        except Exception as exc:
            raise ValueError(f"Invalid MacroEventExtraction lens: {exc}") from exc

        # Guard the no-pydantic fallback path where required fields are not enforced.
        if not getattr(extraction, "event_name", None):
            raise ValueError("Invalid MacroEventExtraction lens: event_name is required.")

        event_id = event_id or f"TGE_{abs(hash(event_name))}"
        nuance = self.parse_event_nuance(event_id)

        # Build the ordered ripple DAG from the validated lens (parents before children).
        ripples = self._distill._build_ripples(extraction, event_id)
        # Additive company-resolution layer (STEEL / US_TARIFF) — deterministic, idempotent,
        # verified symbols only, preserves semantic rows and S formula.
        ripples = self._enrich_ripples_with_companies(event_id, ripples)

        macro_record = {
            "event_id": event_id,
            "event_name": extraction.event_name,
            "category": extraction.event_category or event_category,
            "event_date": nuance.get("effective_date") or date.today().isoformat(),
            "raw_document_path": None,
            "summary": self._summarize(event_name, nuance, len(extraction.primary_effects)),
            "affected_nodes_json": extraction.model_dump(),
            "doc_id": doc_id,
        }

        ripples_created = self.repo.upsert_event_graph(event_id, macro_record, ripples)
        return {
            "event_id": event_id,
            "events_created": 1,
            "ripples_created": ripples_created,
            "status": "spawned",
            "nuance": nuance,
            "primary_target": primary_target,
            "max_hops": max_hops,
        }

    # ------------------------------------------------------------------
    # 4. Canonical US_TARIFF_TEXTILE_RELIEF case (primary != biggest beneficiary)
    # ------------------------------------------------------------------
    def spawn_us_tariff_textile_relief(self) -> Dict[str, Any]:
        """Spawn the canonical ``US_TARIFF_TEXTILE_RELIEF`` transient graph.

        Design invariant (acceptance): the PRIMARY (a small tariffed exporter) is NOT the
        biggest beneficiary. The downstream TextileMachinery rebound carries the largest
        significance ``S`` (verified by ``trace_transient_chain`` ordering ``S DESC``).

        Quantization:
          * 30% tariff relief -> +0.30 primary recovery, but the US-plant condition lowers
            realized probability (0.55), not prose.
          * dyes/yarn EXCEPTIONS -> muted upstream magnitudes + "exception_*" channel tags.
          * lag_time_months quantized: 0m primary, 3m 2nd-order, 6m 3rd-order.
        """
        nuance = self.parse_event_nuance("US_TARIFF_TEXTILE_RELIEF")
        pct = nuance["pct_reduction"]  # 30.0
        cond = nuance["conditional_flag"]  # True

        # Primary: small tariffed exporter. 30% recovery, conditional US-plant -> lower prob.
        primary = PrimaryConsequence(
            target_type="Company",
            target_name=self.TEXTILE_PRIMARY,
            transmission_channel=(
                "tariff_relief_recovery | conditional_us_plant" if cond
                else "tariff_relief_recovery"
            ),
            raw_magnitude=round(pct / 100.0, 4),  # 0.30
            probability=0.55,                       # conditionality reduces confidence
            lag_time_months=0,                      # primary hit at effective date
            second_order_effects=[],
        )

        def sec(name: str, raw: float, prob: float, lag: int, channel_suffix: str) -> RippleConsequence:
            return RippleConsequence(
                order_level=2,
                target_type="Industry",
                target_name=name,
                transmission_channel=channel_suffix,
                transmission_elasticity=1.0,
                raw_magnitude=round(raw, 4),
                probability=round(prob, 4),
                lag_time_months=lag,
            )

        # Downstream (forward) benefit — machinery rebound is the biggest beneficiary.
        machinery = sec("TextileMachineryMakers", 1.50, 0.85, 3, "capex_rebound | downstream | forward")
        garment = sec("GarmentFactories", 0.50, 0.80, 3, "volume_rebound | downstream | forward")
        retail = sec("RetailApparel", 0.30, 0.75, 3, "demand_pull | downstream | forward")

        # Upstream (back) benefit — dyes/yarn EXCEPTED (still tariffed) -> muted.
        yarn = sec("YarnSpinners", 0.15, 0.60, 3, "input_cost_partial | exception_yarn | upstream | back")
        dye = sec("DyeChemicals", 0.10, 0.50, 3, "input_cost_excepted | exception_dyes | upstream | back")
        cotton = sec("CottonGrowers", 0.25, 0.70, 3, "input_cost_relief | upstream | back")

        # 3rd-order: machinery pulls capital-goods / machine-tool demand (lag 6m).
        machine_tool = RippleConsequence(
            order_level=3,
            target_type="Industry",
            target_name="MachineToolMakers",
            transmission_channel="capital_goods_pull | downstream",
            transmission_elasticity=1.0,
            raw_magnitude=0.40,
            probability=0.70,
            lag_time_months=6,
        )
        machinery.downstream_ripples = [machine_tool]

        primary.second_order_effects = [machinery, garment, retail, yarn, dye, cotton]

        extraction = MacroEventExtraction(
            event_name="US Tariff Textile Relief (30% tariff reduction)",
            event_category="Trade",
            primary_effects=[primary],
        )
        return self.spawn_transient_event(
            event_name=extraction.event_name,
            event_category=extraction.event_category,
            doc_id=None,
            extraction=extraction,
            primary_target=self.TEXTILE_PRIMARY,
            event_id="US_TARIFF_TEXTILE_RELIEF",
            max_hops=3,
        )

    def spawn_steel_safeguard_duty(self) -> Dict[str, Any]:
        """Spawn the ``STEEL_SAFEGUARD_DUTY`` transient graph.

        Design invariant: PRIMARY (DomesticSteelProducers, 12% duty shield) is NOT
        the biggest beneficiary — downstream WagonMakers rebound carries the largest
        significance ``S`` (2nd-order, verified by trace_transient_chain S DESC).

        Quantization:
          * 12% safeguard duty -> +0.12 primary protection (prob 0.85, reviewed semi-annually).
          * stainless_steel_specialty_grades EXCEPTION -> muted AutoOEM magnitude + exception_* channel.
          * lag_time_months quantized: 0m primary, 3m 2nd-order, 6m 3rd-order.
        """
        nuance = self.parse_event_nuance("STEEL_SAFEGUARD_DUTY")
        pct = nuance["pct_reduction"]  # 12.0
        # conditional_flag False for steel (applies while surge persists, reviewed semi-annually)

        primary = PrimaryConsequence(
            target_type="Company",
            target_name=self.STEEL_PRIMARY,
            transmission_channel="safeguard_duty_protection | import_surge_persist",
            raw_magnitude=round(pct / 100.0, 4),  # 0.12
            probability=0.85,
            lag_time_months=0,
            second_order_effects=[],
        )

        def sec(name: str, raw: float, prob: float, lag: int, channel_suffix: str) -> RippleConsequence:
            return RippleConsequence(
                order_level=2,
                target_type="Industry",
                target_name=name,
                transmission_channel=channel_suffix,
                transmission_elasticity=1.0,
                raw_magnitude=round(raw, 4),
                probability=round(prob, 4),
                lag_time_months=lag,
            )

        # Downstream — WagonMakers is biggest beneficiary (rail wagon demand + domestic steel availability)
        wagon = sec("WagonMakers", 0.90, 0.80, 3, "wagon_demand_pull | downstream | forward")
        auto = sec("AutoOEMs", -0.25, 0.70, 3, "input_cost_pressure | exception_stainless_specialty_grades | downstream | forward")
        construction = sec("ConstructionFirms", -0.15, 0.60, 3, "steel_cost_push | downstream | forward")

        # Upstream (back) benefit
        iron = sec("IronOreMiners", 0.35, 0.75, 3, "iron_ore_demand_pull | upstream | back")
        coking = sec("CokingCoalImporters", 0.20, 0.65, 3, "coking_coal_substitution | upstream | back")
        capex = sec("CapexGoodsMakers", 0.30, 0.70, 3, "capex_goods_pull | upstream | back")

        # 3rd-order: WagonMakers pulls wheelset/forging demand (lag 6m)
        wheelset = RippleConsequence(
            order_level=3,
            target_type="Industry",
            target_name="WheelsetForgers",
            transmission_channel="capital_goods_pull | downstream",
            transmission_elasticity=1.0,
            raw_magnitude=0.35,
            probability=0.65,
            lag_time_months=6,
        )
        wagon.downstream_ripples = [wheelset]

        primary.second_order_effects = [wagon, auto, construction, iron, coking, capex]

        extraction = MacroEventExtraction(
            event_name="Steel Safeguard Duty (12% safeguard duty on steel imports)",
            event_category="Trade",
            primary_effects=[primary],
        )
        return self.spawn_transient_event(
            event_name=extraction.event_name,
            event_category=extraction.event_category,
            doc_id=None,
            extraction=extraction,
            primary_target=self.STEEL_PRIMARY,
            event_id="STEEL_SAFEGUARD_DUTY",
            max_hops=3,
        )

    def spawn_rail_capex_push(self) -> Dict[str, Any]:
        """Spawn the ``RAIL_CAPEX_PUSH`` transient graph.

        Design invariant: PRIMARY (RailInfraDevelopers, ~9% YoY capex growth) is NOT the
        biggest beneficiary — downstream WagonMakers/EPC rebound carries the largest S.

        Quantization:
          * 9% capex outlay growth -> +0.09 primary (prob 0.90, post-Budget allocation).
          * No exceptions (blanket capex push, Vande Bharat/Kavach prioritised).
          * lag_time_months quantized: 0m primary, 3m 2nd-order, 6m 3rd-order.
        """
        nuance = self.parse_event_nuance("RAIL_CAPEX_PUSH")
        pct = nuance["pct_reduction"]  # 9.0 (outlay growth quantized as pct_reduction field)

        primary = PrimaryConsequence(
            target_type="Company",
            target_name=self.RAIL_PRIMARY,
            transmission_channel="rail_capex_push | vande_bharat_kavach_prioritised",
            raw_magnitude=round(pct / 100.0, 4),  # 0.09
            probability=0.90,
            lag_time_months=0,
            second_order_effects=[],
        )

        def sec(name: str, raw: float, prob: float, lag: int, channel_suffix: str) -> RippleConsequence:
            return RippleConsequence(
                order_level=2,
                target_type="Industry",
                target_name=name,
                transmission_channel=channel_suffix,
                transmission_elasticity=1.0,
                raw_magnitude=round(raw, 4),
                probability=round(prob, 4),
                lag_time_months=lag,
            )

        # Downstream — WagonMakers biggest beneficiary
        wagon = sec("WagonMakers", 1.20, 0.85, 3, "rolling_stock_demand | downstream | forward")
        epc = sec("EPCContractors", 0.85, 0.80, 3, "epc_order_inflow | downstream | forward")
        comp = sec("ComponentSuppliers", 0.50, 0.70, 3, "component_demand_pull | downstream | forward")

        # Upstream
        steel = sec("SteelMakers", 0.60, 0.80, 3, "steel_demand_pull | upstream | back")
        cement = sec("CementMakers", 0.45, 0.75, 3, "cement_demand_pull | upstream | back")
        signal = sec("SignalingOEMs", 0.70, 0.82, 3, "kavach_signaling_pull | upstream | back")

        # 3rd-order: WagonMakers pulls component forging
        forging = RippleConsequence(
            order_level=3,
            target_type="Industry",
            target_name="ComponentForgers",
            transmission_channel="capital_goods_pull | downstream",
            transmission_elasticity=1.0,
            raw_magnitude=0.40,
            probability=0.70,
            lag_time_months=6,
        )
        wagon.downstream_ripples = [forging]

        primary.second_order_effects = [wagon, epc, comp, steel, cement, signal]

        extraction = MacroEventExtraction(
            event_name="Rail Capex Push (9% YoY outlay growth, post-Union Budget)",
            event_category="Policy",
            primary_effects=[primary],
        )
        return self.spawn_transient_event(
            event_name=extraction.event_name,
            event_category=extraction.event_category,
            doc_id=None,
            extraction=extraction,
            primary_target=self.RAIL_PRIMARY,
            event_id="RAIL_CAPEX_PUSH",
            max_hops=3,
        )

    def spawn_nuclear_mission(self) -> Dict[str, Any]:
        """Spawn the ``NUCLEAR_MISSION`` transient graph.

        Design invariant: PRIMARY (NuclearPowerOperators) is NOT the biggest
        beneficiary — downstream ReactorEPCMakers carries the largest S.

        Quantization:
          * pct_reduction 1.0 sentinel (not a reduction; quantified as policy tailwind 0.35, conditional).
          * 100 GW by 2047 target; incentives conditional on private participation -> prob 0.50.
          * lag_time_months quantized: 0m primary, 3m 2nd-order, 6m 3rd-order.
        """
        nuance = self.parse_event_nuance("NUCLEAR_MISSION")
        cond = nuance["conditional_flag"]  # True

        primary = PrimaryConsequence(
            target_type="Company",
            target_name=self.NUCLEAR_PRIMARY,
            transmission_channel=(
                "nuclear_mission_policy | conditional_private_participation" if cond
                else "nuclear_mission_policy"
            ),
            raw_magnitude=0.35,  # policy tailwind (pct_reduction 1.0 sentinel -> not a tariff cut)
            probability=0.50,     # conditional on private participation reduces confidence
            lag_time_months=0,
            second_order_effects=[],
        )

        def sec(name: str, raw: float, prob: float, lag: int, channel_suffix: str) -> RippleConsequence:
            return RippleConsequence(
                order_level=2,
                target_type="Industry",
                target_name=name,
                transmission_channel=channel_suffix,
                transmission_elasticity=1.0,
                raw_magnitude=round(raw, 4),
                probability=round(prob, 4),
                lag_time_months=lag,
            )

        # Downstream — ReactorEPCMakers biggest beneficiary
        reactor = sec("ReactorEPCMakers", 1.20, 0.80, 3, "reactor_epc_demand | downstream | forward")
        cable = sec("CableOEMs", 0.45, 0.70, 3, "cable_demand_pull | downstream | forward")
        eng = sec("EngineeringEPC", 0.60, 0.75, 3, "engineering_epc_pull | downstream | forward")

        # Upstream
        uranium = sec("UraniumImporters", 0.30, 0.60, 3, "uranium_demand_pull | upstream | back")
        heavy = sec("HeavyWaterSuppliers", 0.25, 0.65, 3, "heavy_water_pull | upstream | back")

        # 3rd-order: Reactor EPC pulls turbine makers
        turbine = RippleConsequence(
            order_level=3,
            target_type="Industry",
            target_name="TurbineMakers",
            transmission_channel="capital_goods_pull | downstream",
            transmission_elasticity=1.0,
            raw_magnitude=0.40,
            probability=0.68,
            lag_time_months=6,
        )
        reactor.downstream_ripples = [turbine]

        primary.second_order_effects = [reactor, cable, eng, uranium, heavy]

        extraction = MacroEventExtraction(
            event_name="Nuclear Energy Mission (100 GW by 2047, conditional incentives)",
            event_category="Policy",
            primary_effects=[primary],
        )
        return self.spawn_transient_event(
            event_name=extraction.event_name,
            event_category=extraction.event_category,
            doc_id=None,
            extraction=extraction,
            primary_target=self.NUCLEAR_PRIMARY,
            event_id="NUCLEAR_MISSION",
            max_hops=3,
        )

    # ------------------------------------------------------------------
    # 5. Trace the transient chain (delegates to causal_engine PN/MN/S)
    # ------------------------------------------------------------------
    def trace_transient_chain(self, event_id: str, max_hops: int = 3) -> List[Dict[str, Any]]:
        """Delegate to ``causal_engine.trace_ripple_chain`` (ordered by S DESC)."""
        return self.causal.trace_ripple_chain(event_id, max_hops)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _summarize(event_name: str, nuance: Dict[str, Any], n_primary: int) -> str:
        parts = [f"{event_name} — {n_primary} primary effect(s)"]
        if nuance.get("pct_reduction"):
            parts.append(f"relief {nuance['pct_reduction']:.0f}%")
        if nuance.get("effective_date"):
            parts.append(f"effective {nuance['effective_date']}")
        if nuance.get("exceptions"):
            parts.append("exceptions: " + ", ".join(nuance["exceptions"]))
        if nuance.get("conditional_flag"):
            parts.append("conditional: " + (nuance.get("conditional_detail") or "yes"))
        return " | ".join(parts)


# ----------------------------------------------------------------------
# Module-level convenience wrappers (CLI-callable; cli.py can import these)
# ----------------------------------------------------------------------
_spawner = EventGraphSpawner()


def spawn_us_tariff_textile_relief(manager=None) -> Dict[str, Any]:
    """Convenience: spawn the US_TARIFF_TEXTILE_RELIEF transient graph."""
    sp = EventGraphSpawner(manager) if manager is not None else _spawner
    return sp.spawn_us_tariff_textile_relief()


def spawn_steel_safeguard_duty(manager=None) -> Dict[str, Any]:
    """Convenience: spawn the STEEL_SAFEGUARD_DUTY transient graph."""
    sp = EventGraphSpawner(manager) if manager is not None else _spawner
    return sp.spawn_steel_safeguard_duty()


def spawn_rail_capex_push(manager=None) -> Dict[str, Any]:
    """Convenience: spawn the RAIL_CAPEX_PUSH transient graph."""
    sp = EventGraphSpawner(manager) if manager is not None else _spawner
    return sp.spawn_rail_capex_push()


def spawn_nuclear_mission(manager=None) -> Dict[str, Any]:
    """Convenience: spawn the NUCLEAR_MISSION transient graph."""
    sp = EventGraphSpawner(manager) if manager is not None else _spawner
    return sp.spawn_nuclear_mission()


def spawn_event_graph(event: str, max_hops: int = 3, doc_id: Optional[int] = None,
                      event_category: str = "Trade", manager=None) -> Dict[str, Any]:
    """CLI-callable wrapper. Dispatches a known transient event id to its spawner.

    Returns the spawn result dict. Unknown event ids raise ``NotImplementedError`` with
    guidance (extensibility point for future transient events).
    """
    sp = EventGraphSpawner(manager) if manager is not None else _spawner
    if event == "US_TARIFF_TEXTILE_RELIEF":
        return sp.spawn_us_tariff_textile_relief()
    if event == "STEEL_SAFEGUARD_DUTY":
        return sp.spawn_steel_safeguard_duty()
    if event == "RAIL_CAPEX_PUSH":
        return sp.spawn_rail_capex_push()
    if event == "NUCLEAR_MISSION":
        return sp.spawn_nuclear_mission()
    raise NotImplementedError(
        f"No transient spawner registered for event '{event}'. "
        f"Add a spawner method in reality_engine/processing/event_graph.py and wire it here."
    )


def cmd_spawn_event_graph(args) -> None:
    """CLI command handler (importable by cli.py). Prints a tabular spawn report."""
    import pandas as pd

    event = getattr(args, "event", "US_TARIFF_TEXTILE_RELIEF")
    max_hops = getattr(args, "max_hops", 3)
    doc_id = getattr(args, "doc_id", None)
    result = spawn_event_graph(event, max_hops=max_hops, doc_id=doc_id)

    print("\n" + "=" * 75)
    print(f"  TRANSIENT EVENT-GRAPH SPAWN: {result['event_id']}")
    print("=" * 75)
    print(f"  events_created   : {result['events_created']}")
    print(f"  ripples_created  : {result['ripples_created']}")
    print(f"  status           : {result['status']}")
    nu = result.get("nuance", {})
    print(f"  pct_reduction    : {nu.get('pct_reduction')}")
    print(f"  effective_date   : {nu.get('effective_date')}")
    print(f"  exceptions       : {nu.get('exceptions')}")
    print(f"  conditional_flag : {nu.get('conditional_flag')}")

    chain = _spawner.trace_transient_chain(result["event_id"], max_hops)
    if chain:
        rows = [{
            "Order": c["order_level"],
            "ripple_id": c.get("ripple_id"),
            "Raw": c.get("raw"),
            "Prob": c.get("prob"),
            "Beta": c.get("beta"),
            "Lag": c.get("lag"),
            "S": c.get("s"),
            "Pruned": c.get("pruned"),
        } for c in chain]
        print(pd.DataFrame(rows).to_string(index=False))
        top = max(chain, key=lambda x: x["s"])
        print(f"\n  Biggest beneficiary (max S): order_level={top['order_level']} "
              f"ripple_id={top['ripple_id']} S={top['s']}")
        if top["order_level"] == 1:
            print("  WARNING: primary IS the biggest beneficiary (acceptance violated).")
        else:
            print("  ACCEPTANCE OK: primary != biggest beneficiary.")


# Backwards-friendly alias matching the spec's suggested call site.
spawner = _spawner
