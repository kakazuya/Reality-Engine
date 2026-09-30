"""Overnight chain (resumable via analysis/overnight_state.json). Each step is isolated: a failure is logged and the chain continues.
 1 wait transcription+video load   2 company tagging   3 embed video chunks
 4 wait BSE harvest   5 retry failed symbols (1 worker)   6 BSE join + annual-report PIT + validation
 7 rebuild dense vector index   8 final report  -> analysis/overnight_report.md"""
import json, os, re, sqlite3, subprocess, sys, time, datetime as dt
from pathlib import Path
os.chdir(Path(__file__).resolve().parents[1])
STATE = Path('analysis/overnight_state.json')
state = json.loads(STATE.read_text()) if STATE.exists() else {}
LOG = open('analysis/overnight.log', 'a', encoding='utf-8', buffering=1)
def log(*a):
    m = f"[{dt.datetime.now():%m-%d %H:%M:%S}] " + " ".join(str(x) for x in a); print(m, flush=True); LOG.write(m + '\n')
def run(cmd, name, timeout=None):
    t = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    tail = (p.stdout or '')[-1800:] + (p.stderr or '')[-600:]
    log(f"{name}: exit={p.returncode} {time.time()-t:.0f}s\n{tail}")
    return p.returncode == 0, p.stdout or ''
def step(name):
    def deco(fn):
        def w():
            if state.get(name) == 'done': log(f'skip {name} (done)'); return
            try:
                log(f'START {name}'); fn(); state[name] = 'done'
            except Exception as e:
                log(f'FAILED {name}: {e!r}'); state[name] = f'failed: {e!r}'
            STATE.write_text(json.dumps(state, indent=1))
        return w
    return deco
def yt_counts():
    c = sqlite3.connect('file:reality_engine/data/equity_intelligence.db?mode=ro', uri=True, timeout=120)
    n = c.execute("select count(*) from raw_documents where sha256_hash like 'yt:%'").fetchone()[0]; c.close(); return n
def procs(pat):
    o = subprocess.run(['powershell', '-NoProfile', '-Command',
        f"@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ? {{ $_.CommandLine -match '{pat}' }}).Count"],
        capture_output=True, text=True).stdout.strip()
    return int(o or 0)

@step('1_wait_video_load')
def s1():
    target = len([l for l in open('analysis/yt_batch_3mo.txt') if l.strip()])
    while True:
        failed = len(list(Path('reality_engine/data/video_out').glob('*/FAILED')))
        n = yt_counts()
        if n >= target - failed or (procs('video_transcribe_batch') == 0 and procs('video_load_loop') == 0): break
        time.sleep(60)
    log(f'video docs loaded: {yt_counts()}/{target}')
@step('2_tag_companies')
def s2(): assert run([sys.executable, 'reality_engine/scripts/tag_video_chunks.py'], 'tag')[0]
@step('3_embed_video_chunks')
def s3(): assert run([sys.executable, 'reality_engine/scripts/embed_video_chunks.py'], 'embed')[0]
@step('4_wait_harvest')
def s4():
    while procs('bse_announcement_harvest') > 0: time.sleep(120)
@step('5_retry_failed')
def s5():
    run([sys.executable, 'analysis/bse_harvest_missing.py'], 'missing-list')
    n = sum(1 for _ in open('analysis/bse_harvest_failed.csv')) - 1
    log(f'retry list: {n} symbols')
    if n > 0: run([sys.executable, '-u', 'analysis/bse_announcement_harvest.py', '--workers', '1', '--delay', '1.0',
                   '--symbols-file', 'analysis/bse_harvest_failed.csv'], 'retry-pass')
    run([sys.executable, 'analysis/bse_harvest_missing.py'], 'missing-list-after')
@step('6_join_and_validate')
def s6():
    run([sys.executable, 'analysis/apply_bse_join.py', '--apply'], 'bse-join')
    run([sys.executable, 'analysis/apply_annual_report_pit.py', '--apply'], 'ar-pit')
    ok, out = run([sys.executable, 'analysis/pit_validate.py'], 'pit-validate')
    Path('analysis/pit_validate_final.txt').write_text(out, encoding='utf-8')
@step('7_rebuild_vector_index')
def s7(): run([sys.executable, '-m', 'reality_engine.scripts.build_chunk_vector_index'], 'vector-index')
@step('8_report')
def s8():
    Path('analysis/overnight_report.md').write_text(
        f"# Overnight pipeline report ({dt.datetime.now():%Y-%m-%d %H:%M})\n\n```json\n{json.dumps(state, indent=1)}\n```\n\n"
        f"## PIT validation\n```\n{Path('analysis/pit_validate_final.txt').read_text(encoding='utf-8') if Path('analysis/pit_validate_final.txt').exists() else 'n/a'}\n```\n\n"
        f"## Full log\nsee analysis/overnight.log\n", encoding='utf-8')
for f in (s1, s2, s3, s4, s5, s6, s7, s8): f()
log('PIPELINE COMPLETE')
