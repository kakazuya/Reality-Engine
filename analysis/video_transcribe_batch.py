"""Transcribe finished videos from analysis/yt_batch_3mo.txt with whisper.cpp (Vulkan, RX 6700 XT).
Output per video: reality_engine/data/video_out/<id>/transcript.json (segments with timestamps) + transcript.txt.
Resumable; only processes ids the downloader logged as 'ok'. Loops until all ids in the batch are done."""
import json, re, subprocess, sys, time
from pathlib import Path
ROOT = Path('.')
W = Path('C:/wc/b/bin/Release/whisper-cli.exe')
MODEL = ROOT / 'reality_engine/data/whisper/models/ggml-large-v3-turbo.bin'
CACHE = ROOT / 'reality_engine/data/video_cache'
OUT = ROOT / 'reality_engine/data/video_out'
PROMPT = ("Yeh ek Daily Bytes hai. Aaj hum Titagarh ki order book, margin guidance aur capex ke baare mein baat karenge. "
          "Company ne Q1 FY27 mein strong revenue growth report kiya.")
ids = [l.strip() for l in open('analysis/yt_batch_3mo.txt') if l.strip()]

def downloaded():
    ok = set()
    for line in open('analysis/yt_download.log', encoding='utf-8', errors='ignore'):
        m = re.match(r'\d+ / \d+ (\S+) ok', line)
        if m: ok.add(m.group(1))
    return ok

done = lambda v: (OUT / v / 'transcript.json').exists()
while True:
    ready = [v for v in ids if v in downloaded() and (CACHE / f'{v}.mp4').exists() and not done(v)]
    if not ready:
        if all(done(v) for v in ids) or not (set(ids) - downloaded() - {v for v in ids if done(v)}):
            print('all available videos done', flush=True); break
        time.sleep(30); continue
    v = ready[0]; d = OUT / v; d.mkdir(parents=True, exist_ok=True)
    wav = d / 'audio.wav'; t0 = time.time()
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(CACHE / f'{v}.mp4'), '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(wav)], check=True)
    p = subprocess.run([str(W), '-m', str(MODEL), '-f', str(wav), '-l', 'en', '--prompt', PROMPT, '-oj', '-otxt', '-of', str(d / 'transcript')],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if p.returncode == 0 and (d / 'transcript.json').exists():
        wav.unlink(missing_ok=True)
        print(f'{v} ok {time.time()-t0:.0f}s', flush=True)
    else:
        print(f'{v} FAILED {p.stderr[-200:]}', flush=True); (d / 'FAILED').write_text(p.stderr[-500:]); ids.remove(v)
