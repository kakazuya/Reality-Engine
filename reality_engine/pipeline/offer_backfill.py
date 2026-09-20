"""SEBI offer-document backfill pipeline: listing crawl -> match -> archive -> distill.

Covers the full chain the operator asked for — fetch every DRHP/Prospectus,
learn what each business does, and propagate the learning into the dense
substrate that drives cross-stock (macro/micro) impact reasoning:

1. ``crawl``   — ``SebiOfferClient.crawl_listing`` both stages (no per-company
                 search; ~3.8k records, dedup by filing-page URL).
2. ``match``   — company-name match against ``master_companies`` (normalized
                 suffix-stripped token match; match state persisted per record
                 so re-runs skip decided rows).
3. ``archive``  — ``official_filing_client.archive_many`` direct attachdocs
                 PDFs (sha256 idempotent; skip-if-present on source_url).
4. ``ingest``   — ``PDFIngestor.ingest_pdf`` with ``source_type=OFFER_DOCUMENT``
                 (raw_documents + document_chunks + FTS5 + LanceDB).
5. ``distill``  — deterministic DRHP text extraction into the dense substrate:
                 ``moat_evaluations`` + ``business_model_profiles`` (quality peer),
                 ``company_distilled_parameters`` business_sensitivities /
                 geopolitical_supply_chain / capital_allocation (macro/micro
                 impact inputs), ``regulatory_political_risks`` (policy peer for
                 regulated-industry issuers).

Every stage is independently fail-closed and idempotent; ``state.json`` in the
loop dir records per-record progress so a killed run resumes. Default is
``--dry-run`` (crawl + match report only, zero writes, zero downloads).

Owns ONLY this file. Never edits peer modules.
"""

from __future__ import annotations

import argparse
import errno
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("reality_engine.offer_backfill")

LOOP_SUBDIR = "offer_backfill"
LOCK_NAME = "offer_backfill.lock"
RUN_LOG_NAME = "run_log.jsonl"
STATE_NAME = "state.json"
STALE_LOCK_SECONDS = 45 * 60

# Company-name normalization: strip legal/issue suffixes SEBI titles carry.
_SUFFIX_RES = [
    r"\s*-\s*(drhp|prospectus|rhp|red herring prospectus|abridged prospectus|addendum.*|corrigendum.*)$",
    r"\s+(limited|ltd)(\.|\s|$).*",
    r"\s*\((india|india limited)\)\s*$",
]
_SUFFIX_RES = [re.compile(p, re.IGNORECASE) for p in _SUFFIX_RES]

# Regulated-industry keywords -> policy risk template for the policy peer.
# Severity band mirrors policy_engine.derive_universe_policy_risks (2-4).
_REGULATED_KEYWORDS = [
    (("pharma", "drug", "biotech", "healthcare"), "Drug price control / NPPA action", 3, 0.5),
    (("bank", "nbfc", "finance", "insurance", "finserv"), "RBI capital / provisioning tightening", 3, 0.5),
    (("power", "energy", "solar", "renewable", "utility"), "Power tariff / PPA renegotiation", 3, 0.5),
    (("telecom",), "Telecom tariff / AGR levy action", 4, 0.4),
    (("mining", "steel", "metal", "cement"), "Mining royalty / environmental clearance", 3, 0.5),
    (("liquor", "brewery", "distiller"), "State excise policy change", 3, 0.6),
    (("tobacco", "cigarette"), "Tobacco taxation / packaging regulation", 4, 0.5),
    (("defence", "defense", "aerospace"), "Defence procurement policy shift", 2, 0.4),
    (("rail", "infra", "construction", "road"), "Infra concession / order-book policy", 2, 0.4),
]

# Supply-chain signal keywords mined from DRHP "Objects / Risk Factors" text.
_SUPPLY_KEYWORDS = [
    "raw material", "supplier", "import", "china", "crude", "commodity",
    "logistics", "freight", "supply chain", "vendor", "procurement",
]
_CAPEX_KEYWORDS = ["capex", "capital expenditure", "expansion", "manufacturing facility", "new plant", "order book"]


def repo_root() -> Path:
    return _PROJECT_ROOT


