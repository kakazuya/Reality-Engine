"""Loop: load every finished transcript into the DB (frames+OCR+chunks) until all 65 batch videos are loaded."""
import subprocess, sys, time
ids = [l.strip() for l in open('analysis/yt_batch_3mo.txt') if l.strip()]
while True:
    r = subprocess.run([sys.executable, 'reality_engine/scripts/ingest_video_batch.py', '--all', '--delete-media'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    print(r.stdout.strip()[-1500:], r.stderr.strip()[-300:], flush=True)
    import sqlite3
    c = sqlite3.connect('file:reality_engine/data/equity_intelligence.db?mode=ro', uri=True, timeout=120)
    n = c.execute("select count(*) from raw_documents where sha256_hash like 'yt:%'").fetchone()[0]
    c.close()
    print(f'loaded so far: {n}/{len(ids)}', flush=True)
    if n >= len(ids): break
    time.sleep(120)
