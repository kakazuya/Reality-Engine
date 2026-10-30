"""v4 WP2b — the typed claim table for narrative sources (§B.3, §H.2).

One row per ``concall_facts.cc_items`` row (644,957 held), with

* ``topic`` — a level-2 ``vocab.label`` id from the same deterministic mapper as
  :mod:`reality_engine.query.v4.build_vocab` (never a raw phrase; ``other`` when the
  declared vocabulary cannot name it);
* the facets the extractor already carries — ``direction`` (up/down/neutral, raw
  kept), ``magnitude`` + ``unit`` (parsed from the textual value), ``horizon``
  (the period, canonicalised to ``QnFYYY``/``FYYY`` where it parses),
  ``certainty`` (firmness), ``guidance_vs_fact``;
* the audit trail — the verbatim ``quote``, the raw surface and ``surface_id``
  where the phrase is in the pilot surface layer;
* ``known_at`` = the concall filing time (``cc_items.filed_at``), never a crawl date.

    python -m reality_engine.query.v4.build_claim --out .tmp/v4.db --vocab-db .tmp/v4_vocab.db
    python -m reality_engine.query.v4.build_claim --spotcheck 50     # mechanical check + sample
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
from pathlib import Path

from reality_engine.db.readonly import connect_ro
from reality_engine.query.v4.build_vocab import label_for, words_of

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

SCHEMA = """
CREATE TABLE IF NOT EXISTS claim(
  claim_id INTEGER PRIMARY KEY,
  entity_id TEXT NOT NULL,
  topic TEXT NOT NULL,
  direction TEXT, direction_raw TEXT,
  magnitude REAL, unit TEXT, horizon TEXT,
  certainty TEXT, guidance_vs_fact TEXT,
  quote TEXT, page_no INTEGER, doc_id INTEGER, doctype TEXT,
  surface_id INTEGER, surface_raw TEXT, list_name TEXT, basis TEXT,
  known_at TEXT NOT NULL, pit_conf REAL);
