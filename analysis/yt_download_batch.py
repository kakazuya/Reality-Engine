"""Download the batch listed in analysis/yt_batch_3mo.txt (newest first): <=1080p video+audio -> reality_engine/data/video_cache/<id>.mp4.
Resumable (skips finished ids), paced. Files are intermediates: deleted after transcript/frames are in the DB."""
import subprocess, sys, time
from pathlib import Path
ids = [l.strip() for l in open('analysis/yt_batch_3mo.txt') if l.strip()]
out = Path('reality_engine/data/video_cache')
for i, v in enumerate(ids, 1):
    if (out / f'{v}.mp4').exists():
        continue
    p = subprocess.run([sys.executable, '-m', 'yt_dlp', '-f', 'bv*[height<=1080]+ba/b[height<=1080]', '--merge-output-format', 'mp4',
                        '--no-warnings', '--no-playlist', '-o', str(out / f'{v}.%(ext)s'), f'https://youtu.be/{v}'],
                       capture_output=True, text=True)
    print(i, '/', len(ids), v, 'ok' if p.returncode == 0 else 'ERR ' + (p.stderr.strip().splitlines() or [''])[-1][:100], flush=True)
    time.sleep(3)
print('done', flush=True)
