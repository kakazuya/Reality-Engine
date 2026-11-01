"""Read, rebuild, read the replacements, up to five rounds. Each round only reads pairs not read before."""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
ENV = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}


def run(script, *args):
    return subprocess.run([sys.executable, "-u", str(HERE / script), *args], cwd=ROOT, env=ENV, capture_output=True, text=True, encoding="utf-8")


for n in range(1, 6):
    out = run("reads.py", "--workers", "40")
    lines = [x for x in out.stdout.splitlines() if x.startswith(("to read", "DONE"))]
    print(f"round {n}", lines, out.stderr[-400:], flush=True)
    built = run("run.py")
    print("\n".join(x[:900] for x in built.stdout.splitlines() if not x.startswith("[")), built.stderr[-400:], flush=True)
    if any(x.startswith("to read: 0") for x in lines):
        break
print("LOOP DONE", flush=True)
