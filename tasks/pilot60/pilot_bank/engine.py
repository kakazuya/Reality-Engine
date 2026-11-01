"""Pilot bank rewrite: fills question rules with values read from the stores.

Claude wrote the rules by hand (rules_*.py). A stock gets a question only if every slot and
evidence check for that stock is satisfied by held data known by the row's as_of. Each row keeps
the old text and the evidence it rests on. Read-only on every store.
"""
from __future__ import annotations

import csv
import json
import pickle
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "reality_engine" / "data"
SNAPSHOT = "2026-10-19"
WINDOW_START = "2024-04-01"
TYPE = {"C": "concall", "D": "deck", "A": "annual_report", "N": "results_notes", "X": "announcement"}
LABEL = {"concall": "earnings call", "deck": "investor presentation", "annual_report": "annual report",
         "results_notes": "results notes", "announcement": "filing"}
BUCKET_SUFFIX = {"LARGE": "L", "MID-SMALL": "MS", "MICRO": "MI"}
NAMES = {  # short names used in question text; each checked by hand against master_companies
    "BOSCHLTD": "Bosch", "PIDILITIND": "Pidilite Industries", "GRASIM": "Grasim Industries",
    "HINDUNILVR": "Hindustan Unilever", "BAJFINANCE": "Bajaj Finance", "SUNPHARMA": "Sun Pharma",
    "HINDALCO": "Hindalco", "POWERGRID": "Power Grid", "DLF": "DLF", "IDEA": "Vodafone Idea",
    "TMPV": "Tata Motors Passenger Vehicles", "APLAPOLLO": "APL Apollo Tubes", "ANURAS": "Anupam Rasayan",
    "KEC": "KEC International", "DALBHARAT": "Dalmia Bharat", "KALYANKJIL": "Kalyan Jewellers",
    "INDHOTEL": "Indian Hotels", "UBL": "United Breweries", "ANANDRATHI": "Anand Rathi Wealth",
    "EDELWEISS": "Edelweiss Financial Services", "ALKEM": "Alkem Laboratories", "TATAELXSI": "Tata Elxsi",
    "SAIL": "SAIL", "HINDPETRO": "HPCL", "NLCINDIA": "NLC India", "PRESTIGE": "Prestige Estates",
    "GMRAIRPORT": "GMR Airports", "TEJASNET": "Tejas Networks", "WELSPUNLIV": "Welspun Living",
    "STLTECH": "Sterlite Technologies", "HEGAM": "HEG", "JUBLINGREA": "Jubilant Ingrevia",
    "DDEVPLSTIK": "D&D Plastics", "DOLLAR": "Dollar Industries", "HINDOILEXP": "Hindustan Oil Exploration",
    "ASHIANA": "Ashiana Housing", "BIGBLOC": "BigBloc Construction", "ASHOKA": "Ashoka Buildcon",
    "UFLEX": "Uflex", "WPIL": "WPIL", "AURUM": "Aurum PropTech", "ATGL": "Adani Total Gas",
    "ASAHISONG": "Asahi Songwon Colors", "SPECIALITY": "Speciality Restaurants", "AGVENTURES": "AG Ventures",
    "BMW": "BMW Ventures", "UFBL": "United Foodbrands", "URAVIDEF": "Urav Defence", "ESAFSFB": "ESAF Small Finance Bank",
    "KHADIM": "Khadim India", "HMVL": "HT Media Venture", "COMPINFO": "Compuage Infocom", "DHARAN": "Dharan Infra",
    "TIRUPATIFL": "Tirupati Forge", "RAJESHEXPO": "Rajesh Exports", "UNIVASTU": "Univastu India",
    "IMPEXFERRO": "Impex Ferro Tech", "VIKASWSP": "Vikas WSP", "SIMBHALS": "Simbhaoli Sugars", "PANACHE": "Panache Digilife",
}
EXTRA_SYM = {"INE070C01037": "COMPINFO", "INE278R01034": "DHARAN", "INE319Y01024": "TIRUPATIFL", "INE343B01030": "RAJESHEXPO",
             "INE562X01013": "UNIVASTU", "INE691G01015": "IMPEXFERRO", "INE706A01022": "VIKASWSP", "INE748T01016": "SIMBHALS",
             "INE895W01019": "PANACHE"}


def ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    return con


