"""Read any remaining pairs, up to four more rounds, then do the final build: only passages that were read count."""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
ENV = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}


def run(script, *args, env=ENV):
    return subprocess.run([sys.executable, "-u", str(HERE / script), *args], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")


for n in range(4):
    built = run("run.py")
    if built.returncode:
        sys.exit(built.stderr[-1500:])
    out = run("reads.py", "--workers", "40")
    lines = [x for x in out.stdout.splitlines() if x.startswith(("to read", "DONE"))]
    print("round", n, lines, out.stderr[-300:], flush=True)
    if any(x.startswith("to read: 0") for x in lines):
        break
final = run("run.py", env={**ENV, "BANK_FINAL": "1"})
print("\n".join(x[:300] for x in final.stdout.splitlines() if not x.startswith(("[", "weak"))), final.stderr[-600:], flush=True)
print(run("audit.py").stdout[-1500:], flush=True)
