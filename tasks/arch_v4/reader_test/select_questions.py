"""Pick the frozen 40-question reader-test sample.

Deterministic: the seed below fixes the shuffled order of eligible master-bank
parents.  Five parents are mandated by the job brief and are added first; the
rest are taken in seed order.  Every parent row gets a written exclusion
reason in ``eligibility_parents.jsonl``.

Run ``--freeze`` only after the candidate questions have been premise-checked
by hand; it writes ``questions.jsonl`` + ``questions.manifest.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCH = HERE.parent
REPO = HERE.parents[2]
BANK = REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl"
INSTANCES = REPO / "tasks" / "pilot60" / "INSTANCES.jsonl"
CHUNKS = Path(r"C:\RE\data\pilot\pilot60\chunks_v3_pilot.db")
SEED = 20261031
N = 40
MANDATED = ["MB0337", "MB0345", "MB0355", "MB0415", "MB0540"]

DOC_EVIDENCE = re.compile(
    r"concall|transcript|deck|presentation|slide|annual.?report|\bar_|results_notes|"
    r"bse_announcements|corporate_documents|raw_documents|document|letterhead|note",
    re.I,
)
DOC_QUESTION = re.compile(
    r"\b(said|say|says|saying|disclos\w*|comment\w*|guidance|guided|stated|states|"
    r"according to|management|outlook|target\w*|expect\w*|explain\w*|told|announc\w*)\b",
    re.I,
)
# A question whose answer is a statement or a printed figure in the company's own
# documents, rather than an analytical judgement over several stores.
DISCLOSURE_ASK = re.compile(
    r"(what did|what does|what do|what is|what was|what were|what month|what quarter|what kind|"
    r"which approval|which call|which companies|how many manufacturing|"
    r"how many shares|how much did|how much .{0,40}(pay|capacity|renewable)|"
    r"who changed|from which|when did|did .{0,60}(carry|match|meet|disclose|file|commission)|"
    r"was there a company disclosure|what (filings?|exchange)|"
    r"is .{0,60}(already in the order book|funded by|within the stated|ready to ramp))",
    re.I,
)
ANALYSIS_ASK = re.compile(
    r"(promoter holding|pledge %|shareholding|free float|equity shares|\+ close|"
    r"market react|market's reaction|explained the market|share of the stock move|"
    r"event window|first session|what did it do|gap after|breakaway|exhaustion|volume say|"
    r"load factor|rate cut|history say|utilisation par|ebitda kitna|reinvest|"
    r"returns has the last expansion|revenue cover|years of revenue|platforms dominate|"
    r"what did the market do|which call first|margin guidance has|actually reported|"
    r"what is the gap|compare with its annual revenue|implies for|roic|cost of capital|"
    r"valuation|multiple|payback|unit economics|capital allocation|earnings quality|"
    r"dividend|customer concentration|balance sheet|cash flow cover|cycle|moat|thesis|"
    r"second.order|\bnim\b|segment revenue|what should i watch|which line item|"
    r"sessions before|day 0|dissemination timestamp|management.change filing|"
    r"futures|open interest|rollover|revenue per square|square foot|inventory turns|"
    r"runway|leverage ratio|working.capital|months of work|store base|volume trend|"
    r"detergent share|order book cover|cover in years|unbilled revenue)",
    re.I,
)


NAME_STOP = {"limited", "ltd", "industries", "industry", "company", "corp", "corporation",
             "india", "indian", "the", "and", "of"}


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def pilot_isins() -> set[str]:
    uri = "file:///" + str(CHUNKS).replace("\\", "/") + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    try:
        return {r[0] for r in con.execute("select distinct isin from chunk where isin is not null")}
    finally:
        con.close()


def entity_of(row: dict) -> dict | None:
    ents = row.get("entities") or []
    return ents[0] if len(ents) == 1 else None


def binding_entity(row: dict, pilot: set[str]) -> dict | None:
    """The company the reader query is pinned to.  Mandated multi-company rows bind to the
    first entity that has pilot chunks (MB0415 -> SAIL)."""
    ents = row.get("entities") or []
    for ent in ents:
        if ent.get("isin") in pilot:
            return ent
    return ents[0] if ents else None


def names_entity(question: str, ent: dict) -> bool:
    q = question.lower()
    sym = (ent.get("symbol") or "").strip().lower()
    if len(sym) >= 3 and sym in q:
        return True
    name = (ent.get("name") or "").lower()
    toks = [t for t in re.findall(r"[a-z][a-z.&]+", name) if len(t) >= 4 and t not in NAME_STOP]
    return any(t in q for t in toks)


def parent_status(row: dict, pilot: set[str]) -> tuple[bool, str]:
    q = (row.get("question") or "").strip()
    ent = entity_of(row)
    if row.get("entity_level") != "stock":
        return False, f"entity_level={row.get('entity_level')!r}, not a single-stock question"
    if ent is None:
        return False, "not exactly one entity"
    isin = ent.get("isin")
    if not isin:
        return False, "entity has no ISIN"
    if isin not in pilot:
        return False, "company has no chunks in chunks_v3_pilot.db"
    if not q:
        return False, "blank question"
    if not names_entity(q, ent):
        return False, "question does not name its company"
    ev = str((row.get("rubric") or {}).get("required_evidence") or "")
    gt = str((row.get("rubric") or {}).get("ground_truth") or "")
    ak = row.get("answer_kind") or ""
    quoted_gt = "\u201c" in gt or '"' in gt
    analytical = bool(ANALYSIS_ASK.search(q)) and row.get("mid") not in MANDATED
    if analytical:
        return False, "analytical/structured ask, not a document statement"
    if ak == "text+quote" or quoted_gt:
        return True, "eligible: quote-backed document ask"
    if not (DOC_EVIDENCE.search(ev) or DOC_QUESTION.search(q)):
        return False, "answer is not sought in the company's documents"
    if not DISCLOSURE_ASK.search(q):
        return False, "not a what-was-said/disclosed ask"
    return True, "eligible: document-disclosure ask"


def instance_for(parent: dict) -> dict | None:
    """Prefer an instance bound to the parent's own company (premise holds by construction)."""
    isin = parent["entities"][0]["isin"]
    kids = [r for r in INST if r.get("parent_mid") == parent["mid"]]
    in_pilot = []
    for r in kids:
        ents = r.get("entities") or []
        if len(ents) == 1 and ents[0].get("isin") == isin:
            in_pilot.append(r)
    if not in_pilot:
        return None
    # An instance whose text is the parent question is the parent itself.
    exact = [r for r in in_pilot if (r.get("question") or "").strip() == (parent.get("question") or "").strip()]
    return (exact or in_pilot)[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    args = ap.parse_args()

    mb = load_jsonl(BANK)
    global INST
    INST = load_jsonl(INSTANCES)
    pilot = pilot_isins()
    print(f"parents={len(mb)} instances={len(INST)} pilot_isins={len(pilot)}")

    ledger = []
    eligible = []
    for m in mb:
        ok, why = parent_status(m, pilot)
        ledger.append({"mid": m.get("mid"), "eligible": ok, "reason": why,
                       "question": m.get("question"), "entity": (entity_of(m) or {}).get("symbol"),
                       "answer_kind": m.get("answer_kind"), "template": m.get("template")})
        if ok:
            eligible.append(m)

    rng = random.Random(SEED)
    eligible_sorted = sorted(eligible, key=lambda r: r["mid"])
    rng.shuffle(eligible_sorted)
    order = [m["mid"] for m in eligible_sorted]
    by_mid = {m["mid"]: m for m in mb}
    print(f"eligible={len(eligible)} mandated_present={[x for x in MANDATED if x in by_mid]}")

    chosen = []
    for mid in MANDATED:
        chosen.append(by_mid[mid])
    for m in eligible_sorted:
        if len(chosen) >= N:
            break
        if m["mid"] in MANDATED:
            continue
        chosen.append(m)

    questions = []
    for rank, m in enumerate(chosen):
        kid = instance_for(m)
        ent = binding_entity(m, pilot)
        scope_note = ""
        if m["mid"] == "MB0415":
            scope_note = ("market-wide list question naming SAIL, HINDALCO and SRF; only SAIL and "
                          "HINDALCO have pilot chunks, so the reader is pinned to SAIL and the "
                          "market-wide premise cannot be answered from pilot documents")
        ev = str((m.get("rubric") or {}).get("required_evidence") or "")
        types = []
        if re.search(r"concall|transcript", ev, re.I):
            types.append("concall")
        if re.search(r"deck|presentation|slide", ev, re.I):
            types.append("deck")
        if re.search(r"annual.?report|\bar_", ev, re.I):
            types.append("annual_report")
        if re.search(r"results_notes|results note", ev, re.I):
            types.append("results_notes")
        if re.search(r"bse_announcements|announcement|filing", ev, re.I):
            types.append("announcement")
        if not types:
            types = ["concall", "deck", "annual_report", "results_notes", "announcement"]
        questions.append({
            "qid": f"Q{rank + 1:02d}",
            "mid": m["mid"],
            "instance_mid": (kid or {}).get("mid") or m["mid"],
            "parent_mid": m.get("mid"),
            "mandated": m["mid"] in MANDATED,
            "seed_rank": order.index(m["mid"]) if m["mid"] in order else None,
            "question": m.get("question"),
            "symbol": ent.get("symbol"),
            "name": ent.get("name"),
            "isin": ent.get("isin"),
            "as_of_question": m.get("as_of"),
            "as_of": m.get("as_of") or "2026-10-31",
            "as_of_source": "question" if m.get("as_of") else "run date (question had blank as_of)",
            "period": m.get("period"),
            "template": m.get("template"),
            "answer_kind": m.get("answer_kind"),
            "doc_types": types,
            "required_evidence": ev,
            "rubric_steps": (m.get("rubric") or {}).get("required_steps"),
            "rubric_forbidden": (m.get("rubric") or {}).get("forbidden"),
            "ground_truth": (m.get("rubric") or {}).get("ground_truth"),
            "scope_note": scope_note,
        })

    HERE.mkdir(parents=True, exist_ok=True)
    with open(HERE / "eligibility_parents.jsonl", "w", encoding="utf-8") as f:
        for r in ledger:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(HERE / "candidates.jsonl", "w", encoding="utf-8") as f:
        for r in questions:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"candidates={len(questions)} seed={SEED} -> {HERE / 'candidates.jsonl'}")

    if args.freeze:
        # Premise-check overrides are explicit and written down.
        overrides = HERE / "premise_overrides.json"
        excluded = {}
        if overrides.exists():
            excluded = json.loads(overrides.read_text(encoding="utf-8"))
        final = [r for r in questions if r["mid"] not in excluded]
        if len(final) < N:
            raise SystemExit(f"only {len(final)} questions survive premise overrides; need {N}")
        final = final[:N]
        qfile = HERE / "questions.jsonl"
        qfile.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in final), encoding="utf-8")
        digest = hashlib.sha256(qfile.read_bytes()).hexdigest()
        manifest = {
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "seed": SEED,
            "n": len(final),
            "sha256_questions_jsonl": digest,
            "mandated": MANDATED,
            "parents_total": len(mb),
            "instances_total": len(INST),
            "eligible_parents": len(eligible),
            "pilot_isins_in_chunks": len(pilot),
            "excluded_before_freeze": excluded,
            "bank_sha256": hashlib.sha256(BANK.read_bytes()).hexdigest(),
            "instances_sha256": hashlib.sha256(INSTANCES.read_bytes()).hexdigest(),
            "retrieval_db": str(CHUNKS),
            "retrieval_db_bytes": CHUNKS.stat().st_size,
        }
        (HERE / "questions.manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        print(f"FROZEN {len(final)} questions sha256={digest}")
        print(f"-> {qfile}")


if __name__ == "__main__":
    main()
