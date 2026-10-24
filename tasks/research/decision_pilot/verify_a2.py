"""Verify A2 rerank ranks from cached responses (no API calls)."""
import json
from pathlib import Path

ROOT = Path(r"C:\Users\warri\Downloads\IDM-worktrees\20261024T172743Z-a480564b\tasks\research\decision_pilot")
DATA = ROOT / "cache/responses"


def main():
    pairs = json.load(open(ROOT / "data/a2_pairs.json", encoding="utf-8"))["pairs"]
    for model in ("Cloudflare__clef-flash", "nace-ai__drex-v2.0", "nace-ai__drex-max"):
        byq = {}
        for p in pairs:
            f = DATA / model / "A2" / (p["id"] + ".json")
            r = json.load(open(f))
            prob = r["answers"]["answers"]["noul"]
            byq.setdefault(p["qid"], []).append((prob, p["cand_rank"], p["label"]))
        ranks, detail = [], {}
        for q, rows in byq.items():
            rows = sorted(rows, key=lambda x: (-x[0], x[1]))
            rank = next((i for i, x in enumerate(rows, 1) if x[2]), None)
            ranks.append(rank)
            detail[q] = rank
        print(model, "hit@1", sum(r == 1 for r in ranks), "/48", "hit@3", sum(r is not None and r <= 3 for r in ranks),
              "/48")
        print("  ranks:", ranks)
        print("  top1-but-not-top3:", [q for q, r in detail.items() if r in (2, 3)])


if __name__ == "__main__":
    main()
