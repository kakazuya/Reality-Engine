"""Daily check for new free readers (STATE to-do 1, 2026-10-13). Run once a day by the resource watchdog; safe to run
by hand: python -m reality_engine.scripts.new_reader_check [--no-tests]

1. Lists the free models on OpenCode Zen (`opencode models`, account limited to free models), OpenCode Go (ids ending
   -free) and Kilo (isFree, zero price, or any pricing.discount) and diffs them against yesterday's list
   (reader_watch.json next to this file): new, gone, changed.
2. Zen models are the ones the AR run can use without code changes. A new Zen model not in the register
   (zen_models.json) gets the AR admission test started (ar_queue.py test-export + drive, detached). On the next run a
   finished test is scored: a pass is added to the register (3 slots) and the Zen AR worker is restarted to pick it up;
   a fail is recorded so it is never retested. A registered model missing from Zen is marked retired; back -> passed.
3. Go/Kilo changes are reported only (their readers need a MODELS entry and the API test harness; Claude decides).
Report: reality_engine/data/logs/reader_watch_report.md (appended to the watchdog report every session sees).
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import requests

from reality_engine.scripts import ar_queue
from reality_engine.scripts.resource_watchdog import user_env

HERE = Path(__file__).resolve().parent
WATCH = HERE / "reader_watch.json"
REGISTER = HERE / "zen_models.json"
REPORT = HERE.parent / "data" / "logs" / "reader_watch_report.md"
PY = sys.executable
SLOTS_NEW = 3


def now():
    return datetime.now().isoformat(timespec="seconds")


def zen_models():
    exe = ar_queue.opencode_exe()
    p = subprocess.run([exe, "models"], stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300)
    ids = [l.strip() for l in ar_queue.ANSI.sub("", p.stdout).splitlines() if l.strip().startswith("opencode/")]
    return {i.split("/", 1)[1]: {} for i in ids}


def go_models(env):
    r = requests.get("https://opencode.ai/zen/go/v1/models", timeout=60,
                     headers={"Authorization": f"Bearer {env.get('OPENCODE_GO_API_KEY', '')}"})
    return {m["id"]: {} for m in r.json().get("data", []) if m["id"].endswith("-free")}


def kilo_models(env):
    r = requests.get("https://api.kilo.ai/api/gateway/models", timeout=60,
                     headers={"Authorization": f"Bearer {env.get('KILO_API_KEY', '')}"})
    out = {}
    for m in r.json().get("data", []):
        pr = m.get("pricing") or {}
        free = m.get("isFree") or str(pr.get("prompt")) in ("0", "0.0") and str(pr.get("completion")) in ("0", "0.0")
        if free or pr.get("discount"):
            out[m["id"]] = {"free": bool(free), "discount": pr.get("discount"),
                            "image": "image" in (m.get("architecture") or {}).get("input_modalities", [])}
    return out


def slug(model):
    return re.sub(r"[^a-z0-9]+", "", model.replace("-free", "").replace("-preview", ""))[:16]


def load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def driving(run):
    """True while an `ar_queue drive` process has this run in its --run list."""
    import psutil
    for p in psutil.process_iter(["name", "cmdline"]):
        c = p.info["cmdline"] or []
        if "drive" in c and "--run" in c and run in c[c.index("--run") + 1].split(","):
            return True
    return False


def restart_zen_worker():
    import psutil
    for p in psutil.process_iter(["name", "cmdline"]):
        if (p.info["name"] or "").lower() == "python.exe" and "--route zen" in " ".join(p.info["cmdline"] or []):
            p.kill()   # run_ar_zen.cmd restarts it in 30 s with the new register
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-tests", action="store_true", help="report only; start no admission test")
    a = ap.parse_args()
    env = user_env()
    watch = load(WATCH, {"zen": {}, "go": {}, "kilo": {}, "tests": {}})
    reg = load(REGISTER, {})
    lines, errors = [], []
    seen = {}
    for src, fn in (("zen", zen_models), ("go", lambda: go_models(env)), ("kilo", lambda: kilo_models(env))):
        try:
            seen[src] = fn()
        except Exception as e:
            errors.append(f"{src}: list failed ({str(e)[:120]})")
    for src, cur in seen.items():
        old = watch.get(src, {})
        new = sorted(set(cur) - set(old)); gone = sorted(set(old) - set(cur))
        changed = sorted(m for m in set(cur) & set(old) if cur[m] != old[m].get("info", {}))
        if old and (new or gone or changed):
            lines.append(f"- **{src}**: new {new or '-'}; gone {gone or '-'}; changed {changed or '-'}")
        for m in cur:
            watch.setdefault(src, {}).setdefault(m, {"first_seen": now()})
            watch[src][m].update(last_seen=now(), info=cur[m])
        for m in gone:
            watch[src].pop(m, None)

    # register upkeep and admission tests (Zen only)
    zen = seen.get("zen")
    if zen is not None:
        for m, v in reg.items():
            if m.startswith("_") or not isinstance(v, dict):
                continue
            if v.get("status") == "passed" and m not in zen:
                v["status"] = "retired"; v["retired"] = now(); lines.append(f"- register: **{m} retired** (gone from Zen)")
            elif v.get("status") == "retired" and m in zen:
                v["status"] = "passed"; lines.append(f"- register: **{m} back** on Zen, in use again")
        added = False
        for m, t in list(watch["tests"].items()):   # score finished tests
            if t.get("result"):
                continue
            run_dir = ar_queue.QUEUE / t["run"]
            n_out = len(list(run_dir.glob("*.out.txt"))); n_all = len(list(run_dir.glob("*.prompt.txt")))
            if driving(t["run"]):
                lines.append(f"- test {m}: running, {n_out}/{n_all} pieces"); continue
            ar_queue.test_score(t["run"])
            score = (run_dir / "SCORE.md").read_text(encoding="utf-8")
            mf = re.search(r"Must-find (\d+)/(\d+)", score); nf = re.search(r"not in the text (\d+)/(\d+)", score)
            fx = re.search(r"Facts extracted (\d+)", score)
            ok = (mf and mf.group(1) == mf.group(2) and nf and int(nf.group(1)) < 0.01 * max(1, int(nf.group(2)))
                  and n_out == n_all and fx and int(fx.group(1)) >= ar_queue.DEPTH_MIN)
            t["result"] = "pass" if ok else "fail"; t["scored"] = now()
            line = score.splitlines()[2] if len(score.splitlines()) > 2 else ""
            if ok:
                reg[m] = {"slots": SLOTS_NEW, "status": "passed", "ar_test": f"{now()[:16]} auto: {line}"}
                added = True
            else:
                reg[m] = {"slots": 0, "status": "failed", "ar_test": f"{now()[:16]} auto: {line}; answered {n_out}/{n_all}"}
            lines.append(f"- test {m}: **{t['result'].upper()}** ({line})")
        for m in zen:   # start tests for unregistered models
            if m in reg or m in watch["tests"] or a.no_tests:
                continue
            run = f"t-{slug(m)}-{datetime.now():%m%d}"
            try:
                ar_queue.test_export(run, m)
            except SystemExit:
                pass
            subprocess.Popen([PY, "-m", "reality_engine.scripts.ar_queue", "drive", "--run", run, "--workers", "1"],
                             cwd=HERE.parents[1], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
            watch["tests"][m] = {"run": run, "started": now()}
            lines.append(f"- test {m}: **started** (run {run})")
        REGISTER.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")
        if added and restart_zen_worker():
            lines.append("- Zen AR worker restarted with the new register")
    WATCH.write_text(json.dumps(watch, indent=1) + "\n", encoding="utf-8")
    for m, v in reg.items():   # promotions end: warn ahead (dates from OpenCode's announcements, see promo_source)
        if isinstance(v, dict) and v.get("free_until") and v.get("status") in ("passed", "untested"):
            days = (datetime.fromisoformat(v["free_until"]) - datetime.now()).days
            if days <= 2:
                lines.append(f"- **promo ending**: {m} free until {v['free_until']} ({'past' if days < 0 else f'{days} d left'})")
    passed = [m for m, v in reg.items() if isinstance(v, dict) and v.get("status") == "passed"]
    out = [f"## New-reader check ({now()[:16]})", f"- Zen readers in use (register): {', '.join(passed)}"]
    out += lines or ["- no changes since the last check"]
    out += [f"- ERROR {e}" for e in errors]
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
