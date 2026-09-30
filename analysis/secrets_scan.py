"""Scan files git would publish (tracked + untracked-not-ignored, text, <2MB) for likely secrets.
Prints file:line and pattern name only - never the value. Report: analysis/secrets_report.txt"""
import re, subprocess
from pathlib import Path
PATTERNS = {
 'aws_key': r'AKIA[0-9A-Z]{16}', 'github_token': r'gh[pousr]_[A-Za-z0-9]{30,}', 'hf_token': r'hf_[A-Za-z0-9]{30,}',
 'openai_style_key': r'sk-[A-Za-z0-9_-]{20,}', 'anthropic_key': r'sk-ant-[A-Za-z0-9_-]{20,}',
 'private_key': r'-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----',
 'telegram_api_hash': r'(?i)api_?hash["\']?\s*[:=]\s*["\'][0-9a-f]{32}["\']',
 'generic_secret_assign': r'(?i)(password|passwd|secret|token|api[_-]?key)["\']?\s*[:=]\s*["\'][^"\'\s]{12,}["\']',
 'bot_token': r'\b\d{8,10}:[A-Za-z0-9_-]{35}\b',
}
files = subprocess.run(['git', 'ls-files', '-co', '--exclude-standard'], capture_output=True, text=True, encoding='utf-8').stdout.splitlines()
hits, scanned, binary_or_big = [], 0, 0
for f in files:
    p = Path(f)
    try:
        if not p.is_file() or p.stat().st_size > 2_000_000: binary_or_big += 1; continue
        txt = p.read_text(encoding='utf-8')
    except Exception: binary_or_big += 1; continue
    scanned += 1
    for i, line in enumerate(txt.splitlines(), 1):
        for name, pat in PATTERNS.items():
            if re.search(pat, line): hits.append(f'{f}:{i}  [{name}]')
risky = [f for f in files if re.search(r'(\.session$|browser_profile|\.env$|credentials|id_rsa|\.pem$|\.key$)', f, re.I)]
out = [f'files considered: {len(files)}, text files scanned: {scanned}, skipped (binary/large): {binary_or_big}',
       f'pattern hits: {len(hits)}', *hits[:200], f'risky filenames that git would publish: {len(risky)}', *risky[:50]]
Path('analysis/secrets_report.txt').write_text('\n'.join(out), encoding='utf-8'); print('\n'.join(out[:30]))
