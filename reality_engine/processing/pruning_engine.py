"""4-Pillar Data Pruning & Lifecycle Framework - Exponential Decay & Graph Pruning."""

from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

# Pillar 2: Half-life constants per Architecture spec
HALF_LIVES: dict[str, float] = {
    "Analyst Commentary / YouTube": 3.0,   # months
    "Quarterly Concall / MPC Stance": 6.0,
    "Union Budget / Tax Reform": 12.0,
}

def lambda_for(category: str) -> float:
    hl = HALF_LIVES.get(category, 6.0)
    return math.log(2) / hl

def decayed_significance(S0: float, category: str, months_elapsed: float) -> float:
    """S(t) = S0 * e^{-lambda * delta_t}"""
    lam = lambda_for(category)
    return S0 * math.exp(-lam * months_elapsed)

@dataclass
class TieringPolicy:
    """Pillar 1: Data Tiering"""
    entity: str
    hot_months: int
    warm_months: int
    cold_threshold_months: int
    action_hot: str
    action_warm: str
    action_cold: str

TIERING: list[TieringPolicy] = [
    TieringPolicy("Video/Audio MP4", 0, 0, 0, "never DB", "temp buffer", "S3 Glacier, delete local temp immediately"),
    TieringPolicy("Document Chunks Embeddings", 12, 36, 36, "RAM pgvector ivfflat/HNSW", "drop embedding keep relational text", "Parquet >36m raw text export"),
    TieringPolicy("Ripple Effects", 12, 24, 24, "active unmaterialized paths", "validated backtest archive", "purge PN<0.05 or expired"),
    TieringPolicy("Financials & Moats", 9999, 9999, 9999, "all hot", "all warm", "never purge"),
]

def should_prune_ripple(prob: float, raw: float, decayed_S: float, prob_cutoff: float = 0.08, S_floor: float = 5.0, Pn_cutoff: float = 0.05) -> bool:
    """Pillar 2B: Graph pruning execution rules"""
    if prob < prob_cutoff:
        return True
    if abs(raw) * prob < 0.50:  # ghost node
        return True
    if decayed_S < S_floor:
        return True
    # also PN cutoff handled upstream via recursive CTE PN product
    return False

def tier_for_age(entity: str, age_months: int) -> Literal["hot","warm","cold","purge"]:
    pol = next((p for p in TIERING if p.entity == entity), TIERING[1])
    if age_months <= pol.hot_months:
        return "hot"
    if age_months <= pol.warm_months:
        return "warm"
    if age_months >= pol.cold_threshold_months and pol.cold_threshold_months < 9999:
        return "cold"
    return "warm"

# SQL helpers for repository.py integration
PRUNE_EMBEDDINGS_SQL = """
UPDATE document_chunks dc SET embedding = NULL
FROM raw_documents rd
WHERE dc.doc_id = rd.doc_id
  AND rd.published_date < CURRENT_DATE - INTERVAL '12 months'
  AND dc.embedding IS NOT NULL
  AND COALESCE(rd.source_type,'') NOT ILIKE '%Structural Milestone%';
"""

PRUNE_RIPPLES_SQL = """
DELETE FROM ripple_effects
WHERE parent_ripple_id IS NOT NULL
  AND (probability < 0.10 OR (ABS(raw_magnitude) * probability) < 0.50);
"""

ARCHIVE_MACRO_SQL = """
UPDATE macro_events SET event_category='Archived'
WHERE announcement_date < CURRENT_DATE - INTERVAL '24 months' AND event_category!='Archived';
"""

DECAYED_VIEW_SQL = """
SELECT ripple_id, significance_rank * EXP(-lambda * EXTRACT(MONTH FROM AGE(CURRENT_DATE, announcement_date))) AS decayed
FROM ripple_effects JOIN macro_events USING(event_id) JOIN pruning_decay_config USING(category);
"""