class Store:
    def __init__(self):
        self.eq = ro(DATA / "equity_intelligence.db")
        self.ch = ro(DATA / "pilot" / "pilot60" / "chunks_v3_pilot.db")
        self.xb = ro(DATA / "results_xbrl.db")
        self.ann_db = ro(DATA / "bse_announcements.db")
        self.ms = ro(DATA / "pilot" / "pilot60" / "market_state_pilot.db")
        self.sec = ro(DATA / "pilot" / "pilot60" / "sector_pit.db")
        self.u = []
        for r in csv.DictReader(open(ROOT / "tasks/pilot60/UNIVERSE.csv", encoding="utf-8")):
            sym = r["symbol"] or EXTRA_SYM[r["isin"]]
            self.u.append({"isin": r["isin"], "sym": sym, "bucket": r["bucket"], "name": NAMES[sym]})
        self.by_sym = {s["sym"]: s for s in self.u}
        self.by_isin = {s["isin"]: s for s in self.u}
        self._cache_path = ROOT / ".tmp" / "pilot_bank_hits.pkl"
        self._hits = pickle.load(open(self._cache_path, "rb")) if self._cache_path.exists() else {}
        self._ann = {}
        self._px = {}
        self._f = {}

    # ---------- evidence in the held documents
    def hits(self, match: str, types: str, as_of: str) -> dict:
        # event_date can be malformed in a few rows; those chunks give no usable date

        key = (match, types, as_of)
        if key in self._hits:
            return self._hits[key]
        dts = [TYPE[t] for t in types]
        q = (f"SELECT c.isin,c.doc_type,substr(c.event_date,1,10),c.page_from,c.doc_id,c.chunk_id,c.known_at,"
             f"snippet(chunk_fts,1,'','',' .. ',24) FROM chunk_fts JOIN chunk c ON c.chunk_id=chunk_fts.rowid "
             f"WHERE chunk_fts MATCH ? AND c.doc_type IN ({','.join('?' * len(dts))}) AND substr(c.known_at,1,10)<=? "
             f"AND c.char_len>=200 ORDER BY c.event_date DESC")
        out = defaultdict(lambda: [0, None])
        for r in self.ch.execute(q, ["{body}: (" + match + ")"] + dts + [as_of]):
            if r[0] not in self.by_isin:
                continue
            out[r[0]][0] += 1
            if out[r[0]][1] is None:
                out[r[0]][1] = {"doc_type": r[1], "date": r[2], "page": r[3], "doc_id": r[4], "chunk_id": r[5],
                                "known_at": r[6], "snippet": " ".join(r[7].split())[:220]}
        self._hits[key] = dict(out)
        if len(self._hits) % 25 == 0:
            self.save()
        return self._hits[key]

    def save(self):
        pickle.dump(self._hits, open(self._cache_path, "wb"))

    def ann(self, isin: str, regex: str, as_of: str):
        """Latest announcement whose headline or subject matches; returns date, time, headline."""
        if isin not in self._ann:
            sym = self.by_isin[isin]["sym"]
            codes = self.eq.execute("SELECT bse_code FROM master_companies WHERE isin=?", (isin,)).fetchone()
            code = codes[0] if codes else None
            self._ann[isin] = self.ann_db.execute(
                "SELECT DissemDT,NEWS_DT,HEADLINE,NEWSSUB,CATEGORYNAME,NEWSID FROM ann WHERE SCRIP_CD=? OR symbol=? ORDER BY NEWS_DT DESC",
                (code, sym)).fetchall()
        rows = self._ann[isin]
        rx = re.compile(regex, re.I)
        for d1, d2, h, s, c, nid in rows:
            when = str(d1 or d2 or "")[:19].replace("T", " ")
            if when and WINDOW_START <= when[:10] <= as_of and rx.search(f"{h or ''} {s or ''}"):
                return {"date": when[:10], "time": when[11:16], "headline": " ".join((h or s or "").split())[:160],
                        "source": f"bse_announcements.ann NEWSID={nid}"}
        return None

    def chunk_ref(self, chunk_id: int):
        """The document a verified quote came from: its type, date, page and known time."""
        r = self.ch.execute("SELECT doc_type,substr(event_date,1,10),page_from,doc_id,known_at FROM chunk WHERE chunk_id=?", (chunk_id,)).fetchone()
        if not r:
            return None
        return {"doc_type": r[0], "date": r[1], "page": r[2], "doc_id": r[3], "known_at": r[4], "chunk_id": chunk_id}

    # ---------- prices
    def px(self, isin: str) -> list:
        if isin not in self._px:
            # NSE in every series (a name moved to BE/BZ keeps trading), then BSE where NSE has no session
            nse = self.eq.execute(
                "SELECT date,open,high,low,close,total_volume,delivery_pct,series FROM daily_price_delivery WHERE isin=? AND date<=? "
                "ORDER BY date, series='EQ'", (isin, SNAPSHOT)).fetchall()
            by = {r[0]: r[:7] for r in nse}
            for r in self.eq.execute("SELECT date,open,high,low,close,volume,NULL FROM mkt_bse_eq_daily WHERE isin=? AND date<=? ORDER BY date",
                                     (isin, SNAPSHOT)):
                by.setdefault(r[0], r)
            rows = [by[d] for d in sorted(by)]
            self._px[isin] = [r for r in rows if r[4]]
        return self._px[isin]

    def actions(self, isin: str) -> list:
        return self.eq.execute(
            "SELECT ex_date,action_type,subject FROM corporate_actions WHERE isin=? AND ex_date<=? "
            "AND action_type IN ('SPLIT','BONUS','DEMERGER','RIGHTS') ORDER BY ex_date", (isin, SNAPSHOT)).fetchall()

    def facts(self, isin: str) -> dict:
        if isin in self._f:
            return self._f[isin]
        s = self.by_isin[isin]
        f = {"name": s["name"], "sym": s["sym"], "isin": isin}
        rows = self.px(isin)
        acts = self.actions(isin)
        ex = {a[0] for a in acts}
        moves = []
        for a, b in zip(rows, rows[1:]):
            # adjacent sessions only: a gap in the series is not a one-day move
            if b[0] >= WINDOW_START and a[4] and days_between(a[0], b[0]) <= 5:
                moves.append((b[0], (b[4] / a[4] - 1) * 100))
        # 25%+ in one session with no held action is a data or demerger artefact (HEG 22 Sep 2026), never a premise
        clean = [m for m in moves if m[0] not in ex and abs(m[1]) < 25]
        if clean:
            d, p = min(clean, key=lambda m: m[1])
            if p <= -3:
                f["fall_date"], f["fall_pct"] = fmt_date(d), f"{-p:.2f}"
                f["fall_iso"] = d
            d, p = max(clean, key=lambda m: m[1])
            if p >= 3:
                f["rise_date"], f["rise_pct"] = fmt_date(d), f"{p:.2f}"
                f["rise_iso"] = d
        if rows:
            f["last_date"] = fmt_date(rows[-1][0])
            f["last_iso"] = rows[-1][0]
            f["first_iso"] = rows[0][0]
            f["prev_date"] = fmt_date(rows[-2][0]) if len(rows) > 1 else None
            # two adjacent sessions a month before the end, used for delivery questions
            for i in range(len(rows) - 21, 1, -1):
                if days_between(rows[i][0], rows[i + 1][0]) <= 4:
                    f["d1_date"], f["d2_date"] = fmt_date(rows[i][0]), fmt_date(rows[i + 1][0])
                    break
        # the price file starts 2019 on BSE, so only a later first session is evidence of a listing
        if rows and rows[0][0] > "2019-06-30":
            f["list_date"] = fmt_date(rows[0][0])
        if rows and rows[0][0] <= "2023-10-01" and rows[-1][0] >= "2026-09-01":
            f["has3y"] = "yes"
        if acts:
            a = acts[-1]
            # only an action inside the held price history can be studied
            if rows and rows[0][0] < a[0] <= rows[-1][0]:
                f["ca_date"], f["ca_type"] = fmt_date(a[0]), {"RIGHTS": "rights issue"}.get(a[1], a[1].lower())
        for dt, slot in (("concall", "call"), ("deck", "deck"), ("annual_report", "ar"), ("results_notes", "notes")):
            r = self.ch.execute(
                "SELECT substr(d.event_date,1,10),d.fiscal_period,d.page_count FROM doc d WHERE d.isin=? AND d.doc_type=? AND "
                "d.event_date GLOB '20[0-9][0-9]-*' AND substr(d.known_at,1,10)<=? AND d.char_count>=2000 ORDER BY d.event_date DESC LIMIT 1", (isin, dt, SNAPSHOT)).fetchone()
            if r and re.fullmatch(r"\d{4}-\d{2}-\d{2}", r[0] or ""):
                f[slot + "_date"] = fmt_date(r[0])
                f[slot + "_fy"] = r[1]
                f[slot + "_pages"] = r[2]
        r = self.xb.execute(
            "SELECT reporting_quarter,period_end,COALESCE(dissem_ts,broadcast_ts,filing_ts),audit_opinion FROM filings WHERE isin=? "
            "AND period_end<=? AND COALESCE(dissem_ts,broadcast_ts,filing_ts) IS NOT NULL ORDER BY period_end DESC, "
            "consolidated DESC LIMIT 1", (isin, SNAPSHOT)).fetchone()
        if r and str(r[2])[:10] <= SNAPSHOT:
            when = normal_ts(str(r[2]))
            # only a recent quarter can be asked as "the latest"; an old filing is not a current question
            if when and when[:10] >= "2026-01-01":
                f["res_iso"] = when[:10]
                f["res_date"], f["res_time"] = fmt_date(when[:10]), when[11:16]
                f["res_q"] = quarter(r[1])
                day0 = when[:10] if when[11:16] and when[11:16] < "15:30" else None
                dates = [x[0] for x in rows]
                nxt = next((d for d in dates if (d >= when[:10] if day0 else d > when[:10])), None)
                if nxt:
                    i = dates.index(nxt)
                    if i:
                        f["react_date"] = fmt_date(nxt)
                        f["react_pct"] = f"{(rows[i][4] / rows[i - 1][4] - 1) * 100:+.2f}"
        sec = self.sec.execute("SELECT sector,industry,basic_industry FROM company_sector_pit WHERE isin=? ORDER BY valid_from DESC LIMIT 1",
                               (isin,)).fetchone()
        if sec:
            f["sector"], f["industry"], f["basic_industry"] = sec
        deals = self.eq.execute("SELECT deal_date,COUNT(*) FROM bulk_block_deals WHERE (isin=? OR symbol=?) AND deal_date<=? "
                                "GROUP BY deal_date ORDER BY deal_date DESC LIMIT 1", (isin, s["sym"], SNAPSHOT)).fetchone()
        if deals:
            f["bulk_date"] = fmt_date(deals[0])
        note = self.ch.execute("SELECT period_end FROM result_note WHERE isin=? AND note_no IN ('5','5.') AND substr(known_at,1,10)<=? "
                               "ORDER BY period_end DESC LIMIT 1", (isin, SNAPSHOT)).fetchone()
        if note:
            f["note5_q"] = quarter(note[0])
        shp = self.eq.execute("SELECT COUNT(*) FROM shp_index WHERE isin=?", (isin,)).fetchone()
        if shp and shp[0]:
            f["shp"] = "yes"
        self._f[isin] = f
        return f


