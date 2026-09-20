"""Tier-aware unified search over ``intelligence_fts`` (news-feed v1).

Tier map (prefix match, case-insensitive; unknown -> tier 1):
  tier 0 -- company-published: concall, transcript, presentation,
      announcement, financial_result, annual_report, earnings
  tier 1 -- official macro/policy: union_budget, state_budget,
      economic_survey, pib, rbi, mpc
  tier 2 -- rumor/social: telegram, youtube
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("reality_engine.intel_search")

_TIER0_PREFIXES = (
    "concall",
    "transcript",
    "presentation",
    "announcement",
    "financial_result",
    "annual_report",
    "earnings",
)
_TIER1_PREFIXES = (
    "union_budget",
    "state_budget",
    "economic_survey",
    "pib",
    "rbi",
    "mpc",
)
_TIER2_PREFIXES = (
    "telegram",
    "youtube",
)

TIER_BY_SOURCE: Dict[str, int] = (
    {p: 0 for p in _TIER0_PREFIXES}
    | {p: 1 for p in _TIER1_PREFIXES}
    | {p: 2 for p in _TIER2_PREFIXES}
)


def tier_of(source_type: Optional[str]) -> int:
    """Return the tier (0, 1, 2) for a source_type string.

    Prefix match on the lowercased source_type; unknown/empty -> tier 1.
    """
    s = (source_type or "").strip().lower()
    if not s:
        return 1
    if s in TIER_BY_SOURCE:
        return TIER_BY_SOURCE[s]
    for prefix, tier in TIER_BY_SOURCE.items():
        if s.startswith(prefix):
            return tier
    return 1


def search_intel(
    query: str,
    symbol: Optional[str] = None,
    since: Optional[str] = None,
    tiers: Sequence[int] = (0, 1, 2),
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """Tier-filtered search over intelligence_fts.

    Built on ``Repository.search_fts``; fail-closed (miss/error -> []).
    Score is the FTS rank-order reciprocal ``1 / (1 + rank)``.
    """
    if not query or not query.strip():
        return []
    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        return []
    if top_k <= 0:
        return []
    allowed = set(tiers or ())

    from reality_engine.db.repository import Repository

    repo = Repository()
    try:
        rows = repo.search_fts(query, symbol=symbol, limit=max(1, top_k * 3))
    except Exception as exc:
        logger.warning("search_intel fts miss for query=%r: %s", query, exc)
        return []

    since_s = str(since) if since else None
    out: List[Dict[str, Any]] = []
    for rank, row in enumerate(rows):
        source_type = row.get("source_type") or ""
        tier = tier_of(source_type)
        if tier not in allowed:
            continue
        doc_date = row.get("document_date") or ""
        if since_s and (not doc_date or str(doc_date) < since_s):
            continue
        out.append(
            {
                "chunk_id": row.get("chunk_id"),
                "symbol": row.get("symbol"),
                "source_type": source_type,
                "tier": tier,
                "document_date": doc_date,
                "text": row.get("document_text"),
                "score": 1.0 / (1.0 + rank),
            }
        )
    out.sort(key=lambda d: d["score"], reverse=True)
    return out[:top_k]
