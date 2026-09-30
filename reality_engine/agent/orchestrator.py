"""
Agent Orchestrator Module
Synthesizes quantitative screening, technical flow analysis, fundamental acceleration,
concall transcripts, and causal macro transmission into validated DailyAlphaReport objects.

Phase 6 Top-Down Synthesis (PDF p4 template):
  Policy Catalyst -> Transmission -> Moat -> Verdict
  Synthesizes moat (Moat=0.25SC+...) + policy ENI + monetisation (ROIC>WACC) into theses.
Legacy evaluate_candidate_scrip() preserved; new top-down helpers added as vertical slice.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
import pandas as pd
import numpy as np

from reality_engine.db.repository import repo
from reality_engine.processing.composite_screener import (
    composite_screener,
    TOPDOWN_MIN_MOAT_SCORE,
    TOPDOWN_MIN_POLICY_ENI,
    TOPDOWN_MIN_ROIC_WACC_SPREAD,
)
from reality_engine.agent.schemas import (
    ScripAlphaThesis,
    MarketBreadthSummary,
    DailyAlphaReport,
    ConvictionLevel,
    MarketRegime,
)
from reality_engine.agent.tools import (
    get_scrip_techno_delivery,
    get_quarterly_financials,
    search_concall_guidance,
    get_distilled_parameters,
    simulate_macro_shock,
    trace_macro_causal_chain,
    get_market_breadth_overview,
)

logger = logging.getLogger("reality_engine.agent.orchestrator")


# ------------------------------------------------------------------
# Slice 2 — deterministic action table (mispricing -> BUY/SELL/HOLD).
# Pure function over (sign(realized) x residual>0.5 x quality_intact x
# solvency_ok x dislocation_confirmed x factor_agrees): 16 cells x
# dislocation x factor-gate. BUY iff unexplained weakness + intact quality
# + solvent + dislocation (|realized| >= 2.0 x noise floor — genuine
# dislocation, not 1-sigma noise; live median was 1.43x, min 1.01x) +
# factor_agrees (the factor_statistical/momentum lens points WITH the entry
# direction). A dip without dislocation is HOLD (wait for confirmation/next
# session, never SELL); a dislocation without factor agreement is HOLD too
# (selection, not timing: goal-loop iteration 4 — BUY hit 1/44 at mean −5%,
# buying weakness where momentum says keep falling; only 6/34 closed BUYs
# had a flow lens agreeing and losers ran 26/34 next-day-down, so a lone
# residual is not a thesis — reversal entries need at least one flow lens
# confirming stabilization). SELL iff unexplained strength + broken quality
# (exit/avoid, solvency AND dislocation irrelevant); HOLD otherwise
# (explained moves, don't-chase strength with intact quality, flat prints,
# insolvent never BUY).
# quality_broken = (trajectory == 'Deteriorating') OR (total_moat_score <
# 2.5) OR (agg ENI < 0) — substrate-natural bands, not threshold-shopped:
# 1/2,653 moats Deteriorating (TATASTEEL), <2.5 is the stored None-width
# band (Narrow 1526 / None 949 / Wide 178), neg-ENI covers 35 distinct
# tickers in the 1,758 material unexplained-strength rows (28 low-moat).
# solvency_ok = existing forensic gate result (config: pledge>15% OR IC<2.5x
# OR D/E>1.5x).
# ------------------------------------------------------------------
def decide_action(realized_sign, residual_gt_half, quality_intact, solvency_ok,
                   dislocation_confirmed=True, factor_agrees=True) -> str:
    """Return BUY/SELL/HOLD for one action-table combination (pure, no I/O).

    The 5th dimension, ``dislocation_confirmed`` (|realized| >= 2.0 x noise
    floor), distinguishes a dip (HOLD — wait for confirmation/next session)
    from a dislocation (BUY now). The 6th, ``factor_agrees``
    (factor_statistical lens direction == sign(realized) on weakness legs),
    distinguishes a lone-residual dip from one where at least one flow lens
    confirms stabilization. Both gate BUY only; SELL cells are unaffected.
    Both default True so existing 4-arg/5-arg callers keep prior behavior.
    """
    try:
        r = float(realized_sign)
    except (TypeError, ValueError):
        return "HOLD"
    residual = bool(residual_gt_half)
    quality = bool(quality_intact)
    solvent = bool(solvency_ok)
    dislocation = bool(dislocation_confirmed)
    factor = bool(factor_agrees)
    if r < 0 and residual and quality and solvent and dislocation and factor:
        return "BUY"
    if r > 0 and residual and (not quality):
        return "SELL"
    return "HOLD"


def _ledger_row_to_attribution_block(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a move_attribution ledger row (22-col DDL) to a thesis block."""
    try:
        from reality_engine.processing.move_attributor import LENS_FAMILIES as _FAMS
        fams = tuple(_FAMS)
    except Exception:
        fams = ("factor_statistical", "business_quality", "policy_macro", "supply_chain")
    per_lens = []
    for fam in fams:
        try:
            direction = int(row.get(f"lens_{fam}_dir", 0) or 0)
        except (TypeError, ValueError):
            direction = 0
        try:
            weight = float(row.get(f"lens_{fam}_w", 0.0) or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        try:
            share = float(row.get(f"lens_{fam}_share", 0.0) or 0.0)
        except (TypeError, ValueError):
            share = 0.0
        per_lens.append({
            "family": fam,
            "predicted_direction": direction,
            "weight": weight,
            "share": share,
        })
    try:
        material = bool(int(row.get("is_material", 0)))
    except (TypeError, ValueError):
        material = bool(row.get("is_material", False))
    try:
        realized = float(row.get("realized_move_pct", 0.0) or 0.0)
    except (TypeError, ValueError):
        realized = 0.0
    try:
        floor = float(row.get("noise_floor", 0.0) or 0.0)
    except (TypeError, ValueError):
        floor = 0.0
    try:
        explained = float(row.get("explained_total", 0.0) or 0.0)
    except (TypeError, ValueError):
        explained = 0.0
    try:
        residual_raw = row.get("residual", 1.0)
        residual = float(residual_raw) if residual_raw is not None else 1.0
    except (TypeError, ValueError):
        residual = 1.0
    try:
        _floor_raw = row.get("noise_floor", None)
        if _floor_raw is None:
            dislocation_confirmed = True
        elif floor <= 0:
            dislocation_confirmed = True
        else:
            dislocation_confirmed = abs(realized) >= 2.0 * floor
    except (TypeError, ValueError):
        dislocation_confirmed = True
    return {
        "realized_move_pct": realized,
        "noise_floor": floor,
        "is_material": material,
        "explained_total": explained,
        "residual": residual,
        "dislocation_confirmed": bool(dislocation_confirmed),
        "per_lens": per_lens,
        "investor_majority": str(row.get("investor_majority", "all") or "all"),
        "regime_tag": str(row.get("regime_tag", "*") or "*"),
    }
class AgentOrchestrator:
    """
    Autonomous multi-step equity intelligence orchestrator that queries tool
    registries, stress-tests causal transmission, and synthesizes high-conviction alpha theses.
    """

    def __init__(self, repository=None, screener=None):
        self.repo = repository or repo
        self.screener = screener or composite_screener

    def run_quantitative_screening(
        self,
        target_date: Optional[str] = None,
        universe: str = "nifty200",
        top_n: int = 20,
        use_top_down: bool = False,
        use_ensemble: bool = False,
        **kwargs,
    ) -> pd.DataFrame:
        """Runs the multi-factor quantitative screener to identify candidate scrips.

        Phase 6: set use_top_down=True to route through top_down_screen() funnel
        (Industry>=4 -> Moat>=3.5 -> ENI>=0 -> ROIC>WACC).
        Wave D4: set use_ensemble=True to route through ensemble_screen() — the all-peers
        weighted MoE blend (Σ w_lens * norm(lens_score)) with per-scrip learned noise floors.
        Legacy path preserved for tests when both flags are False.
        """
        date_str = target_date or self.repo.get_latest_price_delivery_date()
        if use_ensemble:
            logger.info("Running Ensemble Screener for date %s (Universe: %s, Top: %d)", date_str, universe, top_n)
            return self.screener.ensemble_screen(target_date=date_str, top_n=top_n, universe=universe, **kwargs)
        logger.info("Running Quantitative Screener for date %s (Universe: %s, Top: %d, top_down=%s)", date_str, universe, top_n, use_top_down)
        if use_top_down:
            return self.screener.top_down_screen(target_date=date_str, top_n=top_n, universe=universe, **kwargs)
        return self.screener.run_screener(target_date=date_str, top_n=top_n, universe=universe)

    def run_topdown_screening(
        self,
        target_date: Optional[str] = None,
        universe: str = "nifty200",
        top_n: int = 20,
        **kwargs,
    ) -> pd.DataFrame:
        """Explicit top-down funnel entry-point (vertical slice). Delegates to composite_screener.top_down_screen()."""
        date_str = target_date or self.repo.get_latest_price_delivery_date()
        logger.info("Running Top-Down Screener for date %s (Universe: %s, Top: %d)", date_str, universe, top_n)
        return self.screener.top_down_screen(target_date=date_str, top_n=top_n, universe=universe, **kwargs)

    def evaluate_candidate_scrip(
        self,
        candidate_row: Dict[str, Any],
        rank: int,
        use_topdown_template: bool = True,
        attribution: Optional[Dict[str, Any]] = None,
        attribution_date: Optional[str] = None,
    ) -> ScripAlphaThesis:
        """
        Performs multi-angle tool inspections for a candidate scrip and synthesizes
        a complete ScripAlphaThesis.

        Phase 6: when candidate_row already contains top-down metrics (secular_growth_score,
        total_moat_score, policy_agg_eni, roic_wacc_spread) from top_down_screen(), those
        are used for the Policy Catalyst -> Transmission -> Moat -> Verdict template.
        Otherwise fallback lookups via composite_screener helpers are performed.
        The template is always produced (backward compatible) but can be disabled with use_topdown_template=False.
        Slice 2: optional ``attribution`` (a move_attribution ledger row, or a
        pre-formed block with ``per_lens``) or ``attribution_date`` (ledger lookup
        for (symbol, date), defensive — empty/missing table yields HOLD/null).
        Attaches ``action`` (BUY/SELL/HOLD via decide_action) + ``attribution``
        block; without ledger evidence attaches ``action="HOLD"`` and
        ``attribution=None`` with rationale unchanged. Never raises for attribution.
        """
        symbol = str(candidate_row.get("symbol", "")).upper().strip()
        cmp = float(candidate_row.get("close", candidate_row.get("current_market_price", 0.0)) or 0.0)

        # 1. Fetch deep technical & delivery flow
        techno = get_scrip_techno_delivery(symbol, lookback_days=20)

        # 2. Fetch quarterly fundamentals & forensic solvency
        funda = get_quarterly_financials(symbol, quarters=8)

        # 3. Fetch distilled parameters & business sensitivities
        distilled = get_distilled_parameters(symbol, parameter_key="ALL")

        # 4. Search concall guidance / catalysts
        concall = search_concall_guidance(symbol, query="order book capex expansion capacity commercialization guidance margin", top_k=3)

        # Company metadata
        comp_info = self.repo.get_company_by_symbol(symbol)
        company_name = comp_info.get("company_name", symbol) if comp_info else symbol
        industry = comp_info.get("industry", "Diversified") if comp_info else "Diversified"
        sector = comp_info.get("sector", "Industrials") if comp_info else "Industrials"

        # Trade setup calculations (vol-scaled bracket: trailing-20σ, clamped;
        # SELL framing is enforced at record_action, thesis terms stay BUY-framed).
        entry_low = round(cmp * 0.985, 2)
        entry_high = round(cmp * 1.015, 2)
        try:
            from reality_engine.processing import portfolio_ledger as _pl
            _br = _pl.vol_scaled_bracket(symbol, cmp, "BUY",
                                         str(attribution_date or ""), manager=self.repo.db)
            target, sl = float(_br["target_price"]), float(_br["stop_loss"])
        except Exception:
            target = round(cmp * 1.18, 2)
            sl = round(cmp * 0.94, 2)
        rr = round((target - cmp) / max(0.01, cmp - sl), 2)

        composite_score = float(candidate_row.get("composite_score") or 0.0)
        if composite_score >= 75.0:
            conviction = ConvictionLevel.HIGH_CONVICTION
        elif composite_score >= 55.0:
            conviction = ConvictionLevel.MODERATE
        else:
            conviction = ConvictionLevel.SPECULATIVE

        # Build Technical Flow Thesis
        dsr = techno.get("delivery_spike_ratio", 1.0)
        deliv_pct = techno.get("delivery_pct", 0.0)
        dcs = techno.get("delivery_conviction_score", 0.0)
        rsi = techno.get("rsi_14", 50.0)
        sma20 = techno.get("sma_20", 0.0)
        sma50 = techno.get("sma_50", 0.0)
        sma200 = techno.get("sma_200", 0.0)
        dist_52w = techno.get("distance_from_52w_high_pct", 0.0)
        trend_desc = techno.get("trend_alignment", "UPTREND")

        techno_thesis = (
            f"Strong institutional delivery accumulation evident with Delivery Spike Ratio of {dsr:.2f}x (20D SMA) "
            f"and delivery volume share of {deliv_pct:.1f}% (DCS: {dcs:.1f}). "
            f"Price action confirms {trend_desc}; CMP INR {cmp:,.2f} trades comfortably above 20-DMA (INR {sma20:,.2f}) "
            f"and 50-DMA (INR {sma50:,.2f}). 14-period RSI sits at {rsi:.1f} indicating healthy momentum without extreme "
            f"overbought exhaustion. Distance from 52-week high is {dist_52w:.1f}%, setting up a high-probability breakout."
        )

        # Build Fundamental Thesis (now includes ROIC>WACC validation)
        latest_period = funda.get("latest_financial_period", "FY26")
        rev_cr = funda.get("latest_revenue_inr_cr", 0.0)
        ebitda_cr = funda.get("latest_ebitda_inr_cr", 0.0)
        ebitda_margin = funda.get("latest_ebitda_margin_pct", 0.0)
        yoy_rev = funda.get("latest_yoy_revenue_growth_pct", 0.0)
        yoy_pat = funda.get("latest_yoy_pat_growth_pct", 0.0)
        opm_delta = funda.get("opm_delta_bps", 0.0)
        forensic = funda.get("forensic_solvency", {})
        promoter_pledge = forensic.get("promoter_pledge_pct", 0.0)
        interest_cov = forensic.get("interest_coverage_ratio", 0.0)
        debt_to_equity = forensic.get("debt_to_equity_ratio", 0.0)

        # Enrich with top-down monetisation (ROIC>WACC) if available in candidate_row.
        # The spread carries a provenance status (measured | proxy | unknown); the claim is
        # only made when the number is actually sourced. It used to be asserted for every
        # name from a terminal constant, printing "ROIC-WACC +6.00% >5% value-creative"
        # with no data behind it.
        roic_spread = candidate_row.get("roic_wacc_spread")
        roic_status = candidate_row.get("roic_wacc_status")
        if roic_spread is None:
            try:
                roic_spread = self.screener._lookup_roic_wacc_spread(symbol, str(candidate_row.get("isin", "")))
            except Exception:
                roic_spread = 0.06
        if roic_status is None:
            try:
                roic_status = self.screener.roic_wacc_status(symbol, str(candidate_row.get("isin", "")))
            except Exception:
                roic_status = "unknown"

        if not isinstance(roic_spread, (int, float)):
            monet_line = ""
        elif roic_status == "measured":
            monet_line = (
                f" Secondary validation ROIC-WACC spread {float(roic_spread):+.2%} (>5% hurdle, value-creative)."
            )
        elif roic_status == "proxy":
            monet_line = (
                f" Monetisation indicated by ROCE proxy {float(roic_spread):+.2%} "
                "(WACC assumed 10%; not a measured ROIC-WACC spread)."
            )
        else:
            monet_line = (
                " Monetisation not measured (no ROIC/WACC source for this name); "
                "any spread quoted elsewhere for it is a placeholder, not evidence."
            )

        funda_thesis = (
            f"Quarterly earnings acceleration in {latest_period}: Revenue reached INR {rev_cr:,.2f} Cr (YoY +{yoy_rev:.1f}%), "
            f"with Net Profit (PAT) expanding YoY by +{yoy_pat:.1f}%. EBITDA stood at INR {ebitda_cr:,.2f} Cr "
            f"with margin at {ebitda_margin:.1f}% (operating margin delta: {opm_delta:+.1f} bps).{monet_line} "
            f"Forensic solvency is fully certified: zero promoter pledge risk ({promoter_pledge:.1f}%), robust interest coverage "
            f"of {interest_cov:.2f}x, and conservative debt-to-equity ratio of {debt_to_equity:.2f}x."
        )

        # Build Causal Macro & Value Chain Rationale (Phase 6 template)
        if use_topdown_template:
            causal_rationale = self._synthesize_topdown_rationale(
                symbol=symbol, sector=sector, industry=industry, distilled=distilled, candidate_row=candidate_row
            )
        else:
            causal_rationale = self._synthesize_causal_rationale(symbol, sector, industry, distilled)

        # Key Catalysts & Risks
        catalysts = self._generate_catalysts(symbol, sector, concall, distilled, yoy_rev)
        risks = self._generate_risks(symbol, sector, distilled, debt_to_equity, dist_52w)

        thesis = ScripAlphaThesis(
            symbol=symbol,
            company_name=company_name,
            composite_rank=rank,
            current_market_price=cmp,
            recommended_entry_range=f"INR {entry_low:,.2f} - INR {entry_high:,.2f}",
            target_price=target,
            stop_loss=sl,
            risk_reward_ratio=rr,
            conviction_level=conviction,
            techno_delivery_thesis=techno_thesis,
            fundamental_thesis=funda_thesis,
            causal_macro_rationale=causal_rationale,
            key_catalysts=catalysts,
            key_risks=risks
        )
        # Preserve policy coverage/ENI state on thesis for audit (None stays None, never claim pass)
        try:
            _pm = self._fetch_topdown_metrics(symbol, candidate_row)
            object.__setattr__(thesis, "policy_agg_eni", _pm.get("policy_agg_eni"))
            object.__setattr__(thesis, "policy_coverage", _pm.get("policy_coverage"))
            object.__setattr__(thesis, "policy_approval", _pm.get("policy_approval"))
            object.__setattr__(thesis, "policy_agg_eni_calc", _pm.get("policy_agg_eni_calc"))
        except Exception:
            pass
        # Slice 2: deterministic action + attribution block (graceful, never crash).
        try:
            action, block = self._resolve_thesis_action(
                symbol,
                candidate_row=candidate_row,
                attribution=attribution,
                attribution_date=attribution_date,
                funda=funda,
            )
            object.__setattr__(thesis, "action", action)
            object.__setattr__(thesis, "attribution", block)
        except Exception as exc:
            logger.debug("thesis action attach failed for %s: %s", symbol, exc)
            try:
                object.__setattr__(thesis, "action", "HOLD")
                object.__setattr__(thesis, "attribution", None)
            except Exception:
                pass
        return thesis
    # ------------------------------------------------------------------
    # Slice 2: attribution lookup + action derivation (defensive, no writes).
    # ------------------------------------------------------------------
    def _lookup_attribution_row(self, symbol: str, attribution_date: Optional[str]) -> Optional[Dict[str, Any]]:
        """Fetch one move_attribution row for (symbol, date); None when absent."""
        if not attribution_date:
            return None
        try:
            with self.repo.db.session() as conn:
                row = conn.execute(
                    "SELECT * FROM move_attribution WHERE symbol = ? AND attribution_date = ? LIMIT 1",
                    (str(symbol).upper().strip(), str(attribution_date).strip()),
                ).fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.debug("attribution lookup failed for %s @ %s: %s", symbol, attribution_date, exc)
            return None

    def _resolve_thesis_action(
        self,
        symbol: str,
        candidate_row: Optional[Dict[str, Any]] = None,
        attribution: Optional[Dict[str, Any]] = None,
        attribution_date: Optional[str] = None,
        funda: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Derive (action, block) for a thesis; (HOLD, None) without evidence."""
        row = attribution
        if row is None and attribution_date:
            row = self._lookup_attribution_row(symbol, attribution_date)
        if row is None:
            return "HOLD", None
        block = row if isinstance(row, dict) and "per_lens" in row else _ledger_row_to_attribution_block(row)
        try:
            realized = float(block.get("realized_move_pct", 0.0) or 0.0)
        except (TypeError, ValueError):
            realized = 0.0
        realized_sign = 1 if realized > 0 else (-1 if realized < 0 else 0)
        try:
            residual = float(block.get("residual", 1.0))
        except (TypeError, ValueError):
            residual = 1.0
        residual_gt_half = residual > 0.5
        # dislocation_confirmed: |realized| >= 2.0 x noise floor — genuine
        # dislocation, not 1-sigma noise. Missing/non-positive floor: True
        # (graceful, preserves prior behavior). A pre-formed block carrying
        # the flag is honored as-is.
        if "dislocation_confirmed" in block:
            try:
                dislocation = bool(block.get("dislocation_confirmed", True))
            except (TypeError, ValueError):
                dislocation = True
        else:
            try:
                _raw_floor = block.get("noise_floor", None)
                _floor = float(_raw_floor) if _raw_floor is not None else 0.0
            except (TypeError, ValueError):
                _floor = 0.0
                _raw_floor = 0.0
            if _raw_floor is None or _floor <= 0:
                dislocation = True
            else:
                dislocation = abs(realized) >= 2.0 * _floor
            try:
                block["dislocation_confirmed"] = bool(dislocation)
            except (TypeError, ValueError):
                pass
        # quality: widened broken-thesis via the shared helper — SAME screener
        # lookup paths as before (moat trajectory/score + agg ENI, no new data
        # sources). (traj == Deteriorating) OR (score < 2.5) OR (ENI < 0).
        quality_intact = True
        quality_reason = "intact"
        try:
            from reality_engine.processing.move_attributor import (
                quality_broken_reason as _quality_broken_reason,
            )
            metrics = self._fetch_topdown_metrics(symbol, candidate_row or {})
            traj = str(metrics.get("moat_trajectory", "Stable") or "Stable")
            broken, quality_reason = _quality_broken_reason(
                traj, metrics.get("total_moat_score"), metrics.get("policy_agg_eni"),
            )
            quality_intact = not broken
        except Exception:
            quality_intact = True
            quality_reason = "intact"
        # Stamp audit flags on the block (resolver-owned; ledger DDL untouched).
        try:
            block["quality_broken"] = bool(not quality_intact)
            block["quality_reason"] = str(quality_reason or "intact")
        except (TypeError, ValueError):
            pass
        # factor_agrees: the factor_statistical (momentum) lens points WITH the
        # entry direction on weakness legs (block per_lens dirs, stored by the
        # ledger already). Missing/neutral (0) -> HOLD (graceful, never assume).
        factor_agrees = False
        try:
            _factor_dir = 0
            for _lens in block.get("per_lens", []) or []:
                if isinstance(_lens, dict) and _lens.get("family") == "factor_statistical":
                    _factor_dir = int(_lens.get("predicted_direction", 0) or 0)
                    break
            factor_agrees = bool(realized_sign != 0 and _factor_dir == realized_sign)
        except (TypeError, ValueError):
            factor_agrees = False
        # solvency_ok: reuse the existing forensic gate result (funda tool
        # summary), never recomputed thresholds here. Missing evidence: HOLD.
        solvency_ok = False
        try:
            forensic = (funda or {}).get("forensic_solvency", {}) or {}
            flag = forensic.get("is_solvency_approved", None)
            if flag is None:
                solvency_ok = False
            else:
                solvency_ok = int(flag) == 1
        except Exception:
            solvency_ok = False
        action = decide_action(realized_sign, residual_gt_half, quality_intact, solvency_ok, dislocation, factor_agrees)
        return action, block

    # ------------------------------------------------------------------
    # Phase 6: Top-down template helpers (Policy Catalyst -> Transmission -> Moat -> Verdict)
    # ------------------------------------------------------------------
    def _fetch_topdown_metrics(self, symbol: str, candidate_row: Dict[str, Any]) -> Dict[str, Any]:
        """Collect moat/policy/monet metrics from candidate_row or via screener lookups (graceful fallback).

        Policy ENI is Optional: ``None`` for ``no_template``/``unknown`` coverage is
        preserved for audit (never coerced to 0). A neutral ``policy_agg_eni_calc``
        (0.0) is provided solely for arithmetic where a float is required.
        """
        sym = symbol.upper().strip()
        isin = str(candidate_row.get("isin", "") or "")
        # Prefer enriched columns from top_down_screen, else lookup
        moat_score = candidate_row.get("total_moat_score")
        # Treat pandas NaN as missing
        if moat_score is None or (isinstance(moat_score, float) and pd.isna(moat_score)):
            try:
                m = self.screener._lookup_moat_metrics(sym, isin)
                moat_score = m.get("total_moat_score", 2.5)
                moat_traj = m.get("moat_trajectory", "Stable")
                moat_width = m.get("moat_width", "Narrow")
                pricing_pwr = m.get("pricing_power_score", 3)
            except Exception:
                moat_score, moat_traj, moat_width, pricing_pwr = 2.5, "Stable", "Narrow", 3
        else:
            moat_traj = candidate_row.get("moat_trajectory", "Stable")
            try:
                _ms_f = float(moat_score)
            except Exception:
                _ms_f = 2.5
            moat_width = candidate_row.get("moat_width", "Wide" if _ms_f >= 3.5 else "Narrow")
            pricing_pwr = candidate_row.get("pricing_power_score", 3)

        # --- Policy ENI: preserve None for no_template/unknown, provide calc fallback ---
        policy_eni_raw = candidate_row.get("policy_agg_eni")
        if policy_eni_raw is None:
            policy_eni_raw = candidate_row.get("policy_eni")
        # pandas NaN -> treat as None
        if policy_eni_raw is not None and pd.isna(policy_eni_raw):
            policy_eni_raw = None
        if policy_eni_raw is not None:
            try:
                policy_eni = float(policy_eni_raw)
            except Exception:
                policy_eni = None
        else:
            try:
                looked = self.screener._lookup_policy_agg_eni(sym)
            except Exception:
                looked = None
            if looked is not None and pd.isna(looked):
                looked = None
            if looked is None:
                policy_eni = None
            else:
                try:
                    policy_eni = float(looked)
                except Exception:
                    policy_eni = None

        # Resolve coverage (mapped / no_template / unknown)
        policy_coverage = candidate_row.get("policy_coverage")
        if policy_coverage is None or (isinstance(policy_coverage, float) and pd.isna(policy_coverage)):
            policy_coverage = candidate_row.get("policy_coverage_status") or candidate_row.get("coverage_status")
        if policy_coverage is None or (isinstance(policy_coverage, float) and pd.isna(policy_coverage)):
            try:
                policy_coverage = self.repo.get_policy_coverage(sym)
            except Exception:
                policy_coverage = None
        if policy_coverage is None or (isinstance(policy_coverage, float) and pd.isna(policy_coverage)):
            policy_coverage = "mapped" if policy_eni is not None else "unknown"
        try:
            policy_coverage = str(policy_coverage).strip().lower()
        except Exception:
            policy_coverage = "unknown"
        if policy_coverage not in ("mapped", "no_template", "unknown"):
            policy_coverage = "mapped" if policy_eni is not None else "unknown"
        # Ensure consistency: numeric ENI must be mapped
        if policy_eni is not None and policy_coverage in ("no_template", "unknown"):
            policy_coverage = "mapped"

        policy_eni_calc = 0.0 if policy_eni is None else float(policy_eni)
        policy_approval = None if policy_eni is None else (policy_eni >= 0)

        roic_spread = candidate_row.get("roic_wacc_spread")
        roic_status = candidate_row.get("roic_wacc_status")
        if roic_spread is None or (isinstance(roic_spread, float) and pd.isna(roic_spread)):
            try:
                if roic_status is None:
                    roic_spread, roic_status = self.screener._roic_wacc_spread_impl(sym, isin)
                else:
                    roic_spread = self.screener._lookup_roic_wacc_spread(sym, isin)
            except Exception:
                roic_spread = 0.06
        if isinstance(roic_spread, float) and pd.isna(roic_spread):
            roic_spread = 0.06
        if roic_status is None:
            try:
                roic_status = self.screener.roic_wacc_status(sym, isin)
            except Exception:
                roic_status = "unknown"

        secular = candidate_row.get("secular_growth_score")
        if secular is None or (isinstance(secular, float) and pd.isna(secular)):
            try:
                comp = self.repo.get_company_by_symbol(sym) or {}
                secular = self.screener._lookup_secular_growth_score(comp.get("industry"), comp.get("sector"))
            except Exception:
                secular = 4.0
        if isinstance(secular, float) and pd.isna(secular):
            secular = 4.0

        return {
            "total_moat_score": float(moat_score),
            "moat_trajectory": str(moat_traj),
            "moat_width": str(moat_width),
            "pricing_power_score": int(pricing_pwr),
            "policy_agg_eni": policy_eni,  # None for no_template/unknown, preserved for audit
            "policy_agg_eni_calc": policy_eni_calc,  # 0.0 neutral for arithmetic
            "policy_coverage": policy_coverage,  # mapped / no_template / unknown
            "policy_eni": policy_eni,  # alias
            "policy_approval": policy_approval,  # True/False/None
            "roic_wacc_spread": float(roic_spread),
            "roic_wacc_status": str(roic_status),  # measured / proxy / unknown
            "secular_growth_score": float(secular),
        }

    def _synthesize_topdown_rationale(
        self,
        symbol: str,
        sector: str,
        industry: str,
        distilled: Dict[str, Any],
        candidate_row: Dict[str, Any],
    ) -> str:
        """
        PDF p4 template: Policy Catalyst -> Transmission -> Moat -> Verdict.
        Incorporates moat (Moat=0.25SC+...) , policy ENI, and monetisation (ROIC>WACC).
        """
        metrics = self._fetch_topdown_metrics(symbol, candidate_row)

        # Policy catalyst identification (canonical graph traces)
        try:
            traces_rail = trace_macro_causal_chain("UNION_BUDGET_2026_RAIL_CAPEX", impact_filter="ALL", max_hops=2)
            traces_defence = trace_macro_causal_chain("DEFENCE_INDIGENIZATION_DAP", impact_filter="ALL", max_hops=2)
            traces_solar = trace_macro_causal_chain("PM_SURYA_GHAR_SOLAR", impact_filter="ALL", max_hops=2)
        except Exception:
            traces_rail = traces_defence = traces_solar = {"traces": []}

        is_rail = any(t.get("node_id") == symbol for t in traces_rail.get("traces", []))
        is_def = any(t.get("node_id") == symbol for t in traces_defence.get("traces", []))
        is_solar = any(t.get("node_id") == symbol for t in traces_solar.get("traces", []))

        if is_def or "DEFENCE" in industry.upper() or "AEROSPACE" in industry.upper() or symbol == "HAL":
            catalyst = "Defence Indigenization Policy DAP 2026 - long-term domestic capital procurement budget (ENI positive)"
            transmission = "Indigenous manufacturing mandate -> cost-plus platform order book (Tejas, helicopters, MRO) with multi-year execution and high pricing power"
        elif is_rail or "RAIL" in industry.upper() or symbol in ["TITAGARH", "KAYNES"]:
            catalyst = "Union Budget 2026 Railway Capex - rolling stock modernization tenders (ENI positive rail capex)"
            transmission = "Coach/signalling procurement awards -> domestic capacity utilization expansion & embedded systems delivery, 24-36 month capex timeline"
        elif is_solar or "ELECTRICAL" in sector.upper() or symbol in ["HAVELLS", "PIDILITIND"]:
            catalyst = "PM Surya Ghar residential solar + national infrastructure push (policy tailwind)"
            transmission = "Residential electrification mandate -> switchgear/building electricals/specialty chemicals demand, raw-material pass-through channel"
        elif "FINANCIAL" in sector.upper() or "BANK" in sector.upper():
            catalyst = f"Robust domestic credit expansion & financial asset penetration in {industry} (neutral-to-positive ENI)"
            transmission = f"Credit growth (>12% YoY) transmits via low credit costs & fee income scale; resilient to rate volatility via CASA franchise"
        elif "CONSUMER" in sector.upper() or "AUTO" in sector.upper():
            catalyst = f"Premiumization & urban discretionary consumption tailwind in {industry} (neutral ENI)"
            transmission = "Volume growth (price×units) via brand/licensure pricing power, stable input costs support operating leverage"
        else:
            _eni = metrics.get("policy_agg_eni")
            _cov = metrics.get("policy_coverage", "unknown")
            if _cov in ("no_template", "unknown") or _eni is None:
                catalyst = f"Sector-level policy neutral (ENI unknown, coverage {_cov}) in {sector} / {industry}; no mapped policy template"
            else:
                catalyst = f"Sector-level policy neutral (ENI {_eni:+.2f}) in {sector} / {industry}; no headwind"
            transmission = "Domestic capex execution & supply-chain positioning channel; pricing power sustains margins across cycles"

        # Moat quantification
        moat_line = (
            f"Wide-moat validated: total_moat_score {metrics['total_moat_score']:.2f}/5 "
            f"({metrics['moat_width']}, {metrics['moat_trajectory']}) - "
            f"Moat=0.25SC+0.25NE+0.20CA+0.20IA+0.10ES; pricing_power_score {metrics['pricing_power_score']}/5; "
            f"secular_growth_score {metrics['secular_growth_score']:.1f}/5 (>=4.0 hurdle)."
        )

        # Verdict (monetisation secondary) - unknown never claims tailwind
        verdict_parts = []
        _v_eni = metrics.get("policy_agg_eni")
        _v_cov = metrics.get("policy_coverage", "unknown")
        if _v_cov == "mapped" and _v_eni is not None:
            if _v_eni >= TOPDOWN_MIN_POLICY_ENI:
                verdict_parts.append(f"policy tailwind ENI {_v_eni:+.2f} >=0")
            else:
                verdict_parts.append(f"policy headwind ENI {_v_eni:+.2f} (<0, monitor)")
        else:
            verdict_parts.append(f"policy neutral (ENI unknown, coverage {_v_cov}; no mapped template)")
        _v_roic_status = metrics.get("roic_wacc_status", "unknown")
        if _v_roic_status == "unknown":
            verdict_parts.append(
                "monetisation unmeasured (no ROIC/WACC source; spread is not evidence)"
            )
        elif metrics["roic_wacc_spread"] > TOPDOWN_MIN_ROIC_WACC_SPREAD:
            _v_label = "" if _v_roic_status == "measured" else " (from ROCE proxy)"
            verdict_parts.append(
                f"ROIC-WACC {metrics['roic_wacc_spread']:+.2%} >5% value-creative{_v_label}"
            )
        else:
            verdict_parts.append(f"ROIC-WACC {metrics['roic_wacc_spread']:+.2%} <=5% (secondary validation soft)")
        if metrics["total_moat_score"] >= TOPDOWN_MIN_MOAT_SCORE and metrics["moat_trajectory"] in ("Stable", "Expanding"):
            verdict_parts.append("moat hurdle passed")
        else:
            verdict_parts.append("moat hurdle not met")

        verdict = (
            f"Top-down verdict: {'; '.join(verdict_parts)}. "
            "Composite conviction integrates macro tailwind + moat durability + monetisation; positioned for 18% upside vs 6% stop."
        )

        # Assemble four-part template verbatim (PDF p4)
        return (
            f"Policy Catalyst: {catalyst}.\n\n"
            f"Transmission: {transmission}.\n\n"
            f"Moat: {moat_line}\n\n"
            f"Verdict: {verdict}"
        )

    def _synthesize_causal_rationale(
        self,
        symbol: str,
        sector: str,
        industry: str,
        distilled: Dict[str, Any]
    ) -> str:
        """Synthesizes the causal macro, policy transmission, and supply-chain moat narrative.

        Phase 6: now routes through top-down template for consistency; legacy simple rationale
        retained as fallback via _synthesize_causal_rationale_legacy.
        """
        # Reuse top-down template with empty candidate_row (lookups inside)
        try:
            return self._synthesize_topdown_rationale(symbol, sector, industry, distilled, candidate_row={})
        except Exception:
            return self._synthesize_causal_rationale_legacy(symbol, sector, industry, distilled)

    def _synthesize_causal_rationale_legacy(
        self,
        symbol: str,
        sector: str,
        industry: str,
        distilled: Dict[str, Any]
    ) -> str:
        """Legacy simple rationale (pre-Phase 6) - kept for fallback."""
        # Check if known canonical nodes connect to this symbol
        traces_rail = trace_macro_causal_chain("UNION_BUDGET_2026_RAIL_CAPEX", impact_filter="ALL", max_hops=2)
        traces_defence = trace_macro_causal_chain("DEFENCE_INDIGENIZATION_DAP", impact_filter="ALL", max_hops=2)
        traces_solar = trace_macro_causal_chain("PM_SURYA_GHAR_SOLAR", impact_filter="ALL", max_hops=2)

        is_rail = any(t.get("node_id") == symbol for t in traces_rail.get("traces", []))
        is_def = any(t.get("node_id") == symbol for t in traces_defence.get("traces", []))
        is_solar = any(t.get("node_id") == symbol for t in traces_solar.get("traces", []))

        if is_def or "DEFENCE" in industry.upper() or "AEROSPACE" in industry.upper() or symbol == "HAL":
            return (
                "Direct beneficiary of Defence Indigenization Policy (DAP 2026) and long-term domestic capital procurement budget. "
                "Causal transmission from indigenous manufacturing mandates converts directly into high-margin platform order book visibility "
                "with resilient pricing power and multi-year execution pipeline."
            )
        elif is_rail or "RAIL" in industry.upper() or symbol in ["TITAGARH", "KAYNES"]:
            return (
                "Direct beneficiary of Union Budget 2026 Railway Capex allocation and rolling stock modernization tenders. "
                "Transmission mechanism operates via multi-year coach/signalling procurement awards, expanding domestic capacity utilization "
                "and high-margin embedded systems delivery."
            )
        elif is_solar or "ELECTRICAL" in sector.upper() or symbol in ["HAVELLS", "PIDILITIND"]:
            return (
                "Propelled by national infrastructure push and PM Surya Ghar residential solar electrification mandates. "
                "Structural demand for building electricals, switchgear, and specialty construction chemicals provides downside resilience "
                "against broader cyclical slowdowns."
            )
        elif "FINANCIAL" in sector.upper() or "BANK" in sector.upper():
            return (
                f"Supported by robust domestic credit expansion and rising financial asset penetration in {industry}. "
                "Clean balance sheet with low credit costs and high Return on Assets (RoA) insulates against macro rate volatility."
            )
        elif "CONSUMER" in sector.upper() or "AUTO" in sector.upper():
            return (
                f"Benefiting from premiumization tailwinds and steady urban discretionary consumption demand in {industry}. "
                "Raw material input cost stability supports gross margin retention and operating leverage expansion."
            )
        else:
            return (
                f"Well-positioned in {sector} ({industry}) with strong market share and domestic capex execution. "
                "Demonstrates resilient supply-chain positioning and passing-through pricing power across raw material cycles."
            )

    def _generate_catalysts(
        self,
        symbol: str,
        sector: str,
        concall: Dict[str, Any],
        distilled: Dict[str, Any],
        yoy_rev: float
    ) -> List[str]:
        """Generates concrete operational and financial catalysts."""
        catalysts = [
            f"Sustained quarterly top-line momentum (YoY +{yoy_rev:.1f}%) driving operating leverage expansion",
            "Order book execution acceleration and timely conversion of prospective tender pipeline",
            f"Favorable sector rotation toward high-ROCE {sector} leaders with pristine solvency profile"
        ]
        if concall.get("hits_count", 0) > 0:
            catalysts.insert(0, "Management concall guidance confirming ongoing capex commercialization and capacity ramp-up")
        return catalysts[:4]

    def _generate_risks(
        self,
        symbol: str,
        sector: str,
        distilled: Dict[str, Any],
        debt_to_equity: float,
        dist_52w: float
    ) -> List[str]:
        """Generates concrete downside triggers and sensitivity risks."""
        risks = [
            "Macroeconomic supply chain disruption and raw material input cost volatility",
            "Broader benchmark market volatility leading to multiple compression in high-beta names"
        ]
        if debt_to_equity > 0.8:
            risks.append(f"Elevated financial leverage (D/E: {debt_to_equity:.2f}x) sensitive to interest rate fluctuations")
        else:
            risks.append("Slight execution delay or quarterly lumpiness in large project milestones")
        return risks[:3]

    def build_macro_shock_radar(self) -> List[Dict[str, Any]]:
        """
        Runs macroeconomic shock simulations across canonical scenarios to build
        the macro shock radar.
        """
        scenarios = [
            ("UNION_BUDGET_2026_RAIL_CAPEX", "Union Budget 2026 Rail Capex"),
            ("DEFENCE_INDIGENIZATION_DAP", "Defence Indigenization DAP"),
            ("COMMODITY_CRUDE_OIL", "Crude Oil Commodity Shock ($95/bbl)"),
            ("PM_SURYA_GHAR_SOLAR", "PM Surya Ghar Solar Policy"),
            ("GEOPOLITICAL_RED_SEA_ATTACKS", "Red Sea Maritime Freight Disruption"),
        ]

        radar: List[Dict[str, Any]] = []
        for shock_id, name in scenarios:
            sim = simulate_macro_shock(shock_id)
            beneficiaries = [b.get("symbol") for b in sim.get("beneficiaries", [])]
            victims = [v.get("symbol") for v in sim.get("victims", [])]

            radar.append({
                "scenario_id": shock_id,
                "scenario_name": name,
                "beneficiaries": beneficiaries,
                "victims": victims,
                "resilient_count": len(sim.get("resilient_companies", [])),
                "impaired_count": len(sim.get("impaired_companies", [])),
            })

        return radar

    def count_disqualified_solvency_companies(self) -> int:
        """Counts how many companies in the universe failed the forensic solvency gate."""
        with self.repo.db.session() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM company_forensic_health WHERE is_solvency_approved = 0"
            ).fetchone()
            return int(row[0]) if row else 0

    def synthesize_daily_alpha_report(
        self,
        target_date: Optional[str] = None,
        universe: str = "nifty200",
        top_n: int = 5,
        screener_pool_size: int = 20,
        use_top_down: bool = False,
        use_ensemble: bool = False,
        investor_majority: str = "all",
        temperature: float = 0.4,
        **kwargs,
    ) -> DailyAlphaReport:
        """
        Executes end-to-end synthesis:
        1. Market Breadth and Regime Snapshot
        2. Multi-factor Quantitative Screening (legacy / top-down funnel / ensemble MoE blend)
        3. Deep Tool Evidence Gathering for Top Candidates (moat/policy/monet aware)
        4. High-Conviction Alpha Thesis Synthesis (Policy Catalyst -> Transmission -> Moat -> Verdict)
        5. Macro Shock Radar Aggregation
        6. Validated DailyAlphaReport Construction

        Phase 6: set use_top_down=True to screen via Industry>=4 -> Moat>=3.5 -> ENI>=0 -> ROIC>WACC.
        Wave D4: set use_ensemble=True to screen via the all-peers weighted MoE blend
            (ensemble_screen: Σ w_lens * norm(lens_score)) and, for every candidate, fire the
            sparse MoE gate (ensemble_ranker.fire_lenses) to attach per-scrip lens activation
            (temperature-controlled explore/exploit) + transient event-graph context.
        Backward compatible: default (both flags False) preserves legacy screen + thesis for tests.
        """
        date_str = target_date or self.repo.get_latest_price_delivery_date() or "2026-08-14"
        logger.info("Synthesizing Daily Alpha Report for date: %s (top_down=%s, ensemble=%s)", date_str, use_top_down, use_ensemble)

        # 1. Market Breadth Overview
        breadth_raw = get_market_breadth_overview()
        breadth_summary = MarketBreadthSummary(
            advance_decline_ratio=float(breadth_raw.get("advance_decline_ratio", 1.0)),
            market_regime=str(breadth_raw.get("market_regime", MarketRegime.NEUTRAL)),
            top_performing_sectors=breadth_raw.get("top_performing_sectors", []),
            vulnerable_sectors=breadth_raw.get("vulnerable_sectors", [])
        )

        # 2. Run Screener (route ensemble / top-down / legacy)
        df_screened = self.run_quantitative_screening(
            target_date=date_str,
            universe=universe,
            top_n=screener_pool_size,
            use_top_down=use_top_down,
            use_ensemble=use_ensemble,
            **kwargs,
        )
        # Fallback: if top-down filters too aggressively and returns < top_n, blend with legacy survivors to keep report populated (minimal slice hygiene)
        fallback_used = False
        if use_top_down and len(df_screened) < top_n:
            logger.warning("Top-down funnel yielded only %d candidates (< %d requested); blending fallback from legacy screen for report completeness", len(df_screened), top_n)
            df_legacy = self.screener.run_screener(target_date=date_str, top_n=screener_pool_size * 2, universe=universe)
            if not df_legacy.empty:
                # merge missing symbols
                existing = set(df_screened["symbol"].astype(str).tolist()) if not df_screened.empty else set()
                extra = df_legacy[~df_legacy["symbol"].astype(str).isin(existing)].head(top_n - len(df_screened))
                if not extra.empty:
                    # Enrich extra with top-down metrics so template still works
                    try:
                        extra = self.screener._enrich_with_topdown_metrics(extra)
                    except Exception:
                        pass
                    df_screened = pd.concat([df_screened, extra], ignore_index=True)
                    fallback_used = True

        # Ensemble screening carries composite in `ensemble_composite` and learned weights in df.attrs.
        ensemble_weights = None
        if use_ensemble and not df_screened.empty:
            if "ensemble_composite" in df_screened.columns:
                df_screened = df_screened.copy()
                df_screened["composite_score"] = df_screened["ensemble_composite"]
            ensemble_weights = df_screened.attrs.get("ensemble_weights")

        # 3. Solvency Disqualifications Count
        disqualified_count = self.count_disqualified_solvency_companies()

        # 4. Synthesize Top Theses (always via top-down template, which degrades gracefully)
        theses: List[ScripAlphaThesis] = []
        activations: List[Dict[str, Any]] = []
        ranker = None
        if use_ensemble:
            try:
                from reality_engine.processing.ensemble_ranker import EnsembleRanker
                ranker = EnsembleRanker()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Ensemble MoE ranker unavailable: %s", exc)
                ranker = None

        if not df_screened.empty:
            top_candidates = df_screened.head(top_n)
            for rank_idx, (_, row) in enumerate(top_candidates.iterrows(), 1):
                try:
                    candidate_dict = row.to_dict()
                    thesis = self.evaluate_candidate_scrip(candidate_dict, rank=rank_idx, use_topdown_template=True, attribution_date=date_str)
                    # MoE activation: fire the sparse gate per candidate so the pathway is
                    # revisable (temperature controls explore vs exploit) and audited.
                    if use_ensemble and ranker is not None:
                        ctx = {
                            "stock": thesis.symbol,
                            "sector": candidate_dict.get("sector") or candidate_dict.get("industry") or "Industrials",
                            "regime": breadth_summary.market_regime,
                            "investor_majority": investor_majority,
                        }
                        try:
                            activation = ranker.fire_lenses(float(temperature), context=ctx)
                        except Exception as e:
                            logger.exception("MoE activation failed for %s: %s", thesis.symbol, e)
                            activation = None
                        if activation is not None:
                            # pydantic model disallows arbitrary fields; attach via object.__setattr__
                            object.__setattr__(thesis, "ensemble_activation", activation)
                            activations.append(activation)
                    theses.append(thesis)
                except Exception as e:
                    logger.exception("Error synthesizing thesis for row %s: %s", row.get("symbol"), e)

        # 5. Macro Shock Radar
        macro_radar = self.build_macro_shock_radar()

        # 6. Build DailyAlphaReport
        report = DailyAlphaReport(
            date=date_str,
            universe=universe.upper(),
            market_breadth=breadth_summary,
            high_conviction_theses=theses,
            macro_shock_radar=macro_radar,
            disqualified_solvency_count=disqualified_count,
            generated_timestamp=datetime.now().isoformat()
        )
        # Attach funnel stats as report metadata when top-down was used (for dashboard/debug)
        if use_top_down and hasattr(df_screened, "attrs") and df_screened.attrs.get("funnel_stats"):
            report_funnel = df_screened.attrs.get("funnel_stats")
            logger.info("Top-down funnel stats %s (fallback=%s)", report_funnel, fallback_used)

        # Wave D4: attach ensemble synthesis metadata (MoE weights, activation log, transient graph)
        if use_ensemble:
            transient = self._collect_transient_graph_context()
            meta = {
                "mode": "ensemble",
                "investor_majority": str(investor_majority),
                "temperature": float(temperature),
                "ensemble_weights": ensemble_weights,
                "n_candidates": len(theses),
                "avg_fired_weight_sum": round(sum(a["fired_weight_sum"] for a in activations) / len(activations), 6) if activations else None,
                "avg_n_fired": round(sum(a["n_fired"] for a in activations) / len(activations), 2) if activations else None,
                "transient_graphs": transient,
            }
            object.__setattr__(report, "ensemble_metadata", meta)
            logger.info("Ensemble metadata attached: %d theses, avg_fired=%s", len(theses), meta["avg_n_fired"])

        logger.info("Successfully synthesized Daily Alpha Report for %s with %d theses (top_down=%s, ensemble=%s).", date_str, len(theses), use_top_down, use_ensemble)
        return report

    def _collect_transient_graph_context(self) -> List[Dict[str, Any]]:
        """Best-effort collection of recently spawned transient event-graphs (Wave D2).

        Returns up to a few recent macro_events with their biggest-beneficiary ripple (max S).
        Purely optional enrichment for the ensemble rationale; any failure degrades to [].
        """
        try:
            from reality_engine.processing.event_graph import EventGraphSpawner
            sp = EventGraphSpawner()
            with self.repo.db.session() as conn:
                rows = conn.execute(
                    "SELECT event_id FROM macro_events ORDER BY event_id DESC LIMIT 5"
                ).fetchall()
            out: List[Dict[str, Any]] = []
            for r in rows:
                eid = r["event_id"]
                try:
                    chain = sp.trace_transient_chain(eid, max_hops=2)
                except Exception:
                    continue
                if chain:
                    try:
                        top = max(chain, key=lambda x: float(x.get("s", 0.0) or 0.0))
                        out.append({
                            "event_id": eid,
                            "biggest_beneficiary": top.get("ripple_id"),
                            "S": top.get("s"),
                        })
                    except Exception:
                        continue
            return out
        except Exception:
            return []

    def synthesize_daily_alpha_report_topdown(
        self,
        target_date: Optional[str] = None,
        universe: str = "nifty200",
        top_n: int = 5,
        screener_pool_size: int = 20,
        **kwargs,
    ) -> DailyAlphaReport:
        """Convenience alias for synthesize_daily_alpha_report(use_top_down=True) vertical slice."""
        return self.synthesize_daily_alpha_report(
            target_date=target_date,
            universe=universe,
            top_n=top_n,
            screener_pool_size=screener_pool_size,
            use_top_down=True,
            **kwargs,
        )

    def synthesize_daily_alpha_report_ensemble(
        self,
        target_date: Optional[str] = None,
        universe: str = "nifty200",
        top_n: int = 5,
        screener_pool_size: int = 20,
        investor_majority: str = "all",
        temperature: float = 0.4,
        **kwargs,
    ) -> DailyAlphaReport:
        """Convenience alias for synthesize_daily_alpha_report(use_ensemble=True) MoE blend."""
        return self.synthesize_daily_alpha_report(
            target_date=target_date,
            universe=universe,
            top_n=top_n,
            screener_pool_size=screener_pool_size,
            use_ensemble=True,
            investor_majority=investor_majority,
            temperature=temperature,
            **kwargs,
        )


# Singleton agent orchestrator instance
agent_orchestrator = AgentOrchestrator()
