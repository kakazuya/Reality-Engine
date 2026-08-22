"""
Fundamental Processing Engine Module
Computes YoY/QoQ revenue & PAT acceleration, EBITDA margin expansion,
Forensic Solvency & Value Trap screening, and Fundamental Acceleration Factor Scores (S_Funda).
"""

import logging
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

from reality_engine.config import (
    MAX_PROMOTER_PLEDGE_PCT,
    MIN_INTEREST_COVERAGE,
    MAX_DEBT_TO_EQUITY,
)

logger = logging.getLogger("reality_engine.fundamental_engine")


class FundamentalEngine:
    """Calculates fundamental growth acceleration and solvency risk metrics."""

    @staticmethod
    def compute_fundamental_score(
        yoy_rev_growth: float,
        yoy_pat_growth: float,
        opm_delta_bps: float = 0.0,
        roce_pct: float = 0.0
    ) -> float:
        """
        Computes Factor 2: Fundamental Acceleration Score (0 - 100).
        Formula:
        S_Funda = min(100, (max(0, g_Rev) * 0.4) + (max(0, g_PAT) * 0.4) + (max(0, dOPM / 50) * 10) + (ROCE_bonus))
        """
        rev_component = max(0.0, float(yoy_rev_growth or 0.0)) * 0.40
        pat_component = max(0.0, float(yoy_pat_growth or 0.0)) * 0.40
        margin_component = max(0.0, float(opm_delta_bps or 0.0) / 50.0) * 10.0
        quality_bonus = 10.0 if float(roce_pct or 0.0) >= 18.0 else (5.0 if float(roce_pct or 0.0) >= 12.0 else 0.0)

        raw_score = rev_component + pat_component + margin_component + quality_bonus
        return float(np.clip(raw_score, 0.0, 100.0))

    @staticmethod
    def evaluate_forensic_solvency(
        promoter_pledge_pct: float,
        interest_coverage_ratio: float,
        debt_to_equity_ratio: float
    ) -> Dict[str, Any]:
        """
        Evaluates strict forensic solvency gates.
        Rejects over-leveraged companies or those with high promoter pledging.
        """
        # Missing or non-numeric forensic data is not evidence of solvency.
        def number(value: Any) -> Optional[float]:
            try:
                return None if value is None or pd.isna(value) else float(value)
            except (TypeError, ValueError):
                return None

        pledge = number(promoter_pledge_pct)
        coverage = number(interest_coverage_ratio)
        leverage = number(debt_to_equity_ratio)
        disqualifications: List[str] = []

        if pledge is None:
            disqualifications.append("Promoter pledge is unavailable")
        elif pledge < 0.0:
            disqualifications.append(f"Promoter pledge {pledge:.1f}% is negative and invalid")
        elif pledge > MAX_PROMOTER_PLEDGE_PCT:
            disqualifications.append(
                f"Promoter pledge {pledge:.1f}% exceeds maximum {MAX_PROMOTER_PLEDGE_PCT:.1f}% limit"
            )

        if coverage is None:
            disqualifications.append("Interest coverage is unavailable")
        elif coverage < MIN_INTEREST_COVERAGE:
            disqualifications.append(
                f"Interest coverage {coverage:.2f}x fails minimum {MIN_INTEREST_COVERAGE:.1f}x solvency barrier"
            )

        if leverage is None:
            disqualifications.append("Debt-to-Equity is unavailable")
        elif leverage < 0.0:
            disqualifications.append(
                f"Debt-to-Equity {leverage:.2f}x is negative (distressed balance sheet / negative net worth)"
            )
        elif leverage > MAX_DEBT_TO_EQUITY:
            disqualifications.append(
                f"Debt-to-Equity {leverage:.2f}x exceeds safe ceiling of {MAX_DEBT_TO_EQUITY:.1f}x"
            )

        is_approved = 1 if len(disqualifications) == 0 else 0

        return {
            "is_solvency_approved": is_approved,
            "disqualifications": disqualifications,
            "reasons_str": "; ".join(disqualifications) if disqualifications else "PASSED_ALL_SOLVENCY_GATES",
        }

    @staticmethod
    def calculate_opm_delta_bps(current_opm_pct: float, prior_opm_pct: float) -> float:
        """Return operating-margin expansion in basis points (1 percentage point = 100 bps)."""
        try:
            if pd.isna(current_opm_pct) or pd.isna(prior_opm_pct):
                return 0.0
            return round((float(current_opm_pct) - float(prior_opm_pct)) * 100.0, 2)
        except (TypeError, ValueError):
            return 0.0


# Singleton fundamental engine
fundamental_engine = FundamentalEngine()
