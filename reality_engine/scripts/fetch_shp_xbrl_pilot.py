"""Pilot-60 shareholding XBRL -> the ownership atoms v4 is missing (§A.1, §A.2).

`equity_intelligence.shp_index` lists every NSE shareholding filing with its XBRL link,
but only promoter/public were ever lifted out of it, so `hold.pct` has no fii/dii/mf
class and `hold.pledge_pct` is empty (`build_membership.ATOM_NOTES`).  This module
fetches the pilot names' filings and parses the XBRL into the long `fact` shape the v4
view uses, without touching the live stores:

    .tmp/shp_xbrl_raw/<file>.xml.gz     gzipped XBRL, resumable (the layout
                                        `raw_market/nse_shp_xbrl/` already uses)
    .tmp/shp_xbrl_pilot.db              filings + fact + xcheck (see DDL below)

    python -m reality_engine.scripts.fetch_shp_xbrl_pilot            # fetch, parse, report
    python -m reality_engine.scripts.fetch_shp_xbrl_pilot --fetch
    python -m reality_engine.scripts.fetch_shp_xbrl_pilot --parse
    python -m reality_engine.scripts.fetch_shp_xbrl_pilot --report

Scope: the 60 ISINs of `tasks/pilot60/UNIVERSE.csv` (or any isin,symbol CSV given with
`--universe`, e.g. a new pilot set), filings as-on 2024-04-01 or later.
A filing is matched on its ISIN *or* on its symbol through `symbol_isin_history`, because
many filings still carry the pre-split ISIN (STLTECH files INE089C01011, the pilot holds
INE089C01029).

Atoms written (`dims` carries the class, exactly as fact_view.sql writes them):

    hold.pct        holder_class=fii | dii | mf | insurance     %
    hold.pledge_pct holder_class=promoter                        %

promoter and public are parsed too, but they are a cross-check against `shp_index`, not
new facts (table `xcheck`), because `shp_index` already carries those two columns.

Reported zero vs missing: a class whose own category context carries the percentage fact
is *reported* -- value 0.0 included.  A class with no such fact gets no row and is listed
in `filings.classes_missing`; nothing is imputed.  `hold.pledge_pct` is written from the
pledge percentage concept, or from an explicit "no promoter shares are pledged" boolean
when the filing states that instead of a number.

PIT: `known_at` is `shp_index.broadcast_at`, falling back to `submission_date`; never a
crawl date and never `quarter_end`.  A revised filing is its own set of rows (the key
carries `known_at`), so the original stays usable before the revision.

Both XBRL conventions in the wild are handled; the existing
`fetch_shareholding.run_parse` view only knows one of them (it keys on context ids like
`InstitutionsForeign_ContextI`, while older filings emit `InstitutionsForeignI` and give
percentages instead of fractions).  This parser keys on the context's
`CategoryOfShareholdersAxis` member instead, and reads the scale off the filing's own
100% row.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import os
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("REALITY_DATA_ROOT") or REPO / "reality_engine" / "data")
UNIVERSE_CSV = REPO / "tasks" / "pilot60" / "UNIVERSE.csv"
OUT_DIR = REPO / ".tmp"
RAW_DIR = OUT_DIR / "shp_xbrl_raw"
DB_PATH = OUT_DIR / "shp_xbrl_pilot.db"
REPORT_PATH = OUT_DIR / "shp_xbrl_pilot_report.md"
START = "2024-04-01"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
PACE_SEC = 0.5
TIMEOUT = 90

DDL = """
CREATE TABLE IF NOT EXISTS filings(
    record_id      TEXT PRIMARY KEY,
    isin           TEXT NOT NULL,          -- pilot ISIN (canonical)
    symbol         TEXT,
    filing_isin    TEXT,                   -- ISIN printed inside the XBRL
    period_end     TEXT NOT NULL,          -- the filing's own as-on date
    known_at       TEXT NOT NULL,          -- broadcast_at, else submission_date
    revised        TEXT,
    file           TEXT,                   -- raw file name (nse_shp_xbrl layout)
    url            TEXT,
    shp_promoter   REAL,                   -- shp_index promoter_pct (the cross-check)
    shp_public     REAL,
    bytes          INTEGER,
    fetched_at     TEXT,
    parse_status   TEXT,                   -- ok | ambiguous | no_facts | scale_unknown | error
    scale          TEXT,                   -- fraction | percent
    classes_reported TEXT,                 -- comma list, "class=value" (a 0 here is reported)
    classes_missing TEXT,                  -- comma list; never imputed to 0
    pledge_basis   TEXT,                   -- numeric | boolean_false | flag_true_no_value
    n_atoms        INTEGER,
    note           TEXT,
    parsed_at      TEXT
);
CREATE TABLE IF NOT EXISTS fact(
    entity_id  TEXT NOT NULL,
    atom       TEXT NOT NULL,
    dims       TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT NOT NULL,
    value      REAL NOT NULL,
    unit       TEXT NOT NULL,
    known_at   TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    record_id  TEXT NOT NULL,
    PRIMARY KEY (entity_id, atom, dims, period_end, known_at)
);
CREATE TABLE IF NOT EXISTS xcheck(
    record_id  TEXT PRIMARY KEY,
    isin       TEXT, period_end TEXT, known_at TEXT, revised TEXT,
    promoter_xbrl REAL, promoter_shp REAL,
    public_xbrl REAL, public_shp REAL,
    promoter_delta REAL, public_delta REAL,
    match      INTEGER,                    -- 1 when both classes agree within TOL
    note       TEXT
);
"""

#: the six classes parsed out of a filing, in the filing's own order
CLASSES = ("promoter", "public", "fii", "dii", "mf", "insurance")
#: category member -> holder class; compared lowercased without the trailing "Member"
MEMBERS = {
    "shareholdingofpromoterandpromotergroup": "promoter",
    "publicshareholding": "public",
    "institutionsforeign": "fii",
    "institutionsdomestic": "dii",
    "mutualfundsoruti": "mf",
    "insurancecompanies": "insurance",
}
PCT = "ShareholdingAsAPercentageOfTotalNumberOfShares"
PLEDGE_PCT = ("EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares",
              "PledgedOrEncumberedSharesHeldAsPercentageOfTotalNumberOfShares")
PLEDGE_FLAG = ("WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged",
               "WhetherAnySharesHeldByPromotersArePledgeOrOtherwiseEncumbered")
CTX = re.compile(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', re.S)
MEMBER = re.compile(r'<xbrldi:explicitMember[^>]*dimension="([^"]+)"\s*>([^<]+)<')
FACT = re.compile(r'<in-bse-shp:([A-Za-z0-9\-]+)\s+contextRef="([^"]+)"[^>]*>([^<]*)<')
#: facts that say which company/period the file covers
IDENT = ("ISIN", "Symbol", "DateOfReport")
TOL = 0.05


# ---------------------------------------------------------------------------- parse
def _member_key(dims: dict[str, str]) -> str | None:
    """The context's `CategoryOfShareholdersAxis` member, lowercased without "Member"."""
    raw = dims.get("CategoryOfShareholdersAxis")
    return raw[:-6].lower() if raw and raw.endswith("Member") else None