def days_between(a: str, b: str) -> int:
    from datetime import date
    return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days


def normal_ts(t: str):
    t = t.strip().replace("T", " ")
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ ](\d{2}:\d{2})", t)
    if m:
        return f"{m[1]} {m[2]}"
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4}) (\d{2}:\d{2})", t)
    if m:
        mon = "JanFebMarAprMayJunJulAugSepOctNovDec".index(m[2].title()) // 3 + 1
        return f"{m[3]}-{mon:02d}-{m[1]} {m[4]}"
    return None


def fmt_date(iso: str) -> str:
    y, m, d = iso[:10].split("-")
    return f"{int(d)} {'January February March April May June July August September October November December'.split()[int(m) - 1]} {y}"


def quarter(period_end: str) -> str:
    y, m = int(period_end[:4]), int(period_end[5:7])
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(m, 0)
    return f"Q{q}FY{(y + 1 if m > 3 else y) % 100:02d}"


SLOT = re.compile(r"\{(\??)(\w+)\}")  # {x} prints a held value; {?x} only requires it


def fill(tpl: str, f: dict, ev: dict | None):
    """Return the text, or None when a slot has no held value."""
    vals = dict(f)
    if ev:
        d = ev.get("date") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", ev.get("date") or "") else (ev.get("known_at") or "")[:10]
        vals.update(ev_date=fmt_date(d) if d else None, ev_page=ev.get("page"),
                    ev_doc=LABEL.get(ev.get("doc_type")))
    miss = [k for _, k in SLOT.findall(tpl) if vals.get(k) in (None, "")]
    if miss:
        return None
    return SLOT.sub(lambda m: "" if m[1] else str(vals[m[2]]), tpl)


MONTHS = "January February March April May June July August September October November December".split()
NAMED_DATE = re.compile(r"\b(\d{1,2}) (" + "|".join(MONTHS) + r") (\d{4})\b")


def dates_have_sessions(text: str, sessions: list) -> bool:
    """Every date a stock question names must have a session of that stock within 5 days."""
    from datetime import date
    days = [date.fromisoformat(d) for d in sessions]
    for d, m, y in NAMED_DATE.findall(text):
        want = date(int(y), MONTHS.index(m) + 1, int(d))
        if not any(abs((x - want).days) <= 5 for x in days):
            return False
    return True


def json_dump(path: Path, rows: list):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
