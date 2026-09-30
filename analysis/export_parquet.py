"""Export the analysis-ready tables to Parquet (chunked, low memory) -> reality_engine/data/parquet/.
Price-side study reads these with polars lazy scans; they also travel to the laptop without the 33 GB DB."""
import sqlite3
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq
OUT = Path('reality_engine/data/parquet'); OUT.mkdir(parents=True, exist_ok=True)
c = sqlite3.connect('file:reality_engine/data/equity_intelligence.db?mode=ro', uri=True, timeout=600)
def dump(name, sql, chunk=250_000):
    cur = c.execute(sql); cols = [d[0] for d in cur.description]; w = None; n = 0
    while True:
        rows = cur.fetchmany(chunk)
        if not rows: break
        t = pa.table({k: [r[i] for r in rows] for i, k in enumerate(cols)})
        if w is None: w = pq.ParquetWriter(OUT / f'{name}.parquet', t.schema, compression='zstd')
        w.write_table(t); n += len(rows)
    if w: w.close()
    print(f'{name}: {n:,} rows', flush=True)
dump('daily_price_delivery', 'select * from daily_price_delivery order by symbol, date')
dump('corporate_actions', 'select * from corporate_actions')
dump('nse_index_breadth', 'select * from nse_index_breadth')
dump('master_companies', 'select isin, nse_symbol, bse_code, company_name, industry, sector, market_cap_tier, is_nifty50, is_nifty100, is_nifty200, is_nifty500, is_active from master_companies')
dump('document_events_pit', 'select id, isin, symbol, doc_type, title, source_url, pit_ts, pit_date, pit_basis, call_date, fiscal_period_end, crawl_doc_date from v_document_pit')
dump('telegram_posts', "select id, channel_title, thread_topic_id, thread_topic_name, message_id, raw_message_text, has_media, post_timestamp, button_links_json from telegram_posts where channel_id='-1002413883243'")
