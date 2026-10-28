"""Independent known_at check on the built store (5 docs per doc type).

    python tasks/pilot_t2/check_known_at.py

Re-derives each doc's filing timestamp from the source record — not from the
builder's in-memory draft — and writes ``known_at_check.md``.  Exit 1 on any
mismatch.  The crawl date (`corporate_documents.doc_date`) is never read.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from reality_engine.db.readonly import connect_ro  # noqa: E402

import os  # noqa: E402

DATA = Path(os.environ.get("REALITY_DATA_ROOT",
                           r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data"))
D_RAW = Path(r"D:\RealityEngine\raw")
DB = Path(os.environ.get("REALITY_CHUNKS_V3") or (REPO / ".tmp" / "pilot" / "chunks_v3_pilot.db"))
OUT = Path(__file__).resolve().parent


def ro(path: Path) -> sqlite3.Connection:
    con = connect_ro(path, timeout_s=60)
    con.row_factory = sqlite3.Row
    return con


def parse_ts(value) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s + "T23:59:59"
    s = s.replace(" ", "T")
    m = re.match(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})", s)
    if m:
        return f"{m.group(1)}T{m.group(2)}"
    for fmt in ("%d-%b-%YT%H:%M:%S", "%d-%m-%YT%H:%M:%S"):
        try:
            return time.strftime("%Y-%m-%dT%H:%M:%S", time.strptime(s, fmt))
        except ValueError:
            pass
    return None


def nse_known(symbol: str, raw_path: str) -> str | None:
    """NSE announcement timestamp by attachment basename (exchdisstime)."""
    base = Path(raw_path or "").name
    for run in sorted((D_RAW / "nse_announcements").glob("*")):
        path = run / f"{symbol}.jsonl"
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if Path(row.get("attachment_url") or "").name == base:
                return parse_ts(row.get("known_at"))
    return None


def record_known_at(con: sqlite3.Connection, row: sqlite3.Row, reads: dict) -> tuple[str | None, str]:
    doc_type = row["doc_type"]
    sha = row["sha256"] or ""
    if doc_type == "annual_report":
        rec = reads["ar"].execute(
            "SELECT filed_at FROM ar_docs WHERE sha256=?", (sha,)).fetchone()
        if rec:
            return parse_ts(rec["filed_at"]), "ar_facts.ar_docs.filed_at(sha)"
        fy = (row["known_at"] or "")[:4]
        fiscal = f"{fy}-03-31" if fy else ""
        rec = reads["ar"].execute(
            "SELECT filed_at FROM ar_docs WHERE isin=? AND fiscal_year=?",
            (row["isin"], fiscal)).fetchone()
        if rec:
            return parse_ts(rec["filed_at"]), "ar_facts.ar_docs.filed_at(fy)"
        return None, "no ar_docs row"
    if doc_type in ("concall", "results_notes"):
        rec = reads["ei"].execute(
            "SELECT COALESCE(bse_dissem_ts, publication_date) AS k FROM corporate_documents "
            "WHERE sha256_hash=?", (sha,)).fetchone()
        if rec and rec["k"]:
            return parse_ts(rec["k"]), "corporate_documents.bse_dissem|publication"
        nse = nse_known(row["symbol_at_time"], row["raw_path"])
        if nse:
            return nse, "nse_announcements.exchdisstime"
        return None, "no filing record"
    if doc_type == "deck":
        rec = reads["deck"].execute(
            "SELECT known_at FROM deck_sources WHERE sha256=?", (sha,)).fetchone()
        if rec:
            return parse_ts(rec["known_at"]), "deck_sources.known_at"
        return None, "no deck_sources row"
    if doc_type == "announcement":
        # BSE rows carry the attachment UUID in raw_url; the local file is named
        # by the fetch key, so the filename is not the join key.
        base = Path(row["raw_url"] or "").name.lower()
        if base:
            rec = reads["ann"].execute(
                "SELECT DissemDT FROM ann WHERE ATTACHMENTNAME=?", (base,)).fetchone()
            if rec:
                return parse_ts(rec["DissemDT"]), "bse_announcements.ann.DissemDT(attachment)"
        newsid = Path(row["raw_path"] or "").stem
        if newsid.isdigit() or "-" in newsid:
            rec = reads["ann"].execute(
                "SELECT DissemDT FROM ann WHERE NEWSID=?", (newsid,)).fetchone()
            if rec:
                return parse_ts(rec["DissemDT"]), "bse_announcements.ann.DissemDT"
        nse = nse_known(row["symbol_at_time"], row["raw_path"])
        if nse:
            return nse, "nse_announcements.exchdisstime"
        return None, "no filing record"
    return None, "unknown doc type"


def main() -> int:
    con = ro(DB)
    reads = {"ar": ro(DATA / "ar_facts.db"), "ei": ro(DATA / "equity_intelligence.db"),
             "deck": ro(DATA / "deck_figures.db"), "ann": ro(DATA / "bse_announcements.db")}
    rows = []
    for doc_type in ("annual_report", "concall", "deck", "announcement"):
        rows.extend(con.execute(
            "SELECT doc_id, sha256, doc_type, isin, symbol_at_time, known_at, raw_path, raw_url "
            "FROM doc WHERE doc_type=? ORDER BY doc_id LIMIT 5", (doc_type,)).fetchall())
    lines = ["# known_at check — 5 docs per type vs the filing record", "",
             "| doc type | doc_id | chunk known_at | record known_at | source | match |",
             "|---|---|---|---|---|---|"]
    bad = 0
    for row in rows:
        record, source = record_known_at(con, row, reads)
        ok = record == row["known_at"]
        bad += 0 if ok else 1
        lines.append(f"| {row['doc_type']} | {row['doc_id'][:26]} | {row['known_at']} | "
                     f"{record} | {source} | {'OK' if ok else 'MISMATCH'} |")
    lines += ["", f"mismatches: {bad} / {len(rows)}"]
    (OUT / "known_at_check.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"known_at check: {bad} mismatch / {len(rows)} rows -> known_at_check.md")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
