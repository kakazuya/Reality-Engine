"""Metadata-only probe (no download): duration + availability for each unique video. -> analysis/yt_probe.csv"""
import csv, json, subprocess, sys, time
ids = sorted({r['video_id'] for r in csv.DictReader(open('analysis/tg_video_links.csv', encoding='utf-8'))})
out = open('analysis/yt_probe.csv', 'w', newline='', encoding='utf-8'); w = csv.writer(out)
w.writerow(['video_id', 'status', 'duration_s', 'availability', 'live_status', 'title', 'upload_date'])
for i, v in enumerate(ids, 1):
    p = subprocess.run([sys.executable, '-m', 'yt_dlp', '--skip-download', '--no-warnings', '-J', f'https://youtu.be/{v}'],
                       capture_output=True, text=True, timeout=120)
    if p.returncode == 0:
        d = json.loads(p.stdout)
        w.writerow([v, 'ok', d.get('duration'), d.get('availability'), d.get('live_status'), (d.get('title') or '')[:80], d.get('upload_date')])
    else:
        w.writerow([v, 'error', '', '', '', (p.stderr.strip().splitlines() or [''])[-1][:120], ''])
    out.flush(); time.sleep(0.5)
    if i % 25 == 0: print(i, '/', len(ids), flush=True)
print('done')