CREATE INDEX IF NOT EXISTS ix_claim_entity_topic ON claim(entity_id, topic);
CREATE INDEX IF NOT EXISTS ix_claim_known_at ON claim(known_at);
CREATE INDEX IF NOT EXISTS ix_claim_topic ON claim(topic);
"""

_DIRECTION = {"raised": "up", "lowered": "down"}
_CERTAINTY = {"firm": "stated", "indicative": "expected", "aspirational": "aspirational"}
_NUM = re.compile(r"(?:^|(?<=[\s(]))[-+]?\d[\d,]*(?:\.\d+)?")
_FY_NUM = re.compile(r"\b(?:fy|q)\s*'?\d{2,4}\b", re.I)
_QFYC = re.compile(r"\bq([1-4])\s*fy\s*'?(\d{2,4})\b", re.I)
_FY = re.compile(r"\bfy\s*'?(\d{2,4})\b", re.I)
_Q = re.compile(r"\bq([1-4])\b", re.I)


def parse_magnitude(value: str | None, unit: str | None) -> float | None:
    """First number in the textual value; a two-number range becomes its midpoint.

    No unit -> no magnitude: a bare number cannot be scaled, and guessing the
    scale is how a claim becomes a lie. Period tokens (``FY24``, ``Q3``) are
    removed before the parse so a horizon never leaks into the magnitude.
    """
    if not value or not unit:
        return None
    text = _FY_NUM.sub(" ", str(value))
    text = re.sub(r"(?<=\d)-(?=\d)", " ", text)      # a range dash, not a minus sign
    nums = [float(n.replace(",", "")) for n in _NUM.findall(text)]
    if not nums:
        return None
    if len(nums) >= 2:
        return round((nums[0] + nums[1]) / 2.0, 6)
    return nums[0]


def horizon_of(period: str | None) -> str | None:
    """``QnFYYY`` / ``FYYY`` when the text names a fiscal period, else the trimmed text."""
    if not period:
        return None
    text = str(period).strip()
    qfy = _QFYC.search(text)
    if qfy:
        return f"Q{qfy.group(1)}FY{qfy.group(2)[-2:]}"
    fy = _FY.search(text)
    if fy:
        yy = fy.group(1)[-2:]
        q = _Q.search(text)
        return f"Q{q.group(1)}FY{yy}" if q else f"FY{yy}"
    return text[:40].lower()


def direction_of(raw: str | None) -> str:
    return _DIRECTION.get((raw or "").strip().lower(), "neutral")


def certainty_of(firmness: str | None) -> str | None:
    return _CERTAINTY.get((firmness or "").strip().lower())


def guidance_vs_fact(list_name: str | None, direction: str | None,
                     firmness: str | None) -> str:
    """A guidance-list item, or anything carrying a guidance facet, is guidance."""
    if (list_name or "").strip().lower() == "guidance":
        return "guidance"
    return "guidance" if (direction or firmness) else "fact"


def claim_row(row: dict, surface_ids: dict[str, int] | None = None,
              weight: dict[str, float] | None = None) -> dict:
    """One cc_items row -> one claim row. Pure: the test builds it without I/O."""
    metric = (row.get("metric") or "").strip()
    label, _method = label_for(words_of(metric), weight) if metric else ("other", "other")
    list_name = (row.get("list_name") or "").strip() or None
    raw_dir = (row.get("direction") or "").strip() or None
    firm = (row.get("firmness") or "").strip() or None
    return {
        "entity_id": row["isin"],
        "topic": label,
        "direction": direction_of(raw_dir),
        "direction_raw": raw_dir,
        "magnitude": parse_magnitude(row.get("value"), row.get("unit")),
        "unit": (row.get("unit") or "").strip() or None,
        "horizon": horizon_of(row.get("period")),
        "certainty": certainty_of(firm),
        "guidance_vs_fact": guidance_vs_fact(list_name, raw_dir, firm),
        "quote": row.get("quote"),
        "page_no": None,
        "doc_id": row.get("doc_id"),
        "doctype": "concall",
        "surface_id": (surface_ids or {}).get(metric),
        "surface_raw": metric or None,
        "list_name": list_name,
        "basis": (row.get("basis") or "").strip() or None,
        "known_at": row["known_at"],
        "pit_conf": None,
    }


def load_surface_ids(vocab_db: Path | None) -> dict[str, int]:
    if not vocab_db or not Path(vocab_db).exists():
        return {}
    con = sqlite3.connect(f"file:{Path(vocab_db).as_posix()}?mode=ro", uri=True)
    try:
        return {s: i for s, i in con.execute("SELECT surface_verbatim, surface_id FROM surface")}
    finally:
        con.close()


_COLS = ("isin", "list_name", "metric", "value", "unit", "period", "basis",
         "direction", "firmness", "quote", "doc_id", "known_at")


def collect_rows(data_root: Path, limit: int | None = None) -> list[dict]:
    con = connect_ro(data_root / "concall_facts.db", timeout_s=180, immutable=True)
    try:
        sql = ("SELECT i.isin, i.list_name, i.metric, i.value, i.unit, i.period, i.basis, "
               "i.direction, i.firmness, i.quote, i.doc_id, "
               "COALESCE(i.filed_at, d.filed_at) AS known_at "
               "FROM cc_items i LEFT JOIN cc_docs d ON d.doc_id = i.doc_id "
               "ORDER BY i.doc_id, i.list_name, i.idx")
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [{c: v for c, v in zip(_COLS, row)}
                for row in (con.execute(sql) or [])]
    finally:
        con.close()


def build(out: Path, data_root: Path, *, vocab_db: Path | None = None,
          limit: int | None = None) -> dict:
    rows = collect_rows(data_root, limit)
    surface_ids = load_surface_ids(vocab_db)
    weight = _surface_weight(surface_ids)
    inserted, no_known, no_quote = 0, 0, 0
    out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(out)
    try:
        con.executescript(SCHEMA)
        con.execute("DELETE FROM claim")
        batch = []
        for raw in rows:
            if not raw.get("known_at"):
                no_known += 1
                continue
            if not (raw.get("quote") or "").strip():
                no_quote += 1
            batch.append(claim_row(raw, surface_ids, weight))
            if len(batch) >= 20_000:
                _insert(con, batch)
                inserted += len(batch)
                batch.clear()
        if batch:
            _insert(con, batch)
            inserted += len(batch)
        con.commit()
        topics = dict(con.execute(
            "SELECT topic, count(*) FROM claim GROUP BY 1 ORDER BY 2 DESC").fetchall())
        labelled = sum(n for t, n in topics.items() if t != "other")
        by_facet = {}
        for col in ("direction", "certainty", "guidance_vs_fact", "horizon"):
            by_facet[col] = dict(con.execute(
                f"SELECT {col}, count(*) FROM claim GROUP BY 1 ORDER BY 2 DESC LIMIT 12").fetchall())
        report = {
            "read": len(rows), "inserted": inserted,
            "skipped_no_known_at": no_known, "empty_quote": no_quote,
            "labelled": labelled,
            "labelled_pct": round(100.0 * labelled / max(1, inserted), 2),
            "other_pct": round(100.0 * topics.get("other", 0) / max(1, inserted), 2),
            "distinct_topics": len(topics),
            "top_topics": dict(list(topics.items())[:15]),
            "facets": by_facet,
            "with_surface_id": con.execute(
                "SELECT count(*) FROM claim WHERE surface_id IS NOT NULL").fetchone()[0],
            "with_magnitude": con.execute(
                "SELECT count(*) FROM claim WHERE magnitude IS NOT NULL").fetchone()[0],
            "out": str(out),
        }
    finally:
        con.close()
    return report


def _insert(con: sqlite3.Connection, rows: list[dict]) -> None:
    con.executemany(
        "INSERT INTO claim (entity_id, topic, direction, direction_raw, magnitude, unit, "
        "horizon, certainty, guidance_vs_fact, quote, page_no, doc_id, doctype, surface_id, "
        "surface_raw, list_name, basis, known_at, pit_conf) "
        "VALUES (:entity_id,:topic,:direction,:direction_raw,:magnitude,:unit,:horizon,"
        ":certainty,:guidance_vs_fact,:quote,:page_no,:doc_id,:doctype,:surface_id,"
        ":surface_raw,:list_name,:basis,:known_at,:pit_conf)", rows)


def _surface_weight(surface_ids: dict[str, int]) -> dict[str, float] | None:
    """Token rarity from the surface layer, so the mapper stays consistent."""
    if not surface_ids:
        return None
    from collections import Counter
    weight: Counter = Counter()
    for surface in surface_ids:
        for t in words_of(surface):
            weight[t] += 1
    return dict(weight)


def spot_check(db: Path, n: int = 50, seed: int = 20261031) -> dict:
    """Draw n random claims and print what a hand checker needs: claim, quote, label.

    The mechanical part checks only what a machine can: the quote is present and
    non-trivial and the phrase the label came from is visible. Precision on the
    label itself is the hand check's job (report it, never assume it).
    """
    con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    try:
        rows = list(con.execute(
            "SELECT claim_id, entity_id, topic, surface_raw, quote, known_at "
            "FROM claim ORDER BY claim_id"))
    finally:
        con.close()
    rng = random.Random(seed)
    sample = rng.sample(rows, min(n, len(rows)))
    syn = _synonyms()
    checked = []
    substantive = visible = 0
    for cid, isin, topic, surface, quote, known_at in sample:
        q = (quote or "").strip()
        tokens = syn.get(topic, set())
        if tokens:
            seen = bool(q) and (any(t in q.lower() for t in tokens)
                                or bool(surface and surface.lower() in q.lower()))
        else:                       # the honest bucket: nothing to look for but the quote
            seen = bool(q)
        ok = len(q) >= 20
        substantive += int(ok)
        visible += int(seen and ok)
        checked.append({"claim_id": cid, "entity_id": isin, "topic": topic,
                        "surface": surface, "quote": q[:400], "known_at": known_at,
                        "label_token_in_quote": seen, "quote_too_short": not ok})
    return {"n": len(checked), "quote_substantive": substantive,
            "quote_substantive_pct": round(100.0 * substantive / max(1, len(checked)), 2),
            "label_token_visible": visible,
            "label_token_visible_pct": round(100.0 * visible / max(1, len(checked)), 2),
            "seed": seed, "sample": checked,
            "note": "mechanical only: quote present and >=20 chars, and the label's own "
                    "wording visible in it. Label precision is the hand check; the brief "
                    "wants 50 claims read against their quote, which this file hands over."}


def _synonyms() -> dict[str, set[str]]:
    """Tokens each label may show in a quote (the declared synonym table)."""
    from reality_engine.query.v4.build_vocab import TOPICS
    return {tid: set(syn.split()) for tid, (_f, syn, _d) in TOPICS.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path(".tmp/v4.db"))
    ap.add_argument("--data-root", type=Path,
                    default=Path(os.environ.get("REALITY_DATA_ROOT", ROOT / "reality_engine" / "data")))
    ap.add_argument("--vocab-db", type=Path, default=Path(".tmp/v4_vocab.db"))
    ap.add_argument("--limit", type=int, default=None, help="small fixture runs")
    ap.add_argument("--spotcheck", type=int, default=50,
                    help="random claims to print for the hand check (0 = skip)")
    ap.add_argument("--spotcheck-out", type=Path, default=Path(".tmp/claim_spotcheck.json"))
    args = ap.parse_args(argv)

    report = build(args.out, args.data_root, vocab_db=args.vocab_db, limit=args.limit)
    if args.spotcheck:
        check = spot_check(args.out, args.spotcheck)
        args.spotcheck_out.parent.mkdir(parents=True, exist_ok=True)
        args.spotcheck_out.write_text(json.dumps(check, indent=1, ensure_ascii=False),
                                      encoding="utf-8")
        report["spotcheck"] = {k: v for k, v in check.items() if k != "sample"}
        report["spotcheck_file"] = str(args.spotcheck_out)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
