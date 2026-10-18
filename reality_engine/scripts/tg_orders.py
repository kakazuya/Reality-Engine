"""Orders from the Telegram 'Big Orders' topic (7) -> tg_orders + tg_order_schedule (2026-10-19).

Sources per post (text first, OCR of the card second):
  single-order alerts (text): 'Value: Rs 237.0 Cr -> Rs 47.4 Cr/yr . 21.2% of FY2026 revenue . Mcap Rs 2,068 Cr',
      'Disseminated 13 Oct 12:57:21 IST (NSE)', 'Customer: ...', filing URL; card OCR adds 'DURATION 60 months'
  daily recap cards (OCR): per company 'Order Rs 187 Cr (Rs 153 Cr/yr) . Revenue Rs 2,002 Cr (FY23) . 8% of revenue'
  older hand-written posts: value 'Rs 110 Cr' and an execution period in months / years when stated
Point in time: known_at = exchange dissemination time when the alert gives it (IST), else the Telegram post time
(recap cards post ~20:00 IST, after the filings). A recap row that repeats an alert already seen (same ISIN, value
within 2%, within 3 days) is dropped; the earlier alert is kept.
Execution: duration_months from the card ('DURATION'), else value / annual rate x 12 ('annualised' < value), else unknown
(annual rate == value means 'within a year': 12 months assumed, flagged duration_source='le_12m_assumed').
Schedule: value spread evenly per month from known_at over duration -> Indian fiscal quarters (Q1 = Apr-Jun).
Private paid-community content: private DB only.

    python -m reality_engine.scripts.tg_orders
"""
import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "reality_engine/data/equity_intelligence.db"
DDL = """
CREATE TABLE IF NOT EXISTS tg_orders (order_id TEXT PRIMARY KEY, post_id TEXT, message_id INTEGER, kind TEXT,
    isin TEXT, symbol TEXT, company TEXT, customer TEXT, description TEXT,
    value_cr REAL, annual_cr REAL, duration_months REAL, duration_source TEXT,
    revenue_cr REAL, revenue_fy TEXT, pct_of_revenue REAL, mcap_cr REAL, price_at_alert REAL,
    known_at TEXT, known_at_source TEXT, post_ts_utc TEXT, filing_url TEXT);
CREATE TABLE IF NOT EXISTS tg_order_schedule (order_id TEXT, isin TEXT, fy INTEGER, q INTEGER, amount_cr REAL,
    PRIMARY KEY (order_id, fy, q));
"""
NUM = r"([\d,]+(?:\.\d+)?)"
MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def f(x):
    return float(x.replace(",", "")) if x else None


def fq(d):
    """Indian fiscal (q, fy two-digit) of a date"""
    q = {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3, 1: 4, 2: 4, 3: 4}[d.month]
    fy = (d.year + 1) % 100 if d.month >= 4 else d.year % 100
    return q, fy


def schedule(value, months, start):
    """even monthly spread from the month of start; returns {(fy, q): amount}"""
    out = {}
    n = max(1, round(months))
    y, m = start.year, start.month
    for _ in range(n):
        q, fy = fq(dt.date(y, m, 1))
        out[(fy, q)] = out.get((fy, q), 0) + value / n
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def ist_to_utc(day, mon, hms, year):
    t = dt.datetime(year, MON[mon.lower()[:3]], int(day), *map(int, hms.split(":")))
    return (t - dt.timedelta(hours=5, minutes=30)).isoformat()


def durations_from(text):
    m = re.search(r"DURATION[^\d]{0,40}?(\d+(?:\.\d+)?)\s*months?", text or "", re.I | re.S)
    if m:
        return float(m.group(1))
    m = re.search(r"(?:execution|execute|completion|complete|within|over|period of)[^.\n]{0,40}?(\d+(?:\.\d+)?)\s*(months?|years?)",
                  text or "", re.I)
    if m:
        return float(m.group(1)) * (12 if m.group(2).lower().startswith("y") else 1)
    return None


