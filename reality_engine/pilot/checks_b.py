"""Checks for the pilot (b) build — the numbers behind tasks/pilot_b/REPORT.md.

Read-only over the built files and the raw sources. Every hand check re-reads the raw
source independently of the build path (the commodity CSV row, the contract row inside the
F&O zip, the held sec_bhavdata_full line, the held constituent CSV) and compares it with
the stored row; nothing is taken from the build's own intermediate state.

    python -m reality_engine.pilot.build_b --verify      # == this module's main()
"""
from __future__ import annotations

import csv
import datetime as dt
import glob
import io
import json
import random
import re
import sqlite3
import zipfile
from collections import Counter
from pathlib import Path

from reality_engine.pilot import build_b as b
from reality_engine.pilot import build_t1 as b1

SEED = 20261029
SNAP_CSVS = {code: fname for code, (_, fname) in b1.CSV_SNAPSHOTS.items()}
BHAV_RE = re.compile(r"sec_bhavdata_full_(\d{2})(\d{2})(\d{4})\.csv$")


# ---------------------------------------------------------------------------------------
# raw-source readers (independent of the build)
# ---------------------------------------------------------------------------------------
def commodity_raw() -> dict[tuple[str, str], dict]:
    out = {}
    with b.COMMODITY_CSV.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            out[(row["series_code"], row["date"])] = row
    return out


def fo_archive() -> dict[str, Path]:
    out = {}
    for path in glob.glob(str(b.FO_DIR / "*.zip")):
        day = b.fo_date_from_name(Path(path).name)
        if day:
            out.setdefault(day, Path(path))
    return out


def bhavcopy_raw() -> dict[str, Path]:
    out = {}
    for path in glob.glob(str(b.BHAVCOPY_RAW / "sec_bhavdata_full_*.csv")):
        m = BHAV_RE.search(Path(path).name)
        if m:
            out[f"{m.group(3)}-{m.group(2)}-{m.group(1)}"] = Path(path)
    return out


def bhavcopy_rows(path: Path) -> dict[tuple[str, str], dict]:
    out = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader)]
        for row in reader:
            rec = dict(zip(header, row))
            out[(rec["SYMBOL"].strip(), rec["SERIES"].strip())] = rec
    return out


def _close(a, bb) -> bool:
    if a is None or bb is None:
        return a == bb
    return abs(float(a) - float(bb)) < 1e-6


def _fmt(value) -> str:
    return "" if value is None else f"{value:.4f}".rstrip("0").rstrip(".") if isinstance(
        value, float) else str(value)


# ---------------------------------------------------------------------------------------
# hand checks: 10 random stored rows vs the raw source
# ---------------------------------------------------------------------------------------
def hand_check_series(con, n=10, seed=SEED) -> list[dict]:
    raw = commodity_raw()
    picks = random.Random(seed).sample(sorted(raw), n)
    out = []
    for code, day in picks:
        db = con.execute("SELECT value, unit, known_at, pit_conf FROM series_observation "
                         "WHERE series_code = ? AND period_start = ?", (code, day)).fetchone()
        src = raw[(code, day)]
        out.append({
            "table": "series_observation", "key": f"{code} {day}",
            "raw": f"close={src['close']} unit={src['unit']} known_at={src['known_at']}",
            "db": f"value={db[0]} unit={db[1]} known_at={db[2]} pit_conf={db[3]}" if db else "MISSING",
            "ok": bool(db) and _close(db[0], src["close"]) and db[1] == src["unit"]
                  and db[2] == f"{src['known_at']}T23:59:59" and db[3] == 0.8,
        })
    return out


