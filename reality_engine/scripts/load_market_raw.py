"""
Load raw market files (from fetch_market_raw.py / fetch_nse_api_raw.py) into the DB.

Every source lands in its own ``mkt_*`` table exactly as published, with no
foreign key to ``master_companies``: delisted names, old ISINs, SME and BSE-only
scrips are all kept. Joining to the ISIN anchor, split/bonus adjustment and
building a clean price series are separate, later steps. Existing tables are
never overwritten; the one exception is ``corporate_actions``, which only gets
new rows (INSERT OR IGNORE on its unique key).

Tables:
  mkt_nse_eq_daily        NSE CM bhavcopy + MTO delivery (2019-01 .. 2021-10)
  mkt_nse_full_daily      NSE sec_bhavdata_full, every series + delivery (~2019-10 ..)
  mkt_bse_deals           BSE bulk / block deals
  mkt_bse_insider         BSE PIT disclosures (2019 .. 2022; raw columns kept in raw_json)
  mkt_nse_sme_daily       NSE Emerge bhavcopy
  mkt_nse_index_daily     NSE all-index close
  mkt_bse_eq_daily        BSE bhavcopy (legacy + UDiFF)
  mkt_bse_delivery_daily  BSE gross deliverables
  mkt_commodity_daily     Commodity futures + USDINR (Yahoo Finance)
  mkt_commodity_monthly   World Bank pink sheet (monthly)
  mkt_nse_insider         SEBI PIT disclosures
  mkt_nse_sast            SAST Reg 29 disclosures
  mkt_nse_deals           Bulk / block deals
  mkt_nse_short           Short-selling disclosures
  corporate_actions       (existing) new NSE actions appended
  mkt_load_log            one row per loaded file (makes reruns idempotent)

Holds the ingestion queue lock (same OS lock as run_ingestion_queue.py) for the
whole run and commits per file, so scheduled writers wait rather than collide.

Usage:
    python -m reality_engine.scripts.load_market_raw --sources all
    python -m reality_engine.scripts.load_market_raw --sources bse_deliv --dry-run
"""

import argparse
import csv
import io
import json
import os
import sqlite3
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from reality_engine import config as cfg
from reality_engine.ingestion.corporate_actions_client import CorporateActionsClient

RAW = cfg.DATA_DIR / "raw_market"

