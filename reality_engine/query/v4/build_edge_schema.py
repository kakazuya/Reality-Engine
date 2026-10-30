"""v4 WP2b — edge DDL for the discovery layer (§E.1, schema only).

Four tables, no rows: ``edge``, ``attention``, ``hypothesis``, ``reaction_lag``.
Nothing is dropped: a link that fails FDR stays visible as ``measured_weak`` or
``contradicted`` with its numbers, so ``label`` is a closed set with a CHECK.

    python -m reality_engine.query.v4.build_edge_schema --out .tmp/v4.db
    python -m reality_engine.query.v4.build_edge_schema --check     # DDL only, temp file

Idempotent: re-running against the same file is a no-op.
"""
from __future__ import annotations

import argparse
import sqlite3
import tempfile
from pathlib import Path

ORIGINS = ("measured", "text", "llm_proposed")
LABELS = ("verified", "measured_weak", "plausible_untested", "contradicted")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS edge(
  driver TEXT NOT NULL,
  target TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ({','.join(repr(o) for o in ORIGINS)})),
  strength REAL,
  lag INTEGER,
  n INTEGER,
  fdr_q REAL,
  stability_by_window TEXT,
  label TEXT NOT NULL CHECK (label IN ({','.join(repr(l) for l in LABELS)})),
  known_at TEXT NOT NULL,
  last_tested TEXT,
  mechanism TEXT,
  evidence_ref TEXT,
  PRIMARY KEY (driver, target, origin));
CREATE INDEX IF NOT EXISTS ix_edge_driver ON edge(driver);
CREATE INDEX IF NOT EXISTS ix_edge_target ON edge(target);

CREATE TABLE IF NOT EXISTS attention(
  entity TEXT NOT NULL,
  topic TEXT,
  day TEXT NOT NULL,
  mention_count INTEGER NOT NULL,
  source_kind TEXT NOT NULL,
  known_at TEXT NOT NULL,
  PRIMARY KEY (entity, topic, day, source_kind));
CREATE INDEX IF NOT EXISTS ix_attention_day ON attention(day);

CREATE TABLE IF NOT EXISTS hypothesis(
  hypothesis_id INTEGER PRIMARY KEY,
  proposed_link TEXT NOT NULL,
  proposer TEXT NOT NULL,
  required_test TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL,
  UNIQUE (proposed_link, created_at));

CREATE TABLE IF NOT EXISTS reaction_lag(
  event_id TEXT NOT NULL,
  hop INTEGER NOT NULL,
  entity TEXT NOT NULL,
  first_price_response_day TEXT,
  days_late INTEGER,
  known_at TEXT NOT NULL,
  PRIMARY KEY (event_id, hop, entity));
CREATE INDEX IF NOT EXISTS ix_reaction_lag_entity ON reaction_lag(entity);
"""

TABLES = ("edge", "attention", "hypothesis", "reaction_lag")


def build(out: Path) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(out)
    try:
        con.executescript(SCHEMA)
        con.commit()
        have = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in TABLES if t in have}
    finally:
        con.close()
    return {"out": str(out), "tables": have,
            "missing": [t for t in TABLES if t not in have], "rows": counts,
            "ok": all(t in have for t in TABLES)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path(".tmp/v4.db"))
    ap.add_argument("--check", action="store_true", help="run the DDL on a temp file only")
    args = ap.parse_args(argv)
    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            report = build(Path(tmp) / "edge_check.db")
        report["out"] = "<temp>"
    else:
        report = build(args.out)
    import json
    print(json.dumps(report, indent=1))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