def _member(dims: dict[str, str]) -> str | None:
    """The holder class a context's category member names, or None for other rows."""
    return MEMBERS.get(_member_key(dims) or "")


def _num(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def parse_shp_xml(text: str) -> dict:
    """One filing's XBRL -> the parsed measure.  Pure: no I/O, no globals.

    Returns ``{"status", "scale", "classes", "missing", "pledge", "pledge_basis",
    "isin", "symbol", "period_end"}`` where ``classes`` maps a holder class to its
    percentage of total shares (a reported 0.0 stays a value) and ``missing`` lists the
    classes the filing does not report at all.
    """
    ctx = {cid: body for cid, body in CTX.findall(text)}
    facts: dict[str, dict[str, str]] = {}
    for concept, cid, value in FACT.findall(text):
        facts.setdefault(cid, {}).setdefault(concept, value.strip())
    if not facts:
        return {"status": "no_facts"}
    dims = {cid: {d.rsplit(":", 1)[-1].strip(): v.rsplit(":", 1)[-1].strip()
                  for d, v in MEMBER.findall(body)}
            for cid, body in ctx.items()}

    # scale: the filing's own 100% row, else promoter+public, else the largest category
    factors = [f for f in (_num(facts[c][PCT]) for c, d in dims.items()
                           if _member_key(d) == "shareholdingpattern"
                           and PCT in facts.get(c, {})) if f is not None]
    if not factors:
        by_class = {c: _num(facts[cid][PCT]) for cid, d in dims.items()
                    for c in [_member(d)] if c in ("promoter", "public")
                    and PCT in facts.get(cid, {})}
        small = [v for v in by_class.values() if v is not None]
        if "promoter" in by_class and "public" in by_class:
            factors = [sum(v for v in small if v is not None)]
        else:
            factors = small
        if len(factors) == 1:                       # promoter alone: its own value
            factors = [max(factors)]
    total = max(factors) if factors else None
    if total is None:
        return {"status": "scale_unknown"}
    if total <= 1.5:
        factor = 100.0
    elif total >= 50.0:
        factor = 1.0
    else:
        return {"status": "scale_unknown", "total": total}

    classes, ambiguous = {}, []
    for cls in CLASSES:
        hits = []
        for cid, d in dims.items():
            if _member(d) != cls:
                continue
            value = _num(facts.get(cid, {}).get(PCT))
            if value is not None:
                hits.append((value * factor, len(d)))
        if not hits:
            continue
        if len({round(v, 4) for v, _n in hits}) > 1:
            ambiguous.append(cls)
            hits = [h for h in hits if h[1] == 1] or hits      # prefer the summary row
        classes[cls] = round(max(hits, key=lambda h: h[1])[0], 4)

    pledge, basis = None, None
    promoter_ctx = [c for c, d in dims.items() if _member(d) == "promoter"]
    for concept in PLEDGE_PCT:
        for cid in promoter_ctx:
            value = _num(facts.get(cid, {}).get(concept))
            if value is not None:
                pledge, basis = round(value * factor, 4), "numeric"
                break
        if pledge is not None:
            break
    if pledge is None:
        flags = [facts[c][k] for c in facts for k in PLEDGE_FLAG if k in facts[c]]
        if flags and all(str(f).lower() in ("false", "0", "no") for f in flags):
            pledge, basis = 0.0, "boolean_false"     # the filing states there is none
        elif flags:
            basis = "flag_true_no_value"             # says yes, gives no number: no row

    ident = {k: v for c in facts for k, v in facts[c].items() if k in IDENT}
    return {"status": "ambiguous" if ambiguous else "ok",
            "scale": "fraction" if factor == 100.0 else "percent",
            "classes": classes,
            "missing": [c for c in CLASSES if c not in classes],
            "ambiguous": ambiguous,
            "pledge": pledge, "pledge_basis": basis,
            "isin": ident.get("ISIN"), "symbol": ident.get("Symbol"),
            "period_end": ident.get("DateOfReport")}


# -------------------------------------------------------------------------- universe
def pilot_universe() -> list[tuple[str, str]]:
    with open(UNIVERSE_CSV, newline="", encoding="utf-8-sig") as fh:
        return [(r["isin"].strip(), (r["symbol"] or "").strip()) for r in csv.DictReader(fh)]


def connect_ro(path: Path) -> sqlite3.Connection:
    from reality_engine.db.readonly import connect_ro as _ro
    return _ro(path, timeout_s=120)


def filings_to_fetch(con_ei: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    """``(fetchable, unusable)`` shp_index filings of a pilot name, as-on ``START``+.

    Matched on the pilot ISIN or on the filing symbol mapped back through
    ``symbol_isin_history`` (older filings carry a pre-split ISIN).  A row with no
    XBRL link or no ``broadcast_at``/``submission_date`` cannot be fetched and cannot
    be stamped point-in-time; it is returned in ``unusable`` with the reason instead of
    being dropped, so the coverage table can show it as a gap.
    """
    pilots = pilot_universe()
    isins = [i for i, _s in pilots]
    ph = ",".join("?" * len(isins))
    sym2isin = {}
    for isin, symbol in con_ei.execute(
            f"SELECT isin, upper(symbol) FROM symbol_isin_history "
            f"WHERE exchange='NSE' AND isin IN ({ph})", isins):
        sym2isin.setdefault(symbol, isin)
    for isin, symbol in pilots:                       # the CSV symbol is authoritative too
        if symbol:
            sym2isin.setdefault(symbol.upper(), isin)
    sh = ",".join("?" * len(sym2isin))
    rows = con_ei.execute(
        f"""SELECT record_id, symbol, isin, quarter_end, broadcast_at, submission_date,
                   promoter_pct, public_pct, revised, xbrl, file
            FROM shp_index
            WHERE quarter_end >= ? AND (isin IN ({ph}) OR upper(symbol) IN ({sh}))
            ORDER BY quarter_end, broadcast_at""",
        [START, *isins, *sym2isin]).fetchall()
    out, unusable = [], []
    for (rid, symbol, isin, period_end, broadcast, submitted, promoter, public,
         revised, url, file) in rows:
        known_at = broadcast or submitted
        pilot_isin = isin if isin in isins else sym2isin.get((symbol or "").upper(), isin)
        if not known_at or not (url or "").startswith("http"):
            why = []
            if not (url or "").startswith("http"):
                why.append("no XBRL link in shp_index")
            if not known_at:
                why.append("no broadcast_at/submission_date")
            unusable.append({"record_id": str(rid), "isin": pilot_isin, "symbol": symbol,
                             "filing_isin": isin, "period_end": period_end,
                             "why": "; ".join(why)})
            continue
        out.append({"record_id": str(rid), "isin": pilot_isin,
                    "symbol": symbol, "filing_isin": isin, "period_end": period_end,
                    "known_at": known_at, "revised": revised, "url": url,
                    "file": file or url.rsplit("/", 1)[-1],
                    "promoter_pct": promoter, "public_pct": public})
    return out, unusable


# ---------------------------------------------------------------------------- fetch
def _valid(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 256:
        return False
    try:
        body = gzip.decompress(path.read_bytes())
    except (OSError, EOFError):
        return False
    return body.lstrip()[:1] == b"<" and b"</" in body[-4096:]


def fetch(rows: list[dict], con: sqlite3.Connection, limit: int = 0,
          pace: float = PACE_SEC) -> dict:
    raw_dir = RAW_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    have = {r["record_id"] for r in rows if _valid(raw_dir / (r["file"] + ".gz"))}
    todo = [r for r in rows if r["record_id"] not in have]
    todo = todo[:limit] if limit else todo
    done = failed = 0
    started = time.time()
    for n, r in enumerate(todo, 1):
        path = raw_dir / (r["file"] + ".gz")
        try:
            req = urllib.request.Request(
                r["url"], headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/"})
            body = urllib.request.urlopen(req, timeout=TIMEOUT).read()
            if body.lstrip()[:1] != b"<":
                raise ValueError(f"not xml: {body[:40]!r}")
            path.write_bytes(gzip.compress(body))
            con.execute("UPDATE filings SET bytes=?, fetched_at=?, note=NULL WHERE record_id=?",
                        (len(body), _now(), r["record_id"]))
            done += 1
        except Exception as exc:                       # noqa: BLE001 - recorded, retried next run
            failed += 1
            con.execute("UPDATE filings SET note=? WHERE record_id=?",
                        (f"fetch failed: {type(exc).__name__}: {exc}"[:300], r["record_id"]))
        if n % 50 == 0:
            con.commit()
            print(f"fetched {n}/{len(todo)} ok {done} failed {failed} "
                  f"{(time.time() - started) / n:.2f} s/file", flush=True)
        time.sleep(pace)
    con.commit()
    elapsed = time.time() - started
    return {"todo": len(todo), "already": len(have), "fetched": done, "failed": failed,
            "seconds": round(elapsed, 1),
            "seconds_per_file": round(elapsed / len(todo), 3) if todo else 0.0}


# ---------------------------------------------------------------------------- parse
def parse(con: sqlite3.Connection, limit: int = 0) -> dict:
    todo = con.execute(
        "SELECT record_id, isin, period_end, known_at, revised, file "
        "FROM filings WHERE parse_status IS NULL OR parse_status='error' "
        "ORDER BY period_end").fetchall()
    todo = todo[:limit] if limit else todo
    counts: dict[str, int] = {}
    for n, (rid, isin, period_end, known_at, revised, file) in enumerate(todo, 1):
        path = RAW_DIR / (file + ".gz")
        if not _valid(path):
            prev = con.execute("SELECT note FROM filings WHERE record_id=?",
                               (rid,)).fetchone()
            why = "raw file missing or truncated"
            _record(con, rid, "error",
                    note=why + (f"; fetch said: {prev[0]}" if prev and prev[0] else ""))
            counts["error"] = counts.get("error", 0) + 1
            continue
        try:
            got = parse_shp_xml(gzip.decompress(path.read_bytes()).decode("utf-8", "replace"))
        except Exception as exc:                       # noqa: BLE001 - recorded, not hidden
            _record(con, rid, "error", note=f"{type(exc).__name__}: {exc}"[:300])
            counts["error"] = counts.get("error", 0) + 1
            continue
        status = got["status"]
        counts[status] = counts.get(status, 0) + 1
        if status in ("no_facts", "scale_unknown"):
            _record(con, rid, status)
            con.commit()
            continue
        classes = got["classes"]
        ref = f"shp_xbrl:{file}"
        atoms = [(isin, "hold.pct", f"holder_class={cls}", period_end, period_end,
                  value, "%", known_at, ref, rid)
                 for cls, value in classes.items() if cls in ("fii", "dii", "mf", "insurance")]
        if got["pledge"] is not None:
            atoms.append((isin, "hold.pledge_pct", "holder_class=promoter", period_end,
                          period_end, got["pledge"], "%", known_at, ref, rid))
        con.executemany(
            "INSERT OR REPLACE INTO fact(entity_id, atom, dims, period_start, period_end,"
            " value, unit, known_at, source_ref, record_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            atoms)
        _record(con, rid, status, scale=got["scale"],
                classes_reported=",".join(f"{c}={v:g}" for c, v in classes.items()),
                classes_missing=",".join(got["missing"]), n_atoms=len(atoms),
                pledge_basis=got["pledge_basis"],
                note=("ambiguous class: " + ",".join(got["ambiguous"])
                      if got["ambiguous"] else None))
        _xcheck(con, rid, isin, period_end, known_at, revised, classes)
        con.commit()
        if n % 100 == 0:
            print(f"parsed {n}/{len(todo)} {counts}", flush=True)
    con.commit()
    return counts


def _record(con: sqlite3.Connection, rid: str, status: str, **kw) -> None:
    cols = {"parse_status": status, "parsed_at": _now()}
    cols.update({k: v for k, v in kw.items() if v is not None})
    con.execute(f"UPDATE filings SET {', '.join(f'{k}=?' for k in cols)} WHERE record_id=?",
                [*cols.values(), rid])


def _xcheck(con, rid, isin, period_end, known_at, revised, classes) -> None:
    """Promoter/public from the XBRL against the shp_index columns (report only).

    ``match`` is 1 only when both sides carry the class and agree within ``TOL``, 0 when
    both carry it and differ, NULL when one side has no value -- the brief compares rows
    "where both exist", and a filing may legitimately omit a category (a company with no
    promoter group files no promoter context) while ``shp_index`` stores 0 for it.
    """
    row = con.execute("SELECT shp_promoter, shp_public FROM filings WHERE record_id=?",
                      (rid,)).fetchone()
    if not row:
        return
    pairs = {"promoter": (classes.get("promoter"), row[0]),
             "public": (classes.get("public"), row[1])}
    delta = {c: round(x - s, 4) for c, (x, s) in pairs.items()
             if x is not None and s is not None}
    differing = [c for c, d in delta.items() if abs(d) > TOL]
    one_sided = [c for c, (x, s) in pairs.items() if (x is None) != (s is None)]
    if differing:
        match, note = 0, "differ beyond tolerance: " + ",".join(differing)
    elif one_sided:
        match, note = None, "not compared, one side absent: " + ",".join(one_sided)
    elif delta:
        match, note = 1, None
    else:
        match, note = None, "not compared, no value on either side"
    con.execute(
        "INSERT OR REPLACE INTO xcheck VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, isin, period_end, known_at, revised, pairs["promoter"][0], pairs["promoter"][1],
         pairs["public"][0], pairs["public"][1], delta.get("promoter"),
         delta.get("public"), match, note))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ----------------------------------------------------------------------------- db
def open_db() -> sqlite3.Connection:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=120)
    con.executescript(DDL)
    return con


def seed(con: sqlite3.Connection, rows: list[dict]) -> int:
    """Upsert the filing index (with the shp_index promoter/public for the cross-check)."""
    con.executemany(
        "INSERT INTO filings(record_id, isin, symbol, filing_isin, period_end, known_at,"
        " revised, file, url, shp_promoter, shp_public) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(record_id) DO UPDATE SET isin=excluded.isin, symbol=excluded.symbol,"
        " filing_isin=excluded.filing_isin, period_end=excluded.period_end,"
        " known_at=excluded.known_at, revised=excluded.revised, url=excluded.url,"
        " shp_promoter=excluded.shp_promoter, shp_public=excluded.shp_public",
        [(r["record_id"], r["isin"], r["symbol"], r["filing_isin"], r["period_end"],
          r["known_at"], r["revised"], r["file"], r["url"], r["promoter_pct"],
          r["public_pct"]) for r in rows])
    con.commit()
    return len(rows)


# -------------------------------------------------------------------------- report
def report(con: sqlite3.Connection, unusable: list[dict] | None = None) -> str:
    pilots = pilot_universe()
    raw = {p.name[:-3] for p in RAW_DIR.glob("*.gz")} if RAW_DIR.exists() else set()
    per: dict[str, list] = {}
    for (isin, rid, period_end, status, file) in con.execute(
            "SELECT isin, record_id, period_end, parse_status, file FROM filings"):
        row = per.setdefault(isin, [0, 0, 0, ""])
        row[0] += 1
        row[1] += (file or "") in raw
        row[2] += status in ("ok", "ambiguous")
        row[3] = max(row[3], period_end or "")
    out = ["# Shareholding XBRL for the pilot 60", "",
           f"generated {_now()} · source `equity_intelligence.shp_index` (read-only) · "
           f"filings as-on {START}+", "",
           "## Coverage", "",
           "| # | ISIN | symbol | quarter filings | fetched | parsed | latest quarter | gap |",
           "|---|---|---|---:|---:|---:|---|---|"]
    gaps = 0
    unl_per: dict[str, int] = {}
    for u in unusable or []:
        unl_per[u["isin"]] = unl_per.get(u["isin"], 0) + 1
    for n, (isin, symbol) in enumerate(pilots, 1):
        total, got, ok, latest = per.get(isin, (0, 0, 0, ""))
        n_unl = unl_per.get(isin, 0)
        if not total and not n_unl:
            gaps += 1
            out.append(f"| {n} | {isin} | {symbol} | 0 | 0 | 0 | - | "
                       f"no shp_index filing for this ISIN or symbol since {START} |")
            continue
        gap = ""
        missing = total - ok
        if missing:
            gap = f"{missing} of {total} incomplete"
        if n_unl:
            gap += ("; " if gap else "") + f"{n_unl} no-link row(s)"
        gaps += bool(gap or not total)
        out.append(f"| {n} | {isin} | {symbol} | {total} | {got} | {ok} | "
                   f"{latest or '-'} | {gap} |")
    out += ["", "`quarter filings` = the `shp_index` rows with an XBRL link and a "
            "`known_at` (normally one a quarter; a later listing has fewer, which is not "
            "a gap). `no-link row(s)` cannot be fetched at all and are listed below."]

    out += ["", "## Gap detail (one line per name that is short)", ""]
    any_gap = False
    for isin, symbol in pilots:
        total, got, ok, _latest = per.get(isin, (0, 0, 0, ""))
        n_unl = unl_per.get(isin, 0)
        if total and got == total and ok == total and not n_unl:
            continue
        any_gap = True
        if not total and not n_unl:
            out.append(f"- `{isin}` {symbol or '-'}: no `shp_index` row for this ISIN or "
                       f"symbol on/after {START} — nothing to fetch")
            continue
        for u in [u for u in (unusable or []) if u["isin"] == isin][:6]:
            out.append(f"- `{isin}` {symbol or '-'} {u['record_id']} {u['period_end']}: "
                       f"not fetchable ({u['why']})")
        for rid, period_end, file, status, note in con.execute(
                "SELECT record_id, period_end, file, parse_status, note FROM filings "
                "WHERE isin=? AND (parse_status IS NULL OR parse_status NOT IN "
                "('ok','ambiguous')) ORDER BY period_end LIMIT 6", (isin,)):
            why = []
            if (file or "") not in raw:
                why.append("not downloaded")
            if status is None:
                why.append("not parsed")
            elif status != "ok":
                why.append(f"parse_status={status}")
            if note:
                why.append(note)
            out.append(f"- `{isin}` {symbol or '-'} {rid} {period_end}: "
                       f"{'; '.join(why) or 'no reason recorded'}")
    if not any_gap:
        out.append("- none: every indexed filing was downloaded and parsed")

    tot = con.execute("SELECT COUNT(*), SUM(parse_status IN ('ok','ambiguous')), "
                      "SUM(parse_status='error'), SUM(parse_status IS NULL) "
                      "FROM filings").fetchone()
    dl = sum(1 for (file,) in con.execute("SELECT file FROM filings") if (file or "") in raw)
    out += ["", "## Status", "",
            f"- filings indexed **{tot[0]}** · downloaded **{dl}** · parsed **{tot[1] or 0}** · "
            f"error **{tot[2] or 0}** · pending **{tot[3] or 0}** · "
            f"no-link rows **{len(unusable or [])}** · "
            f"names with a gap **{gaps}/60** · raw files {len(raw)} under `{RAW_DIR}`"]
    for status, n in con.execute("SELECT parse_status, COUNT(*) FROM filings "
                                 "GROUP BY 1 ORDER BY 2 DESC"):
        out.append(f"  - `{status or 'pending'}`: {n}")
    out += ["", "## Atoms", ""]
    for atom, dims, n, names, q0, q1 in con.execute(
            "SELECT atom, dims, COUNT(*), COUNT(DISTINCT entity_id), MIN(period_end), "
            "MAX(period_end) FROM fact GROUP BY atom, dims ORDER BY atom, dims"):
        out.append(f"- `{atom}` `{dims}`: {n} rows, {names} ISINs, {q0}..{q1}")
    out += ["", "### Classes the filing does not report (no row is written)", ""]
    for miss, n in con.execute(
            "SELECT classes_missing, COUNT(*) FROM filings WHERE classes_missing IS NOT NULL "
            "GROUP BY 1 ORDER BY 2 DESC LIMIT 12"):
        out.append(f"- missing `{miss}`: {n} filings")
    for basis, n in con.execute("SELECT pledge_basis, COUNT(*) FROM filings "
                                "WHERE pledge_basis IS NOT NULL GROUP BY 1"):
        out.append(f"- pledge_basis `{basis}`: {n} filings")
    zero = con.execute("SELECT COUNT(*) FROM fact WHERE atom='hold.pct' AND value=0").fetchone()[0]
    out.append(f"- `hold.pct` rows whose reported value is exactly 0: {zero}")

    matched, differ, skipped = con.execute(
        "SELECT SUM(match=1), SUM(match=0), SUM(match IS NULL) FROM xcheck").fetchone()
    out += ["", "## Promoter / public cross-check against shp_index", "",
            f"- {con.execute('SELECT COUNT(*) FROM xcheck').fetchone()[0]} filings parsed · "
            f"both classes present and agree within {TOL} pp: **{matched or 0}** · "
            f"differ: **{differ or 0}** · not compared (a class absent on one side): "
            f"**{skipped or 0}**", ""]
    for r in con.execute("SELECT record_id, isin, period_end, known_at, promoter_xbrl, "
                        "promoter_shp, public_xbrl, public_shp, note FROM xcheck "
                        "WHERE match=0 ORDER BY period_end"):
        out.append(f"  - MISMATCH record {r[0]} {r[1]} {r[2]} (known {r[3]}): promoter "
                   f"{r[4]} vs {r[5]}, public {r[6]} vs {r[7]} ({r[8]})")
    for r in con.execute("SELECT record_id, isin, period_end, promoter_xbrl, promoter_shp, "
                        "public_xbrl, public_shp, note FROM xcheck WHERE match IS NULL "
                        "ORDER BY period_end LIMIT 40"):
        out.append(f"  - not compared record {r[0]} {r[1]} {r[2]}: promoter {r[3]} vs "
                   f"{r[4]}, public {r[5]} vs {r[6]} ({r[7]})")

    rev = con.execute("SELECT COUNT(*) FROM filings WHERE revised IS NOT NULL "
                      "AND revised NOT IN ('N','')").fetchone()[0]
    out += ["", "## Revised filings", "",
            f"- {rev} revised filing(s) kept as their own rows (the fact key carries "
            f"`known_at`, so the original survives)"]
    for r in con.execute(
            "SELECT isin, period_end, COUNT(*), GROUP_CONCAT(known_at) FROM filings "
            "GROUP BY isin, period_end HAVING COUNT(*) > 1 ORDER BY period_end"):
        out.append(f"  - {r[0]} {r[1]}: {r[2]} filings known {r[3]}")

    out += ["", "## Artifacts", "",
            f"- raw XBRL, resumable (controller moves to `D:\\RealityEngine\\raw`): "
            f"`{RAW_DIR}` — {len(raw)} gzipped filings",
            f"- parsed pilot store: `{DB_PATH}`",
            "- independent re-read of the seed rows: "
            "`python -m reality_engine.scripts.verify_shp_xbrl_seed`",
            "- tests: `python -m pytest reality_engine/tests/test_v4_shp_xbrl.py -q`"]
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------------------- cli
def main() -> None:
    global RAW_DIR, DB_PATH, UNIVERSE_CSV
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--parse", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pace", type=float, default=PACE_SEC, help="seconds between downloads")
    ap.add_argument("--raw", default=str(RAW_DIR))
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--universe", default=str(UNIVERSE_CSV),
                    help="CSV with isin,symbol columns (default: the pilot60 universe)")
    args = ap.parse_args()
    RAW_DIR, DB_PATH, UNIVERSE_CSV = Path(args.raw), Path(args.db), Path(args.universe)
    all_steps = not (args.fetch or args.parse or args.report)
    con = open_db()
    fetchable: list[dict] = []
    unusable: list[dict] = []
    if args.fetch or args.report or all_steps:
        fetchable, unusable = filings_to_fetch(connect_ro(DATA / "equity_intelligence.db"))
    if args.fetch or all_steps:
        print(f"pilot filings {START}+: {len(fetchable)} fetchable, "
              f"{len(unusable)} with no XBRL link or known_at")
        seed(con, fetchable)
        print("fetch:", fetch(fetchable, con, args.limit, args.pace))
    if args.parse or all_steps:
        print("parse:", parse(con, args.limit))
    if args.report or all_steps:
        text = report(con, unusable)
        REPORT_PATH.write_text(text, encoding="utf-8")
        print(text)
        print(f"report -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