DDL = """
CREATE TABLE IF NOT EXISTS mkt_load_log (
    source TEXT NOT NULL, file TEXT NOT NULL, rows INTEGER NOT NULL,
    loaded_at TEXT NOT NULL, PRIMARY KEY (source, file));

CREATE TABLE IF NOT EXISTS mkt_nse_eq_daily (
    date TEXT NOT NULL, symbol TEXT NOT NULL, series TEXT NOT NULL, isin TEXT,
    open REAL, high REAL, low REAL, close REAL, last REAL, prev_close REAL,
    volume INTEGER, turnover_inr REAL, num_trades INTEGER,
    deliverable_qty INTEGER, delivery_pct REAL,
    PRIMARY KEY (date, symbol, series));
CREATE INDEX IF NOT EXISTS idx_mkt_nse_eq_isin ON mkt_nse_eq_daily(isin, date);

CREATE TABLE IF NOT EXISTS mkt_nse_full_daily (
    date TEXT NOT NULL, symbol TEXT NOT NULL, series TEXT NOT NULL,
    prev_close REAL, open REAL, high REAL, low REAL, last REAL, close REAL, avg_price REAL,
    volume INTEGER, turnover_lacs REAL, num_trades INTEGER, deliverable_qty INTEGER, delivery_pct REAL,
    PRIMARY KEY (date, symbol, series));

CREATE TABLE IF NOT EXISTS mkt_bse_deals (
    date TEXT NOT NULL, deal_type TEXT NOT NULL, sc_code TEXT NOT NULL, scrip_name TEXT,
    client_name TEXT NOT NULL, buy_sell TEXT NOT NULL, quantity REAL, price REAL, seq INTEGER NOT NULL,
    PRIMARY KEY (date, deal_type, sc_code, client_name, buy_sell, seq));

CREATE TABLE IF NOT EXISTS mkt_bse_insider (
    file TEXT NOT NULL, line_no INTEGER NOT NULL, company TEXT, isin TEXT, person TEXT,
    raw_json TEXT, PRIMARY KEY (file, line_no));

CREATE TABLE IF NOT EXISTS mkt_fii_dii_cash (
    date TEXT PRIMARY KEY, fii_purchase_cr REAL, fii_sales_cr REAL, fii_net_cr REAL,
    dii_purchase_cr REAL, dii_sales_cr REAL, dii_net_cr REAL,
    nifty_close REAL, nifty_prev_close REAL, nifty_change_pct REAL, source TEXT);

CREATE TABLE IF NOT EXISTS mkt_bse_index_daily (
    date TEXT NOT NULL, index_code TEXT NOT NULL, index_name TEXT,
    open REAL, high REAL, low REAL, close REAL, prev_close REAL, pe REAL, pb REAL, div_yield REAL,
    turnover TEXT, shares_traded TEXT, PRIMARY KEY (date, index_code));

CREATE TABLE IF NOT EXISTS mkt_nse_participant (
    date TEXT NOT NULL, kind TEXT NOT NULL, client_type TEXT NOT NULL,
    fut_idx_long REAL, fut_idx_short REAL, fut_stk_long REAL, fut_stk_short REAL,
    opt_idx_call_long REAL, opt_idx_put_long REAL, opt_idx_call_short REAL, opt_idx_put_short REAL,
    opt_stk_call_long REAL, opt_stk_put_long REAL, opt_stk_call_short REAL, opt_stk_put_short REAL,
    total_long REAL, total_short REAL, PRIMARY KEY (date, kind, client_type));

CREATE TABLE IF NOT EXISTS mkt_nsdl_fpi_daily (
    date TEXT NOT NULL, asset_class TEXT NOT NULL, route TEXT NOT NULL,
    gross_purchase_cr REAL, gross_sales_cr REAL, net_cr REAL, net_usd_mn REAL, usdinr REAL,
    PRIMARY KEY (date, asset_class, route));

CREATE TABLE IF NOT EXISTS mkt_nse_pit_filings (
    app_id TEXT NOT NULL, segment TEXT NOT NULL, symbol TEXT, company TEXT, regulation TEXT,
    submission_type TEXT, broadcast_at TEXT, disseminated_at TEXT, revision_remark TEXT,
    prev_app_id TEXT, xml_url TEXT, ixbrl_url TEXT, PRIMARY KEY (app_id, segment));

CREATE TABLE IF NOT EXISTS mkt_nse_pit_xbrl_facts (
    xml_file TEXT NOT NULL, context_id TEXT NOT NULL, concept TEXT NOT NULL, seq INTEGER NOT NULL,
    value TEXT, unit TEXT, PRIMARY KEY (xml_file, context_id, concept, seq));

-- Report tables kept cell-by-cell (NSDL fortnightly sector data, NSDL one-shot reports and
-- limit lists, NSE FII derivative stats): multi-row headers vary across years, so cells are
-- stored faithfully and tidy views are built later.
CREATE TABLE IF NOT EXISTS mkt_report_cells (
    source TEXT NOT NULL, file TEXT NOT NULL, table_idx INTEGER NOT NULL,
    row_idx INTEGER NOT NULL, col_idx INTEGER NOT NULL, value TEXT,
    PRIMARY KEY (source, file, table_idx, row_idx, col_idx));

CREATE TABLE IF NOT EXISTS mkt_nse_sme_daily (
    date TEXT NOT NULL, symbol TEXT NOT NULL, series TEXT NOT NULL, security TEXT,
    open REAL, high REAL, low REAL, close REAL, prev_close REAL,
    volume INTEGER, turnover_inr REAL, corp_ind TEXT, high_52w REAL, low_52w REAL,
    PRIMARY KEY (date, symbol, series));

CREATE TABLE IF NOT EXISTS mkt_nse_index_daily (
    date TEXT NOT NULL, index_name TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, points_change REAL, pct_change REAL,
    volume INTEGER, turnover_cr REAL, pe REAL, pb REAL, div_yield REAL,
    PRIMARY KEY (date, index_name));

CREATE TABLE IF NOT EXISTS mkt_bse_eq_daily (
    date TEXT NOT NULL, sc_code TEXT NOT NULL, isin TEXT, symbol TEXT, name TEXT,
    sc_group TEXT, sc_type TEXT,
    open REAL, high REAL, low REAL, close REAL, last REAL, prev_close REAL,
    num_trades INTEGER, volume INTEGER, turnover_inr REAL, file_format TEXT,
    PRIMARY KEY (date, sc_code));
CREATE INDEX IF NOT EXISTS idx_mkt_bse_eq_isin ON mkt_bse_eq_daily(isin, date);

CREATE TABLE IF NOT EXISTS mkt_bse_delivery_daily (
    date TEXT NOT NULL, sc_code TEXT NOT NULL,
    deliverable_qty INTEGER, deliverable_value REAL, volume INTEGER, turnover_inr REAL,
    delivery_pct REAL, PRIMARY KEY (date, sc_code));

CREATE TABLE IF NOT EXISTS mkt_commodity_daily (
    date TEXT NOT NULL, commodity TEXT NOT NULL, ticker TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, adj_close REAL, volume REAL,
    source TEXT, PRIMARY KEY (date, commodity));

CREATE TABLE IF NOT EXISTS mkt_commodity_monthly (
    month TEXT NOT NULL, series TEXT NOT NULL, unit TEXT, value REAL, source TEXT,
    PRIMARY KEY (month, series));

CREATE TABLE IF NOT EXISTS mkt_nse_insider (
    did TEXT PRIMARY KEY, pid TEXT, symbol TEXT, company TEXT, acquirer_name TEXT, person_category TEXT,
    security_type TEXT, transaction_type TEXT, acquisition_mode TEXT,
    securities_qty REAL, securities_value REAL, buy_qty REAL, buy_value REAL,
    sell_qty REAL, sell_value REAL, before_shares TEXT, before_pct TEXT,
    after_shares TEXT, after_pct TEXT, acq_from TEXT, acq_to TEXT,
    intimation_date TEXT, disseminated_at TEXT, exchange TEXT, xbrl TEXT, raw_json TEXT);
CREATE INDEX IF NOT EXISTS idx_mkt_insider_sym ON mkt_nse_insider(symbol, disseminated_at);

CREATE TABLE IF NOT EXISTS mkt_nse_sast (
    rec_key TEXT PRIMARY KEY, symbol TEXT, company TEXT, acquirer_name TEXT,
    sale_or_acq TEXT, acquisition_mode TEXT, disseminated_at TEXT, raw_json TEXT);

CREATE TABLE IF NOT EXISTS mkt_nse_deals (
    date TEXT NOT NULL, deal_type TEXT NOT NULL, symbol TEXT NOT NULL, security TEXT,
    client_name TEXT NOT NULL, buy_sell TEXT NOT NULL, quantity INTEGER, price REAL,
    remarks TEXT, seq INTEGER NOT NULL,
    PRIMARY KEY (date, deal_type, symbol, client_name, buy_sell, seq));

CREATE TABLE IF NOT EXISTS mkt_nse_short (
    date TEXT NOT NULL, symbol TEXT NOT NULL, security TEXT, quantity INTEGER,
    PRIMARY KEY (date, symbol));
"""


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def acquire_queue_lock(wait_sec: int):
    """Same OS-level lock as run_ingestion_queue.py; waits up to wait_sec."""
    path = cfg.DATA_DIR / "ingestion_queue.lock"
    handle = path.open("a+b")
    handle.seek(0)
    deadline = time.time() + wait_sec
    while True:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError:
            if time.time() > deadline:
                handle.close()
                return None
            time.sleep(30)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(cfg.DB_PATH), timeout=180)
    for p in cfg.SQLITE_PRAGMAS:
        if "foreign_keys" not in p.lower():
            conn.execute(p)
    return conn


