"""
Macro ingestion orchestrator for the Fundamental Reality Engine.

Composes :class:`MacroPDFFetcher` (audit-trail download into raw_documents) with
:class:`PDFIngestor` (dense-substrate ingestion into document_chunks + FTS) to
implement the "treat macro-policy PDFs as a peer" workflow. All writes are
transactional via ``db_manager.session()``; ingest failures are logged and
continue so a single corrupt PDF never aborts the whole run.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from reality_engine.ingestion.macro_pdf_fetcher import MacroPDFFetcher
from reality_engine.ingestion.pdf_ingestor import PDFIngestor
from reality_engine.processing.distillation_engine import DistillationEngine

logger = logging.getLogger("reality_engine.macro_runner")


class MacroRunner:
    """Orchestrates macro PDF fetch + dense-substrate ingest for a source/year set."""

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        rate_limit_sec: float = 1.0,
        ingestor: Optional[PDFIngestor] = None,
        fetcher: Optional[MacroPDFFetcher] = None,
    ):
        self.fetcher = fetcher or MacroPDFFetcher(rate_limit_sec=rate_limit_sec, data_dir=data_dir)
        self.ingestor = ingestor or PDFIngestor()

    # -- helpers ----------------------------------------------------------------
    @staticmethod
    def _meta_from_detail(detail: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "source_type": detail.get("source_type"),
            "title": detail.get("title"),
            "fiscal_period": detail.get("fiscal_period"),
            "source_url": detail.get("source_url"),
            "published_date": detail.get("published_date"),
            "creator_or_ministry": detail.get("creator_or_ministry"),
        }

    def _ingest_detail(self, cat_summary: Dict[str, int], detail: Dict[str, Any]) -> None:
        p = detail.get("path")
        if not p:
            return
        try:
            res = self.ingestor.ingest_macro_file(Path(p), **self._meta_from_detail(detail))
            status = res.get("status")
            if status == "ingested":
                cat_summary["ingested"] += 1
            elif status == "skipped_duplicate":
                cat_summary["skipped"] += 1
            else:
                cat_summary["failed"] += 1
        except Exception as exc:
            logger.warning("Macro ingest failed for %s: %s", p, exc)
            cat_summary["failed"] += 1

    # -- public API -------------------------------------------------------------
    def run(
        self,
        source: str = "all",
        years: Tuple[str, ...] = ("2024-25", "2025-26"),
        ingest: bool = True,
    ) -> Dict[str, Any]:
        """Fetch (and optionally ingest) macro PDFs.

        Returns a summary dict with top-level fetched/ingested/skipped/failed counts
        and a per-category breakdown under ``categories``.
        """
        years = list(years)
        summary: Dict[str, Any] = {
            "source": source,
            "years": years,
            "ingest": ingest,
            "fetched": 0,
            "ingested": 0,
            "skipped": 0,
            "failed": 0,
            "categories": {},
        }

        # (group, callable) — fetch functions keyed by source group.
        fetch_map: List[Tuple[str, Any]] = [
            ("central", lambda: self.fetcher.fetch_central_budgets(years=years)),
            ("states", lambda: self.fetcher.fetch_state_budgets(years=years)),
            ("pib", lambda: self.fetcher.fetch_pib_circulars(limit=10)),
            ("rbi", lambda: self.fetcher.fetch_rbi_reports(years=years)),
        ]

        for grp, fn in fetch_map:
            if source != "all" and grp != source:
                continue
            try:
                res = fn()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Macro fetch failed for '%s': %s", grp, exc)
                summary["categories"][grp] = {
                    "fetched": 0, "ingested": 0, "skipped": 0, "failed": 0,
                    "error": str(exc),
                }
                continue

            cat = {"fetched": 0, "ingested": 0, "skipped": 0, "failed": 0}
            for d in res.get("details", []):
                if d.get("ok"):
                    cat["fetched"] += 1
                else:
                    cat["failed"] += 1
                if ingest:
                    self._ingest_detail(cat, d)

            summary["categories"][grp] = cat
            summary["fetched"] += cat["fetched"]
            summary["ingested"] += cat["ingested"]
            summary["skipped"] += cat["skipped"]
            summary["failed"] += cat["failed"]

        return summary

    # -- dense-substrate distillation (Wave A1) -------------------------------
    def distill(self, source_type_prefix: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        """Distill ingested macro PDFs (raw_documents) into the dense substrate.

        Delegates to :class:`DistillationEngine.distill_all_macro_documents`, which
        routes each raw PDF through a Pydantic MacroEventExtraction lens into
        macro_events + ripple_effects BEFORE any thesis synthesis.
        """
        engine = DistillationEngine(manager=self.fetcher and getattr(self.fetcher, "db", None) or None)
        return engine.distill_all_macro_documents(source_type_prefix=source_type_prefix, limit=limit)


# Convenience module-level entry points.
def run_macro(source: str = "all", years: Tuple[str, ...] = ("2024-25", "2025-26"), ingest: bool = True) -> Dict[str, Any]:
    """Module-level wrapper: run the macro fetch+ingest pipeline."""
    return MacroRunner().run(source=source, years=years, ingest=ingest)


def run_macro_distill(source_type_prefix: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    """Module-level wrapper: distill ingested macro PDFs into the dense substrate."""
    return MacroRunner().distill(source_type_prefix=source_type_prefix, limit=limit)


def run_macro_distill_all() -> Dict[str, Any]:
    """Module-level wrapper: distill EVERY macro raw_documents row (no filter, no limit).

    Used by the Wave 0 substrate-promotion batch runner. Mirrors
    ``DistillationEngine.distill_all_macro_documents()`` with default arguments.
    """
    return MacroRunner().distill(source_type_prefix=None, limit=None)


__all__ = ["MacroRunner", "run_macro", "run_macro_distill", "run_macro_distill_all"]
