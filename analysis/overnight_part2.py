"""Queue behind overnight_pipeline.py: starts when its step 8 is done (or it has failed/finished), so the machine never idles.
 9 Telegram text backfill   10 Parquet export   11 secrets re-scan   12 Drive pack (preliminary)   13 report"""
import json, os, subprocess, sys, time, datetime as dt
from pathlib import Path
os.chdir(Path(__file__).resolve().parents[1])
S1, S2 = Path('analysis/overnight_state.json'), Path('analysis/overnight2_state.json')
state = json.loads(S2.read_text()) if S2.exists() else {}
LOG = open('analysis/overnight2.log', 'a', encoding='utf-8', buffering=1)
def log(*a):
    m = f"[{dt.datetime.now():%m-%d %H:%M:%S}] " + " ".join(str(x) for x in a); print(m, flush=True); LOG.write(m + '\n')
def run(cmd, name):
    t = time.time(); p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    log(f"{name}: exit={p.returncode} {time.time()-t:.0f}s\n{(p.stdout or '')[-1500:]}{(p.stderr or '')[-500:]}")
    if p.returncode: raise RuntimeError(f'{name} exit {p.returncode}')
def step(name, cmd):
    if state.get(name) == 'done': log('skip', name); return
    try: log('START', name); run(cmd, name); state[name] = 'done'
    except Exception as e: log('FAILED', name, repr(e)); state[name] = f'failed: {e!r}'
    S2.write_text(json.dumps(state, indent=1))
log('waiting for part 1 (step 8_report)')
while not (S1.exists() and json.loads(S1.read_text()).get('8_report') == 'done'): time.sleep(60)
py = sys.executable
step('9_telegram_backfill', [py, '-u', 'reality_engine/scripts/tg_backfill.py'])
step('10_parquet_export', [py, '-u', 'analysis/export_parquet.py'])
step('11_secrets_rescan', [py, 'analysis/secrets_scan.py'])
step('12_drive_pack_preliminary', [py, '-u', 'analysis/package_for_drive.py'])
Path('analysis/overnight2_report.md').write_text(f"# Part 2 report {dt.datetime.now():%Y-%m-%d %H:%M}\n```json\n{json.dumps(state, indent=1)}\n```\nLogs: analysis/overnight2.log\nPack (preliminary): C:/pack_drive\n", encoding='utf-8')
log('PART 2 COMPLETE')