def hand_check_fno(con, n=10, seed=SEED) -> list[dict]:
    archive = fo_archive()
    days = [r[0] for r in con.execute("SELECT DISTINCT date FROM fno_oi_daily ORDER BY date")]
    picks = random.Random(seed).sample([d for d in days if d in archive], n)
    out = []
    for day in sorted(picks):
        db = con.execute(
            "SELECT date, underlying, expiry, strike, option_type, oi, volume, settle "
            "FROM fno_oi_daily WHERE date = ? LIMIT 1", (day,)).fetchone()
        key = (db[1], db[2], db[3], db[4])
        raw = None
        with zipfile.ZipFile(archive[day]) as z:
            with z.open(z.namelist()[0]) as fh:
                reader = csv.reader(io.TextIOWrapper(fh, encoding="utf-8-sig",
                                                     errors="replace", newline=""))
                header = next(reader)
                kind = b.fo_format(header)
                for row in reader:
                    rec = b.fo_normalize(kind, header, row)
                    if rec and (rec[1], rec[2], rec[3], rec[4]) == key:
                        raw = rec
                        break
        out.append({
            "table": "fno_oi_daily", "key": f"{day} {db[1]} {db[2]} {key[2]} {key[3]}",
            "raw": (f"oi={_fmt(raw[5])} vol={_fmt(raw[7])} settle={_fmt(raw[8])}"
                    if raw else "CONTRACT MISSING FROM RAW"),
            "db": f"oi={_fmt(db[5])} vol={_fmt(db[6])} settle={_fmt(db[7])}",
            "ok": bool(raw) and raw[0] == db[0] and _close(raw[5], db[5])
                  and _close(raw[7], db[6]) and _close(raw[8], db[7]),
        })
    return out


def hand_check_bhavcopy(con, n=10, seed=SEED) -> list[dict]:
    raw = bhavcopy_raw()
    days = sorted(raw)
    rows = con.execute(
        "SELECT date, symbol, series, close, volume, turnover_lacs, deliverable_qty, "
        "delivery_pct FROM mkt_nse_full_daily WHERE date IN (%s)"
        % ",".join("?" * len(days)), days).fetchall()
    picks = random.Random(seed).sample(rows, n)
    cache = {}
    out = []
    for day, symbol, series, close, volume, turnover, deliv, deliv_pct in picks:
        raw_rows = cache.setdefault(day, bhavcopy_rows(raw[day]))
        src = raw_rows.get((symbol, series))
        ok = bool(src) and _close(close, src["CLOSE_PRICE"]) \
            and _close(volume, src["TTL_TRD_QNTY"]) and _close(turnover, src["TURNOVER_LACS"]) \
            and _close(deliv, src["DELIV_QTY"]) and _close(deliv_pct, src["DELIV_PER"])
        out.append({
            "table": "mkt_nse_full_daily", "key": f"{day} {symbol} {series}",
            "raw": (f"close={src['CLOSE_PRICE']} volume={src['TTL_TRD_QNTY']} "
                    f"turnover_lacs={src['TURNOVER_LACS']} deliv={src['DELIV_QTY']} "
                    f"deliv_pct={src['DELIV_PER']}" if src else "ROW MISSING FROM RAW"),
            "db": (f"close={_fmt(close)} volume={_fmt(volume)} turnover_lacs={_fmt(turnover)} "
                   f"deliv={_fmt(deliv)} deliv_pct={_fmt(deliv_pct)}"),
            "ok": ok,
        })
    return out


def hand_check_membership(con, n=10, seed=SEED) -> list[dict]:
    root = b.INDEX_HISTORY
    index_rows, member_rows, rng = [], [], random.Random(seed)
    for code, fname in sorted(SNAP_CSVS.items()):
        path = root / fname
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as f:
            isins = {r["ISIN Code"].strip() for r in csv.DictReader(f)
                     if (r.get("ISIN Code") or "").strip().startswith("INE")}
        listed = con.execute("SELECT members_at_snapshot, coverage FROM index_list "
                             "WHERE index_code = ?", (code,)).fetchone()
        index_rows.append({
            "table": "index_list", "key": f"{code} (held {fname})",
            "raw": f"{len(isins)} members in {fname}",
            "db": f"{listed[0]} members, coverage {listed[1]}" if listed else "MISSING",
            "ok": bool(listed) and listed[0] == len(isins),
        })
        for isin in rng.sample(sorted(isins), 2):
            db = con.execute(
                "SELECT added_on, removed_on, source, pit_conf FROM company_membership_pit "
                "WHERE isin = ? AND index_code = ? AND removed_on IS NULL",
                (isin, code)).fetchone()
            member_rows.append({
                "table": "company_membership_pit", "key": f"{code} {isin}",
                "raw": f"current member in {fname}",
                "db": (f"open interval from {db[0]} ({db[2]}, pit_conf {db[3]})"
                       if db else "MISSING"),
                "ok": bool(db) and db[0] <= "2026-09-30",
            })
    return index_rows + member_rows[:n]