def main():
    db = sqlite3.connect(DB, timeout=600)
    db.executescript(DDL)
    db.execute("DELETE FROM tg_orders"); db.execute("DELETE FROM tg_order_schedule")
    by_sym, by_bse, names = {}, {}, {}
    for isin, nse, bse, name in db.execute("SELECT isin, nse_symbol, bse_code, company_name FROM master_companies"):
        if nse: by_sym[nse.upper()] = isin
        if bse: by_bse[str(bse)] = isin
        if name: names[isin] = name
    sym_of = {}
    for isin, nse, bse in db.execute("SELECT isin, nse_symbol, bse_code FROM master_companies"):
        sym_of.setdefault(isin, nse or str(bse))
    ment = {}
    for pid, sym, isin in db.execute("SELECT post_id, symbol, isin FROM tg_company_mentions WHERE topic_id=7"):
        ment.setdefault(pid, []).append((sym, isin))
    posts = db.execute("SELECT id, message_id, post_timestamp, raw_message_text, ocr_extracted_text, button_links_json "
                       "FROM telegram_posts WHERE thread_topic_id=7 ORDER BY post_timestamp").fetchall()
    orders = []
    for pid, mid, ts, text, ocr, bl in posts:
        text = text or ""; ocr = ocr or ""
        year = int(ts[:4])
        v = re.search(rf"Value:\s*₹?\s*{NUM}\s*Cr\s*→\s*₹?\s*{NUM}\s*Cr/yr(?:\s*·\s*{NUM}%\s*of\s*FY(\d{{4}})\s*revenue)?(?:\s*·\s*Mcap\s*₹?\s*{NUM}\s*Cr)?", text)
        if v:      # single-order alert
            code = re.search(r"\b(NSE|BSE)\s*:\s*([A-Z0-9&_-]+)", text)
            isin = (by_sym.get(code.group(2)) if code and code.group(1) == "NSE" else by_bse.get(code.group(2))) if code else None
            dis = re.search(r"Disseminated\s+(\d{1,2})\s+([A-Za-z]{3})\s+(\d{2}:\d{2}:\d{2})\s+IST", text)
            price = re.search(rf"Price at detection:\s*₹?\s*{NUM}", text)
            urls = (json.loads(bl or "{}") or {}).get("urls", []) if isinstance(json.loads(bl or "{}"), dict) else []
            filing = next((u for u in urls if "screener" not in u), None)
            pct = f(v.group(3))
            orders.append(dict(post_id=pid, message_id=mid, kind="alert", isin=isin,
                               symbol=code.group(2) if code else None, company=text.splitlines()[0].strip(),
                               customer=(re.search(r"Customer:\s*(.+)", text) or [None, None])[1],
                               description=None, value_cr=f(v.group(1)), annual_cr=f(v.group(2)),
                               card_months=durations_from(ocr), revenue_cr=(f(v.group(1)) / pct * 100 if pct and f(v.group(2)) == f(v.group(1)) else None),
                               revenue_fy=("FY" + v.group(4)) if v.group(4) else None, pct_of_revenue=pct, mcap_cr=f(v.group(5)),
                               price_at_alert=f(price.group(1)) if price else None,
                               known_at=ist_to_utc(dis.group(1), dis.group(2), dis.group(3), year) if dis else ts[:19],
                               known_at_source="exchange_dissemination" if dis else "telegram_post", post_ts_utc=ts, filing_url=filing))
            continue
        # revenue part optional: 'Order Rs 66.3 Cr (Rs 41.1 Cr/yr) . Revenue not available' (Ameenji, 17 Oct) was dropped
        blocks = list(re.finditer(rf"Order\s*[₹€]?\s*{NUM}\s*Cr(?:\s*\(\s*[₹€]?\s*{NUM}\s*Cr/yr\))?\s*[·.]\s*Revenue\s*(?:[₹€]?\s*{NUM}\s*Cr\s*\((FY\d{{2}})\)\s*[·.]\s*{NUM}%|not available)", ocr))
        if blocks:  # recap card: attach each 'Order ...' line to the company named just before it
            start = 0
            for b in blocks:
                seg = ocr[start:b.start()]; start = b.end()
                isin = sym = None
                for line in reversed([l.strip() for l in seg.splitlines() if l.strip()]):
                    tok = re.sub(r"[^A-Z0-9&]+$", "", line)
                    i = by_sym.get(tok) or by_bse.get(tok)
                    if i:
                        isin, sym = i, tok; break
                    hit = [x for x, nm in names.items() if nm and len(line) > 6 and nm.lower().startswith(line.lower().rstrip(".… "))]
                    if len(hit) == 1:
                        isin = hit[0]; break
                orders.append(dict(post_id=pid, message_id=mid, kind="recap", isin=isin, symbol=sym, company=None,
                                   customer=None, description=None, value_cr=f(b.group(1)), annual_cr=f(b.group(2)),
                                   card_months=None, revenue_cr=f(b.group(3)), revenue_fy=b.group(4), pct_of_revenue=f(b.group(5)),
                                   mcap_cr=None, price_at_alert=None, known_at=ts[:19], known_at_source="telegram_post_recap",
                                   post_ts_utc=ts, filing_url=None))
            continue
        val = re.search(rf"₹\s*{NUM}\s*(?:Cr|crore)", text + " " + ocr, re.I)   # older hand-written posts
        if val and ment.get(pid):
            sym, isin = ment[pid][0]
            orders.append(dict(post_id=pid, message_id=mid, kind="manual", isin=isin, symbol=sym, company=None,
                               customer=None, description=text[:300], value_cr=f(val.group(1)), annual_cr=None,
                               card_months=durations_from(text + "\n" + ocr), revenue_cr=None, revenue_fy=None,
                               pct_of_revenue=None, mcap_cr=None, price_at_alert=None, known_at=ts[:19],
                               known_at_source="telegram_post", post_ts_utc=ts, filing_url=None))
    # drop recap rows that repeat an earlier alert (same ISIN, value within 2%, within 3 days)
    alerts = [o for o in orders if o["kind"] == "alert"]
    keep = []
    for o in orders:
        if o["kind"] == "recap" and o["isin"] and any(
                a["isin"] == o["isin"] and a["value_cr"] and abs(a["value_cr"] - o["value_cr"]) <= 0.02 * a["value_cr"]
                and 0 <= (dt.datetime.fromisoformat(o["known_at"]) - dt.datetime.fromisoformat(a["known_at"])).days <= 3
                for a in alerts):
            continue
        keep.append(o)
    stats = {}
    for n, o in enumerate(keep):
        months, src = o.pop("card_months"), None
        if months:
            src = "stated"
        elif o["annual_cr"] and o["value_cr"] and o["annual_cr"] < o["value_cr"] * 0.98:
            months, src = o["value_cr"] / o["annual_cr"] * 12, "value_over_annual"
        elif o["annual_cr"] and o["value_cr"]:
            months, src = 12, "le_12m_assumed"
        if o["isin"] and not o["symbol"]:
            o["symbol"] = sym_of.get(o["isin"])
        o.update(order_id=f"{o['post_id']}#{n}", duration_months=round(months, 1) if months else None, duration_source=src)
        stats[(o["kind"], src)] = stats.get((o["kind"], src), 0) + 1
        db.execute("INSERT INTO tg_orders VALUES (:order_id,:post_id,:message_id,:kind,:isin,:symbol,:company,:customer,"
                   ":description,:value_cr,:annual_cr,:duration_months,:duration_source,:revenue_cr,:revenue_fy,"
                   ":pct_of_revenue,:mcap_cr,:price_at_alert,:known_at,:known_at_source,:post_ts_utc,:filing_url)", o)
        if months and o["value_cr"]:
            ist = dt.datetime.fromisoformat(o["known_at"]) + dt.timedelta(hours=5, minutes=30)
            for (fy, q), amt in schedule(o["value_cr"], months, ist.date()).items():
                db.execute("INSERT INTO tg_order_schedule VALUES (?,?,?,?,?)", (o["order_id"], o["isin"], fy, q, round(amt, 3)))
    db.commit()
    print(f"orders {len(keep)} (dropped {len(orders) - len(keep)} recap repeats of alerts); with ISIN "
          f"{sum(1 for o in keep if o['isin'])}")
    for k, v in sorted(stats.items(), key=lambda x: (x[0][0], str(x[0][1]))):
        print(f"  {k[0]:7} duration {str(k[1]):18} {v}")
    print("schedule rows", db.execute("SELECT COUNT(*) FROM tg_order_schedule").fetchone()[0])


if __name__ == "__main__":
    main()
