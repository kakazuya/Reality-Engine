"""Walk-forward skill loop driver: fit on early occurrences, evaluate on later ones.

Runs one ``run_round`` per (mode, horizon) and prints the persisted skill
history. Hyperparameters (temperature, prior_mix, min_t) are the frozen module
defaults — they are NOT tuned here, because tuning them against the eval
window would be evaluation-set leakage. If the numbers say no improvement,
that is the report.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from reality_engine.db.database import db_manager  # noqa: E402
from reality_engine.processing import skill_loop as sl  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Walk-forward skill loop driver.")
    ap.add_argument("--modes", default="ensemble,legacy")
    ap.add_argument("--horizons", default="5,20")
    ap.add_argument("--train-frac", type=float, default=0.45)
    ap.add_argument("--history", action="store_true", help="print skill history and exit")
    args = ap.parse_args(argv)

    with db_manager.session() as conn:
        if args.history:
            print(json.dumps(sl.history(conn, limit=30), indent=1, default=str))
            return 0
        for mode in [m.strip() for m in args.modes.split(",") if m.strip()]:
            for h in [int(x) for x in args.horizons.split(",") if x.strip()]:
                rec = sl.run_round(conn, mode=mode, horizon_days=h, train_frac=args.train_frac)
                print(json.dumps({k: v for k, v in rec.items()
                                  if k not in ("stats",)}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
