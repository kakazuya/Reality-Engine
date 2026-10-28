"""Build the 150-case answerability sample (seed 20261028). Read-only on the bank.

Rules (task brief 2026-10-28):
  * all 30 regression:true cases;
  * 30 more from source_bank=reddit200;
  * the other 90 stratified across family x entity_level so every family is
    covered >=3 times and every entity level >=5 times.

A case carries a LIST of families. A case that is tagged with a rare family
(e.g. 5 = cross-document, 7 = company->policy) is counted under that rare tag,
because otherwise those families can never be reached by a first-family-only
stratifier.
"""
from __future__ import annotations

import collections
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
BANK = HERE.parent / "master_bank" / "MASTER_BANK.jsonl"
SEED = 20261028
FAMILY_MIN = 3
LEVEL_MIN = 5


def load() -> list[dict]:
    return [json.loads(line) for line in BANK.read_text(encoding="utf-8").splitlines() if line.strip()]


def rare_family(case: dict, counts: collections.Counter) -> int:
    fams = case.get("family") or [99]
    return min(fams, key=lambda f: (counts[f], f))


def main() -> None:
    rng = random.Random(SEED)
    rows = load()
    fam_counts = collections.Counter(f for r in rows for f in (r.get("family") or []))

    reg = [r for r in rows if r.get("regression")]
    assert len(reg) == 30, len(reg)
    picked = {r["mid"] for r in reg}

    reddit_pool = [r for r in rows if r.get("source_bank") == "reddit200" and r["mid"] not in picked]
    reddit = rng.sample(reddit_pool, 30)
    picked.update(r["mid"] for r in reddit)

    pool = [r for r in rows if not r.get("regression") and r.get("source_bank") != "reddit200"
            and r["mid"] not in picked]
    label = {r["mid"]: rare_family(r, fam_counts) for r in pool}

    def famsat(chosen: list[dict]) -> dict[int, int]:
        return collections.Counter(f for r in chosen for f in (r.get("family") or []))

    def lvlsat(chosen: list[dict]) -> dict[str, int]:
        return collections.Counter(r["entity_level"] for r in chosen)

    chosen: list[dict] = []
    taken: set[str] = set()

    # 1) satisfy the minima greedily
    while len(chosen) < 90:
        fs, ls = famsat(chosen), lvlsat(chosen)
        open_fams = {f for f in fam_counts if fs[f] < FAMILY_MIN}
        open_lvls = {lv for lv in ls if ls[lv] < LEVEL_MIN}
        open_lvls |= {r["entity_level"] for r in pool} - set(ls)
        open_lvls = {lv for lv in open_lvls if lvlsat(chosen)[lv] < LEVEL_MIN}
        if not open_fams and not open_lvls:
            break
        best, best_score = [], 0
        for r in pool:
            if r["mid"] in taken:
                continue
            score = sum(1 for f in (r.get("family") or []) if f in open_fams)
            score += 2 if r["entity_level"] in open_lvls else 0
            if score > best_score:
                best, best_score = [r], score
            elif score == best_score and score > 0:
                best.append(r)
        if not best:
            break
        pick = rng.choice(best)
        chosen.append(pick)
        taken.add(pick["mid"])

    # 2) fill the remaining slots, weighted by remaining stratum size
    rest = [r for r in pool if r["mid"] not in taken]
    while len(chosen) < 90 and rest:
        r = rng.choice(rest)
        chosen.append(r)
        taken.add(r["mid"])
        rest = [x for x in rest if x["mid"] != r["mid"]]

    out = reg + reddit + chosen
    order = {"shivam30": 0, "reddit200": 1, "open300": 2, "variations300": 3, "ripple200": 4}
    out.sort(key=lambda r: (order.get(r.get("source_bank"), 9), r["mid"]))
    assert len(out) == 150, len(out)
    assert len({r["mid"] for r in out}) == 150

    (HERE / "SAMPLE.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")

    fs, ls = famsat(out), lvlsat(out)
    print("rows", len(out), "regressions", sum(1 for r in out if r.get("regression")),
          "reddit", sum(1 for r in out if r.get("source_bank") == "reddit200"))
    print("family coverage", {f: fs[f] for f in sorted(fam_counts)})
    print("family <3", [f for f in sorted(fam_counts) if fs[f] < FAMILY_MIN])
    print("level coverage", dict(sorted(ls.items())))
    print("level <5", [lv for lv in sorted(ls) if ls[lv] < LEVEL_MIN])
    print("banks", collections.Counter(r.get("source_bank") for r in out))


if __name__ == "__main__":
    main()
