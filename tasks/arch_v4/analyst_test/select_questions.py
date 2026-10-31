"""Pick and freeze the 40-row analyst-agent sample (seed 20261040).

Rules, applied in this order, one written reason per instance:

1.  ILL_POSED in the read grade            -> exclude
2.  premise_audit verdict == "false"        -> exclude
3.  no entity                               -> exclude (the five tools bind to a company)
4.  more than one entity                    -> exclude (text names companies other than the row entity)
5.  entity ISIN not in the 60-name pilot    -> exclude
6.  question names a company other than the row entity -> exclude
7.  question does not name the row entity   -> exclude

Survivors are stratified by primary family (largest-remainder quotas, floor 1, n=40),
at most one row per parent, and at least 10 judgement/study rows (answer_kind
"explanation" or source_bank "ripple200").  ``--freeze`` writes questions.jsonl and
the manifest; ``--check`` refuses a changed list.  No row may be swapped after freeze.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
INSTANCES = REPO / "tasks" / "pilot60" / "INSTANCES.jsonl"
BANK = REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl"
AUDIT = REPO / "tasks" / "pilot60" / "PREMISE_AUDIT_2026-10-31.jsonl"
READ = REPO / "tasks" / "arch_v4" / "TRUTH_PANEL_READ_2026-10-31.jsonl"
PILOT_DB = Path(r"C:\RE\data\pilot\v4\fact_v4_pilot.db")
QUESTIONS = HERE / "questions.jsonl"
MANIFEST = HERE / "manifest.json"
EXCLUSIONS = HERE / "exclusions.jsonl"

SEED = 20261040
N = 40
MIN_JUDGEMENT = 10

NAME_STOP = {"limited", "ltd", "the", "and", "of", "india", "indian"}
GENERIC = {"power", "finance", "bank", "steel", "cement", "auto", "industries",
           "energy", "capital", "services", "systems", "technology"}


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


def pilot_universe() -> dict[str, str]:
    con = sqlite3.connect("file:///" + str(PILOT_DB).replace("\\", "/") + "?mode=ro&immutable=1",
                          uri=True)
    try:
        return {r[0]: r[1] for r in con.execute("select isin, symbol from pilot_universe")}
    finally:
        con.close()


def build_aliases(audit: dict[str, dict], pilot: dict[str, str],
                  bank: dict[str, dict]) -> list[tuple[str, str, str, list[str]]]:
    """(isin, symbol, display name, lower-case strings that name the company).

    The bank's own symbols are included with an empty ISIN so a row that kept the
    parent's company name (``CENTURYTEX (now VIKASWSP)``) is caught as naming a
    different company even when that company is outside the pilot.
    """
    aliases: dict[str, tuple[str, str, str, set[str]]] = {}
    for row in audit.values():
        for ent in row.get("entities") or []:
            isin = ent.get("isin")
            if not isin:
                continue
            sym = (ent.get("symbol") or ent.get("name") or "").strip()
            name = (ent.get("name") or sym).strip()
            strings = aliases.setdefault(isin, (isin, sym, name, set()))[3]
            strings.add(sym.lower())
            clean = re.sub(r"\b(limited|ltd|the|and|of|india|indian)\b", " ", name.lower())
            toks = [t for t in re.findall(r"[a-z][a-z.&]+", clean) if len(t) >= 3]
            if len(toks) >= 2:
                strings.add(" ".join(toks[:2]))
                strings.add(" ".join(toks))
            elif toks:
                strings.add(toks[0])
    for isin, sym in pilot.items():
        if not sym:
            continue
        strings = aliases.setdefault(isin, (isin, sym, sym, set()))[3]
        strings.add(sym.lower())
    for row in bank.values():
        for ent in row.get("entities") or []:
            sym = (ent.get("symbol") or "").strip()
            if len(sym) < 3:
                continue
            isin = ent.get("isin") or ""
            strings = aliases.setdefault("bank:" + sym, (isin, sym, sym, set()))[3]
            strings.add(sym.lower())
    return [(i, s, n, sorted(x for x in ss if x)) for i, (i, s, n, ss) in aliases.items()]


def named_companies(question: str, aliases) -> list[tuple[str, str, str, str]]:
    """Every known company named in the question, by symbol or by name string."""
    low = " " + re.sub(r"[^a-z0-9&. ]+", " ", (question or "").lower()) + " "
    hits = []
    for isin, sym, name, strings in aliases:
        for s in strings:
            if not s or s in GENERIC:
                continue
            if " " in s:
                if " " + s + " " in low:
                    hits.append((isin, sym, name, s))
                    break
            elif re.search(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9])", low):
                hits.append((isin, sym, name, s))
                break
    return hits


def classify(row: dict) -> tuple[bool, str]:
    """A judgement or study row: an explanation ask, or an R10 event-study row."""
    if row.get("answer_kind") == "explanation":
        return True, "explanation"
    if row.get("source_bank") == "ripple200":
        return True, "study"
    return False, "lookup"


def eligibility(row: dict, audit: dict[str, dict], read: dict[str, dict],
                pilot: dict[str, str], aliases, bank: dict[str, dict]) -> tuple[bool, str, str]:
    """(eligible, rule, detail) — the first rule that fails, in the documented order."""
    mid = row["mid"]
    if mid in read and read[mid].get("verdict") == "ILL_POSED":
        return False, "read_ill_posed", f"read grade: {read[mid].get('reason_code')}"
    if audit.get(mid, {}).get("verdict") == "false":
        return False, "premise_false", f"premise audit: {audit[mid].get('reason')}"
    ents = row.get("entities") or []
    if not ents:
        return False, "no_entity", "no entity; the five tools bind to a company"
    if len(ents) != 1:
        return False, "multi_entity", f"{len(ents)} entities; text names a company other than the row entity"
    isin = ents[0].get("isin")
    if not isin:
        return False, "no_isin", "entity has no ISIN"
    if isin not in pilot:
        return False, "not_in_pilot", "entity ISIN is not one of the 60 pilot names"
    symbol = (ents[0].get("symbol") or pilot.get(isin) or "").strip().lower()
    # A renamed parent ("SUVENPHAR (now COHANCE)") is safe only when the instance kept
    # the same successor; retargeting it to an unrelated pilot name leaves the old
    # company in the text.
    parent_q = (bank.get(row.get("parent_mid"), {}) or {}).get("question") or ""
    pm = re.search(r"\(now\s+([A-Za-z0-9&.]+)\)", parent_q)
    if pm:
        target = pm.group(1).strip().lower()
        im = re.search(r"\(now\s+([A-Za-z0-9&.]+)\)", row.get("question") or "")
        if im and im.group(1).strip().lower() != target:
            return False, "renamed_parent_mismatch", (
                f"parent renames to {target}, instance says now {im.group(1)}")
        if symbol and symbol != target and not im:
            return False, "renamed_parent_mismatch", (
                f"parent renames to {target}, row entity is {symbol}")
    hits = named_companies(row.get("question") or "", aliases)
    uniq: dict[str, tuple[str, str, str, str]] = {}
    for hit in hits:
        uniq.setdefault((hit[1] or hit[2]).lower(), hit)
    hits = list(uniq.values())

    def own(h: tuple[str, str, str, str]) -> bool:
        return h[0] == isin or (bool(symbol) and h[1].lower() == symbol)

    other = [h for h in hits if not own(h)]
    if other:
        return False, "names_other_company", "question names " + ", ".join(
            sorted({h[1] or h[2] for h in other}))
    own_hits = [h for h in hits if own(h)]
    if not own_hits:
        return False, "does_not_name_own", "question does not name the row entity"
    return True, "eligible", ""


def quotas(counts: dict[int, int], n: int) -> dict[int, int]:
    """Largest-remainder allocation with a floor of one per represented family."""
    total = sum(counts.values())
    fams = sorted(counts)
    raw = {f: counts[f] / total * n for f in fams}
    q = {f: max(1, int(raw[f])) for f in fams}
    while sum(q.values()) > n:  # floor-of-one can overshoot only on tiny pools
        f = max(q, key=lambda x: (q[x] - raw[x], x))
        if q[f] <= 1:
            break
        q[f] -= 1
    order = sorted(fams, key=lambda f: (-(raw[f] - int(raw[f])), f))
    i = 0
    while sum(q.values()) < n:
        f = order[i % len(order)]
        if q[f] < counts[f]:
            q[f] += 1
        i += 1
        if i > 10_000:
            raise RuntimeError("quota allocation did not converge")
    return q


def take_family(rows: list[dict], k: int, rng: random.Random, used_parents: set[str],
                used_isins: Counter) -> list[dict]:
    out = []
    for row in rows:
        if len(out) >= k:
            break
        isin = (row.get("entities") or [{}])[0].get("isin")
        if row["parent_mid"] in used_parents or used_isins[isin] >= 2:
            continue
        used_parents.add(row["parent_mid"])
        used_isins[isin] += 1
        out.append(row)
    return out


def sample(eligible: list[dict], seed: int = SEED, n: int = N) -> tuple[list[dict], dict]:
    """Deterministic stratified sample: one row per parent, at most two per company."""
    by_family: dict[int, list[dict]] = defaultdict(list)
    for row in eligible:
        fam = int((row.get("family") or [0])[0])
        by_family[fam].append(row)
    counts = {f: len(v) for f, v in by_family.items()}
    quota = quotas(counts, n)
    rng = random.Random(seed)
    picked: list[dict] = []
    used_parents: set[str] = set()
    used_isins: Counter = Counter()
    for fam in sorted(by_family):
        rows = sorted(by_family[fam], key=lambda r: r["mid"])
        rng.shuffle(rows)
        take = take_family(rows, quota[fam], rng, used_parents, used_isins)
        picked.extend(take)
        if len(take) < quota[fam]:
            quota[fam] = len(take)

    # Judgement floor: swap a selected lookup row for an unused judgement row.  Prefer a
    # swap inside the same family so the family quotas do not move.
    def is_judgement(r: dict) -> bool:
        return classify(r)[0]

    def unused_judgement(fam: int | None = None) -> dict | None:
        pool = [r for r in eligible
                if is_judgement(r) and r["parent_mid"] not in used_parents
                and used_isins[(r.get("entities") or [{}])[0].get("isin")] < 2
                and (fam is None or int((r.get("family") or [0])[0]) == fam)]
        pool.sort(key=lambda r: r["mid"])
        rng.shuffle(pool)
        return pool[0] if pool else None

    guard = 0
    while sum(1 for r in picked if is_judgement(r)) < MIN_JUDGEMENT and guard < 200:
        guard += 1
        swap_out = next((r for r in reversed(picked) if not is_judgement(r)), None)
        if swap_out is None:
            break
        fam = int((swap_out.get("family") or [0])[0])
        repl = unused_judgement(fam) or unused_judgement()
        if repl is None:
            break
        picked.remove(swap_out)
        used_parents.discard(swap_out["parent_mid"])
        used_isins[(swap_out.get("entities") or [{}])[0].get("isin")] -= 1
        picked.append(repl)
        used_parents.add(repl["parent_mid"])
        used_isins[(repl.get("entities") or [{}])[0].get("isin")] += 1

    picked.sort(key=lambda r: r["mid"])
    meta = {
        "family_quotas": {str(k): v for k, v in sorted(quota.items())},
        "family_eligible": {str(k): counts[k] for k in sorted(counts)},
        "judgement_rows": sum(1 for r in picked if is_judgement(r)),
        "parent_unique": len({r["parent_mid"] for r in picked}) == len(picked),
        "company_max": max(used_isins.values()) if used_isins else 0,
    }
    return picked, meta


def build_questions(picked: list[dict], bank: dict[str, dict], pilot: dict[str, str]) -> list[dict]:
    out = []
    for i, row in enumerate(picked, 1):
        ent = row["entities"][0]
        isin = ent["isin"]
        parent = bank.get(row["parent_mid"], {})
        rubric = parent.get("rubric") or {}
        judge, cat = classify(row)
        out.append({
            "qid": f"Q{i:02d}",
            "mid": row["mid"],
            "parent_mid": row["parent_mid"],
            "entity_isin": isin,
            "symbol": pilot.get(isin) or ent.get("symbol") or "",
            "name": next((a[2] for a in ALIASES if a[0] == isin), ent.get("symbol") or ""),
            "question": row["question"],
            "parent_question": parent.get("question"),
            "as_of": row.get("as_of") or "2026-10-19",
            "as_of_source": "row" if row.get("as_of") else "default 2026-10-19 (blank row as_of)",
            "period": row.get("period"),
            "family": row.get("family"),
            "stratum_family": int((row.get("family") or [0])[0]),
            "source_bank": row.get("source_bank"),
            "answer_kind": row.get("answer_kind"),
            "template": row.get("template"),
            "entity_level": row.get("entity_level"),
            "judgement_or_study": judge,
            "category": cat,
            "required_evidence": rubric.get("required_evidence"),
            "required_steps": rubric.get("required_steps"),
            "ground_truth": rubric.get("ground_truth"),
            "premise_audit": "not_false",
        })
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(questions: list[dict], manifest: dict) -> dict:
    write_jsonl(QUESTIONS, questions)
    manifest = dict(manifest)
    manifest["sha256_questions_jsonl"] = sha256(QUESTIONS)
    manifest["n"] = len(questions)
    MANIFEST.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def check() -> list[dict]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    got = sha256(QUESTIONS)
    if got != manifest["sha256_questions_jsonl"]:
        raise SystemExit(f"question list changed after freeze: {got} != {manifest['sha256_questions_jsonl']}")
    qs = load_jsonl(QUESTIONS)
    if len(qs) != manifest["n"]:
        raise SystemExit(f"expected {manifest['n']} questions, found {len(qs)}")
    return qs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        qs = check()
        print(f"frozen OK: {len(qs)} questions sha256={sha256(QUESTIONS)}")
        return

    instances = load_jsonl(INSTANCES)
    bank = {r["mid"]: r for r in load_jsonl(BANK)}
    audit = {r["mid"]: r for r in load_jsonl(AUDIT)}
    read = {r["mid"]: r for r in load_jsonl(READ)}
    pilot = pilot_universe()
    global ALIASES
    ALIASES = build_aliases(audit, pilot, bank)

    ledger, eligible = [], []
    for row in instances:
        ok, rule, detail = eligibility(row, audit, read, pilot, ALIASES, bank)
        ledger.append({"mid": row["mid"], "parent_mid": row["parent_mid"], "eligible": ok,
                       "rule": rule, "detail": detail, "question": row.get("question"),
                       "entity": pilot.get((row.get("entities") or [{}])[0].get("isin") or "", "")})
        if ok:
            eligible.append(row)

    counts = Counter(r["rule"] for r in ledger)
    picked, meta = sample(eligible)
    questions = build_questions(picked, bank, pilot)
    today = datetime.now(timezone.utc).isoformat()

    manifest = {
        "frozen_at_utc": today,
        "seed": SEED,
        "requested_n": N,
        "source_instances": str(INSTANCES),
        "source_bank": str(BANK),
        "instances_sha256": sha256(INSTANCES),
        "bank_sha256": sha256(BANK),
        "premise_audit_sha256": sha256(AUDIT),
        "read_grade_sha256": sha256(READ),
        "pilot_db": str(PILOT_DB),
        "pilot_db_bytes": PILOT_DB.stat().st_size,
        "pilot_isins": len(pilot),
        "exclusion_counts": dict(sorted(counts.items())),
        "eligible": len(eligible),
        "eligible_parents": len({r["parent_mid"] for r in eligible}),
        "rules": [
            "ILL_POSED in TRUTH_PANEL_READ_2026-10-31.jsonl",
            "premise_audit verdict == false",
            "no entity",
            "more than one entity",
            "entity ISIN not in the 60-name pilot universe",
            "question names a company other than the row entity",
            "question does not name the row entity",
            "one row per parent_mid in the sample",
            "at most two rows per company (ISIN) in the sample",
            f"at least {MIN_JUDGEMENT} judgement/study rows (answer_kind explanation or ripple200)",
        ],
        "family_quotas": meta["family_quotas"],
        "family_eligible": meta["family_eligible"],
        "judgement_rows": meta["judgement_rows"],
        "parent_unique": meta["parent_unique"],
        "company_max": meta["company_max"],
        "as_of_values": dict(sorted(Counter(q["as_of"][:10] for q in questions).items())),
        "source_banks": dict(sorted(Counter(q["source_bank"] for q in questions).items())),
    }

    write_jsonl(EXCLUSIONS, ledger)
    if args.freeze:
        manifest = freeze(questions, manifest)
        print(f"FROZEN {len(questions)} questions sha256={manifest['sha256_questions_jsonl']}")
    else:
        write_jsonl(HERE / "candidates.jsonl", questions)
        (HERE / "candidate_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        print(f"candidates {len(questions)} (not frozen); eligible={len(eligible)}")
    print("exclusions:", dict(sorted(counts.items())))
    print("families:", meta["family_quotas"])
    print("judgement/study:", meta["judgement_rows"])


ALIASES: list[tuple[str, str, str, list[str]]] = []


if __name__ == "__main__":
    main()
