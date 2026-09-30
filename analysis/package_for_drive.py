"""Build the Drive upload pack in C:/pack_drive (originals untouched):
  equity_intelligence.db.xz  (WAL checkpointed first)   aux_pack.zip (harvest DB, vector index, parquet, small csv/jsonl)
  SHA256SUMS.txt   RESTORE.md
Not deleting anything. Re-run after final data changes; it overwrites the pack files only."""
import hashlib, os, sqlite3, subprocess, zipfile, time
from pathlib import Path
OUT = Path('C:/pack_drive'); OUT.mkdir(exist_ok=True)
DB = Path('reality_engine/data/equity_intelligence.db')
t0 = time.time()
c = sqlite3.connect(DB, timeout=900); print('checkpoint:', c.execute('pragma wal_checkpoint(TRUNCATE)').fetchone(), flush=True); c.close()
xz = OUT / 'equity_intelligence.db.xz'
with open(xz, 'wb') as f:
    subprocess.run(['xz', '-T0', '-3', '-c', str(DB)], stdout=f, check=True)
print(f'db compressed: {DB.stat().st_size/1e9:.1f} GB -> {xz.stat().st_size/1e9:.1f} GB in {time.time()-t0:.0f}s', flush=True)
aux = OUT / 'aux_pack.zip'
with zipfile.ZipFile(aux, 'w', zipfile.ZIP_STORED) as z:   # parquet/npy are already compressed or incompressible
    for base in ['reality_engine/data/vector_index', 'reality_engine/data/parquet']:
        for p in Path(base).rglob('*'):
            if p.is_file(): z.write(p, p.as_posix())
    for f in ['analysis/bse_announcements.db', 'analysis/proposed_changes.csv', 'analysis/snapshot_before_dates.jsonl',
              'analysis/tg_video_links.csv', 'analysis/yt_probe.csv', 'analysis/tg_topics.csv']:
        if Path(f).exists(): z.write(f, f)
    for p in Path('reality_engine/data/video_out').rglob('transcript.*'): z.write(p, p.as_posix())
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 24), b''): h.update(b)
    return h.hexdigest()
(OUT / 'SHA256SUMS.txt').write_text('\n'.join(f'{sha(p)}  {p.name}' for p in (xz, aux)) + '\n')
(OUT / 'RESTORE.md').write_text("""# Restore on a new machine
1. Put this folder's files in the repo root of a fresh clone (Windows: xz from https://tukaani.org/xz or 7-Zip).
2. `xz -d -k equity_intelligence.db.xz` then move to `reality_engine/data/equity_intelligence.db` (needs ~35 GB free).
3. Unzip `aux_pack.zip` in the repo root (restores vector_index, parquet, harvest DB, transcripts).
4. Verify: `sha256sum -c SHA256SUMS.txt`, then `python analysis/pit_validate.py`.
The DB is SQLite (WAL was checkpointed). Never commit any of this to GitHub; it contains private community content.
""")
print(f'pack done in {time.time()-t0:.0f}s:', {p.name: f'{p.stat().st_size/1e9:.2f} GB' for p in OUT.iterdir()})