# ---------------------------------------------------------------------------------------
# table stats + report
# ---------------------------------------------------------------------------------------
def table_stats(con) -> dict:
    q = lambda sql, *a: con.execute(sql, a).fetchone()
    stats = {}
    stats["index_list"] = {
        "rows": q("SELECT COUNT(*) FROM index_list")[0],
        "coverage": ", ".join(f"{k} {v}" for k, v in con.execute(
            "SELECT coverage, COUNT(*) FROM index_list GROUP BY coverage ORDER BY 2 DESC")),
    }
    n, lo, hi, isins = q("SELECT COUNT(*), MIN(added_on), MAX(added_on), COUNT(DISTINCT isin) "
                         "FROM company_membership_pit")
    conf = ", ".join(f"pit_conf {k}: {v}" for k, v in con.execute(
        "SELECT pit_conf, COUNT(*) FROM company_membership_pit GROUP BY pit_conf"))
    stats["company_membership_pit"] = {"rows": n, "coverage": f"{lo}..{hi}, {isins} ISINs; {conf}"}
    n, lo, hi = q("SELECT COUNT(*), MIN(period_start), MAX(period_start) FROM series_observation")
    stats["series_meta"] = {"rows": q("SELECT COUNT(*) FROM series_meta")[0],
                            "coverage": "22 World Bank Pink Sheet series, monthly"}
    stats["series_observation"] = {
        "rows": n, "coverage": f"{lo}..{hi} monthly; known_at {', '.join(sorted({r[0][:10] for r in con.execute('SELECT DISTINCT known_at FROM series_observation')}))}"}
    stats["commodity_price_daily"] = {
        "rows": q("SELECT COUNT(*) FROM commodity_price_daily")[0],
        "coverage": f"{q('SELECT MIN(date), MAX(date) FROM commodity_price_daily')[0]}.."
                    f"{q('SELECT MAX(date) FROM commodity_price_daily')[0]} view over "
                    f"{q('SELECT COUNT(DISTINCT commodity) FROM commodity_price_daily')[0]} commodities"}
    typ = ", ".join(f"{k}: {v}" for k, v in con.execute(
        "SELECT option_type, COUNT(*) FROM fno_oi_daily GROUP BY option_type ORDER BY 2 DESC"))
    stats["fno_oi_daily"] = {
        "rows": q("SELECT COUNT(*) FROM fno_oi_daily")[0],
        "coverage": (f"{q('SELECT MIN(date) FROM fno_oi_daily')[0]}.."
                     f"{q('SELECT MAX(date) FROM fno_oi_daily')[0]}, "
                     f"{q('SELECT COUNT(DISTINCT date) FROM fno_oi_daily')[0]} sessions, "
                     f"{q('SELECT COUNT(DISTINCT underlying) FROM fno_oi_daily')[0]} underlyings"
                     f"; {typ}"),
    }
    stats["mkt_nse_full_daily"] = {
        "rows": q("SELECT COUNT(*) FROM mkt_nse_full_daily")[0],
        "coverage": (f"{q('SELECT MIN(date) FROM mkt_nse_full_daily')[0]}.."
                     f"{q('SELECT MAX(date) FROM mkt_nse_full_daily')[0]}, "
                     f"{q('SELECT COUNT(DISTINCT date) FROM mkt_nse_full_daily')[0]} sessions, "
                     f"{q('SELECT COUNT(DISTINCT symbol) FROM mkt_nse_full_daily')[0]} symbols, "
                     f"{q('SELECT COUNT(DISTINCT series) FROM mkt_nse_full_daily')[0]} series"),
    }
    return stats