def num(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "NA", "Nil", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def inum(v):
    f = num(v)
    return int(f) if f is not None else None


def ddmmyyyy(s: str) -> str:
    """'02-JAN-2019' / '02-01-2019' / '02012019' -> '2019-01-02'."""
    s = s.strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%d%m%Y", "%d-%b-%Y %H:%M", "%d-%B-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return s


def ts(s):
    """'31-Jan-2019 23:13' -> '2019-01-31 23:13'; passes through anything unparseable."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%d-%b-%Y %H:%M", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%d-%m-%Y %H:%M", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M" if "%H" in fmt else "%Y-%m-%d")
        except ValueError:
            pass
    return s


def date_from_name(name: str, fmt: str, start: int, length: int) -> str:
    return datetime.strptime(name[start:start + length], fmt).strftime("%Y-%m-%d")


def ok_files(source: str, pattern: str):
    d = RAW / source
    return sorted(p for p in d.glob(pattern) if not p.name.startswith("_")) if d.exists() else []


# ----------------------------------------------------------------------------
# per-source parsers: file -> (table, columns, rows)
# ----------------------------------------------------------------------------
def parse_nse_cm(path: Path):
    with zipfile.ZipFile(path) as z:
        df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), dtype=str)
    df.columns = [c.strip() for c in df.columns]
    date = datetime.strptime(path.name[2:11], "%d%b%Y").strftime("%Y-%m-%d")
    mto = RAW / "nse_mto" / f"MTO_{datetime.strptime(date, '%Y-%m-%d'):%d%m%Y}.DAT"
    deliv = {}
    if mto.exists():
        for line in mto.read_text(encoding="latin1").splitlines():
            parts = line.split(",")
            if len(parts) >= 7 and parts[0] == "20":
                deliv[(parts[2].strip(), parts[3].strip())] = (inum(parts[5]), num(parts[6]))
    rows = []
    for r in df.itertuples(index=False):
        sym, ser = str(r.SYMBOL).strip(), str(r.SERIES).strip()
        dq, dp = deliv.get((sym, ser), (None, None))
        rows.append((date, sym, ser, (r.ISIN or "").strip() or None, num(r.OPEN), num(r.HIGH), num(r.LOW),
                     num(r.CLOSE), num(r.LAST), num(r.PREVCLOSE), inum(r.TOTTRDQTY), num(r.TOTTRDVAL),
                     inum(r.TOTALTRADES), dq, dp))
    return "mkt_nse_eq_daily", 15, rows


def parse_nse_sme(path: Path):
    date = date_from_name(path.name, "%d%m%y", 3, 6)
    df = pd.read_csv(path, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    rows = [(date, str(r.SYMBOL).strip(), str(r.SERIES).strip(), str(r.SECURITY).strip(),
             num(r.OPEN_PRICE), num(r.HIGH_PRICE), num(r.LOW_PRICE), num(r.CLOSE_PRICE),
             num(r.PREV_CL_PR), inum(r.NET_TRDQTY), num(r.NET_TRDVAL), (r.CORP_IND or "").strip() or None,
             num(r.HI_52_WK), num(r.LO_52_WK)) for r in df.itertuples(index=False)]
    return "mkt_nse_sme_daily", 14, rows


def parse_nse_index(path: Path):
    df = pd.read_csv(path, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    rows = []
    for _, r in df.iterrows():
        rows.append((ddmmyyyy(r["Index Date"]), r["Index Name"].strip(), num(r["Open Index Value"]),
                     num(r["High Index Value"]), num(r["Low Index Value"]), num(r["Closing Index Value"]),
                     num(r["Points Change"]), num(r["Change(%)"]), inum(r["Volume"]),
                     num(r["Turnover (Rs. Cr.)"]), num(r["P/E"]), num(r["P/B"]), num(r["Div Yield"])))
    return "mkt_nse_index_daily", 13, rows


def parse_bse_bhav(path: Path):
    rows = []
    if path.suffix.upper() == ".ZIP":
        date = date_from_name(path.name, "%d%m%y", 2, 6)
        with zipfile.ZipFile(path) as z:
            # EQ291221 has one line with 27 fields (two records run together); skip and warn.
            df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), dtype=str, on_bad_lines="warn")
        df.columns = [c.strip() for c in df.columns]
        for r in df.itertuples(index=False):
            rows.append((date, str(r.SC_CODE).strip(), None, None, str(r.SC_NAME).strip(),
                         str(r.SC_GROUP).strip(), str(r.SC_TYPE).strip(), num(r.OPEN), num(r.HIGH),
                         num(r.LOW), num(r.CLOSE), num(r.LAST), num(r.PREVCLOSE), inum(r.NO_TRADES),
                         inum(r.NO_OF_SHRS), num(r.NET_TURNOV), "legacy"))
    else:
        df = pd.read_csv(path, dtype=str)
        df.columns = [c.strip() for c in df.columns]
        for r in df.itertuples(index=False):
            rows.append((str(r.TradDt).strip(), str(r.FinInstrmId).strip(), (r.ISIN or "").strip() or None,
                         (r.TckrSymb or "").strip() or None, (r.FinInstrmNm or "").strip(),
                         (r.SctySrs or "").strip(), (r.FinInstrmTp or "").strip(), num(r.OpnPric),
                         num(r.HghPric), num(r.LwPric), num(r.ClsPric), num(r.LastPric),
                         num(r.PrvsClsgPric), inum(r.TtlNbOfTxsExctd), inum(r.TtlTradgVol),
                         num(r.TtlTrfVal), "udiff"))
    return "mkt_bse_eq_daily", 17, rows


def parse_bse_deliv(path: Path):
    with zipfile.ZipFile(path) as z:
        lines = z.read(z.namelist()[0]).decode("latin1").splitlines()
    rows = []
    for line in lines[1:]:
        p = line.split("|")
        if len(p) < 7:
            continue
        rows.append((ddmmyyyy(p[0]), p[1].strip(), inum(p[2]), num(p[3]), inum(p[4]), num(p[5]), num(p[6])))
    return "mkt_bse_delivery_daily", 7, rows


def parse_insider(path: Path):
    rows = []
    for x in json.loads(path.read_text(encoding="utf-8")):
        # did is unique per disclosure; pid repeats across a person's disclosures.
        rows.append((str(x.get("did")), str(x.get("pid")), x.get("symbol"), x.get("company"), x.get("acqName"),
                     x.get("personCategory"), x.get("secType"), x.get("tdpTransactionType"), x.get("acqMode"),
                     num(x.get("secAcq")), num(x.get("secVal")), num(x.get("buyQuantity")), num(x.get("buyValue")),
                     num(x.get("sellquantity")), num(x.get("sellValue")), x.get("befAcqSharesNo"),
                     x.get("befAcqSharesPer"), x.get("afterAcqSharesNo"), x.get("afterAcqSharesPer"),
                     ts(x.get("acqfromDt")), ts(x.get("acqtoDt")), ts(x.get("intimDt")), ts(x.get("date")),
                     x.get("exchange"), x.get("xbrl"), json.dumps(x)))
    return "mkt_nse_insider", 26, rows


def parse_sast(path: Path):
    rows = []
    for x in json.loads(path.read_text(encoding="utf-8")):
        key = str(x.get("application_no") or x.get("id") or hash(json.dumps(x, sort_keys=True)))
        rows.append((key, x.get("symbol"), x.get("company"), x.get("acquirerName"), x.get("acqSaleType"),
                     x.get("acquisitionMode"), ts(x.get("timestamp") or x.get("date")), json.dumps(x)))
    return "mkt_nse_sast", 8, rows


def parse_deals(path: Path, deal_type: str):
    text = path.read_bytes().decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    next(reader, None)
    rows, seen = [], {}
    for p in reader:
        if len(p) < 7:
            continue
        key = (ddmmyyyy(p[0]), p[1].strip(), p[3].strip(), p[4].strip().upper())
        seen[key] = seen.get(key, 0) + 1
        rows.append((key[0], deal_type, key[1], p[2].strip(), key[2], key[3], inum(p[5]), num(p[6]),
                     p[7].strip() if len(p) > 7 else None, seen[key]))
    return "mkt_nse_deals", 10, rows


def parse_short(path: Path):
    text = path.read_bytes().decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    next(reader, None)
    rows = [(ddmmyyyy(p[0]), p[1].strip(), p[2].strip(), inum(p[3])) for p in reader if len(p) >= 4]
    return "mkt_nse_short", 4, rows


def parse_nse_full(path: Path):
    df = pd.read_csv(path, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df = df.apply(lambda col: col.str.strip())
    rows = [(ddmmyyyy(r.DATE1), r.SYMBOL, r.SERIES, num(r.PREV_CLOSE), num(r.OPEN_PRICE), num(r.HIGH_PRICE),
             num(r.LOW_PRICE), num(r.LAST_PRICE), num(r.CLOSE_PRICE), num(r.AVG_PRICE), inum(r.TTL_TRD_QNTY),
             num(r.TURNOVER_LACS), inum(r.NO_OF_TRADES), inum(r.DELIV_QTY), num(r.DELIV_PER))
            for r in df.itertuples(index=False)]
    return "mkt_nse_full_daily", 15, rows


def parse_bse_deals(path: Path, deal_type: str):
    rows, seen = [], {}
    for x in json.loads(path.read_text(encoding="utf-8")):
        side = {"P": "BUY", "S": "SELL"}.get(str(x.get("TRANSACTION_TYPE")).strip(), str(x.get("TRANSACTION_TYPE")))
        key = (str(x.get("DEAL_DATE", ""))[:10], str(x.get("SCRIP_CODE")), str(x.get("CLIENT_NAME", "")).strip(), side)
        seen[key] = seen.get(key, 0) + 1
        rows.append((key[0], deal_type, key[1], x.get("scripname"), key[2], key[3],
                     num(x.get("QUANTITY")), num(x.get("PRICE")), seen[key]))
    return "mkt_bse_deals", 9, rows


def parse_bse_insider(path: Path):
    reader = csv.DictReader(io.StringIO(path.read_bytes().decode("utf-8-sig", errors="replace")))
    rows = []
    for i, r in enumerate(reader, start=1):
        rows.append((path.name, i, r.get("Name of the Target Company"), r.get("ISIN of Target Company"),
                     r.get("Name(s) of the promoter and/or persons in promoter group"), json.dumps(r)))
    return "mkt_bse_insider", 6, rows


def parse_participant(path: Path):
    kind = "oi" if "_oi_" in path.name else "vol"
    date = datetime.strptime(path.stem[-8:], "%d%m%Y").strftime("%Y-%m-%d")
    lines = path.read_text(encoding="latin1").splitlines()[2:]
    rows = []
    for line in lines:
        p = [c.strip().strip('"') for c in line.split(",")]
        if len(p) >= 15 and p[0]:
            rows.append((date, kind, p[0], *[num(v) for v in p[1:15]]))
    return "mkt_nse_participant", 17, rows


def parse_nsdl_daily(path: Path):
    tables = [t for t in pd.read_html(path) if t.shape[1] >= 8]
    df = tables[0]
    df.columns = range(df.shape[1])
    rows, cur_date, cur_asset = [], None, None
    for _, r in df.iterrows():
        d, asset, route = r[0], r[1], r[2]
        if isinstance(d, str) and d[:2].isdigit():
            cur_date = ddmmyyyy(d)
        if isinstance(asset, str) and asset.strip() and asset.strip() != route:
            cur_asset = asset.strip()
        if not cur_date or not isinstance(route, str) or route.strip() in ("", "Investment Route"):
            continue
        net = lambda v: num(str(v).replace("(", "-").replace(")", ""))
        fx = num(str(r[7]).replace("Rs.", "")) if len(r) > 7 else None
        rows.append((cur_date, cur_asset or "", route.strip(), net(r[3]), net(r[4]), net(r[5]), net(r[6]), fx))
    return "mkt_nsdl_fpi_daily", 8, rows


def parse_pit_filings(path: Path, segment: str):
    rows = [(str(x.get("appId")), segment, x.get("symbol"), x.get("companyName"), x.get("regulation"),
             x.get("typeOfSubmission"), ts(x.get("broadcastDateTime")), ts(x.get("exchdisstime")),
             x.get("revisionRemark"), x.get("prevAppId"), x.get("xmlFileName"), x.get("ixbrl"))
            for x in json.loads(path.read_text(encoding="utf-8"))]
    return "mkt_nse_pit_filings", 12, rows


def parse_pit_xml(path: Path):
    from xml.etree import ElementTree as ET
    root = ET.parse(path).getroot()
    rows, seen = [], {}
    for el in root:
        ctx = el.get("contextRef")
        if not ctx:
            continue
        concept = el.tag.split("}")[-1]
        key = (ctx, concept)
        seen[key] = seen.get(key, 0) + 1
        rows.append((path.name, ctx, concept, seen[key], (el.text or "").strip(), el.get("unitRef")))
    return "mkt_nse_pit_xbrl_facts", 6, rows


def parse_cells(path: Path, source: str):
    if path.suffix.lower() == ".xls":
        tables = list(pd.read_excel(path, sheet_name=None, header=None).values())
    else:
        tables = pd.read_html(path, header=None)
    rows = []
    for ti, t in enumerate(tables):
        for ri in range(t.shape[0]):
            for ci in range(t.shape[1]):
                v = t.iat[ri, ci]
                if v is not None and not (isinstance(v, float) and pd.isna(v)):
                    rows.append((source, path.name, ti, ri, ci, str(v)))
    return "mkt_report_cells", 6, rows


def parse_bse_index(path: Path):
    code = path.stem.rsplit("_", 1)[0]
    rows = []
    for x in json.loads(path.read_text(encoding="utf-8")):
        prev = x.get("Previousclose", x.get("Prev_Close"))
        when = x.get("tdate") or x.get("Date") or ""  # 24 of 644 files use "Date"
        if not when:
            continue
        rows.append((str(when)[:10], code, x.get("I_name"), num(x.get("I_open")),
                     num(x.get("I_high")), num(x.get("I_low")), num(x.get("I_close")), num(prev),
                     num(x.get("I_pe")), num(x.get("I_pb")), num(x.get("I_yl")),
                     x.get("Turnover_1") or x.get("Turnover"), x.get("TOTAL_SHARES_TRADED")))
    return "mkt_bse_index_daily", 13, rows


def parse_mc_fiidii(path: Path):
    """Decoded CSV from fetch_fiidii_moneycontrol.py (FII/DII provisional cash flows, Rs crore)."""
    with path.open(newline="", encoding="utf-8") as f:
        rows = [(r["date"], num(r["fii_purchase"]), num(r["fii_sales"]), num(r["fii_net"]),
                 num(r["dii_purchase"]), num(r["dii_sale"]), num(r["dii_net"]), num(r["nifty_close"]),
                 num(r["nifty_prev_close"]), num(r["nifty_change_pct"]), "moneycontrol")
                for r in csv.DictReader(f)]
    return "mkt_fii_dii_cash", 11, rows


SOURCES = {
    "mc_fiidii": ("*.csv", parse_mc_fiidii),
    "bse_index": ("[!_]*.json", parse_bse_index),
    "nse_part_oi": ("*.csv", parse_participant),
    "nse_part_vol": ("*.csv", parse_participant),
    "nse_fii_stats": ("*.xls", lambda p: parse_cells(p, "nse_fii_stats")),
    "nsdl_fpi_daily": ("*.html", parse_nsdl_daily),
    "nsdl_fpi_fortnight": ("*.html", lambda p: parse_cells(p, "nsdl_fpi_fortnight")),
    "nsdl_reports": ("*.html", lambda p: parse_cells(p, "nsdl_reports")),
    "nsdl_limits": ("*.html", lambda p: parse_cells(p, "nsdl_limits")),
    "nse_pit_gg": ("*.json", lambda p: parse_pit_filings(p, "equities")),
    "nse_pit_gg_sme": ("*.json", lambda p: parse_pit_filings(p, "sme")),
    "nse_pit_gg_xml": ("*.xml", parse_pit_xml),
    "nse_cm": ("*.zip", parse_nse_cm),
    "nse_full": ("*.csv", parse_nse_full),
    "bse_bulk": ("*.json", lambda p: parse_bse_deals(p, "BULK")),
    "bse_block": ("*.json", lambda p: parse_bse_deals(p, "BLOCK")),
    "bse_insider": ("*.csv", parse_bse_insider),
    "nse_sme": ("*.csv", parse_nse_sme),
    "nse_index": ("*.csv", parse_nse_index),
    "bse_bhav": ("*", parse_bse_bhav),
    "bse_deliv": ("*.zip", parse_bse_deliv),
    "nse_pit": ("*.json", parse_insider),
    "nse_sast": ("*.json", parse_sast),
    "nse_bulk": ("*.csv", lambda p: parse_deals(p, "BULK")),
    "nse_block": ("*.csv", lambda p: parse_deals(p, "BLOCK")),
    "nse_short": ("*.csv", parse_short),
}


def load_file_sources(conn, names, dry_run):
    # reload a file when it changed after it was loaded: some fetchers rewrite one growing file (Moneycontrol FII/DII
    # per year, NSDL, BSE index JSON); keyed on name alone those froze in early Oct 2026. Rows are INSERT OR REPLACE.
    loaded = {(s, f): t for s, f, t in conn.execute("SELECT source, file, loaded_at FROM mkt_load_log")}
    summary = {}
    for name in names:
        pattern, parser = SOURCES[name]
        n_files = n_rows = n_err = 0
        for path in ok_files(name, pattern):
            t = loaded.get((name, path.name))
            if t and datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds") <= t:
                continue
            try:
                table, ncol, rows = parser(path)
            except Exception as e:
                n_err += 1
                print(f"  ! {name}/{path.name}: {e}", file=sys.stderr)
                continue
            if not dry_run:
                with conn:
                    conn.executemany(f"INSERT OR REPLACE INTO {table} VALUES ({','.join('?' * ncol)})", rows)
                    conn.execute("INSERT OR REPLACE INTO mkt_load_log VALUES (?,?,?,?)",
                                 (name, path.name, len(rows), datetime.now().isoformat(timespec="seconds")))
            n_files += 1
            n_rows += len(rows)
        summary[name] = {"files": n_files, "rows": n_rows, "errors": n_err}
        print(f"{name:10} {summary[name]}", flush=True)
    return summary


def load_corpact(conn, dry_run):
    cols = ["isin", "symbol", "company_name", "subject", "action_type", "ex_date", "rec_date",
            "bc_start_date", "bc_end_date", "nd_start_date", "nd_end_date", "broadcast_date",
            "face_value", "series", "industry", "source"]
    loaded = {f for (f,) in conn.execute("SELECT file FROM mkt_load_log WHERE source='nse_corpact'")}
    before = conn.execute("SELECT COUNT(*) FROM corporate_actions").fetchone()[0]
    n_files = 0
    for path in ok_files("nse_corpact", "*.json"):
        if path.name in loaded:
            continue
        recs = [CorporateActionsClient._normalize(x) for x in json.loads(path.read_text(encoding="utf-8"))]
        recs = [r for r in recs if r["isin"] and r["symbol"]]
        if not dry_run:
            with conn:
                conn.executemany(
                    f"INSERT OR IGNORE INTO corporate_actions ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    [tuple(r[c] for c in cols) for r in recs])
                conn.execute("INSERT OR REPLACE INTO mkt_load_log VALUES (?,?,?,?)",
                             ("nse_corpact", path.name, len(recs), datetime.now().isoformat(timespec="seconds")))
        n_files += 1
    after = conn.execute("SELECT COUNT(*) FROM corporate_actions").fetchone()[0]
    print(f"nse_corpact {{'files': {n_files}, 'new_rows': {after - before}}}", flush=True)


def load_commodities(conn, dry_run):
    d = RAW / "commod"
    rows = []
    for path in sorted(d.glob("*__*.csv")):
        label, ticker = path.stem.split("__")
        ticker = ticker.replace("_F", "=F").replace("_X", "=X")
        df = pd.read_csv(path, header=[0, 1], index_col=0)  # yfinance writes a 2-row header
        df.columns = [c[0] for c in df.columns]
        for idx, r in df.iterrows():
            try:
                date = pd.Timestamp(idx).strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                continue
            rows.append((date, label, ticker, num(r.get("Open")), num(r.get("High")), num(r.get("Low")),
                         num(r.get("Close")), num(r.get("Adj Close")), num(r.get("Volume")), "yahoo_finance"))
    monthly = []
    wb = d / "worldbank_pink_sheet_monthly.xlsx"
    if wb.exists():
        raw = pd.read_excel(wb, sheet_name="Monthly Prices", header=None)
        names, units = raw.iloc[4], raw.iloc[5]
        for i in range(6, len(raw)):
            month = str(raw.iat[i, 0])
            if "M" not in month:
                continue
            m = month.replace("M", "-")
            if m < "2015":
                continue
            for j in range(1, raw.shape[1]):
                v = num(raw.iat[i, j])
                if v is not None and isinstance(names[j], str):
                    monthly.append((m, names[j].strip(), str(units[j]).strip(), v, "worldbank_pink_sheet"))
    if not dry_run:
        with conn:
            conn.executemany("INSERT OR REPLACE INTO mkt_commodity_daily VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            conn.executemany("INSERT OR REPLACE INTO mkt_commodity_monthly VALUES (?,?,?,?,?)", monthly)
    print(f"commod     {{'daily_rows': {len(rows)}, 'monthly_rows': {len(monthly)}}}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    all_names = [*SOURCES, "nse_corpact", "commod"]
    ap.add_argument("--sources", default="all", help="comma list or 'all' (" + ",".join(all_names) + ")")
    ap.add_argument("--dry-run", action="store_true", help="parse everything, write nothing")
    ap.add_argument("--lock-wait", type=int, default=3600, help="seconds to wait for the queue lock")
    args = ap.parse_args()
    names = all_names if args.sources == "all" else args.sources.split(",")

    lock = None
    if not args.dry_run:
        lock = acquire_queue_lock(args.lock_wait)
        if lock is None:
            sys.exit("queue lock busy (another writer is running); try again later")
    conn = connect()
    try:
        if not args.dry_run:
            conn.executescript(DDL)
        else:
            conn.executescript(DDL.replace("CREATE TABLE IF NOT EXISTS", "CREATE TEMP TABLE IF NOT EXISTS")
                               .replace("CREATE INDEX IF NOT EXISTS", "-- "))
        file_names = [n for n in names if n in SOURCES]
        if file_names:
            load_file_sources(conn, file_names, args.dry_run)
        if "nse_corpact" in names:
            load_corpact(conn, args.dry_run)
        if "commod" in names:
            load_commodities(conn, args.dry_run)
    finally:
        conn.close()
        if lock:
            lock.close()


if __name__ == "__main__":
    main()