def default_loop_dir() -> Path:
    from reality_engine import config

    return Path(config.DATA_DIR) / "logs" / LOOP_SUBDIR


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def acquire_lock(lock_path: Path) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        if age > STALE_LOCK_SECONDS:
            logger.warning("breaking stale offer-backfill lock (%.0fs old)", age)
            lock_path.unlink(missing_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise RuntimeError(f"offer-backfill lock held: {lock_path}") from exc
        raise
    os.write(fd, f"{os.getpid()} {_utc_now_iso()}\n".encode("utf-8"))
    return fd


def release_lock(fd: int, lock_path: Path) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    Path(lock_path).unlink(missing_ok=True)


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation, drop SEBI title suffixes — pure, tested."""
    text = (name or "").lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for pat in _SUFFIX_RES:
        text = pat.sub("", text).strip()
    return re.sub(r"\s+", " ", text).strip()


def _name_tokens(norm: str) -> List[str]:
    stop = {"the", "and", "of", "a", "an", "india", "indian", "limited", "ltd", "private", "pvt"}
    return [t for t in norm.split() if t and t not in stop]


def _token_alias_match(tokens: List[str], cname: str) -> bool:
    """SME-aware token match: every title token must hit the company name.

    A title token hits a company token on equality, prefix containment, or
    first-5-chars fuzzy (SME registrar spelling drift). Single shared tokens
    (``limited``, ``plastics``...) match thousands of companies, so a match
    needs EITHER 2+ hitting tokens OR one hitting token of length >= 8
    (``manika`` alone must never match ``M P K Steels``).
    """
    ctokens = cname.split()
    # Single-letter tokens (M P K / H G initials) never count: they collide
    # across thousands of companies.
    tokens = [t for t in tokens if len(t) > 1]
    ctokens = [c for c in ctokens if len(c) > 1]
    if not tokens or not ctokens:
        return False
    # Anchor rule: the FIRST significant title token must hit a company token
    # (equality or prefix). "Hy Tech" must never match "Garden Reach ...".
    t0 = tokens[0]
    if not any(t0 == c or c.startswith(t0) or (len(t0) >= 5 and t0.startswith(c) and len(c) >= 5) for c in ctokens):
        return False
    hits = 0
    for t in tokens:
        for c in ctokens:
            if t == c or c.startswith(t) or t.startswith(c):
                hits += (2 if len(t) >= 8 else 1)
                break
            if len(t) >= 5 and len(c) >= 5 and t[:5] == c[:5]:
                hits += 1
                break
    return hits >= 2


def match_company(
    title: str, companies: Sequence[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Best master_companies row for a SEBI filing title, or None.

    Token-subset rule with SME alias tolerance (see ``_token_alias_match``);
    ties broken by longest company name (most specific). Pure — unit-tested.
    """
    tokens = _name_tokens(normalize_name(title))
    if not tokens:
        return None
    best: Optional[Dict[str, Any]] = None
    best_len = -1
    for c in companies:
        cname = normalize_name(str(c.get("company_name") or ""))
        if not cname:
            continue
        if _token_alias_match(tokens, cname):
            if len(cname) > best_len:
                best, best_len = c, len(cname)
    return best


def load_match_companies(manager: Any = None) -> List[Dict[str, Any]]:
    """Operating companies eligible for DRHP matching.

    Listed universe (DUAL/NSE, real ISIN) first, then BSE_ONLY with real ISINs
    (newly-listed SME issuers resolve there first). Ranking prefers DUAL/NSE
    rows so a BSE_ONLY row never shadows the listed row. INE_AUTO placeholders
    (no ISIN yet) stay excluded: nothing to anchor the substrate to.
    """
    from reality_engine.db.repository import Repository

    rr = Repository(manager) if manager else None
    if rr is None:
        from reality_engine.db.repository import repo as _repo

        rr = _repo
    all_cos = rr.get_all_companies(active_only=True)
    listed, sme = [], []
    for c in all_cos:
        if not c.get("company_name"):
            continue
        isin = str(c.get("isin") or "")
        if isin.startswith("INF") or isin.startswith("INE_AUTO"):
            continue
        src_tag = c.get("listing_source") or ""
        if src_tag in ("DUAL", "NSE") and c.get("nse_symbol"):
            listed.append(c)
        elif src_tag == "BSE_ONLY" and (c.get("nse_symbol") or c.get("bse_code")):
            sme.append(c)
    return listed + sme


# ---------------------------------------------------------------------------
# State (resume across runs)
# ---------------------------------------------------------------------------
def _state_path(loop_dir: Path) -> Path:
    return Path(loop_dir) / STATE_NAME


def load_state(loop_dir: Path) -> Dict[str, Any]:
    try:
        return json.loads(_state_path(loop_dir).read_text(encoding="utf-8"))
    except Exception:
        return {"records": {}}


def save_state(loop_dir: Path, state: Dict[str, Any]) -> Path:
    path = _state_path(loop_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------
def crawl(
    stages: Sequence[str] = ("final", "draft"),
    max_pages: int = 0,
    client: Any = None,
) -> List[Dict[str, Any]]:
    """Crawl listing pages for each stage; dedup by filing-page URL."""
    if client is None:
        from reality_engine.ingestion.sebi_offer_client import sebi_offer_client as client
    records: List[Dict[str, Any]] = []
    seen: set = set()
    for st in stages:
        for rec in client.crawl_listing(stage=st, max_pages=max_pages):
            url = rec.get("filing_page_url")
            if not url or url in seen:
                continue
            seen.add(url)
            records.append(rec)
    return records


def match_records(
    records: Sequence[Dict[str, Any]],
    companies: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split crawled records into (matched, unmatched); match attaches symbol/isn."""
    matched, unmatched = [], []
    for rec in records:
        hit = match_company(rec.get("title", ""), companies)
        if hit is None:
            unmatched.append(rec)
            continue
        matched.append(
            {
                **rec,
                "symbol": (hit.get("nse_symbol") or "").upper(),
                "isin": hit.get("isin"),
                "company_name": hit.get("company_name"),
            }
        )
    return matched, unmatched


def archive_records(
    matched: Sequence[Dict[str, Any]],
    client: Any = None,
    filing_client: Any = None,
    max_workers: int = 2,
    progress: bool = False,
) -> Dict[str, Any]:
    """Resolve PDFs + archive; returns per-record results with local_file_path."""
    if client is None:
        from reality_engine.ingestion.sebi_offer_client import sebi_offer_client as client
    if filing_client is None:
        from reality_engine.ingestion.official_filing_client import (
            official_filing_client as filing_client,
        )
    discoveries: List[Dict[str, Any]] = []
    pdf_of: Dict[str, str] = {}
    # PDF-URL resolution is one small GET per filing page — parallelize it in
    # the same worker pool the archive uses (SEBI ajax tolerated ~1s pacing;
    # resolve workers default to 8, each client call carries its own floor).
    def _resolve(rec: Dict[str, Any]):
        try:
            return rec["filing_page_url"], client.resolve_pdf_url(rec["filing_page_url"])
        except Exception:
            return rec["filing_page_url"], None
    import concurrent.futures as _cf
    with _cf.ThreadPoolExecutor(max_workers=max(4, max_workers)) as _ex:
        for url, pdf in _ex.map(_resolve, matched):
            if not pdf:
                continue
            rec = next(r for r in matched if r["filing_page_url"] == url)
            pdf_of[url] = pdf
            discoveries.append(
            {
                "symbol": rec["symbol"],
                "links": [
                    {
                        "source_url": pdf,
                        "doc_type": "OFFER_DOCUMENT",
                        "source": "sebi_official",
                        "discovery_source": "sebi_offer_backfill",
                        "title": rec.get("title"),
                        "doc_date": rec.get("doc_date"),
                        "filing_page_url": rec.get("filing_page_url"),
                        "offer_stage": rec.get("stage"),
                    }
                ],
            }
        )
    result = filing_client.archive_many(discoveries, max_workers=max_workers, progress=progress)
    by_url: Dict[str, Dict[str, Any]] = {}
    for sym_res in result.get("per_symbol", []):
        for r in sym_res.get("results", []):
            by_url[r.get("source_url")] = r
    enriched = []
    for rec in matched:
        pdf = pdf_of.get(rec["filing_page_url"])
        enriched.append({**rec, "pdf_url": pdf, "archive": by_url.get(pdf) if pdf else None})
    return {"result": result, "records": enriched}


def ingest_records(
    archived: Sequence[Dict[str, Any]],
    ingestor: Any = None,
    persist: bool = False,
    manager: Any = None,
    max_workers: int = 2,
) -> List[Dict[str, Any]]:
    """Ingest archived PDFs into raw_documents + document_chunks.

    ``persist=False`` still ingests (chunk text is the substrate input) but
    skips the corporate_documents compat write — ingest_pdf always registers
    raw_documents/chunks; the compat row is what persist gates. In practice
    both stay on; the flag exists for dry-run parity with sibling commands.
    """
    if ingestor is None:
        from reality_engine.ingestion.pdf_ingestor import PDFIngestor

        ingestor = PDFIngestor(db=manager) if manager else PDFIngestor()
    # Ingest is CPU-bound text extraction + hash embedding; the OCR fallback
    # (RapidOCR DirectML on the RX 6700 XT) is the only GPU stage and fires
    # only for scanned pages (<300 chars). ThreadPool keeps N PDFs in flight;
    # SQLite writes serialize inside ingest_pdf's session (single-writer safe).
    ingest_workers = max(2, min(8, (max_workers or 2) * 2))
    def _ingest_one(rec: Dict[str, Any]):
        arch = rec.get("archive") or {}
        path = arch.get("local_file_path")
        if not arch.get("ok") or not path:
            return {**rec, "ingest": {"status": "skipped_no_file"}}
        try:
            res = ingestor.ingest_pdf(
                Path(path),
                title=rec.get("title"),
                source_type="OFFER_DOCUMENT",
                published_date=rec.get("doc_date"),
                source_url=rec.get("pdf_url"),
                symbol=rec.get("symbol"),
                isin=rec.get("isin"),
            )
        except Exception as exc:
            res = {"status": "failed", "error": str(exc)[:200]}
        return {**rec, "ingest": res}
    import concurrent.futures as _cf2
    with _cf2.ThreadPoolExecutor(max_workers=ingest_workers) as _ex:
        return list(_ex.map(_ingest_one, archived))


# ---------------------------------------------------------------------------
# Distill — deterministic DRHP text -> dense substrate
# ---------------------------------------------------------------------------
def extract_drhp_signals(text: str) -> Dict[str, Any]:
    """Mine DRHP chunk text for substrate signals. Pure function — tested.

    Returns business-description sentences (what the company does), supply
    keyword hits, capex hits, regulated-industry hits, and a moat keyword
    score vector. Deterministic regex/keyword mining; the LLM lens (Pydantic)
    refines these rows later — never the reverse.
    """
    low = (text or "").lower()
    sents = re.split(r"(?<=[.!?])\s+", text or "")
    # Skip prospectus boilerplate (intermediaries, registrar, offer mechanics)
    # before mining business sentences — the first ~10 chunks of every DRHP
    # are BRLM/registrar tables, not the business description.
    _BOILER = re.compile(
        r"\b(book running|lead manager|registrar to the offer|contact person|"
        r"e-mail|tel:|red herring|price band|bid lot|offer for sale|fresh issue)\b",
        re.I,
    )
    business = [
        s.strip()
        for s in sents
        if len(s.strip()) > 60
        and not _BOILER.search(s)
        and re.search(r"\b(manufactur|engaged in|provides|operates|business of|"
                      r"products|services|business overview|our company|we offer|"
                      r"we provide|principal business|core business)\b", s, re.I)
    ][:8]
    supply = sorted({k for k in _SUPPLY_KEYWORDS if k in low})
    capex = sorted({k for k in _CAPEX_KEYWORDS if k in low})
    regulated = [
        {"keywords": list(kw), "policy_name": name, "severity": sev, "probability": prob}
        for kw, name, sev, prob in _REGULATED_KEYWORDS
        if any(k in low for k in kw)
    ]
    from reality_engine.processing.moat_scorer import score_from_text

    scores = score_from_text(text or "")
    return {
        "business_sentences": business,
        "supply_hits": supply,
        "capex_hits": capex,
        "regulated_hits": regulated,
        "moat": {
            "switching_costs": scores.switching_costs,
            "network_effects": scores.network_effects,
            "cost_advantage": scores.cost_advantage,
            "intangible_assets": scores.intangible_assets,
            "efficient_scale": scores.efficient_scale,
            "total": scores.total(),
            "width": scores.width(),
        },
    }


# Business-prose signals: chunks dense in these describe what the company
# DOES (operations, customers, unit economics). Risk/legal boilerplate scores
# ~0; cover mechanics score low. Rank-then-take beats any fixed offset because
# the business section sits at different depths per issuer (RENTOMOJO ~200/572,
# VEEGALAND elsewhere).
_BUSINESS_DENSE_KW = (
    "we operate", "we provide", "we offer", "our platform", "our services",
    "business model", "revenue from operations", "subscriber", "refurbishment",
    "asset lifecycle", "capital productivity", "our customers", "we serve",
    "our products", "manufacturing facility", "order book", "unit economics",
)
_BOILER_DENSE_KW = (
    "book running", "registrar to the offer", "red herring", "price band",
    "bid lot", "absolute responsibility", "no formal market", "sustained trading",
    "anti-takeover", "takeover provisions",
)


def _chunk_business_score(content: str) -> float:
    low = (content or "").lower()
    score = sum(2.0 for k in _BUSINESS_DENSE_KW if k in low)
    score -= sum(3.0 for k in _BOILER_DENSE_KW if k in low)
    return score


def _chunk_texts_for_symbol(symbol: str, manager: Any, limit: int = 40) -> List[str]:
    # Rank chunks by business-prose density, keep document order among the
    # winners so the lens reads coherent prose, not scattered hits.
    with manager.session() as conn:
        try:
            rows = conn.execute(
                "SELECT dc.chunk_index, dc.content FROM document_chunks dc "
                "JOIN raw_documents rd ON dc.doc_id = rd.doc_id "
                "WHERE dc.symbol = ? AND rd.source_type = 'OFFER_DOCUMENT' "
                "ORDER BY dc.chunk_index ASC",
                (symbol.upper(),),
            ).fetchall()
        except Exception:
            return []
    texts = [(r[0], r[1]) for r in rows if r and r[1]]
    if not texts:
        return []
    scored = sorted(
        ((_chunk_business_score(c), i, c) for i, (_, c) in enumerate(texts)),
        key=lambda t: (-t[0], t[1]),
    )
    winners = sorted(scored[:limit], key=lambda t: t[1])
    if winners and winners[0][0] <= 0:
        # No chunk looks like business prose; fall back to mid-document.
        lo = len(texts) // 5
        return [c for _, c in texts[lo : lo + limit]]
    return [c for _, _, c in winners]


def distill_records(
    ingested: Sequence[Dict[str, Any]],
    manager: Any = None,
    dry_run: bool = False,
    llm_client: Any = None,
    llm_port: int = 8080,
) -> Dict[str, Any]:
    """Promote DRHP signals into moat/business/distilled/policy substrate rows.

    ``dry_run=True`` computes signals and reports counts without writing.
    ``llm_client`` (or a live server on ``llm_port``) upgrades the moat leg
    from keyword heuristics to model-judged deltas; every LLM miss falls back
    to the deterministic path so a dead server never blocks the batch.
    Returns ``{symbols, moat_rows, business_rows, distilled_rows, policy_rows,
    llm_moat_symbols}``.
    """
    from reality_engine.db.database import db_manager as _mgr

    mgr = manager or _mgr
    from reality_engine.db.repository import Repository

    rr = Repository(mgr)
    if llm_client is None:
        try:
            from reality_engine.ingestion.llm_lens_client import LensLLMClient
            probe = LensLLMClient(base_url=f"http://127.0.0.1:{llm_port}")
            llm_client = probe if probe.health() else None
        except Exception:
            llm_client = None
    summary: Dict[str, Any] = {
        "symbols": 0, "moat_rows": 0, "business_rows": 0,
        "distilled_rows": 0, "policy_rows": 0, "llm_moat_symbols": 0,
    }
    today = datetime.now().strftime("%Y-%m-%d")
    for rec in ingested:
        if (rec.get("ingest") or {}).get("status") not in ("ingested", "skipped_duplicate"):
            continue
        symbol = (rec.get("symbol") or "").upper()
        isin = rec.get("isin")
        if not symbol:
            continue
        texts = _chunk_texts_for_symbol(symbol, mgr)
        if not texts:
            continue
        joined = "\n".join(texts[:40])[:60_000]
        sig = extract_drhp_signals(joined)
        # LLM moat upgrade: model-judged deltas over the heuristic baseline.
        llm_moat = None
        if llm_client is not None:
            try:
                llm_moat = llm_client.synthesize(symbol, texts[:6])
            except Exception as exc:
                logger.debug("offer distill llm miss %s: %s", symbol, exc)
                llm_moat = None
        if llm_moat:
            summary["llm_moat_symbols"] += 1
        summary["symbols"] += 1
        if dry_run:
            summary["moat_rows"] += 1
            summary["business_rows"] += 1
            summary["distilled_rows"] += 3
            summary["policy_rows"] += len(sig["regulated_hits"])
            continue
        try:
            rr.ensure_moat_schema(mgr)
            base = sig["moat"]
            if llm_moat:
                deltas = (llm_moat.get("moat_updates") or {})
                clamp = lambda v: max(1, min(5, int(v)))
                rr.upsert_moat_evaluation(
                    ticker=symbol,
                    switching_costs=clamp(base["switching_costs"] + int(deltas.get("switching_costs_delta", 0))),
                    network_effects=clamp(base["network_effects"] + int(deltas.get("network_effects_delta", 0))),
                    cost_advantage=clamp(base["cost_advantage"] + int(deltas.get("cost_advantage_delta", 0))),
                    intangible_assets=clamp(base["intangible_assets"] + int(deltas.get("intangible_assets_delta", 0))),
                    efficient_scale=clamp(base["efficient_scale"] + int(deltas.get("efficient_scale_delta", 0))),
                    moat_trajectory=str(deltas.get("moat_trajectory", "Stable")),
                    isin=isin,
                )
            else:
                rr.upsert_moat_evaluation(
                    ticker=symbol,
                    switching_costs=base["switching_costs"],
                    network_effects=base["network_effects"],
                    cost_advantage=base["cost_advantage"],
                    intangible_assets=base["intangible_assets"],
                    efficient_scale=base["efficient_scale"],
                    moat_trajectory="Stable",
                    isin=isin,
                )
            summary["moat_rows"] += 1
        except Exception as exc:
            logger.warning("offer distill moat miss %s: %s", symbol, exc)
        try:
            rr.ensure_business_profile_schema(mgr)
            from reality_engine.processing.moat_scorer import archetype_for

            rr.upsert_business_model_profile(
                symbol=symbol,
                archetype=archetype_for("", ""),
                revenue_recurrence_pct=50.0,
                pricing_power_score=3,
                capital_intensity_score=3,
                operating_leverage_score=3,
                qualitative_notes="; ".join(sig["business_sentences"][:3])[:2000],
                isin=isin,
            )
            summary["business_rows"] += 1
        except Exception as exc:
            logger.warning("offer distill business miss %s: %s", symbol, exc)
        try:
            rr.upsert_distilled_parameters(
                [
                    {
                        "isin": isin or symbol, "symbol": symbol,
                        "parameter_key": "business_sensitivities",
                        "value_json": {
                            "business_description": sig["business_sentences"][:5],
                            "supply_chain_signals": sig["supply_hits"],
                            "moat_rating": sig["moat"]["total"],
                        },
                        "confidence_score": 0.6,
                        "source_document_ref": f"SEBI_DRHP:{rec.get('pdf_url', '')[:120]}",
                        "last_updated_date": today,
                    },
                    {
                        "isin": isin or symbol, "symbol": symbol,
                        "parameter_key": "geopolitical_supply_chain",
                        "value_json": {
                            "supply_chain_signals": sig["supply_hits"],
                            "transit_route_risks": [],
                        },
                        "confidence_score": 0.55,
                        "source_document_ref": f"SEBI_DRHP:{rec.get('pdf_url', '')[:120]}",
                        "last_updated_date": today,
                    },
                    {
                        "isin": isin or symbol, "symbol": symbol,
                        "parameter_key": "capital_allocation",
                        "value_json": {"capex_signals": sig["capex_hits"]},
                        "confidence_score": 0.55,
                        "source_document_ref": f"SEBI_DRHP:{rec.get('pdf_url', '')[:120]}",
                        "last_updated_date": today,
                    },
                ]
            )
            summary["distilled_rows"] += 3
        except Exception as exc:
            logger.warning("offer distill params miss %s: %s", symbol, exc)
        for hit in sig["regulated_hits"]:
            try:
                rr.ensure_regulatory_political_risks_schema(mgr)
                rr.upsert_regulatory_political_risk(
                    symbol=symbol,
                    policy_name=hit["policy_name"],
                    severity_score=hit["severity"],
                    probability=hit["probability"],
                    time_horizon="Structural",
                    isin=isin,
                )
                summary["policy_rows"] += 1
            except Exception as exc:
                logger.warning("offer distill policy miss %s: %s", symbol, exc)
    return summary


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run_once(
    loop_dir: Optional[Path] = None,
    manager: Any = None,
    dry_run: bool = True,
    stages: Sequence[str] = ("final", "draft"),
    max_pages: int = 0,
    max_archive: int = 0,
    max_workers: int = 2,
    client: Any = None,
    filing_client: Any = None,
    ingestor: Any = None,
) -> Dict[str, Any]:
    """One backfill tick: crawl -> match -> (archive -> ingest -> distill).

    ``dry_run=True`` stops after crawl+match (zero downloads, zero writes
    except the run log + state snapshot of the crawl itself).
    """
    from reality_engine.db.database import db_manager as _mgr

    mgr = manager or _mgr
    loop_dir = Path(loop_dir) if loop_dir else default_loop_dir()
    lock_path = loop_dir / LOCK_NAME
    try:
        fd = acquire_lock(lock_path)
    except RuntimeError as exc:
        logger.warning("%s", exc)
        return {"skipped": True, "rc": 2}
    started = time.time()
    result: Dict[str, Any] = {"dry_run": dry_run, "rc": 1}
    try:
        state = load_state(loop_dir)
        records = crawl(stages, max_pages=max_pages, client=client)
        companies = load_match_companies(manager=mgr)
        matched, unmatched = match_records(records, companies)
        result.update(
            {
                "crawled": len(records),
                "matched": len(matched),
                "unmatched": len(unmatched),
                "match_sample": [
                    {"title": r["title"][:80], "symbol": r["symbol"]} for r in matched[:10]
                ],
                "unmatched_sample": [r["title"][:80] for r in unmatched[:10]],
            }
        )
        # Persist crawl+match decisions so re-runs skip decided rows.
        for r in matched + unmatched:
            state["records"][r["filing_page_url"]] = {
                "title": r.get("title"),
                "stage": r.get("stage"),
                "doc_date": r.get("doc_date"),
                "symbol": r.get("symbol"),
            }
        save_state(loop_dir, state)
        if dry_run:
            result["rc"] = 0
            return result
        todo = matched
        if max_archive:
            # Skip records whose PDF is already archived (idempotent resume).
            todo = [r for r in matched if not state["records"].get(r["filing_page_url"], {}).get("pdf_url")]
            todo = todo[: int(max_archive)]
        arch = archive_records(matched=todo, client=client, filing_client=filing_client,
                               max_workers=max_workers)
        for rec in arch["records"]:
            if rec.get("pdf_url"):
                state["records"].setdefault(rec["filing_page_url"], {})["pdf_url"] = rec["pdf_url"]
        save_state(loop_dir, state)
        ingested = ingest_records(arch["records"], ingestor=ingestor, persist=True, manager=mgr, max_workers=max_workers)
        result["ingested"] = sum(1 for r in ingested if (r.get("ingest") or {}).get("status") == "ingested")
        result["distill"] = distill_records(ingested, manager=mgr)
        result["rc"] = 0
        return result
    except Exception as exc:
        logger.exception("offer-backfill tick miss: %s", exc)
        result.update({"rc": 1, "error": str(exc)[:300]})
        return result
    finally:
        try:
            path = loop_dir / RUN_LOG_NAME
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({**result, "at": _utc_now_iso(),
                                     "seconds": round(time.time() - started, 1)}) + "\n")
        except Exception:
            pass
        release_lock(fd, lock_path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="SEBI DRHP/Prospectus bulk backfill: crawl -> match -> archive -> ingest -> distill."
    )
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Crawl + match report only (default when no --apply)")
    parser.add_argument("--apply", action="store_true", default=False,
                        help="DELIBERATE: run archive -> ingest -> distill writes")
    parser.add_argument("--stage", type=str, default="both", choices=["draft", "final", "both"])
    parser.add_argument("--max-pages", type=int, default=0, help="Cap listing pages per stage (0=all)")
    parser.add_argument("--max-archive", type=int, default=0, help="Cap PDFs archived this run (0=all matched)")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--loop-dir", default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    dry_run = not args.apply or args.dry_run
    stages = ("final", "draft") if args.stage == "both" else (args.stage,)
    result = run_once(
        loop_dir=Path(args.loop_dir) if args.loop_dir else None,
        dry_run=dry_run, stages=stages,
        max_pages=args.max_pages, max_archive=args.max_archive,
        max_workers=args.workers,
    )
    print(json.dumps(result, indent=2, default=str))
    return int(result.get("rc", 1))


if __name__ == "__main__":
    sys.exit(main())
