"""Instantiate the 1,073-case master bank on the stratified pilot-60 universe.

    python tasks/pilot60/instantiate.py
    python tasks/pilot60/instantiate.py --rename-only   # rewrite questions in place

Rules (task brief, 2026-10-28):
  * single-company case -> 3 instantiations, one per bucket; prefer the parent
    company's own sector inside the bucket, otherwise a seeded random pick
    (seed 20261028); the original case is kept and run too;
  * multi-company / peer case -> one instance with a same-sector pilot peer set;
  * sector / industry / index / theme / mcap-bucket / market-wide / policy / macro
    case -> runs as it is on the whole-market T1 (row kind ``as_is``);
  * ``period`` / ``as_of`` shift only when the original date does not exist for
    the new company (company_state_daily): nearest earlier session, or the
    company's first session when the original as_of predates its listing.

Output: tasks/pilot60/INSTANCES.jsonl + INSTANTIATE_STATS.md.
"""
from __future__ import annotations

import csv
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from reality_engine.query.router import period_bounds  # noqa: E402

BANK = REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl"
OUT_DIR = REPO / "tasks" / "pilot60"
UNIVERSE = OUT_DIR / "UNIVERSE.csv"
T1 = REPO / ".tmp" / "pilot_all" / "market_state_pilot.db"
SEED = 20261028
BUCKETS = ("LARGE", "MID-SMALL", "MICRO")
BUCKET_CODE = {"LARGE": "L", "MID-SMALL": "MS", "MICRO": "MI"}
DATA_ROOT = Path(__import__("os").environ.get(
    "REALITY_DATA_ROOT", REPO / "reality_engine" / "data"))