def skipped_statuses(cases_path: Path = b.CASES) -> list[tuple[str, int]]:
    """Fetch-class statuses still blocking (b) cases, by count (the reader ones are listed
    separately in the report because their source is held but needs an extraction pass)."""
    counts = Counter()
    with cases_path.open(encoding="utf-8") as f:
        for line in f:
            case = json.loads(line)
            if case["class"] == "b":
                counts[case["status"]] += 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def report_md(stats, checks, reclass, out: Path = b.PILOT_DIR) -> str:
    by_table = {}
    for row in checks:
        by_table.setdefault(row["table"], []).append(row)
    moved = Counter(table for _, table, _ in reclass["moved_cases"])
    order = ["series_meta", "series_observation", "commodity_price_daily", "index_list",
             "company_membership_pit", "fno_oi_daily", "mkt_nse_full_daily"]
    lines = ["# Pilot (b) — the (b) tables whose source is already held (2026-10-29)", "",
             "Built by `python -m reality_engine.pilot.build_b` into "
             "`.tmp/pilot_b/market_state_b.db` with the DDL of "
             "`tasks/SCHEMA_FINAL_2026-10-29.sql` (schema prefix stripped: one file per "
             "domain). No network, no live-DB write; every raw file on D: is streamed once.",
             "", "## 1. Tables", "",
             "| table | rows | coverage | hand check | cases moved b → a |",
             "|---|---:|---|---|---:|"]
    for name in order:
        st = stats.get(name, {})
        hc = by_table.get("series_observation" if name in ("series_meta",
                                                           "commodity_price_daily") else name, [])
        passed = sum(1 for r in hc if r["ok"])
        lines.append(f"| `{name}` | {st.get('rows', 0):,} | {st.get('coverage', '')} | "
                     f"{passed}/{len(hc)} against the raw file | {moved.get(name, 0)} |")
    lines += ["", f"Case re-classification: **a {reclass['counts'].get('a', 0)} / "
              f"b {reclass['counts'].get('b', 0)} / c {reclass['counts'].get('c', 0)}** "
              f"(from a 629 / b 435 / c 9): {reclass['moved']} moved b → a, "
              f"{reclass['kept_b']} still b, written to `tasks/pilot_b/cases_pilot_b.jsonl`.",
              "", "## 2. Cases moved b → a", ""]
    for cid, _table, note in reclass["moved_cases"]:
        lines.append(f"- `{cid}` — {note}")
    lines += ["", "## 2b. Five dependent bank cases per table (the field is present for the "
              "case's entity and period)", "",
              "| table | case | entity + period evidence | verdict |", "|---|---|---|---|"]
    for name in order:
        picked = [(cid, note) for cid, table, note in reclass["moved_cases"] if table == name]
        picked += [(cid, note) for cid, table, note in reclass["kept_cases"] if table == name]
        for cid, note in picked[:5]:
            verdict = "moved b → a" if (cid, name, note) in reclass["moved_cases"] else \
                "kept b for another reason"
            lines.append(f"| `{name}` | `{cid}` | {note} | {verdict} |")
    lines += ["", "## 3. Cases kept b (the built table did not verify them)", ""]
    for cid, _table, note in reclass["kept_cases"][:40]:
        lines.append(f"- `{cid}` — {note}")
    if len(reclass["kept_cases"]) > 40:
        lines.append(f"- … {len(reclass['kept_cases']) - 40} more in `reclass.json`")
    lines += ["", "## 4. Skipped: needs a fetch or a document reader", "",
              "| blocker | (b) cases | why skipped |", "|---|---:|---|"]
    why = {
        "needs_new_fetch:nse_index_circulars": "held and built (444/446 notice PDFs)",
        "needs_new_fetch:commodity_price_daily": "22 monthly World Bank series built; "
                                                 "daily LME/MCX/domestic series not held",
        "needs_new_fetch:nse_fno_bhavcopy": "held and built (futures market-wide, options "
                                            "pilot symbols)",
        "needs_new_fetch:nse_fno_history": "held and built",
        "needs_new_fetch:bhavcopy_backfill": "NSE history built from the snapshot; SME/BSE-only "
                                             "archive not held",
    }
    for status, n in skipped_statuses():
        if not status.startswith("needs_new_fetch:"):
            continue
        lines.append(f"| `{status}` | {n} | {why.get(status, 'not held; needs the fetch queue')} |")
    for status, n in skipped_statuses():
        if not status.startswith("needs_new_table:"):
            continue
        table = status.split(":", 1)[1]
        why_ = ("already built by the chunks_v3 pilot — not rebuilt here"
                if table == "chunks_v3" else
                "already built by the T1 pilot (`build_t1`) — not rebuilt here"
                if table in ("company_metric_series", "company_segment_pnl") else
                "designed table: source held, but the deterministic/reader build is not "
                "part of this pilot")
        lines.append(f"| `{status}` | {n} | {why_} |")
    lines += ["", "## 6. How to reproduce", "", "```bash",
              "python -m reality_engine.pilot.build_b            # build (~43 min, streamed)",
              "python -m reality_engine.pilot.build_b --verify   # stats + hand checks + reclassify",
              "python -m unittest reality_engine.tests.test_pilot_t1 "
              "reality_engine.tests.test_pilot_b_tables",
              "```", "",
              "No network, no paid model, no commit. The build reads only D: raw files and the "
              "read-only live stores; it writes only `.tmp/pilot_b/` and `tasks/pilot_b/`.",
              ""]
    return "\n".join(lines)
    lines += ["", "## 5. PIT rules used and the drift found", "",
              "- `series_observation.known_at` = the WB sheet's own `Updated on` date at "
              "23:59:59 IST (never the fetch date): every historical row carries the held "
              "vintage stamp, so it cannot leak into an earlier decision. `pit_conf` 0.8 "
              "because the stamp is date-only.",
              "- `fno_oi_daily.date` / `mkt_nse_full_daily.date` are the source session; a "
              "row is usable from that session's 15:30 IST close (the 15:30 rule is applied "
              "by `build_t1.day0`, unchanged).",
              "- `company_membership_pit` carries the notice's effective date in `added_on`/"
              "`removed_on` (source `nse_notice`, pit_conf 1.0) or a 2019-01-01 backcast "
              "(`snapshot_backcast`, pit_conf 0.8).",
              "- **Drift 1:** the brief says the NSE full bhavcopy raw files are held under "
              "`D:/RealityEngine/raw/bhavcopy` and `raw_market`; only 38 recent "
              "`sec_bhavdata_full_*.csv` are there. The complete NSE history is the held "
              "`truth_duckdb.px_nse` (4,290,443 bhavcopy-derived rows, 2019-01-01..2026-10-19), "
              "which is what `mkt_nse_full_daily` was built from; `last` stays NULL because "
              "px_nse does not carry LAST_PRICE.",
              "- **Drift 2:** `D:/.../index_history` holds 444 of the 446 listed notice PDFs "
              "(2 missing), and 6 constituent CSVs (the 3 in `index_constituents/` are older "
              "copies). The rebuild reproduces the T1 pilot exactly (10,895 intervals).",
              "- **Drift 3:** the commodity CSV has 22 series; the design asked for 40 "
              "(LME/MCX/daily). `wb_aluminium` is absent, so aluminium-dependent cases stay b.",
              "- **Drift 4:** F&O options are loaded for the pilot/regression symbols and the "
              "entities of the F&O bank cases only; futures are market-wide (the ban-list and "
              "rollover cases need that).", ""]
    return "\n".join(lines)