def load_cases() -> list[dict]:
    return [json.loads(line) for line in BANK.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def load_universe() -> list[dict]:
    rows = list(csv.DictReader(UNIVERSE.open(encoding="utf-8")))
    for row in rows:
        row["docs"] = {k: int(row[k] or 0) for k in
                       ("annual_report", "concall", "deck", "results_notes", "announcement")}
    assert len(rows) == 60 and len({r["isin"] for r in rows}) == 60, \
        f"UNIVERSE.csv must hold 60 unique ISINs, got {len(rows)}"
    return rows


def parent_identity(cases: list[dict]) -> tuple[dict, dict, dict]:
    """symbol/bse_code -> isin, isin -> sector, isin -> name/codes, from the held master."""
    sym2isin, isin2sector, ident = {}, {}, {}
    con = sqlite3.connect(f"file:{DATA_ROOT / 'equity_intelligence.db'}?mode=ro", uri=True)
    try:
        for isin, sym, bse, sector, industry, name in con.execute(
                "SELECT isin, nse_symbol, bse_code, sector, industry, company_name "
                "FROM master_companies"):
            if sym:
                sym2isin[str(sym).upper()] = isin
            if bse:
                sym2isin[str(bse)] = isin
            isin2sector[isin] = sector or industry or ""
            ident[isin] = {"name": name or "", "symbol": sym or "",
                           "bse_code": str(bse or "")}
        for isin, sector in con.execute("SELECT isin, sector FROM company_industry"):
            if sector:
                isin2sector.setdefault(isin, sector)
    finally:
        con.close()
    return sym2isin, isin2sector, ident


def sessions(con: sqlite3.Connection) -> tuple[dict, dict]:
    """(isin -> [first, last] session, isin -> all sessions) from the T1 build."""
    first_last, all_days = {}, defaultdict(list)
    for isin, day in con.execute("SELECT isin, date FROM company_state_daily ORDER BY isin, date"):
        all_days[isin].append(day)
    for isin, days in all_days.items():
        first_last[isin] = (days[0], days[-1])
    return first_last, all_days


def _nearest(days: list[str], day: str) -> str | None:
    """Latest session <= day, else the first session (company listed later)."""
    import bisect
    idx = bisect.bisect_right(days, day)
    if idx:
        return days[idx - 1]
    return days[0] if days else None


def shift_case(case: dict, isin: str, days: dict) -> tuple[dict, dict]:
    """Shift as_of / period only when the original date has no session for the company."""
    out = dict(case)
    info = {"shifted": [], "forward": False}
    company_days = days.get(isin) or []
    if not company_days:
        info["shifted"].append("no sessions: company not in company_state_daily")
        return out, info
    as_of = str(case.get("as_of") or "")[:10]
    if as_of and not any(d <= as_of for d in company_days):
        out["as_of"] = company_days[0]
        info["shifted"].append(f"as_of {as_of}->{out['as_of']}")
        info["forward"] = True
    date_from, date_to, basis = period_bounds(case)
    if date_from and date_to and basis in ("named date", "named dates"):
        window = [d for d in company_days if date_from <= d <= date_to]
        if not window:
            moved = _nearest(company_days, date_to)
            if moved:
                out["period"] = moved
                info["shifted"].append(f"date {date_from}..{date_to}->{moved}")
    return out, info


def pick(rng: random.Random, rows: list[dict], bucket: str, sector: str | None, used: set) -> dict:
    same = [r for r in rows if r["bucket"] == bucket and sector and
            r["sector"].lower() == sector.lower() and r["isin"] not in used]
    pool = same or [r for r in rows if r["bucket"] == bucket and r["isin"] not in used] or rows
    return rng.choice(pool)


def peer_set(rng: random.Random, rows: list[dict], sectors: list[str], used: set) -> list[dict]:
    """A same-sector peer set spanning buckets; random mid-sized peers when no sector matches."""
    wanted = {s.lower() for s in sectors}
    same = [r for r in rows if r["sector"].lower() in wanted]
    picked, seen_buckets = [], set()
    for bucket in BUCKETS:
        candidates = [r for r in same if r["bucket"] == bucket and r["isin"] not in used]
        if candidates:
            row = rng.choice(candidates)
            picked.append(row)
            seen_buckets.add(bucket)
    if len(picked) < 3:
        for row in sorted((r for r in rows if r["bucket"] == "MID-SMALL"),
                          key=lambda r: -sum(1 for v in r["docs"].values() if v)):
            if len(picked) >= 3:
                break
            if row["isin"] not in used and row not in picked:
                picked.append(row)
    return picked[:3]


def _replace(question: str, old: str, new: str) -> str:
    """Replace one company token; a bare name is replaced where it stands alone."""
    if len(old or "") < 3 or not new or old.lower() == (new or "").lower():
        return question
    pattern = r"(?<![A-Za-z0-9])" + re.escape(old) + r"(?![A-Za-z0-9])"
    return re.sub(pattern, new, question, flags=re.I)


def _aliases(parent: dict, name: str, symbol: str) -> list[tuple[str, str]]:
    """(how the bank spells the parent, what to write instead) for one company.

    The text spells a company by its name, by the name without the legal suffix
    ("JSW Steel Limited" -> "JSW Steel"), by its symbol or by its BSE code.  The
    replacement is the instance's name, or its symbol when master has no name.
    """
    full = (parent.get("name") or "").strip()
    pairs = [(full, name)]
    base = re.sub(r"\s+(limited|ltd|private|pvt|corporation|corp)\.?$", "", full, flags=re.I)
    if base and base.lower() != full.lower():
        pairs.append((base, name))
    pairs += [(parent.get("symbol") or "", symbol), (parent.get("bse_code") or "", symbol)]
    return [(old, new) for old, new in pairs if len(old) >= 3 and new]


def rename_questions(rows: list[dict], ident: dict, sym2isin: dict | None = None) -> int:
    """Rewrite each instance question with the instance company's own name.

    The instance is the entity the answer is produced for, so a question that still
    reads "Trent ..." (the parent case's company) is misleading for a human reader
    even though the grader judges by slot.  A single-company instance is renamed to
    its one entity; a peer-set instance is renamed company by company to its peer
    set (the answer ranks that set, not the parent's).  Deterministic: the text only
    ever moves forward, and a second run reproduces the same text.
    """
    renamed = 0
    sym2isin = sym2isin or {}
    for row in rows:
        parents = [ident[item.get("isin")] for item in row.get("substituted_from") or []
                   if item.get("isin") in ident]
        children = []
        for entity in row.get("entities") or []:
            symbol = str(entity.get("symbol") or "")
            isin = str(entity.get("isin") or "")
            children.append(ident.get(isin) or ident.get(sym2isin.get(symbol.upper()) or "")
                            or {"name": "", "symbol": symbol, "bse_code": ""})
        children = [child for child in children if child.get("symbol") or child.get("name")]
        if row.get("kind") not in ("stock", "peer_set") or not parents or not children:
            continue
        question = str(row.get("question") or "")
        text = question
        for index, parent in enumerate(parents):
            child = children[min(index, len(children) - 1)]
            # A company with no master name is named by its symbol, which is what
            # the answer prints: better terse and correct than another company.
            alias = child.get("name") or child.get("symbol") or ""
            for old, new in _aliases(parent, alias, child.get("symbol") or alias):
                text = _replace(text, old, new)
        if text != question:
            row["question"] = text
            renamed += 1
    return renamed


def build_instances() -> tuple[list[dict], dict, list[dict]]:
    cases = load_cases()
    universe = load_universe()
    sym2isin, isin2sector, ident = parent_identity(cases)
    con = sqlite3.connect(f"file:{T1}?mode=ro", uri=True)
    _, days = sessions(con)
    con.close()
    parent_sector = lambda isin: isin2sector.get(isin) or ""
    rng = random.Random(SEED)
    rows, skipped = [], []
    for case in cases:
        mid = case["mid"]
        base = {k: case.get(k) for k in ("family", "entity_level", "answer_kind", "template",
                                         "source_bank", "question", "answer_kind", "regression")}
        entities = [e for e in (case.get("entities") or []) if isinstance(e, dict)]
        stocks = [e for e in entities if str(e.get("type") or "stock") == "stock"]
        resolved, unresolved = [], []
        for entity in stocks:
            isin = str(entity.get("isin") or "").strip().upper()
            if not isin:
                for key in ("symbol", "nse_symbol", "bse_code"):
                    value = str(entity.get(key) or "").strip().upper()
                    if value in sym2isin:
                        isin = sym2isin[value]
                        break
            if isin.startswith("INE"):
                resolved.append(isin)
            else:
                unresolved.append(isin or str(entity.get("symbol") or ""))
        level = str(case.get("entity_level") or "stock")
        if level != "stock" or not entities:
            rows.append({"mid": mid, "parent_mid": mid, "kind": "as_is", "bucket": None,
                         "sector": None, "entities": entities, "shift": {"shifted": []},
                         **base})
            continue
        if not resolved:
            skipped.append({"mid": mid, "reason": "no stock entity resolves to an equity ISIN",
                            "entities": unresolved})
            continue
        if len(entities) > 1:
            sectors = [parent_sector(i) for i in resolved]
            peers = peer_set(rng, universe, [s for s in sectors if s], set())
            if not peers:
                skipped.append({"mid": mid, "reason": "no pilot peer set"})
                continue
            new_entities = [{"isin": r["isin"], "symbol": r["symbol"]} for r in peers]
            shifted, shift = shift_case(case, peers[0]["isin"], days)
            rows.append({"mid": f"{mid}#P", "parent_mid": mid, "kind": "peer_set",
                         "bucket": None, "sector": peers[0]["sector"],
                         "entities": new_entities, "shift": shift,
                         "substituted_from": [{"isin": i, "sector": s}
                                              for i, s in zip(resolved, sectors)],
                         **base, "as_of": shifted.get("as_of"),
                         "period": shifted.get("period")})
            continue
        sector = parent_sector(resolved[0])
        for bucket in BUCKETS:
            chosen = pick(rng, universe, bucket, sector, set())
            shifted, shift = shift_case(case, chosen["isin"], days)
            rows.append({"mid": f"{mid}#{bucket[0]}", "parent_mid": mid, "kind": "stock",
                         "bucket": bucket, "sector": chosen["sector"],
                         "entities": [{"isin": chosen["isin"], "symbol": chosen["symbol"]}],
                         "shift": shift, "substituted_from": [{"isin": resolved[0],
                                                               "sector": sector}],
                         **base, "as_of": shifted.get("as_of"),
                         "period": shifted.get("period")})
    stats = {
        "cases": len(cases),
        "kinds": dict(Counter(r["kind"] for r in rows)),
        "buckets": dict(Counter(r["bucket"] for r in rows if r["bucket"])),
        "sectors": dict(Counter(r["sector"] for r in rows if r["kind"] == "stock")),
        "renamed": rename_questions(rows, ident),
        "shifted": sum(1 for r in rows if r["shift"].get("shifted")),
        "forward_as_of": sum(1 for r in rows if r["shift"].get("forward")),
        "skipped": skipped,
    }
    return rows, stats, skipped


def rename_only() -> int:
    """Rewrite the instance questions of the existing INSTANCES.jsonl in place.

    The question is rebuilt from the parent bank case (``build_instances`` copies it
    verbatim) and then renamed, so the pass is deterministic: running it twice gives
    the same text instead of compounding a replacement from the renamed text.
    """
    path = OUT_DIR / "INSTANCES.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    cases = {case["mid"]: case for case in load_cases()}
    for row in rows:
        parent = cases.get(row.get("parent_mid"))
        if parent is not None and parent.get("question"):
            row["question"] = parent["question"]
    sym2isin, _, ident = parent_identity(list(cases.values()))
    renamed = rename_questions(rows, ident, sym2isin)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"renamed {renamed} of {len(rows)} instance questions -> {path}")
    return 0


def main() -> int:
    if "--rename-only" in sys.argv:
        return rename_only()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, stats, skipped = build_instances()
    with (OUT_DIR / "INSTANCES.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    covered = {r["parent_mid"] for r in rows}
    lines = ["# Instantiation stats", "",
             f"- master-bank cases: {stats['cases']}",
             f"- cases covered (instantiated or as-is): {len(covered)} "
             f"({100 * len(covered) / stats['cases']:.1f}%)",
             f"- rows by kind: {stats['kinds']}",
             f"- stock instances by bucket: {stats['buckets']}",
             f"- rows with a shifted period/as_of: {stats['shifted']} "
             f"(forward as_of: {stats['forward_as_of']})",
             f"- rows whose question now names its own company: {stats['renamed']}",
             f"- skipped cases: {len(skipped)}", ""]
    if skipped:
        lines += ["| mid | reason |", "|---|---|"]
        lines += [f"| {s['mid']} | {s['reason']} |" for s in skipped]
    (OUT_DIR / "INSTANTIATE_STATS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