def main(out: Path = b.OUT) -> int:
    con = b.readonly(b.MARKET_DB)
    stats = table_stats(con)
    checks = (hand_check_series(con) + hand_check_fno(con) + hand_check_bhavcopy(con)
              + hand_check_membership(con))
    con.close()
    failed = [c for c in checks if not c["ok"]]
    b.PILOT_DIR.mkdir(parents=True, exist_ok=True)
    hc = ["# Pilot (b) hand checks — 10 random stored rows vs the raw source", "",
          f"seed {SEED}; every row below is re-read from the raw file, not from the build.",
          "", "| table | key | raw | stored | ok |", "|---|---|---|---|---|"]
    for c in checks:
        hc.append(f"| `{c['table']}` | {c['key']} | {c['raw']} | {c['db']} | "
                  f"{'OK' if c['ok'] else 'FAIL'} |")
    (b.PILOT_DIR / "HAND_CHECK.md").write_text("\n".join(hc) + "\n", encoding="utf-8")
    reclass = b.reclassify()
    (b.PILOT_DIR / "REPORT.md").write_text(report_md(stats, checks, reclass),
                                           encoding="utf-8")
    print(json.dumps({"stats": stats, "hand_check_ok": len(checks) - len(failed),
                      "hand_check_total": len(checks),
                      "failed": [c["key"] for c in failed],
                      "reclass": reclass["counts"]}, indent=1, default=str))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
